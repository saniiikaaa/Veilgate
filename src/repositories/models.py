"""Pydantic row models for the Warden database.

These are plain data containers that mirror the rows defined in
``db/seeds/schema.sql``. They are NOT ORM models — the schema is the single
source of truth and we run raw SQL against it. Each model is created from a
row mapping via ``model_validate(dict(row._mapping))``.

Enum columns map to the ``StrEnum`` types in ``src.core.types``. asyncpg
returns PostgreSQL enums as ``str`` and jsonb as ``dict``, both of which
Pydantic validates directly.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from src.core.types import (
    AgentType,
    AuthEffect,
    BoundaryKind,
    EventOutcome,
    HandlingAction,
    KeyState,
    PrincipalKind,
    PrincipalState,
    ReceiptKind,
    RiskLevel,
    RunState,
    ScoreRuleKind,
    TrustTier,
    VaultScope,
)


class RowModel(BaseModel):
    """Base for every row model — lets it be built from a SQLAlchemy Row."""

    # Column names such as ``model_id`` would otherwise trip Pydantic's reserved
    # ``model_`` namespace; our models only mirror database columns, so opt out.
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())


# ---------------------------------------------------------------------------------------------------------------------
# 1. Tenancy and principals
# ---------------------------------------------------------------------------------------------------------------------
class Tenant(RowModel):
    id: UUID
    name: str
    settings: dict
    created_at: datetime


class Principal(RowModel):
    id: UUID
    tenant_id: UUID
    kind: PrincipalKind
    display_name: str
    status: PrincipalState
    created_at: datetime


class User(RowModel):
    principal_id: UUID
    tenant_id: UUID
    email: str
    external_auth_id: str | None = None
    name: str | None = None
    created_at: datetime


class Agent(RowModel):
    principal_id: UUID
    tenant_id: UUID
    agent_key: str
    description: str | None = None
    type: AgentType
    framework: str | None = None
    trust: TrustTier
    initial_score: int
    score_ceiling: int
    owner_user_id: UUID | None = None
    created_at: datetime


# ---------------------------------------------------------------------------------------------------------------------
# 5. Runtime
# ---------------------------------------------------------------------------------------------------------------------
class Session(RowModel):
    id: UUID
    tenant_id: UUID
    user_id: UUID
    channel: str | None = None
    external_ref: str | None = None
    started_at: datetime
    ended_at: datetime | None = None


class AgentRun(RowModel):
    id: UUID
    tenant_id: UUID
    session_id: UUID
    agent_id: UUID
    parent_run_id: UUID | None = None
    initial_score: int
    score_ceiling: int
    status: RunState
    started_at: datetime
    ended_at: datetime | None = None


class Event(RowModel):
    id: UUID
    tenant_id: UUID
    session_id: UUID
    run_id: UUID | None = None
    boundary: BoundaryKind
    outcome: EventOutcome
    policy_rule_id: UUID | None = None
    entities_found: int
    tokenized_text: str | None = None
    text_sha256: str | None = None
    latency_ms: float | None = None
    created_at: datetime


class ToolCall(RowModel):
    id: UUID
    tenant_id: UUID
    run_id: UUID
    tool_id: UUID
    request_event_id: UUID
    result_event_id: UUID | None = None
    args_tokenized: dict | None = None
    outcome: EventOutcome
    required_score: int | None = None
    score_at_call: int | None = None
    detokenized: bool
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class ModelCall(RowModel):
    id: UUID
    tenant_id: UUID
    run_id: UUID
    model_id: UUID | None = None
    request_event_id: UUID | None = None
    response_event_id: UUID | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    tokens_estimated: bool
    latency_ms: float | None = None
    cost: float | None = None
    created_at: datetime


# ---------------------------------------------------------------------------------------------------------------------
# 6. Vault
# ---------------------------------------------------------------------------------------------------------------------
class VaultKey(RowModel):
    id: UUID
    tenant_id: UUID
    kms_ref: str
    algorithm: str
    status: KeyState
    created_at: datetime
    rotated_at: datetime | None = None


class VaultEntry(RowModel):
    id: UUID
    tenant_id: UUID
    token: str
    entity_type_code: str
    scope: VaultScope
    scope_ref: UUID | None = None
    owner_user_id: UUID | None = None
    subject_ref: str | None = None
    value_ciphertext: bytes | None = None
    nonce: bytes | None = None
    key_id: UUID
    value_hmac: bytes
    created_by_event_id: UUID | None = None
    created_at: datetime
    expires_at: datetime | None = None
    erased_at: datetime | None = None


# ---------------------------------------------------------------------------------------------------------------------
# 7. Authority score
# ---------------------------------------------------------------------------------------------------------------------
class ScoreRule(RowModel):
    id: UUID
    tenant_id: UUID
    code: str
    kind: ScoreRuleKind
    delta: int
    description: str | None = None


class ScoreLedger(RowModel):
    id: int
    tenant_id: UUID
    run_id: UUID
    rule_id: UUID
    delta: int
    reason: str | None = None
    event_id: UUID | None = None
    admin_audit_id: UUID | None = None
    created_at: datetime


# ---------------------------------------------------------------------------------------------------------------------
# 8. Audit / receipts
# ---------------------------------------------------------------------------------------------------------------------
class Receipt(RowModel):
    id: UUID
    tenant_id: UUID
    session_id: UUID
    seq: int
    type: ReceiptKind
    event_id: UUID | None = None
    run_id: UUID | None = None
    payload: dict
    prev_hash: str
    hash: str
    created_at: datetime


# ---------------------------------------------------------------------------------------------------------------------
# 4. Registry
# ---------------------------------------------------------------------------------------------------------------------
class Tool(RowModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None = None
    risk: RiskLevel
    min_trust: TrustTier
    requires_clear_input: bool
    returns_sensitive: bool
    on_undeclared: str
    status: PrincipalState
    version: int
    arg_schema: dict | None = None
    owner_user_id: UUID | None = None
    created_at: datetime


# ---------------------------------------------------------------------------------------------------------------------
# 2. Permissions / catalog
# ---------------------------------------------------------------------------------------------------------------------
class Permission(RowModel):
    id: UUID
    code: str
    resource_type: str | None = None
    description: str


class Framework(RowModel):
    code: str
    name: str
    description: str | None = None


class EntityType(RowModel):
    code: str
    name: str
    sensitivity: RiskLevel
    description: str | None = None


class HandlingRule(RowModel):
    id: UUID
    tenant_id: UUID
    entity_type_code: str | None = None
    boundary: BoundaryKind | None = None
    action: HandlingAction
    priority: int


# ---------------------------------------------------------------------------------------------------------------------
# Results returned by the SQL guard functions (section 10 of schema.sql)
# ---------------------------------------------------------------------------------------------------------------------
class AuthorizeResult(RowModel):
    allowed: bool
    effect: AuthEffect
    rule_id: UUID | None = None
    reason: str


class ToolCallAuthResult(RowModel):
    allowed: bool
    reason: str
    required_score: int | None = None
    current_score: int | None = None
    rule_id: UUID | None = None
    suggested_penalty: str | None = None


class DetokenizeResult(RowModel):
    allowed: bool
    reason: str
    value_ciphertext: bytes | None = None
    nonce: bytes | None = None
    key_id: UUID | None = None


class VerifyResult(RowModel):
    ok: bool
    receipt_count: int
    broken_at_seq: int | None = None
    reason: str
