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

import hashlib
import json
import logging
import secrets
import subprocess
import time

from copy import deepcopy
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


logger = logging.getLogger(
    "aurix.ai_brain.tool_executor"
)

PENDING_ACTION_TTL_SECONDS = 60.0


def _load_config() -> Dict[str, Any]:
    """Load AURIX config.toml."""

    config_path = (
        Path(__file__).resolve().parent.parent
        / "config.toml"
    )

    if not config_path.exists():
        return {}

    try:
        import sys

        if sys.version_info >= (3, 11):
            import tomllib
        else:
            import tomli as tomllib

        with open(
            config_path,
            "rb",
        ) as f:
            return tomllib.load(f)

    except Exception as exc:
        logger.warning(
            "Unable to load config.toml: %s",
            exc,
        )

        return {}


class _ProcessChecker:

    def is_running(
        self,
        process_names: tuple,
    ) -> bool:

        try:
            import psutil

        except ImportError:
            return False

        expected = {
            name.lower()
            for name in process_names
        }

        for proc in psutil.process_iter(
            ["name"]
        ):
            try:
                name = (
                    proc.info.get("name")
                    or ""
                ).lower()

                if name in expected:
                    return True

            except Exception:
                continue

        return False


class ToolExecutor:

    def __init__(self) -> None:

        self.config = _load_config()

        self.permission_manager = (
            PermissionManager(
                config=self.config
            )
        )

        self.launcher = AppLauncher()
        self.closer = AppCloser()

        self.media = MediaPlayer()
        self.searcher = WebSearcher()

        # File security confirmation is handled centrally
        # by ToolExecutor + PermissionManager.
        self.files = FileController(
            interactive_confirmations=False
        )

        self.email = EmailController()

        self.whatsapp = WhatsAppController(
            app_launcher=self.launcher,
            process_checker=_ProcessChecker(),
        )

        self._pending_actions: Dict[
            str,
            Dict[str, Any],
        ] = {}

    # ============================================================
    # SECURITY HELPERS
    # ============================================================

    @staticmethod
    def _action_fingerprint(
        tool_name: str,
        args: Dict[str, Any],
    ) -> str:
        """Create SHA-256 identity for exact tool + args."""

        payload = {
            "tool": tool_name,
            "args": args,
        }

        serialized = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )

        return hashlib.sha256(
            serialized.encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _security_operation(
        tool_name: str,
        args: Dict[str, Any],
    ) -> str:
        """Return operation name used by security policy."""

        if tool_name == "youtube":

            action = str(
                args.get(
                    "action",
                    "",
                )
            ).lower()

            if action == "download":
                return "youtube_download"

        return tool_name

    def _cleanup_expired_pending(
        self,
    ) -> None:
        """Remove stale confirmation requests."""

        now = time.time()

        expired_ids = [
            request_id
            for request_id, pending
            in self._pending_actions.items()
            if now
            > float(
                pending.get(
                    "expires_at",
                    0,
                )
            )
        ]

        for request_id in expired_ids:

            self._pending_actions.pop(
                request_id,
                None,
            )

            logger.info(
                "Expired pending security request: %s",
                request_id,
            )

    # ============================================================
    # PUBLIC API
    # ============================================================

    def supports(
        self,
        tool_name: str,
    ) -> bool:

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
        """Validate tool arguments before execution."""

        if not isinstance(
            args,
            dict,
        ):
            return (
                f"I couldn't run {tool_name} because its arguments "
                "were not provided in the expected format."
            )

        def clean_string(
            key: str,
        ) -> str:

            value = args.get(
                key,
                "",
            )

            if value is None:
                return ""

            return str(
                value
            ).strip()

        required: Dict[
            str,
            tuple[str, ...],
        ] = {

            "open_app":
                ("target",),

            "close_app":
                ("target",),

            "web_search":
                ("query",),

            "send_whatsapp_message":
                (
                    "contact",
                    "message",
                ),

            "make_whatsapp_call":
                ("contact",),

            "read_file":
                ("path",),

            "write_file":
                ("path",),

            "create_folder":
                ("path",),

            "delete_item":
                ("path",),

            "copy_item":
                (
                    "source",
                    "destination",
                ),

            "move_item":
                (
                    "source",
                    "destination",
                ),

            "rename_item":
                (
                    "path",
                    "new_name",
                ),

            "shell_exec":
                ("command",),
        }

        missing = [
            key
            for key in required.get(
                tool_name,
                (),
            )
            if not clean_string(
                key
            )
        ]

        if missing:

            pretty = ", ".join(
                missing
            )

            return (
                "I need the following information before "
                f"I can run {tool_name}: {pretty}."
            )

        # --------------------------------------------------------
        # Normalize text fields
        # --------------------------------------------------------

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

            if (
                key in args
                and args[key] is not None
                and not isinstance(
                    args[key],
                    bool,
                )
            ):
                args[key] = str(
                    args[key]
                ).strip()

        # --------------------------------------------------------
        # EMAIL
        # --------------------------------------------------------

        if tool_name == "send_email":

            recipient = clean_string(
                "to"
            )

            body = clean_string(
                "body"
            )

            if not recipient:
                return (
                    "I need the recipient email address "
                    "before I can send the email."
                )

            if (
                "@" not in recipient
                or recipient.startswith("@")
                or recipient.endswith("@")
            ):
                return (
                    f"'{recipient}' does not look like "
                    "a valid email address."
                )

            if not body:
                return (
                    "I need the email body/message "
                    "before I can send the email."
                )

            args.setdefault(
                "subject",
                "",
            )

        # --------------------------------------------------------
        # MEDIA
        # --------------------------------------------------------

        if tool_name == "play_media":

            action = (
                clean_string(
                    "action"
                ).lower()
                or "play"
            )

            allowed_actions = {
                "play",
                "pause",
                "next",
                "previous",
            }

            if action not in allowed_actions:

                return (
                    "Unsupported media action. "
                    "Use play, pause, next, or previous."
                )

            args["action"] = action

            if (
                action == "play"
                and not clean_string(
                    "query"
                )
            ):
                return (
                    "Tell me what you want me to play."
                )

            service = (
                clean_string(
                    "service"
                ).lower()
                or "default"
            )

            args["service"] = service

        # --------------------------------------------------------
        # YOUTUBE
        # --------------------------------------------------------

        if tool_name == "youtube":

            action = clean_string(
                "action"
            ).lower()

            allowed_actions = {
                "play",
                "info",
                "summarize",
                "download",
                "trending",
            }

            if not action:

                return (
                    "I need to know what YouTube action "
                    "you want: play, info, summarize, "
                    "download, or trending."
                )

            if action not in allowed_actions:

                return (
                    f"Unsupported YouTube action: {action}."
                )

            args["action"] = action

            if action != "trending":

                has_query = bool(
                    clean_string(
                        "query"
                    )
                )

                has_url = bool(
                    clean_string(
                        "url"
                    )
                )

                if (
                    not has_query
                    and not has_url
                ):
                    return (
                        "I need a YouTube query or URL "
                        f"before I can {action}."
                    )

        # --------------------------------------------------------
        # WHATSAPP CALL
        # --------------------------------------------------------

        if (
            tool_name
            == "make_whatsapp_call"
        ):

            video = args.get(
                "video",
                False,
            )

            if isinstance(
                video,
                str,
            ):

                args["video"] = (
                    video.strip().lower()
                    in {
                        "1",
                        "true",
                        "yes",
                        "video",
                    }
                )

            else:
                args["video"] = bool(
                    video
                )

        # --------------------------------------------------------
        # WRITE FILE
        # --------------------------------------------------------

        if tool_name == "write_file":

            if (
                "content" not in args
                or args["content"] is None
            ):
                args["content"] = ""

            append = args.get(
                "append",
                False,
            )

            if isinstance(
                append,
                str,
            ):

                args["append"] = (
                    append.strip().lower()
                    in {
                        "1",
                        "true",
                        "yes",
                        "append",
                    }
                )

            else:
                args["append"] = bool(
                    append
                )

        # --------------------------------------------------------
        # SAFE DEFAULTS
        # --------------------------------------------------------

        if tool_name == "list_directory":

            if not clean_string(
                "path"
            ):
                args["path"] = "desktop"

        return None

    # ============================================================
    # EXECUTE
    # ============================================================

    def execute(
        self,
        tool_name: str,
        args: Dict[str, Any] | None = None,
        token_id: str | None = None,
    ) -> str:

        args = args or {}

        if not self.supports(
            tool_name
        ):
            return (
                f"Unknown AURIX tool: {tool_name}"
            )

        validation_error = (
            self._validate_args(
                tool_name,
                args,
            )
        )

        if validation_error:

            logger.warning(
                "Rejected malformed tool call: "
                "tool=%s args=%s reason=%s",
                tool_name,
                args,
                validation_error,
            )

            return validation_error

        category = self._get_category(
            tool_name,
            args,
        )

        target = self._get_target(
            tool_name,
            args,
        )

        security_operation = (
            self._security_operation(
                tool_name,
                args,
            )
        )

        request_fingerprint = (
            self._action_fingerprint(
                tool_name,
                args,
            )
        )

        command_text = (
            str(
                args.get(
                    "command",
                    "",
                )
            )
            if tool_name
            == "shell_exec"
            else None
        )

        needs_permission = (
            self.permission_manager.requires_trust_token(
                category=category,
                target_resource=target,
                command_text=command_text,
                operation=security_operation,
                operation_args=args,
            )
        )

        # --------------------------------------------------------
        # SECURITY CONFIRMATION
        # --------------------------------------------------------

        if needs_permission:

            self._cleanup_expired_pending()

            if token_id is None:

                request_id = (
                    secrets.token_hex(
                        6
                    )
                )

                now = time.time()

                self._pending_actions[
                    request_id
                ] = {
                    "tool":
                        tool_name,

                    "args":
                        deepcopy(
                            args
                        ),

                    "category":
                        category,

                    "target":
                        target,

                    "command_text":
                        command_text,

                    "security_operation":
                        security_operation,

                    "fingerprint":
                        request_fingerprint,

                    "created_at":
                        now,

                    "expires_at":
                        (
                            now
                            + PENDING_ACTION_TTL_SECONDS
                        ),
                }

                description = (
                    self._describe_action(
                        tool_name,
                        args,
                    )
                )

                return (
                    "TRUST_TOKEN_REQUIRED:"
                    f"{request_id}:"
                    f"{description}"
                )

            allowed = (
                self.permission_manager.validate_action(
                    category=category,
                    target_resource=target,
                    token_id=token_id,
                    command_text=command_text,
                    operation=security_operation,
                    operation_args=args,
                    request_fingerprint=request_fingerprint,
                )
            )

            if not allowed:
                return (
                    "Security authorization failed."
                )

        # --------------------------------------------------------
        # PHYSICAL EXECUTION
        # --------------------------------------------------------

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

            return (
                f"Tool execution failed: {exc}"
            )

    # ============================================================
    # HUMAN APPROVAL
    # ============================================================

    def confirm_pending(
        self,
        trust_request: str,
    ) -> str:
        """Execute exact pending action after human approval."""

        if trust_request.startswith(
            "TRUST_TOKEN_REQUIRED:"
        ):

            parts = (
                trust_request.split(
                    ":",
                    2,
                )
            )

            if len(parts) < 2:

                return (
                    "Invalid security request."
                )

            request_id = parts[1]

        else:

            request_id = (
                trust_request.strip()
            )

        self._cleanup_expired_pending()

        pending = (
            self._pending_actions.get(
                request_id
            )
        )

        if pending is None:

            return (
                "Security request expired "
                "or no longer exists."
            )

        if (
            time.time()
            > float(
                pending.get(
                    "expires_at",
                    0,
                )
            )
        ):

            self._pending_actions.pop(
                request_id,
                None,
            )

            return (
                "Security request expired. "
                "Please request the action again."
            )

        pending = (
            self._pending_actions.pop(
                request_id
            )
        )

        current_fingerprint = (
            self._action_fingerprint(
                pending["tool"],
                pending["args"],
            )
        )

        stored_fingerprint = str(
            pending.get(
                "fingerprint",
                "",
            )
        )

        if not secrets.compare_digest(
            current_fingerprint,
            stored_fingerprint,
        ):

            logger.error(
                "Pending action %s changed "
                "before execution.",
                request_id,
            )

            return (
                "Security request changed before "
                "execution and was cancelled."
            )

        token = (
            self.permission_manager.grant_trust_token(
                category=pending[
                    "category"
                ],
                target_resource=pending[
                    "target"
                ],
                request_fingerprint=pending[
                    "fingerprint"
                ],
                ttl_seconds=60.0,
            )
        )

        return self.execute(
            tool_name=pending[
                "tool"
            ],
            args=deepcopy(
                pending[
                    "args"
                ]
            ),
            token_id=token.token_id,
        )

    # ============================================================
    # SECURITY CATEGORY
    # ============================================================

    def _get_category(
        self,
        tool_name: str,
        args: Dict[str, Any],
    ) -> ActionCategory:

        if tool_name == "youtube":

            action = str(
                args.get(
                    "action",
                    "",
                )
            ).lower()

            if action == "download":
                return (
                    ActionCategory.FILE_WRITE
                )

            if action == "play":
                return (
                    ActionCategory.APP_CONTROL
                )

            return (
                ActionCategory.LOCAL_SEARCH
            )

        mapping = {

            "open_app":
                ActionCategory.APP_CONTROL,

            "close_app":
                ActionCategory.APP_CONTROL,

            "play_media":
                ActionCategory.APP_CONTROL,

            "web_search":
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

        return mapping[
            tool_name
        ]

    # ============================================================
    # SECURITY TARGET
    # ============================================================

    def _get_target(
        self,
        tool_name: str,
        args: Dict[str, Any],
    ) -> str:
        """Build exact authorization target."""

        if tool_name in {
            "copy_item",
            "move_item",
        }:

            return (
                f"source={args.get('source', '')}"
                f"|destination={args.get('destination', '')}"
            )

        if tool_name == "rename_item":

            return (
                f"path={args.get('path', '')}"
                f"|new_name={args.get('new_name', '')}"
            )

        if tool_name == "send_email":

            return (
                f"recipient={args.get('to', '')}"
            )

        if tool_name in {
            "send_whatsapp_message",
            "make_whatsapp_call",
        }:

            return (
                f"contact={args.get('contact', '')}"
            )

        if tool_name == "youtube":

            action = str(
                args.get(
                    "action",
                    "",
                )
            )

            source = (
                args.get(
                    "url"
                )
                or args.get(
                    "query"
                )
                or ""
            )

            return (
                f"youtube_action={action}"
                f"|source={source}"
            )

        if tool_name == "shell_exec":

            return (
                f"command={args.get('command', '')}"
            )

        if tool_name in {
            "list_directory",
            "read_file",
            "write_file",
            "create_folder",
            "delete_item",
        }:

            return (
                f"path={args.get('path', '')}"
            )

        if tool_name in {
            "open_app",
            "close_app",
        }:

            return (
                f"target={args.get('target', '')}"
            )

        if tool_name == "web_search":

            return (
                f"query={args.get('query', '')}"
            )

        return tool_name

    # ============================================================
    # HUMAN-READABLE CONFIRMATION
    # ============================================================

    def _describe_action(
        self,
        tool_name: str,
        args: Dict[str, Any],
    ) -> str:

        if tool_name == "delete_item":

            return (
                f"Delete {args.get('path')}"
            )

        if tool_name == "send_email":

            body = str(
                args.get(
                    "body",
                    "",
                )
            )

            preview = (
                body[:180]
                + (
                    "..."
                    if len(body) > 180
                    else ""
                )
            )

            return (
                f"Send email to {args.get('to')} "
                f"| Subject: {args.get('subject', '')} "
                f"| Message: {preview}"
            )

        if (
            tool_name
            == "send_whatsapp_message"
        ):

            message = str(
                args.get(
                    "message",
                    "",
                )
            )

            preview = (
                message[:180]
                + (
                    "..."
                    if len(message) > 180
                    else ""
                )
            )

            return (
                "Send WhatsApp message to "
                f"{args.get('contact')} "
                f"| Message: {preview}"
            )

        if (
            tool_name
            == "make_whatsapp_call"
        ):

            call_type = (
                "video"
                if args.get(
                    "video",
                    False,
                )
                else "voice"
            )

            return (
                f"Start {call_type} WhatsApp call "
                f"with {args.get('contact')}"
            )

        if tool_name == "shell_exec":

            return (
                "Run command: "
                f"{args.get('command')}"
            )

        if tool_name == "move_item":

            return (
                f"Move {args.get('source')} "
                f"to {args.get('destination')}"
            )

        if tool_name == "copy_item":

            return (
                f"Copy {args.get('source')} "
                f"to {args.get('destination')}"
            )

        if tool_name == "rename_item":

            return (
                f"Rename {args.get('path')} "
                f"to {args.get('new_name')}"
            )

        if (
            tool_name == "youtube"
            and args.get(
                "action"
            ) == "download"
        ):

            return (
                "Download YouTube content: "
                f"{args.get('url') or args.get('query')}"
            )

        if tool_name == "write_file":

            return (
                f"Write file {args.get('path')}"
            )

        if tool_name == "create_folder":

            return (
                f"Create folder {args.get('path')}"
            )

        return (
            f"Execute {tool_name}"
        )

    # ============================================================
    # ACTUAL TOOLS
    # ============================================================

    def _execute_actual(
        self,
        tool: str,
        args: Dict[str, Any],
    ) -> str:

        # --------------------------------------------------------
        # APP CONTROL
        # --------------------------------------------------------

        if tool == "open_app":

            return self.launcher.launch(
                str(
                    args.get(
                        "target",
                        "",
                    )
                )
            )

        if tool == "close_app":

            return self.closer.close(
                str(
                    args.get(
                        "target",
                        "",
                    )
                )
            )

        # --------------------------------------------------------
        # MEDIA
        # --------------------------------------------------------

        if tool == "play_media":

            action = str(
                args.get(
                    "action",
                    "play",
                )
            ).lower()

            query = str(
                args.get(
                    "query",
                    "",
                )
            )

            service = str(
                args.get(
                    "service",
                    "spotify",
                )
            )

            if action == "pause":
                return (
                    self.media.toggle_playback()
                )

            if action == "next":
                return (
                    self.media.next_track()
                )

            if action == "previous":
                return (
                    self.media.prev_track()
                )

            return self.media.play(
                query,
                service=service,
            )

        # --------------------------------------------------------
        # WEB
        # --------------------------------------------------------

        if tool == "web_search":

            return self.searcher.search(
                str(
                    args.get(
                        "query",
                        "",
                    )
                )
            )

        # --------------------------------------------------------
        # YOUTUBE
        # --------------------------------------------------------

        if tool == "youtube":

            return youtube_video(
                args
            )

        # --------------------------------------------------------
        # EMAIL
        # --------------------------------------------------------

        if tool == "send_email":

            return self.email.send_email(
                str(
                    args.get(
                        "to",
                        "",
                    )
                ),
                str(
                    args.get(
                        "subject",
                        "",
                    )
                ),
                str(
                    args.get(
                        "body",
                        "",
                    )
                ),

                # IMPORTANT:
                # This can only be reached after ToolExecutor's
                # permission/trust-token flow succeeds.
                authorized=True,
            )

        # --------------------------------------------------------
        # WHATSAPP MESSAGE
        # --------------------------------------------------------

        if (
            tool
            == "send_whatsapp_message"
        ):

            contact = str(
                args.get(
                    "contact",
                    "",
                )
            )

            message = str(
                args.get(
                    "message",
                    "",
                )
            )

            pending = (
                self.whatsapp.prepare_message(
                    contact,
                    message,
                )
            )

            result = (
                self.whatsapp.execute(
                    pending,

                    # Central authorization already succeeded.
                    authorized=True,
                )
            )

            return result.detail

        # --------------------------------------------------------
        # WHATSAPP CALL
        # --------------------------------------------------------

        if (
            tool
            == "make_whatsapp_call"
        ):

            contact = str(
                args.get(
                    "contact",
                    "",
                )
            )

            video = bool(
                args.get(
                    "video",
                    False,
                )
            )

            pending = (
                self.whatsapp.prepare_call(
                    contact,
                    video=video,
                )
            )

            result = (
                self.whatsapp.execute(
                    pending,

                    # Central authorization already succeeded.
                    authorized=True,
                )
            )

            return result.detail

        # --------------------------------------------------------
        # FILE LIST
        # --------------------------------------------------------

        if tool == "list_directory":

            return (
                self.files.list_directory(
                    str(
                        args.get(
                            "path",
                            "desktop",
                        )
                    )
                )
            )

        # --------------------------------------------------------
        # FILE READ
        # --------------------------------------------------------

        if tool == "read_file":

            return self.files.read_file(
                str(
                    args.get(
                        "path",
                        "",
                    )
                )
            )

        # --------------------------------------------------------
        # FILE WRITE
        # --------------------------------------------------------

        if tool == "write_file":

            return self.files.write_file(
                str(
                    args.get(
                        "path",
                        "",
                    )
                ),
                str(
                    args.get(
                        "content",
                        "",
                    )
                ),
                append=bool(
                    args.get(
                        "append",
                        False,
                    )
                ),
            )

        # --------------------------------------------------------
        # CREATE FOLDER
        # --------------------------------------------------------

        if tool == "create_folder":

            return (
                self.files.create_folder(
                    str(
                        args.get(
                            "path",
                            "",
                        )
                    )
                )
            )

        # --------------------------------------------------------
        # DELETE
        # --------------------------------------------------------

        if tool == "delete_item":

            return (
                self.files.delete_item(
                    str(
                        args.get(
                            "path",
                            "",
                        )
                    ),
                    visual=False,
                )
            )

        # --------------------------------------------------------
        # COPY
        # --------------------------------------------------------

        if tool == "copy_item":

            return (
                self.files.copy_item(
                    str(
                        args.get(
                            "source",
                            "",
                        )
                    ),
                    str(
                        args.get(
                            "destination",
                            "",
                        )
                    ),
                    visual=False,
                )
            )

        # --------------------------------------------------------
        # MOVE
        # --------------------------------------------------------

        if tool == "move_item":

            return (
                self.files.move_item(
                    str(
                        args.get(
                            "source",
                            "",
                        )
                    ),
                    str(
                        args.get(
                            "destination",
                            "",
                        )
                    ),
                    visual=False,
                )
            )

        # --------------------------------------------------------
        # RENAME
        # --------------------------------------------------------

        if tool == "rename_item":

            return (
                self.files.rename_item(
                    str(
                        args.get(
                            "path",
                            "",
                        )
                    ),
                    str(
                        args.get(
                            "new_name",
                            "",
                        )
                    ),
                    visual=False,
                )
            )

        # --------------------------------------------------------
        # SHELL
        # --------------------------------------------------------

        if tool == "shell_exec":

            command = str(
                args.get(
                    "command",
                    "",
                )
            ).strip()

            if not command:
                return (
                    "No command provided."
                )

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
                    "Command was stopped because it "
                    "exceeded the 30 second execution limit."
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

        return (
            f"Unsupported tool: {tool}"
        )