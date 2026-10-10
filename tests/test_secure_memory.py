"""Encrypted opt-in memory tests with an explicit ephemeral test key."""
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from ai_brain.secure_memory import MemoryStore, get_memory_store


def test_memory_ciphertext_is_not_plaintext(tmp_path):
    store = MemoryStore(root=tmp_path, key=b"x" * 32)
    memory_id = store.add("semantic", "Private contact: test@example.com")
    blob = sqlite3.connect(store.db).execute(
        "SELECT payload FROM memories WHERE id=?", (memory_id,)
    ).fetchone()[0]
    assert b"test@example.com" not in blob
    assert "Private contact" in store.list()[0]["content"]


def test_memory_search_and_delete(tmp_path):
    store = MemoryStore(root=tmp_path, key=b"k" * 32)
    matching_id = store.add("procedural", "Use Python for automation projects")
    store.add("semantic", "Enjoys astronomy")
    found = store.search("Python automation")
    assert [x["id"] for x in found] == [matching_id]
    assert store.delete(matching_id) is True
    assert store.search("Python automation") == []


def test_wrong_key_fails_authentication(tmp_path):
    MemoryStore(tmp_path, key=b"a" * 32).add("episodic", "Secret discussion")
    different = MemoryStore(tmp_path, key=b"b" * 32)
    with pytest.raises(Exception):
        different.list()


def test_disabled_memory_denies_implicit_access():
    with patch("ai_brain.secure_memory.memory_enabled", return_value=False):
        with pytest.raises(PermissionError):
            get_memory_store()
