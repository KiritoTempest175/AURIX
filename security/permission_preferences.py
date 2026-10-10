"""Owner-controlled permission preferences for routine local actions.

These settings cannot bypass high-risk actions, external communications,
arbitrary executable launches or untrusted file paths.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
from security.config_loader import user_data_root

_LOCK = threading.RLock()
_DEFAULTS = {
    "allow_known_app_control": True,
    "allow_local_file_reads": True,
    "allow_trusted_workspace_edits": True,
}


def _path():
    return user_data_root() / "permission_preferences.json"


def read_policy() -> dict[str, bool]:
    with _LOCK:
        try:
            data = json.loads(_path().read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return dict(_DEFAULTS)
            return {
                key: data.get(key) if type(data.get(key)) is bool else default
                for key, default in _DEFAULTS.items()
            }
        except (OSError, ValueError):
            return dict(_DEFAULTS)


def write_policy(values: dict) -> dict[str, bool]:
    if not isinstance(values, dict) or set(values) != set(_DEFAULTS):
        raise ValueError("INVALID_PERMISSION_POLICY")
    if any(type(value) is not bool for value in values.values()):
        raise ValueError("INVALID_PERMISSION_POLICY")
    with _LOCK:
        target = _path()
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.with_name("." + secrets.token_hex(10) + ".tmp")
        try:
            with staged.open("x", encoding="utf-8") as output:
                json.dump(values, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(staged, target)
        finally:
            staged.unlink(missing_ok=True)
        return read_policy()
