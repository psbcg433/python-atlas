"""/api/v1/notes: CRUD, search, a keyset feed, link previews; ETags and a Redis cache."""

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Header, Path, Query, Request, Response, status

from notes_api.core.errors import PROBLEM_JSON, ProblemDetail
from notes_api.dependencies import (
    LinkPreviewerDep,
    NoteCacheDep,
    QueueDep,
    ReaderServiceDep,
    WriterServiceDep,
    kick_relay,
)
from notes_api.exceptions import NoteNotFoundError
from notes_api.models import Note
from notes_api.pagination import CursorPage, Page
from notes_api.schemas import FeedParams, LinkPreview, NoteCreate, NoteFilters, NoteRead, NoteUpdate

NoteId = Annotated[int, Path(ge=1, description="The note's id.")]
NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {
        "model": ProblemDetail,
        "description": "No note has this id.",
        "content": {PROBLEM_JSON: {}},
    }
}
CACHE_CONTROL = "private, no-cache"  # browsers may keep it, but must revalidate (ETag) first

router = APIRouter(prefix="/notes", tags=["notes"])  # every route needs a user (scopes below)


def etag_of(note: dict[str, Any]) -> str:
    """A strong validator: the version changes on every update."""
    return f'"{note["id"]}-{note["version"]}"'


def matches(if_none_match: str | None, etag: str) -> bool:
    """True if the client's If-None-Match lists this ETag (or '*')."""
    if not if_none_match:
        return False
    candidates = {item.strip().removeprefix("W/") for item in if_none_match.split(",")}
    return etag in candidates or "*" in candidates


def after_write(background: BackgroundTasks, queue: Any, cache: Any, note_id: int | None) -> None:
    """After the response (so after the commit): drop the cached copy again, wake the relay."""
    if note_id is not None:
        background.add_task(cache.invalidate, note_id)
    background.add_task(kick_relay, queue)


@router.post("", response_model=NoteRead, status_code=status.HTTP_201_CREATED)
async def create_note(
    note: NoteCreate,
    service: WriterServiceDep,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    queue: QueueDep,
    cache: NoteCacheDep,
) -> Note:
    """Create a note; the Location header points at it."""
    created = await service.create(note)
    response.headers["Location"] = request.app.url_path_for("get_note", note_id=str(created.id))
    after_write(background, queue, cache, None)
    return created


@router.get("", response_model=Page[NoteRead])
async def list_notes(
    filters: Annotated[NoteFilters, Query()], service: ReaderServiceDep, response: Response
) -> dict[str, object]:
    """Search, filter, sort and paginate notes (offset pagination)."""
    notes, total = await service.search(filters)
    response.headers["Cache-Control"] = "private, no-store"  # lists change constantly
    return {"items": notes, "total": total, "limit": filters.limit, "offset": filters.offset}


@router.get("/feed", response_model=CursorPage[NoteRead])
async def notes_feed(
    params: Annotated[FeedParams, Query()], service: ReaderServiceDep
) -> dict[str, object]:
    """Newest notes first, with keyset (cursor) pagination."""
    notes, next_cursor = await service.feed(params.limit, params.cursor)
    return {"items": notes, "limit": params.limit, "next_cursor": next_cursor}


@router.get(
    "/{note_id}",
    response_model=NoteRead,
    responses={**NOT_FOUND, 304: {"description": "Not modified (If-None-Match matched)."}},
)
async def get_note(
    note_id: NoteId,
    service: ReaderServiceDep,
    cache: NoteCacheDep,
    response: Response,
    if_none_match: Annotated[str | None, Header()] = None,
) -> Any:
    """Fetch one note through the cache; 304 when the client's copy is current."""
    cached = await cache.get_or_load(note_id, lambda: service.load_for_cache(note_id))
    if cached is None or cached["owner_id"] != service.owner_id:  # authorize after the cache
        raise NoteNotFoundError(note_id)
    note, etag = cached["note"], etag_of(cached["note"])
    headers = {"ETag": etag, "Cache-Control": CACHE_CONTROL}
    if matches(if_none_match, etag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    response.headers.update(headers)
    return note


@router.put("/{note_id}", response_model=NoteRead, responses=NOT_FOUND)
async def replace_note(
    note_id: NoteId,
    note: NoteCreate,
    service: WriterServiceDep,
    background: BackgroundTasks,
    queue: QueueDep,
    cache: NoteCacheDep,
) -> Note:
    """Replace every field of a note (omitted fields get their defaults)."""
    replaced = await service.replace(note_id, note)  # 404 for someone else's note first
    await cache.invalidate(note_id)  # now (a reader could still re-cache the old row) ...
    after_write(background, queue, cache, note_id)  # ... so once more after the commit
    return replaced


@router.patch("/{note_id}", response_model=NoteRead, responses=NOT_FOUND)
async def update_note(
    note_id: NoteId,
    changes: NoteUpdate,
    service: WriterServiceDep,
    background: BackgroundTasks,
    queue: QueueDep,
    cache: NoteCacheDep,
) -> Note:
    """Change only the fields sent in the body."""
    updated = await service.update(note_id, changes)
    await cache.invalidate(note_id)
    after_write(background, queue, cache, note_id)
    return updated


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND)
async def delete_note(
    note_id: NoteId,
    service: WriterServiceDep,
    background: BackgroundTasks,
    queue: QueueDep,
    cache: NoteCacheDep,
) -> None:
    """Delete a note."""
    await service.delete(note_id)
    await cache.invalidate(note_id)
    after_write(background, queue, cache, note_id)


@router.get("/{note_id}/links", response_model=list[LinkPreview], responses=NOT_FOUND)
async def note_links(
    note_id: NoteId, service: ReaderServiceDep, previewer: LinkPreviewerDep
) -> list[LinkPreview]:
    """Titles of the links in a note's body, fetched with the shared HTTP client."""
    note = await service.get(note_id)
    return await previewer.previews(note.body)
