"""SqlNoteRepository on a real (SQLite) database: sessions, loading, locking, savepoints."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from helpers import create_tables
from notes_api.core.config import Settings
from notes_api.db import create_engine_from_settings, make_session_factory
from notes_api.exceptions import VersionConflictError
from notes_api.models import Note, Tag
from notes_api.repositories import SqlNoteRepository, SqlUserRepository
from notes_api.schemas import NoteCreate

pytestmark = pytest.mark.anyio
NOW = datetime(2026, 11, 17, 9, 30, tzinfo=UTC)


@pytest.fixture
async def session_factory(settings: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A session factory on a fresh database."""
    await create_tables(settings)
    engine = create_engine_from_settings(settings)
    yield make_session_factory(engine)
    await engine.dispose()


async def add_note(factory: async_sessionmaker[AsyncSession], **fields: object) -> int:
    """Create and commit one note (owned by a user created on first use); return its id."""
    async with factory() as session, session.begin():
        users = SqlUserRepository(session)
        owner = await users.user_by_email("owner@example.com")
        owner = owner or await users.add_user("owner@example.com", None, "user")
        note = await SqlNoteRepository(session).add(
            NoteCreate(title="Tea", **fields), NOW, owner.id
        )
        return note.id


async def test_tag_rows_are_shared(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Two notes tagged 'shop' share one Tag row."""
    await add_note(session_factory, tags=["shop", "food"])
    await add_note(session_factory, tags=["shop"])
    async with session_factory() as session:
        assert await session.scalar(select(func.count(Tag.id))) == 2


async def test_lazy_loading_is_switched_off(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """lazy='raise': touching tags without eager loading fails loudly instead of an N+1."""
    note_id = await add_note(session_factory, tags=["shop"])
    async with session_factory() as session:
        plain = await session.get(Note, note_id)
        assert plain is not None
        with pytest.raises(InvalidRequestError, match="lazy='raise'"):
            _ = plain.tags
        loaded = await SqlNoteRepository(session).get(note_id)
        assert loaded is not None and loaded.tags == ["shop"]


async def test_timestamps_come_back_in_utc(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """UTCDateTime attaches UTC to SQLite's naive values."""
    note_id = await add_note(session_factory)
    async with session_factory() as session:
        note = await SqlNoteRepository(session).get(note_id)
        assert note is not None and note.created_at == NOW and note.created_at.tzinfo is UTC


async def test_concurrent_update_raises_version_conflict(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Two sessions read version 1; the second UPDATE matches no row → VersionConflictError."""
    note_id = await add_note(session_factory)
    async with session_factory() as first, session_factory() as second:
        first_note = await SqlNoteRepository(first).get(note_id)
        second_note = await SqlNoteRepository(second).get(note_id)
        assert first_note is not None and second_note is not None
        await SqlNoteRepository(first).update(first_note, {"title": "First"}, NOW)
        await first.commit()
        with pytest.raises(VersionConflictError):
            await SqlNoteRepository(second).update(second_note, {"title": "Second"}, NOW)
    async with session_factory() as session:
        stored = await session.get(Note, note_id)
        assert stored is not None and (stored.title, stored.version) == ("First", 2)


async def test_delete_all_counts_rows(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Bulk DELETE removes notes, their links (cascade) and tags."""
    await add_note(session_factory, tags=["a"])
    await add_note(session_factory, tags=["b"])
    async with session_factory() as session, session.begin():
        assert await SqlNoteRepository(session).delete_all() == 2
    async with session_factory() as session:
        assert await session.scalar(select(func.count(Tag.id))) == 0
