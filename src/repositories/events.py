"""Repository functions for runtime events, tool calls, and model calls."""

import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.types import BoundaryKind, EventOutcome
from src.repositories.models import Event, ModelCall, ToolCall


async def create_event(
    session: AsyncSession,
    tenant_id: UUID,
    session_id: UUID,
    boundary: BoundaryKind,
    outcome: EventOutcome,
    run_id: UUID | None = None,
    policy_rule_id: UUID | None = None,
    entities_found: int = 0,
    tokenized_text: str | None = None,
    text_sha256: str | None = None,
    latency_ms: float | None = None,
) -> Event:
    result = await session.execute(
        text(
            "INSERT INTO events (tenant_id, session_id, run_id, boundary, outcome, "
            "policy_rule_id, entities_found, tokenized_text, text_sha256, latency_ms) "
            "VALUES (:tid, :sid, :run, :boundary, :outcome, :rule, :entities, "
            ":ttext, :sha, :lat) RETURNING *"
        ),
        {
            "tid": tenant_id,
            "sid": session_id,
            "run": run_id,
            "boundary": boundary,
            "outcome": outcome,
            "rule": policy_rule_id,
            "entities": entities_found,
            "ttext": tokenized_text,
            "sha": text_sha256,
            "lat": latency_ms,
        },
    )
    return Event.model_validate(dict(result.fetchone()._mapping))


async def get_event(session: AsyncSession, event_id: UUID) -> Event | None:
    result = await session.execute(
        text("SELECT * FROM events WHERE id = :id"),
        {"id": event_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return Event.model_validate(dict(row._mapping))


async def list_events_for_session(session: AsyncSession, session_id: UUID) -> list[Event]:
    result = await session.execute(
        text("SELECT * FROM events WHERE session_id = :sid ORDER BY created_at"),
        {"sid": session_id},
    )
    return [Event.model_validate(dict(row._mapping)) for row in result.fetchall()]


async def create_tool_call(
    session: AsyncSession,
    tenant_id: UUID,
    run_id: UUID,
    tool_id: UUID,
    request_event_id: UUID,
    args_tokenized: dict | None = None,
    outcome: EventOutcome = EventOutcome.ALLOWED,
    required_score: int | None = None,
    score_at_call: int | None = None,
) -> ToolCall:
    result = await session.execute(
        text(
            "INSERT INTO tool_calls (tenant_id, run_id, tool_id, request_event_id, "
            "args_tokenized, outcome, required_score, score_at_call) "
            "VALUES (:tid, :run, :tool, :req, CAST(:args AS jsonb), :outcome, "
            ":req_score, :score) RETURNING *"
        ),
        {
            "tid": tenant_id,
            "run": run_id,
            "tool": tool_id,
            "req": request_event_id,
            "args": json.dumps(args_tokenized) if args_tokenized is not None else None,
            "outcome": outcome,
            "req_score": required_score,
            "score": score_at_call,
        },
    )
    return ToolCall.model_validate(dict(result.fetchone()._mapping))


async def update_tool_call_result(
    session: AsyncSession,
    tool_call_id: UUID,
    result_event_id: UUID,
    outcome: EventOutcome,
    detokenized: bool = False,
    error: str | None = None,
) -> None:
    await session.execute(
        text(
            "UPDATE tool_calls SET result_event_id = :revid, outcome = :outcome, "
            "detokenized = :detok, finished_at = now(), error = :error WHERE id = :id"
        ),
        {
            "revid": result_event_id,
            "outcome": outcome,
            "detok": detokenized,
            "error": error,
            "id": tool_call_id,
        },
    )


async def create_model_call(
    session: AsyncSession,
    tenant_id: UUID,
    run_id: UUID,
    model_id: UUID | None = None,
    request_event_id: UUID | None = None,
    response_event_id: UUID | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    tokens_estimated: bool = False,
    latency_ms: float | None = None,
    cost: float | None = None,
) -> ModelCall:
    result = await session.execute(
        text(
            "INSERT INTO model_calls (tenant_id, run_id, model_id, request_event_id, "
            "response_event_id, prompt_tokens, completion_tokens, tokens_estimated, "
            "latency_ms, cost) "
            "VALUES (:tid, :run, :model, :req, :resp, :pt, :ct, :est, :lat, :cost) "
            "RETURNING *"
        ),
        {
            "tid": tenant_id,
            "run": run_id,
            "model": model_id,
            "req": request_event_id,
            "resp": response_event_id,
            "pt": prompt_tokens,
            "ct": completion_tokens,
            "est": tokens_estimated,
            "lat": latency_ms,
            "cost": cost,
        },
    )
    return ModelCall.model_validate(dict(result.fetchone()._mapping))
