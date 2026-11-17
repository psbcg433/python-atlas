"""Dependencies shared by the routers, exported as Annotated aliases.

Resolution graph of a notes request:

    NoteServiceDep ── get_note_service ──┬── get_note_repository ── get_session ── app.state
                                         └── get_clock
    ApiKeyDep ── require_api_key ──┬── get_app_settings ── request.app.state
                                   └── X-API-Key header (APIKeyHeader)
"""

import secrets
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from notes_api.core.config import Settings
from notes_api.models import utc_now
from notes_api.repositories import NoteRepository, SqlNoteRepository
from notes_api.services import LinkPreviewer, NoteService

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_app_settings(request: Request) -> Settings:
    """The settings this app was created with (create_app stores them on app.state)."""
    return request.app.state.settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session and one transaction per request: commit on success, roll back on error."""
    async with request.app.state.session_factory() as session, session.begin():
        yield session


# scope="function": commit before the response is sent, so a failed commit is a 500/409,
# never a 200 for data that was not saved (the default scope would commit after sending).
SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]


def get_note_repository(session: SessionDep) -> NoteRepository:
    """The SQL repository on this request's session."""
    return SqlNoteRepository(session)


def get_clock() -> Callable[[], datetime]:
    """The clock for timestamps (tests override it with dependency_overrides)."""
    return utc_now


def get_http_client(request: Request) -> httpx.AsyncClient:
    """The pooled HTTP client the lifespan created."""
    return request.app.state.http_client


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
RepositoryDep = Annotated[NoteRepository, Depends(get_note_repository)]
ClockDep = Annotated[Callable[[], datetime], Depends(get_clock)]
HttpClientDep = Annotated[httpx.AsyncClient, Depends(get_http_client)]


def get_note_service(repository: RepositoryDep, clock: ClockDep) -> NoteService:
    """A NoteService wired to this app's repository and clock (one per request)."""
    return NoteService(repository, clock)


def get_link_previewer(client: HttpClientDep) -> LinkPreviewer:
    """A LinkPreviewer on the shared HTTP client."""
    return LinkPreviewer(client)


async def require_api_key(
    settings: SettingsDep, api_key: Annotated[str | None, Depends(api_key_header)]
) -> None:
    """Router-level guard: 503 when no key is configured, 401 when the header is wrong."""
    if settings.api_key is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "admin API disabled: set NOTES_API_KEY"
        )
    expected = settings.api_key.get_secret_value().encode()
    if api_key is None or not secrets.compare_digest(api_key.encode(), expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing or invalid X-API-Key header")


NoteServiceDep = Annotated[NoteService, Depends(get_note_service)]
LinkPreviewerDep = Annotated[LinkPreviewer, Depends(get_link_previewer)]
ApiKeyDep = Depends(require_api_key)
