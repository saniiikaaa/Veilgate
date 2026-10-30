"""Repository functions for the audit receipt chain."""

import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.types import ReceiptKind
from src.repositories.models import Receipt, VerifyResult


async def insert_receipt(
    session: AsyncSession,
    tenant_id: UUID,
    session_id: UUID,
    type: ReceiptKind,
    payload: dict,
    event_id: UUID | None = None,
    run_id: UUID | None = None,
) -> Receipt:
    # seq, prev_hash and hash are set by the fn_receipt_chain trigger.
    result = await session.execute(
        text(
            "INSERT INTO receipts (tenant_id, session_id, type, event_id, run_id, payload) "
            "VALUES (:tid, :sid, :type, :event, :run, CAST(:payload AS jsonb)) RETURNING *"
        ),
        {
            "tid": tenant_id,
            "sid": session_id,
            "type": type,
            "event": event_id,
            "run": run_id,
            "payload": json.dumps(payload),
        },
    )
    return Receipt.model_validate(dict(result.fetchone()._mapping))


async def verify_chain(session: AsyncSession, session_id: UUID) -> VerifyResult:
    result = await session.execute(
        text("SELECT ok, receipt_count, broken_at_seq, reason FROM fn_verify_receipts(:sid)"),
        {"sid": session_id},
    )
    row = result.fetchone()
    return VerifyResult.model_validate(dict(row._mapping))


async def get_receipts(session: AsyncSession, session_id: UUID) -> list[Receipt]:
    result = await session.execute(
        text("SELECT * FROM receipts WHERE session_id = :sid ORDER BY seq"),
        {"sid": session_id},
    )
    return [Receipt.model_validate(dict(row._mapping)) for row in result.fetchall()]


async def get_receipt_count(session: AsyncSession, session_id: UUID) -> int:
    result = await session.execute(
        text("SELECT count(*) FROM receipts WHERE session_id = :sid"),
        {"sid": session_id},
    )
    return int(result.scalar_one())
