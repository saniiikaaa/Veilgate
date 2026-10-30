"""Resolve the string identities that hooks carry (user_id, agent_id, session_id) to database rows.

Unknown users, agents and tools are provisioned on first sight, so any framework can attach without setup.
"""

from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.scoring import get_scoring

DEFAULT_ROLE = "agent_default"


def session_uuid(external: str) -> UUID:
    try:
        return UUID(external)
    except ValueError:
        return uuid5(NAMESPACE_URL, f"veilgate:session:{external}")


async def _principal(db: AsyncSession, tenant_id: UUID, kind: str, display: str) -> UUID:
    pid = uuid4()
    await db.execute(
        text("INSERT INTO principals (id, tenant_id, kind, display_name) VALUES (:id, :t, :k, :n)"),
        {"id": pid, "t": tenant_id, "k": kind, "n": display},
    )
    return pid


async def get_or_create_user(db: AsyncSession, tenant_id: UUID, user_key: str) -> UUID:
    email = f"{user_key}@veilgate.local" if "@" not in user_key else user_key
    row = (await db.execute(
        text("SELECT principal_id FROM users WHERE tenant_id = :t AND email = :e"), {"t": tenant_id, "e": email}
    )).fetchone()
    if row:
        return row[0]
    pid = await _principal(db, tenant_id, "user", user_key)
    await db.execute(
        text("INSERT INTO users (principal_id, tenant_id, email, name) VALUES (:p, :t, :e, :n)"),
        {"p": pid, "t": tenant_id, "e": email, "n": user_key},
    )
    return pid


async def get_or_create_agent(db: AsyncSession, tenant_id: UUID, agent_key: str, owner: UUID | None = None) -> UUID:
    row = (await db.execute(
        text("SELECT principal_id FROM agents WHERE tenant_id = :t AND agent_key = :k"), {"t": tenant_id, "k": agent_key}
    )).fetchone()
    if row:
        return row[0]
    pid = await _principal(db, tenant_id, "agent", agent_key)
    await db.execute(
        text("INSERT INTO agents (principal_id, tenant_id, agent_key, owner_user_id, initial_score) VALUES (:p, :t, :k, :o, :s)"),
        {"p": pid, "t": tenant_id, "k": agent_key, "o": owner, "s": get_scoring().initial_score},
    )
    await db.execute(
        text("INSERT INTO principal_roles (principal_id, role_id) SELECT :p, id FROM roles WHERE tenant_id = :t AND name = :r"),
        {"p": pid, "t": tenant_id, "r": DEFAULT_ROLE},
    )
    return pid


async def get_or_create_tool(db: AsyncSession, tenant_id: UUID, name: str, risk: str = "medium") -> UUID:
    row = (await db.execute(
        text("SELECT id FROM tools WHERE tenant_id = :t AND name = :n"), {"t": tenant_id, "n": name}
    )).fetchone()
    if row:
        return row[0]
    risk = risk if risk in ("low", "medium", "high", "critical") else "medium"
    return (await db.execute(
        text("INSERT INTO tools (tenant_id, name, risk, min_trust) VALUES (:t, :n, :r, 'untrusted') RETURNING id"),
        {"t": tenant_id, "n": name, "r": risk},
    )).scalar_one()


async def grant_tool(db: AsyncSession, agent_id: UUID, tool_id: UUID) -> None:
    await db.execute(
        text("INSERT INTO agent_tool_grants (agent_id, tool_id) VALUES (:a, :t) ON CONFLICT DO NOTHING"),
        {"a": agent_id, "t": tool_id},
    )


async def get_or_create_session(db: AsyncSession, tenant_id: UUID, user_id: UUID, external: str) -> UUID:
    sid = session_uuid(external)
    await db.execute(
        text(
            "INSERT INTO sessions (id, tenant_id, user_id, channel, external_ref) VALUES (:id, :t, :u, 'hooks', :e) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": sid, "t": tenant_id, "u": user_id, "e": external},
    )
    return sid


async def get_or_create_run(
    db: AsyncSession, tenant_id: UUID, session_id: UUID, owner: UUID, agent_key: str, parent_key: str | None
) -> tuple[UUID, UUID]:
    """Return (run_id, agent_id) for this agent in this session, creating the run (and its parent's) if needed."""
    row = (await db.execute(
        text(
            "SELECT r.id, r.agent_id FROM agent_runs r JOIN agents a ON a.principal_id = r.agent_id "
            "WHERE r.session_id = :s AND a.agent_key = :k ORDER BY r.started_at LIMIT 1"
        ),
        {"s": session_id, "k": agent_key},
    )).fetchone()
    if row:
        return row[0], row[1]
    parent_run = None
    if parent_key and parent_key != agent_key:
        parent_run, _ = await get_or_create_run(db, tenant_id, session_id, owner, parent_key, None)
    agent_id = await get_or_create_agent(db, tenant_id, agent_key, owner)
    run_id = (await db.execute(
        text(
            "INSERT INTO agent_runs (tenant_id, session_id, agent_id, parent_run_id, initial_score, score_ceiling) "
            "SELECT :t, :s, :a, :p, initial_score, score_ceiling FROM agents WHERE principal_id = :a RETURNING id"
        ),
        {"t": tenant_id, "s": session_id, "a": agent_id, "p": parent_run},
    )).scalar_one()
    return run_id, agent_id
