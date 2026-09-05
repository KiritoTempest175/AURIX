"""Unit tests for CheckpointManager: atomic persistence, encryption, rollback, extra_state, and restore by ID."""

import json
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from ai_engine.training.checkpoint_manager import (
    CheckpointManager,
    CheckpointNotFoundError,
)
from security.encryption import CheckpointEncryptor


import pytest
from contextlib import contextmanager


@contextmanager
def get_temp_ckpt_dir():
    d = tempfile.mkdtemp(prefix="luna_test_ckpts_")
    try:
        yield d
    finally:
        if os.path.exists(d):
            shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def temp_dir():
    with get_temp_ckpt_dir() as d:
        yield d


def test_checkpoint_save_and_load_roundtrip(temp_dir: str):
    """Test full save -> load round-trip with encrypted model weights and optimizer/RNG extra state."""
    encryptor = CheckpointEncryptor(key=b"0" * 32)
    manager = CheckpointManager(checkpoint_dir=temp_dir, encrypt_at_rest=True, encryptor=encryptor)

    fake_weights = b"TENSOR_WEIGHTS_BINARY_PAYLOAD_STEP_10"
    extra_state = {
        "optimizer_state": {
            "state": {"0": {"momentum": [0.123, 0.456, 0.789]}},
            "param_groups": [{"lr": 0.0002, "weight_decay": 0.01}],
        },
        "rng_seed": 42,
        "rng_state": [1, 2, 3, 4, 5],
        "epoch": 2,
    }

    ckpt_path = manager.save_checkpoint(
        weights_data=fake_weights,
        step_count=10,
        dataset_version_hash="data_v1_hash",
        lora_rank=16,
        lora_alpha=32,
        eval_loss=0.45,
        extra_state=extra_state,
    )
    assert os.path.exists(ckpt_path)

    # Load latest checkpoint
    loaded = manager.load_latest_checkpoint()
    assert loaded is not None
    loaded_weights, manifest, loaded_extra_state = loaded

    # Assert bit-for-bit weights and metadata
    assert loaded_weights == fake_weights
    assert manifest.step_count == 10
    assert manifest.lora_rank == 16
    assert manifest.eval_loss == 0.45
    assert manifest.is_encrypted is True

    # Assert extra_state restored exactly as saved
    assert loaded_extra_state is not None
    assert loaded_extra_state == extra_state


def test_checkpoint_load_without_extra_state(temp_dir: str):
    """Ensure backward-compatibility when loading a checkpoint saved without extra_state."""
    encryptor = CheckpointEncryptor(key=b"0" * 32)
    manager = CheckpointManager(checkpoint_dir=temp_dir, encrypt_at_rest=True, encryptor=encryptor)

    fake_weights = b"WEIGHTS_NO_EXTRA_STATE"
    manager.save_checkpoint(
        weights_data=fake_weights,
        step_count=5,
        dataset_version_hash="hash_no_extra",
        extra_state=None,
    )

    loaded = manager.load_latest_checkpoint()
    assert loaded is not None
    loaded_weights, manifest, loaded_extra_state = loaded
    assert loaded_weights == fake_weights
    assert manifest.step_count == 5
    assert loaded_extra_state is None


def test_checkpoint_automatic_rollback_on_corruption(temp_dir: str):
    """Ensure corrupted latest checkpoint automatically triggers rollback to previous valid checkpoint."""
    encryptor = CheckpointEncryptor(key=b"1" * 32)
    manager = CheckpointManager(checkpoint_dir=temp_dir, encrypt_at_rest=True, encryptor=encryptor)

    # Save Step 1 with extra state
    weights_v1 = b"WEIGHTS_STEP_1"
    state_v1 = {"step": 1, "optimizer": "adam"}
    manager.save_checkpoint(
        weights_data=weights_v1,
        step_count=1,
        dataset_version_hash="hash_1",
        extra_state=state_v1,
    )

    # Save Step 2
    weights_v2 = b"WEIGHTS_STEP_2"
    ckpt_v2_dir = manager.save_checkpoint(
        weights_data=weights_v2,
        step_count=2,
        dataset_version_hash="hash_2",
    )

    # Corrupt Step 2 binary
    corrupt_file = ckpt_v2_dir / "adapter_model.bin"
    corrupt_file.write_bytes(b"CORRUPTED_GARBAGE_BYTES")

    # Load should detect corruption and rollback to Step 1
    loaded = manager.load_latest_checkpoint()
    assert loaded is not None
    loaded_weights, manifest, loaded_extra_state = loaded
    assert loaded_weights == weights_v1
    assert manifest.step_count == 1
    assert loaded_extra_state == state_v1


def test_load_checkpoint_by_id_success(temp_dir: str):
    """Test explicitly restoring a valid non-latest checkpoint by ID and updating latest pointer."""
    encryptor = CheckpointEncryptor(key=b"2" * 32)
    manager = CheckpointManager(checkpoint_dir=temp_dir, encrypt_at_rest=True, encryptor=encryptor)

    # Save Checkpoint 1
    weights_v1 = b"WEIGHTS_STEP_10"
    state_v1 = {"step": 10, "lr": 0.0005}
    ckpt_1_dir = manager.save_checkpoint(
        weights_data=weights_v1,
        step_count=10,
        dataset_version_hash="hash_10",
        extra_state=state_v1,
    )
    ckpt_1_id = ckpt_1_dir.name

    # Save Checkpoint 2 (becomes latest)
    weights_v2 = b"WEIGHTS_STEP_20"
    state_v2 = {"step": 20, "lr": 0.0001}
    ckpt_2_dir = manager.save_checkpoint(
        weights_data=weights_v2,
        step_count=20,
        dataset_version_hash="hash_20",
        extra_state=state_v2,
    )
    ckpt_2_id = ckpt_2_dir.name

    # Verify latest is currently Checkpoint 2
    pointer_before = json.loads((manager.checkpoint_dir / "latest_checkpoint.json").read_text(encoding="utf-8"))
    assert pointer_before["latest_checkpoint_id"] == ckpt_2_id

    # Restore Checkpoint 1 by explicit ID
    restored = manager.load_checkpoint(ckpt_1_id)
    restored_weights, manifest, restored_state = restored

    assert restored_weights == weights_v1
    assert manifest.checkpoint_id == ckpt_1_id
    assert manifest.step_count == 10
    assert restored_state == state_v1

    # Verify pointer was atomically updated to Checkpoint 1
    pointer_after = json.loads((manager.checkpoint_dir / "latest_checkpoint.json").read_text(encoding="utf-8"))
    assert pointer_after["latest_checkpoint_id"] == ckpt_1_id

    # Calling load_latest_checkpoint should now return Checkpoint 1
    latest = manager.load_latest_checkpoint()
    assert latest is not None
    assert latest[1].checkpoint_id == ckpt_1_id


def test_load_checkpoint_by_id_failure(temp_dir: str):
    """Test that requesting a nonexistent or corrupted checkpoint by ID raises and does NOT alter pointer."""
    encryptor = CheckpointEncryptor(key=b"3" * 32)
    manager = CheckpointManager(checkpoint_dir=temp_dir, encrypt_at_rest=True, encryptor=encryptor)

    # Save Checkpoint 1
    weights_v1 = b"VALID_WEIGHTS"
    ckpt_1_dir = manager.save_checkpoint(
        weights_data=weights_v1,
        step_count=1,
        dataset_version_hash="hash_1",
    )
    ckpt_1_id = ckpt_1_dir.name

    # 1. Nonexistent checkpoint ID raises CheckpointNotFoundError
    caught_not_found = False
    try:
        manager.load_checkpoint("ckpt_nonexistent_id_999999")
    except (CheckpointNotFoundError, FileNotFoundError):
        caught_not_found = True
    assert caught_not_found, "load_checkpoint should raise CheckpointNotFoundError for nonexistent ID"

    # Verify pointer is untouched
    pointer = json.loads((manager.checkpoint_dir / "latest_checkpoint.json").read_text(encoding="utf-8"))
    assert pointer["latest_checkpoint_id"] == ckpt_1_id

    # 2. Corrupted checkpoint ID raises ValueError
    corrupted_dir = manager.checkpoint_dir / "ckpt_corrupted_test"
    corrupted_dir.mkdir()
    # Write invalid manifest and weights
    (corrupted_dir / "manifest.json").write_text(json.dumps({
        "checkpoint_id": "ckpt_corrupted_test",
        "timestamp": 0.0,
        "iso_time": "test",
        "step_count": 0,
        "eval_loss": None,
        "dataset_version_hash": "test",
        "model_architecture": "test",
        "lora_rank": 16,
        "lora_alpha": 32,
        "is_encrypted": True,
        "weights_sha256": "invalid_hash",
    }))
    (corrupted_dir / "adapter_model.bin").write_bytes(b"BAD_BYTES")

    caught_val_err = False
    try:
        manager.load_checkpoint("ckpt_corrupted_test")
    except ValueError:
        caught_val_err = True
    assert caught_val_err, "load_checkpoint should raise ValueError for corrupted checkpoint"

    # Verify pointer remains untouched
    pointer = json.loads((manager.checkpoint_dir / "latest_checkpoint.json").read_text(encoding="utf-8"))
    assert pointer["latest_checkpoint_id"] == ckpt_1_id


if __name__ == "__main__":
    with get_temp_ckpt_dir() as d:
        test_checkpoint_save_and_load_roundtrip(d)
        print("[PASS] test_checkpoint_save_and_load_roundtrip")
        test_checkpoint_load_without_extra_state(d)
        print("[PASS] test_checkpoint_load_without_extra_state")
        test_checkpoint_automatic_rollback_on_corruption(d)
        print("[PASS] test_checkpoint_automatic_rollback_on_corruption")
        test_load_checkpoint_by_id_success(d)
        print("[PASS] test_load_checkpoint_by_id_success")
        test_load_checkpoint_by_id_failure(d)
        print("[PASS] test_load_checkpoint_by_id_failure")
    print("All CheckpointManager tests passed successfully!")
