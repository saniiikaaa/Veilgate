"""Repository functions for the vault: keys and tokenized entries."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.types import VaultScope
from src.repositories.models import VaultEntry, VaultKey


async def get_or_create_vault_key(
    session: AsyncSession, tenant_id: UUID, kms_ref: str
) -> VaultKey:
    # vault_keys has no unique constraint on (tenant_id, kms_ref), so ON CONFLICT
    # could never dedupe (the PK is a random UUID). Get-then-create instead.
    result = await session.execute(
        text(
            "SELECT * FROM vault_keys WHERE tenant_id = :tid AND kms_ref = :ref "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"tid": tenant_id, "ref": kms_ref},
    )
    row = result.fetchone()
    if row is not None:
        return VaultKey.model_validate(dict(row._mapping))
    result = await session.execute(
        text("INSERT INTO vault_keys (tenant_id, kms_ref) VALUES (:tid, :ref) RETURNING *"),
        {"tid": tenant_id, "ref": kms_ref},
    )
    return VaultKey.model_validate(dict(result.fetchone()._mapping))


async def create_vault_entry(
    session: AsyncSession,
    tenant_id: UUID,
    token: str,
    entity_type_code: str,
    key_id: UUID,
    value_hmac: bytes,
    scope: VaultScope = VaultScope.SESSION,
    scope_ref: UUID | None = None,
    owner_user_id: UUID | None = None,
    subject_ref: str | None = None,
    value_ciphertext: bytes | None = None,
    nonce: bytes | None = None,
    created_by_event_id: UUID | None = None,
    expires_at=None,
) -> VaultEntry:
    result = await session.execute(
        text(
            "INSERT INTO vault_entries (tenant_id, token, entity_type_code, scope, "
            "scope_ref, owner_user_id, subject_ref, value_ciphertext, nonce, key_id, "
            "value_hmac, created_by_event_id, expires_at) "
            "VALUES (:tid, :token, :etype, :scope, :sref, :owner, :subject, :cipher, "
            ":nonce, :key, :hmac, :ev, :exp) RETURNING *"
        ),
        {
            "tid": tenant_id,
            "token": token,
            "etype": entity_type_code,
            "scope": scope,
            "sref": scope_ref,
            "owner": owner_user_id,
            "subject": subject_ref,
            "cipher": value_ciphertext,
            "nonce": nonce,
            "key": key_id,
            "hmac": value_hmac,
            "ev": created_by_event_id,
            "exp": expires_at,
        },
    )
    return VaultEntry.model_validate(dict(result.fetchone()._mapping))


async def get_vault_entry_by_token(
    session: AsyncSession, tenant_id: UUID, token: str
) -> VaultEntry | None:
    result = await session.execute(
        text("SELECT * FROM vault_entries WHERE tenant_id = :tid AND token = :token"),
        {"tid": tenant_id, "token": token},
    )
    row = result.fetchone()
    if row is None:
        return None
    return VaultEntry.model_validate(dict(row._mapping))


async def get_vault_entry_by_hmac(
    session: AsyncSession, tenant_id: UUID, entity_type_code: str, value_hmac: bytes
) -> VaultEntry | None:
    result = await session.execute(
        text(
            "SELECT * FROM vault_entries WHERE tenant_id = :tid "
            "AND entity_type_code = :etype AND value_hmac = :hmac"
        ),
        {"tid": tenant_id, "etype": entity_type_code, "hmac": value_hmac},
    )
    row = result.fetchone()
    if row is None:
        return None
    return VaultEntry.model_validate(dict(row._mapping))


async def erase_vault_entry(session: AsyncSession, entry_id: UUID) -> None:
    # Crypto-shredding: the CHECK (erased_at IS NULL) = (value_ciphertext IS NOT NULL)
    # means the ciphertext and the timestamp must be cleared together.
    await session.execute(
        text(
            "UPDATE vault_entries SET erased_at = now(), value_ciphertext = NULL, "
            "nonce = NULL WHERE id = :id"
        ),
        {"id": entry_id},
    )
