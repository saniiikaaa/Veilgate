"""Read-only API behind the dashboard. Every route needs a sign-in; users see only their own sessions, admins see all."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from src.api.auth import Account, current_account, require_admin
from src.core.config import get_settings
from src.core.scoring import get_scoring
from src.repositories.db import _get_session_factory, set_tenant_context
from src.services import tracing

api_router = APIRouter(prefix="/api", tags=["dashboard"], dependencies=[Depends(current_account)])


class _Db:
    async def __aenter__(self):
        self.db = _get_session_factory()()
        await set_tenant_context(self.db, UUID(get_settings().default_tenant_id))
        return self.db

    async def __aexit__(self, *exc):
        await self.db.close()


async def _own_session(db, session_id: UUID, acct: Account) -> None:
    """404 (not 403) when the session is missing or belongs to someone else, so ids cannot be probed."""
    owner = (await db.execute(text("SELECT user_id FROM sessions WHERE id = :s"), {"s": session_id})).scalar()
    if owner is None or (acct.scope is not None and owner != acct.scope):
        raise HTTPException(404, "no such session")


@api_router.get("/traces")
async def traces(limit: int = 50, acct: Account = Depends(current_account)) -> list[dict[str, Any]]:
    async with _Db() as db:
        return await tracing.list_traces(db, min(max(limit, 1), 200), acct.scope)


@api_router.get("/traces/{session_id}")
async def trace(session_id: UUID, acct: Account = Depends(current_account)) -> dict[str, Any]:
    async with _Db() as db:
        await _own_session(db, session_id, acct)
        result = await tracing.build_trace(db, session_id)
    if result is None:
        raise HTTPException(404, "no such session")
    return result


@api_router.get("/traces/{session_id}/receipts")
async def receipts(session_id: UUID, acct: Account = Depends(current_account)) -> dict[str, Any]:
    async with _Db() as db:
        await _own_session(db, session_id, acct)
        rows = (await db.execute(
            text("SELECT seq, type, payload, prev_hash, hash, created_at FROM receipts WHERE session_id = :s ORDER BY seq"),
            {"s": session_id})).mappings().all()
        chain = (await db.execute(
            text("SELECT ok, receipt_count, broken_at_seq, reason FROM fn_verify_receipts(:s)"), {"s": session_id})).mappings().one()
    return {"verify": dict(chain), "receipts": [{**dict(r), "created_at": r["created_at"].isoformat()} for r in rows]}


_SCOPE = "(CAST(:uid AS uuid) IS NULL OR s.user_id = CAST(:uid AS uuid))"


@api_router.get("/agents")
async def agents(acct: Account = Depends(current_account)) -> list[dict[str, Any]]:
    run = f"agent_runs r JOIN sessions s ON s.id = r.session_id WHERE r.agent_id = a.principal_id AND {_SCOPE}"
    async with _Db() as db:
        rows = (await db.execute(
            text(
                f"""
                SELECT a.agent_key, a.description, a.type, a.trust, a.initial_score, a.score_ceiling,
                  (SELECT count(*) FROM {run}) AS runs,
                  (SELECT coalesce(round(avg(fn_run_score(r.id))), a.initial_score) FROM {run}) AS avg_score,
                  (SELECT coalesce(min(fn_run_score(r.id)), a.initial_score) FROM {run}) AS min_score,
                  (SELECT count(*) FROM tool_calls t JOIN agent_runs r ON r.id = t.run_id JOIN sessions s ON s.id = r.session_id
                     WHERE r.agent_id = a.principal_id AND {_SCOPE}) AS tool_calls,
                  (SELECT count(*) FROM tool_calls t JOIN agent_runs r ON r.id = t.run_id JOIN sessions s ON s.id = r.session_id
                     WHERE r.agent_id = a.principal_id AND t.outcome = 'denied' AND {_SCOPE}) AS denied,
                  (SELECT coalesce(sum(e.entities_found), 0) FROM events e JOIN agent_runs r ON r.id = e.run_id JOIN sessions s ON s.id = r.session_id
                     WHERE r.agent_id = a.principal_id AND {_SCOPE}) AS entities,
                  (SELECT coalesce(sum(m.prompt_tokens + m.completion_tokens), 0) FROM model_calls m JOIN agent_runs r ON r.id = m.run_id
                     JOIN sessions s ON s.id = r.session_id WHERE r.agent_id = a.principal_id AND {_SCOPE}) AS tokens,
                  (SELECT max(r.started_at) FROM {run}) AS last_seen,
                  (SELECT coalesce(array_agg(t.name ORDER BY t.name), '{{}}') FROM agent_tool_grants g JOIN tools t ON t.id = g.tool_id
                     WHERE g.agent_id = a.principal_id) AS tools
                FROM agents a
                WHERE EXISTS (SELECT 1 FROM {run}) OR CAST(:uid AS uuid) IS NULL
                ORDER BY last_seen DESC NULLS LAST, a.agent_key
                """
            ), {"uid": acct.scope})).mappings().all()
    return [{**dict(r), "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None} for r in rows]


@api_router.get("/overview")
async def overview(acct: Account = Depends(current_account)) -> dict[str, Any]:
    ss = f"(SELECT s.id FROM sessions s WHERE {_SCOPE})"
    async with _Db() as db:
        one = (await db.execute(
            text(
                f"""
                SELECT (SELECT count(*) FROM {ss} x) AS sessions,
                  (SELECT count(DISTINCT r.agent_id) FROM agent_runs r WHERE r.session_id IN {ss}) AS agents,
                  (SELECT coalesce(sum(entities_found), 0) FROM events WHERE session_id IN {ss}) AS entities_protected,
                  (SELECT count(*) FROM tool_calls t JOIN agent_runs r ON r.id = t.run_id WHERE t.outcome = 'denied' AND r.session_id IN {ss}) AS tools_denied,
                  (SELECT count(*) FROM events WHERE outcome = 'blocked' AND session_id IN {ss}) AS blocked,
                  (SELECT coalesce(sum(m.prompt_tokens + m.completion_tokens), 0) FROM model_calls m JOIN agent_runs r ON r.id = m.run_id WHERE r.session_id IN {ss}) AS tokens,
                  (SELECT count(*) FROM receipts WHERE session_id IN {ss}) AS receipts
                """
            ), {"uid": acct.scope})).mappings().one()
        by_type = (await db.execute(
            text(f"SELECT ee.entity_type_code AS type, count(*) AS n FROM event_entities ee JOIN events e ON e.id = ee.event_id "
                 f"WHERE e.session_id IN {ss} GROUP BY 1 ORDER BY 2 DESC LIMIT 8"), {"uid": acct.scope})).mappings().all()
        recent = await tracing.list_traces(db, 6, acct.scope)
        extra = (await db.execute(
            text(f"SELECT coalesce(round(avg(e.latency_ms)), 0) AS avg_latency_ms, "
                 f"(SELECT count(DISTINCT s.user_id) FROM sessions s WHERE s.started_at > now() - interval '24 hours' AND {_SCOPE}) AS active_users_24h "
                 f"FROM events e WHERE e.session_id IN {ss}"), {"uid": acct.scope})).mappings().one()
        top_users = [] if acct.scope is not None else sorted(await _user_stats(db, None), key=lambda u: -u["violations"])[:5]
    return {**dict(one), **dict(extra), "entities_by_type": [dict(r) for r in by_type], "recent": recent, "top_users": top_users}


@api_router.get("/policies")
async def policies(_: Account = Depends(require_admin)) -> dict[str, Any]:
    s, sc = get_settings(), get_scoring()
    async with _Db() as db:
        tools = (await db.execute(
            text("SELECT t.name, t.risk, t.min_trust, coalesce(array_agg(a.agent_key ORDER BY a.agent_key) FILTER (WHERE a.agent_key IS NOT NULL), '{}') AS agents "
                 "FROM tools t LEFT JOIN agent_tool_grants g ON g.tool_id = t.id LEFT JOIN agents a ON a.principal_id = g.agent_id "
                 "GROUP BY t.id ORDER BY t.risk, t.name"))).mappings().all()
        entity_types = (await db.execute(
            text("SELECT e.code, e.name, e.sensitivity, coalesce(array_agg(f.framework_code ORDER BY f.framework_code) FILTER (WHERE f.framework_code IS NOT NULL), '{}') AS frameworks "
                 "FROM entity_types e LEFT JOIN entity_type_frameworks f ON f.entity_type_code = e.code GROUP BY e.code ORDER BY e.sensitivity, e.code"))).mappings().all()
    return {
        "score_rules": [{"code": c, "delta": d, "description": x} for c, (d, x) in sc.rules.items()],
        "thresholds": {"block_below": sc.block_below, "warn_below": sc.warn_below, "initial_score": sc.initial_score,
                       "tool_risk": sc.risk_thresholds},
        "allowed_email_domains": [d.strip() for d in s.allowed_email_domains.split(",") if d.strip()],
        "tools": [dict(t) for t in tools],
        "entity_types": [dict(e) for e in entity_types],
        "model": {"provider": s.llm_provider, "judge": s.llm_judge},
    }


# ---------------------------------------------------------------------------------------------------------------------
# attention list, users, trust analytics, detection playground
# ---------------------------------------------------------------------------------------------------------------------
def rating(trust: float, events: int, violations: int, flagged: int) -> int:
    """User rating 0-100: 40% mean final effective agent score, 30% violation-free rate, 30% not-denied/blocked rate."""
    if events <= 0:
        return 100
    v, f = min(1.0, violations / events), min(1.0, flagged / events)
    return round(100 * (0.4 * trust / 100 + 0.3 * (1 - v) + 0.3 * (1 - f)))


_USER_STATS = """
WITH ss AS (SELECT s.id, s.user_id, s.started_at FROM sessions s WHERE (CAST(:uid AS uuid) IS NULL OR s.user_id = CAST(:uid AS uuid))),
ev AS (SELECT ss.user_id, count(*) AS n, count(*) FILTER (WHERE e.outcome IN ('denied','blocked')) AS flagged, avg(e.latency_ms) AS lat
       FROM events e JOIN ss ON ss.id = e.session_id GROUP BY 1),
vi AS (SELECT ss.user_id, count(*) AS n FROM score_ledger l JOIN agent_runs r ON r.id = l.run_id JOIN ss ON ss.id = r.session_id
       WHERE l.delta < 0 GROUP BY 1),
sc AS (SELECT ss.user_id, avg(fn_effective_score(r.id)) AS trust FROM agent_runs r JOIN ss ON ss.id = r.session_id GROUP BY 1),
tk AS (SELECT ss.user_id, coalesce(sum(m.prompt_tokens + m.completion_tokens), 0) AS n FROM model_calls m
       JOIN agent_runs r ON r.id = m.run_id JOIN ss ON ss.id = r.session_id GROUP BY 1)
SELECT u.principal_id AS id, coalesce(u.name, u.email) AS name, u.email, count(DISTINCT ss.id) AS sessions, max(ss.started_at) AS last_active,
       coalesce(max(ev.n), 0) AS events, coalesce(max(ev.flagged), 0) AS flagged, coalesce(max(vi.n), 0) AS violations,
       coalesce(max(sc.trust), 100) AS trust, coalesce(max(tk.n), 0) AS tokens
FROM users u JOIN ss ON ss.user_id = u.principal_id
LEFT JOIN ev ON ev.user_id = u.principal_id LEFT JOIN vi ON vi.user_id = u.principal_id
LEFT JOIN sc ON sc.user_id = u.principal_id LEFT JOIN tk ON tk.user_id = u.principal_id
GROUP BY u.principal_id, u.name, u.email ORDER BY last_active DESC
"""


async def _user_stats(db, uid) -> list[dict[str, Any]]:
    rows = (await db.execute(text(_USER_STATS), {"uid": uid})).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        d["id"] = str(d["id"])
        d["trust"] = round(float(d["trust"]))
        d["rating"] = rating(d["trust"], d["events"], d["violations"], d["flagged"])
        d["last_active"] = d["last_active"].isoformat() if d["last_active"] else None
        out.append(d)
    return out


@api_router.get("/users")
async def users(_: Account = Depends(require_admin)) -> list[dict[str, Any]]:
    async with _Db() as db:
        return await _user_stats(db, None)


@api_router.get("/attention")
async def attention(limit: int = 8, acct: Account = Depends(current_account)) -> list[dict[str, Any]]:
    """Latest violations (score penalties) with who, what and why."""
    async with _Db() as db:
        rows = (await db.execute(
            text(
                "SELECT l.created_at AS at, u.name AS user_name, a.agent_key, sr.code AS rule, l.delta, l.reason, s.id AS session_id "
                "FROM score_ledger l JOIN score_rules sr ON sr.id = l.rule_id JOIN agent_runs r ON r.id = l.run_id "
                "JOIN agents a ON a.principal_id = r.agent_id JOIN sessions s ON s.id = r.session_id JOIN users u ON u.principal_id = s.user_id "
                f"WHERE l.delta < 0 AND {_SCOPE} ORDER BY l.id DESC LIMIT :n"), {"uid": acct.scope, "n": min(max(limit, 1), 50)})).mappings().all()
    return [{**dict(r), "at": r["at"].isoformat(), "session_id": str(r["session_id"])} for r in rows]


@api_router.get("/trust")
async def trust(user: UUID | None = None, acct: Account = Depends(current_account)) -> dict[str, Any]:
    """Rating, violations by rule, and per-session history (score, tokens, violations) for one user."""
    uid = acct.scope if acct.scope is not None else user
    async with _Db() as db:
        stats = (await _user_stats(db, uid))
        sessions = (await db.execute(
            text(
                """
                SELECT s.id, s.started_at,
                  (SELECT min(fn_effective_score(r.id)) FROM agent_runs r WHERE r.session_id = s.id) AS min_score,
                  (SELECT coalesce(sum(m.prompt_tokens + m.completion_tokens), 0) FROM model_calls m JOIN agent_runs r ON r.id = m.run_id WHERE r.session_id = s.id) AS tokens,
                  (SELECT count(*) FROM score_ledger l JOIN agent_runs r ON r.id = l.run_id WHERE r.session_id = s.id AND l.delta < 0) AS violations,
                  (SELECT count(*) FROM events e WHERE e.session_id = s.id) AS events,
                  (SELECT count(*) FROM events e WHERE e.session_id = s.id AND e.outcome IN ('denied','blocked')) AS flagged
                FROM sessions s WHERE (CAST(:uid AS uuid) IS NULL OR s.user_id = CAST(:uid AS uuid)) ORDER BY s.started_at LIMIT 60
                """), {"uid": uid})).mappings().all()
        by_rule = (await db.execute(
            text("SELECT sr.code AS rule, count(*) AS n FROM score_ledger l JOIN score_rules sr ON sr.id = l.rule_id JOIN agent_runs r ON r.id = l.run_id "
                 f"JOIN sessions s ON s.id = r.session_id WHERE l.delta < 0 AND {_SCOPE} GROUP BY 1 ORDER BY 2 DESC"), {"uid": uid})).mappings().all()
    total = {"sessions": 0, "events": 0, "flagged": 0, "violations": 0, "tokens": 0}
    for u in stats:
        for k in total:
            total[k] += u[k]
    trust_avg = sum(u["trust"] * u["sessions"] for u in stats) / max(1, total["sessions"]) if stats else 100
    history = [{"id": str(r["id"]), "at": r["started_at"].isoformat(), "min_score": int(r["min_score"] if r["min_score"] is not None else 100),
                "tokens": int(r["tokens"]), "violations": r["violations"], "events": r["events"],
                "rating": rating(float(r["min_score"] if r["min_score"] is not None else 100), r["events"], r["violations"], r["flagged"])} for r in sessions]
    return {"rating": rating(trust_avg, total["events"], total["violations"], total["flagged"]), "trust": round(trust_avg), **total,
            "who": stats[0]["name"] if len(stats) == 1 else "All users", "history": history, "violations_by_rule": [dict(r) for r in by_rule]}


class DetectIn(BaseModel):
    text: str = Field(max_length=20000)


@api_router.post("/detect")
async def detect_playground(body: DetectIn) -> dict[str, Any]:
    """Try the detector: shows what would be tokenized. Nothing is stored and no model is called."""
    from src.detection import detect as run_detect
    from src.detection import find_injection
    from src.services.hooks import get_crypto

    crypto, tenant = get_crypto(), UUID(get_settings().default_tenant_id)
    ents = run_detect(body.text)
    out, pos, items = [], 0, []
    for e in ents:
        tok = crypto.token(e.type, crypto.value_hmac(tenant, e.type, e.value))
        out += [body.text[pos:e.start], tok]
        pos = e.end
        items.append({"type": e.type, "start": e.start, "end": e.end, "value": e.value, "token": tok, "confidence": e.confidence})
    return {"masked": "".join(out) + body.text[pos:], "entities": items, "injection": find_injection(body.text)}
