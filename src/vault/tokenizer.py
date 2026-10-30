"""Replace detected entities in text with vault tokens (same value -> same token)."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.detection import Entity
from src.repositories import vault as vault_repo
from src.vault.crypto import VaultCrypto


@dataclass(frozen=True)
class Tokenized:
    text: str
    items: list[tuple[Entity, UUID, str]]  # (entity, vault_entry_id, token)


async def tokenize(
    session: AsyncSession,
    crypto: VaultCrypto,
    tenant_id: UUID,
    key_id: UUID,
    text: str,
    entities: list[Entity],
    owner_user_id: UUID | None = None,
) -> Tokenized:
    """Tokenize ``entities`` found in ``text``; entries live at tenant scope so tokens are stable."""
    out: list[str] = []
    items: list[tuple[Entity, UUID, str]] = []
    pos = 0
    for e in entities:
        digest = crypto.value_hmac(tenant_id, e.type, e.value)
        entry = await vault_repo.get_vault_entry_by_hmac(session, tenant_id, e.type, digest)
        if entry is None:
            ciphertext, nonce = crypto.encrypt(e.value)
            entry = await vault_repo.create_vault_entry(
                session, tenant_id, crypto.token(e.type, digest), e.type, key_id, digest,
                scope="tenant", owner_user_id=owner_user_id,
                value_ciphertext=ciphertext, nonce=nonce,
            )
        out.append(text[pos:e.start])
        out.append(entry.token)
        items.append((e, entry.id, entry.token))
        pos = e.end
    out.append(text[pos:])
    return Tokenized("".join(out), items)
