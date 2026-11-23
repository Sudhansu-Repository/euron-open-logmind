"""The Overview page in one call: volume and error totals against the previous period,
the level histogram, the noisiest error groups, service health, anomalies (A10) found by
scanning each service's five-minute error series against its own trailing baseline,
recent investigations and alert firings. Cached for ``ROLLUP_CACHE_TTL_S`` per project."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from logmind.alerts.models import AlertRule
from logmind.alerts.service import history
from logmind.analytics.anomaly import detect, fill
from logmind.analytics.schemas import AnomalyOut, OverviewOut, ServiceSummary
from logmind.core.clickhouse import ClickHouse
from logmind.core.db import ProjectScope
from logmind.errors.repository import ErrorGroupRepository
from logmind.errors.service import list_groups
from logmind.investigations.models import AiUsage
from logmind.investigations.service import list_investigations
from logmind.logs import service as logs
from logmind.logs.repository import LogFilter, LogRepository
from logmind.providers.models import AiProvider
from logmind.services.service import health

BUCKET = timedelta(minutes=5)
BASELINE_BUCKETS = 48  # four hours of five-minute windows


def _floor(ts: datetime) -> datetime:
    s = int(BUCKET.total_seconds())
    return datetime.fromtimestamp(int(ts.timestamp()) // s * s, UTC)


async def anomalies(
    ch: ClickHouse, scope: ProjectScope, hours: int, now: datetime
) -> list[AnomalyOut]:
    start = _floor(now - timedelta(hours=hours) - BUCKET * BASELINE_BUCKETS)
    end = _floor(now)
    rows = await LogRepository(ch).service_stats(
        scope, LogFilter(start=start, end=now), int(BUCKET.total_seconds())
    )
    per: dict[str, dict[datetime, int]] = defaultdict(dict)
    for r in rows:
        per[r.service][r.bucket] = r.errors
    window_start = now - timedelta(hours=hours)
    found: list[AnomalyOut] = []
    for service_name, points in per.items():
        series = fill(points, start, end, BUCKET)
        for a in detect(series, baseline_buckets=BASELINE_BUCKETS, threshold=3.5, min_count=10):
            if a.at >= window_start:
                found.append(
                    AnomalyOut(
                        at=a.at,
                        service=service_name,
                        value=a.value,
                        expected=a.expected,
                        zscore=a.zscore,
                    )
                )
    found.sort(key=lambda a: a.at, reverse=True)
    return found[:20]


async def overview(
    ch: ClickHouse, session: AsyncSession, scope: ProjectScope, hours: int
) -> OverviewOut:
    now = datetime.now(UTC)
    start = now - timedelta(hours=hours)
    prev = start - timedelta(hours=hours)
    repo = LogRepository(ch)
    window = LogFilter(start=start, end=now)
    errors_f = LogFilter(start=start, end=now, levels=["error", "fatal"])
    lines = await repo.count(scope, window)
    errors = await repo.count(scope, errors_f)
    warnings = await repo.count(scope, LogFilter(start=start, end=now, levels=["warn"]))
    lines_prev = await repo.count(scope, LogFilter(start=prev, end=start))
    errors_prev = await repo.count(
        scope, LogFilter(start=prev, end=start, levels=["error", "fatal"])
    )
    redactions = await repo.redaction_total(scope, window)
    groups = await list_groups(
        session,
        scope,
        status="open",
        service=None,
        environment=None,
        q=None,
        since_hours=hours,
        sort="occurrences",
        limit=5,
        offset=0,
    )
    new_groups = await ErrorGroupRepository(session).new_since(scope, start)
    services = await health(ch, session, scope, hours)
    firing = await session.scalar(
        select(func.count()).where(
            AlertRule.org_id == scope.org_id,
            AlertRule.project_id == scope.project_id,
            AlertRule.state == "firing",
        )
    )
    tokens = await session.scalar(
        select(func.coalesce(func.sum(AiUsage.input_tokens + AiUsage.output_tokens), 0)).where(
            AiUsage.org_id == scope.org_id,
            AiUsage.project_id == scope.project_id,
            AiUsage.at >= now - timedelta(days=30),
        )
    )
    provider = await session.scalar(
        select(AiProvider.id)
        .where(AiProvider.org_id == scope.org_id, AiProvider.enabled.is_(True))
        .limit(1)
    )
    return OverviewOut(
        hours=hours,
        lines=lines,
        lines_previous=lines_prev,
        errors=errors,
        errors_previous=errors_prev,
        warnings=warnings,
        error_rate=round(errors / lines, 4) if lines else 0.0,
        redactions=redactions,
        open_error_groups=groups.total,
        new_error_groups=new_groups,
        histogram=await logs.histogram(ch, scope, window),
        top_errors=groups.items,
        services=[
            ServiceSummary(
                name=s.name,
                status=s.status,
                total=s.total,
                errors=s.errors,
                error_rate=s.error_rate,
            )
            for s in services.services
        ],
        anomalies=await anomalies(ch, scope, hours, now),
        investigations=await list_investigations(session, scope, error_group_id=None, limit=5),
        alerts=await history(session, scope, rule_id=None, limit=6),
        firing_alerts=int(firing or 0),
        ai_tokens_30d=int(tokens or 0),
        ai_provider_configured=provider is not None,
    )
