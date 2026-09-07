"""AURIX AI Brain — Media Player Integration.

Provides capabilities to play music via Spotify Desktop (UI automation)
or fallback to web browsers.
"""

import logging
import os
import subprocess
from typing import Optional

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None
    PSUTIL_AVAILABLE = False

from core_engine import UiaController

logger = logging.getLogger("aurix.ai_brain.media_player")

class MediaPlayer:
    def __init__(self):
        self.uia = UiaController()

    def _is_spotify_running(self) -> bool:
        if not PSUTIL_AVAILABLE:
            return False
        for proc in psutil.process_iter(['name']):
            if proc.info['name'] and proc.info['name'].lower() == 'spotify.exe':
                return True
        return False

    def play(self, query: str, service: str = "spotify") -> str:
        """Play a song/artist/playlist using the given service."""
        lower_service = service.lower()

        if lower_service == "spotify":
            if self._is_spotify_running():
                try:
                    # Bring Spotify to front and automate
                    if self.uia.find_window_by_title("Spotify"):
                        import time
                        # Click search (Ctrl+K or similar in Spotify, or find search box)
                        # We'll use the UIA controller to find the "Search" box
                        success = self.uia.set_focus_and_type("Spotify", "Search", query)
                        if success:
                            time.sleep(0.5)
                            self.uia.send_enter_key("Spotify")
                            time.sleep(1.0)
                            # Assuming "Play" or "Top result" can be invoked or hit Enter again
                            # For simplicity, sending a second Enter on the search result or invoking "Play"
                            # We can just try to press Tab and Enter or use media keys
                            # A simple play pause media key can work if Spotify is focused
                            self.uia.send_enter_key("Spotify")
                            return f"Playing '{query}' on Spotify."
                except Exception as e:
                    logger.warning(f"Spotify UI automation failed: {e}")
            
            # Fallback to web
            url = f"https://open.spotify.com/search/{query.replace(' ', '%20')}"
            self._open_url(url)
            return f"Opened Spotify web search for '{query}'."

        elif lower_service == "youtube":
            url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
            self._open_url(url)
            return f"Searching YouTube for '{query}'."

        else:
            url = f"https://www.google.com/search?q={query.replace(' ', '+')}+music"
            self._open_url(url)
            return f"Searching web for '{query}'."

    def pause(self, service: str = "spotify") -> str:
        """Pause media."""
        # The easiest way to pause media system-wide is sending VK_MEDIA_PLAY_PAUSE
        # But we cannot easily import windows_sys here since it's a rust dependency, not a python one.
        # Let's use powershell to press media play pause.
        try:
            import ctypes
            # VK_MEDIA_PLAY_PAUSE is 0xB3
            ctypes.windll.user32.keybd_event(0xB3, 0, 0, 0)
            ctypes.windll.user32.keybd_event(0xB3, 0, 0x0002, 0)
            return "Toggled play/pause."
        except Exception:
            return "Failed to toggle media."

    def _open_url(self, url: str) -> None:
        if os.name == 'nt':
            os.startfile(url)
        else:
            subprocess.Popen(['xdg-open', url])
