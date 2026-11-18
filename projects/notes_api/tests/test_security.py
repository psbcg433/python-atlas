"""Password rehashing, forged and expired tokens, log redaction, SSRF protection."""

import asyncio
import base64
import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
import respx
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from helpers import ANONYMOUS, USER_EMAIL, create, login, register
from notes_api.core.config import Settings
from notes_api.core.logging import REDACTED, RedactingFilter, redact_text
from notes_api.db import create_engine_from_settings
from notes_api.main import create_app
from notes_api.security import TokenService, make_password_hasher

ME = "/api/v1/users/me"


def b64(data: dict[str, object]) -> str:
    """base64url(JSON) without padding, as in a JWT."""
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def stored_hash(settings: Settings, email: str) -> str:
    """The password hash in the database."""

    async def read() -> str:
        """One SELECT."""
        engine = create_engine_from_settings(settings)
        async with engine.connect() as connection:
            query = sa.text("SELECT password_hash FROM users WHERE email = :email")
            value = (await connection.execute(query, {"email": email})).scalar_one()
        await engine.dispose()
        return value

    return asyncio.run(read())


def test_login_rehashes_outdated_hashes(
    anonymous: TestClient, app: FastAPI, settings: Settings
) -> None:
    """Raising the Argon2 cost upgrades each user's hash at their next successful login."""
    register(anonymous, USER_EMAIL)
    assert ",t=1," in stored_hash(settings, USER_EMAIL)
    app.state.password_hasher = make_password_hasher(time_cost=2, memory_kib=64)
    assert login(anonymous, USER_EMAIL).status_code == 200
    assert ",t=2," in stored_hash(settings, USER_EMAIL)


@pytest.mark.parametrize("header", [{"alg": "none", "typ": "JWT"}, {"alg": "RS256", "typ": "JWT"}])
def test_tokens_with_another_algorithm_are_rejected(
    anonymous: TestClient, header: dict[str, str]
) -> None:
    """The server fixes the algorithm (HS256); 'none' and algorithm-confusion tokens fail."""
    register(anonymous, USER_EMAIL)
    claims = {
        "sub": "1",
        "iss": "notes-api",
        "aud": "notes-api",
        "exp": 4_102_444_800,
        "iat": 1,
        "jti": "x",
        "scope": "notes:read",
        "type": "access",
    }
    forged = f"{b64(header)}.{b64(claims)}.{'' if header['alg'] == 'none' else 'c2ln'}"
    assert anonymous.get(ME, headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_expired_and_foreign_tokens_are_rejected(anonymous: TestClient, app: FastAPI) -> None:
    """Expiry, issuer and audience are all checked."""
    register(anonymous, USER_EMAIL)
    secret = app.state.jwt_secret
    past = TokenService(
        secret,
        "notes-api",
        "notes-api",
        timedelta(minutes=5),
        lambda: datetime.now(UTC) - timedelta(hours=1),
    )
    other_audience = TokenService(
        secret, "notes-api", "another-api", timedelta(minutes=5), lambda: datetime.now(UTC)
    )
    expired, _ = past.create_access_token(1, "user", {"notes:read"})
    foreign, _ = other_audience.create_access_token(1, "user", {"notes:read"})
    response = anonymous.get(ME, headers={"Authorization": f"Bearer {expired}"})
    assert (response.status_code, response.json()["detail"]) == (401, "access token expired")
    assert anonymous.get(ME, headers={"Authorization": f"Bearer {foreign}"}).status_code == 401


def test_redaction_of_logged_secrets(caplog: pytest.LogCaptureFixture) -> None:
    """Bearer tokens, JWT-shaped strings, API keys and key=value secrets never reach a handler."""
    logger = logging.getLogger("notes_api.redaction-test")
    logger.addFilter(RedactingFilter())
    with caplog.at_level(logging.INFO, logger="notes_api.redaction-test"):
        logger.info("Authorization: Bearer abc.def.ghi password=hunter2 key=%s", "nk_" + "a" * 30)
        logger.info("payload %(user)s", {"user": "asha", "refresh_token": "r" * 20})
    text = caplog.text
    assert "hunter2" not in text and "abc.def.ghi" not in text and "nk_aaaa" not in text
    assert f"Bearer {REDACTED}" in text and f"password={REDACTED}" in text and "asha" in text
    assert redact_text("token: eyJhbGciOi.eyJzdWIi.c2ln") == f"token: {REDACTED}"


@respx.mock
@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://intranet.example/admin", "blocked: not a public address"),
        ("http://metadata.example/latest/meta-data", "blocked: not a public address"),
        ("http://mixed.example/", "blocked: not a public address"),
        ("http://127.0.0.1:8000/admin", "blocked: not a public address"),
        ("http://unknown.example/", "host does not resolve"),
    ],
)
def test_link_previews_refuse_private_targets(client: TestClient, url: str, reason: str) -> None:
    """SSRF (OWASP API7): private, loopback, link-local and unresolvable hosts are never fetched."""
    note = create(client, body=f"see {url}")
    assert client.get(f"/api/v1/notes/{note['id']}/links").json() == [
        {"url": url, "status_code": None, "title": None, "error": reason}
    ]
    assert respx.calls.call_count == 0


@respx.mock
def test_link_previews_do_not_follow_redirects(client: TestClient) -> None:
    """A public page that redirects (possibly to a private address) is not followed."""
    respx.get("https://docs.example/old").respond(302, headers={"Location": "http://10.0.0.7/"})
    note = create(client, body="https://docs.example/old")
    preview = client.get(f"/api/v1/notes/{note['id']}/links").json()[0]
    assert (preview["status_code"], preview["error"]) == (302, "redirect not followed")


def test_anonymous_cannot_read_notes(client: TestClient) -> None:
    """Every notes route needs credentials (401 + WWW-Authenticate with the scope)."""
    response = client.get("/api/v1/notes", headers=ANONYMOUS)
    assert (response.status_code, response.headers["www-authenticate"]) == (
        401,
        'Bearer scope="notes:read"',
    )


def test_placeholder_jwt_secret_is_never_used(settings: Settings) -> None:
    """Copying .env.example unchanged must not sign tokens with 'change-me'."""
    app = create_app(settings.model_copy(update={"jwt_secret": SecretStr("change-me")}))
    assert app.state.jwt_secret != "change-me" and len(app.state.jwt_secret) >= 40
