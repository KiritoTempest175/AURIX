"""Memory capture preference is persisted separately from public config."""
import json

from ai_brain.secure_memory import memory_enabled, set_memory_enabled


def test_disabling_memory_is_persistent(tmp_path, monkeypatch):
    monkeypatch.setenv("AURIX_DATA_DIR", str(tmp_path))
    assert set_memory_enabled(False) is False
    assert json.loads((tmp_path / "privacy-settings.json").read_text()) == {"memory_enabled": False}
    assert memory_enabled() is False


def test_invalid_memory_preference_is_rejected(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setenv("AURIX_DATA_DIR", str(tmp_path))
    with pytest.raises(TypeError):
        set_memory_enabled("true")


def test_corrupt_memory_setting_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("AURIX_DATA_DIR", str(tmp_path))
    (tmp_path / "privacy-settings.json").write_text("not json")
    assert memory_enabled() is False
