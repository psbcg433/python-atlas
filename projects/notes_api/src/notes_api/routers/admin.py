"""/api/v1/admin: bulk import (file upload), export and wipe. Admin role + admin scope."""

import time
from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy import select

from notes_api.dependencies import (
    ADMIN_EXPORT_LIMIT,
    ADMIN_WRITE_LIMIT,
    NoteCacheDep,
    QueueDep,
    RepositoryDep,
    SessionDep,
    SettingsDep,
    WriterServiceDep,
    require_admin,
)
from notes_api.exceptions import UploadRejectedError
from notes_api.models import OutboxEvent
from notes_api.schemas import ImportReport, NoteFilters, NoteRead
from notes_api.services import parse_import

ALLOWED_UPLOADS = {".json": {"application/json"}, ".csv": {"text/csv", "application/vnd.ms-excel"}}

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


async def read_upload(upload: UploadFile, max_bytes: int) -> bytes:
    """The file's bytes after checking its extension, content type and size."""
    filename = upload.filename or ""
    extension = filename[filename.rfind(".") :].lower() if "." in filename else ""
    content_type = (upload.content_type or "").split(";")[0].strip()
    if content_type not in ALLOWED_UPLOADS.get(extension, set()):
        detail = f"expected a .json or .csv file, got {filename!r} ({content_type or 'no type'})"
        raise UploadRejectedError(detail, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
    content = await upload.read(max_bytes + 1)  # one byte more tells us it is too large
    if len(content) > max_bytes:
        raise UploadRejectedError(
            f"file is larger than {max_bytes} bytes", HTTPStatus.CONTENT_TOO_LARGE
        )
    return content


@router.post(
    "/import",
    response_model=ImportReport,
    status_code=status.HTTP_201_CREATED,
    dependencies=[ADMIN_WRITE_LIMIT],
)
async def import_notes(
    file: UploadFile, service: WriterServiceDep, settings: SettingsDep
) -> ImportReport:
    """Create notes (owned by the admin) from an uploaded .json list or .csv file."""
    content = await read_upload(file, settings.max_upload_bytes)
    notes = parse_import(file.filename or "", content)
    created = await service.import_notes(notes)
    ids = [note.id for note in created]
    return ImportReport(filename=file.filename or "", imported=len(created), ids=ids)


@router.get("/export", dependencies=[ADMIN_EXPORT_LIMIT])
async def export_notes(repository: RepositoryDep) -> JSONResponse:
    """Every user's notes as a downloadable JSON file."""
    notes, _total = await repository.search(NoteFilters(limit=100, sort="created_at"), None)
    payload = [NoteRead.model_validate(note).model_dump(mode="json") for note in notes]
    headers = {"Content-Disposition": 'attachment; filename="notes.json"'}
    return JSONResponse(payload, headers=headers)


@router.delete("/notes", dependencies=[ADMIN_WRITE_LIMIT])
async def delete_all_notes(repository: RepositoryDep) -> dict[str, int]:
    """Remove every note of every user."""
    return {"deleted": await repository.delete_all()}


@router.get("/cache-stats")
async def cache_stats(cache: NoteCacheDep) -> dict[str, float]:
    """Note-cache hits, misses and hit rate."""
    return await cache.stats()


@router.get("/webhooks/dead")
async def dead_webhooks(session: SessionDep) -> list[dict[str, object]]:
    """The dead-letter list: events whose webhook failed on every attempt."""
    statement = (
        select(OutboxEvent).where(OutboxEvent.webhook_status == "dead").order_by(OutboxEvent.id)
    )
    events = await session.scalars(statement)
    return [
        {
            "id": event.id,
            "type": event.event_type,
            "attempts": event.webhook_attempts,
            "error": event.last_error,
        }
        for event in events
    ]


@router.post(
    "/webhooks/dead/{event_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[ADMIN_WRITE_LIMIT],
)
async def retry_dead_webhook(
    event_id: int, session: SessionDep, queue: QueueDep
) -> dict[str, object]:
    """Send a dead-lettered event again (after the receiver was fixed)."""
    event = await session.get(OutboxEvent, event_id)
    if event is None or event.webhook_status != "dead":
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no dead webhook for event {event_id}")
    event.webhook_status, event.webhook_attempts = "pending", 0
    await queue.enqueue_job(
        "deliver_webhook", event_id, _job_id=f"webhook:{event_id}:retry:{time.time_ns()}"
    )
    return {"id": event_id, "status": "pending"}
