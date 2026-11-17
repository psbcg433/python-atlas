"""/api/v1/admin: bulk import (file upload), export and wipe. Every route needs X-API-Key."""

from http import HTTPStatus

from fastapi import APIRouter, UploadFile, status
from fastapi.responses import JSONResponse

from notes_api.dependencies import ApiKeyDep, NoteServiceDep, SettingsDep
from notes_api.exceptions import UploadRejectedError
from notes_api.schemas import ImportReport, NoteFilters, NoteRead
from notes_api.services import parse_import

ALLOWED_UPLOADS = {".json": {"application/json"}, ".csv": {"text/csv", "application/vnd.ms-excel"}}

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[ApiKeyDep])


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


@router.post("/import", response_model=ImportReport, status_code=status.HTTP_201_CREATED)
async def import_notes(
    file: UploadFile, service: NoteServiceDep, settings: SettingsDep
) -> ImportReport:
    """Create notes from an uploaded .json list or .csv file (all or nothing)."""
    content = await read_upload(file, settings.max_upload_bytes)
    notes = parse_import(file.filename or "", content)
    created = await service.import_notes(notes)
    return ImportReport(
        filename=file.filename or "", imported=len(created), ids=[note.id for note in created]
    )


@router.get("/export")
async def export_notes(service: NoteServiceDep) -> JSONResponse:
    """Every note as a downloadable JSON file."""
    notes, _total = await service.search(NoteFilters(limit=100, sort="created_at"))
    payload = [NoteRead.model_validate(note).model_dump(mode="json") for note in notes]
    headers = {"Content-Disposition": 'attachment; filename="notes.json"'}
    return JSONResponse(payload, headers=headers)


@router.delete("/notes")
async def delete_all_notes(service: NoteServiceDep) -> dict[str, int]:
    """Remove every note."""
    return {"deleted": await service.delete_all()}
