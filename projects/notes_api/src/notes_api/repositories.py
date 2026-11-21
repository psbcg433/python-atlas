"""Storage behind Protocols: services depend on NoteRepository / UserRepository, not on SQL.

Unit 6.3 shipped an in-memory note repository; Unit 6.4 replaced it with SqlNoteRepository;
Unit 6.5 scopes notes to their owner and adds SqlUserRepository (users, refresh tokens, keys).
"""

from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import Select, delete, func, or_, select, tuple_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.exc import StaleDataError

from notes_api.exceptions import VersionConflictError
from notes_api.models import ApiKey, Note, OutboxEvent, RefreshToken, Tag, User
from notes_api.pagination import CursorKey
from notes_api.schemas import NoteCreate, NoteFilters


class NoteRepository(Protocol):
    """What the service needs from storage."""

    async def add(self, data: NoteCreate, now: datetime, owner_id: int) -> Note:
        """Store a new note for owner_id and return it with its id."""
        ...

    async def get(self, note_id: int) -> Note | None:
        """The note with this id, or None."""
        ...

    async def search(self, filters: NoteFilters, owner_id: int | None) -> tuple[list[Note], int]:
        """One page of matching notes (of owner_id, or everyone's when None) and the total."""
        ...

    async def feed(self, limit: int, after: CursorKey | None, owner_id: int) -> list[Note]:
        """Up to limit of owner_id's notes, newest first, strictly older than the key after."""
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

    async def add_event(self, event: OutboxEvent) -> None:
        """Store an outbox event in the current transaction."""
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

    async def add(self, data: NoteCreate, now: datetime, owner_id: int) -> Note:
        """INSERT the note and its tag links; flush so the id is known."""
        fields = data.model_dump(exclude={"tags"})
        note = Note(**fields, owner_id=owner_id, created_at=now, updated_at=now)
        note.tag_objects = await self._tags(data.tags)
        self.session.add(note)
        await self.session.flush()
        return note

    async def get(self, note_id: int) -> Note | None:
        """One note with its tags."""
        return await self.session.scalar(self._select().where(Note.id == note_id))

    async def search(self, filters: NoteFilters, owner_id: int | None) -> tuple[list[Note], int]:
        """WHERE for the filters, COUNT for the total, ORDER BY + LIMIT/OFFSET for the page."""
        conditions = [Note.tag_objects.any(Tag.name == name) for name in filters.tag]
        if owner_id is not None:
            conditions.append(Note.owner_id == owner_id)
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

    async def feed(self, limit: int, after: CursorKey | None, owner_id: int) -> list[Note]:
        """Keyset page: WHERE (created_at, id) < (:created_at, :id) on an index, no OFFSET."""
        statement = self._select().where(Note.owner_id == owner_id)
        statement = statement.order_by(Note.created_at.desc(), Note.id.desc())
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

    async def add_event(self, event: OutboxEvent) -> None:
        """Same session, same transaction: the event exists if and only if the change does."""
        self.session.add(event)
        await self.session.flush()


class UserRepository(Protocol):
    """What the auth service needs from storage."""

    async def add_user(self, email: str, password_hash: str | None, role: str) -> User:
        """Store a new user (IntegrityError if the email exists)."""
        ...

    async def user_by_id(self, user_id: int) -> User | None:
        """The user, or None."""
        ...

    async def user_by_email(self, email: str) -> User | None:
        """The user with this email (case-insensitive), or None."""
        ...


class SqlUserRepository:
    """Users, refresh tokens and API keys on the request's session."""

    def __init__(self, session: AsyncSession) -> None:
        """Work inside the request's session."""
        self.session = session

    async def add_user(
        self, email: str, password_hash: str | None, role: str, oidc_subject: str | None = None
    ) -> User:
        """INSERT a user; a duplicate email raises IntegrityError at the flush."""
        user = User(email=email.lower(), password_hash=password_hash, role=role)
        user.oidc_subject = oidc_subject
        self.session.add(user)
        await self.session.flush()
        return user

    async def user_by_id(self, user_id: int) -> User | None:
        """Primary-key lookup (identity map first)."""
        return await self.session.get(User, user_id)

    async def user_by_email(self, email: str) -> User | None:
        """Emails are stored lower-cased."""
        return await self.session.scalar(select(User).where(User.email == email.lower()))

    async def user_by_oidc_subject(self, subject: str) -> User | None:
        """The user linked to a third-party identity."""
        return await self.session.scalar(select(User).where(User.oidc_subject == subject))

    async def add_refresh_token(self, token: RefreshToken) -> None:
        """Store a refresh token row."""
        self.session.add(token)
        await self.session.flush()

    async def refresh_token_by_hash(self, token_hash: str) -> RefreshToken | None:
        """Look a refresh token up by its SHA-256."""
        return await self.session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )

    async def revoke_family(self, family_id: str, now: datetime) -> int:
        """Revoke every token of one login; returns how many were still active."""
        result = await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        return result.rowcount

    async def add_api_key(self, key: ApiKey) -> ApiKey:
        """Store an API key row."""
        self.session.add(key)
        await self.session.flush()
        return key

    async def api_key_by_hash(self, key_hash: str) -> ApiKey | None:
        """An active (not revoked) key by its SHA-256."""
        return await self.session.scalar(
            select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
        )

    async def api_keys_of(self, user_id: int) -> list[ApiKey]:
        """A user's keys, newest first (revoked ones included)."""
        statement = select(ApiKey).where(ApiKey.user_id == user_id).order_by(ApiKey.id.desc())
        return list(await self.session.scalars(statement))

    async def delete_user(self, user_id: int) -> None:
        """DELETE the user; the database's ON DELETE CASCADE removes everything it owns."""
        await self.session.execute(delete(User).where(User.id == user_id))
