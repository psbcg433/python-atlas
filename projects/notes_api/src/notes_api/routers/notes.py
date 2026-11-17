"""/api/v1/notes: CRUD, search with offset pages, a keyset feed, and link previews."""

from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Request, Response, status

from notes_api.core.errors import PROBLEM_JSON, ProblemDetail
from notes_api.dependencies import LinkPreviewerDep, NoteServiceDep
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

router = APIRouter(prefix="/notes", tags=["notes"])


@router.post("", response_model=NoteRead, status_code=status.HTTP_201_CREATED)
async def create_note(
    note: NoteCreate, service: NoteServiceDep, request: Request, response: Response
) -> Note:
    """Create a note; the Location header points at it."""
    created = await service.create(note)
    response.headers["Location"] = request.app.url_path_for("get_note", note_id=str(created.id))
    return created


@router.get("", response_model=Page[NoteRead])
async def list_notes(
    filters: Annotated[NoteFilters, Query()], service: NoteServiceDep
) -> dict[str, object]:
    """Search, filter, sort and paginate notes (offset pagination)."""
    notes, total = await service.search(filters)
    return {"items": notes, "total": total, "limit": filters.limit, "offset": filters.offset}


@router.get("/feed", response_model=CursorPage[NoteRead])
async def notes_feed(
    params: Annotated[FeedParams, Query()], service: NoteServiceDep
) -> dict[str, object]:
    """Newest notes first, with keyset (cursor) pagination."""
    notes, next_cursor = await service.feed(params.limit, params.cursor)
    return {"items": notes, "limit": params.limit, "next_cursor": next_cursor}


@router.get("/{note_id}", response_model=NoteRead, responses=NOT_FOUND)
async def get_note(note_id: NoteId, service: NoteServiceDep) -> Note:
    """Fetch one note."""
    return await service.get(note_id)


@router.put("/{note_id}", response_model=NoteRead, responses=NOT_FOUND)
async def replace_note(note_id: NoteId, note: NoteCreate, service: NoteServiceDep) -> Note:
    """Replace every field of a note (omitted fields get their defaults)."""
    return await service.replace(note_id, note)


@router.patch("/{note_id}", response_model=NoteRead, responses=NOT_FOUND)
async def update_note(note_id: NoteId, changes: NoteUpdate, service: NoteServiceDep) -> Note:
    """Change only the fields sent in the body."""
    return await service.update(note_id, changes)


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND)
async def delete_note(note_id: NoteId, service: NoteServiceDep) -> None:
    """Delete a note."""
    await service.delete(note_id)


@router.get("/{note_id}/links", response_model=list[LinkPreview], responses=NOT_FOUND)
async def note_links(
    note_id: NoteId, service: NoteServiceDep, previewer: LinkPreviewerDep
) -> list[LinkPreview]:
    """Titles of the links in a note's body, fetched with the shared HTTP client."""
    note = await service.get(note_id)
    return await previewer.previews(note.body)
