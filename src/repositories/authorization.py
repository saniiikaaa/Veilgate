"""Thin wrappers around the SQL guard functions (section 10 of schema.sql).

These run the database's decision functions and map the result rows to Pydantic
models. ``request_detokenize`` also writes a vault_access_log row and (when a
session is given) a receipt inside the function, so the caller must commit the
session afterwards.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.types import BoundaryKind
from src.repositories.models import (
    AuthorizeResult,
    DetokenizeResult,
    ToolCallAuthResult,
    VerifyResult,
)


async def authorize(
    session: AsyncSession,
    principal_id: UUID,
    permission: str,
    resource_type: str | None = None,
    resource_ref: str | None = None,
    boundary: BoundaryKind | None = None,
    run_id: UUID | None = None,
) -> AuthorizeResult:
    result = await session.execute(
        text(
            "SELECT allowed, effect, rule_id, reason FROM fn_authorize("
            ":principal, :permission, :rtype, :rref, :boundary, :run)"
        ),
        {
            "principal": principal_id,
            "permission": permission,
            "rtype": resource_type,
            "rref": resource_ref,
            "boundary": boundary,
            "run": run_id,
        },
    )
    row = result.fetchone()
    return AuthorizeResult.model_validate(dict(row._mapping))


async def authorize_tool_call(
    session: AsyncSession, run_id: UUID, tool_id: UUID
) -> ToolCallAuthResult:
    result = await session.execute(
        text(
            "SELECT allowed, reason, required_score, current_score, rule_id, "
            "suggested_penalty FROM fn_authorize_tool_call(:run, :tool)"
        ),
        {"run": run_id, "tool": tool_id},
    )
    row = result.fetchone()
    return ToolCallAuthResult.model_validate(dict(row._mapping))


async def request_detokenize(
    session: AsyncSession,
    principal_id: UUID,
    entry_id: UUID,
    boundary: BoundaryKind,
    run_id: UUID | None = None,
    tool_id: UUID | None = None,
    session_id: UUID | None = None,
    event_id: UUID | None = None,
) -> DetokenizeResult:
    result = await session.execute(
        text(
            "SELECT allowed, reason, value_ciphertext, nonce, key_id "
            "FROM fn_request_detokenize("
            ":principal, :entry, :boundary, :run, :tool, :session, :event)"
        ),
        {
            "principal": principal_id,
            "entry": entry_id,
            "boundary": boundary,
            "run": run_id,
            "tool": tool_id,
            "session": session_id,
            "event": event_id,
        },
    )
    row = result.fetchone()
    return DetokenizeResult.model_validate(dict(row._mapping))


async def verify_chain(session: AsyncSession, session_id: UUID) -> VerifyResult:
    result = await session.execute(
        text("SELECT ok, receipt_count, broken_at_seq, reason FROM fn_verify_receipts(:sid)"),
        {"sid": session_id},
    )
    row = result.fetchone()
    return VerifyResult.model_validate(dict(row._mapping))


async def get_run_score(session: AsyncSession, run_id: UUID) -> int:
    result = await session.execute(text("SELECT fn_run_score(:run)"), {"run": run_id})
    return int(result.scalar_one() or 0)


async def get_effective_score(session: AsyncSession, run_id: UUID) -> int:
    result = await session.execute(text("SELECT fn_effective_score(:run)"), {"run": run_id})
    return int(result.scalar_one() or 0)
