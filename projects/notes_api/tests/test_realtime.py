"""WebSocket live updates: first-message authentication, Redis fan-out, heartbeats."""

import json

import fakeredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

from notes_api.events import user_channel


def token_of(client: TestClient) -> str:
    """The logged-in client's access token."""
    return client.headers["authorization"].removeprefix("Bearer ")


def test_socket_needs_a_valid_token(client: TestClient) -> None:
    """A wrong first message closes the socket with 1008 (policy violation)."""
    with client.websocket_connect("/api/v1/ws") as websocket:
        websocket.send_json({"token": "not-a-token"})
        with pytest.raises(WebSocketDisconnect) as closed:
            websocket.receive_json()
    assert closed.value.code == 1008


def test_events_published_in_redis_reach_the_socket(
    client: TestClient, fake_redis: fakeredis.FakeAsyncRedis, app: FastAPI
) -> None:
    """Whatever process publishes on the user's channel, the socket forwards it."""
    with client.websocket_connect("/api/v1/ws") as websocket:
        websocket.send_json({"token": token_of(client)})
        assert websocket.receive_json() == {"type": "ready", "user_id": 1}
        assert app.state.connections.count() == 1
        event = {"id": 7, "type": "note.updated", "data": {"note_id": 3}}
        client.portal.call(fake_redis.publish, user_channel(1), json.dumps(event))
        client.portal.call(fake_redis.publish, user_channel(2), json.dumps({"id": 8}))  # not ours
        assert websocket.receive_json() == event
        websocket.send_json({"type": "ping"})
        assert websocket.receive_json() == {"type": "pong"}
    assert app.state.connections.count() == 0


def test_heartbeat_pings(client: TestClient, app: FastAPI) -> None:
    """The server pings idle clients every ws_heartbeat_seconds."""
    app.state.settings.ws_heartbeat_seconds = 0.1
    with client.websocket_connect("/api/v1/ws") as websocket:
        websocket.send_json({"token": token_of(client)})
        websocket.receive_json()
        assert websocket.receive_json() == {"type": "ping"}
