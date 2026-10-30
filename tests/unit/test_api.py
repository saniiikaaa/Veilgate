"""Unit tests for the FastAPI skeleton (Task 4).

Uses the sync TestClient — no running event loop needed.
DB dependency is overridden with lightweight mocks so no real DB is required.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.core.errors import PolicyDenyError, WardenError
from src.main import app
from src.api.deps import get_db_session


# ---------------------------------------------------------------------------
# Helper: a mock session that successfully executes SELECT 1
# ---------------------------------------------------------------------------
def _ok_session_override():
    """Dependency override that returns a mock DB session (healthy)."""
    async def _gen():
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar=lambda: 1))
        yield session
    return _gen


def _fail_session_override():
    """Dependency override that yields a session whose execute() raises."""
    async def _gen():
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=RuntimeError("DB connection failed"))
        yield session
    return _gen


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def client():
    """Clean TestClient with no dependency overrides."""
    app.dependency_overrides = {}
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides = {}


@pytest.fixture()
def client_db_ok():
    """TestClient with a healthy mock DB session."""
    app.dependency_overrides[get_db_session] = _ok_session_override()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides = {}


@pytest.fixture()
def client_db_fail():
    """TestClient with a failing mock DB session."""
    app.dependency_overrides[get_db_session] = _fail_session_override()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides = {}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_healthz_returns_200(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_healthz_has_env_field(client):
    resp = client.get("/healthz")
    assert "env" in resp.json()


def test_readyz_returns_200_when_db_ok(client_db_ok):
    resp = client_db_ok.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["db"] == "ok"


def test_readyz_returns_503_when_db_fails(client_db_fail):
    resp = client_db_fail.get("/readyz")
    assert resp.status_code == 503


def test_admin_status_returns_200(client):
    resp = client.get("/admin/status")
    assert resp.status_code == 200
    assert resp.json()["service"] == "warden"


def test_policy_deny_error_returns_403(client):
    """Add a temp route that raises PolicyDenyError, then call it."""
    @app.get("/test/policy-deny")
    async def _raise_policy_deny():
        raise PolicyDenyError(reason="blocked", agent_id="agent-1", pack="pack-1")

    resp = client.get("/test/policy-deny")
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"] == "policy_deny"
    assert body["reason"] == "blocked"


def test_warden_error_returns_500(client):
    """Add a temp route that raises a generic WardenError."""
    @app.get("/test/warden-error")
    async def _raise_warden():
        raise WardenError("something went wrong")

    resp = client.get("/test/warden-error")
    assert resp.status_code == 500
    assert resp.json()["error"] == "warden_error"


def test_docs_available(client):
    resp = client.get("/docs")
    assert resp.status_code == 200


def test_cors_header_present(client):
    resp = client.get("/healthz", headers={"Origin": "http://example.com"})
    assert "access-control-allow-origin" in resp.headers
