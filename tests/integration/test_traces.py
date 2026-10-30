"""The trace of a multi-agent session shows every kind of edge."""

import uuid

import httpx
import pytest
import pytest_asyncio

from src.main import app

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(loop_scope="function")
async def client():
    from src.api.auth import ensure_demo_accounts

    await ensure_demo_accounts()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/auth/login", json={"email": "admin@veilgate.demo", "password": "admin-demo-2026"})
        assert r.status_code == 200
        yield c


async def test_trace_graph_covers_user_agent_tool_model_edges(client):
    sid = str(uuid.uuid4())

    async def hook(name, agent, parent=None, **kw):
        r = await client.post(f"/api/v1/{name}", json={"user_id": "tracer", "session_id": sid, "agent_id": agent,
                                                       "parent_agent_id": parent, **kw})
        assert r.status_code == 200

    await hook("on_prompt_received", "orchestrator", prompt="Summarise Dr. Ann Lee, SSN 123-45-6789")
    await hook("on_prompt_received", "data_agent", "orchestrator", prompt="fetch record")
    await hook("on_tool_call", "data_agent", "orchestrator", tool_name="lookup", tool_risk="low", agent_allowed_tools=["lookup"], tool_args={})
    await hook("on_tool_result", "data_agent", "orchestrator", tool_name="lookup", result="ok", latency_ms=5)
    await hook("on_tool_call", "rogue", tool_name="wipe", tool_risk="high", agent_allowed_tools=[], tool_args={})
    await hook("on_completion_received", "data_agent", "orchestrator", completion="done", prompt_tokens=5, completion_tokens=3, latency_ms=40)
    await hook("on_completion_received", "orchestrator", completion="all done", prompt_tokens=9, completion_tokens=4, latency_ms=70)
    await hook("on_session_end", "orchestrator", summary={})

    t = (await client.get(f"/api/traces/{sid}")).json()
    kinds = {e["kind"] for e in t["edges"]}
    assert {"user_to_agent", "agent_to_agent", "agent_to_tool", "tool_to_agent", "agent_to_model", "model_to_agent", "agent_to_user"} <= kinds
    assert t["receipts"]["ok"] is True
    assert t["summary"]["flagged"] == 1  # the rogue tool call
    assert t["summary"]["tokens"] == 21
    denied = [s for s in t["spans"] if s["outcome"] == "denied"][0]
    assert denied["score_changes"][0]["rule"] == "out_of_scope"
    assert "123-45-6789" not in str(t)

    listed = (await client.get("/api/traces")).json()
    assert any(x["id"] == sid for x in listed)
    assert (await client.get("/api/agents")).status_code == 200
    assert (await client.get("/api/overview")).json()["receipts"] > 0
    assert (await client.get(f"/api/traces/{uuid.uuid4()}")).status_code == 404
