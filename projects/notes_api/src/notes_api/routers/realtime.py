"""/api/v1/ws: live note events over a WebSocket, fanned out through Redis pub/sub."""

import asyncio
import contextlib
import json
import time
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from notes_api.dependencies import RedisDep, SettingsDep, get_auth_service, get_clock
from notes_api.events import user_channel
from notes_api.exceptions import AuthenticationError
from notes_api.security import Principal

AUTH_TIMEOUT_SECONDS = 5.0
POLICY_VIOLATION = 1008  # WebSocket close code for "you are not allowed here"

router = APIRouter(tags=["realtime"])


class ConnectionManager:
    """The sockets open in this process, per user. Other processes' sockets are reached
    through Redis: every process subscribes to the channels of its own connected users."""

    def __init__(self) -> None:
        """Start with no connections."""
        self.active: defaultdict[int, set[WebSocket]] = defaultdict(set)

    def add(self, user_id: int, websocket: WebSocket) -> None:
        """Remember a connection."""
        self.active[user_id].add(websocket)

    def remove(self, user_id: int, websocket: WebSocket) -> None:
        """Forget a connection."""
        self.active[user_id].discard(websocket)
        if not self.active[user_id]:
            del self.active[user_id]

    def count(self) -> int:
        """Open connections in this process."""
        return sum(len(sockets) for sockets in self.active.values())


async def authenticate(
    websocket: WebSocket, token: str, redis: RedisDep, settings: SettingsDep
) -> Principal:
    """Check the access token sent as the first message, with a short-lived DB session."""
    async with websocket.app.state.session_factory() as session:
        auth = get_auth_service(websocket, session, redis, settings, get_clock())  # type: ignore[arg-type]
        return await auth.principal_from_access_token(token)


def slots_key(user_id: int) -> str:
    """The Redis sorted set of a user's open sockets (member: connection id, score: last beat)."""
    return f"ws:open:{user_id}"


async def claim_slot(
    redis: Redis, user_id: int, connection_id: str, limit: int, stale: float
) -> bool:
    """Count this socket against the user's cap, across every process (OWASP API4).

    Entries older than `stale` seconds belong to sockets of a process that died without
    cleaning up; they are dropped first. Over the cap: the claim is withdrawn, False.
    """
    key, now = slots_key(user_id), time.time()
    async with redis.pipeline(transaction=True) as pipeline:
        pipeline.zremrangebyscore(key, 0, now - stale)
        pipeline.zadd(key, {connection_id: now})
        pipeline.zcard(key)
        pipeline.expire(key, int(stale) + 1)
        _, _, open_sockets, _ = await pipeline.execute()
    if open_sockets > limit:
        await redis.zrem(key, connection_id)
        return False
    return True


async def forward_events(
    websocket: WebSocket,
    pubsub: PubSub,
    heartbeat_seconds: float,
    keep_slot: Callable[[], Awaitable[None]],
) -> None:
    """Redis → client, plus a ping every heartbeat_seconds (dead connections show up fast);
    each ping also refreshes the socket's entry in the per-user cap."""
    last_ping = time.monotonic()
    while True:
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.2)
        if message is not None:
            await websocket.send_text(message["data"])
        if time.monotonic() - last_ping >= heartbeat_seconds:
            await websocket.send_json({"type": "ping"})
            await keep_slot()
            last_ping = time.monotonic()


async def read_client(websocket: WebSocket) -> None:
    """Client → server: answer pings; any other message is ignored. Ends on disconnect."""
    while True:
        message = await websocket.receive_json()
        if message.get("type") == "ping":
            await websocket.send_json({"type": "pong"})


@router.websocket("/ws")
async def live_updates(websocket: WebSocket, redis: RedisDep, settings: SettingsDep) -> None:
    """Accept, authenticate with the first message ({"token": ...}), then stream events."""
    await websocket.accept()
    try:
        first = await asyncio.wait_for(websocket.receive_json(), timeout=AUTH_TIMEOUT_SECONDS)
        principal = await authenticate(websocket, str(first.get("token", "")), redis, settings)
    except TimeoutError, AuthenticationError, json.JSONDecodeError, AttributeError:
        await websocket.close(code=POLICY_VIOLATION, reason="authentication required")
        return
    except WebSocketDisconnect:
        return
    connection_id, stale = uuid.uuid4().hex, 3 * settings.ws_heartbeat_seconds
    limit = settings.ws_connections_per_user
    if not await claim_slot(redis, principal.user_id, connection_id, limit, stale):
        await websocket.close(code=POLICY_VIOLATION, reason="too many open connections")
        return
    manager: ConnectionManager = websocket.app.state.connections
    manager.add(principal.user_id, websocket)
    pubsub = redis.pubsub()
    await pubsub.subscribe(user_channel(principal.user_id))
    await websocket.send_json({"type": "ready", "user_id": principal.user_id})
    beat = settings.ws_heartbeat_seconds

    async def keep_slot() -> None:
        """Refresh this socket's score (it is alive)."""
        await redis.zadd(slots_key(principal.user_id), {connection_id: time.time()})

    tasks = [
        asyncio.create_task(forward_events(websocket, pubsub, beat, keep_slot)),
        asyncio.create_task(read_client(websocket)),
    ]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)  # the client left
    finally:
        for task in tasks:
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
            await asyncio.gather(*tasks)
        manager.remove(principal.user_id, websocket)
        await redis.zrem(slots_key(principal.user_id), connection_id)
        await pubsub.unsubscribe()
        await pubsub.aclose()
