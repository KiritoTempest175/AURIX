"""LUNA Versioned Checkpoint & State Hibernation Manager.

Implements atomic, encrypted checkpoint persistence and rollback for Luna-Student-5B
during training, idle-lock, and OS shutdown/hibernation events.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from security.encryption import CheckpointEncryptor, get_default_encryptor

logger = logging.getLogger("luna.ai_engine.checkpoint_manager")


@dataclass
class CheckpointManifest:
    """Metadata manifest describing a saved training checkpoint."""
    checkpoint_id: str
    timestamp: float
    iso_time: str
    step_count: int
    eval_loss: Optional[float]
    dataset_version_hash: str
    model_architecture: str
    lora_rank: int
    lora_alpha: int
    is_encrypted: bool
    weights_sha256: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CheckpointManifest:
        return cls(**data)


class CheckpointManager:
    """Manages versioned, encrypted model checkpoints with atomic pointer updates and rollback."""

    def __init__(
        self,
        checkpoint_dir: Union[str, Path] = "checkpoints/luna-student",
        max_retained: int = 5,
        encrypt_at_rest: bool = True,
        encryptor: Optional[CheckpointEncryptor] = None,
    ) -> None:
        """Initialize CheckpointManager.

        Args:
            checkpoint_dir: Base directory for storing versioned checkpoints.
            max_retained: Maximum number of historical checkpoints to retain.
            encrypt_at_rest: Whether to encrypt weights and optimizer states at rest.
            encryptor: CheckpointEncryptor instance.
        """
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.max_retained = max(3, max_retained)
        self.encrypt_at_rest = encrypt_at_rest
        self.encryptor = encryptor or get_default_encryptor()
        self.pointer_file = self.checkpoint_dir / "latest_checkpoint.json"

    @staticmethod
    def calculate_file_hash(path: Path) -> str:
        """Calculate SHA-256 hash of a file."""
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    def save_checkpoint(
        self,
        weights_data: bytes,
        step_count: int,
        dataset_version_hash: str,
        lora_rank: int = 16,
        lora_alpha: int = 32,
        eval_loss: Optional[float] = None,
        extra_state: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """Atomically persist a versioned checkpoint to disk with manifest and encryption.

        Args:
            weights_data: Serialized LoRA adapter weights / state dict.
            step_count: Current training step.
            dataset_version_hash: Hash of current training dataset state.
            lora_rank: Active LoRA rank used.
            lora_alpha: Active LoRA alpha used.
            eval_loss: Optional validation loss metric.
            extra_state: Optional optimizer or RNG state dictionary.

        Returns:
            Path to the saved checkpoint directory.
        """
        raw_hash = hashlib.sha256(weights_data).hexdigest()[:12]
        now = time.time()
        iso_str = time.strftime("%Y%m%d_%H%M%S", time.gmtime(now))
        ckpt_id = f"ckpt_{iso_str}_{raw_hash}"
        ckpt_dir = self.checkpoint_dir / ckpt_id
        ckpt_dir.mkdir(parents=True, exist_ok=True)

        weights_file = ckpt_dir / "adapter_model.bin"
        if self.encrypt_at_rest:
            encrypted_weights = self.encryptor.encrypt_bytes(
                weights_data, associated_data=ckpt_id.encode("utf-8")
            )
            weights_file.write_bytes(encrypted_weights)
        else:
            weights_file.write_bytes(weights_data)

        # Save extra state (optimizer/RNG) if provided
        if extra_state:
            state_file = ckpt_dir / "training_state.json"
            if self.encrypt_at_rest:
                enc_state = self.encryptor.encrypt_json(extra_state)
                state_file.write_text(enc_state, encoding="utf-8")
            else:
                state_file.write_text(json.dumps(extra_state, indent=2), encoding="utf-8")

        # Create Manifest
        final_hash = self.calculate_file_hash(weights_file)
        manifest = CheckpointManifest(
            checkpoint_id=ckpt_id,
            timestamp=now,
            iso_time=iso_str,
            step_count=step_count,
            eval_loss=eval_loss,
            dataset_version_hash=dataset_version_hash,
            model_architecture="Luna-Student-5B-QLoRA",
            lora_rank=lora_rank,
            lora_alpha=lora_alpha,
            is_encrypted=self.encrypt_at_rest,
            weights_sha256=final_hash,
        )

        manifest_file = ckpt_dir / "manifest.json"
        manifest_file.write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")

        # Atomically update pointer file
        self._update_pointer_atomic(manifest)

        # Prune old checkpoints beyond max_retained
        self._prune_historical_checkpoints()

        logger.info(f"Successfully persisted checkpoint '{ckpt_id}' (Step {step_count})")
        return ckpt_dir

    def _update_pointer_atomic(self, manifest: CheckpointManifest) -> None:
        """Write latest_checkpoint.json atomically via temporary file and rename."""
        temp_pointer = self.checkpoint_dir / "latest_checkpoint.json.tmp"
        payload = {
            "latest_checkpoint_id": manifest.checkpoint_id,
            "timestamp": manifest.timestamp,
            "step_count": manifest.step_count,
            "manifest_path": str(self.checkpoint_dir / manifest.checkpoint_id / "manifest.json"),
        }
        with open(temp_pointer, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())

        # Atomic replace
        os.replace(temp_pointer, self.pointer_file)

    def load_latest_checkpoint(self) -> Optional[Tuple[bytes, CheckpointManifest]]:
        """Load and verify the latest checkpoint. Automatically rolls back if corrupted.

        Returns:
            Tuple of (decrypted_weights_bytes, manifest) or None if no checkpoints exist.
        """
        if not self.pointer_file.exists():
            logger.info("No latest_checkpoint.json pointer found. Initializing from baseline.")
            return None

        try:
            pointer = json.loads(self.pointer_file.read_text(encoding="utf-8"))
            latest_id = pointer.get("latest_checkpoint_id")
            if not latest_id:
                return self._rollback_to_previous()

            ckpt_dir = self.checkpoint_dir / latest_id
            return self._load_and_verify_dir(ckpt_dir)
        except Exception as e:
            logger.error(f"Failed to load latest checkpoint: {e}. Initiating automatic rollback.")
            return self._rollback_to_previous()

    def _load_and_verify_dir(self, ckpt_dir: Path) -> Optional[Tuple[bytes, CheckpointManifest]]:
        """Verify hash and decrypt checkpoint from directory."""
        if not ckpt_dir.exists():
            raise FileNotFoundError(f"Checkpoint directory {ckpt_dir} does not exist")

        manifest_file = ckpt_dir / "manifest.json"
        weights_file = ckpt_dir / "adapter_model.bin"

        if not manifest_file.exists() or not weights_file.exists():
            raise ValueError(f"Missing manifest or weights in {ckpt_dir}")

        manifest = CheckpointManifest.from_dict(json.loads(manifest_file.read_text(encoding="utf-8")))

        # Verify integrity hash
        actual_hash = self.calculate_file_hash(weights_file)
        if actual_hash != manifest.weights_sha256:
            raise ValueError(
                f"Integrity check failed for {manifest.checkpoint_id}: expected {manifest.weights_sha256}, got {actual_hash}"
            )

        raw_payload = weights_file.read_bytes()
        if manifest.is_encrypted:
            weights = self.encryptor.decrypt_bytes(
                raw_payload, associated_data=manifest.checkpoint_id.encode("utf-8")
            )
        else:
            weights = raw_payload

        return weights, manifest

    def _rollback_to_previous(self) -> Optional[Tuple[bytes, CheckpointManifest]]:
        """Rollback to the most recent valid historical checkpoint."""
        history = self.list_checkpoints()
        for ckpt_meta in history:
            ckpt_dir = self.checkpoint_dir / ckpt_meta["checkpoint_id"]
            try:
                result = self._load_and_verify_dir(ckpt_dir)
                if result is not None:
                    _, manifest = result
                    logger.warning(f"Rolled back to valid checkpoint '{manifest.checkpoint_id}'")
                    self._update_pointer_atomic(manifest)
                    return result
            except Exception as e:
                logger.warning(f"Checkpoint {ckpt_dir.name} is invalid ({e}), checking next...")

        logger.error("All historical checkpoints failed verification. Resetting to baseline.")
        return None

    def list_checkpoints(self) -> List[Dict[str, Any]]:
        """Return a reverse-chronological list of available checkpoints."""
        checkpoints: List[Dict[str, Any]] = []
        for item in sorted(self.checkpoint_dir.glob("ckpt_*"), reverse=True):
            if item.is_dir():
                manifest_file = item / "manifest.json"
                if manifest_file.exists():
                    try:
                        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                        checkpoints.append(manifest)
                    except Exception:
                        pass
        return checkpoints

    def _prune_historical_checkpoints(self) -> None:
        """Keep only the latest N checkpoints."""
        all_ckpts = sorted(self.checkpoint_dir.glob("ckpt_*"), reverse=True)
        if len(all_ckpts) > self.max_retained:
            for old_ckpt in all_ckpts[self.max_retained:]:
                try:
                    shutil.rmtree(old_ckpt)
                    logger.debug(f"Pruned historical checkpoint {old_ckpt.name}")
                except Exception as e:
                    logger.warning(f"Failed to prune {old_ckpt}: {e}")


_GLOBAL_CHECKPOINT_MANAGER: Optional[CheckpointManager] = None


def get_default_checkpoint_manager() -> CheckpointManager:
    """Return default singleton CheckpointManager."""
    global _GLOBAL_CHECKPOINT_MANAGER
    if _GLOBAL_CHECKPOINT_MANAGER is None:
        _GLOBAL_CHECKPOINT_MANAGER = CheckpointManager()
    return _GLOBAL_CHECKPOINT_MANAGER
