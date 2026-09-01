"""Unit tests for PermissionManager and TrustToken verification."""

import pytest
from security.permissions import ActionCategory, PermissionManager, TrustToken


def test_permission_manager_requires_trust_token():
    manager = PermissionManager()
    assert manager.requires_trust_token(ActionCategory.FILE_DELETE, "sensitive_file.py") is True
    assert manager.requires_trust_token(ActionCategory.CHECKPOINT_RESTORE, "ckpt_1") is True
    assert manager.requires_trust_token(ActionCategory.FILE_READ, "main.rs") is False


def test_permission_manager_token_issuance_and_consumption():
    manager = PermissionManager()
    token = manager.issue_trust_token(ActionCategory.FILE_DELETE, "data/temp.csv")
    assert token.token_id.startswith("tok_")
    assert token.used is False

    # Validate action with token
    valid = manager.validate_action(ActionCategory.FILE_DELETE, "data/temp.csv", token.token_id)
    assert valid is True

    # Token cannot be reused
    invalid_second_attempt = manager.validate_action(ActionCategory.FILE_DELETE, "data/temp.csv", token.token_id)
    assert invalid_second_attempt is False


def test_permission_manager_rejects_mismatched_resource():
    manager = PermissionManager()
    token = manager.issue_trust_token(ActionCategory.FILE_DELETE, "data/temp.csv")

    # Mismatched target resource
    valid = manager.validate_action(ActionCategory.FILE_DELETE, "system32/kernel.dll", token.token_id)
    assert valid is False
