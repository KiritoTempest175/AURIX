"""Real offline microphone transcription for AURIX using preinstalled weights.

Neither the implementation nor the model loader may download weights on demand.
Recording occurs locally through the default Windows input device.
"""
from __future__ import annotations

import os
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


def transcribe_microphone() -> str:
    """Record a fixed bounded segment; return actual recognized words."""
    if not _VOICE_LOCK.acquire(blocking=False):
        raise RuntimeError("VOICE_BUSY")
    try:
        cfg = _config()
        path = _model_path(cfg)
        try:
            import numpy as np
            import sounddevice as sd
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("VOICE_DEPENDENCY_MISSING") from exc

        seconds = min(12.0, max(2.0, float(cfg.get("record_seconds", 6.0))))
        sample_rate = 16000
        model = WhisperModel(str(path), device="cpu", compute_type="int8",
                             local_files_only=True)
        # Audio data and text remain in process memory, not a temp recording file.
        frames = sd.rec(int(seconds * sample_rate), samplerate=sample_rate,
                        channels=1, dtype="float32")
        sd.wait()
        signal = np.asarray(frames, dtype=np.float32).reshape(-1)
        segments, _ = model.transcribe(signal, beam_size=3, vad_filter=True)
        return " ".join(segment.text.strip() for segment in segments).strip()[:12000]
    finally:
        _VOICE_LOCK.release()
