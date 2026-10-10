"""No cloud endpoint or QLoRA training in AURIX model selection."""
from unittest.mock import patch

import pytest

from ai_engine.inference.ollama_runtime import (
    OllamaRunner, get_model_runner, selection, set_selection, valid_model,
)


def test_tags_are_strictly_validated():
    assert valid_model("qwen3:4b")
    assert valid_model("gemma3:12b")
    assert not valid_model("http://external.example")
    assert not valid_model("../../bad")
    assert not valid_model(" ; powershell")
    assert not valid_model("gpt-oss:20b-cloud")


def test_no_uninstalled_model_activation(tmp_path, monkeypatch):
    monkeypatch.setenv("AURIX_DATA_DIR", str(tmp_path))
    with patch("ai_engine.inference.ollama_runtime.installed_models", return_value=["qwen3:4b"]):
        with pytest.raises(ValueError, match="MODEL_NOT_INSTALLED"):
            set_selection("ollama", "gemma3:4b")
        saved = set_selection("ollama", "qwen3:4b")
        assert saved["model"] == "qwen3:4b"
        assert selection()["model"] == "qwen3:4b"


def test_reject_non_ollama_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("AURIX_DATA_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="INVALID_BACKEND"):
        set_selection("llama_cpp", "qwen3:4b")


def test_chat_is_local_and_does_not_train():
    runner = OllamaRunner("qwen3:4b")
    with patch.object(runner, "_chat", return_value="Hello") as mocked:
        assert runner.chat("hi") == "Hello"
    assert mocked.call_count == 1
