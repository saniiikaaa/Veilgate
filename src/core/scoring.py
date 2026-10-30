"""Authority and tool-gate numbers, read from config/default.yml (override the path with VEILGATE_CONFIG).

The file is the single source of truth: ``sync_*`` writes it into score_rules and risk_thresholds, which the database
functions read, so changing a number means editing the YAML and restarting (or re-running the seed).
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "default.yml"


@dataclass(frozen=True)
class Scoring:
    initial_score: int
    block_below: int
    warn_below: int
    rules: dict[str, tuple[int, str]]  # code -> (delta, description)
    risk_thresholds: dict[str, int]


@lru_cache
def raw_config() -> dict[str, Any]:
    path = Path(os.environ.get("VEILGATE_CONFIG", DEFAULT_PATH))
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@lru_cache
def get_scoring() -> Scoring:
    raw = raw_config()
    auth = raw["authority"]
    rules = {code: (int(r["delta"]), r.get("description", "")) for code, r in auth["rules"].items()}
    return Scoring(
        initial_score=int(auth["initial_score"]),
        block_below=int(auth["block_below"]),
        warn_below=int(auth["warn_below"]),
        rules=rules,
        risk_thresholds={k: int(v) for k, v in raw["tools"]["risk_thresholds"].items()},
    )


_RULE_SQL = (
    "INSERT INTO score_rules (tenant_id, code, kind, delta, description) VALUES (%(t)s, %(c)s, %(k)s, %(d)s, %(x)s) "
    "ON CONFLICT (tenant_id, code) DO UPDATE SET kind = EXCLUDED.kind, delta = EXCLUDED.delta, description = EXCLUDED.description"
)
_RISK_SQL = (
    "INSERT INTO risk_thresholds (tenant_id, risk, min_score) VALUES (%(t)s, %(r)s, %(m)s) "
    "ON CONFLICT (tenant_id, risk) DO UPDATE SET min_score = EXCLUDED.min_score"
)


def sync_rows(tenant_id: UUID | str) -> list[tuple[str, dict[str, Any]]]:
    """(sql, params) pairs that write the config into the database (psycopg-style named parameters)."""
    sc = get_scoring()
    rows: list[tuple[str, dict[str, Any]]] = []
    for code, (delta, desc) in sc.rules.items():
        rows.append((_RULE_SQL, {"t": str(tenant_id), "c": code, "k": "penalty" if delta < 0 else "reward", "d": delta, "x": desc}))
    for risk, minimum in sc.risk_thresholds.items():
        rows.append((_RISK_SQL, {"t": str(tenant_id), "r": risk, "m": minimum}))
    return rows


def sync_sync(conn: Any, tenant_id: UUID | str) -> None:
    """Write the config using a psycopg2 connection (seed script, tests). Commits."""
    with conn.cursor() as cur:
        for sql, params in sync_rows(tenant_id):
            cur.execute(sql, params)
    conn.commit()


async def sync_async(db: Any, tenant_id: UUID) -> None:
    """Write the config using an AsyncSession that already has the tenant context set. Caller commits."""
    from sqlalchemy import text

    for sql, params in sync_rows(tenant_id):
        await db.execute(text(sql.replace("%(", ":").replace(")s", "")), params)
