"""Health and readiness check endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session
from src.core.config import get_settings

health_router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    env: str
    version: str


class ReadyResponse(BaseModel):
    status: str
    db: str


@health_router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    """Liveness check — always fast, no DB required."""
    settings = get_settings()
    return HealthResponse(status="ok", env=settings.app_env, version="0.1.0")


@health_router.get("/readyz", response_model=ReadyResponse)
async def readyz(session: AsyncSession = Depends(get_db_session)) -> ReadyResponse:
    """Readiness check — verifies DB connectivity."""
    try:
        await session.execute(text("SELECT 1"))
        return ReadyResponse(status="ready", db="ok")
    except Exception:
        raise HTTPException(
            status_code=503,
            detail={"status": "unavailable", "db": "unreachable"},
        )
