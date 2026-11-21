"""Per-user budgets on expensive routes, the per-user WebSocket cap, deleting an account."""

import pytest
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

from helpers import ANONYMOUS, USER_EMAIL, auth_headers, create, login, register
from notes_api.core.config import Settings


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """Small budgets; a one-day window, so no window boundary falls inside a test."""
    small = {"write_rate_limit": 3, "link_preview_rate_limit": 2, "export_rate_limit": 1}
    return settings.model_copy(
        update={**small, "user_rate_window_seconds": 86_400, "ws_connections_per_user": 2}
    )


def test_writes_are_limited_per_user(client: TestClient) -> None:
    """The fourth write is a 429 with Retry-After; reads and other users are unaffected."""
    for number in range(3):
        create(client, title=f"note {number}")
    refused = client.post("/api/v1/notes", json={"title": "one too many"})
    assert (refused.status_code, refused.json()["type"]) == (429, "/problems/rate-limited")
    assert int(refused.headers["Retry-After"]) > 0
    assert client.get("/api/v1/notes").json()["total"] == 3
    other = auth_headers(client, "other@example.com")
    assert client.post("/api/v1/notes", json={"title": "mine"}, headers=other).status_code == 201


def test_link_previews_and_exports_have_their_own_budgets(client: TestClient) -> None:
    """Each link-preview call can fetch five URLs and each export is a worker job."""
    note = create(client, body="no links here")
    codes = [client.get(f"/api/v1/notes/{note['id']}/links").status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    assert [client.post("/api/v1/exports").status_code for _ in range(2)] == [202, 429]


def test_websocket_cap_per_user(client: TestClient) -> None:
    """Two sockets are fine; the third is closed with 1008; closing one frees a slot."""
    token = client.headers["authorization"].removeprefix("Bearer ")
    with client.websocket_connect("/api/v1/ws") as first:
        first.send_json({"token": token})
        assert first.receive_json()["type"] == "ready"
        with client.websocket_connect("/api/v1/ws") as second:
            second.send_json({"token": token})
            assert second.receive_json()["type"] == "ready"
            with client.websocket_connect("/api/v1/ws") as third:
                third.send_json({"token": token})
                with pytest.raises(WebSocketDisconnect) as closed:
                    third.receive_json()
            assert (closed.value.code, closed.value.reason) == (1008, "too many open connections")
        with client.websocket_connect("/api/v1/ws") as again:
            again.send_json({"token": token})
            assert again.receive_json()["type"] == "ready"


def test_deleting_the_account_removes_everything(client: TestClient) -> None:
    """204; the token and the password stop working; the address can register again, empty."""
    create(client, title="private")
    assert client.delete("/api/v1/users/me").status_code == 204
    assert client.get("/api/v1/notes").status_code == 401
    assert login(client, USER_EMAIL).status_code == 401
    assert register(client, USER_EMAIL).status_code == 201
    fresh = auth_headers(client, USER_EMAIL)
    assert client.get("/api/v1/notes", headers=fresh).json()["total"] == 0
    assert client.delete("/api/v1/users/me", headers=ANONYMOUS).status_code == 401
