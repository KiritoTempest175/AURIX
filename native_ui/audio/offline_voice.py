"""Real offline microphone transcription for AURIX using preinstalled weights.

Neither the implementation nor the model loader may download weights on demand.
Recording occurs locally through the default Windows input device.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

_VOICE_LOCK = threading.Lock()
from security.config_loader import program_root, user_data_root, load_config
_PROJECT = program_root()


def _config() -> dict:
    return load_config().get("voice", {})


def _model_path(config: dict) -> Path:
    configured = str(config.get("stt_model_path", "")).strip()
    if not configured:
        raise RuntimeError("NO_STT_MODEL")
    path = Path(configured)
    if not path.is_absolute():
        user_path = user_data_root() / path
        path = user_path if user_path.is_dir() else _PROJECT / path
    path = path.resolve()
    if not path.is_dir():
        raise RuntimeError("NO_STT_MODEL")
    return path


def _windows_speech_recognition(seconds: int = 8) -> str:
    """Use Windows' installed local .NET speech recognizer without downloads.

    Only a constant PowerShell script is executed. It does not interpret any
    user text as code, and no microphone recording is written to disk.
    Some Windows installations lack a speech recognition language pack.
    """
    if sys.platform != "win32":
        raise RuntimeError("NO_STT_MODEL")
    script = r"""
$ErrorActionPreference = 'Stop'
$engine = $null
try {
    Add-Type -AssemblyName System.Speech
    $culture = [System.Globalization.CultureInfo]::GetCultureInfo('en-US')
    $engine = [System.Speech.Recognition.SpeechRecognitionEngine]::new($culture)
    $grammar = [System.Speech.Recognition.DictationGrammar]::new()
    $engine.LoadGrammar($grammar)
    $engine.SetInputToDefaultAudioDevice()
    $result = $engine.Recognize([TimeSpan]::FromSeconds(8))
    if ($null -ne $result) { [Console]::Out.Write($result.Text) }
} catch {
    exit 2
} finally {
    if ($null -ne $engine) { $engine.Dispose() }
}
"""
    import base64
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
             "-EncodedCommand", encoded],
            capture_output=True, text=True, errors="replace",
            timeout=seconds + 18,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("WINDOWS_SPEECH_UNAVAILABLE") from error
    if completed.returncode:
        raise RuntimeError("WINDOWS_SPEECH_UNAVAILABLE")
    return completed.stdout.strip()[:12000]


def speech_backend() -> str:
    """Report which offline microphone backend can be attempted."""
    try:
        _model_path(_config())
        import importlib.util
        if importlib.util.find_spec("sounddevice") is None or importlib.util.find_spec("faster_whisper") is None:
            raise ImportError
        return "whisper"
    except (RuntimeError, ImportError, OSError):
        return "windows_speech" if sys.platform == "win32" else "unavailable"


def transcribe_microphone() -> str:
    """Record a fixed bounded segment; return actual recognized words."""
    if not _VOICE_LOCK.acquire(blocking=False):
        raise RuntimeError("VOICE_BUSY")
    try:
        cfg = _config()
        try:
            path = _model_path(cfg)
        except RuntimeError as exc:
            if str(exc) == "NO_STT_MODEL":
                return _windows_speech_recognition()
            raise
        try:
            import numpy as np
            import sounddevice as sd
            from faster_whisper import WhisperModel
        except ImportError as exc:
            if sys.platform == "win32":
                return _windows_speech_recognition()
            raise RuntimeError("VOICE_DEPENDENCY_MISSING") from exc

        seconds = min(12.0, max(2.0, float(cfg.get("record_seconds", 6.0))))
        sample_rate = 16000
        model = WhisperModel(str(path), device="cpu", compute_type="int8",
                             local_files_only=True)
        frames = sd.rec(int(seconds * sample_rate), samplerate=sample_rate,
                        channels=1, dtype="float32")
        sd.wait()
        signal = np.asarray(frames, dtype=np.float32).reshape(-1)
        segments, _ = model.transcribe(signal, beam_size=3, vad_filter=True)
        return " ".join(segment.text.strip() for segment in segments).strip()[:12000]
    finally:
        _VOICE_LOCK.release()
