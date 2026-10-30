"""Repository functions for principals, users, and agents."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.models import Agent, Principal, User


async def get_agent(session: AsyncSession, agent_id: UUID) -> Agent | None:
    result = await session.execute(
        text("SELECT * FROM agents WHERE principal_id = :id"),
        {"id": agent_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return Agent.model_validate(dict(row._mapping))


async def get_agent_by_key(
    session: AsyncSession, tenant_id: UUID, agent_key: str
) -> Agent | None:
    result = await session.execute(
        text("SELECT * FROM agents WHERE tenant_id = :tid AND agent_key = :key"),
        {"tid": tenant_id, "key": agent_key},
    )
    row = result.fetchone()
    if row is None:
        return None
    return Agent.model_validate(dict(row._mapping))


async def list_agents(session: AsyncSession, tenant_id: UUID) -> list[Agent]:
    result = await session.execute(
        text("SELECT * FROM agents WHERE tenant_id = :tid ORDER BY created_at"),
        {"tid": tenant_id},
    )
    return [Agent.model_validate(dict(row._mapping)) for row in result.fetchall()]


async def get_principal(session: AsyncSession, principal_id: UUID) -> Principal | None:
    result = await session.execute(
        text("SELECT * FROM principals WHERE id = :id"),
        {"id": principal_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return Principal.model_validate(dict(row._mapping))


async def get_user(session: AsyncSession, user_id: UUID) -> User | None:
    result = await session.execute(
        text("SELECT * FROM users WHERE principal_id = :id"),
        {"id": user_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return User.model_validate(dict(row._mapping))
