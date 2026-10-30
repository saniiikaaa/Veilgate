"""Drop and recreate the database, then apply schema and seeds.

Connects to the maintenance 'postgres' database (same owner credentials, different
dbname) to DROP/CREATE guardrail_v2, then reuses migrate.py and seed.py. Destructive:
prints a warning before the drop.
"""

import importlib.util
import os
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg2

HERE = Path(__file__).resolve().parent
DEFAULT_TARGET = "postgresql://guardrail_owner:ownerpass@localhost:5432/guardrail_v2"
DB_NAME = "guardrail_v2"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Import the sibling scripts by file path so their names cannot clash.
migrate = _load_module("warden_migrate", HERE / "migrate.py")
seed = _load_module("warden_seed", HERE / "seed.py")


def _maintenance_url(target: str) -> str:
    """Swap the dbname in a target URL to 'postgres' for DROP/CREATE."""
    parsed = urlparse(target)
    return urlunparse(parsed._replace(path="/postgres"))


def main() -> None:
    target_url = os.environ.get("MIGRATION_DATABASE_URL", DEFAULT_TARGET)
    maint_url = _maintenance_url(target_url)

    print(f"WARNING: dropping and recreating database {DB_NAME!r}; all data will be lost.")
    conn = psycopg2.connect(maint_url)
    conn.autocommit = True  # DROP/CREATE DATABASE cannot run inside a transaction
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)")
            cur.execute(f"CREATE DATABASE {DB_NAME}")
    finally:
        conn.close()

    migrate.main()  # connects to the freshly created guardrail_v2
    seed.main()
    print("database reset complete")


if __name__ == "__main__":
    main()
