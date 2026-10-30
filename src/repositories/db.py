"""Async database connection management.

The application connects as the restricted ``guardrail_app`` role, so row-level
security applies to every session. RLS reads ``app.tenant_id``, which must be set
per session or every tenant-scoped row is hidden (safe-fail).

Note: ``SET app.tenant_id = :param`` cannot be used with the asyncpg driver
(bind parameters are not allowed in SET), so we use ``set_config(...)`` which
is session-scoped when ``is_local`` is false and accepts a parameter.

Engine creation is deferred to first use so that importing this module at
collection time (before any event loop exists) does not create background
asyncio tasks that then fail when the test loop is closed.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import get_settings


def to_async_url(url: str) -> str:
    """Convert a ``postgresql://`` URL to the asyncpg dialect SQLAlchemy expects."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


# ---------------------------------------------------------------------------
# Lazy engine — created on first access so imports never open connections.
# ---------------------------------------------------------------------------

_engine = None
_session_factory = None


def _get_engine():
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        url = to_async_url(settings.database_url)
        _engine = create_async_engine(
            url,
            echo=False,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
        )
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def _get_session_factory():
    _get_engine()  # ensure engine is initialised
    return _session_factory


# Public name used by tests and services.
# Accessing this property initialises the engine on first use.
class _LazySessionFactory:
    """Proxy that initialises the engine on first call."""

    def __call__(self):
        return _get_session_factory()()

    def __aenter__(self):  # allow:  async with async_session_factory() as s:
        return _get_session_factory().__aenter__()  # type: ignore[return-value]

    def __aexit__(self, *args):
        return _get_session_factory().__aexit__(*args)  # type: ignore[return-value]


# Tests and services import this name.
async_session_factory = _LazySessionFactory()


async def dispose_engine() -> None:
    """Dispose the connection pool.  Call this in test teardown or on shutdown."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def set_tenant_context(session: AsyncSession, tenant_id: UUID) -> None:
    """Set the session GUC RLS uses to filter tenant-scoped rows."""
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, false)"),
        {"tid": str(tenant_id)},
    )


async def get_session(tenant_id: UUID | None = None) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yield a session, setting RLS context when given."""
    async with _get_session_factory()() as session:
        if tenant_id is not None:
            await set_tenant_context(session, tenant_id)
        yield session


@asynccontextmanager
async def get_session_with_tenant(tenant_id: UUID):
    """Context manager for scripts/tests: a session with the tenant already set."""
    async with _get_session_factory()() as session:
        await set_tenant_context(session, tenant_id)
        yield session
