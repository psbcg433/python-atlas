"""/api/v1/users/me: the current user and their API keys."""

from typing import Annotated

from fastapi import APIRouter, Path, status

from notes_api.dependencies import AuthServiceDep, CurrentPrincipal, LinkPreviewerDep
from notes_api.exceptions import AuthenticationError, InvalidWebhookError, PermissionDeniedError
from notes_api.models import ApiKey, User
from notes_api.schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyRead, UserRead, WebhookSettings
from notes_api.security import new_secret

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
async def me(principal: CurrentPrincipal, auth: AuthServiceDep) -> User:
    """Who am I?"""
    user = await auth.users.user_by_id(principal.user_id)
    if user is None:
        raise AuthenticationError("account disabled")
    return user


@router.post("/me/api-keys", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    data: ApiKeyCreate, principal: CurrentPrincipal, auth: AuthServiceDep
) -> dict[str, object]:
    """Create a key; its full value appears in this response only."""
    if principal.method != "token":
        raise PermissionDeniedError("API keys cannot create API keys; log in first")
    key, raw_key = await auth.create_api_key(principal, data)
    return {**ApiKeyRead.model_validate(key).model_dump(), "key": raw_key}


@router.get("/me/api-keys", response_model=list[ApiKeyRead])
async def list_api_keys(principal: CurrentPrincipal, auth: AuthServiceDep) -> list[ApiKey]:
    """The caller's keys, without their secrets."""
    return await auth.users.api_keys_of(principal.user_id)


@router.delete("/me/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: Annotated[int, Path(ge=1)], principal: CurrentPrincipal, auth: AuthServiceDep
) -> None:
    """Revoke one of the caller's keys."""
    await auth.revoke_api_key(principal, key_id)


@router.get("/me/webhook")
async def get_webhook(principal: CurrentPrincipal, auth: AuthServiceDep) -> dict[str, str | None]:
    """Where note events are POSTed (the secret is never shown again)."""
    user = await auth.users.user_by_id(principal.user_id)
    return {"url": user.webhook_url if user else None}


@router.put("/me/webhook")
async def set_webhook(
    body: WebhookSettings,
    principal: CurrentPrincipal,
    auth: AuthServiceDep,
    previewer: LinkPreviewerDep,
) -> dict[str, str]:
    """Register a public HTTPS/HTTP URL; returns a new signing secret, once."""
    if reason := await previewer.check_url(str(body.url)):  # same SSRF rules as link previews
        raise InvalidWebhookError(f"{body.url}: {reason}")
    user = await auth.users.user_by_id(principal.user_id)
    if user is None:
        raise AuthenticationError("account disabled")
    user.webhook_url, user.webhook_secret = str(body.url), f"whsec_{new_secret(24)}"
    return {"url": user.webhook_url, "secret": user.webhook_secret}


@router.delete("/me/webhook", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(principal: CurrentPrincipal, auth: AuthServiceDep) -> None:
    """Stop sending webhooks."""
    user = await auth.users.user_by_id(principal.user_id)
    if user is not None:
        user.webhook_url = user.webhook_secret = None
