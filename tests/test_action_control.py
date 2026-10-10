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


def test_pre_stop_native_approval_cannot_be_reused_after_resume(monkeypatch):
    from unittest.mock import patch
    executor = ToolExecutor()
    with patch.object(executor, "_execute_actual") as physical:
        staged = executor.execute("open_app", {"target": "powershell"})
        assert staged.startswith("TRUST_TOKEN_REQUIRED:")
        request_id = staged.split(":")[1]
        assert executor.preview_pending(request_id).get("description")
        action_control.stop_actions()
        action_control.resume_actions()
        assert "cancelled" in executor.confirm_pending(request_id).lower()
        physical.assert_not_called()


def test_voice_emergency_stop_is_deterministic_and_blocks_actions():
    from ai_brain.dispatcher import BrainDispatcher
    action_control.resume_actions()
    try:
        reply, handled = BrainDispatcher().dispatch("Hey Luna stop")
        assert handled and "Emergency block" in reply
        assert action_control.action_is_stopped()
        assert ToolExecutor().execute("open_app", {"target": "notepad"}).startswith("ACTION_STOPPED")
    finally:
        action_control.resume_actions()
