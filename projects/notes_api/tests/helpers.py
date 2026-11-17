"""Small helpers shared by the test modules."""

from typing import Any

from fastapi.testclient import TestClient

from notes_api.core.config import Settings
from notes_api.db import Base, create_engine_from_settings


def create(client: TestClient, **fields: Any) -> dict[str, Any]:
    """POST a note (title defaults to "Buy tea") and return the created note."""
    response = client.post("/api/v1/notes", json={"title": "Buy tea", **fields})
    assert response.status_code == 201, response.text
    return response.json()


def ids(response: Any) -> list[int]:
    """Ids of the notes on a page."""
    assert response.status_code == 200, response.text
    return [note["id"] for note in response.json()["items"]]


async def create_tables(settings: Settings) -> None:
    """CREATE TABLE for every model (fast; the PostgreSQL tests run the Alembic migrations)."""
    engine = create_engine_from_settings(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()
