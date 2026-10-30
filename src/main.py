"""Warden FastAPI application entry point."""

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from uuid import UUID

from sqlalchemy import text

from src.core import scoring
from src.core import auth
from src.core.config import get_settings
from src.core.errors import AuthorityError, PolicyDenyError, VaultError, WardenError
from src.core.logging import setup_logging
from src.repositories.db import async_session_factory, dispose_engine, set_tenant_context

# Initialise structured logging at module load time so all subsequent imports
# and log calls use the configured processors.
setup_logging()

logger = structlog.get_logger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup: verify DB is reachable. Shutdown: dispose the connection pool."""
    if settings.is_production:
        missing = [
            name
            for name, value in (
                ("HOOK_API_KEY", settings.hook_api_key),
                ("VAULT_KEY_HEX", settings.vault_key_hex),
                ("AUTH_KEY_HEX", settings.auth_key_hex),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"Missing required production secrets: {', '.join(missing)}")
        from src.services.hooks import get_crypto

        get_crypto()
        auth.validate_secret()

    # Startup
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
            tenant = UUID(settings.default_tenant_id)
            await set_tenant_context(session, tenant)
            await scoring.sync_async(session, tenant)  # config/default.yml is the source of the score numbers
            await session.commit()
            await ensure_demo_accounts()
        logger.info("warden.startup", port=settings.governance_port, env=settings.app_env)
    except Exception as exc:
        logger.error("warden.startup.db_unreachable", error=str(exc))

    yield

    # Shutdown
    await dispose_engine()
    logger.info("warden.shutdown")


app = FastAPI(
    title="Warden",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Exception handlers  (most-specific first)
# ---------------------------------------------------------------------------
from src.api.errors import (  # noqa: E402 — after app creation to avoid circular import
    internal_error_handler,
    warden_authority_handler,
    warden_generic_handler,
    warden_policy_deny_handler,
    warden_vault_handler,
)

app.add_exception_handler(PolicyDenyError, warden_policy_deny_handler)  # type: ignore[arg-type]
app.add_exception_handler(VaultError, warden_vault_handler)  # type: ignore[arg-type]
app.add_exception_handler(AuthorityError, warden_authority_handler)  # type: ignore[arg-type]
app.add_exception_handler(WardenError, warden_generic_handler)  # type: ignore[arg-type]
app.add_exception_handler(Exception, internal_error_handler)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
from src.api.admin import admin_router  # noqa: E402
from src.api.health import health_router  # noqa: E402
from src.api.auth import auth_router, ensure_demo_accounts  # noqa: E402
from src.api.hooks import hooks_router  # noqa: E402
from src.api.traces import api_router  # noqa: E402

app.include_router(health_router, prefix="")
app.include_router(hooks_router)
app.include_router(auth_router)
app.include_router(api_router)
app.include_router(admin_router, prefix="/admin")

# The dashboard (static files, same origin as the API so the sign-in cookie just works).
from pathlib import Path  # noqa: E402

from fastapi.responses import RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

_DASH = Path(__file__).resolve().parents[1] / "dashboard" / "public"


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse("/app/")


if _DASH.is_dir():
    app.mount("/app", StaticFiles(directory=_DASH, html=True), name="dashboard")
