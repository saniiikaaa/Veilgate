"""Integration tests for the repository layer against the live Postgres.

Uses SQLAlchemy async + asyncpg (via the repository layer, NOT raw asyncpg) and
sets the RLS tenant context via ``set_tenant_context``. Every test opens its own
engine and session, rolls back after each test, and disposes the engine, so the
seeded data is never mutated and the suite is repeatable.

Assumes the schema and seeds are applied (scripts/db/migrate.py + seed.py) and
the ``warden-db`` container is running.
"""

import hashlib
import hmac

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from uuid import UUID

from src.core.config import get_settings
from src.core.types import AuthEffect, ReceiptKind, RunState, TrustTier
from src.repositories.agents import get_agent, get_agent_by_key
from src.repositories.audit import insert_receipt, verify_chain
from src.repositories.authorization import authorize, authorize_tool_call
from src.repositories.authority import append_score_event, get_current_score, get_score_rule
from src.repositories.db import set_tenant_context, to_async_url
from src.repositories.sessions import create_run, create_session
from src.repositories.tools import get_agent_tools
from src.repositories.vault import (
    create_vault_entry,
    get_or_create_vault_key,
    get_vault_entry_by_hmac,
    get_vault_entry_by_token,
)

# Use function-scoped loops for these tests so each test gets a fresh event loop
# and asyncpg connections are never shared between tests or with test_db.py's raw asyncpg.
pytestmark = pytest.mark.asyncio(loop_scope="function")

DEMO_TENANT = UUID("11111111-1111-1111-1111-111111111111")
DEMO_USER = UUID("22222222-2222-2222-2222-222222222222")
ORCH = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
DATA_AGENT = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
LOOKUP_PATIENT = UUID("dddd1111-dddd-dddd-dddd-dddddddd1111")
DELETE_RECORD = UUID("dddd3333-dddd-dddd-dddd-dddddddd3333")


def _make_engine():
    settings = get_settings()
    url = to_async_url(settings.database_url)
    return create_async_engine(url, echo=False, pool_size=2, max_overflow=2)


@pytest_asyncio.fixture(loop_scope="function")
async def session():
    """Fresh engine + session per test with function-scoped loop. Rolls back after each test."""
    engine = _make_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await set_tenant_context(s, DEMO_TENANT)
        yield s
        await s.rollback()
    await engine.dispose()


async def _grant_tool_invoke(session: AsyncSession, principal_id: UUID) -> None:
    """In-transaction: grant tool.invoke to a principal so fn_authorize can allow."""
    role_id = (
        await session.execute(
            text(
                "INSERT INTO roles (tenant_id, name, holder) "
                "VALUES (:t, 'tool_invoker_tmp', 'agent') RETURNING id"
            ),
            {"t": DEMO_TENANT},
        )
    ).scalar_one()
    perm_id = (
        await session.execute(
            text("SELECT id FROM permissions WHERE code = 'tool.invoke'")
        )
    ).scalar_one()
    await session.execute(
        text("INSERT INTO role_permissions (role_id, permission_id) VALUES (:r, :p)"),
        {"r": role_id, "p": perm_id},
    )
    await session.execute(
        text("INSERT INTO principal_roles (principal_id, role_id) VALUES (:p, :r)"),
        {"p": principal_id, "r": role_id},
    )


@pytest.mark.asyncio
async def test_get_agent_by_key(session):
    agent = await get_agent_by_key(session, DEMO_TENANT, "orchestrator")
    assert agent is not None
    assert agent.agent_key == "orchestrator"
    assert agent.trust is TrustTier.TRUSTED
    assert agent.initial_score == 100


@pytest.mark.asyncio
async def test_get_agent_not_found(session):
    agent = await get_agent(session, UUID("00000000-0000-0000-0000-000000000000"))
    assert agent is None


@pytest.mark.asyncio
async def test_create_session_and_run(session):
    sess = await create_session(session, DEMO_TENANT, DEMO_USER)
    assert sess.id is not None
    assert sess.user_id == DEMO_USER
    run = await create_run(session, DEMO_TENANT, sess.id, ORCH)
    assert run.initial_score == 100
    assert run.score_ceiling == 100
    assert run.status == RunState.RUNNING
    assert run.agent_id == ORCH


@pytest.mark.asyncio
async def test_authorize_tool_call_allowed(session):
    await _grant_tool_invoke(session, ORCH)
    sess = await create_session(session, DEMO_TENANT, DEMO_USER)
    run = await create_run(session, DEMO_TENANT, sess.id, ORCH)
    result = await authorize_tool_call(session, run.id, LOOKUP_PATIENT)
    assert result.allowed is True
    assert result.current_score == 100
    assert result.required_score == 40


@pytest.mark.asyncio
async def test_authorize_tool_call_out_of_scope(session):
    sess = await create_session(session, DEMO_TENANT, DEMO_USER)
    run = await create_run(session, DEMO_TENANT, sess.id, DATA_AGENT)
    result = await authorize_tool_call(session, run.id, DELETE_RECORD)
    assert result.allowed is False
    assert "out of scope" in result.reason
    assert result.suggested_penalty == "out_of_scope"


@pytest.mark.asyncio
async def test_score_lifecycle(session):
    sess = await create_session(session, DEMO_TENANT, DEMO_USER)
    run = await create_run(session, DEMO_TENANT, sess.id, ORCH)
    assert await get_current_score(session, run.id) == 100

    # the delta comes from config/default.yml, the single source of the score numbers
    from src.core.scoring import get_scoring

    rule = await get_score_rule(session, DEMO_TENANT, "pii_in_reply")
    assert rule is not None
    assert rule.delta == get_scoring().rules["pii_in_reply"][0]

    await append_score_event(
        session, DEMO_TENANT, run.id, rule.id, rule.delta, reason="pii leaked in reply"
    )
    assert await get_current_score(session, run.id) == 100 + rule.delta


@pytest.mark.asyncio
async def test_vault_entry_crud(session):
    key = await get_or_create_vault_key(session, DEMO_TENANT, "kms-test-key")
    assert key.id is not None

    value_hmac = hmac.new(b"vault-key", b"normalized-name", hashlib.sha256).digest()
    entry = await create_vault_entry(
        session,
        tenant_id=DEMO_TENANT,
        token="tok_name_9f3a21c4e7b0",
        entity_type_code="NAME",
        key_id=key.id,
        value_hmac=value_hmac,
        value_ciphertext=b"encrypted-original",
        nonce=b"unique-nonce",
    )
    assert entry.token == "tok_name_9f3a21c4e7b0"
    assert entry.value_hmac == value_hmac

    by_token = await get_vault_entry_by_token(session, DEMO_TENANT, entry.token)
    assert by_token is not None
    assert by_token.id == entry.id

    by_hmac = await get_vault_entry_by_hmac(session, DEMO_TENANT, "NAME", value_hmac)
    assert by_hmac is not None
    assert by_hmac.id == entry.id


@pytest.mark.asyncio
async def test_receipt_chain(session):
    sess = await create_session(session, DEMO_TENANT, DEMO_USER)
    for i in range(3):
        await insert_receipt(
            session, DEMO_TENANT, sess.id, ReceiptKind.DECISION, {"index": i}
        )
    result = await verify_chain(session, sess.id)
    assert result.ok is True
    assert result.receipt_count == 3
    assert result.broken_at_seq is None
    assert result.reason == "chain intact"


@pytest.mark.asyncio
async def test_authorize_unknown_permission(session):
    result = await authorize(session, ORCH, "fake.permission.that.does.not.exist")
    assert result.allowed is False
    assert result.effect == AuthEffect.DENY
    assert "unknown permission" in result.reason


@pytest.mark.asyncio
async def test_get_tools_for_agent(session):
    tools = await get_agent_tools(session, DATA_AGENT)
    names = {t.name for t in tools}
    assert "lookup_patient" in names
    assert "web_search" in names
    assert "delete_record" not in names
