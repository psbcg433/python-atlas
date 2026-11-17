"""Server-rendered pages: Jinja2 templates, a form with redirect-after-POST, HTMX partials."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, Header, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from notes_api.dependencies import NoteServiceDep
from notes_api.schemas import NoteCreate, NoteFilters, NoteUpdate

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(include_in_schema=False)  # HTML for people, not part of the JSON API


@router.get("/", response_class=HTMLResponse)
async def notes_page(
    request: Request,
    service: NoteServiceDep,
    q: str = "",
    hx_request: Annotated[str | None, Header()] = None,
) -> Response:
    """The notes page; for an HTMX search request only the list fragment."""
    notes, total = await service.search(NoteFilters(q=q or None, limit=50))
    context = {"notes": notes, "total": total, "q": q, "errors": [], "form": {}}
    template = "_notes.html" if hx_request == "true" else "index.html"
    return templates.TemplateResponse(request, template, context)


@router.post("/notes", response_class=HTMLResponse)
async def create_from_form(
    request: Request,
    service: NoteServiceDep,
    title: Annotated[str, Form()] = "",
    body: Annotated[str, Form()] = "",
    tags: Annotated[str, Form()] = "",
) -> Response:
    """Create a note from the HTML form, then redirect (303) so a reload does not re-post."""
    form = {"title": title, "body": body, "tags": tags}
    try:
        data = NoteCreate(
            title=title, body=body, tags=[tag for tag in tags.replace(",", " ").split() if tag]
        )
    except ValidationError as error:
        notes, total = await service.search(NoteFilters(limit=50))
        errors = [
            f"{'.'.join(map(str, problem['loc']))}: {problem['msg']}" for problem in error.errors()
        ]
        context = {"notes": notes, "total": total, "q": "", "errors": errors, "form": form}
        return templates.TemplateResponse(
            request, "index.html", context, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT
        )
    await service.create(data)
    return RedirectResponse(request.url_for("notes_page"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/notes/{note_id}/pin", response_class=HTMLResponse)
async def toggle_pin(request: Request, note_id: int, service: NoteServiceDep) -> Response:
    """HTMX: flip the pinned flag and return just this note's fragment."""
    note = await service.get(note_id)
    note = await service.update(note_id, NoteUpdate(pinned=not note.pinned))
    return templates.TemplateResponse(request, "_note.html", {"note": note})
