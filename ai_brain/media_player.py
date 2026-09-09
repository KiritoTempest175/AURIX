"""AURIX AI Brain — Media Player Integration via PyAutoGUI.

Controls local media playback (Spotify & YouTube Music) using native 
Windows media keys and official UI keyboard shortcuts.
"""

import os
import time
import urllib.parse
import logging

try:
    import pyautogui
    pyautogui.PAUSE = 0.15 
    pyautogui.FAILSAFE = True
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

logger = logging.getLogger("aurix.ai_brain.media_player")

# ─── TIMING & UI TARGETING CONFIGURATION ─────────────────────────────
SPOTIFY_LOAD_DELAY = 4.0      # Increased for first-time cold boots
SPOTIFY_SEARCH_DELAY = 1.5    
SPOTIFY_PAGE_DELAY = 1.0      
YT_MUSIC_LOAD_DELAY = 6.0     # Increased for browser cold boots
YT_MUSIC_SEARCH_DELAY = 2.0   # Wait for search results to load
YT_MUSIC_TAB_COUNT = 4        # Adjusted for the '/' shortcut starting position
# ─────────────────────────────────────────────────────────────────────

class MediaPlayer:
    """Automates media playback via desktop apps or web fallback."""

    def __init__(self):
        pass

    # Note: Global Windows media keys are used here instead of app-specific 
    # shortcuts (like 'J' or 'Space') so Luna can control the music even 
    # when the app is minimized in the background.
    def toggle_playback(self) -> str:
        if not PYAUTOGUI_AVAILABLE: return "PyAutoGUI not installed."
        pyautogui.press("playpause")
        return "Toggled play/pause."

    def next_track(self) -> str:
        if not PYAUTOGUI_AVAILABLE: return "PyAutoGUI not installed."
        pyautogui.press("nexttrack")
        return "Skipped to next track."

    def prev_track(self) -> str:
        if not PYAUTOGUI_AVAILABLE: return "PyAutoGUI not installed."
        pyautogui.press("prevtrack")
        return "Returned to previous track."

    def play(self, query: str, service: str = "spotify") -> str:
        if not PYAUTOGUI_AVAILABLE:
            return "PyAutoGUI not installed."

        service = service.lower().strip()
        if service == "spotify":
            return self._play_spotify(query)
        elif service in ["youtube", "yt", "youtube music", "yt music"]:
            return self._play_youtube_music(query)
        else:
            return f"Service '{service}' is not supported yet."

    def start_spotify_dj(self) -> str:
        logger.info("MediaPlayer: Attempting to launch Spotify DJ.")
        try:
            os.startfile("spotify:")
            time.sleep(SPOTIFY_LOAD_DELAY)
            
            # Use official shortcut: Go to Made For You (Alt + Shift + M)
            pyautogui.hotkey("alt", "shift", "m")
            time.sleep(1.5)
            
            # The DJ is typically the first card on the Made For You page
            pyautogui.press("tab")
            time.sleep(0.2)
            
            # First Enter: Opens the DJ
            pyautogui.press("enter")
            time.sleep(SPOTIFY_PAGE_DELAY)
            
            # Second Enter: Starts playback
            pyautogui.press("enter")
            
            return "Started Spotify DJ via Made For You shortcut."
        except Exception as e:
            return f"Spotify DJ automation failed: {e}"

    def _play_spotify(self, query: str) -> str:
        logger.info("MediaPlayer: Attempting to play '%s' on Spotify.", query)
        
        try:
            os.startfile("spotify:")
            time.sleep(SPOTIFY_LOAD_DELAY)
            
            # Use official shortcut: Open Quick Search (Ctrl + K)
            pyautogui.hotkey("ctrl", "k")
            time.sleep(0.5)
            
            # Type the query
            pyautogui.write(query, interval=0.03)
            time.sleep(SPOTIFY_SEARCH_DELAY)
            
            # First Enter: Opens the top result (Playlist, Album, Artist, etc.)
            pyautogui.press("enter")
            time.sleep(SPOTIFY_PAGE_DELAY)
            
            # Second Enter: Starts playing the track/playlist
            pyautogui.press("enter")
            
            return f"Playing '{query}' on Spotify Desktop."
            
        except Exception as e:
            logger.error("Spotify automation failed: %s", e)
            return f"Spotify UI automation failed: {e}"

    def _play_youtube_music(self, query: str) -> str:
        logger.info("MediaPlayer: Attempting to play '%s' on YT Music.", query)
        
        try:
            # 1. Launch the base YT Music homepage
            os.startfile("https://music.youtube.com")
            time.sleep(YT_MUSIC_LOAD_DELAY)
            
            # 2. Use official shortcut: Open Search (/)
            pyautogui.press("/")
            time.sleep(0.5)
            
            # 3. Type query and search
            pyautogui.write(query, interval=0.03)
            time.sleep(0.3)
            pyautogui.press("enter")
            time.sleep(YT_MUSIC_SEARCH_DELAY)
            
            # 4. Tab from the search bar down to the Top Result play button
            for _ in range(YT_MUSIC_TAB_COUNT):
                pyautogui.press("tab")
                time.sleep(0.15) 
                
            pyautogui.press("enter")
            return f"Playing '{query}' on YouTube Music."
            
        except Exception as e:
            logger.error("YouTube Music automation failed: %s", e)
            return f"YouTube Music automation failed: {e}"


def media_player(parameters: dict, response=None, player=None, session_memory=None) -> str:
    params = parameters or {}
    action = params.get("action", "play").lower().strip()
    query = params.get("query", "").strip()
    service = params.get("service", "spotify").strip()

    player_ctrl = MediaPlayer()

    if action in ["pause", "playpause", "stop"]:
        result = player_ctrl.toggle_playback()
    elif action in ["next", "skip"]:
        result = player_ctrl.next_track()
    elif action in ["prev", "previous", "back"]:
        result = player_ctrl.prev_track()
    elif action == "dj":
        result = player_ctrl.start_spotify_dj()
    elif action == "play":
        if not query:
            result = player_ctrl.toggle_playback()
        else:
            result = player_ctrl.play(query, service)
    else:
        result = f"Unknown media action: '{action}'"

    if player:
        player.write_log(f"[Media] {result}")

    print(f"[MediaPlayer] 🎵 {result}")
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(levelname)s: %(message)s")
    print("AURIX Media Player Test Mode (Type 'exit' to quit)")
    controller = MediaPlayer()

    while True:
        try:
            raw_input = input("\n[Media Player] >>> ").strip()
            if not raw_input or raw_input.lower() in ["exit", "quit"]: break

            if raw_input.lower().startswith("play "):
                print(controller.play(raw_input[5:].strip(), "spotify"))
            elif raw_input.lower().startswith("yt "):
                print(controller.play(raw_input[3:].strip(), "youtube"))
            elif raw_input.lower() == "dj":
                print(controller.start_spotify_dj())
            elif raw_input.lower() in ["pause", "resume", "playpause", "stop"]:
                print(controller.toggle_playback())
            elif raw_input.lower() in ["next", "skip"]:
                print(controller.next_track())
            elif raw_input.lower() in ["prev", "back", "previous"]:
                print(controller.prev_track())
            else:
                print("Commands: play <query>, yt <query>, dj, pause, next, prev")

        except KeyboardInterrupt:
            break