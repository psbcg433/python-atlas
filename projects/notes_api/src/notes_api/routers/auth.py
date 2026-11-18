"""/api/v1/auth: register, log in (OAuth2 password form), refresh, log out, OpenID Connect."""

import contextlib
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm

from notes_api.dependencies import (
    AuthServiceDep,
    LoginLimiterDep,
    MailerDep,
    OidcClientDep,
    SettingsDep,
    oauth2_scheme,
)
from notes_api.exceptions import AuthenticationError, RateLimitedError
from notes_api.mailer import send_welcome_email
from notes_api.models import User
from notes_api.ratelimit import FixedWindowRateLimiter
from notes_api.schemas import RefreshRequest, TokenPair, UserCreate, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


def client_ip(request: Request) -> str:
    """The peer address (behind a proxy, configure Uvicorn's --forwarded-allow-ips)."""
    return request.client.host if request.client else "unknown"


async def enforce_limit(limiter: FixedWindowRateLimiter, key: str) -> None:
    """Count one attempt; 429 with Retry-After once the window's budget is spent."""
    result = await limiter.hit(key)
    if not result.allowed:
        raise RateLimitedError(result.retry_after)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(
    data: UserCreate,
    request: Request,
    auth: AuthServiceDep,
    limiter: LoginLimiterDep,
    background: BackgroundTasks,
    mailer: MailerDep,
) -> User:
    """Create an account (rate limited); the welcome email goes out after the response."""
    await enforce_limit(limiter, f"register:{client_ip(request)}")
    user = await auth.register(data)
    background.add_task(send_welcome_email, mailer, user.email)
    return user


@router.post("/token", response_model=TokenPair)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    request: Request,
    auth: AuthServiceDep,
    limiter: LoginLimiterDep,
) -> TokenPair:
    """OAuth2 password grant: username = email; optional space-separated scope."""
    await enforce_limit(limiter, f"{client_ip(request)}:{form.username.lower()}")
    user = await auth.authenticate(form.username, form.password)
    return await auth.issue_tokens(user, auth.grant_scopes(user.role, form.scopes))


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, auth: AuthServiceDep) -> TokenPair:
    """Exchange a refresh token for a new pair (the old refresh token stops working)."""
    return await auth.refresh(body.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: RefreshRequest,
    auth: AuthServiceDep,
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> None:
    """Revoke the refresh-token family; also deny the access token sent, if any."""
    principal = None
    if token:
        with contextlib.suppress(AuthenticationError):
            principal = await auth.principal_from_access_token(token)
    await auth.logout(body.refresh_token, principal)


@router.get("/oauth/login", response_class=RedirectResponse, status_code=status.HTTP_302_FOUND)
async def oauth_login(settings: SettingsDep, oidc: OidcClientDep) -> RedirectResponse:
    """Start an OpenID Connect login: redirect to the provider (PKCE, state, nonce)."""
    if not settings.oauth_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "third-party login is not configured")
    return RedirectResponse(await oidc.authorization_url(), status_code=status.HTTP_302_FOUND)


@router.get("/oauth/callback", response_model=TokenPair)
async def oauth_callback(
    code: str, state: str, settings: SettingsDep, oidc: OidcClientDep, auth: AuthServiceDep
) -> TokenPair:
    """Finish the login: verify state, exchange the code, verify the ID token, issue tokens."""
    if not settings.oauth_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "third-party login is not configured")
    claims = await oidc.finish(code, state)
    return await auth.oidc_login(claims)
