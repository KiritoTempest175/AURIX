"""LUNA Checkpoint and Data Encryption Module.

Provides AES-256-GCM authenticated encryption at rest for model checkpoints,
interaction datasets, and sensitive configuration files.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import platform
import secrets
from pathlib import Path
from typing import Any, Dict, Optional, Union

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger("luna.security.encryption")


class CheckpointEncryptor:
    """Handles AES-256-GCM authenticated encryption and decryption for LUNA artifacts."""

    def __init__(self, key: Optional[bytes] = None, key_path: Optional[Union[str, Path]] = None) -> None:
        """Initialize the encryptor with a 256-bit key or derive one locally.

        Args:
            key: Optional 32-byte AES key. If None, derived from key_path or machine identity.
            key_path: Path to local keyfile. Defaults to data/.luna_master.key.
        """
        if key is not None:
            if len(key) != 32:
                raise ValueError(f"AES-256 key must be exactly 32 bytes, got {len(key)}")
            self._key = key
        else:
            self._key = self._load_or_create_key(key_path)

        self._aesgcm = AESGCM(self._key)

    @classmethod
    def _load_or_create_key(cls, key_path: Optional[Union[str, Path]] = None) -> bytes:
        """Load an existing master key or securely generate and persist a new 256-bit key.

        Args:
            key_path: Optional path for storing the key.

        Returns:
            32-byte key.
        """
        if key_path is None:
            base_dir = Path.home() / ".luna"
            base_dir.mkdir(parents=True, exist_ok=True)
            path = base_dir / "master.key"
        else:
            path = Path(key_path)
            path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            try:
                raw = path.read_bytes()
                if len(raw) == 32:
                    return raw
            except Exception as e:
                logger.warning(f"Failed to read existing key at {path}: {e}")

        # Derive a strong 32-byte machine-anchored key
        entropy = secrets.token_bytes(32)
        machine_id = f"{platform.node()}-{platform.machine()}-{platform.processor()}".encode("utf-8")
        derived_key = hashlib.pbkdf2_hmac("sha256", entropy, machine_id, 100_000, dklen=32)

        try:
            path.write_bytes(derived_key)
            if platform.system() != "Windows":
                os.chmod(path, 0o600)
            logger.info(f"Generated new LUNA AES-256 master key at {path}")
        except Exception as e:
            logger.error(f"Could not persist key to {path}: {e}")

        return derived_key

    def encrypt_bytes(self, data: bytes, associated_data: Optional[bytes] = None) -> bytes:
        """Encrypt raw bytes using AES-256-GCM.

        Format: [12-byte Nonce] + [Ciphertext + 16-byte Tag]

        Args:
            data: Plaintext bytes to encrypt.
            associated_data: Optional authenticated associated data (AAD).

        Returns:
            Encrypted payload bytes.
        """
        nonce = secrets.token_bytes(12)
        ciphertext = self._aesgcm.encrypt(nonce, data, associated_data)
        return nonce + ciphertext

    def decrypt_bytes(self, payload: bytes, associated_data: Optional[bytes] = None) -> bytes:
        """Decrypt AES-256-GCM payload.

        Args:
            payload: [12-byte Nonce] + [Ciphertext + 16-byte Tag].
            associated_data: Optional authenticated associated data (AAD).

        Returns:
            Decrypted plaintext bytes.

        Raises:
            ValueError: If payload is too short or authentication tag fails.
        """
        if len(payload) < 28:
            raise ValueError(f"Payload too short ({len(payload)} bytes) for AES-GCM")
        nonce = payload[:12]
        ciphertext = payload[12:]
        return self._aesgcm.decrypt(nonce, ciphertext, associated_data)

    def encrypt_file(self, src_path: Union[str, Path], dst_path: Optional[Union[str, Path]] = None) -> Path:
        """Encrypt a file and write to dst_path or overwrite src_path.

        Args:
            src_path: Path to plaintext source file.
            dst_path: Path to encrypted destination file.

        Returns:
            Path to encrypted file.
        """
        src = Path(src_path)
        dst = Path(dst_path) if dst_path else src.with_suffix(src.suffix + ".enc")
        plaintext = src.read_bytes()
        aad = src.name.encode("utf-8")
        encrypted = self.encrypt_bytes(plaintext, associated_data=aad)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(encrypted)
        return dst

    def decrypt_file(self, enc_path: Union[str, Path], dst_path: Optional[Union[str, Path]] = None) -> Path:
        """Decrypt an encrypted file.

        Args:
            enc_path: Path to encrypted file.
            dst_path: Path to decrypted destination file.

        Returns:
            Path to decrypted file.
        """
        src = Path(enc_path)
        dst = Path(dst_path) if dst_path else (src.with_suffix("") if src.suffix == ".enc" else src.with_suffix(".dec"))
        payload = src.read_bytes()
        aad = dst.name.encode("utf-8")
        plaintext = self.decrypt_bytes(payload, associated_data=aad)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(plaintext)
        return dst

    def encrypt_json(self, data: Dict[str, Any]) -> str:
        """Serialize and encrypt a dictionary into a base64 string."""
        raw_json = json.dumps(data, indent=2).encode("utf-8")
        encrypted = self.encrypt_bytes(raw_json)
        return base64.b64encode(encrypted).decode("ascii")

    def decrypt_json(self, b64_payload: str) -> Dict[str, Any]:
        """Decrypt and deserialize a base64 encrypted JSON string."""
        raw_encrypted = base64.b64decode(b64_payload.encode("ascii"))
        decrypted = self.decrypt_bytes(raw_encrypted)
        return json.loads(decrypted.decode("utf-8"))


_GLOBAL_ENCRYPTOR: Optional[CheckpointEncryptor] = None


def get_default_encryptor() -> CheckpointEncryptor:
    """Return singleton CheckpointEncryptor instance."""
    global _GLOBAL_ENCRYPTOR
    if _GLOBAL_ENCRYPTOR is None:
        _GLOBAL_ENCRYPTOR = CheckpointEncryptor()
    return _GLOBAL_ENCRYPTOR
