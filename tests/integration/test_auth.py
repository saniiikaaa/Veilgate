"""Sign-in, per-user scoping and the optional hook key."""

import uuid

import httpx
import pytest
import pytest_asyncio

from src.api.auth import ensure_demo_accounts
from src.core.config import get_settings
from src.main import app

pytestmark = pytest.mark.asyncio

ADMIN = {"email": "admin@veilgate.demo", "password": "admin-demo-2026"}
IYER = {"email": "iyer@veilgate.demo", "password": "iyer-demo-2026"}


@pytest_asyncio.fixture(loop_scope="function")
async def anon():
    await ensure_demo_accounts()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def signed_in(creds):
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    r = await c.post("/api/auth/login", json=creds)
    assert r.status_code == 200, r.text
    return c


async def make_session(c, user_id):
    sid = str(uuid.uuid4())
    r = await c.post("/api/v1/on_prompt_received", json={"user_id": user_id, "session_id": sid, "agent_id": "orchestrator", "prompt": "hello there"})
    assert r.status_code == 200
    return sid


async def test_dashboard_api_requires_sign_in(anon):
    for path in ("/api/traces", "/api/agents", "/api/overview", "/api/policies", "/api/auth/me"):
        assert (await anon.get(path)).status_code == 401, path


async def test_wrong_password_and_tampered_cookie_rejected(anon):
    assert (await anon.post("/api/auth/login", json={**ADMIN, "password": "nope"})).status_code == 401
    anon.cookies.set("vg_session", "abc.def")
    assert (await anon.get("/api/auth/me")).status_code == 401


async def test_user_sees_only_own_sessions_and_not_policies(anon):
    mine = await make_session(anon, "dr.iyer")
    theirs = await make_session(anon, "someone.else")
    iyer, admin = await signed_in(IYER), await signed_in(ADMIN)
    try:
        ids = {t["id"] for t in (await iyer.get("/api/traces")).json()}
        assert mine in ids and theirs not in ids
        assert (await iyer.get(f"/api/traces/{theirs}")).status_code == 404
        assert (await iyer.get(f"/api/traces/{theirs}/receipts")).status_code == 404
        assert (await iyer.get(f"/api/traces/{mine}")).status_code == 200
        assert (await iyer.get("/api/policies")).status_code == 403

        all_ids = {t["id"] for t in (await admin.get("/api/traces")).json()}
        assert {mine, theirs} <= all_ids
        pol = (await admin.get("/api/policies")).json()
        assert pol["thresholds"]["block_below"] == 20 and pol["tools"] and pol["entity_types"]
        assert "api_key" not in str(pol).lower()
    finally:
        await iyer.aclose()
        await admin.aclose()


async def test_hook_key_is_enforced_when_configured(anon, monkeypatch):
    body = {"user_id": "k", "session_id": str(uuid.uuid4()), "agent_id": "a", "prompt": "hi there"}
    monkeypatch.setattr(get_settings(), "hook_api_key", "s3cret")
    assert (await anon.post("/api/v1/on_prompt_received", json=body)).status_code == 401
    ok = await anon.post("/api/v1/on_prompt_received", json=body, headers={"X-Veilgate-Key": "s3cret"})
    assert ok.status_code == 200


async def test_public_detect_is_open_but_limited(anon):
    r = await anon.post("/api/auth/public-detect", json={"text": "Call Rahul Verma on 98765 43210"})
    assert r.status_code == 200 and "98765" not in r.json()["masked"] and r.json()["entities"]
    big = await anon.post("/api/auth/public-detect", json={"text": "x" * 5000})
    assert big.status_code == 200  # truncated, not rejected
