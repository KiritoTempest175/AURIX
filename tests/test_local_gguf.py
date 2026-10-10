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
