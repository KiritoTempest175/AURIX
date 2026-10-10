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
    for section in ("security", "resources", "llm", "memory", "voice", "audio", "general"):
        if not isinstance(data.get(section, {}), dict):
            raise ValueError(f"{section} must be a TOML section")
    resources = data.get("resources", {})
    if not isinstance(resources, dict):
        raise ValueError("resources must be a TOML section")
    for key, default in (
        ("min_free_ram_percent", 5.0),
        ("min_free_vram_percent", 5.0),
        ("gpu_busy_percent", 85.0),
        ("cpu_throttle_percent", 85.0),
    ):
        value = resources.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not (0 <= value <= 100):
            raise ValueError(f"resources.{key} must be between 0 and 100 percent")
    interval = resources.get("poll_interval_ms", 2500)
    if isinstance(interval, bool) or not isinstance(interval, int) or interval < 500:
        raise ValueError("resources.poll_interval_ms must be >= 500")
    # Legacy max_ram_gb and max_vram_gb keys are ignored: no fixed quotas.
    security = data.get("security", {})
    paths = security.get("allowed_project_paths", [])
    if not isinstance(paths, list) or any(not isinstance(p, str) or not p.strip() for p in paths):
        raise ValueError("security.allowed_project_paths must be a list of non-empty strings")
    llm = data.get("llm", {})
    context = llm.get("n_ctx", 2048)
    if type(context) is not int or not 512 <= context <= 8192:
        raise ValueError("llm.n_ctx must be 512–8192")
    if type(data.get("memory", {}).get("enabled", False)) is not bool:
        raise ValueError("memory.enabled must be boolean")
    if type(data.get("general", {}).get("offline_mode", True)) is not bool:
        raise ValueError("general.offline_mode must be boolean")
    for key, default, low, high in (("n_gpu_layers", -1, -1, 256), ("model_unload_after_seconds", 120, 30, 3600)):
        value = llm.get(key, default)
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"llm.{key} must be an integer between {low} and {high}")
    return data
