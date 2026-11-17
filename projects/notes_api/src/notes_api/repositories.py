"""Storage behind a Protocol: the service depends on NoteRepository, not on a database.

Unit 6.3 shipped an in-memory implementation; Unit 6.4 replaces it with SqlNoteRepository,
which has the same methods, so the service and the routers barely change.
"""

from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import Select, delete, func, or_, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.exc import StaleDataError

from notes_api.exceptions import VersionConflictError
from notes_api.models import Note, Tag
from notes_api.pagination import CursorKey
from notes_api.schemas import NoteCreate, NoteFilters


class NoteRepository(Protocol):
    """What the service needs from storage."""

    async def add(self, data: NoteCreate, now: datetime) -> Note:
        """Store a new note and return it with its id."""
        ...

    async def get(self, note_id: int) -> Note | None:
        """The note with this id, or None."""
        ...

    async def search(self, filters: NoteFilters) -> tuple[list[Note], int]:
        """One page of matching notes and the total number of matches."""
        ...

    async def feed(self, limit: int, after: CursorKey | None) -> list[Note]:
        """Up to limit notes, newest first, strictly older than the key after."""
        ...

    async def update(self, note: Note, changes: dict[str, Any], now: datetime) -> Note:
        """Apply field changes (tags as a list of names), stamp updated_at, return the note."""
        ...

    async def delete(self, note: Note) -> None:
        """Remove a note returned by this repository."""
        ...

    async def delete_all(self) -> int:
        """Remove every note; return how many there were."""
        ...


class SqlNoteRepository:
    """NoteRepository on an AsyncSession: SQL filters, sorts and pages; tags always eager."""

    def __init__(self, session: AsyncSession) -> None:
        """Work inside the request's session (and so its transaction)."""
        self.session = session

    @staticmethod
    def _select() -> Select[tuple[Note]]:
        """SELECT notes plus one extra query for all their tags (no N+1, no lazy loads)."""
        return select(Note).options(selectinload(Note.tag_objects))

    async def _tags(self, names: list[str]) -> list[Tag]:
        """Tag rows for these names (sorted), creating missing ones; a savepoint absorbs a race."""
        if not names:
            return []
        found = await self.session.scalars(select(Tag).where(Tag.name.in_(names)))
        by_name = {tag.name: tag for tag in found}
        for name in names:
            if name in by_name:
                continue
            try:
                async with self.session.begin_nested():  # SAVEPOINT
                    tag = Tag(name=name)
                    self.session.add(tag)
                by_name[name] = tag
            except IntegrityError:  # another transaction inserted it first: use theirs
                by_name[name] = await self.session.scalar(select(Tag).where(Tag.name == name))
        return sorted((by_name[name] for name in names), key=lambda tag: tag.name)

    async def _flush(self, note: Note) -> None:
        """Send pending changes; a version mismatch becomes a domain conflict."""
        note_id = note.id  # read it now: after a failed flush the session needs a rollback
        try:
            await self.session.flush()
        except StaleDataError as error:
            raise VersionConflictError(note_id) from error

    async def add(self, data: NoteCreate, now: datetime) -> Note:
        """INSERT the note and its tag links; flush so the id is known."""
        note = Note(**data.model_dump(exclude={"tags"}), created_at=now, updated_at=now)
        note.tag_objects = await self._tags(data.tags)
        self.session.add(note)
        await self.session.flush()
        return note

    async def get(self, note_id: int) -> Note | None:
        """One note with its tags."""
        return await self.session.scalar(self._select().where(Note.id == note_id))

    async def search(self, filters: NoteFilters) -> tuple[list[Note], int]:
        """WHERE for the filters, COUNT for the total, ORDER BY + LIMIT/OFFSET for the page."""
        conditions = [Note.tag_objects.any(Tag.name == name) for name in filters.tag]
        if filters.pinned is not None:
            conditions.append(Note.pinned == filters.pinned)
        if filters.q:
            conditions.append(
                or_(
                    Note.title.icontains(filters.q, autoescape=True),
                    Note.body.icontains(filters.q, autoescape=True),
                )
            )
        total = await self.session.scalar(select(func.count(Note.id)).where(*conditions))
        field_name = filters.sort.removeprefix("-")
        column = func.lower(Note.title) if field_name == "title" else getattr(Note, field_name)
        if filters.sort.startswith("-"):
            order = [column.desc(), Note.id.desc()]
        else:
            order = [column.asc(), Note.id.asc()]
        page = self._select().where(*conditions).order_by(*order)
        notes = await self.session.scalars(page.offset(filters.offset).limit(filters.limit))
        return list(notes), total or 0

    async def feed(self, limit: int, after: CursorKey | None) -> list[Note]:
        """Keyset page: WHERE (created_at, id) < (:created_at, :id) on an index, no OFFSET."""
        statement = self._select().order_by(Note.created_at.desc(), Note.id.desc())
        if after is not None:
            statement = statement.where(tuple_(Note.created_at, Note.id) < tuple_(*after))
        return list(await self.session.scalars(statement.limit(limit)))

    async def update(self, note: Note, changes: dict[str, Any], now: datetime) -> Note:
        """Change attributes; the flush sends UPDATE ... WHERE id = ? AND version = ?."""
        changes = dict(changes)
        tag_names = changes.pop("tags", None)
        for name, value in changes.items():
            setattr(note, name, value)
        if tag_names is not None:
            note.tag_objects = await self._tags(tag_names)
        note.updated_at = now
        await self._flush(note)
        return note

    async def delete(self, note: Note) -> None:
        """DELETE the note (its tag links go by ON DELETE CASCADE)."""
        await self.session.delete(note)
        await self._flush(note)

    async def delete_all(self) -> int:
        """Bulk DELETE statements: every note, then every tag."""
        result = await self.session.execute(delete(Note))
        await self.session.execute(delete(Tag))
        return result.rowcount
