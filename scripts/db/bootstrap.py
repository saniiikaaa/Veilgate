"""Container start-up: wait for Postgres, create the schema once, then (re)apply seeds and the score config.

Safe to run on every start: the schema is only created when the database is empty; seeds are idempotent.
"""

import importlib.util
import os
import sys
import time
from pathlib import Path

import psycopg2

HERE = Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, str(HERE / f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    url = os.environ["MIGRATION_DATABASE_URL"]
    for attempt in range(40):
        try:
            conn = psycopg2.connect(url)
            break
        except psycopg2.OperationalError as exc:
            print(f"waiting for the database ({exc.__class__.__name__}) ...", file=sys.stderr)
            time.sleep(1.5)
    else:
        sys.exit("database never came up")
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.tenants')")
        fresh = cur.fetchone()[0] is None
    conn.close()
    if fresh:
        print("empty database: creating the schema")
        _load("migrate").main()
    _load("seed").main()


if __name__ == "__main__":
    main()
