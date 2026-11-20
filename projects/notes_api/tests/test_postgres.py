"""The same app on PostgreSQL in Docker: migrations, drift check, trigram search, races.

Uses the CI service (NOTES_TEST_DATABASE_URL) or a testcontainer; skipped without either.
Run only these: `uv run pytest -m postgres`; skip them: `uv run pytest -m "not postgres"`.
"""

import asyncio
import secrets
from collections.abc import Iterator
from datetime import UTC, datetime

import fakeredis
import pytest
import sqlalchemy as sa
from alembic import command
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from helpers import USER_EMAIL, auth_headers, postgres_alembic_config
from notes_api.core.config import Settings
from notes_api.dependencies import get_redis
from notes_api.main import create_app
from notes_api.repositories import SqlNoteRepository, SqlUserRepository
from notes_api.schemas import NoteCreate

pytestmark = pytest.mark.postgres


@pytest.fixture
def empty_url(postgres_url: str) -> Iterator[str]:
    """The database with every row removed and ids restarted, before and after the test.

    The database is shared with test_postgres_rollback.py (session-scoped), so these
    committing tests clean up after themselves.
    """

    async def truncate() -> None:
        """TRUNCATE all tables."""
        engine = create_async_engine(postgres_url)
        async with engine.begin() as connection:
            await connection.execute(
                sa.text("TRUNCATE notes, tags, users RESTART IDENTITY CASCADE")
            )
        await engine.dispose()

    asyncio.run(truncate())
    yield postgres_url
    asyncio.run(truncate())


def test_models_match_the_migrations(postgres_url: str) -> None:
    """alembic check: autogenerate finds no difference between the models and the schema."""
    command.check(postgres_alembic_config(postgres_url))


def test_api_round_trip_on_postgres(empty_url: str) -> None:
    """Create, search (ILIKE), feed, PATCH with versions and the 409, on the real database."""
    settings = Settings(
        _env_file=None,
        environment="test",
        jwt_secret=SecretStr(secrets.token_urlsafe(32)),
        password_time_cost=1,
        password_memory_kib=64,
        database_url=SecretStr(empty_url),
    )
    app = create_app(settings)
    app.dependency_overrides[get_redis] = lambda: fakeredis.FakeAsyncRedis(decode_responses=True)
    with TestClient(app) as client:
        client.headers.update(auth_headers(client, USER_EMAIL))
        for title in ("Buy Tea", "Steep the tea", "Call Ravi"):
            assert (
                client.post("/api/v1/notes", json={"title": title, "tags": ["x"]}).status_code
                == 201
            )
        found = client.get("/api/v1/notes", params={"q": "TEA", "sort": "title"}).json()
        assert [note["title"] for note in found["items"]] == ["Buy Tea", "Steep the tea"]
        feed = client.get("/api/v1/notes/feed", params={"limit": 2}).json()
        assert [note["id"] for note in feed["items"]] == [3, 2] and feed["next_cursor"]
        assert (
            client.patch("/api/v1/notes/1", json={"pinned": True, "version": 1}).json()["version"]
            == 2
        )
        assert (
            client.patch("/api/v1/notes/1", json={"pinned": False, "version": 1}).status_code == 409
        )
        assert client.get("/health/ready").json()["checks"]["database"] == "ok"


def test_trigram_index_serves_substring_search(empty_url: str) -> None:
    """EXPLAIN shows ILIKE '%tea%' using the GIN trigram index (sequential scans off)."""

    async def plan() -> str:
        """The query plan of a title search."""
        async_engine = create_async_engine(empty_url)
        async with async_engine.begin() as connection:
            await connection.execute(sa.text("SET LOCAL enable_seqscan = off"))
            rows = await connection.execute(
                sa.text("EXPLAIN SELECT id FROM notes WHERE title ILIKE '%tea%'")
            )
            text = "\n".join(row[0] for row in rows)
        await async_engine.dispose()
        return text

    assert "ix_notes_title_trgm" in asyncio.run(plan())


def test_concurrent_new_tag_is_absorbed_by_the_savepoint(empty_url: str) -> None:
    """Two transactions add one new tag; a SAVEPOINT absorbs the loser's unique violation."""
    now = datetime(2026, 11, 17, tzinfo=UTC)

    async def race() -> list[list[str]]:
        """Run the two transactions concurrently and report each note's tags."""
        engine = create_async_engine(empty_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        first_flushed = asyncio.Event()
        async with factory() as session, session.begin():
            owner = await SqlUserRepository(session).add_user("racer@example.com", None, "user")

        async def first() -> list[str]:
            """Insert the tag, hold the transaction open for a moment, then commit."""
            async with factory() as session, session.begin():
                note = await SqlNoteRepository(session).add(
                    NoteCreate(title="A", tags=["race"]), now, owner.id
                )
                first_flushed.set()
                await asyncio.sleep(0.3)  # the second transaction blocks on the unique index
                return list(note.tags)

        async def second(session_factory: async_sessionmaker[AsyncSession]) -> list[str]:
            """Insert the same tag while the first transaction still holds it."""
            await first_flushed.wait()
            async with session_factory() as session, session.begin():
                note = await SqlNoteRepository(session).add(
                    NoteCreate(title="B", tags=["race"]), now, owner.id
                )
                return list(note.tags)

        results = await asyncio.gather(first(), second(factory))
        async with engine.connect() as connection:
            tag_count = await connection.scalar(sa.text("SELECT count(*) FROM tags"))
        await engine.dispose()
        assert tag_count == 1
        return list(results)

    assert asyncio.run(race()) == [["race"], ["race"]]
