"""Privileged action intent and complete outgoing preview checks."""
from ai_brain.tool_executor import ToolExecutor
from security.permissions import ActionCategory


def test_program_launch_requires_approval():
    executor = ToolExecutor()
    assert executor._get_category("open_app", {"target": "powershell"}) == ActionCategory.SYSTEM_SETTING


def test_outbound_email_preview_contains_complete_message():
    executor = ToolExecutor()
    message = "project proposal " * 24
    args = {"to": "recipient@example.com", "subject": "Proposal", "body": message}
    assert executor._validate_args("send_email", args) is None
    # Tool validation normalizes trailing whitespace before sending.
    assert args["body"] in executor._describe_action("send_email", args)


def test_oversized_communication_is_rejected():
    executor = ToolExecutor()
    assert "too long" in executor._validate_args(
        "send_email", {"to": "test@example.com", "body": "x" * 601}
    )
    assert "too long" in executor._validate_args(
        "send_whatsapp_message", {"contact": "test", "message": "x" * 601}
    )
