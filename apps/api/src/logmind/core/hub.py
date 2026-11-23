"""A small Redis pub/sub relay for the live log stream (``/api/v1/logs/live``).

Each project has one topic; ingestion publishes the newly stored lines to it and every
connected websocket for that project receives them. Nothing here is persisted: a reconnect
loads recent history over REST (the log explorer query), never a replay over the socket.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import orjson
from redis.asyncio import Redis
from redis.exceptions import RedisError

log = logging.getLogger("logmind.hub")


def project_topic(project_id: object) -> str:
    return f"logmind:live:{project_id}"


class Hub:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def publish(self, topic: str, event: dict[str, Any]) -> None:
        try:
            await self._redis.publish(topic, orjson.dumps(event))
        except RedisError:
            log.warning("could not publish live logs; the live view falls back to polling")

    @asynccontextmanager
    async def subscribe(self, *topics: str) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(*topics)

        async def _reader() -> None:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    event = orjson.loads(message["data"])
                except orjson.JSONDecodeError:
                    continue
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(event)

        task = asyncio.create_task(_reader())
        try:
            yield queue
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
            await pubsub.unsubscribe(*topics)
            await pubsub.aclose()  # type: ignore[no-untyped-call]  # redis-py's PubSub.aclose has no stub annotation
