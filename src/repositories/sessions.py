"""Repository functions for runtime sessions and agent runs."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.types import RunState
from src.repositories.models import AgentRun, Session


async def create_session(
    session: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    channel: str | None = None,
    external_ref: str | None = None,
) -> Session:
    result = await session.execute(
        text(
            "INSERT INTO sessions (tenant_id, user_id, channel, external_ref) "
            "VALUES (:tid, :uid, :channel, :eref) RETURNING *"
        ),
        {"tid": tenant_id, "uid": user_id, "channel": channel, "eref": external_ref},
    )
    return Session.model_validate(dict(result.fetchone()._mapping))


async def get_session(session: AsyncSession, session_id: UUID) -> Session | None:
    result = await session.execute(
        text("SELECT * FROM sessions WHERE id = :id"),
        {"id": session_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return Session.model_validate(dict(row._mapping))


async def end_session(session: AsyncSession, session_id: UUID) -> None:
    await session.execute(
        text("UPDATE sessions SET ended_at = now() WHERE id = :id"),
        {"id": session_id},
    )


async def create_run(
    session: AsyncSession,
    tenant_id: UUID,
    session_id: UUID,
    agent_id: UUID,
    parent_run_id: UUID | None = None,
) -> AgentRun:
    # initial_score and score_ceiling are copied from the agent at run start.
    result = await session.execute(
        text(
            "INSERT INTO agent_runs (tenant_id, session_id, agent_id, parent_run_id, "
            "initial_score, score_ceiling) "
            "SELECT :tid, :sid, :aid, :parent, a.initial_score, a.score_ceiling "
            "FROM agents a WHERE a.principal_id = :aid "
            "RETURNING *"
        ),
        {"tid": tenant_id, "sid": session_id, "aid": agent_id, "parent": parent_run_id},
    )
    return AgentRun.model_validate(dict(result.fetchone()._mapping))


async def get_run(session: AsyncSession, run_id: UUID) -> AgentRun | None:
    result = await session.execute(
        text("SELECT * FROM agent_runs WHERE id = :id"),
        {"id": run_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return AgentRun.model_validate(dict(row._mapping))


async def update_run_status(
    session: AsyncSession, run_id: UUID, status: RunState
) -> None:
    await session.execute(
        text("UPDATE agent_runs SET status = :status, ended_at = now() WHERE id = :id"),
        {"status": status, "id": run_id},
    )
