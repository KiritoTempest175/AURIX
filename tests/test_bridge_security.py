"""Abuse-case checks for transport and sensitive-operation controls."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from frontend.bridge_server import BridgeHandler, MAX_BODY
from ai_brain.tool_executor import ToolExecutor
from ai_brain.second_brain import SecondBrain


def test_bridge_rejects_missing_bearer_token():
    handler = object.__new__(BridgeHandler)
    handler.server = Mock(server_port=9721, token="temporary-secret-for-testing")
    handler.headers = {"Host": "127.0.0.1:9721"}
    assert not handler._authorized()


def test_bridge_rejects_browser_origins_even_with_token():
    handler = object.__new__(BridgeHandler)
    token = "temporary-secret-for-testing"
    handler.server = Mock(server_port=9721, token=token)
    handler.headers = {
        "Host": "127.0.0.1:9721",
        "Authorization": "Bearer " + token,
        "Origin": "https://attacker.example",
    }
    assert not handler._authorized()


def test_bridge_rejects_foreign_hosts():
    handler = object.__new__(BridgeHandler)
    token = "temporary-secret-for-testing"
    handler.server = Mock(server_port=9721, token=token)
    handler.headers = {"Host": "evil.test:9721", "Authorization": "Bearer " + token}
    assert not handler._authorized()


def test_shell_is_disabled_without_a_process_sandbox():
    assert ToolExecutor().execute("shell_exec", {"command": "whoami"}).startswith("SHELL_DISABLED")


def test_vault_rejects_sibling_prefix(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    outside = tmp_path / "vault-malicious" / "notes.md"
    brain = SecondBrain(vault)
    with pytest.raises(ValueError, match="escapes"):
        brain._resolve(str(outside))


def test_preview_requires_pending_action():
    assert ToolExecutor().preview_pending("not-a-real-request")["error"] == "NOT_FOUND"


def test_bridge_rejects_referer_and_browser_fetch_metadata():
    handler = object.__new__(BridgeHandler)
    token = "temporary-secret-for-testing"
    handler.server = Mock(server_port=9721, token=token)
    for forbidden in (
        {"Referer": "http://127.0.0.1:9721/"},
        {"Sec-Fetch-Site": "none"},
        {"Sec-Fetch-Site": "cross-site"},
    ):
        handler.headers = {
            "Host": "127.0.0.1:9721",
            "Authorization": "Bearer " + token,
            **forbidden,
        }
        assert not handler._authorized()


def test_worker_port_is_selected_from_validated_local_env(monkeypatch):
    from frontend.bridge_server import bridge_port
    monkeypatch.delenv("AURIX_BRIDGE_PORT", raising=False)
    assert bridge_port() == 9721
    monkeypatch.setenv("AURIX_BRIDGE_PORT", "58231")
    assert bridge_port() == 58231
    for bad in ("0", "80", "65536", "-1", "http://evil.invalid", "not-a-number"):
        monkeypatch.setenv("AURIX_BRIDGE_PORT", bad)
        with pytest.raises(ValueError, match="INVALID_BRIDGE_PORT"):
            bridge_port()


def test_bridge_rejects_chunked_smuggling_even_with_content_length():
    handler = object.__new__(BridgeHandler)
    handler.headers = {
        "Transfer-Encoding": "chunked",
        "Content-Length": "2",
    }
    with pytest.raises(ValueError, match="TRANSFER_ENCODING_UNSUPPORTED"):
        handler._body()


def test_bridge_mutations_have_bounded_token_bucket():
    import threading
    import time
    from frontend.bridge_server import SecureServer
    server = object.__new__(SecureServer)
    server._rate_lock = threading.Lock()
    server._tokens = 1.0
    server._refill = time.monotonic()
    assert server.admit()
    assert not server.admit()
