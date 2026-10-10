"""Scoped Git tools retain policy controls."""
from ai_brain.tool_executor import ToolExecutor
from security.action_control import set_offline_mode
from security.permissions import ActionCategory


def test_git_push_is_tier_three():
    executor = ToolExecutor()
    assert executor._get_category("git_push", {"repo": "C:/repo"}) == ActionCategory.EXTERNAL_COMMUNICATION
    assert executor._get_category("git_commit", {"repo": "C:/repo"}) == ActionCategory.SYSTEM_SETTING


def test_offline_mode_blocks_git_push_before_repository_resolution():
    set_offline_mode(True)
    assert ToolExecutor().execute("git_push", {}).startswith("OFFLINE_MODE")


def test_git_publish_preview_displays_destination():
    message = ToolExecutor()._describe_action("git_push", {"repo": "C:/trusted", "branch": "main"})
    assert "origin" in message and "main" in message
