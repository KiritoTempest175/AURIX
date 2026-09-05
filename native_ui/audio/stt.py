"""LUNA Speech-to-Text (STT) Engine.

Provides speech recognition using Google Speech API with fallback mechanisms
for local/offline processing. Converts recorded audio files into textual commands.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("luna.audio.stt")

try:
    import speech_recognition as sr
    HAS_SPEECH_RECOGNITION = True
except ImportError:
    sr = None
    HAS_SPEECH_RECOGNITION = False


class SpeechToTextEngine:
    """Manages audio file transcription with multi-tier fallback."""

    def __init__(self, default_language: str = "en-US") -> None:
        self.default_language = default_language
        self._recognizer: Optional[sr.Recognizer] = None
        if HAS_SPEECH_RECOGNITION:
            self._recognizer = sr.Recognizer()
            # Dynamic energy threshold adjustments
            self._recognizer.dynamic_energy_threshold = True

    @property
    def is_available(self) -> bool:
        return HAS_SPEECH_RECOGNITION and self._recognizer is not None

    def transcribe(
        self,
        audio_path: str | Path,
        language: Optional[str] = None,
    ) -> Optional[str]:
        """Transcribe audio from a WAV file to text.

        Returns transcribed string if successful, or None if speech was unintelligible.
        """
        if not self.is_available:
            logger.error("speech_recognition package is not installed.")
            return None

        p = Path(audio_path)
        if not p.exists() or p.stat().st_size < 1000:
            logger.warning(f"Audio file '{audio_path}' does not exist or is too small.")
            return None

        lang = language or self.default_language
        start_time = time.time()

        try:
            with sr.AudioFile(str(p)) as source:
                audio_data = self._recognizer.record(source)

            # 1. Primary: Google Speech Recognition (Fast, high accuracy)
            try:
                text = self._recognizer.recognize_google(audio_data, language=lang)
                elapsed = time.time() - start_time
                text_clean = text.strip()
                if text_clean:
                    logger.info(f"STT [Google] ({elapsed:.2f}s): '{text_clean}'")
                    return text_clean
            except sr.UnknownValueError:
                logger.info("STT: Speech was detected but could not be understood.")
                return None
            except sr.RequestError as req_err:
                logger.warning(f"Google STT service unreachable ({req_err}). Trying fallback...")

            # 2. Fallback: Offline Whisper via speech_recognition if model exists
            try:
                text = self._recognizer.recognize_whisper(audio_data, model="base")
                elapsed = time.time() - start_time
                text_clean = text.strip()
                if text_clean:
                    logger.info(f"STT [Whisper] ({elapsed:.2f}s): '{text_clean}'")
                    return text_clean
            except Exception as whisper_err:
                logger.debug(f"Whisper fallback unavailable: {whisper_err}")

        except Exception as e:
            logger.error(f"Error reading or transcribing audio file '{audio_path}': {e}")

        return None


_GLOBAL_STT: Optional[SpeechToTextEngine] = None


def get_stt_engine() -> SpeechToTextEngine:
    """Return the global singleton SpeechToTextEngine."""
    global _GLOBAL_STT
    if _GLOBAL_STT is None:
        _GLOBAL_STT = SpeechToTextEngine()
    return _GLOBAL_STT


def transcribe_audio(audio_path: str | Path, language: str = "en-US") -> Optional[str]:
    """Convenience helper to transcribe an audio WAV file."""
    engine = get_stt_engine()
    return engine.transcribe(audio_path, language=language)
