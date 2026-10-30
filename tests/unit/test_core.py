import pytest

from src.core.config import Settings


def test_settings_loads(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "postgresql://owner:pass@localhost/test")
    monkeypatch.setenv("UPSTREAM_BASE_URL", "https://api.studio.nebius.ai/v1")
    monkeypatch.setenv("NEBIUS_API_KEY", "test-key")
    settings = Settings()
    assert settings.governance_port == 8080
    assert settings.enable_ner is True
    assert settings.app_env == "local"


def test_settings_fails_without_required_fields(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("UPSTREAM_BASE_URL", raising=False)
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    with pytest.raises(Exception):
        Settings(_env_file=None)
