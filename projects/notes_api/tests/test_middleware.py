"""Request ids, Server-Timing, GZip, CORS and the order of the middleware stack."""

import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from helpers import create
from notes_api.core.middleware import RequestIdMiddleware, TimingMiddleware


def test_request_id_is_generated_echoed_or_replaced(client: TestClient) -> None:
    """No header → a new hex id; a safe header is reused; an unsafe one is replaced."""
    generated = client.get("/health").headers["x-request-id"]
    assert re.fullmatch(r"[0-9a-f]{32}", generated)
    assert (
        client.get("/health", headers={"X-Request-ID": "abc-123"}).headers["x-request-id"]
        == "abc-123"
    )
    replaced = client.get("/health", headers={"X-Request-ID": "bad id\twith spaces"}).headers[
        "x-request-id"
    ]
    assert re.fullmatch(r"[0-9a-f]{32}", replaced)


def test_problem_bodies_carry_the_request_id(client: TestClient) -> None:
    """The id in the error body matches the header, so a client can quote it in a report."""
    response = client.get("/api/v1/notes/99", headers={"X-Request-ID": "trace-42"})
    assert response.json()["request_id"] == response.headers["x-request-id"] == "trace-42"


def test_server_timing_header(client: TestClient) -> None:
    """Every response says how long the app took, in milliseconds."""
    assert re.fullmatch(r"app;dur=\d+\.\d", client.get("/health").headers["server-timing"])


def test_large_responses_are_gzipped(client: TestClient) -> None:
    """Responses over 1000 bytes are compressed when the client accepts gzip."""
    for number in range(10):
        create(client, title=f"Note {number}", body="lorem ipsum " * 20)
    big = client.get("/api/v1/notes", headers={"Accept-Encoding": "gzip"})
    small = client.get("/health", headers={"Accept-Encoding": "gzip"})
    assert big.headers["content-encoding"] == "gzip"
    assert "content-encoding" not in small.headers


def test_cors_preflight_for_an_allowed_and_a_foreign_origin(client: TestClient) -> None:
    """The configured origin may send X-API-Key; other origins get no CORS headers."""
    preflight = {
        "Access-Control-Request-Method": "PATCH",
        "Access-Control-Request-Headers": "x-api-key",
    }
    allowed = client.options(
        "/api/v1/notes/1", headers={"Origin": "http://localhost:5173", **preflight}
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "PATCH" in allowed.headers["access-control-allow-methods"]
    foreign = client.options(
        "/api/v1/notes/1", headers={"Origin": "https://evil.example", **preflight}
    )
    assert foreign.status_code == 400
    assert "access-control-allow-origin" not in foreign.headers


def test_simple_cors_request_exposes_headers(client: TestClient) -> None:
    """A cross-origin GET may read X-Request-ID because the app exposes it."""
    response = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert "X-Request-ID" in response.headers["access-control-expose-headers"]


def test_middleware_order(app: FastAPI) -> None:
    """Outermost first: request id, CORS, GZip, timing (the last one added runs first)."""
    names = [middleware.cls.__name__ for middleware in app.user_middleware]
    assert names == ["RequestIdMiddleware", "CORSMiddleware", "GZipMiddleware", "TimingMiddleware"]
    assert {RequestIdMiddleware, TimingMiddleware} <= {
        middleware.cls for middleware in app.user_middleware
    }
