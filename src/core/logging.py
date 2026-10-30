import structlog
from src.core.config import get_settings


def setup_logging() -> None:
    settings = get_settings()
    is_local = settings.app_env == "local"
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer() if is_local
            else structlog.processors.JSONRenderer(),
        ]
    )
