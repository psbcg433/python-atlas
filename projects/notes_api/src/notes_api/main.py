"""The Notes API application.

Unit 6.2 version: path operations, Pydantic schemas, response models, status codes, errors and
OpenAPI metadata. Later units add dependency injection and routers (6.3), a database (6.4),
authentication (6.5), background jobs and caching (6.6), observability (6.7) and deployment (6.8).
"""

from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Path, Query, Response, status
from fastapi.routing import APIRoute

from notes_api import __version__
from notes_api.schemas import ErrorMessage, NoteCreate, NoteFilters, NotePage, NoteRead, NoteUpdate
from notes_api.store import Note, NoteNotFoundError, NoteStore


def operation_id(route: APIRoute) -> str:
    """Use the function name as the OpenAPI operationId (clean names in generated clients)."""
    return route.name


app = FastAPI(
    title="Notes API",
    version=__version__,
    summary="Create, search and organize notes.",
    description="Built step by step in Phase 6 of the course. Timestamps are UTC, ISO 8601.",
    openapi_tags=[
        {"name": "notes", "description": "Create, read, update and delete notes."},
        {"name": "health", "description": "Liveness probe for load balancers and tests."},
    ],
    generate_unique_id_function=operation_id,
)

notes_store = NoteStore()  # module-level for now; Unit 6.3 turns it into a dependency

NoteId = Annotated[int, Path(ge=1, description="The note's id.")]
NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorMessage, "description": "No note has this id."}
}


def find_note(note_id: int) -> Note:
    """The stored note, or an HTTP 404."""
    try:
        return notes_store.get(note_id)
    except NoteNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.post("/notes", response_model=NoteRead, status_code=status.HTTP_201_CREATED, tags=["notes"])
async def create_note(note: NoteCreate, response: Response) -> Note:
    """Create a note; the Location header points at it."""
    created = notes_store.add(note)
    response.headers["Location"] = app.url_path_for("get_note", note_id=str(created.id))
    return created


@app.get("/notes", response_model=NotePage, tags=["notes"])
async def list_notes(filters: Annotated[NoteFilters, Query()]) -> dict[str, object]:
    """Search, filter, sort and paginate notes."""
    notes, total = notes_store.search(filters)
    return {"items": notes, "total": total, "limit": filters.limit, "offset": filters.offset}


@app.get("/notes/{note_id}", response_model=NoteRead, responses=NOT_FOUND, tags=["notes"])
async def get_note(note_id: NoteId) -> Note:
    """Fetch one note."""
    return find_note(note_id)


@app.put("/notes/{note_id}", response_model=NoteRead, responses=NOT_FOUND, tags=["notes"])
async def replace_note(note_id: NoteId, note: NoteCreate) -> Note:
    """Replace every field of a note (omitted fields get their defaults)."""
    find_note(note_id)
    return notes_store.replace(note_id, note)


@app.patch("/notes/{note_id}", response_model=NoteRead, responses=NOT_FOUND, tags=["notes"])
async def update_note(note_id: NoteId, changes: NoteUpdate) -> Note:
    """Change only the fields sent in the body."""
    find_note(note_id)
    return notes_store.update(note_id, changes)


@app.delete(
    "/notes/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=NOT_FOUND,
    tags=["notes"],
)
async def delete_note(note_id: NoteId) -> None:
    """Delete a note."""
    find_note(note_id)
    notes_store.delete(note_id)
