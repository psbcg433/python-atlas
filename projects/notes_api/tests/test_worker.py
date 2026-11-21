"""ARQ tasks, called directly: relay, signed webhooks with retries and dead letters, locks."""

import json
from collections.abc import Callable
from typing import Any

import fakeredis
import httpx
import pytest
import respx
from arq import Retry
from arq.connections import ArqRedis
from fastapi.testclient import TestClient

from helpers import create, fake_resolver
from notes_api.core.config import Settings
from notes_api.db import create_engine_from_settings, make_session_factory
from notes_api.events import SIGNATURE_HEADER, user_channel, verify_webhook
from notes_api.models import OutboxEvent
from notes_api.worker import DEAD_LETTERS, deliver_webhook, purge_expired_tokens, relay_outbox

HOOK = "https://hooks.example/notes"


@pytest.fixture
def ctx(
    client: TestClient,
    settings: Settings,
    fake_redis: fakeredis.FakeAsyncRedis,
    fake_queue: ArqRedis,
) -> dict[str, Any]:
    """What WorkerSettings.on_startup builds, but on the test database and fake Redis."""
    engine = create_engine_from_settings(settings)
    return {
        "settings": settings,
        "session_factory": make_session_factory(engine),
        "text_redis": fake_redis,
        "redis": fake_queue,
        "http": httpx.AsyncClient(timeout=1),
        "resolver": fake_resolver,
        "job_try": 1,
    }


def run(client: TestClient, task: Callable[..., Any], *args: Any) -> Any:
    """Run an async task on the app's event loop (where the fake Redis lives)."""
    return client.portal.call(task, *args)


def with_webhook(client: TestClient) -> str:
    """Register the test receiver; return the signing secret."""
    response = client.put("/api/v1/users/me/webhook", json={"url": HOOK})
    assert response.status_code == 200, response.text
    return response.json()["secret"]


async def events(ctx: dict[str, Any]) -> list[OutboxEvent]:
    """Every outbox row."""
    from sqlalchemy import select

    async with ctx["session_factory"]() as session:
        return list(await session.scalars(select(OutboxEvent).order_by(OutboxEvent.id)))


def test_writes_create_outbox_events(client: TestClient, ctx: dict[str, Any]) -> None:
    """Create, update and delete each leave one event, in the same transaction as the change."""
    note = create(client, title="Tea")
    client.patch(f"/api/v1/notes/{note['id']}", json={"pinned": True})
    client.delete(f"/api/v1/notes/{note['id']}")
    rows = run(client, events, ctx)
    assert [row.event_type for row in rows] == ["note.created", "note.updated", "note.deleted"]
    assert json.loads(rows[0].payload) == {"note_id": 1, "title": "Tea", "version": 1}


def test_a_failed_write_leaves_no_event(client: TestClient, ctx: dict[str, Any]) -> None:
    """A rolled-back request (409) writes no event: change and event share one transaction."""
    note = create(client)
    client.patch(f"/api/v1/notes/{note['id']}", json={"title": "x"})
    assert (
        client.patch(f"/api/v1/notes/{note['id']}", json={"title": "y", "version": 1}).status_code
        == 409
    )
    assert [row.event_type for row in run(client, events, ctx)] == ["note.created", "note.updated"]


@respx.mock
def test_relay_publishes_and_queues_webhooks(
    client: TestClient, ctx: dict[str, Any], fake_redis: fakeredis.FakeAsyncRedis
) -> None:
    """Each event goes to the user's Redis channel once; webhook jobs are queued by event id."""
    with_webhook(client)
    create(client, title="Tea")

    async def relay_and_listen() -> tuple[int, int, list[str]]:
        """Subscribe, relay twice, collect the published messages."""
        pubsub = fake_redis.pubsub()
        await pubsub.subscribe(user_channel(1))
        first, second = await relay_outbox(ctx), await relay_outbox(ctx)
        messages = []
        for _ in range(5):  # the subscribe confirmation also comes back as None: poll a few times
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.05)
            if message is not None:
                messages.append(message["data"])
        await pubsub.aclose()
        return first, second, messages

    first, second, messages = run(client, relay_and_listen)
    assert (first, second) == (1, 0)  # published once; the second run finds nothing new
    assert json.loads(messages[0])["type"] == "note.created"
    queued = run(client, ctx["redis"].queued_jobs)
    assert [(job.function, job.args) for job in queued if job.function == "deliver_webhook"] == [
        ("deliver_webhook", (1,))
    ]
    assert run(client, ctx["redis"].exists, "arq:job:webhook:1") == 1  # the job id is the event id


@respx.mock
def test_webhook_is_signed_and_delivered_once(client: TestClient, ctx: dict[str, Any]) -> None:
    """The receiver can verify the signature; a duplicate job does not send twice."""
    secret = with_webhook(client)
    create(client, title="Tea")
    route = respx.post(HOOK).respond(204)
    assert run(client, deliver_webhook, ctx, 1) == "delivered"
    request = route.calls.last.request
    assert verify_webhook(
        secret,
        request.headers[SIGNATURE_HEADER],
        request.content,
        now=int(request.headers[SIGNATURE_HEADER].split(",")[0][2:]),
    )
    assert run(client, deliver_webhook, ctx, 1) == "already delivered" and route.call_count == 1


@respx.mock
def test_failing_webhook_retries_then_dead_letters(
    client: TestClient,
    ctx: dict[str, Any],
    fake_redis: fakeredis.FakeAsyncRedis,
    admin_headers: dict[str, str],
) -> None:
    """Failures raise Retry with growing delays; the last try marks the event dead."""
    with_webhook(client)
    create(client)
    respx.post(HOOK).respond(500)
    delays = []
    for attempt in range(1, ctx["settings"].webhook_max_attempts):
        ctx["job_try"] = attempt
        with pytest.raises(Retry) as retry:
            run(client, deliver_webhook, ctx, 1)
        delays.append(retry.value.defer_score)
    ctx["job_try"] = ctx["settings"].webhook_max_attempts
    assert run(client, deliver_webhook, ctx, 1) == "dead"
    assert delays == [2000, 4000, 8000, 16000]  # milliseconds
    assert run(client, fake_redis.lrange, DEAD_LETTERS, 0, -1) == ["1"]
    dead = client.get("/api/v1/admin/webhooks/dead", headers=admin_headers).json()
    assert dead == [{"id": 1, "type": "note.created", "attempts": 5, "error": "HTTP 500"}]
    assert (
        client.post("/api/v1/admin/webhooks/dead/1/retry", headers=admin_headers).status_code == 202
    )


@respx.mock
def test_webhook_url_is_checked_again_before_delivery(
    client: TestClient, ctx: dict[str, Any], fake_redis: fakeredis.FakeAsyncRedis
) -> None:
    """The host now resolves to a private address: nothing is sent, the event is dead at once."""
    with_webhook(client)
    create(client)
    route = respx.post(HOOK).respond(204)

    async def changed_dns(host: str) -> list[str]:
        """The DNS answer after the URL was saved (a rebinding attacker controls it)."""
        return ["10.0.0.7"]

    ctx["resolver"] = changed_dns
    assert run(client, deliver_webhook, ctx, 1) == "blocked"
    assert route.call_count == 0
    assert run(client, fake_redis.lrange, DEAD_LETTERS, 0, -1) == ["1"]


def test_relay_lock_prevents_overlap(
    client: TestClient, ctx: dict[str, Any], fake_redis: fakeredis.FakeAsyncRedis
) -> None:
    """While another relay holds the lock, a second one does nothing."""
    create(client)
    run(client, fake_redis.set, "lock:relay-outbox", "1")
    assert run(client, relay_outbox, ctx) == 0
    run(client, fake_redis.delete, "lock:relay-outbox")
    assert run(client, relay_outbox, ctx) == 1


def test_purge_expired_tokens(client: TestClient, ctx: dict[str, Any]) -> None:
    """The daily job runs once per lock and deletes nothing that is still valid."""
    assert run(client, purge_expired_tokens, ctx) == 0


def test_webhook_url_must_be_public(client: TestClient) -> None:
    """Webhooks get the same SSRF rules as link previews."""
    response = client.put("/api/v1/users/me/webhook", json={"url": "http://intranet.example/hook"})
    assert (response.status_code, response.json()["type"]) == (422, "/problems/invalid-webhook")
