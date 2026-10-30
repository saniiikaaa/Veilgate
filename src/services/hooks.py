"""The five governance hooks. Each runs in one database transaction under the tenant's row-level security."""

import hashlib
import json
import time
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.scoring import get_scoring
from src.detection import TOKEN_RX, detect, find_injection, find_known, merge
from src.repositories import audit as audit_repo
from src.repositories import authorization as authz_repo
from src.repositories import events as events_repo
from src.repositories import vault as vault_repo
from src.repositories.db import _get_session_factory
from src.services import identity
from src.detection import judge as llm_judge
from src.services import authority
from src.services.hooks_ctx import Ctx, open_ctx  # noqa: F401 - re-exported for the API layer
from src.vault.crypto import VaultCrypto, load_key
from src.vault.tokenizer import tokenize

log = structlog.get_logger(__name__)

_crypto: VaultCrypto | None = None


def get_crypto() -> VaultCrypto:
    global _crypto
    if _crypto is None:
        settings = get_settings()
        _crypto = VaultCrypto(load_key(settings.vault_key_file, settings.vault_key_hex))
    return _crypto


async def _trusted_tokens(ctx: Ctx, value: str) -> set[str]:
    """Token-shaped strings in ``value`` that the vault really issued. Fakes are scanned like any other text."""
    found = set(TOKEN_RX.findall(value))
    if not found:
        return set()
    rows = (await ctx.db.execute(
        text("SELECT token FROM vault_entries WHERE tenant_id = :t AND token = ANY(:tokens)"),
        {"t": ctx.tenant_id, "tokens": list(found)},
    )).fetchall()
    return {r[0] for r in rows}


async def _known_values(ctx: Ctx) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Values already tokenized in this session, decrypted in memory only: (all of them, those that came in from outside).

    All of them are used to protect text in any format. Only the ones that arrived through an input (the user, a handoff or
    a tool) count as real when a model repeats them; a value the model itself made up is protected but is not a leak.
    """
    rows = (await ctx.db.execute(
        text(
            "SELECT v.entity_type_code, v.value_ciphertext, v.nonce, bool_or(e.boundary <> 'model_output') AS from_input "
            "FROM vault_entries v JOIN event_entities ee ON ee.vault_entry_id = v.id JOIN events e ON e.id = ee.event_id "
            "WHERE e.session_id = :s AND v.value_ciphertext IS NOT NULL GROUP BY v.id"
        ),
        {"s": ctx.session_id},
    )).fetchall()
    crypto = get_crypto()
    plain = [(r[0], crypto.decrypt(bytes(r[1]), bytes(r[2])), r[3]) for r in rows]
    return [(t, v) for t, v, _ in plain], [(t, v) for t, v, from_input in plain if from_input]


def _masked_view(value: str, entities: list) -> str:
    out, pos = [], 0
    for e in entities:
        out += [value[pos:e.start], f"<{e.type}>"]
        pos = e.end
    return "".join(out) + value[pos:]


async def _protect(ctx: Ctx, value: str, boundary: str = "model_input") -> tuple[str, list]:
    """Detect and tokenize sensitive values in ``value``. Returns (safe text, [(entity, entry_id, token)])."""
    trusted = await _trusted_tokens(ctx, value)
    all_known, input_known = await _known_values(ctx)
    known = find_known(value, all_known)
    ctx.known_hits = len(find_known(value, input_known))  # real values from this session showing up again (a genuine leak)
    entities = merge(detect(value, trusted_tokens=trusted), known, value)
    if llm_judge.needs_judge(_masked_view(value, entities), boundary):
        verdict = await llm_judge.judge(value, entities, boundary)
        entities = merge(entities, verdict.entities, value)
        ctx.judge_note = verdict.injection
    if not entities:
        return value, []
    result = await tokenize(ctx.db, get_crypto(), ctx.tenant_id, ctx.key_id, value, entities, ctx.user_id)
    return result.text, result.items


async def _record(
    ctx: Ctx, boundary: str, outcome: str, safe_text: str | None, items: list, latency_ms: float,
    detail: dict[str, Any] | None = None,
):
    """Write the event, its entity links and a hash-chained receipt."""
    sha = hashlib.sha256(safe_text.encode()).hexdigest() if safe_text is not None else None
    ev = await events_repo.create_event(
        ctx.db, ctx.tenant_id, ctx.session_id, boundary, outcome, run_id=ctx.run_id,
        entities_found=len(items), tokenized_text=safe_text, text_sha256=sha, latency_ms=latency_ms,
    )
    for entity, entry_id, _token in items:
        await ctx.db.execute(
            text(
                "INSERT INTO event_entities (event_id, vault_entry_id, entity_type_code, confidence) "
                "VALUES (:e, :v, :t, :c) ON CONFLICT DO NOTHING"
            ),
            {"e": ev.id, "v": entry_id, "t": entity.type, "c": entity.confidence},
        )
    payload = {
        "agent": ctx.agent_key, "parent": ctx.parent_key, "boundary": boundary, "outcome": outcome,
        "text_sha256": sha, "entities": sorted({e.type for e, _, _ in items}), **(detail or {}),
    }
    if ctx.model:
        payload["model"] = ctx.model
    await audit_repo.insert_receipt(ctx.db, ctx.tenant_id, ctx.session_id, "decision", payload, ev.id, ctx.run_id)
    return ev


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


async def _first_event(ctx: Ctx) -> bool:
    n = (await ctx.db.execute(text("SELECT count(*) FROM events WHERE run_id = :r"), {"r": ctx.run_id})).scalar_one()
    return n == 0


def _bad_recipients(tool_name: str, raw_args: str) -> list[str]:
    """Email addresses in the args of a mail-like tool that fall outside ALLOWED_EMAIL_DOMAINS."""
    if not any(w in tool_name.lower() for w in ("mail", "send", "message", "notify")):
        return []
    allowed = {d.strip().lower() for d in get_settings().allowed_email_domains.split(",") if d.strip()}
    return [e.value for e in detect(raw_args, {"EMAIL"}) if e.value.rsplit("@", 1)[-1].lower() not in allowed]


async def on_prompt_received(ctx: Ctx, prompt: str) -> str:
    t0 = time.perf_counter()
    first = await _first_event(ctx)
    safe, items = await _protect(ctx, prompt, "model_input")
    hits = find_injection(prompt)  # a user's or an agent's own instructions are never "injection" by the judge's say-so
    boundary = ("handoff" if ctx.parent_key else "user_input") if first else "model_input"
    outcome = "logged" if hits else ("tokenized" if items else "allowed")
    ev = await _record(ctx, boundary, outcome, safe, items, _ms(t0), {"injection": hits} if hits else None)
    await ctx.db.execute(
        text("INSERT INTO model_calls (tenant_id, run_id, request_event_id) VALUES (:t, :r, :e)"),
        {"t": ctx.tenant_id, "r": ctx.run_id, "e": ev.id},
    )
    if hits:
        await authority.apply_rule(ctx, "prompt_injection", ev.id, f"injection phrase in prompt: {hits[0]}")
    return safe


async def on_completion_received(
    ctx: Ctx, completion: str, prompt_tokens: int, completion_tokens: int, latency_ms: float
) -> str:
    t0 = time.perf_counter()
    safe, items = await _protect(ctx, completion, "model_output")
    # A real value from this session repeated in the agent's own reply costs it authority. Invented look-alike values
    # (a hallucinated MRN, a made-up name) are still tokenized, but they are not a leak.
    if ctx.known_hits:
        await authority.apply_rule(ctx, "pii_in_reply", None, f"reply repeated {ctx.known_hits} real value(s) from this session")

    blocked_reason = None
    if ctx.parent_key and await authority.own_score(ctx) < get_scoring().block_below:
        blocked_reason = f"agent {ctx.agent_key} is below the trust floor; its reply is withheld from {ctx.parent_key}"
    elif not ctx.parent_key:
        verdict = await authority.session_verdict(ctx.db, ctx.session_id)
        if verdict.blocked:
            blocked_reason = f"output blocked: {verdict.reason}"
    result_text = f"output blocked: {blocked_reason}" if blocked_reason and not blocked_reason.startswith("output") else (blocked_reason or safe)

    outcome = "blocked" if blocked_reason else ("tokenized" if items else "allowed")
    ev = await _record(ctx, "model_output", outcome, result_text if blocked_reason else safe, items, _ms(t0),
                       {"blocked": blocked_reason} if blocked_reason else None)
    updated = await ctx.db.execute(
        text(
            "UPDATE model_calls SET response_event_id = :e, prompt_tokens = :pt, completion_tokens = :ct, latency_ms = :l "
            "WHERE id = (SELECT id FROM model_calls WHERE run_id = :r AND response_event_id IS NULL "
            "ORDER BY created_at DESC LIMIT 1)"
        ),
        {"e": ev.id, "pt": prompt_tokens, "ct": completion_tokens, "l": latency_ms, "r": ctx.run_id},
    )
    if updated.rowcount == 0:
        await events_repo.create_model_call(
            ctx.db, ctx.tenant_id, ctx.run_id, response_event_id=ev.id, prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens, latency_ms=latency_ms,
        )
    return result_text


async def on_tool_call(
    ctx: Ctx, tool_name: str, tool_args: Any, tool_risk: str, allowed_tools: list[str] | None
) -> bool:
    t0 = time.perf_counter()
    tool_id = await identity.get_or_create_tool(ctx.db, ctx.tenant_id, tool_name, tool_risk)
    if allowed_tools is not None and tool_name in allowed_tools:
        await identity.grant_tool(ctx.db, ctx.agent_id, tool_id)
    decision = await authz_repo.authorize_tool_call(ctx.db, ctx.run_id, tool_id)

    raw = json.dumps(tool_args, default=str, ensure_ascii=False)
    bad = _bad_recipients(tool_name, raw) if decision.allowed else []
    allowed = bool(decision.allowed) and not bad
    reason = decision.reason if not bad else f"recipient outside allowed domains: {', '.join(bad)}"
    penalty = decision.suggested_penalty if not decision.allowed else ("external_recipient" if bad else None)

    safe_raw, items = await _protect(ctx, raw, "tool_input")
    try:
        safe_args = json.loads(safe_raw)
    except ValueError:
        safe_args = {"_": safe_raw}
    outcome = "allowed" if allowed else "denied"
    ev = await _record(
        ctx, "tool_input", outcome, safe_raw, items, _ms(t0),
        {"tool": tool_name, "risk": tool_risk, "reason": reason, "required_score": decision.required_score,
         "score": decision.current_score},
    )
    await events_repo.create_tool_call(
        ctx.db, ctx.tenant_id, ctx.run_id, tool_id, ev.id, safe_args if isinstance(safe_args, dict) else {"args": safe_args},
        outcome, decision.required_score, decision.current_score,
    )
    if penalty:
        await authority.apply_rule(ctx, penalty, ev.id, f"{tool_name}: {reason}")
    return allowed


async def on_tool_result(ctx: Ctx, tool_name: str, result: str, succeeded: bool, latency_ms: float) -> str:
    t0 = time.perf_counter()
    safe, items = await _protect(ctx, result, "tool_output")
    hits = find_injection(result) + ([f"judge: {ctx.judge_note}"] if ctx.judge_note else [])
    if hits:
        safe = f"[blocked: prompt injection detected in the output of {tool_name}]"
    outcome = "blocked" if hits else ("tokenized" if items else "allowed")
    ev = await _record(
        ctx, "tool_output", outcome, safe, items, _ms(t0),
        {"tool": tool_name, "succeeded": succeeded, "tool_latency_ms": latency_ms, **({"injection": hits} if hits else {})},
    )
    row = (await ctx.db.execute(
        text(
            "SELECT tc.id FROM tool_calls tc JOIN tools t ON t.id = tc.tool_id WHERE tc.run_id = :r AND t.name = :n "
            "AND tc.result_event_id IS NULL AND tc.outcome <> 'denied' ORDER BY tc.started_at DESC LIMIT 1"
        ),
        {"r": ctx.run_id, "n": tool_name},
    )).fetchone()
    if row:
        await events_repo.update_tool_call_result(
            ctx.db, row[0], ev.id, "blocked" if hits else ("allowed" if succeeded else "blocked"),
            error=None if succeeded else "tool failed",
        )
    if hits:
        await authority.apply_rule(ctx, "prompt_injection", ev.id, f"injection in {tool_name} output: {hits[0]}")
    elif succeeded:
        await authority.apply_rule(ctx, "clean_tool_result", ev.id, f"{tool_name} ran cleanly")
    return safe


async def on_session_end(ctx: Ctx, summary: dict[str, Any]) -> None:
    verdict = await authority.session_verdict(ctx.db, ctx.session_id)
    await ctx.db.execute(
        text("UPDATE agent_runs SET status = 'completed', ended_at = now() WHERE session_id = :s AND status = 'running'"),
        {"s": ctx.session_id},
    )
    await ctx.db.execute(text("UPDATE sessions SET ended_at = now() WHERE id = :s"), {"s": ctx.session_id})
    await audit_repo.insert_receipt(
        ctx.db, ctx.tenant_id, ctx.session_id, "decision",
        {"boundary": "session_end", "summary": summary, "verdict": {"blocked": verdict.blocked, "reason": verdict.reason, "scores": verdict.scores}},
        None, ctx.run_id,
    )


def session_factory():
    return _get_session_factory()()
