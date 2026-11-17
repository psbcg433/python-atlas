"""In-memory storage for notes. Unit 6.4 replaces it with SQLAlchemy behind the same methods."""

import dataclasses
import itertools
from collections.abc import Callable
from datetime import UTC, datetime

from notes_api.schemas import NoteCreate, NoteFilters, NoteUpdate


@dataclasses.dataclass(slots=True)
class Note:
    """A stored note: the server's own record, not a schema."""

    id: int
    title: str
    body: str
    tags: list[str]
    pinned: bool
    created_at: datetime
    updated_at: datetime


class NoteNotFoundError(LookupError):
    """No note has the requested id."""

    def __init__(self, note_id: int) -> None:
        """Remember the id; the message is what the API sends as the 404 detail."""
        super().__init__(f"note {note_id} not found")
        self.note_id = note_id


def utc_now() -> datetime:
    """The current time in UTC (the default clock)."""
    return datetime.now(UTC)


def matches(note: Note, filters: NoteFilters) -> bool:
    """True if the note passes every filter."""
    if filters.pinned is not None and note.pinned != filters.pinned:
        return False
    if not set(filters.tag) <= set(note.tags):
        return False
    if filters.q:
        needle = filters.q.casefold()
        return needle in note.title.casefold() or needle in note.body.casefold()
    return True


def sort_key(field_name: str) -> Callable[[Note], tuple[object, int]]:
    """Sort by one field (text ignores case), then by id so the order is always stable."""

    def key(note: Note) -> tuple[object, int]:
        """The sort key of one note."""
        value = getattr(note, field_name)
        return (value.casefold() if isinstance(value, str) else value, note.id)

    return key


class NoteStore:
    """Notes in a dict, ids from a counter. Used only from async handlers (one thread)."""

    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        """Start empty; clock supplies created_at/updated_at (injectable for tests)."""
        self.clock = clock
        self._notes: dict[int, Note] = {}
        self._ids = itertools.count(1)

    def clear(self) -> None:
        """Remove every note and restart ids at 1."""
        self._notes.clear()
        self._ids = itertools.count(1)

    def add(self, data: NoteCreate) -> Note:
        """Store a new note."""
        now = self.clock()
        note = Note(id=next(self._ids), **data.model_dump(), created_at=now, updated_at=now)
        self._notes[note.id] = note
        return note

    def get(self, note_id: int) -> Note:
        """The note with this id, or NoteNotFoundError."""
        try:
            return self._notes[note_id]
        except KeyError:
            raise NoteNotFoundError(note_id) from None

    def search(self, filters: NoteFilters) -> tuple[list[Note], int]:
        """One page of matching notes, and how many notes match in total."""
        found = [note for note in self._notes.values() if matches(note, filters)]
        descending = filters.sort.startswith("-")
        found.sort(key=sort_key(filters.sort.removeprefix("-")), reverse=descending)
        return found[filters.offset : filters.offset + filters.limit], len(found)

    def replace(self, note_id: int, data: NoteCreate) -> Note:
        """Replace every client-owned field (PUT)."""
        note = self.get(note_id)
        replaced = dataclasses.replace(note, **data.model_dump(), updated_at=self.clock())
        self._notes[note_id] = replaced
        return replaced

    def update(self, note_id: int, changes: NoteUpdate) -> Note:
        """Apply only the fields the client sent (PATCH); updated_at moves only on a change."""
        note = self.get(note_id)
        sent = changes.model_dump(exclude_unset=True)
        if all(getattr(note, name) == value for name, value in sent.items()):
            return note
        updated = dataclasses.replace(note, **sent, updated_at=self.clock())
        self._notes[note_id] = updated
        return updated

    def delete(self, note_id: int) -> None:
        """Remove the note, or raise NoteNotFoundError."""
        self.get(note_id)
        del self._notes[note_id]
