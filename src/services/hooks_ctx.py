"""Per-hook context: who is acting, in which session and run."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.repositories import vault as vault_repo
from src.repositories.db import set_tenant_context
from src.services import identity


@dataclass
class Ctx:
    """Everything a hook needs about who is acting."""

    db: AsyncSession
    tenant_id: UUID
    user_id: UUID
    session_id: UUID
    run_id: UUID
    agent_id: UUID
    agent_key: str
    parent_key: str | None
    key_id: UUID
    model: str | None = None  # the model behind this call, when the caller says
    judge_note: str | None = None  # injection quote from the LLM judge during this hook
    known_hits: int = 0  # session-known values found again in this hook's text


async def open_ctx(db: AsyncSession, user: str, agent: str, session: str, parent: str | None, model: str | None = None) -> Ctx:
    tenant_id = UUID(get_settings().default_tenant_id)
    await set_tenant_context(db, tenant_id)
    user_id = await identity.get_or_create_user(db, tenant_id, user)
    session_id = await identity.get_or_create_session(db, tenant_id, user_id, session)
    run_id, agent_id = await identity.get_or_create_run(db, tenant_id, session_id, user_id, agent, parent)
    key = await vault_repo.get_or_create_vault_key(db, tenant_id, f"file:{get_settings().vault_key_file}")
    return Ctx(db, tenant_id, user_id, session_id, run_id, agent_id, agent, parent, key.id, model)
