"""Heuristic prompt-injection detector (fast first pass; an LLM judge can confirm in a later phase)."""

import re

_PATTERNS = [
    r"ignore (?:all |any )?(?:the )?(?:previous|prior|above|earlier) (?:instructions|prompts?|rules)",
    r"disregard (?:all |any )?(?:the )?(?:previous|prior|above|your) (?:instructions|rules|guidelines)",
    r"forget (?:everything|all) (?:you|above|previous)",
    r"you are now (?:in )?(?:dan|developer mode|jailbroken|an? unrestricted)",
    r"(?:reveal|print|show|repeat|leak) (?:your |the )?(?:system|hidden|initial) (?:prompt|instructions)",
    r"(?:send|forward|email|exfiltrate) (?:all |every |the )?(?:data|records|patients?|credentials|secrets?)\b.{0,40}\bto\b",
    r"override (?:the )?(?:safety|security|governance|policy|guardrails?)",
    r"new instructions?\s*:",
    r"</?(?:system|assistant)>",
]
_RX = [re.compile(p, re.I | re.S) for p in _PATTERNS]


def find_injection(text: str) -> list[str]:
    """Return the matched phrases (empty when the text looks clean)."""
    return [m.group(0)[:80] for rx in _RX for m in [rx.search(text)] if m]
