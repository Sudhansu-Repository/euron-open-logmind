"""Log Explorer queries: search with filters and keyset pagination, a level histogram,
filter facets, one line with its surrounding context. All of it works with no AI provider
configured (A5); nothing here calls a model."""

from __future__ import annotations

import base64
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logmind.core.clickhouse import ClickHouse
from logmind.core.db import ProjectScope
from logmind.core.errors import AppError, NotFoundError
from logmind.errors.models import ErrorGroup
from logmind.logs.repository import LogFilter, LogRepository, StoredEvent
from logmind.logs.schemas import (
    FacetsOut,
    FacetValue,
    HistogramBucket,
    HistogramOut,
    LogContextOut,
    LogEventOut,
    LogPage,
)

LEVEL_ORDER = ("trace", "debug", "info", "warn", "error", "fatal")
# Bucket sizes a histogram picks from so that a window shows about 60 to 120 bars.
_BUCKETS = (10, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 21600, 43200, 86400)


def encode_cursor(ts: datetime, event_id: uuid.UUID) -> str:
    raw = f"{ts.timestamp():.6f}|{event_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        ts_s, id_s = base64.urlsafe_b64decode(padded.encode()).decode().split("|", 1)
        return datetime.fromtimestamp(float(ts_s), UTC), uuid.UUID(id_s)
    except (ValueError, UnicodeDecodeError) as exc:
        raise AppError(
            "The cursor is not valid; start from the first page", code="bad_cursor"
        ) from exc


def pick_bucket(start: datetime, end: datetime) -> int:
    span = max((end - start).total_seconds(), 1)
    for b in _BUCKETS:
        if span / b <= 120:
            return b
    return _BUCKETS[-1]


def resolve_window(
    start: datetime | None, end: datetime | None, default: timedelta = timedelta(hours=1)
) -> tuple[datetime, datetime]:
    end = (end or datetime.now(UTC)).astimezone(UTC)
    start = (start or end - default).astimezone(UTC)
    if start >= end:
        raise AppError("start must be before end", code="bad_window")
    if end - start > timedelta(days=400):
        raise AppError(
            "The window is longer than the longest retention (400 days)", code="bad_window"
        )
    return start, end


async def group_ids_for(
    session: AsyncSession, scope: ProjectScope, fingerprints: set[str]
) -> dict[str, uuid.UUID]:
    if not fingerprints:
        return {}
    rows = await session.execute(
        select(ErrorGroup.fingerprint, ErrorGroup.id).where(
            ErrorGroup.org_id == scope.org_id,
            ErrorGroup.project_id == scope.project_id,
            ErrorGroup.fingerprint.in_(fingerprints),
        )
    )
    return {str(fp): gid for fp, gid in rows.all()}


def to_out(e: StoredEvent, groups: dict[str, uuid.UUID]) -> LogEventOut:
    return LogEventOut(
        event_id=e.event_id,
        timestamp=e.timestamp,
        received_at=e.received_at,
        level=e.level,
        service=e.service,
        environment=e.environment,
        host=e.host,
        message=e.message,
        attributes=e.attributes,
        trace_id=e.trace_id,
        span_id=e.span_id,
        request_id=e.request_id,
        exception_type=e.exception_type,
        stack_trace=e.stack_trace,
        fingerprint=e.fingerprint,
        redactions=e.redactions,
        source=e.source,
        error_group_id=groups.get(e.fingerprint) if e.fingerprint else None,
    )


async def outs(
    session: AsyncSession, scope: ProjectScope, events: list[StoredEvent]
) -> list[LogEventOut]:
    groups = await group_ids_for(session, scope, {e.fingerprint for e in events if e.fingerprint})
    return [to_out(e, groups) for e in events]


async def search(
    ch: ClickHouse,
    session: AsyncSession,
    scope: ProjectScope,
    f: LogFilter,
    *,
    limit: int,
    cursor: str | None,
) -> LogPage:
    started = time.perf_counter()
    before = decode_cursor(cursor) if cursor else None
    rows = await LogRepository(ch).search(scope, f, limit=limit + 1, before=before)
    page, more = rows[:limit], len(rows) > limit
    next_cursor = encode_cursor(page[-1].timestamp, page[-1].event_id) if more and page else None
    items = await outs(session, scope, page)
    return LogPage(
        items=items,
        next_cursor=next_cursor,
        took_ms=round((time.perf_counter() - started) * 1000, 1),
    )


async def histogram(ch: ClickHouse, scope: ProjectScope, f: LogFilter) -> HistogramOut:
    bucket = pick_bucket(f.start, f.end)
    rows = await LogRepository(ch).histogram(scope, f, bucket)
    buckets: dict[datetime, HistogramBucket] = {}
    total = 0
    for at, level, n in rows:
        b = buckets.setdefault(at, HistogramBucket(at=at))
        if level in LEVEL_ORDER:
            setattr(b, level, getattr(b, level) + n)
        total += n
    return HistogramOut(
        bucket_seconds=bucket, buckets=[buckets[k] for k in sorted(buckets)], total=total
    )


async def facets(ch: ClickHouse, scope: ProjectScope, f: LogFilter) -> FacetsOut:
    repo = LogRepository(ch)
    unfiltered = LogFilter(start=f.start, end=f.end)
    return FacetsOut(
        services=[
            FacetValue(value=v, count=n) for v, n in await repo.facet(scope, unfiltered, "service")
        ],
        environments=[
            FacetValue(value=v, count=n)
            for v, n in await repo.facet(scope, unfiltered, "environment")
        ],
        levels=[
            FacetValue(value=v, count=n) for v, n in await repo.facet(scope, unfiltered, "level")
        ],
    )


async def get_event(
    ch: ClickHouse,
    session: AsyncSession,
    scope: ProjectScope,
    event_id: uuid.UUID,
    at: datetime | None,
) -> LogEventOut:
    start, end = _event_window(at)
    event = await LogRepository(ch).get(scope, event_id, start, end)
    if event is None:
        raise NotFoundError("Log line not found in this project", code="log_not_found")
    return (await outs(session, scope, [event]))[0]


def _event_window(at: datetime | None) -> tuple[datetime, datetime]:
    if at is None:
        now = datetime.now(UTC)
        return now - timedelta(days=400), now + timedelta(days=1)
    at = at.astimezone(UTC)
    return at - timedelta(seconds=1), at + timedelta(seconds=1)


async def context(
    ch: ClickHouse,
    session: AsyncSession,
    scope: ProjectScope,
    event_id: uuid.UUID,
    at: datetime | None,
    size: int,
) -> LogContextOut:
    repo = LogRepository(ch)
    start, end = _event_window(at)
    event = await repo.get(scope, event_id, start, end)
    if event is None:
        raise NotFoundError("Log line not found in this project", code="log_not_found")
    around = timedelta(minutes=30)
    near = LogFilter(
        start=event.timestamp - around, end=event.timestamp + around, services=[event.service]
    )
    key = (event.timestamp, event.event_id)
    before = await repo.search(scope, near, limit=size, before=key)
    after = await repo.search(scope, near, limit=size, before=key, ascending=True)
    same_trace: list[StoredEvent] = []
    if event.trace_id or event.request_id:
        trace_filter = LogFilter(
            start=event.timestamp - timedelta(hours=1),
            end=event.timestamp + timedelta(hours=1),
            trace_id=event.trace_id,
            request_id="" if event.trace_id else event.request_id,
        )
        same_trace = await repo.search(scope, trace_filter, limit=50, ascending=True)
    every = [event, *before, *after, *same_trace]
    groups = await group_ids_for(session, scope, {e.fingerprint for e in every if e.fingerprint})
    return LogContextOut(
        event=to_out(event, groups),
        before=[to_out(e, groups) for e in reversed(before)],
        after=[to_out(e, groups) for e in after],
        same_trace=[to_out(e, groups) for e in same_trace if e.event_id != event.event_id],
    )
