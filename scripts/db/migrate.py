"""Apply the database schema: the app role (0000) then the full schema.sql.

Run as the owner role via MIGRATION_DATABASE_URL. The application never runs this;
it connects as the restricted guardrail_app role, to which row-level security applies.
"""

import os
import sys
from pathlib import Path

import psycopg2

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_URL = "postgresql://guardrail_owner:ownerpass@localhost:5432/guardrail_v2"

MIGRATIONS_DIR = PROJECT_ROOT / "db" / "migrations"
SCHEMA_FILE = PROJECT_ROOT / "db" / "seeds" / "schema.sql"


def _run_sql(conn, path: Path) -> None:
    with conn.cursor() as cur:
        cur.execute(path.read_text(encoding="utf-8"))
    conn.commit()


def main() -> None:
    url = os.environ.get("MIGRATION_DATABASE_URL", DEFAULT_URL)
    try:
        conn = psycopg2.connect(url)
        _run_sql(conn, MIGRATIONS_DIR / "0000_roles.sql")
        _run_sql(conn, SCHEMA_FILE)
        app_password = os.environ.get("APP_DB_PASSWORD")
        if app_password:
            with conn.cursor() as cur:
                cur.execute("ALTER ROLE guardrail_app WITH LOGIN PASSWORD %s", (app_password,))
            conn.commit()
        conn.close()
    except Exception as exc:  # noqa: BLE001 - report any failure and exit non-zero
        print(f"migrate failed: {exc}", file=sys.stderr)
        sys.exit(1)
    print("schema applied")


if __name__ == "__main__":
    main()
