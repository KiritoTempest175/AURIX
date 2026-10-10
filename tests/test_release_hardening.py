"""Regression coverage for release blockers, without models or real actions."""
import hashlib
import http.client
import json
import threading
from unittest.mock import Mock, patch

import pytest

from frontend import bridge_server as bridge
from ai_brain.dispatcher import BrainDispatcher
from ai_brain.tool_executor import ToolExecutor
from ai_engine.inference import local_gguf
from security import action_control
from scripts.import_model import verify_and_import


@pytest.fixture
def private_bridge():
    server = bridge.SecureServer(("127.0.0.1", 0), bridge.BridgeHandler, "a" * 64)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def post(server, path, body, **headers):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    conn.request("POST", path, json.dumps(body), headers={
        "Authorization": "Bearer " + server.token, **headers,
    })
    response = conn.getresponse()
    result = response.status, json.loads(response.read())
    conn.close()
    return result


def test_live_bridge_rejects_browser(private_bridge):
    assert post(private_bridge, "/dispatch", {"text": "hey luna"}, Origin="https://bad.test")[0] == 401


def test_busy_dispatch_does_not_wait_or_run_later(private_bridge):
    with patch.object(bridge, "dispatcher") as dispatcher:
        with bridge._execute_lock:
            status, body = post(private_bridge, "/dispatch", {"text": "open notepad"})
        assert (status, body["error"]) == (409, "WORKER_BUSY")
        dispatcher.assert_not_called()


def test_rate_limit_reserves_emergency_stop(private_bridge):
    with private_bridge._rate_lock:
        private_bridge._tokens = -100
    assert post(private_bridge, "/dispatch", {"text": "hey luna"})[0] == 429
    try:
        assert post(private_bridge, "/kill", {}) == (200, {"stopped": True, "note": "new actions blocked"})
        assert action_control.action_is_stopped()
    finally:
        action_control.resume_actions()


def test_stop_invalidates_existing_approval_after_resume():
    executor = ToolExecutor()
    pending = executor.execute("delete_item", {"path": "file.txt"})
    request = pending.split(":", 2)[1]
    action_control.stop_actions()
    action_control.resume_actions()
    with patch.object(executor, "_execute_actual") as actual:
        assert executor.confirm_pending(request).startswith("ACTION_STOPPED")
        actual.assert_not_called()


def test_stop_voice_phrase_does_not_require_model():
    try:
        dispatcher = BrainDispatcher(model_runner=Mock())
        reply, handled = dispatcher.dispatch("Hey Luna stop!")
        assert handled and "blocked" in reply
        assert action_control.action_is_stopped()
        dispatcher.router._runner.select_tool.assert_not_called()
    finally:
        action_control.resume_actions()


def test_approval_contains_write_contents_and_mode():
    preview = ToolExecutor()._describe_action("write_file", {"path": "notes.txt", "content": "replacement", "append": False})
    assert "replacement" in preview and '"append": false' in preview


def test_native_preview_cannot_hide_arguments_after_nul():
    result = ToolExecutor().execute("open_app", {"target": "notepad\x00powershell"})
    assert result.startswith("INVALID_ARGUMENT")


def test_idle_reaper_closes_real_singleton_and_preserves_history(monkeypatch):
    runner = local_gguf.LocalGGUFRunner({"model_path": ""})
    runner._model = Mock()
    model = runner._model
    runner._history = [{"role": "user", "content": "remember conversation"}]
    runner._last_used = 0
    monkeypatch.setattr(local_gguf, "_default_runner", runner)
    assert local_gguf.reap_idle_runner()
    model.close.assert_called_once()
    assert runner._model is None and runner._history


def test_failed_import_preserves_existing_model(tmp_path, monkeypatch):
    monkeypatch.setenv("AURIX_DATA_DIR", str(tmp_path / "data"))
    source = tmp_path / "test.gguf"
    source.write_bytes(b"original")
    destination = verify_and_import(source, hashlib.sha256(b"original").hexdigest())
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="verification failed"):
        verify_and_import(source, hashlib.sha256(b"original").hexdigest())
    assert destination.read_bytes() == b"original"
    assert not list(destination.parent.glob("*.part"))


def test_desktop_router_uses_embedded_model():
    from ai_brain import agent_router
    assert agent_router.get_model_runner is local_gguf.get_default_local_runner
