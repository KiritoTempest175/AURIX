"""AURIX AI Brain — Central Intent Dispatcher.

Routes user text to the appropriate brain-level handler. This is the single
entry point that frontend.py calls — it decides whether a command is a brain
action (open/close/cmd) or should fall through to the LLM.
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Tuple, Optional

from ai_brain.app_control import AppCloser, AppLauncher
from security.permissions import PermissionManager, ActionCategory
from ai_engine.inference.gemma_e4b import get_default_gemma_runner

logger = logging.getLogger("aurix.ai_brain.dispatcher")


class BrainDispatcher:
    """Central brain router that parses intent and dispatches to handlers."""

    # Greetings / wake phrases handled directly
    _WAKE_PHRASES = frozenset({
        "luna", "hey luna", "aurix", "wake up", "call luna", "hello",
    })

    def __init__(self, permission_manager: Optional[PermissionManager] = None) -> None:
        self.launcher = AppLauncher()
        self.closer = AppCloser()
        self.permission_manager = permission_manager or PermissionManager()
        self.gemma_runner = get_default_gemma_runner()
        logger.info("BrainDispatcher initialized.")

    def dispatch(self, text: str) -> Tuple[str, bool]:
        """Parse user text and route to the appropriate handler using Gemma."""
        if not text or not text.strip():
            return ("", False)

        trimmed = text.strip()
        lower = trimmed.lower()

        # 1. Check wake phrases
        if lower in self._WAKE_PHRASES:
            return ("AURIX Executive online and listening. Ready for your command.", True)

        # 2. Check literal shell prefix
        if lower.startswith("cmd:") or lower.startswith("run:"):
            raw_cmd = trimmed.split(":", 1)[1].strip()
            return self._handle_shell(raw_cmd)

        # 3. LLM-driven tool selection
        tool_call = self.gemma_runner.select_tool(text)
        tool_name = tool_call.get("tool")
        args = tool_call.get("args", {})

        logger.info(f"LLM Tool Selection: {tool_name} with args {args}")

        # 4. Map tool names to handler methods
        handlers = {
            "open_app": self._handle_open_app,
            "close_app": self._handle_close_app,
            "play_media": self._handle_play_media,
            "web_search": self._handle_web_search,
            "send_email": self._handle_send_email,
            "send_whatsapp_message": self._handle_send_whatsapp,
            "make_phone_call": self._handle_make_phone_call,
            "general_answer": self._handle_general_answer,
        }

        handler = handlers.get(tool_name)
        if not handler:
            return self._handle_general_answer({"response": f"Unknown tool selected: {tool_name}"})

        # 5. Execute
        try:
            return handler(args)
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}")
            return (f"Error executing {tool_name}: {e}", True)

    # ── Tool Handlers ─────────────────────────────────────────────────────

    def _handle_open_app(self, args: dict) -> Tuple[str, bool]:
        target = args.get("target")
        if not target:
            return ("No target specified to open.", True)
        return (self.launcher.launch(target), True)

    def _handle_close_app(self, args: dict) -> Tuple[str, bool]:
        target = args.get("target")
        if not target:
            return ("No target specified to close.", True)
        return (self.closer.close(target), True)

    def _handle_play_media(self, args: dict) -> Tuple[str, bool]:
        # Lazy load to avoid circular deps if needed
        from ai_brain.media_player import MediaPlayer
        player = MediaPlayer()
        
        query = args.get("query", "")
        service = args.get("service", "spotify")
        action = args.get("action", "play")
        
        if action == "play" and query:
            return (player.play(query, service), True)
        elif action == "pause":
            return (player.pause(service), True)
        else:
            return (f"Media action {action} not fully implemented.", True)

    def _handle_web_search(self, args: dict) -> Tuple[str, bool]:
        from ai_brain.web_search import WebSearcher
        searcher = WebSearcher()
        query = args.get("query")
        if not query:
            return ("No search query provided.", True)
        return (searcher.search(query, self.gemma_runner), True)

    def _handle_send_email(self, args: dict) -> Tuple[str, bool]:
        from ai_brain.communications import EmailClient
        to = args.get("to")
        subject = args.get("subject", "")
        body = args.get("body", "")
        
        if self.permission_manager.requires_trust_token(ActionCategory.EXTERNAL_COMMUNICATION, to):
            # frontend.py will handle the actual interruption, we just return a structured response
            return (f"TRUST_TOKEN_REQUIRED:email:{to}|{subject}|{body}", True)
            
        client = EmailClient()
        return (client.send_email(to, subject, body), True)

    def _handle_send_whatsapp(self, args: dict) -> Tuple[str, bool]:
        contact = (args.get("contact") or "").strip()
        message = (args.get("message") or "").strip()
        if not contact or not message:
            return ("Please specify both a recipient contact and a message body.", True)

        from ai_brain.communications import WhatsAppClient
        if self.permission_manager.requires_trust_token(ActionCategory.EXTERNAL_COMMUNICATION, contact):
            return (f"TRUST_TOKEN_REQUIRED:whatsapp:{contact}|{message}", True)
            
        client = WhatsAppClient()
        return (client.send_message(contact, message), True)

    def _handle_make_phone_call(self, args: dict) -> Tuple[str, bool]:
        contact = (args.get("contact") or "").strip()
        message = (args.get("message") or "").strip()
        if not contact:
            return ("Please specify a contact to call.", True)

        if self.permission_manager.requires_trust_token(ActionCategory.EXTERNAL_COMMUNICATION, contact):
            return (f"TRUST_TOKEN_REQUIRED:call:{contact}|{message}", True)

        from ai_brain.communications import WhatsAppClient
        return (WhatsAppClient().make_call(contact, message), True)

    def _handle_general_answer(self, args: dict) -> Tuple[str, bool]:
        # Return False to let frontend / standard fallback handle it, OR return the LLM's direct answer
        response = args.get("response", "")
        if response:
            return (response, True)
        return ("", False)

    # ── Legacy Shell Handler ──────────────────────────────────────────────

    def _handle_shell(self, raw_cmd: str) -> Tuple[str, bool]:
        """Execute a shell command and return its output."""
        if not raw_cmd:
            return ("No command provided.", True)

        try:
            res = subprocess.run(
                raw_cmd, shell=True,
                capture_output=True, text=True, errors="replace",
            )
            out = res.stdout.strip()
            err = res.stderr.strip()
            if res.returncode == 0:
                return (f"Command executed successfully.\n{out}", True)
            else:
                return (f"Command failed (Code {res.returncode}).\n{err}", True)
        except Exception as e:
            return (f"Shell execution error: {e}", True)


    def execute_trust_token(self, token_str: str) -> str:
        """Executes an action that was previously blocked by a trust token."""
        parts = token_str.split(":", 2)
        if len(parts) < 3:
            return "Invalid trust token format."
        _, action, data = parts
        
        try:
            if action == "email":
                parts = data.split("|")
                to = parts[0] if len(parts) > 0 else ""
                subject = parts[1] if len(parts) > 1 else ""
                body = parts[2] if len(parts) > 2 else ""
                from ai_brain.communications import EmailClient
                from security.permissions import ActionCategory
                self.permission_manager.grant_trust_token(ActionCategory.EXTERNAL_COMMUNICATION, to, "user_approved")
                return EmailClient().send_email(to, subject, body)
            elif action == "whatsapp":
                parts = data.split("|", 1)
                contact = parts[0] if len(parts) > 0 else ""
                message = parts[1] if len(parts) > 1 else ""
                from ai_brain.communications import WhatsAppClient
                from security.permissions import ActionCategory
                self.permission_manager.grant_trust_token(ActionCategory.EXTERNAL_COMMUNICATION, contact, "user_approved")
                return WhatsAppClient().send_message(contact, message)
            elif action == "call":
                parts = data.split("|", 1)
                contact = parts[0] if len(parts) > 0 else ""
                message = parts[1] if len(parts) > 1 else ""
                from ai_brain.communications import WhatsAppClient
                from security.permissions import ActionCategory
                self.permission_manager.grant_trust_token(ActionCategory.EXTERNAL_COMMUNICATION, contact, "user_approved")
                return WhatsAppClient().make_call(contact, message)
            return f"Unknown trust token action: {action}"
        except Exception as e:
            return f"Failed to execute trusted action: {e}"
