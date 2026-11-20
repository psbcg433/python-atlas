"""Dependencies shared by the routers, as Annotated aliases. A notes request resolves as:

ReaderServiceDep ── Security(get_note_service, ["notes:read"])
                      ├─ get_note_repository ─ get_session
                      ├─ get_clock
                      └─ get_current_principal (receives the accumulated scopes)
get_current_principal ─┬─ OAuth2PasswordBearer (Authorization: Bearer ...)
                       ├─ APIKeyHeader (X-API-Key)
                       └─ get_auth_service ─ get_session, get_redis, app.state
"""

import contextlib
import time
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timedelta
from typing import Annotated

import httpx
from arq.connections import ArqRedis
from fastapi import Depends, Request, Security
from fastapi.requests import HTTPConnection
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer, SecurityScopes
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from notes_api.auth import AuthService
from notes_api.cache import NoteCache
from notes_api.core.config import Settings
from notes_api.exceptions import AuthenticationError, PermissionDeniedError
from notes_api.mailer import LogMailer, Mailer
from notes_api.models import utc_now
from notes_api.oauth import OidcClient
from notes_api.ratelimit import FixedWindowRateLimiter
from notes_api.repositories import NoteRepository, SqlNoteRepository, SqlUserRepository
from notes_api.security import ALL_SCOPES, Principal, TokenService
from notes_api.services import LinkPreviewer, NoteService, Resolver, resolve_host


def get_app_settings(connection: HTTPConnection) -> Settings:
    """The settings this app was created with (HTTPConnection: works for WebSockets too)."""
    return connection.app.state.settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session and one transaction per request: commit on success, roll back on error."""
    async with request.app.state.session_factory() as session, session.begin():
        yield session


# scope="function": commit before the response is sent, so a failed commit is a 500/409,
# never a 200 for data that was not saved (the default scope would commit after sending).
SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]


def get_redis(connection: HTTPConnection) -> Redis:
    """The Redis client the lifespan created (tests override this with fakeredis)."""
    return connection.app.state.redis


def get_clock() -> Callable[[], datetime]:
    """The clock for timestamps (tests override it with dependency_overrides)."""
    return utc_now


def get_http_client(request: Request) -> httpx.AsyncClient:
    """The pooled HTTP client the lifespan created."""
    return request.app.state.http_client


def get_resolver() -> Resolver:
    """DNS resolution for link previews (tests override it: no real DNS in tests)."""
    return resolve_host


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
RedisDep = Annotated[Redis, Depends(get_redis)]
ClockDep = Annotated[Callable[[], datetime], Depends(get_clock)]
HttpClientDep = Annotated[httpx.AsyncClient, Depends(get_http_client)]


def get_note_repository(session: SessionDep) -> NoteRepository:
    """The SQL repository on this request's session."""
    return SqlNoteRepository(session)


RepositoryDep = Annotated[NoteRepository, Depends(get_note_repository)]


def get_auth_service(
    request: Request, session: SessionDep, redis: RedisDep, settings: SettingsDep, clock: ClockDep
) -> AuthService:
    """An AuthService on this request's session, with the app-wide hasher and secret."""
    tokens = TokenService(
        request.app.state.jwt_secret,
        settings.jwt_issuer,
        settings.jwt_audience,
        timedelta(minutes=settings.access_token_minutes),
        clock,
    )
    return AuthService(
        SqlUserRepository(session),
        tokens,
        request.app.state.password_hasher,
        request.app.state.dummy_hash,
        redis,
        request.app.state.session_factory,
        timedelta(days=settings.refresh_token_days),
        settings.admin_emails,
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


SESSION_COOKIE = "notes_session"
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/token", scopes=ALL_SCOPES, auto_error=False
)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_current_principal(
    security_scopes: SecurityScopes,
    auth: AuthServiceDep,
    token: Annotated[str | None, Depends(oauth2_scheme)],
    api_key: Annotated[str | None, Depends(api_key_header)],
) -> Principal:
    """Authenticate with a bearer token or an API key, then check the required scopes."""
    if token:
        principal = await auth.principal_from_access_token(token)
    elif api_key:
        principal = await auth.principal_from_api_key(api_key)
    else:
        raise AuthenticationError("not authenticated", security_scopes.scopes)
    missing = set(security_scopes.scopes) - principal.scopes
    if missing:
        raise PermissionDeniedError(f"missing scope(s): {' '.join(sorted(missing))}")
    return principal


CurrentPrincipal = Annotated[Principal, Security(get_current_principal)]


async def require_admin(
    principal: Annotated[Principal, Security(get_current_principal, scopes=["admin"])],
) -> Principal:
    """Role check on top of the scope check (OWASP API5: function-level authorization)."""
    if principal.role != "admin":
        raise PermissionDeniedError("admin role required")
    return principal


AdminPrincipal = Annotated[Principal, Depends(require_admin)]


def get_note_service(
    repository: RepositoryDep, clock: ClockDep, principal: CurrentPrincipal
) -> NoteService:
    """A NoteService limited to the caller's notes; route scopes flow down to the principal."""
    return NoteService(repository, clock, principal.user_id)


ReaderServiceDep = Annotated[NoteService, Security(get_note_service, scopes=["notes:read"])]
WriterServiceDep = Annotated[NoteService, Security(get_note_service, scopes=["notes:write"])]


def get_link_previewer(
    client: HttpClientDep, resolver: Annotated[Resolver, Depends(get_resolver)]
) -> LinkPreviewer:
    """A LinkPreviewer on the shared HTTP client, with SSRF checks."""
    return LinkPreviewer(client, resolver)


LinkPreviewerDep = Annotated[LinkPreviewer, Depends(get_link_previewer)]


def get_login_limiter(redis: RedisDep, settings: SettingsDep) -> FixedWindowRateLimiter:
    """The login/registration rate limiter (shared by every worker through Redis)."""
    return FixedWindowRateLimiter(
        redis, settings.login_rate_limit, settings.login_rate_window_seconds, "login"
    )


LoginLimiterDep = Annotated[FixedWindowRateLimiter, Depends(get_login_limiter)]


def get_oidc_client(settings: SettingsDep, client: HttpClientDep, redis: RedisDep) -> OidcClient:
    """The OpenID Connect client (the router checks settings.oauth_enabled first)."""
    return OidcClient(settings, client, redis)


OidcClientDep = Annotated[OidcClient, Depends(get_oidc_client)]


async def get_cookie_principal(request: Request, auth: AuthServiceDep) -> Principal | None:
    """The user of an HTML page, from the HttpOnly session cookie (None if absent or invalid)."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        return await auth.principal_from_access_token(token)
    except AuthenticationError:
        return None


CookiePrincipalDep = Annotated[Principal | None, Depends(get_cookie_principal)]


def get_queue(request: Request) -> ArqRedis:
    """The ARQ client for enqueuing jobs (tests override it with one on fakeredis)."""
    return request.app.state.queue


def get_mailer() -> Mailer:
    """Where emails go (tests override it with a fake that records messages)."""
    return LogMailer()


def get_note_cache(request: Request, redis: RedisDep, settings: SettingsDep) -> NoteCache:
    """Cache-aside for single notes, traced with the app's tracer."""
    return NoteCache(redis, settings.cache_ttl_seconds, tracer=request.app.state.tracer)


QueueDep = Annotated[ArqRedis, Depends(get_queue)]
MailerDep = Annotated[Mailer, Depends(get_mailer)]
NoteCacheDep = Annotated[NoteCache, Depends(get_note_cache)]


async def kick_relay(queue: ArqRedis) -> None:
    """Background task after a write: wake the outbox relay now instead of at the next cron
    tick. Best effort: if Redis is down, the cron job publishes the events later."""
    with contextlib.suppress(Exception):
        await queue.enqueue_job("relay_outbox", _job_id=f"relay-kick:{int(time.time())}")
