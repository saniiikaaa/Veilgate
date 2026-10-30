"""Every integration test runs on its own event loop, so the shared engine must not outlive the test."""

import pytest_asyncio

from src.repositories.db import dispose_engine


@pytest_asyncio.fixture(loop_scope="function", autouse=True)
async def _fresh_engine():
    yield
    await dispose_engine()
