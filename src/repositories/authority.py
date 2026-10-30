"""Repository functions for the authority score (rules, ledger, live scores)."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.models import ScoreLedger, ScoreRule


async def get_score_rule(
    session: AsyncSession, tenant_id: UUID, code: str
) -> ScoreRule | None:
    result = await session.execute(
        text("SELECT * FROM score_rules WHERE tenant_id = :tid AND code = :code"),
        {"tid": tenant_id, "code": code},
    )
    row = result.fetchone()
    if row is None:
        return None
    return ScoreRule.model_validate(dict(row._mapping))


async def append_score_event(
    session: AsyncSession,
    tenant_id: UUID,
    run_id: UUID,
    rule_id: UUID,
    delta: int,
    reason: str | None = None,
    event_id: UUID | None = None,
    admin_audit_id: UUID | None = None,
) -> ScoreLedger:
    # The fn_ledger_guard trigger validates the delta against the rule's kind.
    result = await session.execute(
        text(
            "INSERT INTO score_ledger (tenant_id, run_id, rule_id, delta, reason, "
            "event_id, admin_audit_id) "
            "VALUES (:tid, :run, :rule, :delta, :reason, :event, :audit) RETURNING *"
        ),
        {
            "tid": tenant_id,
            "run": run_id,
            "rule": rule_id,
            "delta": delta,
            "reason": reason,
            "event": event_id,
            "audit": admin_audit_id,
        },
    )
    return ScoreLedger.model_validate(dict(result.fetchone()._mapping))


async def get_current_score(session: AsyncSession, run_id: UUID) -> int:
    result = await session.execute(text("SELECT fn_run_score(:run)"), {"run": run_id})
    return int(result.scalar_one() or 0)


async def get_effective_score(session: AsyncSession, run_id: UUID) -> int:
    result = await session.execute(text("SELECT fn_effective_score(:run)"), {"run": run_id})
    return int(result.scalar_one() or 0)


async def get_score_history(session: AsyncSession, run_id: UUID) -> list[ScoreLedger]:
    result = await session.execute(
        text("SELECT * FROM score_ledger WHERE run_id = :run ORDER BY id"),
        {"run": run_id},
    )
    return [ScoreLedger.model_validate(dict(row._mapping)) for row in result.fetchall()]
