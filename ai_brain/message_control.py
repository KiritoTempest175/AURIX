"""AURIX AI Brain -- WhatsApp Desktop Controller (Message & Call).

Optimized hybrid version using the robust OS-level AppLauncher and reliable
PyAutoGUI keyboard shortcuts (Ctrl+N for global search).

NOTE: The two-turn confirmation security and calling features are currently 
COMMENTED OUT for testing purposes. Messages will send instantly.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional, Protocol

try:
    import pyautogui
    pyautogui.PAUSE = 0.1
    pyautogui.FAILSAFE = True
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

logger = logging.getLogger("aurix.ai_brain.whatsapp_control")

# ═══════════════════════════════════════════════════════════════════════════
#  Protocols matching the BrainDispatcher
# ═══════════════════════════════════════════════════════════════════════════

class AppLauncherProtocol(Protocol):
    def launch(self, target: str) -> str: ...

class ProcessCheckerProtocol(Protocol):
    def is_running(self, process_names: tuple) -> bool: ...

class WhatsAppUIError(RuntimeError):
    pass

class WhatsAppLaunchError(RuntimeError):
    pass

@dataclass
class PendingWhatsAppAction:
    """Represents a resolved-but-not-yet-executed send or call."""
    kind: str  # "message" | "call"
    matched_contact: str
    message: Optional[str] = None
    video: bool = False

@dataclass
class ActionResult:
    status: str  # "sent" | "called" | "error"
    detail: str
    matched_contact: Optional[str] = None

class WhatsAppController:
    def __init__(
        self,
        actuator=None,
        app_launcher: AppLauncherProtocol = None,
        process_checker: ProcessCheckerProtocol = None,
        element_timeout_ms: int = 4000,
    ) -> None:
        self.app_launcher = app_launcher
        self.process_checker = process_checker
        logger.info("WhatsAppController initialized (Security: DISABLED)")

    # ── INSTANT EXECUTION (Security Bypassed for Testing) ─────────────────

    def send_message_direct(self, contact_query: str, message: str) -> ActionResult:
        """
        Instantly searches for the contact and sends the message.
        Bypasses the two-turn confirmation block.
        """
        if not PYAUTOGUI_AVAILABLE:
            raise WhatsAppLaunchError("PyAutoGUI is required but not installed.")
            
        self._ensure_running()
        
        # 1. Search and open contact
        matched_name = self._search_and_open_contact(contact_query)
        
        # 2. Instantly type and send
        try:
            time.sleep(0.3)
            pyautogui.write(message, interval=0.02)
            time.sleep(0.3)
            pyautogui.press("enter")
        except Exception as e:
            logger.error("WhatsApp send failed for '%s': %s", matched_name, e)
            return ActionResult(
                status="error",
                detail=f"Automation failed while sending: {e}",
                matched_contact=matched_name,
            )

        logger.info("WhatsApp message sent instantly to '%s'", matched_name)
        return ActionResult(status="sent", detail="Message sent successfully.", matched_contact=matched_name)


    # ── SECURE METHODS (Currently Commented Out) ──────────────────────────
    """
    def prepare_message(self, contact_query: str, message: str) -> PendingWhatsAppAction:
        if not PYAUTOGUI_AVAILABLE:
            raise WhatsAppLaunchError("PyAutoGUI is required but not installed.")
            
        self._ensure_running()
        matched_name = self._search_and_open_contact(contact_query)
        return PendingWhatsAppAction(kind="message", matched_contact=matched_name, message=message)

    def prepare_call(self, contact_query: str, video: bool = False) -> PendingWhatsAppAction:
        if not PYAUTOGUI_AVAILABLE:
            raise WhatsAppLaunchError("PyAutoGUI is required but not installed.")
            
        self._ensure_running()
        matched_name = self._search_and_open_contact(contact_query)
        return PendingWhatsAppAction(kind="call", matched_contact=matched_name, video=video)

    def execute(self, pending: PendingWhatsAppAction) -> ActionResult:
        self._ensure_running()
        
        if pending.kind == "message":
            return self._execute_message(pending)
        elif pending.kind == "call":
            return self._execute_call(pending)
        raise ValueError(f"Unknown pending action kind: {pending.kind!r}")

    def _execute_message(self, pending: PendingWhatsAppAction) -> ActionResult:
        try:
            time.sleep(0.3)
            pyautogui.write(pending.message, interval=0.02)
            time.sleep(0.3)
            pyautogui.press("enter")
        except Exception as e:
            return ActionResult(status="error", detail=f"Failed: {e}", matched_contact=pending.matched_contact)
        return ActionResult(status="sent", detail="Message sent.", matched_contact=pending.matched_contact)

    def _execute_call(self, pending: PendingWhatsAppAction) -> ActionResult:
        call_kind = "video call" if pending.video else "voice call"
        try:
            if pending.video:
                pyautogui.hotkey("ctrl", "shift", "v")
            else:
                pyautogui.hotkey("ctrl", "shift", "c")
            time.sleep(0.5)
        except Exception as e:
            return ActionResult(status="error", detail=f"Failed: {e}", matched_contact=pending.matched_contact)
        return ActionResult(status="called", detail=f"{call_kind.capitalize()} placed.", matched_contact=pending.matched_contact)
    """

    # ── Internal helpers ─────────────────────────────────────────────────

    def _ensure_running(self) -> None:
        """
        Uses the AppLauncher URI (whatsapp:) to instantly open or focus 
        the WhatsApp window without duplicating processes.
        """
        if self.app_launcher:
            self.app_launcher.launch("whatsapp")
        else:
            pyautogui.press("win")
            time.sleep(0.4)
            pyautogui.write("whatsapp", interval=0.04)
            time.sleep(0.5)
            pyautogui.press("enter")
            
        time.sleep(1.5)

    def _search_and_open_contact(self, contact_query: str) -> str:
        """
        Uses Ctrl+N to force global contact search, bypassing active chats.
        """
        try:
            # Ctrl+N guarantees we hit "Search or start a new chat"
            pyautogui.hotkey("ctrl", "n")
            time.sleep(0.6)
            
            # Type contact name
            pyautogui.write(contact_query, interval=0.03)
            time.sleep(1.2) # Wait for WhatsApp contact list to filter
            
            # Press enter to open the chat
            pyautogui.press("enter")
            time.sleep(0.6)
            
            return contact_query.title()
        except Exception as e:
            raise WhatsAppUIError(f"Failed to search for contact: {e}") from e

# ═══════════════════════════════════════════════════════════════════════════
#  Standalone Test Block
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    import os
    
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(levelname)s: %(message)s")
    
    print("=" * 60)
    print("AURIX WhatsApp Control - DIRECT TEST MODE")
    print("Commands:")
    print("  'message <contact> <text>'  - Instantly sends a text message")
    print("  'exit'                      - Quits the test mode")
    print("=" * 60)

    try:
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
        from ai_brain.app_control import AppLauncher
        launcher = AppLauncher()
    except ImportError:
        logger.warning("Could not import AppLauncher. Falling back to native PyAutoGUI window launch.")
        launcher = None

    whatsapp = WhatsAppController(app_launcher=launcher)

    while True:
        try:
            user_input = input("\n[Test Mode] >>> ").strip()
            
            if not user_input:
                continue
                
            if user_input.lower() in ["exit", "quit"]:
                print("Exiting test mode.")
                break
                
            if user_input.lower().startswith("message "):
                parts = user_input[8:].strip().split(" ", 1)
                if len(parts) == 2:
                    contact, msg = parts
                    print(f"Instantly sending message to {contact}...")
                    result = whatsapp.send_message_direct(contact, msg)
                    print(f"Result: {result.status} | {result.detail}")
                else:
                    print("Invalid format. Use: message <contact> <text>")
                    
            # ── CALLING FEATURES COMMENTED OUT ──
            # elif user_input.lower().startswith("call "):
            #     print("Calling features are currently disabled.")
            # elif user_input.lower().startswith("video call "):
            #     print("Video Calling features are currently disabled.")
                
            else:
                print("Invalid command. Please use 'message' or 'exit'.")
                
        except KeyboardInterrupt:
            print("\nExiting test mode.")
            break
        except Exception as e:
            print(f"\nAn error occurred: {e}")