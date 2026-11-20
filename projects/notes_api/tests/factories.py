"""Test data factories: valid objects with sensible defaults, overridable per test.

Like factory_boy or polyfactory, but small: each call makes a new row with unique values (a
sequence number), so tests state only the fields they care about.
"""

import itertools
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from notes_api.models import Note, User
from notes_api.repositories import SqlNoteRepository, SqlUserRepository
from notes_api.schemas import NoteCreate

SEQUENCE = itertools.count(1)
NOW = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)


async def make_user(session: AsyncSession, **overrides: Any) -> User:
    """A user (no password: tests that log in use the HTTP API instead)."""
    number = next(SEQUENCE)
    fields = {"email": f"user{number}@example.com", "password_hash": None, "role": "user"}
    fields |= overrides
    return await SqlUserRepository(session).add_user(
        fields["email"], fields["password_hash"], fields["role"]
    )


async def make_note(session: AsyncSession, owner: User | None = None, **overrides: Any) -> Note:
    """A note owned by owner (a new user if none is given)."""
    owner = owner or await make_user(session)
    number = next(SEQUENCE)
    fields: dict[str, Any] = {"title": f"Note {number}", "body": "", "tags": [], "pinned": False}
    fields |= overrides
    return await SqlNoteRepository(session).add(NoteCreate(**fields), NOW, owner.id)
