"""Opt-in AES-GCM local memory, encrypted with a Windows DPAPI-wrapped key.

Only ciphertext is written to SQLite. Private memory is NEVER part of the repo.
Non-Windows use is limited to tests that explicitly provide a 32-byte key.
"""
from __future__ import annotations

import os
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KINDS = frozenset(("episodic", "semantic", "procedural", "knowledge"))
_LOCK = threading.RLock()
_STORE = None


def memory_enabled() -> bool:
    """Explicit opt-in from the single active configuration."""
    try:
        import sys
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            import tomli as tomllib
        root = Path(__file__).resolve().parent.parent
        with (root / "config.toml").open("rb") as stream:
            return tomllib.load(stream).get("memory", {}).get("enabled") is True
    except (OSError, ValueError, ImportError):
        return False


def _user_root() -> Path:
    if os.name != "nt" or not os.environ.get("LOCALAPPDATA"):
        raise RuntimeError("Persistent memory requires Windows LocalAppData")
    return Path(os.environ["LOCALAPPDATA"]) / "AURIX" / "private"


def _master_key(root: Path) -> bytes:
    if os.name != "nt":
        raise RuntimeError("DPAPI is required for persistent memory keys")
    try:
        import win32crypt
    except ImportError as exc:
        raise RuntimeError("pywin32 is required for Windows DPAPI") from exc
    path = root / "memory.key.dpapi"
    if path.exists():
        try:
            key = win32crypt.CryptUnprotectData(path.read_bytes(), None, None, None, 0)[1]
            if len(key) != 32:
                raise ValueError("Corrupt memory master key")
            return key
        except Exception as exc:
            raise RuntimeError("DPAPI cannot unwrap memory key") from exc
    key = secrets.token_bytes(32)
    protected = win32crypt.CryptProtectData(key, "AURIX memory key", None, None, None, 0)
    path.write_bytes(protected)
    return key


class MemoryStore:
    """Thread-safe encrypted data store with simple keyword/recency retrieval.

    This is *not* an embedding vector store and does not pretend to be one.
    """

    def __init__(self, root: Optional[Path] = None, key: Optional[bytes] = None):
        self.root = Path(root) if root is not None else _user_root()
        self.root.mkdir(parents=True, exist_ok=True)
        if key is None:
            key = _master_key(self.root)
        if len(key) != 32:
            raise ValueError("AES-256 key must be exactly 32 bytes")
        self.cipher = AESGCM(key)
        self.db = self.root / "memories.db"
        self.lock = threading.RLock()
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS memories(
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    created REAL NOT NULL,
                    importance REAL NOT NULL,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    payload BLOB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_memory_recent ON memories(created DESC);
            """)

    def _connect(self):
        conn = sqlite3.connect(self.db, timeout=5)
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA secure_delete=ON")
        return conn

    def _encrypt(self, item_id: str, content: str) -> bytes:
        nonce = secrets.token_bytes(12)
        data = content.encode("utf-8")
        return nonce + self.cipher.encrypt(nonce, data, item_id.encode("ascii"))

    def _decrypt(self, item_id: str, payload: bytes) -> str:
        return self.cipher.decrypt(payload[:12], payload[12:], item_id.encode("ascii")).decode("utf-8")

    def add(self, kind: str, content: str, importance: float = 0.5, pinned: bool = False) -> str:
        if kind not in KINDS:
            raise ValueError("Unsupported memory type")
        if not content or len(content) > 12000:
            raise ValueError("Memory content must contain 1–12000 characters")
        if not (0.0 <= importance <= 1.0):
            raise ValueError("Importance must be 0–1")
        item_id = secrets.token_hex(16)
        with self.lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO memories(id,kind,created,importance,pinned,payload) VALUES(?,?,?,?,?,?)",
                (item_id, kind, time.time(), float(importance), int(bool(pinned)),
                 self._encrypt(item_id, content)),
            )
        return item_id

    def list(self, limit: int = 100) -> list[dict]:
        count = max(1, min(200, int(limit)))
        with self.lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id,kind,created,importance,pinned,payload FROM memories "
                "ORDER BY pinned DESC, created DESC LIMIT ?", (count,)
            ).fetchall()
        return [self._record(x) for x in rows]

    def _record(self, row) -> dict:
        mid, kind, created, importance, pinned, payload = row
        return {"id": mid, "kind": kind, "created": created,
                "importance": importance, "pinned": bool(pinned),
                "content": self._decrypt(mid, payload)}

    def search(self, query: str, limit: int = 5) -> list[dict]:
        tokens = set(re.findall(r"[a-z0-9]{3,}", query.casefold()))
        if not tokens:
            return []
        with self.lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id,kind,created,importance,pinned,payload FROM memories "
                "ORDER BY created DESC LIMIT 300"
            ).fetchall()
        now = time.time()
        scored = []
        for row in rows:
            record = self._record(row)
            words = set(re.findall(r"[a-z0-9]{3,}", record["content"].casefold()))
            overlap = len(tokens & words)
            if not overlap:
                continue
            age_days = max(0.0, (now - record["created"]) / 86400)
            score = overlap * 2 + record["importance"] + (
                1.0 if record["pinned"] else 0.0
            ) + (1.0 / (1.0 + age_days / 30.0))
            scored.append((score, record))
        scored.sort(key=lambda it: it[0], reverse=True)
        return [item for _, item in scored[:max(1, min(20, limit))]]

    def delete(self, item_id: str) -> bool:
        with self.lock, self._connect() as conn:
            cursor = conn.execute("DELETE FROM memories WHERE id=?", (item_id,))
            return cursor.rowcount > 0

    def clear(self):
        with self.lock, self._connect() as conn:
            conn.execute("DELETE FROM memories")
        with self.lock, self._connect() as conn:
            conn.execute("VACUUM")


def get_memory_store() -> MemoryStore:
    global _STORE
    if not memory_enabled():
        raise PermissionError("Memory collection is disabled")
    with _LOCK:
        if _STORE is None:
            _STORE = MemoryStore()
        return _STORE
