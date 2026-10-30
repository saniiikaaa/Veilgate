from enum import StrEnum


class PrincipalKind(StrEnum):
    USER = "user"
    AGENT = "agent"
    SERVICE = "service"


class PrincipalState(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    RETIRED = "retired"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TrustTier(StrEnum):
    UNTRUSTED = "untrusted"
    STANDARD = "standard"
    TRUSTED = "trusted"


class BoundaryKind(StrEnum):
    USER_INPUT = "user_input"
    MODEL_INPUT = "model_input"
    MODEL_OUTPUT = "model_output"
    TOOL_INPUT = "tool_input"
    TOOL_OUTPUT = "tool_output"
    HANDOFF = "handoff"
    USER_OUTPUT = "user_output"


class AuthEffect(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class HandlingAction(StrEnum):
    TOKENIZE = "tokenize"
    BLOCK = "block"
    LOG_ONLY = "log_only"


class EventOutcome(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    TOKENIZED = "tokenized"
    BLOCKED = "blocked"
    LOGGED = "logged"
    APPROVAL_REQUIRED = "approval_required"


class PolicyState(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


class VaultScope(StrEnum):
    SESSION = "session"
    USER = "user"
    TENANT = "tenant"


class KeyState(StrEnum):
    ACTIVE = "active"
    RETIRING = "retiring"
    RETIRED = "retired"


class ReceiptKind(StrEnum):
    DECISION = "decision"
    AUTHORITY = "authority"
    DETOKENIZE = "detokenize"


class ScoreRuleKind(StrEnum):
    PENALTY = "penalty"
    REWARD = "reward"
    ADMIN_RESTORE = "admin_restore"


class AgentType(StrEnum):
    ORCHESTRATOR = "orchestrator"
    WORKER = "worker"
    SCRIPTED = "scripted"
    EXTERNAL = "external"


class RunState(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
