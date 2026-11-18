"""Register, log in, refresh with rotation and reuse detection, log out, rate limits, API keys."""

import pytest
from fastapi.testclient import TestClient

from helpers import ANONYMOUS, PASSWORD, USER_EMAIL, login, register

ME = "/api/v1/users/me"


def bearer(token: str) -> dict[str, str]:
    """An Authorization header."""
    return {"Authorization": f"Bearer {token}"}


def test_register_returns_the_user_without_secrets(anonymous: TestClient) -> None:
    """201 with id, email and role; no hash; emails are case-insensitive and unique."""
    response = register(anonymous, "Asha@Example.com")
    assert response.status_code == 201
    assert set(response.json()) == {"id", "email", "role", "created_at"}
    assert response.json()["email"] == "asha@example.com"
    duplicate = register(anonymous, "asha@example.com")
    assert (duplicate.status_code, duplicate.json()["type"]) == (409, "/problems/email-taken")


@pytest.mark.parametrize(
    "body",
    [
        {"email": "x@example.com", "password": "short"},
        {"email": "x@example.com", "password": "long enough pass", "role": "admin"},
    ],
)
def test_register_rejects_weak_passwords_and_role_fields(
    anonymous: TestClient, body: dict[str, str]
) -> None:
    """Passwords need 12+ characters; clients cannot choose their role (mass assignment)."""
    assert anonymous.post("/api/v1/auth/register", json=body).status_code == 422


def test_login_and_me(anonymous: TestClient) -> None:
    """The password grant returns a token pair; /users/me needs the access token."""
    register(anonymous, USER_EMAIL)
    tokens = login(anonymous, USER_EMAIL).json()
    assert (tokens["token_type"], tokens["expires_in"], tokens["scope"]) == (
        "bearer",
        900,
        "notes:read notes:write",
    )
    assert anonymous.get(ME, headers=bearer(tokens["access_token"])).json()["email"] == USER_EMAIL
    missing = anonymous.get(ME)
    assert (missing.status_code, missing.headers["www-authenticate"]) == (401, "Bearer")


def test_wrong_password_and_unknown_user_look_the_same(anonymous: TestClient) -> None:
    """Same status and message, so the API does not reveal which emails exist."""
    register(anonymous, USER_EMAIL)
    wrong = login(anonymous, USER_EMAIL, password="not the password")
    unknown = login(anonymous, "nobody@example.com")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"] == "incorrect email or password"


def test_refresh_rotates_and_detects_reuse(anonymous: TestClient) -> None:
    """A refresh token works once; replaying an old one revokes the whole family."""
    register(anonymous, USER_EMAIL)
    first = login(anonymous, USER_EMAIL).json()
    second = anonymous.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert second.status_code == 200 and second.json()["refresh_token"] != first["refresh_token"]
    replay = anonymous.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert (replay.status_code, replay.json()["detail"]) == (
        401,
        "refresh token reuse detected; please log in again",
    )
    newest = anonymous.post(
        "/api/v1/auth/refresh", json={"refresh_token": second.json()["refresh_token"]}
    )
    assert newest.status_code == 401  # the thief's (or the user's) newer token is revoked too


def test_logout_revokes_refresh_and_access_tokens(anonymous: TestClient) -> None:
    """After logout neither the refresh token nor the access token works."""
    register(anonymous, USER_EMAIL)
    tokens = login(anonymous, USER_EMAIL).json()
    body = {"refresh_token": tokens["refresh_token"]}
    assert (
        anonymous.post(
            "/api/v1/auth/logout", json=body, headers=bearer(tokens["access_token"])
        ).status_code
        == 204
    )
    assert anonymous.post("/api/v1/auth/refresh", json=body).status_code == 401
    denied = anonymous.get(ME, headers=bearer(tokens["access_token"]))
    assert (denied.status_code, denied.json()["detail"]) == (401, "access token revoked")


def test_login_is_rate_limited(anonymous: TestClient) -> None:
    """After the window's budget (10 in tests) the API answers 429 with Retry-After."""
    register(anonymous, USER_EMAIL)
    statuses = [login(anonymous, USER_EMAIL, password="guess").status_code for _ in range(10)]
    blocked = login(anonymous, USER_EMAIL, password=PASSWORD)  # even the right password waits
    assert set(statuses) == {401}
    assert (blocked.status_code, blocked.json()["type"]) == (429, "/problems/rate-limited")
    assert 1 <= int(blocked.headers["retry-after"]) <= 60


def test_scopes_limit_what_a_token_can_do(anonymous: TestClient) -> None:
    """A read-only token can list notes but not create them (403 names the missing scope)."""
    register(anonymous, USER_EMAIL)
    read_only = login(anonymous, USER_EMAIL, scope="notes:read").json()
    headers = bearer(read_only["access_token"])
    assert anonymous.get("/api/v1/notes", headers=headers).status_code == 200
    refused = anonymous.post("/api/v1/notes", json={"title": "x"}, headers=headers)
    assert (refused.status_code, refused.json()["detail"]) == (403, "missing scope(s): notes:write")
    too_much = login(anonymous, USER_EMAIL, scope="admin")
    assert too_much.status_code == 403  # an ordinary user cannot even ask for the admin scope


def test_tampered_token_is_rejected(client: TestClient) -> None:
    """Changing one character of the signature invalidates the token."""
    token = client.headers["authorization"].removeprefix("Bearer ")
    tampered = token[:-2] + ("A" if token[-2] != "A" else "B") + token[-1]
    assert client.get(ME, headers=bearer(tampered)).status_code == 401


def test_api_keys_are_shown_once_hashed_and_scoped(client: TestClient) -> None:
    """Create a read-only key, use it, list it without the secret, revoke it."""
    created = client.post(
        "/api/v1/users/me/api-keys", json={"name": "cli", "scopes": ["notes:read"]}
    )
    assert created.status_code == 201
    key = created.json()["key"]
    assert key.startswith("nk_") and created.json()["prefix"] == key[:10]
    with_key = {"X-API-Key": key, **ANONYMOUS}
    assert client.get("/api/v1/notes", headers=with_key).status_code == 200
    assert client.post("/api/v1/notes", json={"title": "x"}, headers=with_key).status_code == 403
    listed = client.get("/api/v1/users/me/api-keys").json()
    assert "key" not in listed[0] and listed[0]["last_used_at"] is not None
    assert client.delete(f"/api/v1/users/me/api-keys/{listed[0]['id']}").status_code == 204
    assert client.get("/api/v1/notes", headers=with_key).status_code == 401
    assert client.delete("/api/v1/users/me/api-keys/999").status_code == 404


def test_api_keys_cannot_create_api_keys(client: TestClient) -> None:
    """A leaked key must not be able to mint more keys."""
    key = client.post("/api/v1/users/me/api-keys", json={"name": "ci"}).json()["key"]
    response = client.post(
        "/api/v1/users/me/api-keys", json={"name": "more"}, headers={"X-API-Key": key, **ANONYMOUS}
    )
    assert response.status_code == 403
