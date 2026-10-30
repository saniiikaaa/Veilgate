"""
Top-level pytest configuration for the Warden test suite.

The tests run against their own database (``<dbname>_test``) so they never write into the database you demo from.
It is created and migrated on first use; the seeds and score config are re-applied every run.

pytest-asyncio 0.24 deprecates redefining event_loop; the session loop scope comes from pyproject.toml.
"""

import os
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg2
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
TENANT = "11111111-1111-1111-1111-111111111111"


def _with_db(url: str, dbname: str) -> str:
    p = urlparse(url)
    return urlunparse(p._replace(path=f"/{dbname}"))


def _prepare_test_database() -> None:
    env = {**dotenv_values(ROOT / ".env"), **os.environ}
    owner_url, app_url = env.get("MIGRATION_DATABASE_URL"), env.get("DATABASE_URL")
    if not owner_url or not app_url:
        return  # unit tests only; integration tests will fail loudly on their own
    base = urlparse(owner_url).path.lstrip("/")
    test_db = base if base.endswith("_test") else f"{base}_test"
    owner_test = _with_db(owner_url, test_db)

    admin = psycopg2.connect(_with_db(owner_url, "postgres"))
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (test_db,))
        fresh = cur.fetchone() is None
        if fresh:
            cur.execute(f'CREATE DATABASE "{test_db}"')
    admin.close()

    conn = psycopg2.connect(owner_test)
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.tenants')")
        if cur.fetchone()[0] is None:
            for f in (ROOT / "db/migrations/0000_roles.sql", ROOT / "db/seeds/schema.sql"):
                cur.execute(f.read_text(encoding="utf-8"))
        conn.commit()
        for f in sorted((ROOT / "db/seeds").glob("0*.sql")):
            cur.execute(f.read_text(encoding="utf-8"))
        conn.commit()
    from src.core.scoring import sync_sync

    sync_sync(conn, TENANT)
    conn.close()

    os.environ["DATABASE_URL"] = _with_db(app_url, test_db)
    os.environ["MIGRATION_DATABASE_URL"] = owner_test


os.environ["LLM_JUDGE"] = "off"  # tests never call a model; judge tests switch it on with a stand-in

_prepare_test_database()
