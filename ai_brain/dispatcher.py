"""AURIX AI Brain -- Central Intent Dispatcher.

Rev. 2 -- adds WhatsApp messaging/calling, routed through a two-turn
confirm flow: the first utterance resolves the contact and asks for
confirmation; the NEXT utterance (yes/no) actually executes the send/call.
This is necessary because dispatch(text) is single-shot (one reply per
call, no blocking wait for a second input) -- see whatsapp_control.py's
docstring for why the confirmation logic couldn't just be a blocking
callback inside a single dispatch() call.

Still uses the existing prefix-based routing for open/close/cmd -- the
LUNA AI Brain directive's recommendation to eventually replace this with
Gemma 4 E4B function-calling still stands, but is a separate, larger
change from this one, which only adds WhatsApp support in the style the
rest of this file already uses.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Optional, Tuple

from ai_brain.app_control import AppCloser, AppLauncher
from ai_brain.message_control import (
    ActionResult,
    PendingWhatsAppAction,
    WhatsAppController,
    WhatsAppLaunchError,
    WhatsAppUIError,
)

logger = logging.getLogger("aurix.ai_brain.dispatcher")

_AFFIRMATIVE = frozenset({"yes", "yeah", "yep", "confirm", "confirmed", "do it", "send it", "go ahead", "sure"})
_NEGATIVE = frozenset({"no", "nope", "cancel", "cancelled", "stop", "don't", "dont", "never mind", "nevermind"})


class BrainDispatcher:
    """Central brain router that parses intent and dispatches to handlers.

    Usage from frontend.py:
        brain = BrainDispatcher(uia_actuator=core_engine.UiaController())
        reply, handled = brain.dispatch(user_text)
        if not handled:
            # fall through to LLM
    """

    _WAKE_PHRASES = frozenset({
        "luna", "hey luna", "aurix", "wake up", "call luna", "hello",
    })

    def __init__(self, uia_actuator=None, process_checker=None) -> None:
        self.launcher = AppLauncher()
        self.closer = AppCloser()

        # WhatsApp support is optional -- if no actuator is supplied (e.g. the
        # Rust core_engine_uia_patch.rs additions haven't been built yet),
        # WhatsApp commands are reported as unavailable rather than crashing
        # the whole dispatcher.
        self._whatsapp: Optional[WhatsAppController] = None
        if uia_actuator is not None:
            checker = process_checker or _DefaultProcessChecker()
            self._whatsapp = WhatsAppController(
                actuator=uia_actuator,
                app_launcher=self.launcher,
                process_checker=checker,
            )

        # Two-turn confirmation state -- set when a message/call has been
        # resolved and is awaiting a yes/no from the next utterance. Cleared
        # after either turn resolves it (confirmed, declined, or a new
        # unrelated command interrupts it -- see dispatch()).
        self._pending_whatsapp: Optional[PendingWhatsAppAction] = None

        logger.info("BrainDispatcher initialized. WhatsApp support: %s", "enabled" if self._whatsapp else "disabled")

    def dispatch(self, text: str) -> Tuple[str, bool]:
        if not text or not text.strip():
            return ("", False)

        trimmed = text.strip()
        lower = trimmed.lower()

        # ── Pending WhatsApp confirmation takes priority over everything
        #    else -- if we just asked "send this to X?", the next thing the
        #    user says should be interpreted as answering that, not as a
        #    brand new command. ─────────────────────────────────────────
        if self._pending_whatsapp is not None:
            return self._resolve_pending_whatsapp(lower)

        # ── Wake / greeting phrases ───────────────────────────────────────
        if lower in self._WAKE_PHRASES:
            return ("AURIX Executive online and listening. Ready for your command.", True)

        # ── Shell command execution ───────────────────────────────────────
        if lower.startswith("cmd:") or lower.startswith("run:"):
            raw_cmd = trimmed.split(":", 1)[1].strip()
            return self._handle_shell(raw_cmd)

        # ── WhatsApp message ────────────────────────────────────────────
        # Accepted forms: "message <contact> saying <text>" / "text <contact> saying <text>"
        parsed = self._try_parse_whatsapp_message(trimmed)
        if parsed is not None:
            contact, message = parsed
            return self._start_whatsapp_message(contact, message)

        # ── WhatsApp call ────────────────────────────────────────────────
        # Accepted forms: "call <contact>" / "video call <contact>"
        parsed_call = self._try_parse_whatsapp_call(lower, trimmed)
        if parsed_call is not None:
            contact, video = parsed_call
            return self._start_whatsapp_call(contact, video)

        # ── Close application ─────────────────────────────────────────────
        if lower.startswith("close "):
            target = trimmed[6:].strip()
            if target:
                return (self.closer.close(target), True)

        # ── Open / launch application ─────────────────────────────────────
        if lower.startswith("open "):
            target = trimmed[5:].strip()
            if target:
                return (self.launcher.launch(target), True)

        if lower in ("notepad", "calc", "calculator", "explorer"):
            return (self.launcher.launch(lower), True)

        return ("", False)

    # ── WhatsApp: turn 1 (resolve + ask) ─────────────────────────────────

    def _try_parse_whatsapp_message(self, trimmed: str) -> Optional[Tuple[str, str]]:
        """Recognizes several natural phrasings for a WhatsApp message, not
        just the single rigid "X saying Y" form:
            message saad saying hi
            text saad saying hi
            message saad "hi"          <- quoted, no "saying"
            message saad: hi           <- colon-separated
            message saad 'hi'          <- single-quoted

        This is still simple keyword/pattern matching, not real language
        understanding -- it will still miss less common phrasings. The LUNA
        AI Brain directive's recommendation to eventually replace this whole
        prefix-based dispatcher with Gemma 4 E4B function-calling (Part B.0)
        is exactly for this reason: rigid pattern matching will always have
        gaps like the one that was just found. This fix widens the gap, it
        doesn't close the underlying problem.
        """
        lower = trimmed.lower()
        for prefix in ("message ", "text "):
            if not lower.startswith(prefix):
                continue
            body = trimmed[len(prefix):]
            body_lower = body.lower()

            # Form 1: "<contact> saying <message>"
            if " saying " in body_lower:
                idx = body_lower.index(" saying ")
                contact = body[:idx].strip()
                message = body[idx + len(" saying "):].strip()
                if contact and message:
                    return contact, message

            # Form 2: "<contact> "<message>"" or "<contact> '<message>'"
            # (straight double/single quotes, and common curly-quote variants)
            for open_q, close_q in (('"', '"'), ("'", "'"), ("\u201c", "\u201d"), ("\u2018", "\u2019")):
                if open_q in body and body.rstrip().endswith(close_q):
                    q_start = body.index(open_q)
                    contact = body[:q_start].strip()
                    message = body[q_start + 1: body.rstrip().rfind(close_q)].strip()
                    if contact and message:
                        return contact, message

            # Form 3: "<contact>: <message>"
            if ":" in body:
                idx = body.index(":")
                contact = body[:idx].strip()
                message = body[idx + 1:].strip()
                if contact and message:
                    return contact, message

        return None

    def _try_parse_whatsapp_call(self, lower: str, trimmed: str) -> Optional[Tuple[str, bool]]:
        if lower.startswith("video call "):
            contact = trimmed[len("video call "):].strip()
            return (contact, True) if contact else None
        if lower.startswith("call "):
            contact = trimmed[len("call "):].strip()
            return (contact, False) if contact else None
        return None

    def _start_whatsapp_message(self, contact: str, message: str) -> Tuple[str, bool]:
        if self._whatsapp is None:
            return ("WhatsApp automation isn't set up yet on this system.", True)
        try:
            pending = self._whatsapp.prepare_message(contact, message)
        except (WhatsAppLaunchError, WhatsAppUIError) as e:
            return (f"Couldn't prepare that message: {e}", True)

        self._pending_whatsapp = pending
        return (
            f"Found {pending.matched_contact} on WhatsApp. Send: \"{pending.message}\"? "
            f"Say yes to confirm or no to cancel.",
            True,
        )

    def _start_whatsapp_call(self, contact: str, video: bool) -> Tuple[str, bool]:
        if self._whatsapp is None:
            return ("WhatsApp automation isn't set up yet on this system.", True)
        try:
            pending = self._whatsapp.prepare_call(contact, video=video)
        except (WhatsAppLaunchError, WhatsAppUIError) as e:
            return (f"Couldn't prepare that call: {e}", True)

        self._pending_whatsapp = pending
        kind = "video call" if video else "voice call"
        return (
            f"Found {pending.matched_contact} on WhatsApp. Place a {kind}? "
            f"Say yes to confirm or no to cancel.",
            True,
        )

    # ── WhatsApp: turn 2 (confirm/decline + execute) ─────────────────────

    def _resolve_pending_whatsapp(self, lower: str) -> Tuple[str, bool]:
        pending = self._pending_whatsapp

        if lower in _AFFIRMATIVE:
            self._pending_whatsapp = None  # clear BEFORE executing -- if execute()
                                            # raises, we don't want a stale pending
                                            # action left confirmable by a later "yes"
            result: ActionResult = self._whatsapp.execute(pending)
            if result.status == "error":
                return (f"That didn't go through: {result.detail}", True)
            return (result.detail, True)

        if lower in _NEGATIVE:
            self._pending_whatsapp = None
            kind = "message" if pending.kind == "message" else "call"
            return (f"Okay, {kind} to {pending.matched_contact} cancelled.", True)

        # Anything else: treat the pending action as abandoned (don't leave
        # it silently hanging forever waiting for a yes/no that never comes)
        # and fall through to normal dispatch for whatever the user actually
        # said. Re-dispatch once, now that _pending_whatsapp is cleared, so
        # this doesn't recurse into itself.
        logger.info(
            "Pending WhatsApp %s to '%s' abandoned -- user said something else instead.",
            pending.kind, pending.matched_contact,
        )
        self._pending_whatsapp = None
        return self.dispatch(lower)

    # ── Handler Methods ───────────────────────────────────────────────────

    def _handle_shell(self, raw_cmd: str) -> Tuple[str, bool]:
        if not raw_cmd:
            return ("No command provided.", True)
        try:
            res = subprocess.run(
                raw_cmd, shell=True,
                capture_output=True, text=True, errors="replace",
            )
            out = (res.stdout or res.stderr or "Command executed successfully (exit code 0).").strip()
            reply = f"[Command Result (Exit {res.returncode})]:\n{out}"
        except Exception as e:
            reply = f"[Command Error]: {e}"
        return (reply, True)


class _DefaultProcessChecker:
    """Thin psutil-based process checker, used when the caller doesn't
    supply their own. Matches the process-scanning approach AppCloser
    already uses elsewhere in this file."""

    def is_running(self, process_names: tuple) -> bool:
        try:
            import psutil
        except ImportError:
            return False
        names_lower = {n.lower() for n in process_names}
        for proc in psutil.process_iter(["name"]):
            try:
                if (proc.info["name"] or "").lower() in names_lower:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return False