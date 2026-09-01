"""Unit tests for CheckpointManager: atomic persistence, encryption, and rollback."""

import os
import shutil
import tempfile
from contextlib import contextmanager
from ai_engine.training.checkpoint_manager import CheckpointManager
from security.encryption import CheckpointEncryptor


@contextmanager
def get_temp_ckpt_dir():
    temp_dir = tempfile.mkdtemp(prefix="luna_test_ckpts_")
    try:
        yield temp_dir
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


def test_checkpoint_save_and_load_roundtrip(temp_dir: str):
    encryptor = CheckpointEncryptor(key=b"0" * 32)
    manager = CheckpointManager(checkpoint_dir=temp_dir, encrypt_at_rest=True, encryptor=encryptor)

    fake_weights = b"TENSOR_WEIGHTS_BINARY_PAYLOAD_STEP_10"
    ckpt_path = manager.save_checkpoint(
        weights_data=fake_weights,
        step_count=10,
        dataset_version_hash="data_v1_hash",
        lora_rank=16,
        lora_alpha=32,
        eval_loss=0.45,
    )
    assert os.path.exists(ckpt_path)

    # Load latest checkpoint
    loaded = manager.load_latest_checkpoint()
    assert loaded is not None
    loaded_weights, manifest = loaded
    assert loaded_weights == fake_weights
    assert manifest.step_count == 10
    assert manifest.lora_rank == 16
    assert manifest.eval_loss == 0.45
    assert manifest.is_encrypted is True


def test_checkpoint_automatic_rollback_on_corruption(temp_dir: str):
    encryptor = CheckpointEncryptor(key=b"1" * 32)
    manager = CheckpointManager(checkpoint_dir=temp_dir, encrypt_at_rest=True, encryptor=encryptor)

    # Save Step 1
    weights_v1 = b"WEIGHTS_STEP_1"
    manager.save_checkpoint(weights_data=weights_v1, step_count=1, dataset_version_hash="hash_1")

    # Save Step 2
    weights_v2 = b"WEIGHTS_STEP_2"
    ckpt_v2_dir = manager.save_checkpoint(weights_data=weights_v2, step_count=2, dataset_version_hash="hash_2")

    # Corrupt Step 2 binary
    corrupt_file = ckpt_v2_dir / "adapter_model.bin"
    corrupt_file.write_bytes(b"CORRUPTED_GARBAGE_BYTES")

    # Load should detect corruption and rollback to Step 1
    loaded = manager.load_latest_checkpoint()
    assert loaded is not None
    loaded_weights, manifest = loaded
    assert loaded_weights == weights_v1
    assert manifest.step_count == 1
