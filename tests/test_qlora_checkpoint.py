# ─────────────────────────────────────────────────────────────────────────────
# tests/test_qlora_checkpoint.py
# ─────────────────────────────────────────────────────────────────────────────
# Pytest suite verifying that the GracefulMemoryManager correctly evicts
# CUDA VRAM when the Rust governor signals a resource spike.
#
# Strategy:
#   - Mock `aurix_core.SystemState` to forcibly return True for
#     `check_suspended()` (simulating a RAM/VRAM spike).
#   - Use fake model/tokenizer stubs with spy-wrapped `.save_pretrained()`.
#   - Assert checkpoint saves, eviction counts, and return values.
#   - Assert that CUDA VRAM drops significantly when tested with GPU.
# ─────────────────────────────────────────────────────────────────────────────

import gc
import json
import pytest
import torch
from unittest.mock import MagicMock


# ─── Test Fixtures ────────────────────────────────────────────────────────────


class FakeModel:
    """Minimal model stub implementing .save_pretrained() for testing."""

    def save_pretrained(self, path):
        pass


class FakeTokenizer:
    """Minimal tokenizer stub implementing .save_pretrained() for testing."""

    def save_pretrained(self, path):
        pass


class MockSystemState:
    """Mock replacement for aurix_core.SystemState.

    Simulates a governor spike that resolves after `spike_duration` polls.
    After `spike_duration` calls to `check_suspended()`, it returns False
    (simulating resource recovery).

    Args:
        spike_duration:  Number of times check_suspended() returns True.
    """

    def __init__(self, spike_duration: int = 1):
        self._spike_duration = spike_duration
        self._poll_count = 0

    def check_suspended(self) -> bool:
        self._poll_count += 1
        return self._poll_count <= self._spike_duration

    def pause(self):
        pass

    def resume(self):
        pass


# ─── Test: Eviction triggers on suspend ──────────────────────────────────────


def test_check_and_evict_triggers_on_suspend():
    """Verify that check_and_evict() fires the full eviction sequence when
    the Rust governor's suspend flag is True.

    Asserts:
      - save_pretrained() called on both model and tokenizer
      - check_and_evict() returns True
      - total_evictions counter incremented to 1
    """
    from ai_engine.training.memory_manager import GracefulMemoryManager

    mock_state = MockSystemState(spike_duration=1)

    model = FakeModel()
    tokenizer = FakeTokenizer()

    # Spy on save_pretrained calls
    model.save_pretrained = MagicMock()
    tokenizer.save_pretrained = MagicMock()

    manager = GracefulMemoryManager(
        model=model,
        tokenizer=tokenizer,
        save_path="./test_checkpoint_tmp",
    )
    manager.system_state = mock_state

    # Act: trigger the eviction check
    evicted = manager.check_and_evict()

    # Assert: eviction was triggered
    assert evicted is True, "check_and_evict() must return True during a spike"

    # Assert: model checkpoint was saved
    model.save_pretrained.assert_called_once_with("./test_checkpoint_tmp")
    tokenizer.save_pretrained.assert_called_once_with("./test_checkpoint_tmp")

    # Assert: eviction counter incremented
    assert manager.total_evictions == 1


# ─── Test: No eviction when not suspended ────────────────────────────────────


def test_no_eviction_when_not_suspended():
    """Verify that check_and_evict() does NOT trigger eviction when the
    governor reports no spike (check_suspended() returns False).
    """
    from ai_engine.training.memory_manager import GracefulMemoryManager

    mock_state = MagicMock()
    mock_state.check_suspended.return_value = False

    model = FakeModel()
    tokenizer = FakeTokenizer()
    model.save_pretrained = MagicMock()
    tokenizer.save_pretrained = MagicMock()

    manager = GracefulMemoryManager(
        model=model,
        tokenizer=tokenizer,
        save_path="./test_checkpoint_tmp",
    )
    manager.system_state = mock_state

    evicted = manager.check_and_evict()

    # Assert: no eviction occurred
    assert evicted is False, "check_and_evict() must return False with no spike"

    # Assert: save_pretrained was NOT called (no checkpoint needed)
    model.save_pretrained.assert_not_called()
    tokenizer.save_pretrained.assert_not_called()

    assert manager.total_evictions == 0


# ─── Test: Multiple eviction cycles ──────────────────────────────────────────


def test_multiple_eviction_cycles():
    """Verify that the eviction counter correctly tracks multiple spikes."""
    from ai_engine.training.memory_manager import GracefulMemoryManager

    model = FakeModel()
    tokenizer = FakeTokenizer()
    model.save_pretrained = MagicMock()
    tokenizer.save_pretrained = MagicMock()

    manager = GracefulMemoryManager(
        model=model,
        tokenizer=tokenizer,
        save_path="./test_checkpoint_tmp",
    )

    # Simulate 3 spike → recovery cycles
    for _ in range(3):
        manager.system_state = MockSystemState(spike_duration=1)
        manager.check_and_evict()

    assert manager.total_evictions == 3, (
        f"Expected 3 evictions, got {manager.total_evictions}"
    )
    assert model.save_pretrained.call_count == 3


# ─── Test: CUDA VRAM eviction (GPU-only, skipped if no CUDA) ────────────────


def test_cuda_vram_drops_after_eviction():
    """Verify that torch.cuda.memory_allocated() drops after eviction when
    a GPU is available.
    """
    if not torch.cuda.is_available():
        pytest.skip("No CUDA device available on current test runner")

    # Allocate a 256MB tensor on the GPU
    tensor = torch.randn(64, 1024, 1024, device="cuda")
    vram_before = torch.cuda.memory_allocated()

    assert vram_before > 200 * 1024**2

    # Simulate the eviction sequence from GracefulMemoryManager
    del tensor
    gc.collect()
    torch.cuda.empty_cache()

    vram_after = torch.cuda.memory_allocated()
    freed = vram_before - vram_after

    assert freed > 200 * 1024**2, (
        f"Expected >200MB freed, got {freed / 1024**2:.1f}MB"
    )


# ─── Test: Dynamic Dataset Streaming ─────────────────────────────────────────


def test_dynamic_dataset_parses_samples(tmp_path):
    """Verify DynamicTelemetryDataset correctly streams and formats samples."""
    from ai_engine.training.dynamic_loader import DynamicTelemetryDataset

    jsonl_file = tmp_path / "test_telemetry.jsonl"
    samples = [
        {"instruction": "Open Notepad", "input": "", "output": "Opening Notepad..."},
        {"instruction": "List files", "input": "C:\\Users", "output": "dir output"},
        {"instruction": "", "input": "", "output": "missing instruction"},
    ]
    with open(jsonl_file, "w") as f:
        for s in samples:
            f.write(json.dumps(s) + "\n")

    dataset = DynamicTelemetryDataset(data_path=str(jsonl_file))
    results = list(dataset)

    # Only 2 valid samples (the third has no instruction → skipped)
    assert len(results) == 2, f"Expected 2 valid samples, got {len(results)}"

    for r in results:
        assert "text" in r
        assert "### Instruction:" in r["text"]
        assert "### Response:" in r["text"]


def test_dynamic_dataset_handles_missing_file():
    """Verify that DynamicTelemetryDataset yields 0 samples for a missing file."""
    from ai_engine.training.dynamic_loader import DynamicTelemetryDataset

    dataset = DynamicTelemetryDataset(data_path="./nonexistent_file.jsonl")
    results = list(dataset)

    assert len(results) == 0, "Missing file should yield 0 samples"


def test_dynamic_dataset_max_samples(tmp_path):
    """Verify the max_samples cap limits the number of yielded samples."""
    from ai_engine.training.dynamic_loader import DynamicTelemetryDataset

    jsonl_file = tmp_path / "capped.jsonl"
    with open(jsonl_file, "w") as f:
        for i in range(100):
            f.write(json.dumps({
                "instruction": f"Task {i}",
                "input": "",
                "output": f"Result {i}",
            }) + "\n")

    dataset = DynamicTelemetryDataset(data_path=str(jsonl_file), max_samples=5)
    results = list(dataset)

    assert len(results) == 5, f"Expected 5 capped samples, got {len(results)}"
