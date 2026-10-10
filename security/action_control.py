"""Local, in-memory emergency stop and explicit offline network policy.

The stop prevents new work, not yet a hard OS process/job kill switch.
"""
from __future__ import annotations

import threading
from pathlib import Path

_LOCK = threading.RLock()
_STOP = False
_OFFLINE = None
_NETWORK_TOOLS = frozenset({
    "web_search", "youtube", "send_email",
    "send_whatsapp_message", "make_whatsapp_call",
    "play_media",
})


def _configured_offline() -> bool:
    try:
        import sys
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            import tomli as tomllib
        path = Path(__file__).resolve().parent.parent / "config.toml"
        with path.open("rb") as stream:
            return bool(tomllib.load(stream).get("general", {}).get("offline_mode", True))
    except (OSError, ValueError, ImportError):
        return True


def offline_mode() -> bool:
    global _OFFLINE
    with _LOCK:
        if _OFFLINE is None:
            _OFFLINE = _configured_offline()
        return _OFFLINE


def set_offline_mode(enabled: bool) -> bool:
    global _OFFLINE
    if not isinstance(enabled, bool):
        raise TypeError("offline toggle requires a boolean")
    with _LOCK:
        _OFFLINE = enabled
        return _OFFLINE


def network_allowed(tool_name: str) -> bool:
    return tool_name not in _NETWORK_TOOLS or not offline_mode()


def action_is_stopped() -> bool:
    with _LOCK:
        return _STOP


def stop_actions() -> None:
    global _STOP
    with _LOCK:
        _STOP = True


def resume_actions() -> None:
    global _STOP
    with _LOCK:
        _STOP = False
