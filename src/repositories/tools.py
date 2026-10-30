"""Repository functions for the tool registry, grants, and thresholds."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.types import RiskLevel
from src.repositories.models import Tool


async def get_tool(session: AsyncSession, tool_id: UUID) -> Tool | None:
    result = await session.execute(
        text("SELECT * FROM tools WHERE id = :id"),
        {"id": tool_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return Tool.model_validate(dict(row._mapping))


async def get_tool_by_name(session: AsyncSession, tenant_id: UUID, name: str) -> Tool | None:
    result = await session.execute(
        text("SELECT * FROM tools WHERE tenant_id = :tid AND name = :name"),
        {"tid": tenant_id, "name": name},
    )
    row = result.fetchone()
    if row is None:
        return None
    return Tool.model_validate(dict(row._mapping))


async def get_agent_tools(session: AsyncSession, agent_id: UUID) -> list[Tool]:
    result = await session.execute(
        text(
            "SELECT t.* FROM tools t "
            "JOIN agent_tool_grants g ON g.tool_id = t.id "
            "WHERE g.agent_id = :aid AND (g.expires_at IS NULL OR g.expires_at > now())"
        ),
        {"aid": agent_id},
    )
    return [Tool.model_validate(dict(row._mapping)) for row in result.fetchall()]


async def get_risk_threshold(
    session: AsyncSession, tenant_id: UUID, risk: RiskLevel
) -> int:
    result = await session.execute(
        text("SELECT min_score FROM risk_thresholds WHERE tenant_id = :tid AND risk = :risk"),
        {"tid": tenant_id, "risk": risk},
    )
    row = result.fetchone()
    return int(row[0]) if row is not None else 0


async def get_tool_entity_access(
    session: AsyncSession, tool_id: UUID, direction: str
) -> list[str]:
    result = await session.execute(
        text(
            "SELECT entity_type_code FROM tool_entity_access "
            "WHERE tool_id = :tid AND direction = :dir"
        ),
        {"tid": tool_id, "dir": direction},
    )
    return [row[0] for row in result.fetchall()]


async def can_delegate(
    session: AsyncSession, parent_agent_id: UUID, child_agent_id: UUID
) -> bool:
    result = await session.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM agent_delegation_rules "
            "WHERE parent_agent_id = :p AND child_agent_id = :c)"
        ),
        {"p": parent_agent_id, "c": child_agent_id},
    )
    return bool(result.scalar_one())
