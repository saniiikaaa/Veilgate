"""Admin router stub — build info endpoint (auth added in Task 12)."""

from fastapi import APIRouter

admin_router = APIRouter(tags=["admin"])


@admin_router.get("/status")
async def admin_status() -> dict:
    """Return basic service/build information."""
    return {
        "service": "warden",
        "version": "0.1.0",
        "tasks_complete": ["core", "database", "repositories", "api"],
    }
