"""The GGUF engine never silently substitutes fake LLM output."""
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from ai_engine.inference.local_gguf import LocalGGUFRunner, _local_path


def test_missing_model_is_not_reported_as_loaded(tmp_path):
    runner = LocalGGUFRunner({"model_path": str(tmp_path / "absent.gguf")})
    assert runner.is_available is False
    with pytest.raises(RuntimeError, match="No local GGUF model"):
        runner.chat("hello")


def test_rejects_unsafe_extensions(tmp_path):
    fake = tmp_path / "payload.exe"
    fake.write_text("not a model")
    assert _local_path(str(fake)) is None


def test_history_is_bounded(tmp_path):
    runner = LocalGGUFRunner({"model_path": ""})
    for i in range(20):
        runner.remember_exchange(str(i), str(i))
    assert len(runner._history) == 12


def test_gpu_offload_not_locked_to_nvml():
    from ai_engine.inference.local_gguf import choose_gpu_layers
    with patch.dict("sys.modules", {"pynvml": None}):
        assert choose_gpu_layers(24) == 24
        assert choose_gpu_layers(-1) == -1


def test_gpu_preflight_cpu_only_mode():
    from ai_engine.inference.local_gguf import choose_gpu_layers
    assert choose_gpu_layers(0) == 0


def test_small_gpu_is_not_rejected_by_fixed_vram_cutoff():
    from ai_engine.inference.local_gguf import choose_gpu_layers
    from types import SimpleNamespace
    gpu = SimpleNamespace(
        nvmlInit=lambda: None, nvmlDeviceGetCount=lambda: 1,
        nvmlDeviceGetHandleByIndex=lambda index: index,
        nvmlDeviceGetMemoryInfo=lambda handle: SimpleNamespace(total=4*1024**3, free=2*1024**3),
        nvmlDeviceGetUtilizationRates=lambda handle: SimpleNamespace(gpu=5),
    )
    with patch.dict("sys.modules", {"pynvml": gpu}):
        assert choose_gpu_layers(-1) == -1


def test_gpu_load_failure_retries_cpu(tmp_path):
    import sys
    from types import SimpleNamespace
    import ai_engine.inference.local_gguf as gguf

    path = tmp_path / "test.gguf"
    path.write_bytes(b"fake weights; test double intercepts the load")
    tries = []
    def fake_llama(**kwargs):
        tries.append(kwargs["n_gpu_layers"])
        if kwargs["n_gpu_layers"] != 0:
            raise RuntimeError("GPU unavailable")
        return SimpleNamespace()
    runner = gguf.LocalGGUFRunner({"model_path": str(path), "n_gpu_layers": -1})
    with patch.dict(sys.modules, {"pynvml": None, "llama_cpp": SimpleNamespace(Llama=fake_llama)}):
        assert runner._ensure_model() is not None
    assert tries == [-1, 0]
