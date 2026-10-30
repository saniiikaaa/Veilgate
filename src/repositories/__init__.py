"""Repository layer: raw-SQL data access over async SQLAlchemy.

Re-exports the key functions of each submodule so services can import a single
namespace, e.g. ``from src.repositories import get_agent, create_run,
authorize_tool_call, verify_chain``.

Note: ``get_session`` is intentionally not re-exported here because it exists in
two roles — ``db.get_session`` (FastAPI dependency) and ``sessions.get_session``
(fetch a Session row) — so callers should import the one they mean explicitly.
``verify_chain`` and ``get_effective_score`` are defined in more than one module
(they cut across audit/authority and authorization); the canonical ones below come
from ``audit`` and ``authority``.
"""

from src.repositories.agents import (
    get_agent,
    get_agent_by_key,
    get_principal,
    get_user,
    list_agents,
)
from src.repositories.audit import (
    get_receipt_count,
    get_receipts,
    insert_receipt,
    verify_chain,
)
from src.repositories.authority import (
    append_score_event,
    get_current_score,
    get_effective_score,
    get_score_history,
    get_score_rule,
)
from src.repositories.authorization import (
    authorize,
    authorize_tool_call,
    get_run_score,
    request_detokenize,
)
from src.repositories.db import (
    async_session_factory,
    dispose_engine,
    get_session,
    get_session_with_tenant,
    set_tenant_context,
)
from src.repositories.events import (
    create_event,
    create_model_call,
    create_tool_call,
    get_event,
    list_events_for_session,
    update_tool_call_result,
)
from src.repositories.policy import (
    get_active_policies,
    get_entity_types,
    get_entity_types_for_framework,
    get_frameworks,
    get_handling_rules,
    get_permission,
    get_policy_rules,
    get_roles_for_principal,
)
from src.repositories.tools import (
    can_delegate,
    get_agent_tools,
    get_risk_threshold,
    get_tool,
    get_tool_by_name,
    get_tool_entity_access,
)
from src.repositories.vault import (
    create_vault_entry,
    erase_vault_entry,
    get_or_create_vault_key,
    get_vault_entry_by_hmac,
    get_vault_entry_by_token,
)

# Bring the session-row fetcher in too (aliased to avoid the name clash with the
# FastAPI dependency above) for callers that want both from the package root.
from src.repositories.sessions import create_run, create_session, end_session, get_run
from src.repositories.sessions import get_session as get_session_row
from src.repositories.sessions import update_run_status

__all__ = [
    "append_score_event",
    "async_session_factory",
    "authorize",
    "authorize_tool_call",
    "can_delegate",
    "create_event",
    "create_model_call",
    "create_run",
    "create_session",
    "create_tool_call",
    "create_vault_entry",
    "end_session",
    "dispose_engine",
    "erase_vault_entry",
    "get_active_policies",
    "get_agent",
    "get_agent_by_key",
    "get_agent_tools",
    "get_current_score",
    "get_effective_score",
    "get_entity_types",
    "get_entity_types_for_framework",
    "get_event",
    "get_frameworks",
    "get_handling_rules",
    "get_or_create_vault_key",
    "get_permission",
    "get_policy_rules",
    "get_principal",
    "get_receipt_count",
    "get_receipts",
    "get_risk_threshold",
    "get_roles_for_principal",
    "get_run",
    "get_run_score",
    "get_score_history",
    "get_score_rule",
    "get_session",
    "get_session_row",
    "get_session_with_tenant",
    "get_tool",
    "get_tool_by_name",
    "get_tool_entity_access",
    "get_user",
    "get_vault_entry_by_hmac",
    "get_vault_entry_by_token",
    "insert_receipt",
    "list_agents",
    "list_events_for_session",
    "request_detokenize",
    "set_tenant_context",
    "update_run_status",
    "update_tool_call_result",
    "verify_chain",
]
