"""AURIX AI Brain -- Secure WhatsApp Desktop Controller.

Security flow:

User request
    ↓
ToolExecutor
    ↓
PermissionManager / Trust Token
    ↓
WhatsApp contact search
    ↓
Recipient verification through Windows UI Automation
    ↓
execute(..., authorized=True)
    ↓
Physical message/call

Security rules:
- Direct sending is disabled.
- Search result alone is NOT trusted.
- Selected chat header must match requested contact.
- Recipient is verified again immediately before send/call.
- Verification failure blocks the action.
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata

from dataclasses import dataclass
from typing import Optional, Protocol


# ================================================================
# PYAUTOGUI
# ================================================================

try:
    import pyautogui

    pyautogui.PAUSE = 0.1
    pyautogui.FAILSAFE = True

    PYAUTOGUI_AVAILABLE = True

except ImportError:
    pyautogui = None
    PYAUTOGUI_AVAILABLE = False


# ================================================================
# WINDOWS UI AUTOMATION
# ================================================================

try:
    from pywinauto import Desktop

    UIA_AVAILABLE = True

except ImportError:
    Desktop = None
    UIA_AVAILABLE = False


logger = logging.getLogger(
    "aurix.ai_brain.whatsapp_control"
)


# ================================================================
# PROTOCOLS
# ================================================================

class AppLauncherProtocol(Protocol):

    def launch(
        self,
        target: str,
    ) -> str:
        ...


class ProcessCheckerProtocol(Protocol):

    def is_running(
        self,
        process_names: tuple,
    ) -> bool:
        ...


# ================================================================
# ERRORS
# ================================================================

class WhatsAppUIError(RuntimeError):
    pass


class WhatsAppLaunchError(RuntimeError):
    pass


# ================================================================
# ACTION MODELS
# ================================================================

@dataclass(frozen=True)
class PendingWhatsAppAction:

    kind: str

    # Name AURIX actually verified from the selected chat.
    matched_contact: str

    # Original contact requested by user/model.
    requested_contact: Optional[str] = None

    message: Optional[str] = None

    video: bool = False


@dataclass
class ActionResult:

    status: str

    detail: str

    matched_contact: Optional[str] = None


# ================================================================
# CONTROLLER
# ================================================================

class WhatsAppController:

    def __init__(
        self,
        actuator=None,
        app_launcher: Optional[
            AppLauncherProtocol
        ] = None,
        process_checker: Optional[
            ProcessCheckerProtocol
        ] = None,
        element_timeout_ms: int = 4000,
    ) -> None:

        self.app_launcher = app_launcher

        self.process_checker = (
            process_checker
        )

        self.element_timeout_ms = (
            element_timeout_ms
        )

        logger.info(
            "WhatsAppController initialized "
            "(Security: ENABLED, "
            "Recipient Verification: ENABLED)"
        )

    # ============================================================
    # DIRECT SEND -- BLOCKED
    # ============================================================

    def send_message_direct(
        self,
        contact_query: str,
        message: str,
    ) -> ActionResult:

        contact_query = str(
            contact_query or ""
        ).strip()

        logger.warning(
            "Blocked direct WhatsApp "
            "send attempt to '%s'.",
            contact_query,
        )

        return ActionResult(
            status="blocked",
            detail=(
                "Direct WhatsApp sending is disabled. "
                "Use the AURIX ToolExecutor approval flow."
            ),
        )

    # ============================================================
    # PREPARE MESSAGE
    # ============================================================

    def prepare_message(
        self,
        contact_query: str,
        message: str,
    ) -> PendingWhatsAppAction:

        self._require_pyautogui()

        contact_query = str(
            contact_query or ""
        ).strip()

        message = str(
            message or ""
        )

        if not contact_query:

            raise ValueError(
                "WhatsApp contact cannot be empty."
            )

        if not message.strip():

            raise ValueError(
                "WhatsApp message cannot be empty."
            )

        self._ensure_running()

        self._search_and_open_contact(
            contact_query
        )

        # Do not trust the search query itself.
        # Verify actual selected chat.
        matched_contact = (
            self._verify_selected_contact(
                contact_query
            )
        )

        return PendingWhatsAppAction(
            kind="message",
            requested_contact=contact_query,
            matched_contact=matched_contact,
            message=message,
        )

    # ============================================================
    # PREPARE CALL
    # ============================================================

    def prepare_call(
        self,
        contact_query: str,
        video: bool = False,
    ) -> PendingWhatsAppAction:

        self._require_pyautogui()

        contact_query = str(
            contact_query or ""
        ).strip()

        if not contact_query:

            raise ValueError(
                "WhatsApp contact cannot be empty."
            )

        self._ensure_running()

        self._search_and_open_contact(
            contact_query
        )

        matched_contact = (
            self._verify_selected_contact(
                contact_query
            )
        )

        return PendingWhatsAppAction(
            kind="call",
            requested_contact=contact_query,
            matched_contact=matched_contact,
            video=bool(video),
        )

    # ============================================================
    # EXECUTE
    # ============================================================

    def execute(
        self,
        pending: PendingWhatsAppAction,
        *,
        authorized: bool = False,
    ) -> ActionResult:
        """Execute only after authorization + recipient re-verification."""

        # --------------------------------------------------------
        # CENTRAL SECURITY CHECK
        # --------------------------------------------------------

        if not authorized:

            logger.warning(
                "Blocked WhatsApp execution "
                "without central authorization."
            )

            return ActionResult(
                status="blocked",
                detail=(
                    "WhatsApp action blocked: "
                    "central AURIX approval is required."
                ),
                matched_contact=(
                    pending.matched_contact
                    if isinstance(
                        pending,
                        PendingWhatsAppAction,
                    )
                    else None
                ),
            )

        if not isinstance(
            pending,
            PendingWhatsAppAction,
        ):

            return ActionResult(
                status="error",
                detail=(
                    "Invalid WhatsApp action."
                ),
            )

        self._require_pyautogui()

        self._ensure_running()

        requested_contact = (
            pending.requested_contact
            or pending.matched_contact
        )

        # --------------------------------------------------------
        # SECOND RECIPIENT VERIFICATION
        #
        # Important:
        # The user/chat might have changed between prepare and send.
        # --------------------------------------------------------

        try:

            current_contact = (
                self._verify_selected_contact(
                    requested_contact
                )
            )

        except WhatsAppUIError as exc:

            logger.warning(
                "Recipient verification failed "
                "before execution: %s",
                exc,
            )

            return ActionResult(
                status="blocked",
                detail=(
                    "WhatsApp action blocked: "
                    "recipient verification failed. "
                    f"{exc}"
                ),
                matched_contact=(
                    pending.matched_contact
                ),
            )

        # --------------------------------------------------------
        # CHAT CHANGED?
        # --------------------------------------------------------

        if not self._contact_names_match(
            pending.matched_contact,
            current_contact,
        ):

            logger.warning(
                "WhatsApp selected chat changed "
                "from '%s' to '%s'.",
                pending.matched_contact,
                current_contact,
            )

            return ActionResult(
                status="blocked",
                detail=(
                    "WhatsApp action blocked: "
                    "selected chat changed after approval."
                ),
                matched_contact=current_contact,
            )

        # --------------------------------------------------------
        # PHYSICAL ACTION
        # --------------------------------------------------------

        if pending.kind == "message":

            return self._execute_message(
                pending
            )

        if pending.kind == "call":

            return self._execute_call(
                pending
            )

        return ActionResult(
            status="error",
            detail=(
                f"Unknown WhatsApp action kind: "
                f"{pending.kind!r}"
            ),
            matched_contact=(
                pending.matched_contact
            ),
        )

    # ============================================================
    # SEND MESSAGE
    # ============================================================

    def _execute_message(
        self,
        pending: PendingWhatsAppAction,
    ) -> ActionResult:

        message = str(
            pending.message or ""
        )

        if not message.strip():

            return ActionResult(
                status="error",
                detail=(
                    "WhatsApp message is empty."
                ),
                matched_contact=(
                    pending.matched_contact
                ),
            )

        try:

            time.sleep(
                0.25
            )

            self._focus_message_composer()
            if message.isascii():
                pyautogui.write(message, interval=0.012)
            else:
                import pyperclip
                previous = pyperclip.paste()
                try:
                    pyperclip.copy(message)
                    pyautogui.hotkey("ctrl", "v")
                finally:
                    pyperclip.copy(previous)
            time.sleep(0.2)
            pyautogui.press("enter")

        except Exception as exc:

            logger.exception(
                "WhatsApp send failed for "
                "verified contact '%s'.",
                pending.matched_contact,
            )

            return ActionResult(
                status="error",
                detail=(
                    "Failed to send WhatsApp message: "
                    f"{exc}"
                ),
                matched_contact=(
                    pending.matched_contact
                ),
            )

        logger.info(
            "WhatsApp message sent to "
            "verified contact '%s'.",
            pending.matched_contact,
        )

        return ActionResult(
            status="sent",
            detail="Message sent.",
            matched_contact=(
                pending.matched_contact
            ),
        )

    # ============================================================
    # START CALL
    # ============================================================

    def _execute_call(
        self,
        pending: PendingWhatsAppAction,
    ) -> ActionResult:

        call_kind = (
            "video call"
            if pending.video
            else "voice call"
        )

        try:

            if pending.video:

                pyautogui.hotkey(
                    "ctrl",
                    "shift",
                    "v",
                )

            else:

                pyautogui.hotkey(
                    "ctrl",
                    "shift",
                    "c",
                )

            time.sleep(
                0.5
            )

        except Exception as exc:

            logger.exception(
                "WhatsApp %s failed for '%s'.",
                call_kind,
                pending.matched_contact,
            )

            return ActionResult(
                status="error",
                detail=(
                    f"Failed to start {call_kind}: "
                    f"{exc}"
                ),
                matched_contact=(
                    pending.matched_contact
                ),
            )

        return ActionResult(
            status="called",
            detail=(
                f"{call_kind.capitalize()} placed."
            ),
            matched_contact=(
                pending.matched_contact
            ),
        )

    # ============================================================
    # CONTACT NORMALIZATION
    # ============================================================

    @staticmethod
    def _normalize_contact_name(
        value: str,
    ) -> str:

        normalized = (
            unicodedata.normalize(
                "NFKC",
                str(
                    value or ""
                ),
            )
        )

        normalized = re.sub(
            r"\s+",
            " ",
            normalized,
        )

        return (
            normalized
            .strip()
            .casefold()
        )

    # ============================================================
    # PHONE NORMALIZATION
    # ============================================================

    @staticmethod
    def _phone_digits(
        value: str,
    ) -> Optional[str]:

        raw = str(
            value or ""
        ).strip()

        if not raw:
            return None

        # Only treat actual phone-looking text as number.
        if not re.fullmatch(
            r"[+\d\s().-]+",
            raw,
        ):
            return None

        digits = re.sub(
            r"\D",
            "",
            raw,
        )

        if len(digits) < 7:
            return None

        return digits

    # ============================================================
    # EXACT CONTACT MATCH
    # ============================================================

    @classmethod
    def _contact_names_match(
        cls,
        requested: str,
        actual: str,
    ) -> bool:

        requested_phone = (
            cls._phone_digits(
                requested
            )
        )

        actual_phone = (
            cls._phone_digits(
                actual
            )
        )

        if (
            requested_phone is not None
            and actual_phone is not None
        ):

            return (
                requested_phone
                == actual_phone
            )

        return (
            cls._normalize_contact_name(
                requested
            )
            == cls._normalize_contact_name(
                actual
            )
        )

    # ============================================================
    # DEPENDENCY CHECKS
    # ============================================================

    @staticmethod
    def _require_pyautogui() -> None:

        if not PYAUTOGUI_AVAILABLE:

            raise WhatsAppLaunchError(
                "PyAutoGUI is required for "
                "WhatsApp automation."
            )

    @staticmethod
    def _require_uia() -> None:

        if not UIA_AVAILABLE:

            raise WhatsAppUIError(
                "Recipient verification unavailable: "
                "pywinauto is not installed."
            )

    # ============================================================
    # FIND WHATSAPP WINDOW
    # ============================================================

    def _get_whatsapp_window(
        self,
    ):
        """Locate visible WhatsApp Desktop window."""

        self._require_uia()

        try:

            desktop = Desktop(
                backend="uia"
            )

            matches = []

            for window in desktop.windows():

                try:

                    title = str(
                        window.window_text()
                        or ""
                    ).strip()

                    if (
                        "whatsapp"
                        in title.casefold()
                    ):

                        matches.append(
                            window
                        )

                except Exception:
                    continue

            if not matches:

                raise WhatsAppUIError(
                    "Could not find the "
                    "WhatsApp Desktop window."
                )

            # Prefer largest visible WhatsApp window.
            visible = []

            for window in matches:

                try:

                    if not window.is_visible():
                        continue

                    rect = (
                        window.rectangle()
                    )

                    area = (
                        max(
                            rect.width(),
                            0,
                        )
                        * max(
                            rect.height(),
                            0,
                        )
                    )

                    visible.append(
                        (
                            area,
                            window,
                        )
                    )

                except Exception:
                    continue

            if visible:

                visible.sort(
                    key=lambda item: item[0],
                    reverse=True,
                )

                return visible[
                    0
                ][1]

            return matches[0]

        except WhatsAppUIError:
            raise

        except Exception as exc:

            raise WhatsAppUIError(
                "Unable to inspect WhatsApp "
                "through Windows UI Automation: "
                f"{exc}"
            ) from exc

    # ============================================================
    # READ CHAT HEADER
    # ============================================================

    def _collect_chat_header_texts(self) -> list[str]:
        """Read only active-chat toolbar labels (Text or Button roles).

        Dates in the message pane and names in the left-hand contact list
        must never authorize outbound messages.
        """
        window = self._get_whatsapp_window()
        outer = window.rectangle()
        left = outer.left + int(max(outer.width(), 1) * 0.35)
        bottom = outer.top + min(120, max(70, int(max(outer.height(), 1) * .15)))
        labels = []
        # WhatsApp releases expose the chat title as Text, Button or Group;
        # only inspect the top-right chat toolbar, never the conversation.
        for kind in ("Text", "Button", "Group", "Hyperlink"):
            for element in window.descendants(control_type=kind):
                try:
                    if not element.is_visible():
                        continue
                    rect = element.rectangle()
                    if rect.left < left or not outer.top + 6 <= rect.top <= bottom:
                        continue
                    value = str(element.window_text() or "").strip()
                    if not value:
                        value = str(getattr(element.element_info, "name", "") or "").strip()
                    if not value or len(value) > 180:
                        continue
                    if value.casefold() in {
                        "monday", "tuesday", "wednesday", "thursday",
                        "friday", "saturday", "sunday", "today", "yesterday",
                        "search", "video call", "voice call", "menu"
                    }:
                        continue
                    if value not in labels:
                        labels.append(value)
                except Exception:
                    continue
        return labels

    # ============================================================
    # VERIFY SELECTED CONTACT
    # ============================================================

    def _verify_selected_contact(
        self,
        requested_contact: str,
    ) -> str:
        """Verify actual selected chat using Windows UI text."""

        requested_contact = str(
            requested_contact or ""
        ).strip()

        if not requested_contact:

            raise WhatsAppUIError(
                "Recipient verification received "
                "an empty contact."
            )

        self._require_uia()

        timeout_seconds = max(
            1.0,
            self.element_timeout_ms
            / 1000.0,
        )

        deadline = (
            time.monotonic()
            + timeout_seconds
        )

        last_texts = []

        while (
            time.monotonic()
            < deadline
        ):

            header_texts = (
                self._collect_chat_header_texts()
            )

            last_texts = (
                header_texts
            )

            matches = [
                text
                for text in header_texts
                if self._header_matches_contact(
                    requested_contact,
                    text,
                )
            ]

            if len(matches) == 1:

                logger.info(
                    "Verified WhatsApp recipient: "
                    "requested='%s' selected='%s'",
                    requested_contact,
                    matches[0],
                )

                return matches[0]

            if len(matches) > 1:

                raise WhatsAppUIError(
                    "Multiple matching recipient "
                    "labels were detected."
                )

            time.sleep(
                0.25
            )

        preview = ", ".join(
            repr(
                text
            )
            for text in last_texts[:8]
        )

        if not preview:

            preview = (
                "<no readable chat-header text>"
            )

        raise WhatsAppUIError(
            "Selected chat could not be verified "
            f"as '{requested_contact}'. "
            f"Accessible toolbar labels: {preview}. "
            "Open the exact contact in WhatsApp Desktop, maximize the window, "
            "and retry. Sending is blocked until the recipient can be verified."
        )

    # ============================================================
    # ENSURE WHATSAPP RUNNING
    # ============================================================

    @classmethod
    def _header_matches_contact(cls, expected: str, label: str) -> bool:
        """Allow exact contact names and UIA profile-button descriptions."""
        if cls._contact_names_match(expected, label):
            return True
        expected_name = cls._normalize_contact_name(expected)
        label_name = cls._normalize_contact_name(label)
        return bool(expected_name) and (
            label_name.startswith(expected_name + ", contact info")
            or label_name.startswith(expected_name + ", view profile")
            or label_name.startswith(expected_name + " - contact info")
        )

    def _focus_message_composer(self) -> None:
        window = self._get_whatsapp_window()
        bounds = window.rectangle()
        bottom = bounds.top + int(max(bounds.height(), 1) * .66)
        left = bounds.left + int(max(bounds.width(), 1) * .31)
        inputs = []
        for kind in ("Edit", "Document"):
            for element in window.descendants(control_type=kind):
                try:
                    if not element.is_visible():
                        continue
                    rect = element.rectangle()
                    if rect.top < bottom or rect.left < left:
                        continue
                    label = str(element.window_text() or getattr(element.element_info, "name", "") or "").casefold()
                    if any(term in label for term in ("message", "type", "compose")):
                        inputs.append(element)
                except Exception:
                    continue
        if len(inputs) != 1:
            raise WhatsAppUIError(
                "Cannot safely identify the WhatsApp message box. "
                "Open the intended chat and try again."
            )
        inputs[0].click_input()

    def _ensure_running(
        self,
    ) -> None:

        self._require_pyautogui()

        if self.process_checker:

            try:

                running = (
                    self.process_checker.is_running(
                        (
                            "WhatsApp.exe",
                            "WhatsApp",
                        )
                    )
                )

                if (
                    running
                    and self.app_launcher
                ):

                    self.app_launcher.launch(
                        "whatsapp"
                    )

                    time.sleep(
                        0.8
                    )

                    return

            except Exception as exc:

                logger.debug(
                    "WhatsApp process "
                    "check failed: %s",
                    exc,
                )

        if self.app_launcher:

            self.app_launcher.launch(
                "whatsapp"
            )

        else:

            pyautogui.press(
                "win"
            )

            time.sleep(
                0.4
            )

            pyautogui.write(
                "whatsapp",
                interval=0.04,
            )

            time.sleep(
                0.5
            )

            pyautogui.press(
                "enter"
            )

        time.sleep(
            1.5
        )

    # ============================================================
    # SEARCH CONTACT
    # ============================================================

    def _search_and_open_contact(
        self,
        contact_query: str,
    ) -> None:
        """Search and open candidate contact.

        IMPORTANT:
        Opening first result does NOT count as verification.
        """

        self._require_pyautogui()

        contact_query = str(
            contact_query or ""
        ).strip()

        if not contact_query:

            raise WhatsAppUIError(
                "Contact search query is empty."
            )

        try:

            pyautogui.hotkey(
                "ctrl",
                "n",
            )

            time.sleep(
                0.6
            )

            # Clear any old search text.
            pyautogui.hotkey(
                "ctrl",
                "a",
            )

            pyautogui.write(
                contact_query,
                interval=0.03,
            )

            time.sleep(
                1.2
            )

            pyautogui.press(
                "enter"
            )

            time.sleep(
                0.7
            )

        except Exception as exc:

            raise WhatsAppUIError(
                "Failed to search/open "
                f"WhatsApp contact: {exc}"
            ) from exc


# ================================================================
# SAFE STANDALONE MODE
# ================================================================

if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "[%(name)s] "
            "%(levelname)s: %(message)s"
        ),
    )

    print("=" * 60)
    print("AURIX Secure WhatsApp Controller")
    print("=" * 60)

    print(
        "PyAutoGUI:",
        (
            "available"
            if PYAUTOGUI_AVAILABLE
            else "missing"
        ),
    )

    print(
        "Recipient verification:",
        (
            "available"
            if UIA_AVAILABLE
            else "missing - install pywinauto"
        ),
    )

    print(
        "Direct sending: BLOCKED"
    )

    print(
        "Use ToolExecutor for real WhatsApp actions."
    )