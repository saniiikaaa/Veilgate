"""Dev start script — runs Warden via uvicorn with hot-reload."""

import uvicorn

if __name__ == "__main__":
    from src.core.config import get_settings

    s = get_settings()
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=s.governance_port,
        reload=True,
        log_level="info",
    )
