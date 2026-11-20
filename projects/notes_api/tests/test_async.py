"""httpx.AsyncClient + ASGITransport: the app runs in the test's own event loop.

TestClient runs the app in a separate thread with its own loop: convenient for synchronous
tests, but async resources created by the test (an asyncpg connection, a task) cannot be
shared with the app. AsyncClient calls the ASGI app directly from the test's loop.
"""

import asyncio
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI

from notes_api.dependencies import get_clock

pytestmark = pytest.mark.anyio
NOTES = "/api/v1/notes"


async def test_crud_through_the_async_client(async_client: httpx.AsyncClient) -> None:
    """The same API, awaited."""
    created = (await async_client.post(NOTES, json={"title": "Async tea"})).json()
    fetched = await async_client.get(f"{NOTES}/{created['id']}")
    assert fetched.status_code == 200 and fetched.json()["title"] == "Async tea"
    assert (await async_client.get(NOTES)).json()["total"] == 1


async def test_concurrent_requests_in_one_loop(async_client: httpx.AsyncClient) -> None:
    """asyncio.gather sends ten requests at once; every note gets its own id."""
    responses = await asyncio.gather(
        *(async_client.post(NOTES, json={"title": f"Note {number}"}) for number in range(10))
    )
    assert {response.status_code for response in responses} == {201}
    assert len({response.json()["id"] for response in responses}) == 10


async def test_dependency_override_freezes_the_clock(
    app: FastAPI, async_client: httpx.AsyncClient
) -> None:
    """dependency_overrides swaps a dependency for the rest of the test."""
    frozen = datetime(2026, 11, 18, 9, 30, tzinfo=UTC)
    app.dependency_overrides[get_clock] = lambda: lambda: frozen
    created = (await async_client.post(NOTES, json={"title": "Frozen"})).json()
    assert created["created_at"] == "2026-11-18T09:30:00Z"
