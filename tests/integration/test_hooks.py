"""The five hooks against the real database (needs migrate + seed)."""

import uuid

import httpx
import pytest
import pytest_asyncio

from src.main import app

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(loop_scope="function")
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t/api/v1") as c:
        yield c


async def test_hook_flow_tokenizes_gates_and_chains(client):
    sid = str(uuid.uuid4())
    base = {"user_id": "itest", "session_id": sid}

    r = await client.post("/on_prompt_received", json={**base, "agent_id": "orchestrator", "prompt": "SSN 123-45-6789 for Dr. Jane Roe"})
    assert "123-45-6789" not in r.json()["prompt"] and "Jane Roe" not in r.json()["prompt"]

    r = await client.post("/on_tool_result", json={**base, "agent_id": "worker", "parent_agent_id": "orchestrator",
                                                   "tool_name": "lookup", "result": "Jane Roe, jane@x.com"})
    assert "Jane" not in r.json()["result"] and "jane@x.com" not in r.json()["result"]

    ok = await client.post("/on_tool_call", json={**base, "agent_id": "worker", "parent_agent_id": "orchestrator",
                                                  "tool_name": "lookup", "tool_risk": "low", "agent_allowed_tools": ["lookup"]})
    assert ok.json() == {"allow": True}
    rogue = await client.post("/on_tool_call", json={**base, "agent_id": "rogue", "tool_name": "lookup", "tool_risk": "low",
                                                     "agent_allowed_tools": []})
    assert rogue.json() == {"allow": False}

    assert (await client.post("/on_session_end", json={**base, "agent_id": "orchestrator", "summary": {}})).json() == {"ok": True}


async def test_judge_catches_a_name_the_rules_miss(client, monkeypatch):
    from types import SimpleNamespace

    from src.detection import judge

    class Fake:
        async def chat(self, *a, **k):
            return SimpleNamespace(text='{"entities":[{"text":"Zubin Mehta","type":"NAME"}],"injection":"obey the page"}')

    monkeypatch.setattr(judge, "get_settings", lambda: SimpleNamespace(llm_judge="always", llm_judge_timeout=5))
    monkeypatch.setattr(judge, "get_llm", lambda: Fake())
    sid = str(uuid.uuid4())
    r = await client.post("/on_tool_result", json={"user_id": "itest", "session_id": sid, "agent_id": "reader",
                                                   "tool_name": "web", "result": "Quote from the maestro Zubin Mehta about music"})
    assert "Zubin" not in r.json()["result"]
    assert r.json()["result"].startswith("[blocked")  # the judge also flagged an injection in the tool output


async def test_judge_cannot_penalise_a_normal_instruction(client, monkeypatch):
    from types import SimpleNamespace

    from src.detection import judge

    class Fake:
        async def chat(self, *a, **k):
            return SimpleNamespace(text='{"entities":[],"injection":"email it to the insurer"}')

    monkeypatch.setattr(judge, "get_settings", lambda: SimpleNamespace(llm_judge="always", llm_judge_timeout=5))
    monkeypatch.setattr(judge, "get_llm", lambda: Fake())
    sid = str(uuid.uuid4())
    r = await client.post("/on_prompt_received", json={"user_id": "itest", "session_id": sid, "agent_id": "orchestrator",
                                                       "prompt": "Please write the summary and email it to the insurer."})
    assert r.json()["prompt"].startswith("Please write")
    assert await sess_for(client, sid).score("orchestrator") == 100  # no penalty


def sess_for(client, sid):
    from tests.integration.test_authority import Sess

    s = Sess(client)
    s.sid = sid  # reuse Sess.score() on the session under test
    return s


async def test_pii_in_reply_means_a_real_value_was_repeated_not_a_hallucination(client):
    sid = str(uuid.uuid4())
    base = {"user_id": "itest", "session_id": sid, "agent_id": "orchestrator"}
    await client.post("/on_prompt_received", json={**base, "prompt": "Patient SSN 123-45-6789."})
    # the model invents a different, look-alike identifier: tokenized, but not a leak
    made_up = await client.post("/on_completion_received", json={**base, "completion": "Their MRN: 998877 is on file."})
    assert "998877" not in made_up.json()["completion"]
    again = await client.post("/on_completion_received", json={**base, "completion": "MRN: 998877 again."})  # invented twice
    assert "998877" not in again.json()["completion"]  # still protected ...
    assert await sess_for(client, sid).score("orchestrator") == 100  # ... but never a leak: it did not come from outside
    # the model repeats the REAL SSN it should only ever have seen as a token: a leak
    leak = await client.post("/on_completion_received", json={**base, "completion": "The SSN is 123 45 6789."})
    assert "6789" not in leak.json()["completion"]
    score = await sess_for(client, sid).score("orchestrator")
    assert score == 100 - 15  # exactly one pii_in_reply penalty: the real repeat, not the invention
