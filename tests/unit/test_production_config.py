import pytest

from src.api import auth as auth_api
from src.core import auth
from src.core.config import get_settings


def test_auth_secret_uses_stable_hex_secret(monkeypatch):
    key = "a1" * 32
    monkeypatch.setattr(get_settings(), "auth_key_hex", key)
    assert auth._secret() == bytes.fromhex(key)


def test_auth_secret_rejects_invalid_hex_secret(monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_key_hex", "invalid")
    with pytest.raises(ValueError, match="AUTH_KEY_HEX"):
        auth._secret()


@pytest.mark.asyncio
async def test_production_demo_hint_is_disabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "app_env", "production")
    assert await auth_api.demo_hint() == []


@pytest.mark.asyncio
async def test_production_does_not_create_demo_accounts(monkeypatch):
    monkeypatch.setattr(get_settings(), "app_env", "production")
    monkeypatch.setattr(get_settings(), "bootstrap_admin_email", "")
    monkeypatch.setattr(get_settings(), "bootstrap_admin_password", "")

    def database_must_not_be_opened():
        raise AssertionError("production without a bootstrap admin must not access the database")

    monkeypatch.setattr(auth_api, "_get_session_factory", database_must_not_be_opened)
    await auth_api.ensure_demo_accounts()
