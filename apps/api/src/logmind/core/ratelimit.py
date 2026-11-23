"""A fixed-window rate limiter on Redis (``INCR`` + ``EXPIRE`` in one pipeline), shared by
every API replica. Used on the credential routes (sign in, sign up), per client address.
When Redis is unreachable the limiter lets the request through and logs it: refusing every
sign in because a cache is down would turn a cache outage into a full outage."""

from __future__ import annotations

import logging
import time

from redis.asyncio import Redis
from redis.exceptions import RedisError

from logmind.core.errors import RateLimitedError

log = logging.getLogger("logmind.ratelimit")


async def hit(redis: Redis, bucket: str, limit: int, window_s: int = 60) -> None:
    """Count one attempt in ``bucket``; raise ``RateLimitedError`` past ``limit``."""
    window = int(time.time()) // window_s
    key = f"logmind:rl:{bucket}:{window}"
    try:
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window_s + 5)
            count, _ = await pipe.execute()
    except RedisError:
        log.warning("rate limiter unavailable, allowing the request", extra={"bucket": bucket})
        return
    if int(count) > limit:
        retry = window_s - int(time.time()) % window_s
        raise RateLimitedError(
            "Too many attempts. Wait a minute and try again",
            headers={"retry-after": str(retry)},
        )
