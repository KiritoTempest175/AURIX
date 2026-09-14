"""AURIX Permission Scoping & Trust Token Enforcement.

Security goals:
- Exact trust-token binding.
- One-time authorization.
- Expiring authorization.
- Bind authorization to the exact tool arguments.
- Require approval for destructive/risky file writes.
"""

from __future__ import annotations

import enum
import logging
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aurix.security.permissions")


class ActionCategory(enum.Enum):
    """Categorized autonomous capability scopes."""

    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"

    SHELL_EXEC = "shell_exec"

    APP_CONTROL = "app_control"
    LOCAL_SEARCH = "local_search"

    CHECKPOINT_RESTORE = "checkpoint_restore"
    SYSTEM_SETTING = "system_setting"

    EXTERNAL_COMMUNICATION = "external_communication"


def _normalize_resource(resource: str) -> str:
    """Normalize a security resource for exact comparison."""

    return str(resource or "").strip().casefold()


@dataclass
class TrustToken:
    """Single-use authorization issued after explicit human approval."""

    token_id: str

    action_category: ActionCategory

    target_resource: str

    # SHA-256 fingerprint of:
    #
    # {
    #     "tool": ...,
    #     "args": ...
    # }
    #
    # This prevents an approved action from having its arguments changed
    # before execution.
    request_fingerprint: Optional[str] = None

    created_at: float = field(
        default_factory=time.time
    )

    expires_at: float = field(
        default_factory=lambda: time.time() + 60.0
    )

    used: bool = False

    def is_valid(
        self,
        category: ActionCategory,
        resource: str,
        request_fingerprint: Optional[str] = None,
    ) -> bool:
        """Validate token against the exact approved action."""

        if self.used:
            return False

        if time.time() > self.expires_at:
            return False

        if self.action_category != category:
            return False

        approved_resource = _normalize_resource(
            self.target_resource
        )

        requested_resource = _normalize_resource(
            resource
        )

        # IMPORTANT:
        #
        # Old implementation used substring matching:
        #
        #   approved in requested
        #
        # That allowed loosely related resources to reuse the token.
        #
        # Security authorization must use exact binding.
        if not secrets.compare_digest(
            approved_resource,
            requested_resource,
        ):
            return False

        # If token was issued for a specific action fingerprint,
        # the exact fingerprint must be presented.
        if self.request_fingerprint is not None:

            if not request_fingerprint:
                return False

            if not secrets.compare_digest(
                self.request_fingerprint,
                request_fingerprint,
            ):
                return False

        return True


class PermissionManager:
    """Central AURIX permission policy."""

    HIGH_RISK_CATEGORIES = {
        ActionCategory.FILE_DELETE,
        ActionCategory.CHECKPOINT_RESTORE,
        ActionCategory.SYSTEM_SETTING,
    }

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:

        self.config = config or {}

        self._active_tokens: Dict[
            str,
            TrustToken,
        ] = {}

        security_cfg = self.config.get(
            "security",
            {},
        )

        self._allowed_paths: List[str] = security_cfg.get(
            "allowed_project_paths",
            [],
        )

    # ============================================================
    # PATH POLICY
    # ============================================================

    @staticmethod
    def _resolve_path(path_value: str) -> Optional[Path]:

        if not path_value:
            return None

        try:
            return Path(
                path_value
            ).expanduser().resolve(
                strict=False
            )

        except Exception:
            return None

    def _is_inside_allowed_paths(
        self,
        path_value: str,
    ) -> bool:
        """Return True when path is inside an explicitly trusted workspace."""

        requested = self._resolve_path(
            path_value
        )

        if requested is None:
            return False

        if not self._allowed_paths:
            return False

        for allowed_value in self._allowed_paths:

            allowed = self._resolve_path(
                allowed_value
            )

            if allowed is None:
                continue

            try:

                requested.relative_to(
                    allowed
                )

                return True

            except ValueError:
                continue

        return False

    # ============================================================
    # TOKENS
    # ============================================================

    def issue_trust_token(
        self,
        category: ActionCategory,
        target_resource: str,
        request_fingerprint: Optional[str] = None,
        ttl_seconds: float = 60.0,
    ) -> TrustToken:
        """Issue a short-lived, single-use Trust Token."""

        token_id = (
            f"tok_{secrets.token_hex(16)}"
        )

        now = time.time()

        token = TrustToken(
            token_id=token_id,
            action_category=category,
            target_resource=target_resource,
            request_fingerprint=request_fingerprint,
            created_at=now,
            expires_at=now + ttl_seconds,
        )

        self._active_tokens[
            token_id
        ] = token

        logger.info(
            "Issued Trust Token %s for %s on '%s'",
            token_id,
            category.value,
            target_resource,
        )

        return token

    def grant_trust_token(
        self,
        category: ActionCategory,
        target_resource: str,
        request_fingerprint: Optional[str] = None,
        user_id: str = "user_approved",
        ttl_seconds: float = 60.0,
    ) -> TrustToken:
        """Grant token after explicit human approval."""

        return self.issue_trust_token(
            category=category,
            target_resource=target_resource,
            request_fingerprint=request_fingerprint,
            ttl_seconds=ttl_seconds,
        )

    # ============================================================
    # FILE WRITE POLICY
    # ============================================================

    def _file_write_requires_confirmation(
        self,
        operation: Optional[str],
        args: Dict[str, Any],
    ) -> bool:
        """Apply risk-based policy instead of treating every write equally."""

        operation = (
            operation or ""
        ).strip().lower()

        # --------------------------------------------------------
        # YouTube download
        # --------------------------------------------------------

        if operation == "youtube_download":
            return True

        # --------------------------------------------------------
        # Move
        #
        # Existing data changes location.
        # --------------------------------------------------------

        if operation == "move_item":
            return True

        # --------------------------------------------------------
        # Rename
        #
        # Existing file/folder identity changes.
        # --------------------------------------------------------

        if operation == "rename_item":
            return True

        # --------------------------------------------------------
        # WRITE FILE
        # --------------------------------------------------------

        if operation == "write_file":

            path = str(
                args.get(
                    "path",
                    "",
                )
            ).strip()

            append = bool(
                args.get(
                    "append",
                    False,
                )
            )

            resolved = self._resolve_path(
                path
            )

            # Unknown path => fail safe.
            if resolved is None:
                return True

            # Anything outside explicitly trusted workspace
            # requires approval.
            if not self._is_inside_allowed_paths(
                path
            ):
                return True

            # Existing file overwrite is destructive-ish.
            #
            # Append is less risky and can remain autonomous
            # inside an approved workspace.
            if resolved.exists() and not append:
                return True

            # New file inside trusted workspace.
            return False

        # --------------------------------------------------------
        # CREATE FOLDER
        # --------------------------------------------------------

        if operation == "create_folder":

            path = str(
                args.get(
                    "path",
                    "",
                )
            ).strip()

            # Creating inside explicitly trusted workspace is safe.
            return not self._is_inside_allowed_paths(
                path
            )

        # --------------------------------------------------------
        # COPY
        # --------------------------------------------------------

        if operation == "copy_item":

            destination = str(
                args.get(
                    "destination",
                    "",
                )
            ).strip()

            resolved_destination = (
                self._resolve_path(
                    destination
                )
            )

            if resolved_destination is None:
                return True

            # Copy outside trusted workspace.
            if not self._is_inside_allowed_paths(
                destination
            ):
                return True

            # Replacing something that already exists.
            if resolved_destination.exists():
                return True

            return False

        # Unknown FILE_WRITE operation:
        # safest behavior is confirmation.
        return True

    # ============================================================
    # POLICY
    # ============================================================

    def requires_trust_token(
        self,
        category: ActionCategory,
        target_resource: str,
        command_text: Optional[str] = None,
        operation: Optional[str] = None,
        operation_args: Optional[
            Dict[str, Any]
        ] = None,
    ) -> bool:
        """Determine whether explicit approval is required."""

        security_cfg = self.config.get(
            "security",
            {},
        )

        permissions_cfg = security_cfg.get(
            "permissions",
            {},
        )

        security_enabled = security_cfg.get(
            "trust_token_required",
            True,
        )

        if not security_enabled:
            return False

        # --------------------------------------------------------
        # ALWAYS HIGH RISK
        # --------------------------------------------------------

        if category in self.HIGH_RISK_CATEGORIES:
            return True

        # --------------------------------------------------------
        # RISK-BASED FILE WRITES
        # --------------------------------------------------------

        if category == ActionCategory.FILE_WRITE:

            return self._file_write_requires_confirmation(
                operation=operation,
                args=operation_args or {},
            )

        # --------------------------------------------------------
        # EXTERNAL COMMUNICATION
        # --------------------------------------------------------

        if (
            category
            == ActionCategory.EXTERNAL_COMMUNICATION
        ):

            return permissions_cfg.get(
                "require_trust_token_for_comms",
                True,
            )

        # --------------------------------------------------------
        # SHELL
        # --------------------------------------------------------

        if category == ActionCategory.SHELL_EXEC:

            if permissions_cfg.get(
                "require_trust_token_for_shell",
                True,
            ):
                return True

            dangerous_triggers = [
                "rm ",
                "del ",
                "erase ",
                "rmdir",
                "rd ",
                "format ",
                "mkfs",
                "diskpart",
                "drop table",
                "drop database",
                "shutdown",
                "reboot",
                "restart-computer",
                "stop-computer",
                "reg delete",
                "bcdedit",
            ]

            command_lower = (
                command_text or ""
            ).casefold()

            return any(
                trigger in command_lower
                for trigger in dangerous_triggers
            )

        return False

    # ============================================================
    # VALIDATION
    # ============================================================

    def validate_action(
        self,
        category: ActionCategory,
        target_resource: str,
        token_id: Optional[str] = None,
        command_text: Optional[str] = None,
        operation: Optional[str] = None,
        operation_args: Optional[
            Dict[str, Any]
        ] = None,
        request_fingerprint: Optional[str] = None,
    ) -> bool:
        """Validate an action before physical execution."""

        needs_token = self.requires_trust_token(
            category=category,
            target_resource=target_resource,
            command_text=command_text,
            operation=operation,
            operation_args=operation_args,
        )

        if not needs_token:
            return True

        if not token_id:

            logger.warning(
                "Action %s rejected: missing Trust Token",
                category.value,
            )

            return False

        token = self._active_tokens.get(
            token_id
        )

        if token is None:

            logger.warning(
                "Unknown Trust Token: %s",
                token_id,
            )

            return False

        if not token.is_valid(
            category=category,
            resource=target_resource,
            request_fingerprint=request_fingerprint,
        ):

            logger.warning(
                "Action %s on %s rejected: "
                "invalid, expired or mismatched token %s",
                category.value,
                target_resource,
                token_id,
            )

            return False

        # Single-use token.
        token.used = True

        # Remove from active store after successful consumption.
        self._active_tokens.pop(
            token_id,
            None,
        )

        return True


_GLOBAL_PERMISSION_MANAGER = (
    PermissionManager()
)


def get_default_permission_manager() -> PermissionManager:
    """Return global PermissionManager."""

    return _GLOBAL_PERMISSION_MANAGER