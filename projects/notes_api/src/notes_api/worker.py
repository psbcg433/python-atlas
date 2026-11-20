"""The ARQ worker (python -m notes_api.worker): relay, webhooks, exports, clean-up."""

import asyncio
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import httpx
import redis.asyncio as redis_asyncio
from arq import Retry, cron
from arq.connections import RedisSettings
from arq.worker import Worker
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from notes_api import __version__
from notes_api.core.config import Settings, get_settings
from notes_api.core.logging import configure_logging
from notes_api.db import create_engine_from_settings, make_session_factory
from notes_api.events import (
    EVENT_ID_HEADER,
    SIGNATURE_HEADER,
    event_message,
    sign_webhook,
    user_channel,
)
from notes_api.exports import add_progress, owner_key, result_key
from notes_api.models import Note, OutboxEvent, RefreshToken, User
from notes_api.schemas import NoteRead

RELAY_BATCH = 100
EXPORT_CHUNK = 25
DEAD_LETTERS = "webhooks:dead"


def utc_now() -> datetime:
    """Now, in UTC."""
    return datetime.now(UTC)


async def startup(ctx: dict[str, Any]) -> None:
    """Open what the tasks share (once per worker process)."""
    settings: Settings = ctx.get("settings") or get_settings()
    ctx["settings"] = settings
    ctx["engine"] = create_engine_from_settings(settings)
    ctx["session_factory"] = make_session_factory(ctx["engine"])
    ctx["text_redis"] = redis_asyncio.from_url(
        settings.redis_url.get_secret_value(), decode_responses=True
    )
    ctx["http"] = httpx.AsyncClient(
        timeout=settings.webhook_timeout_seconds,
        follow_redirects=False,
        headers={"User-Agent": f"notes-api-webhooks/{__version__}"},
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    """Close everything startup opened."""
    await ctx["http"].aclose()
    await ctx["text_redis"].aclose()
    await ctx["engine"].dispose()


async def relay_outbox(ctx: dict[str, Any]) -> int:
    """Publish unpublished outbox events (Redis pub/sub) and queue their webhooks.

    A Redis lock keeps two relays (cron + a kick, or two workers) from overlapping; on
    PostgreSQL the SELECT ... FOR UPDATE SKIP LOCKED would also let several relays share work.
    """
    redis = ctx["text_redis"]
    if not await redis.set("lock:relay-outbox", "1", nx=True, ex=30):
        return 0
    try:
        async with ctx["session_factory"]() as session, session.begin():
            statement = (
                select(OutboxEvent, User.webhook_url)
                .join(User, User.id == OutboxEvent.user_id)
                .where(OutboxEvent.published_at.is_(None))
                .order_by(OutboxEvent.id)
                .limit(RELAY_BATCH)
                .with_for_update(skip_locked=True, of=OutboxEvent)
            )
            rows = (await session.execute(statement)).all()
            for event, webhook_url in rows:
                await redis.publish(user_channel(event.user_id), json.dumps(event_message(event)))
                if webhook_url:
                    event.webhook_status = "pending"
                    await ctx["redis"].enqueue_job(
                        "deliver_webhook", event.id, _job_id=f"webhook:{event.id}"
                    )
                event.published_at = utc_now()
        return len(rows)
    finally:
        await redis.delete("lock:relay-outbox")


async def deliver_webhook(ctx: dict[str, Any], event_id: int) -> str:
    """POST one signed event; retry with exponential backoff; dead-letter after the last try."""
    settings: Settings = ctx["settings"]
    async with ctx["session_factory"]() as session, session.begin():
        event = await session.get(OutboxEvent, event_id)
        user = await session.get(User, event.user_id) if event else None
        if event is None or user is None or not user.webhook_url or not user.webhook_secret:
            return "skipped"
        if event.webhook_status == "delivered":
            return "already delivered"  # a duplicate job: at-least-once delivery
        body = json.dumps(event_message(event), separators=(",", ":")).encode()
        headers = {
            "Content-Type": "application/json",
            EVENT_ID_HEADER: str(event.id),  # receivers deduplicate on this id
            SIGNATURE_HEADER: sign_webhook(user.webhook_secret, int(time.time()), body),
        }
        event.webhook_attempts += 1
        try:
            response = await ctx["http"].post(user.webhook_url, content=body, headers=headers)
            error = None if response.is_success else f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            error = type(exc).__name__
        if error is None:
            event.webhook_status, event.last_error = "delivered", None
            return "delivered"
        event.last_error = error
        if ctx.get("job_try", 1) >= settings.webhook_max_attempts:
            event.webhook_status = "dead"
            await ctx["text_redis"].lpush(DEAD_LETTERS, str(event.id))
            return "dead"
    raise Retry(defer=2 ** ctx.get("job_try", 1))  # 2, 4, 8 ... seconds (after the commit)


async def export_notes(
    ctx: dict[str, Any], export_id: str, user_id: int, delay: float = 0.0
) -> int:
    """Build a JSON export of a user's notes in chunks, reporting progress to a Redis Stream."""
    redis, ttl = ctx["text_redis"], ctx["settings"].export_ttl_seconds
    if await redis.get(owner_key(export_id)) != str(user_id):
        return 0
    async with ctx["session_factory"]() as session:
        statement = (
            select(Note).options(selectinload(Note.tag_objects)).where(Note.owner_id == user_id)
        )
        notes = list(await session.scalars(statement.order_by(Note.id)))
    total, exported = len(notes), []
    await add_progress(redis, export_id, ttl, status="running", done=0, total=total)
    for start in range(0, total, EXPORT_CHUNK):
        chunk = notes[start : start + EXPORT_CHUNK]
        exported += [NoteRead.model_validate(note).model_dump(mode="json") for note in chunk]
        if delay:
            await asyncio.sleep(delay)  # demos slow the export down to watch the progress
        await add_progress(redis, export_id, ttl, status="running", done=len(exported), total=total)
    await redis.set(result_key(export_id), json.dumps(exported), ex=ttl)
    await add_progress(redis, export_id, ttl, status="done", done=total, total=total)
    return total


async def purge_expired_tokens(ctx: dict[str, Any]) -> int:
    """Daily: delete refresh tokens that expired more than a day ago (one worker at a time)."""
    redis = ctx["text_redis"]
    if not await redis.set("lock:purge-tokens", "1", nx=True, ex=600):
        return 0
    try:
        cutoff = utc_now() - timedelta(days=1)
        async with ctx["session_factory"]() as session, session.begin():
            result = await session.execute(
                delete(RefreshToken).where(RefreshToken.expires_at < cutoff)
            )
        return result.rowcount
    finally:
        await redis.delete("lock:purge-tokens")


class WorkerSettings:
    """What `arq notes_api.worker.WorkerSettings` runs."""

    functions: ClassVar[list[Any]] = [
        relay_outbox,
        deliver_webhook,
        export_notes,
        purge_expired_tokens,
    ]
    cron_jobs: ClassVar[list[Any]] = [
        cron(relay_outbox, second={0, 10, 20, 30, 40, 50}, unique=True),  # safety net for kicks
        cron(purge_expired_tokens, hour={3}, minute={0}, unique=True),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url.get_secret_value())
    max_tries = get_settings().webhook_max_attempts
    job_timeout = 60
    keep_result = 300


async def run_worker(burst: bool = False, settings: Settings | None = None) -> None:
    """Build the arq Worker inside a running event loop and run it (SIGTERM stops it cleanly).

    `arq notes_api.worker.WorkerSettings` is the usual command, but arq 0.25's CLI calls
    asyncio.get_event_loop() outside a running loop, which raises on Python 3.14+.
    """
    log_settings = settings or get_settings()
    configure_logging(log_settings.log_level, log_settings.log_json)  # the same JSON as the API
    worker = Worker(
        functions=WorkerSettings.functions,
        cron_jobs=WorkerSettings.cron_jobs,
        redis_settings=(
            RedisSettings.from_dsn(settings.redis_url.get_secret_value())
            if settings
            else WorkerSettings.redis_settings
        ),
        on_startup=startup,
        on_shutdown=shutdown,
        ctx={"settings": settings} if settings else {},
        burst=burst,
        poll_delay=0.1,
        health_check_interval=HEALTH_CHECK_SECONDS,  # arq's default is an hour
        max_tries=WorkerSettings.max_tries if settings is None else settings.webhook_max_attempts,
        job_timeout=WorkerSettings.job_timeout,
        keep_result=WorkerSettings.keep_result,
    )
    try:
        await worker.async_run()  # sets worker.main_task: the task arq's SIGTERM handler cancels
    except asyncio.CancelledError:
        current_task = asyncio.current_task()
        if current_task is not None and current_task.cancelling():
            raise  # run_worker itself was cancelled (not a signal): let that propagate
    finally:
        await worker.close()


HEALTH_CHECK_KEY = "arq:queue:health-check"  # arq refreshes it every health_check_interval
HEALTH_CHECK_SECONDS = 30


async def worker_is_healthy(settings: Settings) -> bool:
    """True if some worker refreshed its health key recently (it expires after ~31 s)."""
    redis = redis_asyncio.from_url(settings.redis_url.get_secret_value())
    try:
        return bool(await redis.exists(HEALTH_CHECK_KEY))
    except OSError, redis_asyncio.RedisError:
        return False
    finally:
        await redis.aclose()


if __name__ == "__main__":
    if "--check" in sys.argv:  # container health check: exit 0 = healthy
        sys.exit(0 if asyncio.run(worker_is_healthy(get_settings())) else 1)
    asyncio.run(run_worker(burst="--burst" in sys.argv))
