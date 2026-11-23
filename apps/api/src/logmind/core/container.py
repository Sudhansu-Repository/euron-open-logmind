"""Process-wide services, built once in the app lifespan and shared by every request.

Holding them in one object (on ``app.state``) instead of module globals keeps the app
factory re-entrant and lets tests build an isolated container per app. External systems
(object storage, key sealing, mail) are chosen here from config, once; nothing below this
layer branches on which backend is in use.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from redis.asyncio import Redis

from logmind.core.aws import aws_client
from logmind.core.cache import ConfigCache, RollupCache
from logmind.core.clickhouse import ClickHouse
from logmind.core.config import Settings
from logmind.core.db import Database
from logmind.core.hub import Hub
from logmind.core.redis_client import create_redis
from logmind.core.sealing import KeySealer, KmsSealer, LocalSealer
from logmind.core.storage import LocalStorage, ObjectStorage, S3Storage


def build_http_client(timeout_s: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_s, connect=5.0),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        follow_redirects=False,
    )


@dataclass
class Container:
    settings: Settings
    db: Database
    redis: Redis
    clickhouse: ClickHouse
    # Outbound calls: model providers, webhooks, Slack.
    http: httpx.AsyncClient
    config_cache: ConfigCache
    rollup_cache: RollupCache
    hub: Hub
    sealer: KeySealer
    storage: ObjectStorage

    @classmethod
    def build(cls, settings: Settings) -> Container:
        redis = create_redis(settings.redis_url)
        sealer: KeySealer = (
            KmsSealer(aws_client(settings, "kms"), settings.kms_key_id)
            if settings.key_mode == "kms"
            else LocalSealer(settings.local_master_key)
        )
        storage: ObjectStorage = (
            S3Storage(aws_client(settings, "s3"), settings.evidence_bucket)
            if settings.storage == "s3"
            else LocalStorage(settings.local_storage_dir)
        )
        return cls(
            settings=settings,
            db=Database(
                settings.database_url,
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
            ),
            redis=redis,
            clickhouse=ClickHouse(settings.clickhouse_url, timeout_s=settings.clickhouse_timeout_s),
            http=build_http_client(max(settings.webhook_timeout_s, 10.0)),
            config_cache=ConfigCache(redis, ttl_s=settings.config_cache_ttl_s),
            rollup_cache=RollupCache(redis, ttl_s=settings.rollup_cache_ttl_s),
            hub=Hub(redis),
            sealer=sealer,
            storage=storage,
        )

    async def close(self) -> None:
        await self.http.aclose()
        await self.clickhouse.close()
        await self.redis.aclose()
        await self.db.dispose()
