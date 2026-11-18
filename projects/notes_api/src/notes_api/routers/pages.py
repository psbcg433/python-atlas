"""Server-rendered pages: cookie login, CSRF protection, Jinja2 templates, HTMX partials.

Browsers send cookies automatically, so every state-changing form needs a CSRF defence. Two
layers: the session cookie is SameSite=Lax (not sent on cross-site POSTs), and every form or
HTMX request must echo a random token that is also stored in a cookie (double submit).
"""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, Header, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from notes_api.dependencies import (
    SESSION_COOKIE,
    AuthServiceDep,
    ClockDep,
    CookiePrincipalDep,
    LoginLimiterDep,
    RepositoryDep,
    SettingsDep,
)
from notes_api.exceptions import AuthenticationError, PermissionDeniedError, RateLimitedError
from notes_api.schemas import NoteCreate, NoteFilters, NoteUpdate
from notes_api.security import ROLE_SCOPES, new_secret, same_secret
from notes_api.services import NoteService

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)
CSRF_COOKIE = "notes_csrf"
CSRF_HEADER = "X-CSRF-Token"

router = APIRouter(include_in_schema=False)  # HTML for people, not part of the JSON API


def csrf_token(request: Request) -> str:
    """The browser's CSRF token (a new one if it has none yet)."""
    return request.cookies.get(CSRF_COOKIE) or new_secret(16)


def check_csrf(request: Request, sent: str | None) -> None:
    """The token in the form (or the X-CSRF-Token header) must match the cookie."""
    cookie = request.cookies.get(CSRF_COOKIE)
    sent = sent or request.headers.get(CSRF_HEADER)
    if not cookie or not sent or not same_secret(cookie, sent):
        raise PermissionDeniedError("CSRF token missing or invalid")


def render(
    request: Request,
    settings_secure: bool,
    template: str,
    context: dict[str, object],
    status_code: int = 200,
) -> Response:
    """Render a template and (re)set the CSRF cookie the page's forms will echo."""
    token = csrf_token(request)
    response = templates.TemplateResponse(
        request, template, {**context, "csrf_token": token}, status_code=status_code
    )
    response.set_cookie(
        CSRF_COOKIE, token, httponly=True, secure=settings_secure, samesite="strict"
    )
    return response


def to_login() -> RedirectResponse:
    """303 to the login page (after a POST the browser follows it with a GET)."""
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, settings: SettingsDep) -> Response:
    """The login form."""
    return render(request, settings.cookie_secure, "login.html", {"error": None, "email": ""})


@router.post("/login", response_class=HTMLResponse)
async def login_form(
    request: Request,
    settings: SettingsDep,
    auth: AuthServiceDep,
    limiter: LoginLimiterDep,
    email: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    csrf: Annotated[str | None, Form(alias="csrf_token")] = None,
) -> Response:
    """Check CSRF and the password, then set an HttpOnly session cookie and redirect."""
    check_csrf(request, csrf)
    host = request.client.host if request.client else "unknown"
    try:
        if not (await limiter.hit(f"{host}:{email.lower()}")).allowed:
            raise RateLimitedError(settings.login_rate_window_seconds)
        user = await auth.authenticate(email, password)
    except (AuthenticationError, RateLimitedError) as error:
        context = {"error": str(error), "email": email}
        return render(
            request, settings.cookie_secure, "login.html", context, status_code=error.status_code
        )
    token, lifetime = auth.tokens.create_access_token(user.id, user.role, ROLE_SCOPES[user.role])
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=lifetime,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    return response


@router.post("/logout")
async def logout_form(
    request: Request,
    principal: CookiePrincipalDep,
    auth: AuthServiceDep,
    csrf: Annotated[str | None, Form(alias="csrf_token")] = None,
) -> Response:
    """Deny the session token and delete the cookie."""
    check_csrf(request, csrf)
    if principal is not None:
        await auth.deny_access_token(principal)
    response = to_login()
    response.delete_cookie(SESSION_COOKIE)
    return response


@router.get("/", response_class=HTMLResponse)
async def notes_page(
    request: Request,
    settings: SettingsDep,
    principal: CookiePrincipalDep,
    repository: RepositoryDep,
    clock: ClockDep,
    q: str = "",
    hx_request: Annotated[str | None, Header()] = None,
) -> Response:
    """The signed-in user's notes; for an HTMX search request only the list fragment."""
    if principal is None:
        return to_login()
    service = NoteService(repository, clock, principal.user_id)
    notes, total = await service.search(NoteFilters(q=q or None, limit=50))
    context = {"notes": notes, "total": total, "q": q, "errors": [], "form": {}, "user": principal}
    template = "_notes.html" if hx_request == "true" else "index.html"
    return render(request, settings.cookie_secure, template, context)


@router.post("/notes", response_class=HTMLResponse)
async def create_from_form(
    request: Request,
    settings: SettingsDep,
    principal: CookiePrincipalDep,
    repository: RepositoryDep,
    clock: ClockDep,
    title: Annotated[str, Form()] = "",
    body: Annotated[str, Form()] = "",
    tags: Annotated[str, Form()] = "",
    csrf: Annotated[str | None, Form(alias="csrf_token")] = None,
) -> Response:
    """Create a note from the form, then redirect (303) so a reload does not re-post."""
    if principal is None:
        return to_login()
    check_csrf(request, csrf)
    service = NoteService(repository, clock, principal.user_id)
    form = {"title": title, "body": body, "tags": tags}
    try:
        data = NoteCreate(title=title, body=body, tags=tags.replace(",", " ").split())
    except ValidationError as error:
        notes, total = await service.search(NoteFilters(limit=50))
        errors = [f"{'.'.join(map(str, item['loc']))}: {item['msg']}" for item in error.errors()]
        context = {
            "notes": notes,
            "total": total,
            "q": "",
            "errors": errors,
            "form": form,
            "user": principal,
        }
        return render(request, settings.cookie_secure, "index.html", context, status_code=422)
    await service.create(data)
    return RedirectResponse(request.url_for("notes_page"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/notes/{note_id}/pin", response_class=HTMLResponse)
async def toggle_pin(
    request: Request,
    note_id: int,
    principal: CookiePrincipalDep,
    repository: RepositoryDep,
    clock: ClockDep,
) -> Response:
    """HTMX: flip the pinned flag and return just this note's fragment."""
    if principal is None:
        return to_login()
    check_csrf(request, None)  # HTMX sends the token in the X-CSRF-Token header
    service = NoteService(repository, clock, principal.user_id)
    note = await service.get(note_id)
    note = await service.update(note_id, NoteUpdate(pinned=not note.pinned))
    return templates.TemplateResponse(request, "_note.html", {"note": note})
