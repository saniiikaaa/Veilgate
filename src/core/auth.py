"""Dashboard login: scrypt password hashes and stateless signed session tokens (stdlib only)."""

import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Any

from src.core.config import get_settings

COOKIE = "vg_session"


def _secret() -> bytes:
    configured_key_hex = get_settings().auth_key_hex
    if configured_key_hex:
        try:
            key = bytes.fromhex(configured_key_hex)
        except ValueError as exc:
            raise ValueError("AUTH_KEY_HEX must be a 64-character hexadecimal value") from exc
        if len(key) != 32:
            raise ValueError("AUTH_KEY_HEX must encode exactly 32 bytes")
        return key

    p = Path(get_settings().auth_key_file)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(os.urandom(32))
        p.chmod(0o600)
    return p.read_bytes()


def validate_secret() -> None:
    _secret()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, digest = stored.split("$")
        dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
        return scheme == "scrypt" and hmac.compare_digest(dk.hex(), digest)
    except (ValueError, TypeError):
        return False


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def make_token(claims: dict[str, Any], ttl_seconds: int) -> str:
    body = _b64(json.dumps({**claims, "exp": int(time.time()) + ttl_seconds}, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_token(token: str) -> dict[str, Any] | None:
    try:
        body, sig = token.split(".")
        good = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return None
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        return claims if claims.get("exp", 0) > time.time() else None
    except (ValueError, TypeError):
        return None
