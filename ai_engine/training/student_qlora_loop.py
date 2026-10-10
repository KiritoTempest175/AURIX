"""LUNA Student-5B Continuous QLoRA Training Engine (v0.4.1).

Gemma 4 E4B acts as both the live assistant and the source of general-purpose training data;
the student model is expected to be broadly competent, with the user's own real interactions
contributing a smaller personalization layer on top.

Trains the student model using a balanced mix of general-purpose synthetic distillation (70%)
and live user interaction traces (30%) via 4-bit NF4 QLoRA, paged 8-bit optimizer states,
rank auto-scaling, experience replay, and adaptive power-state governor awareness.
"""

from __future__ import annotations

import gc
import logging
import os
import subprocess
import sys
from pathlib import Path
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from ai_engine.training.checkpoint_manager import (
    CheckpointManager,
    CheckpointManifest,
    get_default_checkpoint_manager,
)
from ai_engine.training.synthetic_generator import GeneralSyntheticDataGenerator

logger = logging.getLogger("luna.ai_engine.student_training")

try:
    import torch
    from transformers import TrainerCallback, TrainerControl, TrainerState, TrainingArguments
    TORCH_AVAILABLE = True
except ImportError:
    torch = None
    TrainerCallback = object
    TORCH_AVAILABLE = False

FastLanguageModel = None
UNSLOTH_AVAILABLE = False


def get_unsloth_backend():
    """
    Lazily load Unsloth only on a CUDA-capable machine.

    Importing Unsloth on CPU-only PyTorch can raise AssertionError or
    RuntimeError during module import, which previously broke pytest
    collection and application startup.
    """
    global FastLanguageModel, UNSLOTH_AVAILABLE

    if FastLanguageModel is not None:
        return FastLanguageModel

    if not TORCH_AVAILABLE or torch is None:
        return None

    try:
        if not torch.cuda.is_available():
            return None
    except Exception as exc:
        logger.warning(
            "CUDA detection failed; Unsloth disabled: %s",
            exc,
        )
        return None

    try:
        from unsloth import FastLanguageModel as _FastLanguageModel

        FastLanguageModel = _FastLanguageModel
        UNSLOTH_AVAILABLE = True

        return FastLanguageModel

    except Exception as exc:
        logger.warning(
            "Optional Unsloth training backend unavailable: %s",
            exc,
        )

        FastLanguageModel = None
        UNSLOTH_AVAILABLE = False

        return None

try:
    from trl import SFTTrainer
    TRL_AVAILABLE = True
except ImportError:
    SFTTrainer = None
    TRL_AVAILABLE = False


class LunaGovernorCallback(TrainerCallback if TORCH_AVAILABLE else object):
    """Callback monitoring LUNA Governor PowerState and hardware ceilings during SFT steps."""

    def __init__(
        self,
        checkpoint_manager: CheckpointManager,
        check_suspended_fn: Optional[Callable[[], bool]] = None,
        get_power_state_fn: Optional[Callable[[], int]] = None,
    ) -> None:
        self.checkpoint_manager = checkpoint_manager
        self.check_suspended_fn = check_suspended_fn or (lambda: False)
        self.get_power_state_fn = get_power_state_fn or (lambda: 0)

    def on_step_end(self, args: Any, state: Any, control: Any, **kwargs: Any) -> Any:
        """Check hardware governor flags at the end of each training step."""
        power_state = self.get_power_state_fn()

        # 1. OS Shutdown / Suspend Signal (State 3 = Suspending)
        if power_state == 3:
            logger.critical("LUNA Governor signaled OS SUSPENDING. Saving emergency checkpoint immediately...")
            self._save_emergency_checkpoint(kwargs.get("model"), state.global_step, kwargs.get("optimizer"))
            control.should_training_stop = True
            return control

        # 2. Hardware Ceiling Overload
        if self.check_suspended_fn():
            logger.warning("LUNA Governor signaled HARDWARE LIMIT BREACH. Pausing training and purging VRAM...")
            self._save_emergency_checkpoint(kwargs.get("model"), state.global_step, kwargs.get("optimizer"))
            if torch and torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()

            # Spin-lock until governor clears suspension
            while self.check_suspended_fn():
                time.sleep(1.0)
            logger.info("Hardware resources nominal. Resuming QLoRA training.")

        return control

    def _save_emergency_checkpoint(self, model: Any, step: int, optimizer: Any = None) -> None:
        """Serialize adapter weights and training extra_state, then persist through CheckpointManager."""
        try:
            if model is not None and hasattr(model, "state_dict"):
                import io
                buf = io.BytesIO()
                torch.save(model.state_dict(), buf)

                extra_state: Dict[str, Any] = {}
                if optimizer is not None and hasattr(optimizer, "state_dict"):
                    extra_state["optimizer_state"] = optimizer.state_dict()
                if TORCH_AVAILABLE and torch is not None:
                    try:
                        extra_state["rng_state"] = torch.random.get_rng_state().tolist()
                    except Exception:
                        pass

                self.checkpoint_manager.save_checkpoint(
                    weights_data=buf.getvalue(),
                    step_count=step,
                    dataset_version_hash="telemetry_live",
                    lora_rank=16,
                    extra_state=extra_state if extra_state else None,
                )
        except Exception as e:
            logger.error(f"Failed to persist emergency checkpoint: {e}")


class StudentTrainingController:
    """Thread-safe controller to start, stop, and inspect the continuous Student-5B training process."""

    def __init__(
        self,
        base_model_name: str = "google/gemma-4-E4B-it",
        checkpoint_dir: str = "checkpoints/luna-student",
        active_lora_rank: int = 16,
        idle_lora_rank: int = 32,
        live_interaction_weight: float = 0.3,
        synthetic_general_weight: float = 0.7,
        get_power_state_fn: Optional[Callable[[], int]] = None,
        synthetic_generator: Optional[GeneralSyntheticDataGenerator] = None,
    ) -> None:
        self.base_model_name = base_model_name
        self.checkpoint_dir = checkpoint_dir
        self.active_lora_rank = active_lora_rank
        self.idle_lora_rank = idle_lora_rank
        self.live_interaction_weight = live_interaction_weight
        self.synthetic_general_weight = synthetic_general_weight

        # Governor power state query (queries live SystemState, fails closed to 0/ACTIVE if unavailable)
        if get_power_state_fn is not None:
            self.get_power_state_fn = get_power_state_fn
        else:
            def _default_power_query() -> int:
                try:
                    from core_engine import SystemState
                    return SystemState().get_power_state()
                except Exception:
                    return 0  # ACTIVE (fail closed)
            self.get_power_state_fn = _default_power_query

        self.synthetic_generator = synthetic_generator or GeneralSyntheticDataGenerator(
            get_power_state_fn=self.get_power_state_fn
        )

        self.checkpoint_manager = CheckpointManager(checkpoint_dir=checkpoint_dir)
        self._is_training_running = False
        self._stop_requested = threading.Event()
        self._training_thread: Optional[threading.Thread] = None

        self.current_step = 0
        self.current_rank = active_lora_rank
        self.current_loss = None  # Only an actual training callback may report loss.
        self.last_error: Optional[str] = None
        self.last_exit_code: Optional[int] = None
        self._training_process: Optional[subprocess.Popen] = None

    @property
    def is_running(self) -> bool:
        return self._is_training_running

    def start_training(self) -> bool:
        """Launch the *real* QLoRA trainer; refuse if preconditions are missing.

        No synthetic progress, mock weights, or simulated evaluation losses.
        A runner can be launched only on an idle workstation with CUDA.
        """
        if self._is_training_running:
            self.last_error = "Training is already running"
            return False
        if self.get_power_state_fn() not in (1, 2):
            self.last_error = "Training requires confirmed IDLE or LOCKED state"
            return False
        try:
            import psutil
            battery = psutil.sensors_battery()
            if battery is not None and not battery.power_plugged:
                self.last_error = "Training requires external power"
                return False
        except ImportError:
            self.last_error = "Cannot confirm system power state without psutil"
            return False

        if not TORCH_AVAILABLE or torch is None or not torch.cuda.is_available():
            self.last_error = "Training requires a CUDA-capable GPU"
            return False
        if get_unsloth_backend() is None or not TRL_AVAILABLE:
            self.last_error = "Unsloth and TRL training backends must be installed"
            return False
        project_root = Path(__file__).resolve().parents[2]
        dataset = project_root / "data_pipeline/storage/telemetry.jsonl"
        if not dataset.is_file() or dataset.stat().st_size == 0:
            self.last_error = "No non-empty training dataset is available"
            return False

        self._stop_requested.clear()
        self.last_error = None
        self.last_exit_code = None
        # Offline flags protect against unrequested model downloads.
        env = os.environ.copy()
        env.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
        try:
            self._training_process = subprocess.Popen(
                [sys.executable, "-m", "ai_engine.training.qlora_loop"],
                cwd=str(project_root),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            self.last_error = f"Unable to start local training process: {type(exc).__name__}"
            return False
        self._is_training_running = True
        self._training_thread = threading.Thread(
            target=self._run_training_worker, daemon=True, name="LunaStudentTrainerMonitor"
        )
        self._training_thread.start()
        return True

    def stop_training(self) -> bool:
        """Terminate the owned local training worker and wait for exit."""
        process = self._training_process
        if not self._is_training_running or process is None:
            return False
        self._stop_requested.set()
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        self.last_exit_code = process.returncode
        self._is_training_running = False
        return True

    def resume_from_latest_checkpoint(
        self, model: Any = None, optimizer: Any = None
    ) -> Optional[CheckpointManifest]:
        """Restore model weights, optimizer state, and RNG state from the latest valid checkpoint."""
        loaded = self.checkpoint_manager.load_latest_checkpoint()
        if loaded is None:
            logger.info("No checkpoint found to resume.")
            return None

        weights_bytes, manifest, extra_state = loaded
        self.current_step = manifest.step_count
        self.current_rank = manifest.lora_rank
        if manifest.eval_loss is not None:
            self.current_loss = manifest.eval_loss

        # Apply weights to model if provided
        if model is not None and TORCH_AVAILABLE and torch is not None:
            import io
            buf = io.BytesIO(weights_bytes)
            state_dict = torch.load(buf, map_location="cpu")
            if hasattr(model, "load_state_dict"):
                model.load_state_dict(state_dict)

        # Restore optimizer and RNG extra state
        if extra_state:
            if optimizer is not None and "optimizer_state" in extra_state:
                if hasattr(optimizer, "load_state_dict"):
                    try:
                        optimizer.load_state_dict(extra_state["optimizer_state"])
                        logger.info("Successfully restored optimizer state dict.")
                    except Exception as e:
                        logger.warning(f"Failed to restore optimizer state: {e}")
            if "rng_state" in extra_state and TORCH_AVAILABLE and torch is not None:
                try:
                    rng_bytes = torch.ByteTensor(extra_state["rng_state"])
                    torch.random.set_rng_state(rng_bytes)
                    logger.info("Successfully restored PyTorch RNG state.")
                except Exception as e:
                    logger.warning(f"Could not restore RNG state: {e}")

        logger.info(f"Resumed training state from checkpoint '{manifest.checkpoint_id}' (Step {manifest.step_count})")
        return manifest

    def get_status(self) -> Dict[str, Any]:
        """Report only observable training state; no invented progress."""
        return {
            "is_running": self._is_training_running,
            "current_step": None,
            "active_rank": None,
            "current_loss": None,
            "last_error": self.last_error,
            "last_exit_code": self.last_exit_code,
            "checkpoint_dir": str(self.checkpoint_dir),
            "model_name": self.base_model_name,
            "live_interaction_weight": self.live_interaction_weight,
            "synthetic_general_weight": self.synthetic_general_weight,
        }

    def _run_training_worker(self) -> None:
        """Monitor the actual subprocess; never simulate a training step."""
        process = self._training_process
        if process is None:
            self._is_training_running = False
            self.last_error = "Training process was not launched"
            return
        self.last_exit_code = process.wait()
        if self.last_exit_code != 0 and not self._stop_requested.is_set():
            self.last_error = f"QLoRA process exited with code {self.last_exit_code}"
        self._is_training_running = False


_GLOBAL_TRAINER: Optional[StudentTrainingController] = None


def get_default_student_trainer() -> StudentTrainingController:
    """Return default singleton StudentTrainingController."""
    global _GLOBAL_TRAINER
    if _GLOBAL_TRAINER is None:
        _GLOBAL_TRAINER = StudentTrainingController()
    return _GLOBAL_TRAINER
