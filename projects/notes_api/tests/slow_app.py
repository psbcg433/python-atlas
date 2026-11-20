"""The Notes API plus one slow route, for the graceful-shutdown test (never deployed)."""

import asyncio

from notes_api.main import create_app

app = create_app()


@app.get("/test/slow")
async def slow(seconds: float = 1.0) -> dict[str, float]:
    """A request that is still running when the server is told to stop."""
    await asyncio.sleep(seconds)
    return {"slept": seconds}
