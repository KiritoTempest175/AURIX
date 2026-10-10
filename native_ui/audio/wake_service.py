"""Opt-in offline wake-phrase listener.

Microphone capture is only enabled after an explicit UI opt-in, which is
persisted privately for the user. Audio never leaves the device or disk.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections import deque
from pathlib import Path

from security.config_loader import user_data_root

LOG = logging.getLogger("aurix.voice.wake")
_LOCK = threading.RLock()
_STOP = threading.Event()
_THREAD: threading.Thread | None = None
_EVENTS: deque[dict] = deque(maxlen=20)
_FAILURE = ""
_LOADED = False
_ENABLED = False
_WAKE = re.compile(r"\b(?:hey|hello|okay|ok)\s+luna\b|\bluna\b|\bhey\s+aurix\b", re.I)


def _path() -> Path:
    return user_data_root() / "wake_preference.json"


def _persist(enabled: bool) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    import secrets
    temp = path.with_name("." + secrets.token_hex(8) + ".tmp")
    try:
        with temp.open("x", encoding="utf-8") as stream:
            json.dump({"enabled": enabled}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _ensure_loaded() -> None:
    global _LOADED, _ENABLED
    if _LOADED:
        return
    _LOADED = True
    try:
        _ENABLED = json.loads(_path().read_text(encoding="utf-8")).get("enabled") is True
    except (OSError, ValueError, AttributeError):
        _ENABLED = False
    if _ENABLED:
        _start()


def _listen() -> None:
    global _FAILURE
    from native_ui.audio.offline_voice import transcribe_microphone
    while not _STOP.is_set():
        try:
            heard = transcribe_microphone()
            if _STOP.is_set():
                break
            match = _WAKE.search(heard)
            if match:
                with _LOCK:
                    _EVENTS.append({"kind": "wake", "command": heard[match.end():].strip(" ,.!?")[:500]})
                    _FAILURE = ""
        except RuntimeError as exc:
            if str(exc) in {"WINDOWS_SPEECH_UNAVAILABLE", "NO_STT_MODEL", "VOICE_DEPENDENCY_MISSING"}:
                with _LOCK:
                    _FAILURE = str(exc)
                break
        except Exception:
            LOG.exception("Wake reader unavailable")
            with _LOCK:
                _FAILURE = "VOICE_UNAVAILABLE"
            break
        _STOP.wait(.5)


def _start() -> None:
    global _THREAD, _FAILURE
    if _THREAD and _THREAD.is_alive():
        _STOP.clear()
        return
    _FAILURE = ""
    _STOP.clear()
    _THREAD = threading.Thread(target=_listen, name="aurix-wake", daemon=True)
    _THREAD.start()


def configure(enabled: bool) -> dict:
    global _ENABLED
    if type(enabled) is not bool:
        raise ValueError("INVALID_WAKE_SETTING")
    with _LOCK:
        _persist(enabled)
        _ENABLED = enabled
        _ensure_loaded()
        if enabled:
            _start()
        else:
            _STOP.set()
        return status()


def status() -> dict:
    with _LOCK:
        _ensure_loaded()
        from native_ui.audio.offline_voice import speech_backend
        return {
            "enabled": _ENABLED,
            "listening": bool(_THREAD and _THREAD.is_alive() and not _STOP.is_set()),
            "backend": speech_backend(),
            "error": _FAILURE,
        }


def drain_events() -> list[dict]:
    with _LOCK:
        _ensure_loaded()
        events = list(_EVENTS)
        _EVENTS.clear()
        return events
