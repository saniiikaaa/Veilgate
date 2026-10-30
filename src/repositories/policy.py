"""Repository functions for the compliance catalog, roles, and policies."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.models import EntityType, Framework, HandlingRule, Permission


async def get_frameworks(session: AsyncSession) -> list[Framework]:
    result = await session.execute(text("SELECT * FROM frameworks ORDER BY code"))
    return [Framework.model_validate(dict(row._mapping)) for row in result.fetchall()]


async def get_entity_types(session: AsyncSession) -> list[EntityType]:
    result = await session.execute(text("SELECT * FROM entity_types ORDER BY code"))
    return [EntityType.model_validate(dict(row._mapping)) for row in result.fetchall()]


async def get_entity_types_for_framework(
    session: AsyncSession, framework_code: str
) -> list[EntityType]:
    result = await session.execute(
        text(
            "SELECT e.* FROM entity_types e "
            "JOIN entity_type_frameworks f ON f.entity_type_code = e.code "
            "WHERE f.framework_code = :code ORDER BY e.code"
        ),
        {"code": framework_code},
    )
    return [EntityType.model_validate(dict(row._mapping)) for row in result.fetchall()]


async def get_handling_rules(session: AsyncSession, tenant_id: UUID) -> list[HandlingRule]:
    result = await session.execute(
        text("SELECT * FROM handling_rules WHERE tenant_id = :tid ORDER BY priority"),
        {"tid": tenant_id},
    )
    return [HandlingRule.model_validate(dict(row._mapping)) for row in result.fetchall()]


async def get_permission(session: AsyncSession, code: str) -> Permission | None:
    result = await session.execute(
        text("SELECT * FROM permissions WHERE code = :code"),
        {"code": code},
    )
    row = result.fetchone()
    if row is None:
        return None
    return Permission.model_validate(dict(row._mapping))


async def get_roles_for_principal(session: AsyncSession, principal_id: UUID) -> list[dict]:
    result = await session.execute(
        text(
            "SELECT r.* FROM roles r "
            "JOIN principal_roles pr ON pr.role_id = r.id "
            "WHERE pr.principal_id = :pid"
        ),
        {"pid": principal_id},
    )
    return [dict(row._mapping) for row in result.fetchall()]


async def get_active_policies(session: AsyncSession, tenant_id: UUID) -> list[dict]:
    result = await session.execute(
        text("SELECT * FROM policies WHERE tenant_id = :tid AND status = 'active'"),
        {"tid": tenant_id},
    )
    return [dict(row._mapping) for row in result.fetchall()]


async def get_policy_rules(session: AsyncSession, policy_id: UUID) -> list[dict]:
    result = await session.execute(
        text("SELECT * FROM policy_rules WHERE policy_id = :pid ORDER BY priority"),
        {"pid": policy_id},
    )
    return [dict(row._mapping) for row in result.fetchall()]
