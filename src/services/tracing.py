"""Build a trace from a session: who talked to whom, with every decision, score change and receipt.

Every boundary crossing is an event. We turn each into a span with a source and a destination, so a session reads as
a graph (user, agents, tools, models) and as a time-ordered sequence. The last model output of each agent also becomes
a return edge: agent -> its parent, or agent -> user for the top-level agent.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.scoring import get_scoring
from src.services import authority

# boundary -> (kind label, direction relative to the acting agent)
_EDGE = {
    "user_input": "user_to_agent",
    "handoff": "agent_to_agent",
    "model_input": "agent_to_model",
    "model_output": "model_to_agent",
    "tool_input": "agent_to_tool",
    "tool_output": "tool_to_agent",
    "user_output": "agent_to_user",
}


def _agent(k: str) -> str:
    return f"agent:{k}"


async def list_traces(db: AsyncSession, limit: int = 50, uid: UUID | None = None) -> list[dict[str, Any]]:
    rows = (await db.execute(
        text(
            """
            SELECT s.id, s.started_at, s.ended_at, u.name AS user_name,
              (SELECT count(*) FROM agent_runs r WHERE r.session_id = s.id) AS agents,
              (SELECT count(*) FROM events e WHERE e.session_id = s.id) AS events,
              (SELECT count(*) FROM events e WHERE e.session_id = s.id AND e.outcome IN ('denied','blocked')) AS flagged,
              (SELECT count(*) FROM tool_calls t JOIN agent_runs r ON r.id = t.run_id WHERE r.session_id = s.id) AS tool_calls,
              (SELECT coalesce(sum(m.prompt_tokens + m.completion_tokens), 0) FROM model_calls m JOIN agent_runs r ON r.id = m.run_id
                 WHERE r.session_id = s.id) AS tokens,
              (SELECT min(fn_run_score(r.id)) FROM agent_runs r WHERE r.session_id = s.id) AS min_score,
              (SELECT coalesce(sum(e.entities_found), 0) FROM events e WHERE e.session_id = s.id) AS entities
            FROM sessions s JOIN users u ON u.principal_id = s.user_id
            WHERE (CAST(:uid AS uuid) IS NULL OR s.user_id = CAST(:uid AS uuid))
            ORDER BY s.started_at DESC LIMIT :n
            """
        ),
        {"n": limit, "uid": uid},
    )).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        d["id"] = str(d["id"])
        d["status"] = "flagged" if d["flagged"] else "clean"
        out.append(d)
    return out


async def build_trace(db: AsyncSession, session_id: UUID) -> dict[str, Any] | None:
    sess = (await db.execute(
        text("SELECT s.id, s.started_at, s.ended_at, s.external_ref, u.name AS user_name FROM sessions s "
             "JOIN users u ON u.principal_id = s.user_id WHERE s.id = :s"), {"s": session_id})).mappings().first()
    if sess is None:
        return None
    user = sess["user_name"] or "user"

    runs = (await db.execute(
        text(
            "SELECT r.id, a.agent_key, a.description, a.trust, r.parent_run_id, r.initial_score, r.score_ceiling, r.status, "
            "fn_run_score(r.id) AS score, fn_effective_score(r.id) AS effective "
            "FROM agent_runs r JOIN agents a ON a.principal_id = r.agent_id WHERE r.session_id = :s ORDER BY r.started_at"
        ), {"s": session_id})).mappings().all()
    key_of = {r["id"]: r["agent_key"] for r in runs}

    events = (await db.execute(
        text(
            """
            SELECT e.id, e.run_id, e.boundary, e.outcome, e.entities_found, e.tokenized_text, e.latency_ms, e.created_at,
                   rc.seq, rc.payload,
                   (SELECT array_agg(DISTINCT ee.entity_type_code) FROM event_entities ee WHERE ee.event_id = e.id) AS entity_types,
                   m.prompt_tokens, m.completion_tokens, m.latency_ms AS model_latency_ms,
                   EXISTS (SELECT 1 FROM model_calls mq WHERE mq.request_event_id = e.id) AS sends_to_model
            FROM events e
            LEFT JOIN receipts rc ON rc.event_id = e.id AND rc.type = 'decision'
            LEFT JOIN model_calls m ON m.response_event_id = e.id
            WHERE e.session_id = :s ORDER BY rc.seq NULLS LAST, e.created_at
            """
        ), {"s": session_id})).mappings().all()

    ledger = (await db.execute(
        text(
            "SELECT l.event_id, l.run_id, l.delta, l.reason, sr.code AS rule, l.created_at FROM score_ledger l "
            "JOIN score_rules sr ON sr.id = l.rule_id WHERE l.run_id = ANY(:runs) ORDER BY l.id"
        ), {"runs": [r["id"] for r in runs]})).mappings().all()
    delta_by_event: dict[Any, list[dict]] = {}
    for l in ledger:
        delta_by_event.setdefault(l["event_id"], []).append({"rule": l["rule"], "delta": l["delta"], "reason": l["reason"]})

    parent_key = {r["agent_key"]: key_of.get(r["parent_run_id"]) for r in runs}
    model_of: dict[str, str] = {}  # the model each agent used (callers name it on model hooks)
    for e in events:
        m = (e["payload"] or {}).get("model")
        if m:
            model_of[key_of.get(e["run_id"], "?")] = m
    last_output: dict[str, int] = {}
    spans: list[dict[str, Any]] = []
    for e in events:
        agent = key_of.get(e["run_id"], "?")
        parent = parent_key.get(agent)
        b = e["boundary"]
        payload = e["payload"] or {}
        tool = payload.get("tool")
        mnode = f"model:{model_of.get(agent, 'llm')}"
        src, dst = {
            "user_input": (f"user:{user}", _agent(agent)),
            "handoff": (_agent(parent) if parent else f"user:{user}", _agent(agent)),
            "model_input": (_agent(agent), mnode),
            "model_output": (mnode, _agent(agent)),
            "tool_input": (_agent(agent), f"tool:{tool}"),
            "tool_output": (f"tool:{tool}", _agent(agent)),
            "user_output": (_agent(agent), f"user:{user}"),
        }[b]
        spans.append({
            "seq": e["seq"], "at": e["created_at"].isoformat(), "kind": _EDGE[b], "boundary": b, "agent": agent,
            "from": src, "to": dst, "outcome": e["outcome"], "text": e["tokenized_text"],
            "entities": e["entity_types"] or [], "latency_ms": float(e["latency_ms"] or 0),
            "tool": tool, "reason": payload.get("reason") or payload.get("blocked"), "injection": payload.get("injection"),
            "tokens": (e["prompt_tokens"] or 0) + (e["completion_tokens"] or 0) if e["prompt_tokens"] is not None else None,
            "model_latency_ms": float(e["model_latency_ms"]) if e["model_latency_ms"] is not None else None,
            "score_changes": delta_by_event.get(e["id"], []),
        })
        if b == "model_output":
            last_output[agent] = len(spans) - 1
        if e["sends_to_model"] and b in ("user_input", "handoff"):
            # The prompt hook is also the agent's call to the model; show that hop explicitly.
            spans.append({**spans[-1], "seq": (e["seq"] or 0) + 0.25, "kind": "agent_to_model", "boundary": "model_input",
                          "from": _agent(agent), "to": mnode, "tokens": None, "model_latency_ms": None, "score_changes": [],
                          "synthetic": True})

    # Return edges: each agent's last answer goes back to its parent, or to the user for the top-level agent.
    for agent, idx in last_output.items():
        parent = parent_key.get(agent)
        base = spans[idx]
        spans.append({
            **base, "seq": (base["seq"] or 0) + 0.5, "kind": "agent_to_agent" if parent else "agent_to_user",
            "boundary": "handoff_return" if parent else "user_output", "from": _agent(agent),
            "to": _agent(parent) if parent else f"user:{user}", "tokens": None, "model_latency_ms": None, "score_changes": [],
            "synthetic": True,
        })
    spans.sort(key=lambda s: (s["seq"] is None, s["seq"]))

    # Graph: nodes with live stats, edges aggregated by (from, to, kind).
    nodes: dict[str, dict[str, Any]] = {f"user:{user}": {"id": f"user:{user}", "type": "user", "label": user}}
    for r in runs:
        nodes[_agent(r["agent_key"])] = {
            "id": _agent(r["agent_key"]), "type": "agent", "label": r["agent_key"], "score": r["score"], "effective_score": r["effective"],
            "ceiling": r["score_ceiling"], "status": r["status"], "trust": r["trust"], "parent": parent_key.get(r["agent_key"]),
        }
    edges: dict[tuple, dict[str, Any]] = {}
    for sp in spans:
        for n in (sp["from"], sp["to"]):
            if n not in nodes:
                nodes[n] = {"id": n, "type": n.split(":")[0], "label": n.split(":", 1)[1]}
        k = (sp["from"], sp["to"], sp["kind"])
        e = edges.setdefault(k, {"from": sp["from"], "to": sp["to"], "kind": sp["kind"], "count": 0, "flagged": 0, "tokens": 0, "latency_ms": 0.0})
        e["count"] += 1
        e["flagged"] += sp["outcome"] in ("denied", "blocked")
        e["tokens"] += sp["tokens"] or 0
        e["latency_ms"] += sp["latency_ms"]

    # Each agent's score over the session (what the tool gate saw), plus per-agent counters for the table.
    by_run = {r["id"]: r for r in runs}
    cur = {r["id"]: r["initial_score"] for r in runs}
    series: dict[str, dict[str, Any]] = {r["agent_key"]: {"initial": r["initial_score"], "ceiling": r["score_ceiling"], "points": []} for r in runs}
    for i, l in enumerate(ledger, 1):
        r = by_run[l["run_id"]]
        cur[r["id"]] = max(0, min(r["score_ceiling"], cur[r["id"]] + l["delta"]))
        series[r["agent_key"]]["points"].append({"i": i, "score": cur[r["id"]], "delta": l["delta"], "rule": l["rule"], "reason": l["reason"]})
    violations = {k: sum(1 for p in v["points"] if p["delta"] < 0) for k, v in series.items()}
    for n in nodes.values():
        if n["type"] != "agent":
            continue
        mine = [sp for sp in spans if not sp.get("synthetic") and sp["agent"] == n["label"]]
        n["tool_calls"] = sum(sp["boundary"] == "tool_input" for sp in mine)
        n["denied"] = sum(sp["boundary"] == "tool_input" and sp["outcome"] == "denied" for sp in mine)
        n["violations"] = violations.get(n["label"], 0)
        n["tokens"] = sum(sp["tokens"] or 0 for sp in mine)
    sc = get_scoring()

    verdict = await authority.session_verdict(db, session_id)
    chain = (await db.execute(
        text("SELECT ok, receipt_count, broken_at_seq, reason FROM fn_verify_receipts(:s)"), {"s": session_id})).mappings().one()
    real = [s for s in spans if not s.get("synthetic")]
    return {
        "session": {"id": str(sess["id"]), "user": user, "started_at": sess["started_at"].isoformat(),
                    "ended_at": sess["ended_at"].isoformat() if sess["ended_at"] else None},
        "summary": {
            "agents": len(runs), "spans": len(real), "flagged": sum(s["outcome"] in ("denied", "blocked") for s in real),
            "entities_protected": sum(len(s["entities"]) for s in real),
            "tool_calls": sum(s["boundary"] == "tool_input" for s in real),
            "tokens": sum(s["tokens"] or 0 for s in real),
            "score_events": len(ledger),
        },
        "verdict": {"blocked": verdict.blocked, "reason": verdict.reason, "scores": verdict.scores},
        "receipts": dict(chain),
        "score_series": series,
        "gates": {"block_below": sc.block_below, "warn_below": sc.warn_below, "tool_risk": sc.risk_thresholds},
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "spans": spans,
    }
