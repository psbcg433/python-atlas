"""OpenID Connect login against a mocked provider (respx): PKCE, state, nonce, ID-token checks."""

import asyncio
import base64
import hashlib
import json
import time
import urllib.parse
from collections.abc import Iterator
from typing import Any

import fakeredis
import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from helpers import ANONYMOUS, create_tables, fake_resolver, register
from notes_api.core.config import Settings
from notes_api.dependencies import get_redis, get_resolver
from notes_api.main import create_app
from notes_api.oauth import pkce_challenge

ISSUER = "https://id.example"
PROVIDER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWK = {
    **json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(PROVIDER_KEY.public_key())),
    "kid": "key-1",
    "use": "sig",
    "alg": "RS256",
}


def id_token(nonce: str, overrides: dict[str, Any] | None = None) -> str:
    """An ID token as the provider would sign it (overrides replace claims)."""
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": "notes-web",
        "sub": "user-42",
        "email": "oidc@example.com",
        "email_verified": True,
        "nonce": nonce,
        "iat": now,
        "exp": now + 300,
    }
    claims |= overrides or {}
    return jwt.encode(claims, PROVIDER_KEY, algorithm="RS256", headers={"kid": "key-1"})


@pytest.fixture
def oidc_client(settings: Settings, fake_redis: fakeredis.FakeAsyncRedis) -> Iterator[TestClient]:
    """An app with OpenID Connect configured for the fake provider."""
    configured = settings.model_copy(
        update={
            "oauth_client_id": "notes-web",
            "oauth_authorize_url": f"{ISSUER}/authorize",
            "oauth_token_url": f"{ISSUER}/token",
            "oauth_jwks_url": f"{ISSUER}/jwks",
            "oauth_issuer": ISSUER,
        }
    )
    asyncio.run(create_tables(configured))
    application = create_app(configured)
    application.dependency_overrides[get_redis] = lambda: fake_redis
    application.dependency_overrides[get_resolver] = lambda: fake_resolver
    with TestClient(application) as test_client:
        yield test_client


def start_login(client: TestClient) -> dict[str, str]:
    """GET /oauth/login and return the query parameters of the provider redirect."""
    response = client.get("/api/v1/auth/oauth/login", follow_redirects=False)
    assert response.status_code == 302
    location = urllib.parse.urlsplit(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == f"{ISSUER}/authorize"
    return dict(urllib.parse.parse_qsl(location.query))


def mock_provider(token_response: dict[str, Any]) -> respx.Route:
    """The provider's token and JWKS endpoints."""
    respx.get(f"{ISSUER}/jwks").respond(json={"keys": [JWK]})
    return respx.post(f"{ISSUER}/token").respond(json=token_response)


@respx.mock
def test_full_login_with_pkce(oidc_client: TestClient) -> None:
    """The callback exchanges the code with the PKCE verifier and returns our own tokens."""
    query = start_login(oidc_client)
    assert (query["code_challenge_method"], query["response_type"], query["scope"]) == (
        "S256",
        "code",
        "openid email",
    )
    token_route = mock_provider({"id_token": id_token(query["nonce"]), "token_type": "Bearer"})
    response = oidc_client.get(
        "/api/v1/auth/oauth/callback", params={"code": "abc", "state": query["state"]}
    )
    assert response.status_code == 200, response.text
    sent = dict(urllib.parse.parse_qsl(token_route.calls.last.request.content.decode()))
    assert pkce_challenge(sent["code_verifier"]) == query["code_challenge"]
    me = oidc_client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {response.json()['access_token']}"}
    )
    assert me.json()["email"] == "oidc@example.com"


@respx.mock
def test_state_is_single_use(oidc_client: TestClient) -> None:
    """An unknown or replayed state is refused before any call to the provider."""
    query = start_login(oidc_client)
    mock_provider({"id_token": id_token(query["nonce"])})
    params = {"code": "abc", "state": query["state"]}
    assert oidc_client.get("/api/v1/auth/oauth/callback", params=params).status_code == 200
    replay = oidc_client.get("/api/v1/auth/oauth/callback", params=params)
    assert (replay.status_code, replay.json()["detail"]) == (401, "unknown or expired login state")


@respx.mock
@pytest.mark.parametrize(
    ("overrides", "detail"),
    [
        ({"nonce": "another-login"}, "ID token nonce mismatch"),
        ({"email_verified": False}, "the provider did not confirm an email address"),
        ({"aud": "someone-else"}, "invalid ID token: Audience doesn't match"),
        ({"iss": "https://evil.example"}, "invalid ID token: Invalid issuer"),
    ],
)
def test_bad_id_tokens_are_refused(
    oidc_client: TestClient, overrides: dict[str, Any], detail: str
) -> None:
    """Nonce, verified email, audience and issuer are all checked."""
    query = start_login(oidc_client)
    mock_provider({"id_token": id_token(query["nonce"], overrides)})
    response = oidc_client.get(
        "/api/v1/auth/oauth/callback", params={"code": "abc", "state": query["state"]}
    )
    assert (response.status_code, response.json()["detail"]) == (401, detail)


@respx.mock
def test_existing_account_is_linked_by_verified_email(oidc_client: TestClient) -> None:
    """A user who registered with a password can also sign in with the provider."""
    registered = register(oidc_client, "oidc@example.com").json()
    query = start_login(oidc_client)
    mock_provider({"id_token": id_token(query["nonce"])})
    tokens = oidc_client.get(
        "/api/v1/auth/oauth/callback", params={"code": "abc", "state": query["state"]}
    ).json()
    me = oidc_client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.json()["id"] == registered["id"]


def test_login_is_404_when_not_configured(anonymous: TestClient) -> None:
    """Without provider settings the routes do not exist for clients."""
    assert (
        anonymous.get(
            "/api/v1/auth/oauth/login", headers=ANONYMOUS, follow_redirects=False
        ).status_code
        == 404
    )


def test_pkce_challenge_is_unpadded_base64url_sha256() -> None:
    """S256 (RFC 7636): base64url(SHA-256(ASCII verifier)) with the '=' padding removed."""
    verifier = "a-verifier-of-at-least-43-characters-0123456789"
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode()
    assert pkce_challenge(verifier) == expected.rstrip("=") and len(pkce_challenge(verifier)) == 43
