#!/usr/bin/env python3
"""Import an explicitly chosen GGUF model after verifying its SHA-256 digest."""
from __future__ import annotations
import argparse
import hashlib
import os
import secrets
from pathlib import Path
from security.config_loader import user_data_root

def verify_and_import(source: Path, expected_sha256: str) -> Path:
    if source.suffix.lower() != ".gguf" or not source.is_file():
        raise ValueError("Expected an existing local .gguf model")
    expected = expected_sha256.lower()
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise ValueError("A verified full-length SHA-256 digest is required")
    destination = user_data_root() / "models" / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name("." + secrets.token_hex(16) + ".part")
    actual = hashlib.sha256()
    try:
        # Verify the bytes that will be installed, not a source that can change
        # between a separate hash pass and a later copy.
        with source.open("rb") as incoming, tmp.open("xb") as outgoing:
            for block in iter(lambda: incoming.read(1024 * 1024), b""):
                actual.update(block)
                outgoing.write(block)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        if actual.hexdigest() != expected:
            raise ValueError("Model SHA-256 verification failed")
        os.replace(tmp, destination)
    finally:
        tmp.unlink(missing_ok=True)
    return destination

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model_file", type=Path)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()
    print(verify_and_import(args.model_file, args.sha256))

if __name__ == "__main__":
    main()
