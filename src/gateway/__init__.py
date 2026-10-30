"""Model gateway: one OpenAI-compatible client, two providers behind a single toggle."""

from src.gateway.llm import LLMResult, get_llm

__all__ = ["LLMResult", "get_llm"]
