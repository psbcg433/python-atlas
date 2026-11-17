"""Business logic: what the API does, independent of HTTP and of how notes are stored."""

import asyncio
import csv
import io
import json
import re
from collections.abc import Callable
from datetime import datetime
from http import HTTPStatus

import httpx
from pydantic import TypeAdapter, ValidationError

from notes_api.exceptions import NoteNotFoundError, UploadRejectedError, VersionConflictError
from notes_api.models import Note, utc_now
from notes_api.pagination import decode_cursor, encode_cursor
from notes_api.repositories import NoteRepository
from notes_api.schemas import LinkPreview, NoteCreate, NoteFilters, NoteUpdate

URL_PATTERN = re.compile(r"https?://[^\s<>\"')]+")
TITLE_PATTERN = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
MAX_LINKS = 5
IMPORT_ADAPTER = TypeAdapter(list[NoteCreate])


class NoteService:
    """Use cases for notes; the repository and the clock are injected."""

    def __init__(self, repository: NoteRepository, clock: Callable[[], datetime] = utc_now) -> None:
        """Keep the collaborators."""
        self.repository = repository
        self.clock = clock

    async def create(self, data: NoteCreate) -> Note:
        """Store a new note stamped with the current time."""
        return await self.repository.add(data, self.clock())

    async def get(self, note_id: int) -> Note:
        """The note, or NoteNotFoundError (the API turns it into a 404 problem)."""
        note = await self.repository.get(note_id)
        if note is None:
            raise NoteNotFoundError(note_id)
        return note

    async def search(self, filters: NoteFilters) -> tuple[list[Note], int]:
        """One page of matching notes and the total."""
        return await self.repository.search(filters)

    async def feed(self, limit: int, cursor: str | None) -> tuple[list[Note], str | None]:
        """A keyset page, newest first, and the cursor of the next page (None at the end)."""
        after = decode_cursor(cursor) if cursor else None
        notes = await self.repository.feed(limit + 1, after)  # one extra: is there a next page?
        page = notes[:limit]
        has_more = len(notes) > limit
        next_cursor = encode_cursor((page[-1].created_at, page[-1].id)) if has_more else None
        return page, next_cursor

    async def replace(self, note_id: int, data: NoteCreate) -> Note:
        """PUT: every client-owned field gets the new value (or its default)."""
        note = await self.get(note_id)
        return await self.repository.update(note, data.model_dump(), self.clock())

    async def update(self, note_id: int, changes: NoteUpdate) -> Note:
        """PATCH: check the expected version, apply the fields sent, move updated_at on change."""
        note = await self.get(note_id)
        if changes.version is not None and changes.version != note.version:
            raise VersionConflictError(note_id, expected=changes.version, actual=note.version)
        sent = changes.model_dump(exclude_unset=True, exclude={"version"})
        if all(getattr(note, name) == value for name, value in sent.items()):
            return note
        return await self.repository.update(note, sent, self.clock())

    async def delete(self, note_id: int) -> None:
        """Delete a note, or NoteNotFoundError."""
        note = await self.get(note_id)
        await self.repository.delete(note)

    async def import_notes(self, notes: list[NoteCreate]) -> list[Note]:
        """Create every note of an import, in file order."""
        return [await self.create(note) for note in notes]

    async def delete_all(self) -> int:
        """Remove every note."""
        return await self.repository.delete_all()


def parse_import(filename: str, content: bytes) -> list[NoteCreate]:
    """Notes from a .json list or a .csv file (title, body, tags separated by ';', pinned)."""
    try:
        text = content.decode("utf-8-sig")
        if filename.endswith(".json"):
            return IMPORT_ADAPTER.validate_python(json.loads(text))
        rows = [
            {**row, "tags": [tag for tag in (row.get("tags") or "").split(";") if tag]}
            for row in csv.DictReader(io.StringIO(text))
        ]
        return IMPORT_ADAPTER.validate_python(rows)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
        reason = f"{type(error).__name__}: {str(error).splitlines()[0]}"
        raise UploadRejectedError(reason, HTTPStatus.UNPROCESSABLE_CONTENT) from error


class LinkPreviewer:
    """Fetch the <title> of links in a note through the app's shared HTTP client."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        """Use the pooled client created by the lifespan."""
        self.client = client

    async def preview(self, url: str) -> LinkPreview:
        """One link: its status and title, or the error name (never raises)."""
        try:
            response = await self.client.get(url)
        except httpx.HTTPError as error:
            return LinkPreview(url=url, error=type(error).__name__)
        match = TITLE_PATTERN.search(response.text)
        title = " ".join(match[1].split()) if match else None
        return LinkPreview(url=url, status_code=response.status_code, title=title)

    async def previews(self, body: str) -> list[LinkPreview]:
        """The first MAX_LINKS distinct links of a body, fetched concurrently."""
        urls = list(dict.fromkeys(URL_PATTERN.findall(body)))[:MAX_LINKS]
        return list(await asyncio.gather(*(self.preview(url) for url in urls)))
