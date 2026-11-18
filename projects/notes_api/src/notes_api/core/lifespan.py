"""Startup and shutdown: create shared resources once and keep them on app.state."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as redis_asyncio
from arq.connections import ArqRedis
from fastapi import FastAPI

from notes_api import __version__
from notes_api.core.config import Settings
from notes_api.db import create_engine_from_settings, make_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the database pool, Redis (text and queue clients) and an HTTP client; close them."""
    settings: Settings = app.state.settings
    engine = create_engine_from_settings(settings)  # connects lazily, on first use
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.redis = redis_asyncio.from_url(  # also lazy: no connection until the first command
        settings.redis_url.get_secret_value(), decode_responses=True
    )
    # The ARQ client (bytes, pickled jobs) for enqueuing background work; lazy as well
    app.state.queue = ArqRedis.from_url(settings.redis_url.get_secret_value())
    try:
        async with httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            follow_redirects=False,  # a redirect could lead a server-side fetch somewhere private
            headers={"User-Agent": f"notes-api/{__version__}"},
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        ) as http_client:
            app.state.http_client = http_client
            yield
    finally:
        await app.state.queue.aclose()
        await app.state.redis.aclose()
        await engine.dispose()  # close every pooled database connection
