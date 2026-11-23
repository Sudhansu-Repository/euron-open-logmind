"""Service Health Monitoring from ingested logs alone (no APM agent): per service, line
volume, error and warning counts, error rate (overall and over the last 15 minutes), an
availability figure, anomaly count and a status, all from the ClickHouse per-minute
rollup, so the page costs the same whether a service logged a thousand lines or a billion.

Status rules, applied to the last 15 minutes: no lines while the service logged earlier
in the window is ``silent``; an error rate of 10% or more is ``critical``; 2% or more is
``degraded``; otherwise ``healthy``.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from logmind.analytics.anomaly import detect, fill
from logmind.core.clickhouse import ClickHouse
from logmind.core.db import ProjectScope
from logmind.errors.models import ErrorGroup
from logmind.logs.repository import LogFilter, LogRepository, ServiceBucket
from logmind.services.repository import ServiceRepository
from logmind.services.schemas import HealthPoint, ServiceHealthOut, ServicesOut

BUCKET_S = 300
RECENT = timedelta(minutes=15)


def _floor(ts: datetime, seconds: int) -> datetime:
    epoch = int(ts.timestamp()) // seconds * seconds
    return datetime.fromtimestamp(epoch, UTC)


def status_for(recent_total: int, recent_errors: int, seen_before: bool) -> str:
    if recent_total == 0:
        return "silent" if seen_before else "healthy"
    rate = recent_errors / recent_total
    if rate >= 0.10:
        return "critical"
    if rate >= 0.02:
        return "degraded"
    return "healthy"


async def health(
    ch: ClickHouse, session: AsyncSession, scope: ProjectScope, hours: int, name: str | None = None
) -> ServicesOut:
    now = datetime.now(UTC)
    start = _floor(now - timedelta(hours=hours), BUCKET_S)
    catalogue = await ServiceRepository(session).list_for(scope)
    if name is not None:
        catalogue = [s for s in catalogue if s.name == name]
    f = LogFilter(start=start, end=now, services=[name] if name else [])
    rows = await LogRepository(ch).service_stats(scope, f, BUCKET_S)
    per: dict[str, list[ServiceBucket]] = defaultdict(list)
    for r in rows:
        per[r.service].append(r)
    open_rows = await session.execute(
        select(func.unnest(ErrorGroup.services).label("svc"), func.count())
        .where(
            ErrorGroup.org_id == scope.org_id,
            ErrorGroup.project_id == scope.project_id,
            ErrorGroup.status == "open",
        )
        .group_by("svc")
    )
    open_groups = {str(svc): int(n) for svc, n in open_rows.all()}
    out: list[ServiceHealthOut] = []
    recent_cut = now - RECENT
    end_bucket = _floor(now, BUCKET_S)
    for svc in catalogue:
        buckets = per.get(svc.name, [])
        total = sum(b.total for b in buckets)
        errors = sum(b.errors for b in buckets)
        recent = [b for b in buckets if b.bucket >= recent_cut - timedelta(seconds=BUCKET_S)]
        r_total = sum(b.total for b in recent)
        r_errors = sum(b.errors for b in recent)
        active = [b for b in buckets if b.total > 0]
        good = [b for b in active if b.errors / b.total < 0.05]
        series = fill(
            {b.bucket: b.errors for b in buckets}, start, end_bucket, timedelta(seconds=BUCKET_S)
        )
        anomalies = detect(series, baseline_buckets=48, threshold=4.0, min_count=10)
        hourly: dict[datetime, list[int]] = defaultdict(lambda: [0, 0])
        for b in buckets:
            h = _floor(b.bucket, 3600)
            hourly[h][0] += b.total
            hourly[h][1] += b.errors
        out.append(
            ServiceHealthOut(
                name=svc.name,
                status=status_for(r_total, r_errors, total > 0),
                first_seen_at=svc.first_seen_at,
                last_seen_at=svc.last_seen_at,
                total=total,
                errors=errors,
                warnings=sum(b.warnings for b in buckets),
                error_rate=round(errors / total, 4) if total else 0.0,
                recent_error_rate=round(r_errors / r_total, 4) if r_total else 0.0,
                availability=round(len(good) / len(active), 4) if active else 1.0,
                anomalies=len(anomalies),
                open_error_groups=open_groups.get(svc.name, 0),
                series=[
                    HealthPoint(at=h, total=v[0], errors=v[1]) for h, v in sorted(hourly.items())
                ],
            )
        )
    rank = {"critical": 0, "degraded": 1, "silent": 2, "healthy": 3}
    out.sort(key=lambda s: (rank[s.status], s.name))
    return ServicesOut(hours=hours, services=out)
