"""Agent authority: score penalties and rewards, run status, and the session verdict.

An agent's score starts at its initial value and only falls on violations; it earns a little back for clean,
verified tool results. A sub-agent is capped by its parent (see fn_effective_score). Every change is a ledger row
(the database refuses an unexplained rise) and an authority receipt.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.scoring import get_scoring
from src.repositories import audit as audit_repo
from src.repositories import authority as authority_repo
from src.services.hooks_ctx import Ctx



async def apply_rule(ctx: Ctx, code: str, event_id: UUID | None, reason: str) -> int | None:
    """Record rule ``code`` on this run. Returns the delta applied, or None if the tenant has no such rule."""
    rule = await authority_repo.get_score_rule(ctx.db, ctx.tenant_id, code)
    if rule is None:
        return None
    await authority_repo.append_score_event(ctx.db, ctx.tenant_id, ctx.run_id, rule.id, rule.delta, reason, event_id)
    own = await authority_repo.get_current_score(ctx.db, ctx.run_id)
    eff = await authority_repo.get_effective_score(ctx.db, ctx.run_id)
    await audit_repo.insert_receipt(
        ctx.db, ctx.tenant_id, ctx.session_id, "authority",
        {"agent": ctx.agent_key, "rule": code, "delta": rule.delta, "reason": reason, "score": own, "effective": eff},
        event_id, ctx.run_id,
    )
    if own < get_scoring().block_below:
        await ctx.db.execute(text("UPDATE agent_runs SET status = 'blocked' WHERE id = :r AND status = 'running'"), {"r": ctx.run_id})
    return rule.delta


async def own_score(ctx: Ctx) -> int:
    return await authority_repo.get_current_score(ctx.db, ctx.run_id)


@dataclass(frozen=True)
class Verdict:
    blocked: bool
    reason: str
    scores: dict[str, int]


async def session_verdict(db: AsyncSession, session_id: UUID) -> Verdict:
    rows = (await db.execute(
        text(
            "SELECT a.agent_key, fn_run_score(r.id) FROM agent_runs r JOIN agents a ON a.principal_id = r.agent_id "
            "WHERE r.session_id = :s"
        ),
        {"s": session_id},
    )).fetchall()
    scores = {r[0]: int(r[1]) for r in rows}
    sc = get_scoring()
    low = [k for k, v in scores.items() if v < sc.block_below]
    mid = [k for k, v in scores.items() if v < sc.warn_below]
    if low:
        return Verdict(True, f"agent(s) {', '.join(sorted(low))} fell below {sc.block_below}", scores)
    if len(scores) >= 2 and len(mid) * 2 >= len(scores):
        return Verdict(True, f"{len(mid)} of {len(scores)} agents fell below {sc.warn_below}", scores)
    return Verdict(False, "ok", scores)
