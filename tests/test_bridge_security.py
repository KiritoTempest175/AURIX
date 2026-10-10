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
