"""LUNA Desktop Executive — Native UI Controller.

Integrates Slint 1.8 GUI with the Gemma 3n E4B inference brain, Student-5B QLoRA
training engine, Checkpoint Manager, Wake-Word Detector, and Hardware Power Governor.
"""

from __future__ import annotations

import datetime
import logging
import os
import queue
import sys
import threading
import time
from typing import Any, Dict, List

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure project root is in python path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import psutil
import slint

from ai_engine.inference.gemma_e4b import get_default_gemma_runner
from ai_engine.training.checkpoint_manager import get_default_checkpoint_manager
from ai_engine.training.student_qlora_loop import get_default_student_trainer
from data_pipeline.storage.telemetry_daemon import get_default_telemetry_daemon
from native_ui.audio.wakeword_detector import get_default_wakeword_detector

try:
    import core_engine
    HAS_RUST_CORE = True
except ImportError:
    core_engine = None
    HAS_RUST_CORE = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("luna.native_ui.run_ui")


class LunaController:
    """Bridges LUNA subsystems (AI inference, student training, security, governor) to Slint GUI."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.start_time = time.time()
        self.cmd_count = 0
        self.response_queue: queue.Queue[tuple[str, str]] = queue.Queue()

        # 1. Initialize Subsystems
        logger.info("Initializing Gemma 3n E4B Inference Engine...")
        self.gemma_runner = get_default_gemma_runner()

        logger.info("Initializing Student-5B Training Controller...")
        self.student_trainer = get_default_student_trainer()

        logger.info("Initializing Checkpoint Manager...")
        self.checkpoint_manager = get_default_checkpoint_manager()

        logger.info("Initializing Telemetry Ingestion Daemon...")
        self.telemetry = get_default_telemetry_daemon()

        logger.info("Initializing Wake-Word Detector ('Luna')...")
        self.wakeword = get_default_wakeword_detector()
        self.wakeword.on_wake_detected = self._handle_wakeword_triggered
        self.wakeword.start_listening()

        # 2. Rust Core Engine State
        self.system_state = core_engine.SystemState() if HAS_RUST_CORE else None
        if HAS_RUST_CORE:
            try:
                core_engine.start_hardware_monitor()
                logger.info("Rust Hardware Power Governor started.")
            except Exception as e:
                logger.warning(f"Could not spawn hardware monitor thread: {e}")

        # 3. Bind UI Callbacks
        self._bind_callbacks()

        # 4. Start 1-second Telemetry Timer
        self.timer = slint.Timer()
        self.timer.start(
            slint.TimerMode.Repeated,
            datetime.timedelta(seconds=1),
            self._update_telemetry,
        )

        # 5. Start 100ms Queue Poll Timer for AI Responses
        self.poll_timer = slint.Timer()
        self.poll_timer.start(
            slint.TimerMode.Repeated,
            datetime.timedelta(milliseconds=100),
            self._poll_response_queue,
        )

        logger.info("✅ [LUNA Controller] All backend subsystems integrated with Frontend UI!")

    def _bind_callbacks(self) -> None:
        """Binds Slint GUI events to Python handlers."""
        self.app.send_message = self._handle_send_message
        self.app.toggle_training = self._handle_toggle_training
        self.app.open_checkpoint_browser = self._handle_open_checkpoint_browser
        self.app.restore_checkpoint = self._handle_restore_checkpoint
        self.app.clear_conversation = self._handle_clear_conversation
        self.app.export_conversation = self._handle_export_conversation
        self.app.review_approve = self._handle_review_approve
        self.app.review_reject = self._handle_review_reject
        self.app.alert_retry = self._handle_alert_retry
        self.app.alert_cancel = self._handle_alert_cancel
        self.app.alert_close = self._handle_alert_close

    def _get_time_str(self) -> str:
        return datetime.datetime.now().strftime("%H:%M:%S")

    def _handle_send_message(self, text: str) -> None:
        if not text.strip():
            return

        now_str = self._get_time_str()
        self.cmd_count += 1

        # 1. Update UI with User Message
        current_msgs = list(self.app.messages)
        current_msgs.append({"sender": "USER", "text": text, "time": now_str})
        self.app.messages = slint.ListModel(current_msgs)

        # 2. Ingest into telemetry (with secret scrubbing)
        try:
            self.telemetry.ingest_execution_log(
                session_id="luna_gui_session",
                action_type="USER_COMMAND",
                target_command=text,
                status="EXECUTING",
                return_code=0,
            )
        except Exception as e:
            logger.error(f"Telemetry log failed: {e}")

        # 3. Dispatch Async Inference with Gemma 3n E4B
        def generate_job():
            try:
                formatted_prompt = self.gemma_runner.format_chat_prompt(user_message=text)
                reply = self.gemma_runner.generate_response(formatted_prompt)
            except Exception as err:
                reply = f"[Error]: {err}"
            self.response_queue.put((reply, self._get_time_str()))

        threading.Thread(target=generate_job, daemon=True, name="GemmaInferenceThread").start()

    def _poll_response_queue(self) -> None:
        """Polls queue for async AI response and appends to Slint UI model."""
        while not self.response_queue.empty():
            reply_text, timestamp = self.response_queue.get_nowait()
            current_msgs = list(self.app.messages)
            current_msgs.append({"sender": "LUNA", "text": reply_text, "time": timestamp})
            self.app.messages = slint.ListModel(current_msgs)

    def _handle_wakeword_triggered(self, confirmation: str) -> None:
        """Triggered when offline wake-word detector spots 'Luna'."""
        logger.info(f"Wake-Word Event: {confirmation}")
        self.app.toast_message = f"Luna awake: '{confirmation}'"
        self.app.toast_visible = True

    def _handle_toggle_training(self) -> None:
        """User clicked Start / Stop Continuous Training toggle button."""
        if self.student_trainer.is_running:
            self.student_trainer.stop_training()
            self.app.training_running = False
            self.app.toast_message = "Student-5B training stopped."
        else:
            self.student_trainer.start_training()
            self.app.training_running = True
            self.app.toast_message = "Student-5B continuous training active!"
        self.app.toast_visible = True

    def _handle_open_checkpoint_browser(self) -> None:
        """Opens checkpoint browser modal populated with saved checkpoints."""
        checkpoints_meta = self.checkpoint_manager.list_checkpoints()
        ckpt_entries = []
        for ckpt in checkpoints_meta:
            ckpt_entries.append({
                "checkpoint_id": str(ckpt.get("checkpoint_id", "")),
                "iso_time": str(ckpt.get("iso_time", "")),
                "step_count": int(ckpt.get("step_count", 0)),
                "eval_loss": f"{ckpt.get('eval_loss', 0.0):.4f}" if ckpt.get("eval_loss") else "N/A",
                "lora_rank": int(ckpt.get("lora_rank", 16)),
            })
        self.app.checkpoints = slint.ListModel(ckpt_entries)
        self.app.checkpoint_browser_visible = True

    def _handle_restore_checkpoint(self, checkpoint_id: str) -> None:
        """Restores a versioned checkpoint by ID."""
        logger.info(f"Restoring checkpoint '{checkpoint_id}'...")
        try:
            self.checkpoint_manager.load_checkpoint(checkpoint_id)
            self.app.toast_message = f"Restored Checkpoint: {checkpoint_id}"
            self.app.toast_visible = True
            logger.info(f"Successfully restored checkpoint '{checkpoint_id}'")
        except Exception as e:
            logger.error(f"Failed to restore checkpoint '{checkpoint_id}': {e}")
            self.app.toast_message = f"Restore Failed: {e}"
            self.app.toast_visible = True

    def _handle_clear_conversation(self) -> None:
        welcome = {
            "sender": "LUNA",
            "text": "LUNA Executive initialized. Ready for voice or command instructions.",
            "time": self._get_time_str(),
        }
        self.app.messages = slint.ListModel([welcome])
        self.app.toast_message = "Conversation history cleared."
        self.app.toast_visible = True

    def _handle_export_conversation(self) -> None:
        try:
            log_path = os.path.join(ROOT_DIR, "data", "logs", "luna_chat_export.txt")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "w", encoding="utf-8") as f:
                for msg in list(self.app.messages):
                    f.write(f"[{msg.time}] {msg.sender}: {msg.text}\n")
            self.app.toast_message = f"Saved conversation to {log_path}"
            self.app.toast_visible = True
        except Exception as e:
            self.app.toast_message = f"Export failed: {e}"
            self.app.toast_visible = True

    def _handle_review_approve(self) -> None:
        logger.info("✔ [Trust Token] Action Approved by Operator")
        self.app.toast_message = "Trust Token Authorization Granted"
        self.app.toast_visible = True

    def _handle_review_reject(self) -> None:
        logger.info("❌ [Trust Token] Action Rejected by Operator")
        self.app.toast_message = "Directive Rejected"
        self.app.toast_visible = True

    def _handle_alert_retry(self) -> None:
        logger.info("🔄 [Self-Healing] Retry Action Initiated")

    def _handle_alert_cancel(self) -> None:
        logger.info("⏹ [Self-Healing] Action Cancelled")

    def _handle_alert_close(self) -> None:
        logger.info("ℹ [Self-Healing] Alert Modal Closed")

    def _update_telemetry(self) -> None:
        """Updates real-time system metrics (CPU, RAM, VRAM, Power State, Training) on Slint UI."""
        now = datetime.datetime.now()
        self.app.live_time = now.strftime("%H:%M:%S")

        # Query Power State
        if self.system_state:
            power_state_str = self.system_state.get_power_state_name()
        else:
            power_state_str = "ACTIVE"
        self.app.power_state = power_state_str

        # Update Training Status
        training_status = self.student_trainer.get_status()
        self.app.training_step = training_status["current_step"]
        self.app.training_rank = training_status["active_rank"]
        self.app.training_loss = f"{training_status['current_loss']:.4f}"

        # Real Hardware Metrics
        try:
            cpu_pct = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()

            ram_used_gb = mem.used / (1024 ** 3)
            ram_total_gb = mem.total / (1024 ** 3)

            self.app.cpu_usage = cpu_pct / 100.0
            self.app.cpu_display = f"{int(cpu_pct)}%"

            self.app.ram_usage = mem.percent / 100.0
            self.app.ram_display = f"{ram_used_gb:.1f} / 12.0 GB"

            # Save frame to SQLite telemetry DB
            self.telemetry.ingest_hardware_metrics(
                ram_gb=round(ram_used_gb, 2),
                vram_gb=0.0,
                power_state=power_state_str,
                training_state="RUNNING" if self.student_trainer.is_running else "STOPPED",
            )
        except Exception:
            pass


def main() -> None:
    slint_file = os.path.join(os.path.dirname(__file__), "ui", "main.slint")
    logger.info(f"Loading Slint UI from {slint_file}...")
    ui = slint.load_file(slint_file)
    app = ui.AurixCommandCenter()

    LunaController(app)

    logger.info("🚀 Launching LUNA Command Center GUI...")
    app.run()


if __name__ == "__main__":
    main()
