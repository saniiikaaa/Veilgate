"""Apply the seed data files (db/seeds/0*.sql) in numeric order.

Run as the owner role via MIGRATION_DATABASE_URL, after migrate.py.
schema.sql is the source of truth for the schema; these files only add reference
and demo data and are safe to re-run (every statement uses ON CONFLICT DO NOTHING).
"""

import os
import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.core.scoring import sync_sync  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_URL = "postgresql://guardrail_owner:ownerpass@localhost:5432/guardrail_v2"
SEEDS_DIR = PROJECT_ROOT / "db" / "seeds"
DEFAULT_TENANT_ID = "11111111-1111-1111-1111-111111111111"


def _run_sql(conn, path: Path) -> None:
    with conn.cursor() as cur:
        cur.execute(path.read_text(encoding="utf-8"))
    conn.commit()


def main() -> None:
    url = os.environ.get("MIGRATION_DATABASE_URL", DEFAULT_URL)
    is_production = os.environ.get("APP_ENV", "").strip().lower() in {"prod", "production"}
    seed_files = sorted(SEEDS_DIR.glob("0*.sql"))
    if is_production:
        seed_files = [f for f in seed_files if f.name not in {"004_demo_tenant.sql", "005_demo_tools.sql"}]
    try:
        conn = psycopg2.connect(url)
        if is_production:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO tenants (id, name, settings) VALUES (%s, %s, '{}'::jsonb) "
                    "ON CONFLICT (id) DO NOTHING",
                    (DEFAULT_TENANT_ID, "Veilgate Production"),
                )
            conn.commit()
        for path in seed_files:
            _run_sql(conn, path)
        sync_sync(conn, DEFAULT_TENANT_ID)
        conn.close()
    except Exception as exc:  # noqa: BLE001 - report any failure and exit non-zero
        print(f"seed failed: {exc}", file=sys.stderr)
        sys.exit(1)
    print("seeds applied")


if __name__ == "__main__":
    main()
