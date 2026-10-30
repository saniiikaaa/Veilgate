"""FastAPI dependency injection functions."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings, get_settings
from src.repositories.db import async_session_factory


def get_settings_dep() -> Settings:
    """Return the app Settings instance (injectable in tests)."""
    return get_settings()


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a raw AsyncSession.

    Tenant context is NOT set here — that requires a tenant_id from auth
    (Task 12). Services that need RLS should call set_tenant_context themselves.
    """
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
