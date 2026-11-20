"""Observability: correlated JSON logs, Prometheus metrics, OpenTelemetry spans, probes, Sentry."""

import importlib.util
import io
import json
import logging
from typing import Any

import pytest
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from helpers import create
from notes_api.core.logging import configure_logging
from notes_api.dependencies import get_redis


def json_lines(buffer: io.StringIO) -> list[dict[str, Any]]:
    """The log output, one dict per line."""
    return [json.loads(line) for line in buffer.getvalue().splitlines() if line.startswith("{")]


def test_access_log_is_json_with_request_and_trace_ids(client: TestClient, app: FastAPI) -> None:
    """One line per request; its trace id is the server span's trace id."""
    buffer = io.StringIO()
    configure_logging("INFO", json_output=True, stream=buffer)
    client.get("/api/v1/notes", headers={"X-Request-ID": "req-123"})
    access = [line for line in json_lines(buffer) if line["event"] == "request"][-1]
    assert (access["request_id"], access["status"], access["method"]) == ("req-123", 200, "GET")
    assert access["level"] == "info" and access["timestamp"].endswith("Z")
    spans = app.state.span_exporter.get_finished_spans()
    server_trace_ids = {format(span.context.trace_id, "032x") for span in spans}
    assert access["trace_id"] in server_trace_ids


def test_secrets_never_reach_the_logs() -> None:
    """stdlib and structlog records are redacted the same way."""
    buffer = io.StringIO()
    configure_logging("INFO", json_output=True, stream=buffer)
    logging.getLogger("notes_api.test").warning("retry with password=%s", "hunter2")
    structlog.get_logger("notes_api.test").info("key used", api_key="nk_" + "x" * 24)
    first, second = json_lines(buffer)[-2:]
    assert first["event"] == "retry with password=[REDACTED]"
    assert second["api_key"] == "[REDACTED]"


def test_metrics_use_route_templates(client: TestClient) -> None:
    """Counters and histograms are labelled by route template, never by raw path."""
    note_id = create(client, title="Metric me")["id"]
    client.get(f"/api/v1/notes/{note_id}")
    client.get("/api/v1/notes/987654")
    client.get("/no/such/page")
    text = client.get("/metrics").text
    route = 'route="/api/v1/notes/{note_id}"'
    assert f'notes_http_requests_total{{method="GET",{route},status="200"}}' in text
    assert f'{route},status="404"' in text
    assert 'route="unmatched"' in text
    assert f'notes_http_request_duration_seconds_bucket{{le="0.2",method="GET",{route}}}' in text
    assert 'notes_writes_total{operation="created"}' in text
    assert 'notes_cache_lookups_total{result="miss"}' in text
    assert f'/api/v1/notes/{note_id}"' not in text


def test_spans_for_requests_and_the_cache(client: TestClient, app: FastAPI) -> None:
    """The instrumentation makes a server span; NoteCache adds a child span with cache.hit."""
    note_id = create(client, title="Trace me")["id"]
    app.state.span_exporter.clear()
    client.get(f"/api/v1/notes/{note_id}")
    client.get(f"/api/v1/notes/{note_id}")
    spans = app.state.span_exporter.get_finished_spans()
    cache_spans = [span for span in spans if span.name == "cache.get_or_load"]
    assert [span.attributes["cache.hit"] for span in cache_spans] == [False, True]
    server = [span for span in spans if span.kind.name == "SERVER"]
    assert len(server) == 2
    assert server[0].attributes["http.status_code"] == 200
    assert server[0].attributes["http.route"].startswith("/api/v1/notes/{note_id")
    assert cache_spans[0].parent.span_id == server[0].context.span_id


def test_probes(client: TestClient, app: FastAPI, settings: Any) -> None:
    """Liveness never touches dependencies; readiness and startup report each check."""
    assert client.get("/health/live").json() == {"status": "ok"}
    ready = client.get("/health/ready")
    assert ready.json()["checks"] == {"database": "ok", "redis": "ok"}
    assert client.get("/health/startup").status_code == 200  # check_migrations=False in tests


class BrokenRedis:
    """A Redis client whose server is gone."""

    async def ping(self) -> bool:
        """Fail like a refused connection."""
        raise ConnectionError("connection refused")


def test_readiness_fails_when_redis_is_down(client: TestClient, app: FastAPI) -> None:
    """503 with the failing check named; liveness stays 200."""
    app.dependency_overrides[get_redis] = BrokenRedis
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["redis"] == "unavailable: ConnectionError"
    assert client.get("/health/live").status_code == 200


def test_startup_waits_for_migrations(settings: Any, app: FastAPI) -> None:
    """With the check on, a schema made by create_all (no alembic_version) is not ready."""
    app.state.settings = settings.model_copy(update={"check_migrations": True})
    with TestClient(app) as anonymous:
        response = anonymous.get("/health/startup")
    assert response.status_code == 503
    assert response.json()["checks"]["migrations"] == "at None, need 0006"


@pytest.mark.skipif(importlib.util.find_spec("sentry_sdk") is None, reason="sentry-sdk missing")
def test_sentry_captures_errors_without_secrets(settings: Any) -> None:
    """An unhandled error reaches Sentry's transport, with the Authorization header scrubbed."""
    import sentry_sdk
    from sentry_sdk.transport import Transport

    from notes_api.core.sentry import install_sentry

    class CapturingTransport(Transport):
        """Keeps envelopes instead of sending them."""

        def __init__(self) -> None:
            """Start empty."""
            super().__init__()
            self.events: list[dict[str, Any]] = []

        def capture_envelope(self, envelope: Any) -> None:
            """Store the event of each envelope."""
            if (event := envelope.get_event()) is not None:
                self.events.append(event)

    transport = CapturingTransport()
    dsn = SecretStr("https://public@sentry.example/1")
    sentry_settings = settings.model_copy(update={"sentry_dsn": dsn})
    try:
        assert install_sentry(sentry_settings, transport=transport)
        sentry_sdk.capture_exception(RuntimeError("boom"))
        sentry_sdk.flush()
        assert transport.events and transport.events[0]["exception"]["values"][0]["type"] == (
            "RuntimeError"
        )
        scrubbed = {"request": {"headers": {"Authorization": "Bearer abc.def.ghi", "X": "1"}}}
        from notes_api.core.sentry import scrub_event

        assert scrub_event(scrubbed, {})["request"]["headers"] == {
            "Authorization": "[REDACTED]",
            "X": "1",
        }
    finally:
        sentry_sdk.init()  # no DSN: back to a disabled client
