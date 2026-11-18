"""A fixed-window rate limiter on Redis: one INCR per attempt, keys expire by themselves."""

import dataclasses
import time
from collections.abc import Callable

from redis.asyncio import Redis


@dataclasses.dataclass(frozen=True, slots=True)
class RateLimitResult:
    """The outcome of one attempt."""

    allowed: bool
    remaining: int
    retry_after: int  # seconds until the current window ends


class FixedWindowRateLimiter:
    """At most `limit` hits per key per window of `window_seconds` (shared by every process)."""

    def __init__(
        self,
        redis: Redis,
        limit: int,
        window_seconds: int,
        prefix: str,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Keep the client and the limits; the clock is injectable for tests."""
        self.redis = redis
        self.limit = limit
        self.window_seconds = window_seconds
        self.prefix = prefix
        self.clock = clock

    async def hit(self, key: str) -> RateLimitResult:
        """Count one attempt for key in the current window."""
        now = self.clock()
        window = int(now // self.window_seconds)
        redis_key = f"ratelimit:{self.prefix}:{key}:{window}"
        async with self.redis.pipeline(transaction=True) as pipeline:
            pipeline.incr(redis_key)
            pipeline.expire(redis_key, self.window_seconds + 1)
            count, _ = await pipeline.execute()
        retry_after = max(1, int((window + 1) * self.window_seconds - now + 0.999))
        return RateLimitResult(count <= self.limit, max(0, self.limit - count), retry_after)
