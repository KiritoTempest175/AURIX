"""LUNA Permission Scoping & Trust Token Enforcement.

Enforces principle of least privilege, mapping autonomous agent actions to
defined security categories and requiring interactive human-in-the-loop Trust Tokens
for high-impact or destructive operations.
"""

from __future__ import annotations

import enum
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("luna.security.permissions")


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


@dataclass
class TrustToken:
    """Cryptographic authorization token issued upon explicit human approval."""
    token_id: str
    action_category: ActionCategory
    target_resource: str
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 60.0) # 60s validity window
    used: bool = False

    def is_valid(self, category: ActionCategory, resource: str) -> bool:
        """Check if token is valid, unused, unexpired, and matches target action."""
        now = time.time()
        if self.used:
            return False
        if now > self.expires_at:
            return False
        if self.action_category != category:
            return False
        # Target resource check (case-insensitive substring or match)
        if resource.lower() not in self.target_resource.lower() and self.target_resource.lower() not in resource.lower():
            return False
        return True


class PermissionManager:
    """Evaluates agent execution intents against security policies and trust token requirements."""

    # Actions inherently destructive or high risk that mandate human Trust Token authorization
    HIGH_RISK_CATEGORIES: Set[ActionCategory] = {
        ActionCategory.FILE_DELETE,
        ActionCategory.CHECKPOINT_RESTORE,
        ActionCategory.SYSTEM_SETTING,
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        """Initialize PermissionManager from configuration dictionary."""
        self.config = config or {}
        self._active_tokens: Dict[str, TrustToken] = {}
        self._allowed_paths: List[str] = self.config.get("security", {}).get("allowed_project_paths", [])

    def issue_trust_token(self, category: ActionCategory, target_resource: str, ttl_seconds: float = 60.0) -> TrustToken:
        """Issue a new Trust Token upon user confirmation."""
        token_id = f"tok_{secrets.token_hex(8)}"
        token = TrustToken(
            token_id=token_id,
            action_category=category,
            target_resource=target_resource,
            expires_at=time.time() + ttl_seconds,
        )
        self._active_tokens[token_id] = token
        logger.info(f"Issued Trust Token {token_id} for {category.value} on '{target_resource}'")
        return token

    def requires_trust_token(self, category: ActionCategory, target_resource: str, command_text: Optional[str] = None) -> bool:
        """Determine if an action requires explicit interactive human approval."""
        if category in self.HIGH_RISK_CATEGORIES:
            return True

        # Check shell exec destructive commands
        if category == ActionCategory.SHELL_EXEC and command_text:
            dangerous_triggers = ["rm ", "del ", "rmdir", "format ", "mkfs", "drop table", "shutdown", "reboot"]
            if any(term in command_text.lower() for term in dangerous_triggers):
                return True

        return False

    def validate_action(
        self,
        category: ActionCategory,
        target_resource: str,
        token_id: Optional[str] = None,
        command_text: Optional[str] = None,
    ) -> bool:
        """Validate if an agent action is permitted under current security context.

        Args:
            category: The action scope.
            target_resource: Path or target system identifier.
            token_id: Optional Trust Token ID presented for confirmation.
            command_text: Optional shell command body.

        Returns:
            True if action is allowed to proceed, False otherwise.
        """
        needs_token = self.requires_trust_token(category, target_resource, command_text)
        if not needs_token:
            return True

        if not token_id or token_id not in self._active_tokens:
            logger.warning(f"Action {category.value} on {target_resource} rejected: missing valid Trust Token")
            return False

        token = self._active_tokens[token_id]
        if not token.is_valid(category, target_resource):
            logger.warning(f"Action {category.value} on {target_resource} rejected: invalid/expired Trust Token {token_id}")
            return False

        # Mark token as used
        token.used = True
        return True


_GLOBAL_PERMISSION_MANAGER: PermissionManager = PermissionManager()


def get_default_permission_manager() -> PermissionManager:
    """Return default PermissionManager."""
    return _GLOBAL_PERMISSION_MANAGER
