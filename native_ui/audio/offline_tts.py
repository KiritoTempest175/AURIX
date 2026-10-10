"""Local Piper speech with explicit interruption and no network downloads.

Only Windows offline playback via winsound is implemented; the executable and
voice model must be installed by the user. Text is passed through stdin, never
into an executable shell command.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
import threading
from pathlib import Path
from typing import Optional

LOG = logging.getLogger("aurix.offline_tts")
_LOCK = threading.RLock()
_ACTIVE = False
_CANCEL = threading.Event()
_THREAD: Optional[threading.Thread] = None
_NATIVE_PROC: Optional[subprocess.Popen] = None
_LAST_SPOKE_AT = 0.0


def _resources() -> tuple[str, Path]:
    from security.config_loader import load_config, program_root, user_data_root
    cfg = load_config()
    audio = cfg.get("audio", {})
    binary = str(audio.get("piper_executable", "piper")).strip()
    if not binary or binary != Path(binary).name or not binary.lower().startswith("piper"):
        raise RuntimeError("TTS_BINARY_NOT_CONFIGURED")
    program = shutil.which(binary)
    if program is None:
        raise RuntimeError("TTS_BINARY_NOT_INSTALLED")
    raw = str(audio.get("piper_model_path", "")).strip()
    if not raw:
        raise RuntimeError("TTS_MODEL_NOT_CONFIGURED")
    model = Path(raw).expanduser()
    if not model.is_absolute():
        user_path = user_data_root() / model
        model = user_path if user_path.is_file() else program_root() / model
    model = model.resolve()
    if not model.is_file() or model.suffix.lower() != ".onnx":
        raise RuntimeError("TTS_MODEL_NOT_INSTALLED")
    return program, model


def is_speaking() -> bool:
    with _LOCK:
        return _ACTIVE


def stop() -> None:
    _CANCEL.set()
    with _LOCK:
        process = _NATIVE_PROC
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
    if os.name == "nt":
        try:
            import winsound
            winsound.PlaySound(None, 0)
        except OSError:
            LOG.warning("Windows TTS playback stop was not acknowledged")


def speak_async(text: str) -> bool:
    """Start a bounded offline speech job; returns when accepted, not spoken."""
    global _ACTIVE, _THREAD
    if not isinstance(text, str) or not text.strip() or len(text) > 800:
        raise ValueError("Speech must contain 1–800 characters")
    if os.name != "nt":
        raise RuntimeError("TTS_WINDOWS_REQUIRED")
    try:
        executable, model = _resources()
    except RuntimeError:
        # Windows ships speech synthesis voices on supported installations.
        # This fallback needs no separately installed Piper runtime or model.
        executable, model = None, None
    with _LOCK:
        if _ACTIVE:
            raise RuntimeError("TTS_BUSY")
        _CANCEL.clear()
        _ACTIVE = True
        worker = _speak_worker if executable and model else _speak_windows_voice
        args = (executable, model, text) if executable and model else (text,)
        _THREAD = threading.Thread(
            target=worker, args=args, daemon=True,
            name="aurix-local-speech"
        )
        _THREAD.start()
    return True


def _speak_worker(executable: str, model: Path, text: str) -> None:
    global _ACTIVE, _LAST_SPOKE_AT
    target = None
    try:
        import winsound
        with tempfile.NamedTemporaryFile(suffix=".wav", prefix="aurix_voice_", delete=False) as file:
            target = Path(file.name)
        result = subprocess.run(
            [executable, "--model", str(model), "--output_file", str(target)],
            input=text, text=True, encoding="utf-8", capture_output=True,
            timeout=25, shell=False,
        )
        if result.returncode != 0:
            LOG.error("Piper local synthesis failed with exit status %d", result.returncode)
            return
        if not _CANCEL.is_set() and target.is_file() and target.stat().st_size > 44:
            # Playback can be interrupted by stop() in another request thread.
            winsound.PlaySound(str(target), winsound.SND_FILENAME)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        LOG.exception("Local speech could not complete")
    finally:
        if target is not None:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                LOG.warning("Temporary voice file could not be removed")
        with _LOCK:
            _LAST_SPOKE_AT = time.monotonic()
            _ACTIVE = False


def is_active() -> bool:
    with _LOCK:
        return bool(_ACTIVE)


def spoken_recently() -> bool:
    with _LOCK:
        return bool(_ACTIVE or (time.monotonic() - _LAST_SPOKE_AT) < 1.5)


def _speak_windows_voice(text: str) -> None:
    """Speak using Windows-installed local voices; no network or shell input."""
    global _ACTIVE, _NATIVE_PROC, _LAST_SPOKE_AT
    import base64
    script = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$voice = [System.Speech.Synthesis.SpeechSynthesizer]::new()
try {
    try {
        $voice.SelectVoiceByHints(
            [System.Speech.Synthesis.VoiceGender]::Female,
            [System.Speech.Synthesis.VoiceAge]::Adult
        )
    } catch { }
    $voice.Rate = 1
    $voice.Speak([Console]::In.ReadToEnd())
}
finally { $voice.Dispose() }
"""
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    process = None
    try:
        process = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-NoLogo",
             "-EncodedCommand", encoded],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        with _LOCK:
            _NATIVE_PROC = process
        process.communicate(input=text, timeout=45)
        if process.returncode:
            LOG.warning("Windows speech synthesis unavailable (exit %s)", process.returncode)
    except (OSError, subprocess.TimeoutExpired):
        LOG.warning("Local Windows speech synthesis could not complete")
        if process is not None and process.poll() is None:
            process.kill()
    finally:
        with _LOCK:
            _NATIVE_PROC = None
            _LAST_SPOKE_AT = time.monotonic()
            _ACTIVE = False
