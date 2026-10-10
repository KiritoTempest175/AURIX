"""Append-only audit ledger verifies ordered HMAC records."""
import sqlite3
import pytest
from security.action_audit import ActionAudit


def test_log_is_chained_and_append_only(tmp_path):
    ledger = ActionAudit(tmp_path, b"a" * 32)
    fingerprint = "1" * 64
    ledger.append("read_file", "REQUESTED", fingerprint)
    ledger.append("read_file", "RETURNED", fingerprint)
    assert ledger.verify()
    assert [e["stage"] for e in ledger.recent()] == ["RETURNED", "REQUESTED"]
    with sqlite3.connect(ledger.path) as db:
        with pytest.raises(sqlite3.DatabaseError):
            db.execute("UPDATE events SET stage='FAILED' WHERE seq=1")


def test_rejects_invalid_action_fingerprint(tmp_path):
    ledger = ActionAudit(tmp_path, b"a" * 32)
    with pytest.raises(ValueError):
        ledger.append("read_file", "REQUESTED", "not-a-sha256")


def test_wrong_key_invalidates_signature(tmp_path):
    first = ActionAudit(tmp_path, b"a" * 32)
    first.append("write_file", "APPROVED", "0" * 64)
    assert not ActionAudit(tmp_path, b"b" * 32).verify()
