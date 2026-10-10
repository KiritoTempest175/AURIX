"""Validated AURIX configuration with user-scoped overrides.

The application reads one active TOML schema, never untrusted defaults from
the current working directory. Model files remain outside the executable.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def program_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def user_data_root() -> Path:
    custom = os.environ.get("AURIX_DATA_DIR")
    if custom:
        return Path(custom).expanduser().resolve()
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "AURIX"
    return program_root()


def config_file() -> Path:
    explicit = os.environ.get("AURIX_CONFIG_PATH")
    if explicit:
        return Path(explicit).expanduser().resolve()
    user_file = user_data_root() / "config.toml"
    if user_file.is_file():
        return user_file
    return program_root() / "config.toml"


def install_user_config() -> Path:
    """Copy default configuration on first packaged launch; never overwrite edits."""
    destination = user_data_root() / "config.toml"
    if destination.exists():
        return destination
    source = program_root() / "config.toml"
    if not source.is_file():
        raise FileNotFoundError("Bundled configuration unavailable")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("x", encoding="utf-8") as stream:
            stream.write(source.read_text(encoding="utf-8"))
    except FileExistsError:
        pass
    return destination


def load_config() -> dict:
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib
    with config_file().open("rb") as stream:
        data = tomllib.load(stream)
    if not isinstance(data, dict):
        raise ValueError("Invalid AURIX config")
    resources = data.get("resources", {})
    for key, upper in (("max_ram_gb", 12.0), ("max_vram_gb", 6.0)):
        value = resources.get(key, upper)
        if not isinstance(value, (int, float)) or not (0 < value <= upper):
            raise ValueError(f"resources.{key} must be in (0,{upper}]")
    security = data.get("security", {})
    if not isinstance(security.get("allowed_project_paths", []), list):
        raise ValueError("security.allowed_project_paths must be a list")
    llm = data.get("llm", {})
    if not (512 <= int(llm.get("n_ctx", 2048)) <= 8192):
        raise ValueError("llm.n_ctx must be 512–8192")
    if data.get("memory", {}).get("enabled", False) not in (True, False):
        raise ValueError("memory.enabled must be boolean")
    return data
