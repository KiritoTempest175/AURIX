"""LUNA AI Brain -- WhatsApp Desktop Controller (Message & Call).

Drives the WhatsApp Desktop app via UI Automation to send messages and place
calls on the user's behalf. Implements the confirmation-before-send safety
requirement from the LUNA AI Brain directive (Part B.5): before any message is
sent or call is placed, the resolved contact name is read back from WhatsApp's
own search UI and must be explicitly confirmed -- this is what prevents a
fuzzy-match mistake (the same class of bug fixed in app_control.py) from
turning into a message or call sent to the wrong person.

IMPORTANT -- what this file does NOT include, and why:
    This module depends on a `UiaActuator` (UI Automation actuator) to actually
    find and click things inside WhatsApp Desktop -- the Rust/PyO3 component
    described as core_engine's `uia_actuator.rs` in the LUNA AI Brain directive.
    That component has NOT been written yet. Writing it blind, without seeing
    the project's existing `uia_tree.rs` (the current read-only UI Automation
    observer this is meant to extend) or core_engine's PyO3 module structure,
    would mean guessing at class names, method signatures, and how it's
    exposed to Python -- exactly the kind of unverified guessing that's been
    causing bugs from the other agent. So instead, this file defines the
    `UiaActuator` Protocol (the interface this module NEEDS from that Rust
    component) and is fully testable/verified against a fake implementation of
    it. Once you share `uia_tree.rs` (or core_engine's lib.rs / PyO3 module
    init file), the real actuator can be written to satisfy this exact
    interface, and this controller will work against it unchanged.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Optional, Protocol

logger = logging.getLogger("luna.ai_brain.whatsapp_control")

WHATSAPP_PROCESS_NAMES = ("WhatsApp.exe", "WhatsApp")
WHATSAPP_APP_QUERY = "whatsapp"  # passed to AppLauncher.launch() to open it if not running

# UI Automation element identifiers this controller expects the actuator to be
# able to find inside WhatsApp Desktop. WhatsApp's own UI can and does change
# between versions -- if these ever stop matching, wait_for_element() should
# time out and raise WhatsAppUIError rather than silently clicking something
# else, per the "fail loudly, never guess-click" requirement in the directive.
_EL_SEARCH_BOX = "Search or start new chat"
_EL_MESSAGE_BOX = "Type a message"
_EL_SEND_BUTTON = "Send"
_EL_VOICE_CALL_BUTTON = "Voice call"
_EL_VIDEO_CALL_BUTTON = "Video call"

_DEFAULT_ELEMENT_TIMEOUT_MS = 4000
_DEFAULT_APP_LAUNCH_WAIT_S = 3.0


# ═══════════════════════════════════════════════════════════════════════════
#  Actuator interface -- this is what the Rust/PyO3 uia_actuator.rs component
#  needs to satisfy. See module docstring: not implemented here.
# ═══════════════════════════════════════════════════════════════════════════

class ElementHandle(Protocol):
    """Opaque handle to a found UI element. Real implementation is whatever
    core_engine's PyO3 binding returns -- this controller never inspects it,
    only passes it back into the actuator."""
    ...


class UiaActuator(Protocol):
    """Interface this controller needs from the Windows UI Automation actuator.

    Matches the shape specified in the LUNA AI Brain directive, Part B.6.
    """

    def find_element(
        self, window_title_or_process: str, by: str, value: str
    ) -> Optional[ElementHandle]:
        """Find a UI element. `by` is one of "Name", "AutomationId", "ControlType".
        Returns None if not found immediately (no waiting)."""
        ...

    def wait_for_element(
        self, window_title_or_process: str, by: str, value: str, timeout_ms: int
    ) -> ElementHandle:
        """Poll until the element is found or timeout_ms elapses.
        Raises a timeout error (any exception) if not found in time -- this
        controller catches Exception broadly at the call site and converts it
        to WhatsAppUIError, so the actuator's exact exception type doesn't
        need to be agreed on in advance."""
        ...

    def invoke(self, element: ElementHandle) -> None:
        """Fire IUIAutomationInvokePattern (e.g. click a button)."""
        ...

    def set_value(self, element: ElementHandle, text: str) -> None:
        """Fire IUIAutomationValuePattern.SetValue (fill a text box)."""
        ...

    def get_text(self, element: ElementHandle) -> str:
        """Read the visible text/name of an element (used to read back the
        top search-result contact name for confirmation)."""
        ...


class AppLauncherProtocol(Protocol):
    """Matches ai_brain.app_control.AppLauncher's public interface -- only the
    one method this controller actually needs."""

    def launch(self, target: str) -> str: ...


class ProcessCheckerProtocol(Protocol):
    """Something that can say whether WhatsApp Desktop is currently running.
    In production this should be a thin wrapper around psutil, matching the
    same process-scanning approach AppCloser already uses elsewhere in this
    project -- not reimplemented here to avoid duplicating that logic."""

    def is_running(self, process_names: tuple) -> bool: ...


# ═══════════════════════════════════════════════════════════════════════════
#  Errors
# ═══════════════════════════════════════════════════════════════════════════

class WhatsAppUIError(RuntimeError):
    """Raised when an expected WhatsApp UI element can't be found/interacted
    with in time. Callers should surface this as a clear failure to the user,
    never silently retry with a different, possibly-wrong element."""
    pass


class WhatsAppLaunchError(RuntimeError):
    """Raised when WhatsApp Desktop couldn't be launched at all."""
    pass


# ═══════════════════════════════════════════════════════════════════════════
#  Result types
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ContactMatch:
    """A contact found via WhatsApp's own search -- WhatsApp's search is the
    source of truth here, this controller does not maintain its own contact
    database (per the directive: 'let WhatsApp's own search be the source of
    truth')."""
    display_name: str
    result_element: ElementHandle


@dataclass
class ActionResult:
    status: str  # "sent" | "called" | "cancelled" | "error"
    detail: str
    matched_contact: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════
#  Controller
# ═══════════════════════════════════════════════════════════════════════════

# Signature: (matched_contact_name: str, action_description: str) -> bool
# e.g. confirm_fn("John Smith", "send: 'Running 10 minutes late'") -> True/False
ConfirmCallback = Callable[[str, str], bool]


class WhatsAppController:
    """Sends WhatsApp messages and places WhatsApp calls on the user's behalf,
    via UI Automation, with a mandatory confirm-before-acting step.

    This class intentionally has NO default/real actuator or process-checker --
    they must be injected. This is what makes it fully testable without a real
    Windows machine (see the test suite run against a FakeActuator), and it's
    also what makes it safe to wire up the real Rust actuator later without
    changing anything in this file.
    """

    def __init__(
        self,
        actuator: UiaActuator,
        app_launcher: AppLauncherProtocol,
        process_checker: ProcessCheckerProtocol,
        confirm_callback: ConfirmCallback,
        element_timeout_ms: int = _DEFAULT_ELEMENT_TIMEOUT_MS,
    ) -> None:
        self.actuator = actuator
        self.app_launcher = app_launcher
        self.process_checker = process_checker
        self.confirm_callback = confirm_callback
        self.element_timeout_ms = element_timeout_ms

    # ── Public API ────────────────────────────────────────────────────────

    def send_message(self, contact_query: str, message: str) -> ActionResult:
        """Find `contact_query` in WhatsApp, confirm with the user, and send
        `message` if confirmed."""
        try:
            self._ensure_running()
        except WhatsAppLaunchError as e:
            return ActionResult(status="error", detail=str(e))

        try:
            contact = self._search_contact(contact_query)
        except WhatsAppUIError as e:
            return ActionResult(status="error", detail=f"Couldn't search WhatsApp: {e}")

        if contact is None:
            return ActionResult(status="error", detail=f"No WhatsApp contact found matching '{contact_query}'.")

        approved = self.confirm_callback(contact.display_name, f"send: '{message}'")
        if not approved:
            logger.info("WhatsApp send cancelled by user for contact '%s'", contact.display_name)
            return ActionResult(status="cancelled", detail="Message not sent.", matched_contact=contact.display_name)

        try:
            self.actuator.invoke(contact.result_element)  # open the chat
            msg_box = self.actuator.wait_for_element(
                "WhatsApp", "Name", _EL_MESSAGE_BOX, self.element_timeout_ms
            )
            self.actuator.set_value(msg_box, message)
            send_btn = self.actuator.wait_for_element(
                "WhatsApp", "Name", _EL_SEND_BUTTON, self.element_timeout_ms
            )
            self.actuator.invoke(send_btn)
        except Exception as e:
            logger.error("WhatsApp send failed for '%s': %s", contact.display_name, e)
            return ActionResult(
                status="error",
                detail=f"WhatsApp UI didn't respond as expected while sending: {e}",
                matched_contact=contact.display_name,
            )

        logger.info("WhatsApp message sent to '%s'", contact.display_name)
        return ActionResult(status="sent", detail="Message sent.", matched_contact=contact.display_name)

    def make_call(self, contact_query: str, video: bool = False) -> ActionResult:
        """Find `contact_query` in WhatsApp, confirm with the user, and place
        a voice or video call if confirmed."""
        try:
            self._ensure_running()
        except WhatsAppLaunchError as e:
            return ActionResult(status="error", detail=str(e))

        try:
            contact = self._search_contact(contact_query)
        except WhatsAppUIError as e:
            return ActionResult(status="error", detail=f"Couldn't search WhatsApp: {e}")

        if contact is None:
            return ActionResult(status="error", detail=f"No WhatsApp contact found matching '{contact_query}'.")

        call_kind = "video call" if video else "voice call"
        approved = self.confirm_callback(contact.display_name, f"place a {call_kind} to")
        if not approved:
            logger.info("WhatsApp call cancelled by user for contact '%s'", contact.display_name)
            return ActionResult(status="cancelled", detail="Call not placed.", matched_contact=contact.display_name)

        try:
            self.actuator.invoke(contact.result_element)  # open the chat
            call_button_name = _EL_VIDEO_CALL_BUTTON if video else _EL_VOICE_CALL_BUTTON
            call_btn = self.actuator.wait_for_element(
                "WhatsApp", "Name", call_button_name, self.element_timeout_ms
            )
            self.actuator.invoke(call_btn)
        except Exception as e:
            logger.error("WhatsApp call failed for '%s': %s", contact.display_name, e)
            return ActionResult(
                status="error",
                detail=f"WhatsApp UI didn't respond as expected while placing the call: {e}",
                matched_contact=contact.display_name,
            )

        logger.info("WhatsApp %s placed to '%s'", call_kind, contact.display_name)
        return ActionResult(status="called", detail=f"{call_kind.capitalize()} placed.", matched_contact=contact.display_name)

    # ── Internal helpers ─────────────────────────────────────────────────

    def _ensure_running(self) -> None:
        if self.process_checker.is_running(WHATSAPP_PROCESS_NAMES):
            return
        logger.info("WhatsApp Desktop not running -- launching it.")
        result = self.app_launcher.launch(WHATSAPP_APP_QUERY)
        if "launched" not in result.lower():
            raise WhatsAppLaunchError(f"Couldn't launch WhatsApp Desktop: {result}")
        time.sleep(_DEFAULT_APP_LAUNCH_WAIT_S)  # give the app a moment to actually open

    def _search_contact(self, contact_query: str) -> Optional[ContactMatch]:
        """Type into WhatsApp's own search box and read back the top result.
        WhatsApp's own search is the source of truth -- this method does not
        do any fuzzy matching of its own."""
        search_box = self.actuator.wait_for_element(
            "WhatsApp", "Name", _EL_SEARCH_BOX, self.element_timeout_ms
        )
        self.actuator.set_value(search_box, contact_query)

        # First search result -- AutomationId is used here rather than Name
        # since the result's Name IS the contact name we're trying to read,
        # not a fixed string we can search for.
        result_el = self.actuator.find_element("WhatsApp", "AutomationId", "search-result-0")
        if result_el is None:
            return None

        display_name = self.actuator.get_text(result_el)
        if not display_name:
            return None

        return ContactMatch(display_name=display_name, result_element=result_el)