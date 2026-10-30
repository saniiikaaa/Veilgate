"""AES-256-GCM encryption and keyed hashing for vault values. The key never touches the database."""

import hashlib
import hmac
import os
from pathlib import Path
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def load_key(path: str, configured_key_hex: str = "") -> bytes:
    """Read a configured 32-byte key or create/read the local development key."""
    if configured_key_hex:
        try:
            key = bytes.fromhex(configured_key_hex)
        except ValueError as exc:
            raise ValueError("VAULT_KEY_HEX must be a 64-character hexadecimal value") from exc
        if len(key) != 32:
            raise ValueError("VAULT_KEY_HEX must encode exactly 32 bytes")
        return key

    p = Path(path)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(os.urandom(32))
        p.chmod(0o600)
    key = p.read_bytes()
    if len(key) != 32:
        raise ValueError(f"vault key at {path} must be 32 bytes")
    return key


class VaultCrypto:
    def __init__(self, key: bytes) -> None:
        self._aes = AESGCM(key)
        self._hmac_key = hashlib.sha256(b"hmac:" + key).digest()

    def encrypt(self, value: str) -> tuple[bytes, bytes]:
        nonce = os.urandom(12)
        return self._aes.encrypt(nonce, value.encode(), None), nonce

    def decrypt(self, ciphertext: bytes, nonce: bytes) -> str:
        return self._aes.decrypt(nonce, ciphertext, None).decode()

    def value_hmac(self, tenant_id: UUID, entity_type: str, value: str) -> bytes:
        msg = f"{tenant_id}|{entity_type}|{value.strip().lower()}".encode()
        return hmac.new(self._hmac_key, msg, hashlib.sha256).digest()

    def token(self, entity_type: str, digest: bytes) -> str:
        return f"tok_{entity_type.lower()}_{digest.hex()[:12]}"
