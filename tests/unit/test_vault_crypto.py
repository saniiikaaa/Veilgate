import os
from uuid import uuid4

import pytest

from src.vault.crypto import VaultCrypto, load_key


def test_roundtrip_and_stable_token():
    c = VaultCrypto(os.urandom(32))
    ct, nonce = c.encrypt("123-45-6789")
    assert b"123" not in ct
    assert c.decrypt(ct, nonce) == "123-45-6789"
    t = uuid4()
    assert c.token("SSN", c.value_hmac(t, "SSN", "123-45-6789")) == c.token("SSN", c.value_hmac(t, "SSN", " 123-45-6789 "))


def test_other_tenant_gets_other_token():
    c = VaultCrypto(os.urandom(32))
    assert c.value_hmac(uuid4(), "SSN", "x") != c.value_hmac(uuid4(), "SSN", "x")


def test_load_key_creates_and_validates(tmp_path):
    p = tmp_path / "k.key"
    assert load_key(str(p)) == load_key(str(p))
    p.write_bytes(b"short")
    with pytest.raises(ValueError):
        load_key(str(p))


def test_load_key_accepts_stable_hex_secret(tmp_path):
    key = os.urandom(32)
    assert load_key(str(tmp_path / "unused.key"), key.hex()) == key
    with pytest.raises(ValueError, match="VAULT_KEY_HEX"):
        load_key(str(tmp_path / "unused.key"), "invalid")
