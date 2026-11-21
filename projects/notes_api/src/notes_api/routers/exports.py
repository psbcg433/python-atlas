"""/api/v1/exports: start an export job (202), follow its progress with Server-Sent Events."""

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse

from notes_api.dependencies import EXPORT_LIMIT, CurrentPrincipal, QueueDep, RedisDep, SettingsDep
from notes_api.exceptions import ExportNotFoundError
from notes_api.exports import add_progress, events_key, owner_key, progress_events, result_key

router = APIRouter(prefix="/exports", tags=["exports"])


async def check_owner(redis: RedisDep, export_id: str, user_id: int) -> None:
    """Someone else's (or an unknown) export is 'not found'."""
    if await redis.get(owner_key(export_id)) != str(user_id):
        raise ExportNotFoundError(export_id)


@router.post("", status_code=status.HTTP_202_ACCEPTED, dependencies=[EXPORT_LIMIT])
async def start_export(
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
    redis: RedisDep,
    queue: QueueDep,
    settings: SettingsDep,
) -> dict[str, str]:
    """Queue an export of all the caller's notes; 202 Accepted with where to look."""
    export_id = uuid.uuid4().hex
    ttl = settings.export_ttl_seconds
    await redis.set(owner_key(export_id), str(principal.user_id), ex=ttl)
    await add_progress(redis, export_id, ttl, status="queued", done=0, total=0)
    await queue.enqueue_job(
        "export_notes", export_id, principal.user_id, _job_id=f"export:{export_id}"
    )
    status_url = request.app.url_path_for("export_status", export_id=export_id)
    response.headers["Location"] = status_url
    return {"id": export_id, "status_url": status_url, "events_url": f"{status_url}/events"}


@router.get("/{export_id}")
async def export_status(
    export_id: str, principal: CurrentPrincipal, redis: RedisDep
) -> dict[str, object]:
    """The latest progress event (polling is the fallback for clients without SSE)."""
    await check_owner(redis, export_id, principal.user_id)
    latest = await redis.xrevrange(events_key(export_id), count=1)
    fields = latest[0][1] if latest else {"status": "unknown"}
    return {
        "id": export_id,
        **{key: int(value) if value.isdigit() else value for key, value in fields.items()},
    }


@router.get("/{export_id}/download")
async def download_export(
    export_id: str, principal: CurrentPrincipal, redis: RedisDep
) -> JSONResponse:
    """The finished export as a JSON file (404 until it is ready)."""
    await check_owner(redis, export_id, principal.user_id)
    result = await redis.get(result_key(export_id))
    if result is None:
        raise ExportNotFoundError(export_id)
    headers = {"Content-Disposition": f'attachment; filename="notes-{export_id}.json"'}
    return JSONResponse(json.loads(result), headers=headers)


@router.get("/{export_id}/events", response_class=StreamingResponse)
async def export_events(
    export_id: str,
    principal: CurrentPrincipal,
    redis: RedisDep,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    """text/event-stream of progress; a reconnecting EventSource resumes after Last-Event-ID."""
    await check_owner(redis, export_id, principal.user_id)
    return StreamingResponse(
        progress_events(redis, export_id, last_event_id or "0-0"),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},  # no proxy buffering
    )
