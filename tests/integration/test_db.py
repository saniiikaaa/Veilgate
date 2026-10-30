"""Integration tests for the Warden database (PostgreSQL, asyncpg).

These tests assume a running Postgres with the schema and seed data applied
(scripts/db/migrate.py then scripts/db/seed.py). They connect as the restricted
``guardrail_app`` role, so row-level security applies.
"""

import os

import asyncpg
import pytest

DEFAULT_URL = "postgresql://guardrail_app:apppass@localhost:5432/guardrail_v2"

DEMO_TENANT = "11111111-1111-1111-1111-111111111111"
DEMO_USER = "22222222-2222-2222-2222-222222222222"
OTHER_TENANT = "33333333-3333-3333-3333-333333333333"
OTHER_PRINCIPAL = "33333333-3333-3333-3333-333333333330"


def _url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


async def _set_tenant(conn, tenant: str) -> None:
    # set_config(value, is_local=false) sets a session GUC; RLS reads current_setting.
    await conn.execute("SELECT set_config('app.tenant_id', $1, false)", tenant)


@pytest.mark.asyncio
async def test_can_connect():
    conn = await asyncpg.connect(_url())
    try:
        val = await conn.fetchval("SELECT 1")
        assert val == 1
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_rls_filters_other_tenant():
    conn = await asyncpg.connect(_url())
    try:
        await conn.execute("BEGIN")
        try:
            # tenants has no RLS: a second tenant is visible to anyone.
            await conn.execute(
                "INSERT INTO tenants (id, name, settings) VALUES ($1, $2, '{}') "
                "ON CONFLICT (id) DO NOTHING",
                OTHER_TENANT,
                "Other Tenant",
            )
            # create a user in the *other* tenant (WITH CHECK needs app.tenant_id)
            await _set_tenant(conn, OTHER_TENANT)
            await conn.execute(
                "INSERT INTO principals (id, tenant_id, kind, display_name) "
                "VALUES ($1, $2, 'user', 'Other User') ON CONFLICT (id) DO NOTHING",
                OTHER_PRINCIPAL,
                OTHER_TENANT,
            )
            await conn.execute(
                "INSERT INTO users (principal_id, tenant_id, email, name) "
                "VALUES ($1, $2, $3, 'Other User') ON CONFLICT (principal_id) DO NOTHING",
                OTHER_PRINCIPAL,
                OTHER_TENANT,
                "other@other.test",
            )
            # switch to the demo tenant: the other tenant's user must be hidden by RLS.
            # (The hooks auto-provision users in the demo tenant, so assert on the emails, not a row count.)
            await _set_tenant(conn, DEMO_TENANT)
            emails = [r["email"] for r in await conn.fetch("SELECT email FROM users")]
            assert "demo@acme.health" in emails
            assert "other@other.test" not in emails, "RLS should hide the other tenant's user"
        finally:
            await conn.execute("ROLLBACK")
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_fn_authorize_unknown_principal():
    conn = await asyncpg.connect(_url())
    try:
        row = await conn.fetchrow(
            "SELECT * FROM fn_authorize('00000000-0000-0000-0000-000000000000'::uuid, 'tool.invoke')"
        )
        assert row["allowed"] is False
        assert row["effect"] == "deny"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_fn_verify_receipts_empty():
    conn = await asyncpg.connect(_url())
    try:
        await conn.execute("BEGIN")
        try:
            await _set_tenant(conn, DEMO_TENANT)
            session_id = await conn.fetchval(
                "INSERT INTO sessions (tenant_id, user_id) VALUES ($1, $2) RETURNING id",
                DEMO_TENANT,
                DEMO_USER,
            )
            row = await conn.fetchrow(
                "SELECT ok, receipt_count FROM fn_verify_receipts($1)", session_id
            )
            assert row["ok"] is True
            assert row["receipt_count"] == 0
        finally:
            await conn.execute("ROLLBACK")
    finally:
        await conn.close()
