"""HTTP exception handler functions for the Warden API."""

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse

from src.core.errors import AuthorityError, PolicyDenyError, VaultError, WardenError

logger = structlog.get_logger(__name__)


async def warden_policy_deny_handler(request: Request, exc: PolicyDenyError) -> JSONResponse:
    logger.warning(
        "policy_deny",
        reason=exc.reason,
        agent_id=exc.agent_id,
        pack=exc.pack,
        path=request.url.path,
    )
    return JSONResponse(
        status_code=403,
        content={
            "error": "policy_deny",
            "reason": exc.reason,
            "agent_id": exc.agent_id,
            "pack": exc.pack,
        },
    )


async def warden_vault_handler(request: Request, exc: VaultError) -> JSONResponse:
    logger.error("vault_error", detail=str(exc), path=request.url.path)
    return JSONResponse(
        status_code=422,
        content={"error": "vault_error", "detail": str(exc)},
    )


async def warden_authority_handler(request: Request, exc: AuthorityError) -> JSONResponse:
    logger.warning("authority_error", detail=str(exc), path=request.url.path)
    return JSONResponse(
        status_code=403,
        content={"error": "authority_error", "detail": str(exc)},
    )


async def warden_generic_handler(request: Request, exc: WardenError) -> JSONResponse:
    logger.error("warden_error", detail=str(exc), path=request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "warden_error", "detail": str(exc)},
    )


async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("internal_error", path=request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "detail": "An unexpected error occurred"},
    )
