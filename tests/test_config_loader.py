"""One explicit configuration loader for packaged and source execution."""
import pytest

from security.config_loader import load_config, program_root, config_file


def test_repo_default_config_is_valid():
    assert load_config()["resources"]["max_ram_gb"] <= 12
    assert config_file().is_file()


def test_rejects_excessive_memory_budget(tmp_path, monkeypatch):
    contents = (program_root() / "config.toml").read_text(encoding="utf-8")
    file = tmp_path / "invalid.toml"
    file.write_text(contents.replace("max_ram_gb = 12.0", "max_ram_gb = 48.0"), encoding="utf-8")
    monkeypatch.setenv("AURIX_CONFIG_PATH", str(file))
    with pytest.raises(ValueError, match="max_ram_gb"):
        load_config()
