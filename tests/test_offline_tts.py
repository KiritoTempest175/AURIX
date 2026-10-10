"""Offline TTS must be real, bounded, and never download models."""
import pytest
from native_ui.audio import offline_tts


def test_invalid_speech_rejected_before_loading_any_binary():
    for bad in ("", " " * 3, "x" * 801):
        with pytest.raises(ValueError):
            offline_tts.speak_async(bad)


def test_no_hidden_download_or_shell_interpolation():
    import inspect
    source = inspect.getsource(offline_tts._speak_worker)
    assert "shell=False" in source
    assert "subprocess.run" in source
    assert "http://" not in source
