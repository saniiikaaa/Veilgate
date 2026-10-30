from types import SimpleNamespace

import pytest

from src.core.config import Settings
from src.gateway.llm import LLM


def settings(**kw):
    base = dict(database_url="postgresql://x", migration_database_url="postgresql://x")
    return Settings(_env_file=None, **{**base, **kw})


def test_nebius_uses_nemotron_tiers():
    llm = LLM(settings(llm_provider="nebius", nebius_api_key="k"))
    assert llm.provider == "nebius"
    assert "nemotron" in llm.model_for("ultra").lower()
    assert llm.model_for("nano") != llm.model_for("ultra")


def test_nebius_without_key_fails_loudly():
    with pytest.raises(RuntimeError, match="NEBIUS_API_KEY"):
        LLM(settings(llm_provider="nebius", nebius_api_key=""))


def test_local_maps_every_tier_to_one_model():
    llm = LLM(settings(llm_provider="local", local_llm_model="my-model"))
    assert {llm.model_for(t) for t in ("nano", "super", "ultra")} == {"my-model"}


def test_unknown_provider_rejected():
    with pytest.raises(ValueError):
        LLM(settings(llm_provider="other"))


async def test_reasoning_model_that_runs_out_of_tokens_is_retried(monkeypatch):
    llm = LLM(settings(llm_provider="local", local_llm_model="m"))
    calls = []

    class Resp:
        def __init__(self, content, finish):
            self.choices = [SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish)]
            self.usage = SimpleNamespace(prompt_tokens=5, completion_tokens=7)

    async def create(**kw):
        calls.append(kw["max_tokens"])
        return Resp(None, "length") if len(calls) == 1 else Resp("<think>hmm</think> the answer", "stop")

    monkeypatch.setattr(llm._client.chat.completions, "create", create)
    r = await llm.chat([{"role": "user", "content": "x"}], max_tokens=100)
    assert r.text == "the answer" and calls == [100, 400] and r.completion_tokens == 14
