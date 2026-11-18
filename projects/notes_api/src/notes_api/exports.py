"""Note exports: state and progress in Redis (a Stream per export), read back as SSE."""

import json
from collections.abc import AsyncIterator

from redis.asyncio import Redis

FINAL_STATUSES = {"done", "failed"}
HEARTBEAT_MILLISECONDS = 15_000


def owner_key(export_id: str) -> str:
    """Who may see this export."""
    return f"export:{export_id}:owner"


def events_key(export_id: str) -> str:
    """The Redis Stream of progress events."""
    return f"export:{export_id}:events"


def result_key(export_id: str) -> str:
    """The finished JSON document."""
    return f"export:{export_id}:result"


async def add_progress(redis: Redis, export_id: str, ttl: int, **fields: object) -> str:
    """Append one event (XADD) and keep the stream alive for ttl seconds; returns its id."""
    entry_id = await redis.xadd(
        events_key(export_id), {key: str(value) for key, value in fields.items()}
    )
    await redis.expire(events_key(export_id), ttl)
    return entry_id if isinstance(entry_id, str) else entry_id.decode()


def format_sse(event_id: str, event: str, data: dict[str, object]) -> str:
    """One text/event-stream message: id, event and data lines, then a blank line."""
    return f"id: {event_id}\nevent: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


async def progress_events(redis: Redis, export_id: str, last_event_id: str) -> AsyncIterator[str]:
    """SSE messages after last_event_id until the export finishes; a comment line as heartbeat.

    Stream ids are the SSE ids, so a reconnecting EventSource (Last-Event-ID) resumes exactly.
    """
    cursor = last_event_id or "0-0"
    while True:
        batches = await redis.xread(
            {events_key(export_id): cursor}, block=HEARTBEAT_MILLISECONDS, count=100
        )
        if not batches:
            yield ": keep-alive\n\n"  # comments keep proxies from closing an idle connection
            continue
        for entry_id, fields in batches[0][1]:
            cursor = entry_id
            data = {
                key: (int(value) if value.isdigit() else value) for key, value in fields.items()
            }
            yield format_sse(entry_id, "progress", data)
            if fields.get("status") in FINAL_STATUSES:
                return
