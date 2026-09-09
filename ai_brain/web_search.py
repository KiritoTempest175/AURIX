"""AURIX AI Brain — Web Search Integration via PyAutoGUI & Chrome Guest Mode.

Opens Google Chrome in Guest Mode to bypass profile selection screens,
navigates to Google, and executes the search query visually.
"""

import time
import logging
import subprocess
from typing import Any

try:
    import pyautogui
    pyautogui.PAUSE = 0.1
    pyautogui.FAILSAFE = True
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

logger = logging.getLogger("aurix.ai_brain.web_search")

class WebSearcher:
    """Performs visual web searches by automating Chrome in Guest Mode."""
    
    def __init__(self):
        pass

    def search(self, query: str) -> str:
        """Opens Chrome in Guest Mode and searches the query visually."""
        if not PYAUTOGUI_AVAILABLE:
            return "PyAutoGUI is required for visual web search but is not installed."

        if not query or not query.strip():
            return "Please provide a valid search query."

        clean_query = query.strip()
        logger.info("WebSearcher: Launching Chrome in Guest Mode for query: '%s'", clean_query)

        try:
            # 1. Launch Google Chrome explicitly in Guest Mode using Windows cmd 
            # This bypasses any user profile selection screen entirely.
            subprocess.Popen("start chrome --guest", shell=True)
            time.sleep(2.5)  # Wait for Chrome window to surface and initialize

            # 2. Focus address bar / search box or open google.com directly
            pyautogui.hotkey("ctrl", "l")
            time.sleep(0.3)
            pyautogui.write("https://www.google.com", interval=0.03)
            pyautogui.press("enter")
            time.sleep(2.0)  # Wait for Google homepage to load

            # 3. Type the search query into Google's search input and hit enter
            pyautogui.write(clean_query, interval=0.03)
            time.sleep(0.3)
            pyautogui.press("enter")

            return f"Successfully performed visual web search for: '{clean_query}'"

        except Exception as e:
            logger.error("WebSearcher failed execution: %s", e)
            return f"Web search automation failed: {e}"


def web_search(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    Called from main dispatcher/router.
    
    parameters:
        query : The search term string
    """
    params = parameters or {}
    query = params.get("query", "").strip()

    if not query:
        return "Please provide a search query, sir."

    if player:
        player.write_log(f"[Search] Visually searching: {query}")

    print(f"[WebSearch] 🔍 Visual Guest Mode Search Query: {query!r}")

    searcher = WebSearcher()
    result = searcher.search(query)

    print(f"[WebSearch] ✅ {result}")
    return result


# ═══════════════════════════════════════════════════════════════════════════
#  Standalone Interactive Test Mode
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(levelname)s: %(message)s")

    print("=" * 60)
    print("AURIX Web Search -- Standalone Test Mode")
    print("Commands:")
    print("  search <query>   - Opens Chrome Guest Mode and searches")
    print("  exit             - Quit")
    print("=" * 60)

    while True:
        try:
            raw_input = input("\n[Web Search] >>> ").strip()
            if not raw_input:
                continue

            cmd_lower = raw_input.lower()
            if cmd_lower in ["exit", "quit"]:
                print("Exiting test mode.")
                break

            if cmd_lower.startswith("search "):
                search_term = raw_input[7:].strip()
                # Wrap it in the parameters dictionary to mimic the actual router call
                result = web_search({"query": search_term})
                print(f"Result: {result}")
            else:
                print("Unknown command. Use 'search <query>' or 'exit'.")

        except KeyboardInterrupt:
            print("\nExiting test mode.")
            break
        except Exception as ex:
            print(f"\nError: {ex}")