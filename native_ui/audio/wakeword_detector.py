"""LUNA Offline Wake-Word Detection Engine.

Continuously listens on the local microphone for spoken keywords ("Luna", "Hey Luna",
"Can you speak", "Can you say something", etc.) without cloud streaming.
Dispatches a wake callback with audio/visual confirmation.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("luna.native_ui.wakeword")

ROOT_DIR = Path(__file__).resolve().parent.parent.parent


class WakeWordDetector:
    """Offline keyword detector for 'Luna' wake-word activation."""

    def __init__(
        self,
        keyword: str = "Luna",
        sensitivity: float = 0.65,
        confirmation_echo: str = "Yes?",
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
        self._paused = threading.Event()
        self._listen_thread: Optional[threading.Thread] = None
        self._process: Optional[subprocess.Popen] = None

    @property
    def is_listening(self) -> bool:
        return self._is_listening and not self._paused.is_set()

    def start_listening(self) -> bool:
        """Start background microphone audio stream processing."""
        if self._is_listening:
            return False

        self._stop_requested.clear()
        self._paused.clear()
        self._is_listening = True
        self._listen_thread = threading.Thread(
            target=self._listening_worker, daemon=True, name="LunaWakeWordWorker"
        )
        self._listen_thread.start()
        logger.info(f"Wake-Word Detector active. Listening for '{self.keyword}' (Offline)...")
        return True

    def pause_listening(self) -> None:
        """Temporarily pause wake-word detector and release microphone device."""
        self._paused.set()
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
                self._process.wait(timeout=1.0)
            except Exception:
                pass
            self._process = None
        logger.debug("Wake-Word Detector paused (mic released).")

    def resume_listening(self) -> None:
        """Resume wake-word detector after voice recording completes."""
        self._paused.clear()
        logger.debug("Wake-Word Detector resumed.")

    def stop_listening(self) -> bool:
        """Stop background wake-word processing."""
        if not self._is_listening:
            return False

        self._stop_requested.set()
        self._paused.clear()
        if self._process:
            try:
                self._process.terminate()
            except Exception:
                pass
        if self._listen_thread and self._listen_thread.is_alive():
            self._listen_thread.join(timeout=2.0)
        self._is_listening = False
        logger.info("Wake-Word Detector stopped.")
        return True

    def simulate_wake_event(self) -> None:
        """Manually trigger wake-word event for testing or GUI interaction."""
        logger.info(f"Wake-Word '{self.keyword}' detected! Confirmation: '{self.confirmation_echo}'")
        if self.on_wake_detected:
            self.on_wake_detected(self.confirmation_echo)

    def _listening_worker(self) -> None:
        """Continuous background microphone listener."""
        ps_script = ROOT_DIR / "scripts" / "wakeword_listener.ps1"

        while not self._stop_requested.is_set():
            if self._paused.is_set():
                time.sleep(0.3)
                continue
            if ps_script.exists():
                try:
                    self._process = subprocess.Popen(
                        [
                            "powershell",
                            "-NoProfile",
                            "-NonInteractive",
                            "-ExecutionPolicy",
                            "Bypass",
                            "-File",
                            str(ps_script),
                        ],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        bufsize=1,
                    )

                    while not self._stop_requested.is_set() and self._process.poll() is None:
                        line = self._process.stdout.readline()
                        if not line:
                            break
                        line_str = line.strip()
                        if "WAKEWORD_DETECTED:" in line_str:
                            detected = line_str.split("WAKEWORD_DETECTED:", 1)[1].strip()
                            logger.info(f"🎤 Wake-word detected: '{detected}'")
                            if self.on_wake_detected:
                                try:
                                    self.on_wake_detected(self.confirmation_echo)
                                except Exception as err:
                                    logger.error(f"Error in wake handler: {err}")
                            time.sleep(1.0)  # Debounce
                except Exception as e:
                    logger.debug(f"Wake listener process error: {e}")
            
            if not self._stop_requested.is_set():
                time.sleep(2.0)


_GLOBAL_WAKEWORD_DETECTOR: Optional[WakeWordDetector] = None


def get_default_wakeword_detector() -> WakeWordDetector:
    """Return default singleton WakeWordDetector."""
    global _GLOBAL_WAKEWORD_DETECTOR
    if _GLOBAL_WAKEWORD_DETECTOR is None:
        _GLOBAL_WAKEWORD_DETECTOR = WakeWordDetector()
    return _GLOBAL_WAKEWORD_DETECTOR
