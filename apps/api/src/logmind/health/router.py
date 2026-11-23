"""``/healthz`` (liveness: the process is up), ``/readyz`` (readiness: Postgres, Redis and
ClickHouse, the three stores the request path needs, are reachable) and ``/metrics``
(Prometheus)."""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from logmind.core.deps import ContainerDep
from logmind.core.schemas import ApiModel

router = APIRouter(tags=["health"])


class HealthOut(ApiModel):
    status: str


class ReadyOut(ApiModel):
    status: str
    postgres: bool
    redis: bool
    clickhouse: bool


@router.get("/healthz", response_model=HealthOut, summary="Liveness probe")
async def healthz() -> HealthOut:
    return HealthOut(status="ok")


@router.get("/readyz", response_model=ReadyOut, summary="Readiness probe")
async def readyz(container: ContainerDep, response: Response) -> ReadyOut:
    postgres_ok = False
    try:
        async with container.db.sessionmaker() as session:
            await session.execute(text("SELECT 1"))
        postgres_ok = True
    except Exception:
        postgres_ok = False
    redis_ok = False
    try:
        await container.redis.ping()
        redis_ok = True
    except Exception:
        redis_ok = False
    clickhouse_ok = await container.clickhouse.ping()
    ready = postgres_ok and redis_ok and clickhouse_ok
    if not ready:
        response.status_code = 503
    return ReadyOut(
        status="ok" if ready else "degraded",
        postgres=postgres_ok,
        redis=redis_ok,
        clickhouse=clickhouse_ok,
    )


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
