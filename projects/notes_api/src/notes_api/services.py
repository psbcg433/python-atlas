"""Business logic: what the API does, independent of HTTP and of how notes are stored."""

import asyncio
import csv
import io
import ipaddress
import json
import re
import socket
import urllib.parse
from collections.abc import Awaitable, Callable
from datetime import datetime
from http import HTTPStatus
from typing import Any

import httpx
from pydantic import TypeAdapter, ValidationError

from notes_api.core.metrics import NOTES_WRITTEN
from notes_api.events import new_event
from notes_api.exceptions import NoteNotFoundError, UploadRejectedError, VersionConflictError
from notes_api.models import Note
from notes_api.pagination import decode_cursor, encode_cursor
from notes_api.repositories import NoteRepository
from notes_api.schemas import LinkPreview, NoteCreate, NoteFilters, NoteRead, NoteUpdate

URL_PATTERN = re.compile(r"https?://[^\s<>\"')]+")
TITLE_PATTERN = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
MAX_LINKS = 5
MAX_PREVIEW_BYTES = 64 * 1024
IMPORT_ADAPTER = TypeAdapter(list[NoteCreate])


class NoteService:
    """Use cases for one user's notes; repository, clock and owner are injected."""

    def __init__(
        self, repository: NoteRepository, clock: Callable[[], datetime], owner_id: int
    ) -> None:
        """Keep the collaborators; every operation is limited to owner_id's notes."""
        self.repository = repository
        self.clock = clock
        self.owner_id = owner_id

    async def record(self, event_type: str, note: Note) -> None:
        """Write an outbox event in the same transaction as the change it describes."""
        data = {"note_id": note.id, "title": note.title, "version": note.version}
        await self.repository.add_event(new_event(self.owner_id, event_type, data))
        NOTES_WRITTEN.labels(event_type.removeprefix("note.")).inc()

    async def create(self, data: NoteCreate) -> Note:
        """Store a new note for the owner, stamped with the current time."""
        note = await self.repository.add(data, self.clock(), self.owner_id)
        await self.record("note.created", note)
        return note

    async def load_for_cache(self, note_id: int) -> dict[str, Any] | None:
        """The cacheable form of any note (owner included): the caller checks the owner."""
        note = await self.repository.get(note_id)
        if note is None:
            return None
        return {
            "owner_id": note.owner_id,
            "note": NoteRead.model_validate(note).model_dump(mode="json"),
        }

    async def get(self, note_id: int) -> Note:
        """The owner's note, or NoteNotFoundError: someone else's note is 'not found' too,
        so ids cannot be probed (404, not 403)."""
        note = await self.repository.get(note_id)
        if note is None or note.owner_id != self.owner_id:
            raise NoteNotFoundError(note_id)
        return note

    async def search(self, filters: NoteFilters) -> tuple[list[Note], int]:
        """One page of the owner's matching notes and the total."""
        return await self.repository.search(filters, self.owner_id)

    async def feed(self, limit: int, cursor: str | None) -> tuple[list[Note], str | None]:
        """A keyset page, newest first, and the cursor of the next page (None at the end)."""
        after = decode_cursor(cursor) if cursor else None
        notes = await self.repository.feed(limit + 1, after, self.owner_id)  # one extra
        page = notes[:limit]
        has_more = len(notes) > limit
        next_cursor = encode_cursor((page[-1].created_at, page[-1].id)) if has_more else None
        return page, next_cursor

    async def replace(self, note_id: int, data: NoteCreate) -> Note:
        """PUT: every client-owned field gets the new value (or its default)."""
        note = await self.get(note_id)
        note = await self.repository.update(note, data.model_dump(), self.clock())
        await self.record("note.updated", note)
        return note

    async def update(self, note_id: int, changes: NoteUpdate) -> Note:
        """PATCH: check the expected version, apply the fields sent, move updated_at on change."""
        note = await self.get(note_id)
        if changes.version is not None and changes.version != note.version:
            raise VersionConflictError(note_id, expected=changes.version, actual=note.version)
        sent = changes.model_dump(exclude_unset=True, exclude={"version"})
        if all(getattr(note, name) == value for name, value in sent.items()):
            return note
        note = await self.repository.update(note, sent, self.clock())
        await self.record("note.updated", note)
        return note

    async def delete(self, note_id: int) -> None:
        """Delete a note, or NoteNotFoundError."""
        note = await self.get(note_id)
        await self.record("note.deleted", note)
        await self.repository.delete(note)

    async def import_notes(self, notes: list[NoteCreate]) -> list[Note]:
        """Create every note of an import, in file order."""
        return [await self.create(note) for note in notes]


def parse_import(filename: str, content: bytes) -> list[NoteCreate]:
    """Notes from a .json list or a .csv file (title, body, tags separated by ';', pinned)."""
    try:
        text = content.decode("utf-8-sig")
        if filename.endswith(".json"):
            return IMPORT_ADAPTER.validate_python(json.loads(text), strict=False)
        rows = [
            {**row, "tags": [tag for tag in (row.get("tags") or "").split(";") if tag]}
            for row in csv.DictReader(io.StringIO(text))
        ]
        return IMPORT_ADAPTER.validate_python(rows, strict=False)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
        reason = f"{type(error).__name__}: {str(error).splitlines()[0]}"
        raise UploadRejectedError(reason, HTTPStatus.UNPROCESSABLE_CONTENT) from error


type Resolver = Callable[[str], Awaitable[list[str]]]


async def resolve_host(host: str) -> list[str]:
    """Every IP address a host name resolves to (getaddrinfo runs in a worker thread)."""
    infos = await asyncio.to_thread(socket.getaddrinfo, host, None, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def is_public_address(address: str) -> bool:
    """False for loopback, private, link-local, reserved, multicast and unspecified addresses."""
    ip = ipaddress.ip_address(address)
    return ip.is_global and not ip.is_multicast


class LinkPreviewer:
    """Fetch the <title> of links in a note, refusing anything that is not a public web URL.

    Server-side request forgery (OWASP API7): a note body is user input, so a link could point
    at 127.0.0.1, the cloud metadata service (169.254.169.254) or a private network. Each host
    is resolved first and every address must be public; redirects are not followed (a public
    URL could redirect to a private one); at most MAX_PREVIEW_BYTES of a page are read.
    """

    def __init__(self, client: httpx.AsyncClient, resolver: Resolver = resolve_host) -> None:
        """Use the pooled client created by the lifespan and an injectable DNS resolver."""
        self.client = client
        self.resolver = resolver

    async def check_url(self, url: str) -> str | None:
        """None if the URL may be fetched, else the reason it may not."""
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return "only public http(s) URLs are fetched"
        try:
            addresses = await self.resolver(parsed.hostname)
        except OSError:
            return "host does not resolve"
        if not addresses or not all(is_public_address(address) for address in addresses):
            return "blocked: not a public address"
        return None

    async def preview(self, url: str) -> LinkPreview:
        """One link: its status and title, or why it was not fetched (never raises)."""
        if reason := await self.check_url(url):
            return LinkPreview(url=url, error=reason)
        try:
            async with self.client.stream("GET", url, follow_redirects=False) as response:
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= MAX_PREVIEW_BYTES:
                        break
        except httpx.HTTPError as error:
            return LinkPreview(url=url, error=type(error).__name__)
        if response.is_redirect:
            return LinkPreview(
                url=url, status_code=response.status_code, error="redirect not followed"
            )
        text = b"".join(chunks)[:MAX_PREVIEW_BYTES].decode(response.encoding or "utf-8", "replace")
        match = TITLE_PATTERN.search(text)
        title = " ".join(match[1].split()) if match else None
        return LinkPreview(url=url, status_code=response.status_code, title=title)

    async def previews(self, body: str) -> list[LinkPreview]:
        """The first MAX_LINKS distinct links of a body, fetched concurrently."""
        urls = list(dict.fromkeys(URL_PATTERN.findall(body)))[:MAX_LINKS]
        return list(await asyncio.gather(*(self.preview(url) for url in urls)))
