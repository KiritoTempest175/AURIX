"""Validate adaptive settings without imposing hard memory budgets."""
import pytest
from security.config_loader import load_config, program_root, config_file


def test_repo_default_config_is_adaptive():
    resources = load_config()["resources"]
    assert "max_ram_gb" not in resources
    assert "max_vram_gb" not in resources
    assert resources["min_free_ram_percent"] >= 0
    assert config_file().is_file()


def test_legacy_hard_caps_are_ignored(tmp_path, monkeypatch):
    contents = (program_root() / "config.toml").read_text(encoding="utf-8")
    custom = tmp_path / "legacy.toml"
    custom.write_text(contents.replace(
        "[resources]", "[resources]\nmax_ram_gb = 128.0\nmax_vram_gb = 64.0"
    ), encoding="utf-8")
    monkeypatch.setenv("AURIX_CONFIG_PATH", str(custom))
    assert load_config()["resources"]["max_ram_gb"] == 128.0


def test_invalid_pressure_percentage_is_rejected(tmp_path, monkeypatch):
    contents = (program_root() / "config.toml").read_text(encoding="utf-8")
    custom = tmp_path / "invalid.toml"
    custom.write_text(contents.replace(
        "min_free_ram_percent = 5.0", "min_free_ram_percent = 105.0"
    ), encoding="utf-8")
    monkeypatch.setenv("AURIX_CONFIG_PATH", str(custom))
    with pytest.raises(ValueError, match="min_free_ram_percent"):
        load_config()
