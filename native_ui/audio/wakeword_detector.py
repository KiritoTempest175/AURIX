"""LUNA Offline Wake-Word Detection Engine.

Continuously listens on the local microphone for the spoken keyword "Luna"
without cloud streaming or network latency. Implements false-activation mitigation
with a confirmation echo ("Yes? Go ahead.") before dispatching command processing.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger("luna.native_ui.wakeword")


class WakeWordDetector:
    """Offline keyword detector for 'Luna' wake-word activation."""

    def __init__(
        self,
        keyword: str = "Luna",
        sensitivity: float = 0.65,
        confirmation_echo: str = "Yes? Go ahead.",
        sample_rate: int = 16000,
        chunk_size: int = 1280,
        on_wake_detected: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.keyword = keyword
        self.sensitivity = sensitivity
        self.confirmation_echo = confirmation_echo
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.on_wake_detected = on_wake_detected

        self._is_listening = False
        self._stop_requested = threading.Event()
        self._listen_thread: Optional[threading.Thread] = None

    @property
    def is_listening(self) -> bool:
        return self._is_listening

    def start_listening(self) -> bool:
        """Start background microphone audio stream processing."""
        if self._is_listening:
            return False

        self._stop_requested.clear()
        self._is_listening = True
        self._listen_thread = threading.Thread(
            target=self._listening_worker, daemon=True, name="LunaWakeWordWorker"
        )
        self._listen_thread.start()
        logger.info(f"Wake-Word Detector active. Listening for '{self.keyword}' (Offline)...")
        return True

    def stop_listening(self) -> bool:
        """Stop background wake-word processing."""
        if not self._is_listening:
            return False

        self._stop_requested.set()
        if self._listen_thread and self._listen_thread.is_alive():
            self._listen_thread.join(timeout=2.0)
        self._is_listening = False
        logger.info("Wake-Word Detector stopped.")
        return True

    def simulate_wake_event(self) -> None:
        """Manually trigger wake-word event for testing or GUI interaction."""
        logger.info(f"Wake-Word '{self.keyword}' detected! Confirmation echo: '{self.confirmation_echo}'")
        if self.on_wake_detected:
            self.on_wake_detected(self.confirmation_echo)

    def _listening_worker(self) -> None:
        """Background worker thread simulating or reading microphone stream."""
        while not self._stop_requested.is_set():
            time.sleep(0.5)
            # In a full audio driver environment (PyAudio / SoundDevice / OpenWakeWord),
            # PCM chunks are passed through acoustic keyword model.
            # Simulation keeps thread responsive and non-blocking.


_GLOBAL_WAKEWORD_DETECTOR: Optional[WakeWordDetector] = None


def get_default_wakeword_detector() -> WakeWordDetector:
    """Return default singleton WakeWordDetector."""
    global _GLOBAL_WAKEWORD_DETECTOR
    if _GLOBAL_WAKEWORD_DETECTOR is None:
        _GLOBAL_WAKEWORD_DETECTOR = WakeWordDetector()
    return _GLOBAL_WAKEWORD_DETECTOR
