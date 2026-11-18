"""Exports: 202 + a queued job, progress in a Redis Stream, Server-Sent Events, download."""

from typing import Any

import fakeredis
import pytest
from arq.connections import ArqRedis
from fastapi.testclient import TestClient

from helpers import auth_headers, create
from notes_api.core.config import Settings
from notes_api.db import create_engine_from_settings, make_session_factory
from notes_api.worker import export_notes


@pytest.fixture
def started(client: TestClient) -> dict[str, str]:
    """Three notes, then POST /exports."""
    for number in range(3):
        create(client, title=f"Note {number}")
    response = client.post("/api/v1/exports")
    assert (
        response.status_code == 202
        and response.headers["location"] == response.json()["status_url"]
    )
    return response.json()


def run_job(
    client: TestClient, settings: Settings, fake_redis: fakeredis.FakeAsyncRedis, export_id: str
) -> int:
    """What the worker would do with the queued job."""
    ctx: dict[str, Any] = {
        "settings": settings,
        "session_factory": make_session_factory(create_engine_from_settings(settings)),
        "text_redis": fake_redis,
    }
    return client.portal.call(export_notes, ctx, export_id, 1)


def sse_messages(text: str) -> list[dict[str, str]]:
    """Parse text/event-stream into dicts of fields."""
    messages = []
    for block in text.strip().split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if not line.startswith(":")
        )
        messages.append(fields)
    return messages


def test_export_job_is_queued(
    client: TestClient, started: dict[str, str], fake_queue: ArqRedis
) -> None:
    """The API only records the request and queues the work."""
    jobs = client.portal.call(fake_queue.queued_jobs)
    assert [(job.function, job.args) for job in jobs if job.function == "export_notes"] == [
        ("export_notes", (started["id"], 1))
    ]
    assert client.get(started["status_url"]).json() == {
        "id": started["id"],
        "status": "queued",
        "done": 0,
        "total": 0,
    }


def test_progress_streams_as_sse_and_resumes(
    client: TestClient,
    started: dict[str, str],
    settings: Settings,
    fake_redis: fakeredis.FakeAsyncRedis,
) -> None:
    """Every progress event arrives once with an id; Last-Event-ID resumes after it."""
    assert run_job(client, settings, fake_redis, started["id"]) == 3
    response = client.get(started["events_url"])
    assert response.headers["content-type"].startswith("text/event-stream")
    messages = sse_messages(response.text)
    statuses = [message["data"] for message in messages]
    assert [message["event"] for message in messages] == ["progress"] * 4
    assert (
        statuses[0] == '{"status":"queued","done":0,"total":0}'
        and statuses[-1] == '{"status":"done","done":3,"total":3}'
    )
    resumed = client.get(started["events_url"], headers={"Last-Event-ID": messages[1]["id"]})
    assert [message["id"] for message in sse_messages(resumed.text)] == [
        message["id"] for message in messages[2:]
    ]
    assert [note["title"] for note in client.get(f"{started['status_url']}/download").json()] == [
        "Note 0",
        "Note 1",
        "Note 2",
    ]


def test_other_users_cannot_see_an_export(client: TestClient, started: dict[str, str]) -> None:
    """Status, events and download are 404 for anyone else."""
    intruder = auth_headers(client, "intruder@example.com")
    for suffix in ("", "/events", "/download"):
        assert client.get(f"{started['status_url']}{suffix}", headers=intruder).status_code == 404
