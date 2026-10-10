"""Action emergency stop/offline guard must not be bypassable by model output."""
import pytest
from security import action_control
from ai_brain.tool_executor import ToolExecutor
from security.permissions import PermissionManager, ActionCategory


def test_emergency_halt_blocks_actions():
    action_control.stop_actions()
    try:
        assert ToolExecutor().execute("read_file", {"path": "desktop"}).startswith("ACTION_STOPPED")
    finally:
        action_control.resume_actions()


def test_offline_mode_restricts_online_tools():
    action_control.set_offline_mode(True)
    assert ToolExecutor().execute("web_search", {"query": "latest news"}).startswith("OFFLINE_MODE")
    action_control.set_offline_mode(False)
    assert action_control.network_allowed("web_search")
    action_control.set_offline_mode(True)


def test_tier_three_cannot_be_disabled_by_config():
    manager = PermissionManager(config={"security": {
        "trust_token_required": False,
        "permissions": {"require_trust_token_for_comms": False},
    }})
    for category in (ActionCategory.FILE_DELETE, ActionCategory.SYSTEM_SETTING, ActionCategory.EXTERNAL_COMMUNICATION):
        assert manager.requires_trust_token(category, "action")
