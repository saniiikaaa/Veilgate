"""LLM client. ``LLM_PROVIDER`` in .env picks the backend; both speak the OpenAI chat API.

nebius: Nebius Token Factory with NVIDIA Nemotron (tier = nano | super | ultra picks the model).
local:  the company-hosted model; every tier maps to the one model there.
"""

import re
import time
from dataclasses import dataclass

from openai import AsyncOpenAI

from src.core.config import Settings, get_settings


@dataclass(frozen=True)
class LLMResult:
    text: str
    model: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float


class LLM:
    def __init__(self, settings: Settings) -> None:
        self.provider = settings.llm_provider.lower()
        if self.provider == "nebius":
            if not settings.nebius_api_key:
                raise RuntimeError("LLM_PROVIDER=nebius but NEBIUS_API_KEY is empty")
            self._client = AsyncOpenAI(base_url=settings.upstream_base_url, api_key=settings.nebius_api_key, timeout=90, max_retries=1)
            self._models = {
                "nano": settings.nebius_model_nano,
                "super": settings.nebius_model_super,
                "ultra": settings.nebius_model_ultra,
            }
        elif self.provider == "local":
            self._client = AsyncOpenAI(
                base_url=settings.local_llm_base_url, api_key=settings.local_llm_api_key or "none", timeout=120, max_retries=1
            )
            self._models = dict.fromkeys(("nano", "super", "ultra"), settings.local_llm_model)
        else:
            raise ValueError(f"LLM_PROVIDER must be 'nebius' or 'local', got {settings.llm_provider!r}")

    def model_for(self, tier: str) -> str:
        return self._models[tier]

    async def chat(self, messages: list[dict[str, str]], tier: str = "nano", temperature: float = 0.0,
                   max_tokens: int = 512) -> LLMResult:
        """One chat call. Reasoning models (Nemotron) think before they answer, so a small ``max_tokens`` can be spent
        entirely on thinking and return nothing; in that case retry once with a larger budget."""
        model = self.model_for(tier)
        t0 = time.perf_counter()
        prompt_tokens = completion_tokens = 0
        text = ""
        for budget in (max_tokens, min(max_tokens * 4, 4096)):
            r = await self._client.chat.completions.create(
                model=model, messages=messages, temperature=temperature, max_tokens=budget
            )
            usage = r.usage
            prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
            completion_tokens += getattr(usage, "completion_tokens", 0) or 0
            text = re.sub(r"<think>.*?</think>", "", r.choices[0].message.content or "", flags=re.S).strip()
            if text or r.choices[0].finish_reason != "length":
                break
        return LLMResult(
            text=text,
            model=model,
            provider=self.provider,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=round((time.perf_counter() - t0) * 1000, 1),
        )


_llm: LLM | None = None


def get_llm() -> LLM:
    global _llm
    if _llm is None:
        _llm = LLM(get_settings())
    return _llm
