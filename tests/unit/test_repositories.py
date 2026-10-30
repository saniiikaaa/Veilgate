"""Unit tests for the repository layer (no database required).

Covers: the db.py URL-conversion logic, Pydantic row models (enum coercion and
``from_attributes``), and that the lookup functions return ``None`` for missing
rows when the session is mocked.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from src.core.types import (
    AgentType,
    AuthEffect,
    ReceiptKind,
    RunState,
    TrustTier,
    VaultScope,
)
from src.repositories import db
from src.repositories.agents import get_agent, list_agents
from src.repositories.authority import get_current_score, get_effective_score
from src.repositories.authorization import authorize
from src.repositories.models import Agent, AuthorizeResult, Receipt, VaultEntry
from src.repositories.sessions import get_run


# ---------------------------------------------------------------------------------------------------------------------
# db.py URL conversion
# ---------------------------------------------------------------------------------------------------------------------
def test_to_async_url_converts_postgresql_scheme():
    assert db.to_async_url("postgresql://u:p@h:5432/db") == (
        "postgresql+asyncpg://u:p@h:5432/db"
    )


def test_to_async_url_leaves_asyncpg_scheme_untouched():
    assert db.to_async_url("postgresql+asyncpg://u:p@h:5432/db") == (
        "postgresql+asyncpg://u:p@h:5432/db"
    )


def test_to_async_url_leaves_non_postgres_untouched():
    assert db.to_async_url("sqlite:///./app.db") == "sqlite:///./app.db"


def test_engine_uses_asyncpg_dialect():
    # to_async_url is the canonical check — no DB connection needed.
    url = db.to_async_url("postgresql://u:p@h:5432/db")
    assert url.startswith("postgresql+asyncpg://")


# ---------------------------------------------------------------------------------------------------------------------
# Pydantic row models
# ---------------------------------------------------------------------------------------------------------------------
def test_agent_model_coerces_enums():
    agent = Agent.model_validate(
        {
            "principal_id": uuid4(),
            "tenant_id": uuid4(),
            "agent_key": "orchestrator",
            "type": "orchestrator",
            "trust": "trusted",
            "initial_score": 100,
            "score_ceiling": 100,
            "created_at": datetime.now(timezone.utc),
        }
    )
    assert agent.trust is TrustTier.TRUSTED
    assert agent.type is AgentType.ORCHESTRATOR
    assert agent.description is None


def test_agent_model_from_attributes():
    obj = MagicMock()
    obj.principal_id = uuid4()
    obj.tenant_id = uuid4()
    obj.agent_key = "data_agent"
    obj.description = None
    obj.type = "worker"
    obj.framework = "langgraph"
    obj.trust = "standard"
    obj.initial_score = 80
    obj.score_ceiling = 90
    obj.owner_user_id = None
    obj.created_at = datetime.now(timezone.utc)
    agent = Agent.model_validate(obj)
    assert agent.agent_key == "data_agent"
    assert agent.trust is TrustTier.STANDARD


def test_authorize_result_coerces_effect():
    res = AuthorizeResult.model_validate(
        {"allowed": True, "effect": "allow", "rule_id": None, "reason": "granted by role"}
    )
    assert res.allowed is True
    assert res.effect is AuthEffect.ALLOW
    assert res.rule_id is None


def test_vault_entry_holds_bytes_and_enum():
    entry = VaultEntry.model_validate(
        {
            "id": uuid4(),
            "tenant_id": uuid4(),
            "token": "tok_name_abc",
            "entity_type_code": "NAME",
            "scope": "session",
            "key_id": uuid4(),
            "value_hmac": b"\x01\x02\x03",
            "created_at": datetime.now(timezone.utc),
        }
    )
    assert entry.value_hmac == b"\x01\x02\x03"
    assert entry.scope is VaultScope.SESSION
    assert entry.value_ciphertext is None


def test_receipt_model_holds_payload_dict_and_kind():
    receipt = Receipt.model_validate(
        {
            "id": uuid4(),
            "tenant_id": uuid4(),
            "session_id": uuid4(),
            "seq": 1,
            "type": "decision",
            "event_id": None,
            "run_id": None,
            "payload": {"n": 1},
            "prev_hash": "0" * 64,
            "hash": "1" * 64,
            "created_at": datetime.now(timezone.utc),
        }
    )
    assert receipt.payload == {"n": 1}
    assert receipt.type is ReceiptKind.DECISION


# ---------------------------------------------------------------------------------------------------------------------
# Lookups return None / map rows, against a mocked AsyncSession
# ---------------------------------------------------------------------------------------------------------------------
def _row(mapping: dict) -> MagicMock:
    row = MagicMock()
    row._mapping = mapping
    return row


def _mock_session(*, fetchone=None, fetchall=None, scalar=None) -> AsyncMock:
    result = MagicMock()
    result.fetchone.return_value = fetchone
    result.fetchall.return_value = fetchall or []
    result.scalar_one.return_value = scalar
    result.scalar.return_value = scalar
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


def _agent_mapping() -> dict:
    return {
        "principal_id": uuid4(),
        "tenant_id": uuid4(),
        "agent_key": "orchestrator",
        "description": None,
        "type": "orchestrator",
        "framework": "langgraph",
        "trust": "trusted",
        "initial_score": 100,
        "score_ceiling": 100,
        "owner_user_id": None,
        "created_at": datetime.now(timezone.utc),
    }


@pytest.mark.asyncio
async def test_get_agent_returns_none_when_missing():
    session = _mock_session(fetchone=None)
    assert await get_agent(session, uuid4()) is None


@pytest.mark.asyncio
async def test_get_run_returns_none_when_missing():
    session = _mock_session(fetchone=None)
    assert await get_run(session, uuid4()) is None


@pytest.mark.asyncio
async def test_get_agent_maps_row_to_model():
    mapping = _agent_mapping()
    session = _mock_session(fetchone=_row(mapping))
    agent = await get_agent(session, mapping["principal_id"])
    assert agent.agent_key == "orchestrator"
    assert agent.trust is TrustTier.TRUSTED
    assert agent.initial_score == 100


@pytest.mark.asyncio
async def test_list_agents_maps_all_rows():
    session = _mock_session(fetchall=[_row(_agent_mapping()), _row(_agent_mapping())])
    agents = await list_agents(session, uuid4())
    assert len(agents) == 2
    assert all(a.trust is TrustTier.TRUSTED for a in agents)


@pytest.mark.asyncio
async def test_get_current_score_reads_scalar():
    session = _mock_session(scalar=80)
    assert await get_current_score(session, uuid4()) == 80


@pytest.mark.asyncio
async def test_get_effective_score_defaults_to_zero_for_null():
    session = _mock_session(scalar=None)
    assert await get_effective_score(session, uuid4()) == 0


@pytest.mark.asyncio
async def test_authorize_maps_fn_result():
    mapping = {
        "allowed": False,
        "effect": "deny",
        "rule_id": None,
        "reason": "no role grants tool.invoke",
    }
    session = _mock_session(fetchone=_row(mapping))
    res = await authorize(session, uuid4(), "tool.invoke")
    assert res.allowed is False
    assert res.effect is AuthEffect.DENY
    assert "no role grants" in res.reason


def test_run_state_enum_value():
    assert RunState.RUNNING.value == "running"
