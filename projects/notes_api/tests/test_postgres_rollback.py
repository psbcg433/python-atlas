"""Rollback-per-test on PostgreSQL: one outer transaction per test, rolled back at the end.

The app's session joins the test's connection with join_transaction_mode="create_savepoint":
the app's commits become SAVEPOINT releases inside the outer transaction, so each test sees
an empty database without truncating or re-migrating. AsyncClient keeps app and test on one
event loop (an asyncpg connection belongs to the loop that opened it).
"""

from collections.abc import AsyncIterator

import fakeredis
import httpx
import pytest
import sqlalchemy as sa
from arq.connections import ArqRedis
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from conftest import async_auth_headers
from factories import make_note, make_user
from helpers import USER_EMAIL, FakeMailer, fake_resolver
from notes_api.core.config import Settings
from notes_api.dependencies import get_mailer, get_queue, get_redis, get_resolver, get_session
from notes_api.main import create_app

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
async def db_connection(postgres_url: str) -> AsyncIterator[AsyncConnection]:
    """A connection with an open transaction that is always rolled back."""
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()
    await engine.dispose()


@pytest.fixture
async def db_session(db_connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    """A session whose commits are savepoints inside the test's transaction."""
    session = AsyncSession(
        bind=db_connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    try:
        yield session
    finally:
        await session.close()


@pytest.fixture
async def pg_client(
    settings: Settings,
    postgres_url: str,
    db_session: AsyncSession,
    fake_redis: fakeredis.FakeAsyncRedis,
    fake_queue: ArqRedis,
    mailer: FakeMailer,
) -> AsyncIterator[httpx.AsyncClient]:
    """A logged-in AsyncClient whose requests use the test's session."""
    app: FastAPI = create_app(settings.model_copy(update={"database_url": SecretStr(postgres_url)}))

    async def session_in_test_transaction() -> AsyncIterator[AsyncSession]:
        """Each request: a savepoint in the test transaction (nested if one is already open)."""
        nested = db_session.in_transaction()
        async with db_session.begin_nested() if nested else db_session.begin():
            yield db_session

    app.dependency_overrides[get_session] = session_in_test_transaction
    app.dependency_overrides[get_redis] = lambda: fake_redis
    app.dependency_overrides[get_queue] = lambda: fake_queue
    app.dependency_overrides[get_mailer] = lambda: mailer
    app.dependency_overrides[get_resolver] = lambda: fake_resolver
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            http.headers.update(await async_auth_headers(http, USER_EMAIL))
            yield http


async def count_notes(connection: AsyncConnection | AsyncSession) -> int:
    """Rows in notes, as the test's transaction sees them."""
    return (await connection.execute(sa.text("SELECT count(*) FROM notes"))).scalar_one()


@pytest.mark.parametrize("run", [1, 2])
async def test_every_test_starts_empty(
    pg_client: httpx.AsyncClient, db_session: AsyncSession, run: int
) -> None:
    """Both runs see zero notes first, though each one writes three."""
    assert await count_notes(db_session) == 0
    for number in range(3):
        response = await pg_client.post("/api/v1/notes", json={"title": f"Run {run} #{number}"})
        assert response.status_code == 201
    assert await count_notes(db_session) == 3


async def test_factories_make_valid_rows(db_session: AsyncSession) -> None:
    """Factories fill in unique, valid defaults; tests override only what matters."""
    owner = await make_user(db_session)
    pinned = await make_note(db_session, owner, pinned=True, tags=["work"])
    other = await make_note(db_session)
    assert pinned.owner_id == owner.id and pinned.tags == ["work"] and pinned.pinned
    assert other.owner_id != owner.id and other.title != pinned.title
    assert await count_notes(db_session) == 2
