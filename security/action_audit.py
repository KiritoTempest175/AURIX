"""Append-only action event ledger with a local HMAC hash chain.

Only action names and fingerprints are stored, never message bodies, paths,
credentials or command output. DPAPI protects the per-user HMAC key on Windows.
This is tamper-evident against casual SQLite changes, not a remote attestation.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

EVENTS = frozenset({"REQUESTED", "PENDING", "APPROVED", "REJECTED", "RETURNED", "FAILED", "BLOCKED"})
_DEFAULT = None
_LOCK = threading.Lock()


class ActionAudit:
    def __init__(self, root: Path, key: bytes):
        if len(key) < 32:
            raise ValueError("Audit key is too short")
        self.path = Path(root) / "action_audit.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.key = hashlib.sha256(key + b":aurix-audit-key-v1").digest()
        self.lock = threading.RLock()
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    tool TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    previous TEXT NOT NULL,
                    digest TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS protect_event_update BEFORE UPDATE ON events
                    BEGIN SELECT RAISE(ABORT, 'Audit log is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS protect_event_delete BEFORE DELETE ON events
                    BEGIN SELECT RAISE(ABORT, 'Audit log is append-only'); END;
            """)

    def _db(self):
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _digest(self, seq: int, ts: float, tool: str, stage: str,
                fingerprint: str, previous: str) -> str:
        message = f"{seq}|{ts:.6f}|{tool}|{stage}|{fingerprint}|{previous}".encode()
        return hmac.new(self.key, message, hashlib.sha256).hexdigest()

    def append(self, tool: str, stage: str, fingerprint: str) -> None:
        if stage not in EVENTS:
            raise ValueError("Unknown audit event type")
        if not tool or len(tool) > 128 or not all(c.isalnum() or c in "_-" for c in tool):
            raise ValueError("Invalid audit tool name")
        if len(fingerprint) != 64 or any(c not in "0123456789abcdef" for c in fingerprint):
            raise ValueError("Invalid action fingerprint")
        with self.lock, self._db() as db:
            previous_row = db.execute("SELECT seq,digest FROM events ORDER BY seq DESC LIMIT 1").fetchone()
            seq = previous_row[0] + 1 if previous_row else 1
            previous = previous_row[1] if previous_row else "0" * 64
            ts = round(time.time(), 6)
            digest = self._digest(seq, ts, tool, stage, fingerprint, previous)
            db.execute(
                "INSERT INTO events(seq,timestamp,tool,stage,fingerprint,previous,digest)"
                " VALUES(?,?,?,?,?,?,?)",
                (seq, ts, tool, stage, fingerprint, previous, digest),
            )

    def recent(self, limit: int = 50) -> list[dict]:
        with self.lock, self._db() as db:
            rows = db.execute(
                "SELECT seq,timestamp,tool,stage FROM events ORDER BY seq DESC LIMIT ?",
                (max(1, min(200, limit)),),
            ).fetchall()
        return [{"seq": seq, "timestamp": ts, "tool": tool, "stage": stage}
                for seq, ts, tool, stage in rows]

    def verify(self) -> bool:
        with self.lock, self._db() as db:
            rows = db.execute(
                "SELECT seq,timestamp,tool,stage,fingerprint,previous,digest "
                "FROM events ORDER BY seq"
            ).fetchall()
        last = "0" * 64
        for expected_seq, row in enumerate(rows, 1):
            seq, ts, tool, stage, fingerprint, previous, digest = row
            if seq != expected_seq or previous != last:
                return False
            calculated = self._digest(seq, ts, tool, stage, fingerprint, previous)
            if not hmac.compare_digest(calculated, digest):
                return False
            last = digest
        return True


def default_audit() -> Optional[ActionAudit]:
    """Native protection only: non-Windows development environments do not log."""
    global _DEFAULT
    if os.name != "nt":
        return None
    with _LOCK:
        if _DEFAULT is None:
            from ai_brain.secure_memory import _master_key
            from security.config_loader import user_data_root
            root = user_data_root() / "private"
            root.mkdir(parents=True, exist_ok=True)
            _DEFAULT = ActionAudit(root, _master_key(root))
        return _DEFAULT
