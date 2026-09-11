"""AURIX Central Tool Executor.

All physical actions performed by AURIX must pass through this layer.

Reasoning model
    ↓
AgentRouter
    ↓
ToolExecutor
    ↓
PermissionManager
    ↓
Actual controller
"""

from __future__ import annotations

import logging
import secrets
import subprocess
from pathlib import Path
from typing import Any, Dict

from ai_brain.app_control import AppLauncher, AppCloser
from ai_brain.email_control import EmailController
from ai_brain.file_control import FileController
from ai_brain.media_player import MediaPlayer
from ai_brain.message_control import WhatsAppController
from ai_brain.web_search import WebSearcher
from ai_brain.youtube_video import youtube_video

from security.permissions import (
    PermissionManager,
    ActionCategory,
)

logger = logging.getLogger("aurix.ai_brain.tool_executor")


def _load_config() -> Dict[str, Any]:
    """Load AURIX config.toml."""

    config_path = Path(__file__).resolve().parent.parent / "config.toml"

    if not config_path.exists():
        return {}

    try:
        import sys

        if sys.version_info >= (3, 11):
            import tomllib
        else:
            import tomli as tomllib

        with open(config_path, "rb") as f:
            return tomllib.load(f)

    except Exception as exc:
        logger.warning("Unable to load config.toml: %s", exc)
        return {}


class _ProcessChecker:
    def is_running(self, process_names: tuple) -> bool:
        try:
            import psutil
        except ImportError:
            return False

        expected = {name.lower() for name in process_names}

        for proc in psutil.process_iter(["name"]):
            try:
                name = (proc.info.get("name") or "").lower()

                if name in expected:
                    return True

            except Exception:
                continue

        return False


class ToolExecutor:

    def __init__(self) -> None:

        self.config = _load_config()

        self.permission_manager = PermissionManager(
            config=self.config
        )

        self.launcher = AppLauncher()
        self.closer = AppCloser()

        self.media = MediaPlayer()
        self.searcher = WebSearcher()

        # IMPORTANT:
        # FileController internal confirmations are disabled because
        # permission handling now lives HERE centrally.
        self.files = FileController(
            interactive_confirmations=False
        )

        self.email = EmailController()

        self.whatsapp = WhatsAppController(
            app_launcher=self.launcher,
            process_checker=_ProcessChecker(),
        )

        self._pending_actions: Dict[str, Dict[str, Any]] = {}

    # ============================================================
    # PUBLIC API
    # ============================================================

    def supports(self, tool_name: str) -> bool:

        return tool_name in {
            "open_app",
            "close_app",
            "play_media",
            "web_search",
            "youtube",
            "send_email",
            "send_whatsapp_message",
            "make_whatsapp_call",
            "list_directory",
            "read_file",
            "write_file",
            "create_folder",
            "delete_item",
            "copy_item",
            "move_item",
            "rename_item",
            "shell_exec",
        }

    def _validate_args(
        self,
        tool_name: str,
        args: Dict[str, Any],
    ) -> str | None:
        """Validate tool arguments before security checks or execution.

        Returns:
            None when arguments are valid.
            A user-facing clarification/error string when something is missing
            or malformed.
        """

        if not isinstance(args, dict):
            return (
                f"I couldn't run {tool_name} because its arguments "
                "were not provided in the expected format."
            )

        def clean_string(key: str) -> str:
            value = args.get(key, "")
            if value is None:
                return ""
            return str(value).strip()

        # Required simple string arguments.
        required: Dict[str, tuple[str, ...]] = {
            "open_app": ("target",),
            "close_app": ("target",),
            "web_search": ("query",),
            "send_whatsapp_message": ("contact", "message"),
            "make_whatsapp_call": ("contact",),
            "read_file": ("path",),
            "write_file": ("path",),
            "create_folder": ("path",),
            "delete_item": ("path",),
            "copy_item": ("source", "destination"),
            "move_item": ("source", "destination"),
            "rename_item": ("path", "new_name"),
            "shell_exec": ("command",),
        }

        missing = [
            key
            for key in required.get(tool_name, ())
            if not clean_string(key)
        ]

        if missing:
            pretty = ", ".join(missing)
            return (
                f"I need the following information before I can run "
                f"{tool_name}: {pretty}."
            )

        # Normalize string fields in-place so downstream controllers receive
        # clean values rather than whitespace-only strings.
        for key in (
            "target",
            "query",
            "to",
            "subject",
            "body",
            "contact",
            "message",
            "path",
            "source",
            "destination",
            "new_name",
            "command",
            "action",
            "service",
            "url",
        ):
            if key in args and args[key] is not None and not isinstance(args[key], bool):
                args[key] = str(args[key]).strip()

        # ---------------------------------------------------------
        # Email validation
        # ---------------------------------------------------------
        if tool_name == "send_email":
            recipient = clean_string("to")
            body = clean_string("body")

            if not recipient:
                return "I need the recipient email address before I can send the email."

            if "@" not in recipient or recipient.startswith("@") or recipient.endswith("@"):
                return (
                    f"'{recipient}' does not look like a valid email address. "
                    "Please provide the recipient again."
                )

            if not body:
                return "I need the email body/message before I can send the email."

            # Subject may legitimately be empty.
            args.setdefault("subject", "")

        # ---------------------------------------------------------
        # Media validation
        # ---------------------------------------------------------
        if tool_name == "play_media":
            action = clean_string("action").lower() or "play"

            allowed_actions = {
                "play",
                "pause",
                "next",
                "previous",
            }

            if action not in allowed_actions:
                return (
                    "Unsupported media action. Use play, pause, next, "
                    "or previous."
                )

            args["action"] = action

            if action == "play" and not clean_string("query"):
                return "Tell me what you want me to play."

            service = clean_string("service").lower() or "default"
            args["service"] = service

        # ---------------------------------------------------------
        # YouTube validation
        # ---------------------------------------------------------
        if tool_name == "youtube":
            action = clean_string("action").lower()

            allowed_actions = {
                "play",
                "info",
                "summarize",
                "download",
                "trending",
            }

            if not action:
                return (
                    "I need to know what YouTube action you want: "
                    "play, info, summarize, download, or trending."
                )

            if action not in allowed_actions:
                return f"Unsupported YouTube action: {action}."

            args["action"] = action

            if action != "trending":
                has_query = bool(clean_string("query"))
                has_url = bool(clean_string("url"))

                if not has_query and not has_url:
                    return (
                        f"I need a YouTube query or URL before I can "
                        f"{action}."
                    )

        # ---------------------------------------------------------
        # WhatsApp call boolean normalization
        # ---------------------------------------------------------
        if tool_name == "make_whatsapp_call":
            video = args.get("video", False)

            if isinstance(video, str):
                args["video"] = video.strip().lower() in {
                    "1",
                    "true",
                    "yes",
                    "video",
                }
            else:
                args["video"] = bool(video)

        # ---------------------------------------------------------
        # File write normalization
        # ---------------------------------------------------------
        if tool_name == "write_file":
            # Empty content is allowed because creating an empty file is valid.
            if "content" not in args or args["content"] is None:
                args["content"] = ""

            append = args.get("append", False)
            if isinstance(append, str):
                args["append"] = append.strip().lower() in {
                    "1",
                    "true",
                    "yes",
                    "append",
                }
            else:
                args["append"] = bool(append)

        # ---------------------------------------------------------
        # Safe defaults
        # ---------------------------------------------------------
        if tool_name == "list_directory":
            if not clean_string("path"):
                args["path"] = "desktop"

        return None

    def execute(
        self,
        tool_name: str,
        args: Dict[str, Any] | None = None,
        token_id: str | None = None,
    ) -> str:

        args = args or {}

        if not self.supports(tool_name):
            return f"Unknown AURIX tool: {tool_name}"

        validation_error = self._validate_args(
            tool_name,
            args,
        )

        if validation_error:
            logger.warning(
                "Rejected malformed tool call: tool=%s args=%s reason=%s",
                tool_name,
                args,
                validation_error,
            )
            return validation_error

        category = self._get_category(tool_name)

        target = self._get_target(tool_name, args)

        command_text = (
            str(args.get("command", ""))
            if tool_name == "shell_exec"
            else None
        )

        needs_permission = self.permission_manager.requires_trust_token(
            category=category,
            target_resource=target,
            command_text=command_text,
        )

        if needs_permission:

            if token_id is None:

                request_id = secrets.token_hex(6)

                self._pending_actions[request_id] = {
                    "tool": tool_name,
                    "args": args,
                    "category": category,
                    "target": target,
                    "command_text": command_text,
                }

                description = self._describe_action(
                    tool_name,
                    args,
                )

                return (
                    f"TRUST_TOKEN_REQUIRED:"
                    f"{request_id}:"
                    f"{description}"
                )

            allowed = self.permission_manager.validate_action(
                category=category,
                target_resource=target,
                token_id=token_id,
                command_text=command_text,
            )

            if not allowed:
                return "Security authorization failed."

        try:
            return self._execute_actual(
                tool_name,
                args,
            )

        except Exception as exc:

            logger.exception(
                "Tool execution failed: %s",
                tool_name,
            )

            return f"Tool execution failed: {exc}"

    def confirm_pending(self, trust_request: str) -> str:
        """Called by frontend after the human approves an action."""

        if trust_request.startswith(
            "TRUST_TOKEN_REQUIRED:"
        ):
            parts = trust_request.split(":", 2)

            if len(parts) < 2:
                return "Invalid security request."

            request_id = parts[1]

        else:
            request_id = trust_request

        pending = self._pending_actions.pop(
            request_id,
            None,
        )

        if not pending:
            return "Security request expired or no longer exists."

        token = self.permission_manager.grant_trust_token(
            category=pending["category"],
            target_resource=pending["target"],
        )

        return self.execute(
            tool_name=pending["tool"],
            args=pending["args"],
            token_id=token.token_id,
        )

    # ============================================================
    # SECURITY
    # ============================================================

    def _get_category(
        self,
        tool_name: str,
    ) -> ActionCategory:

        mapping = {

            "open_app":
                ActionCategory.APP_CONTROL,

            "close_app":
                ActionCategory.APP_CONTROL,

            "play_media":
                ActionCategory.APP_CONTROL,

            "web_search":
                ActionCategory.LOCAL_SEARCH,

            "youtube":
                ActionCategory.LOCAL_SEARCH,

            "send_email":
                ActionCategory.EXTERNAL_COMMUNICATION,

            "send_whatsapp_message":
                ActionCategory.EXTERNAL_COMMUNICATION,

            "make_whatsapp_call":
                ActionCategory.EXTERNAL_COMMUNICATION,

            "list_directory":
                ActionCategory.FILE_READ,

            "read_file":
                ActionCategory.FILE_READ,

            "write_file":
                ActionCategory.FILE_WRITE,

            "create_folder":
                ActionCategory.FILE_WRITE,

            "delete_item":
                ActionCategory.FILE_DELETE,

            "copy_item":
                ActionCategory.FILE_WRITE,

            "move_item":
                ActionCategory.FILE_WRITE,

            "rename_item":
                ActionCategory.FILE_WRITE,

            "shell_exec":
                ActionCategory.SHELL_EXEC,
        }

        return mapping[tool_name]

    def _get_target(
        self,
        tool_name: str,
        args: Dict[str, Any],
    ) -> str:

        for key in (
            "target",
            "path",
            "contact",
            "to",
            "source",
            "command",
            "query",
        ):
            value = args.get(key)

            if value:
                return str(value)

        return tool_name

    def _describe_action(
        self,
        tool_name: str,
        args: Dict[str, Any],
    ) -> str:

        if tool_name == "delete_item":
            return f"Delete {args.get('path')}"

        if tool_name == "send_email":
            return (
                f"Send email to "
                f"{args.get('to')}"
            )

        if tool_name == "send_whatsapp_message":
            return (
                f"Send WhatsApp message to "
                f"{args.get('contact')}"
            )

        if tool_name == "make_whatsapp_call":
            return (
                f"Call "
                f"{args.get('contact')} on WhatsApp"
            )

        if tool_name == "shell_exec":
            return (
                f"Run command: "
                f"{args.get('command')}"
            )

        return f"Execute {tool_name}"

    # ============================================================
    # ACTUAL TOOLS
    # ============================================================

    def _execute_actual(
        self,
        tool: str,
        args: Dict[str, Any],
    ) -> str:

        if tool == "open_app":

            return self.launcher.launch(
                str(args.get("target", ""))
            )

        if tool == "close_app":

            return self.closer.close(
                str(args.get("target", ""))
            )

        if tool == "play_media":

            action = str(
                args.get("action", "play")
            ).lower()

            query = str(
                args.get("query", "")
            )

            service = str(
                args.get("service", "spotify")
            )

            if action == "pause":
                return self.media.toggle_playback()

            if action == "next":
                return self.media.next_track()

            if action == "previous":
                return self.media.prev_track()

            return self.media.play(
                query,
                service=service,
            )

        if tool == "web_search":

            return self.searcher.search(
                str(args.get("query", ""))
            )

        if tool == "youtube":

            return youtube_video(args)

        if tool == "send_email":

            return self.email.send_email(
                str(args.get("to", "")),
                str(args.get("subject", "")),
                str(args.get("body", "")),
            )

        if tool == "send_whatsapp_message":

            contact = str(
                args.get("contact", "")
            )

            message = str(
                args.get("message", "")
            )

            pending = self.whatsapp.prepare_message(
                contact,
                message,
            )

            result = self.whatsapp.execute(
                pending
            )

            return result.detail

        if tool == "make_whatsapp_call":

            contact = str(
                args.get("contact", "")
            )

            video = bool(
                args.get("video", False)
            )

            pending = self.whatsapp.prepare_call(
                contact,
                video=video,
            )

            result = self.whatsapp.execute(
                pending
            )

            return result.detail

        if tool == "list_directory":

            return self.files.list_directory(
                str(args.get("path", "desktop"))
            )

        if tool == "read_file":

            return self.files.read_file(
                str(args.get("path", ""))
            )

        if tool == "write_file":

            return self.files.write_file(
                str(args.get("path", "")),
                str(args.get("content", "")),
                append=bool(
                    args.get("append", False)
                ),
            )

        if tool == "create_folder":

            return self.files.create_folder(
                str(args.get("path", ""))
            )

        if tool == "delete_item":

            return self.files.delete_item(
                str(args.get("path", "")),
                visual=False,
            )

        if tool == "copy_item":

            return self.files.copy_item(
                str(args.get("source", "")),
                str(args.get("destination", "")),
                visual=False,
            )

        if tool == "move_item":

            return self.files.move_item(
                str(args.get("source", "")),
                str(args.get("destination", "")),
                visual=False,
            )

        if tool == "rename_item":

            return self.files.rename_item(
                str(args.get("path", "")),
                str(args.get("new_name", "")),
                visual=False,
            )

        if tool == "shell_exec":

            command = str(
                args.get("command", "")
            ).strip()

            if not command:
                return "No command provided."

            try:
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=30,
                )
            except subprocess.TimeoutExpired:
                return (
                    "Command was stopped because it exceeded "
                    "the 30 second execution limit."
                )

            output = (
                result.stdout
                or result.stderr
                or "Command completed."
            )

            return (
                f"[Exit {result.returncode}]\n"
                f"{output.strip()}"
            )

        return f"Unsupported tool: {tool}"