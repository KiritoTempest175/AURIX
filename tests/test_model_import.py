"""Model imports fail closed when SHA-256 does not match."""
import hashlib
import pytest
from scripts.import_model import verify_and_import

def test_rejects_invalid_digest(tmp_path):
    source = tmp_path / "tiny.gguf"
    source.write_bytes(b"demo")
    with pytest.raises(ValueError, match="verification failed"):
        verify_and_import(source, "0" * 64)

def test_imports_verified_local_model(tmp_path, monkeypatch):
    monkeypatch.setenv("AURIX_DATA_DIR", str(tmp_path / "data"))
    source = tmp_path / "sample.gguf"
    source.write_bytes(b"model test fixture")
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    assert verify_and_import(source, expected).read_bytes() == source.read_bytes()
