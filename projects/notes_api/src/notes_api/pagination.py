"""Generic page envelopes and opaque keyset cursors."""

import base64
import binascii
import json
from datetime import datetime

from pydantic import BaseModel

from notes_api.exceptions import InvalidCursorError

type CursorKey = tuple[datetime, int]  # (created_at, id) of the last note on a page


class Page[ItemT](BaseModel):
    """One page of an offset-paginated list."""

    items: list[ItemT]
    total: int
    limit: int
    offset: int


class CursorPage[ItemT](BaseModel):
    """One page of a keyset-paginated list; pass next_cursor back to get the next page."""

    items: list[ItemT]
    limit: int
    next_cursor: str | None


def encode_cursor(key: CursorKey) -> str:
    """Opaque URL-safe text for (created_at, id): clients must not build or parse it."""
    created_at, note_id = key
    raw = json.dumps([created_at.isoformat(), note_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> CursorKey:
    """The (created_at, id) inside a cursor, or InvalidCursorError."""
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        created_text, note_id = json.loads(raw)
        if not isinstance(note_id, int):
            raise TypeError("id must be an integer")
        return datetime.fromisoformat(created_text), note_id
    except (binascii.Error, ValueError, TypeError) as error:
        raise InvalidCursorError(f"cursor {cursor!r} is not valid") from error
