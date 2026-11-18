"""Cache-aside for single notes in Redis: TTL with jitter, invalidation, stampede protection."""

import asyncio
import json
import random
from collections.abc import Awaitable, Callable
from typing import Any

from redis.asyncio import Redis

KEY_PREFIX = "notes:v5"  # bump the version when the cached shape changes
STATS_KEY = f"{KEY_PREFIX}:cache-stats"
LOCK_MILLISECONDS = 2000
WAIT_STEPS = 10


def note_key(note_id: int) -> str:
    """notes:v5:note:<id>: namespace, schema version, entity, id."""
    return f"{KEY_PREFIX}:note:{note_id}"


class NoteCache:
    """Read-through helper; the loader returns a JSON-able dict, or None for 'no such note'."""

    def __init__(self, redis: Redis, ttl_seconds: int, rng: random.Random | None = None) -> None:
        """Keep the client and the base TTL."""
        self.redis = redis
        self.ttl_seconds = ttl_seconds
        self.rng = rng or random.Random()

    def ttl(self) -> int:
        """The base TTL ±10 %, so keys written together do not all expire together."""
        spread = max(1, self.ttl_seconds // 10)
        return self.ttl_seconds + self.rng.randint(-spread, spread)

    async def get_or_load(
        self, note_id: int, loader: Callable[[], Awaitable[dict[str, Any] | None]]
    ) -> dict[str, Any] | None:
        """Cached value, or load it once (one loader per key at a time) and cache it."""
        key = note_key(note_id)
        if (cached := await self.redis.get(key)) is not None:
            await self.redis.hincrby(STATS_KEY, "hits", 1)
            return json.loads(cached)
        await self.redis.hincrby(STATS_KEY, "misses", 1)
        lock = f"{key}:lock"
        if await self.redis.set(lock, "1", nx=True, px=LOCK_MILLISECONDS):
            try:
                value = await loader()
                if value is not None:
                    await self.redis.set(key, json.dumps(value), ex=self.ttl())
                return value
            finally:
                await self.redis.delete(lock)
        for _ in range(WAIT_STEPS):  # someone else is loading: wait briefly for their result
            await asyncio.sleep(LOCK_MILLISECONDS / 1000 / WAIT_STEPS / 4)
            if (cached := await self.redis.get(key)) is not None:
                return json.loads(cached)
        return await loader()  # give up waiting: correctness first

    async def invalidate(self, note_id: int) -> None:
        """Delete the cached copy (called before and again after the database commit)."""
        await self.redis.delete(note_key(note_id))

    async def stats(self) -> dict[str, float]:
        """Hits, misses and the hit rate since the counters were last reset."""
        raw = await self.redis.hgetall(STATS_KEY)
        hits, misses = int(raw.get("hits", 0)), int(raw.get("misses", 0))
        total = hits + misses
        return {
            "hits": hits,
            "misses": misses,
            "hit_rate": round(hits / total, 3) if total else 0.0,
        }
