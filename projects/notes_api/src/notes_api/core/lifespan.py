"""Startup and shutdown: create shared resources once and keep them on app.state."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from notes_api import __version__
from notes_api.core.config import Settings
from notes_api.db import create_engine_from_settings, make_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the database pool and one HTTP client; close both on shutdown."""
    settings: Settings = app.state.settings
    engine = create_engine_from_settings(settings)  # connects lazily, on first use
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    try:
        async with httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": f"notes-api/{__version__}"},
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        ) as http_client:
            app.state.http_client = http_client
            yield
    finally:
        await engine.dispose()  # close every pooled database connection
