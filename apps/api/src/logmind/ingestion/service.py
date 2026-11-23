"""The ingestion pipeline, run inside the request for every accepted batch:

1. normalise (``normalize.py`` / ``otlp.py``) and check the timestamp window;
2. redact PII and secrets with the project's policy (A7), before anything is written;
3. fingerprint error lines (``errors/fingerprint.py``);
4. one ClickHouse insert for the whole batch (the lines are queryable when the request
   returns, A1);
5. one Postgres transaction upserting the error groups (A2), the service catalogue and
   the environments;
6. publish the stored lines to the project's live stream.

Why inline rather than a background queue: redaction must happen before persistence, and
a queue is persistence; and doing the work inline means "202 accepted" never means "maybe
later". The ClickHouse insert comes first: if the Postgres step then fails, the client
gets a 503 and retries, at worst duplicating lines, never losing them.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import orjson
from sqlalchemy.ext.asyncio import AsyncSession

from logmind.core import metrics
from logmind.core.clickhouse import ch_datetime
from logmind.core.container import Container
from logmind.core.hub import project_topic
from logmind.errors.fingerprint import compute
from logmind.errors.repository import ErrorGroupRepository, GroupDelta
from logmind.ingestion.normalize import (
    InvalidEventError,
    RawEvent,
    check_window,
    clean_name,
    normalize_level,
    parse_timestamp,
    truncate,
)
from logmind.ingestion.schemas import BatchDefaults, IngestResult, LogIn, RejectedEvent
from logmind.logs.repository import LogRepository
from logmind.projects.dependencies import ProjectConfig
from logmind.projects.repository import EnvironmentRepository
from logmind.redaction.engine import RedactionResult
from logmind.services.repository import ServiceRepository

log = logging.getLogger("logmind.ingestion")

MAX_ATTRIBUTE_BYTES = 32_000


def from_native(item: LogIn, defaults: BatchDefaults, now: datetime, max_chars: int) -> RawEvent:
    ts = parse_timestamp(item.timestamp) or now
    exc = item.exception
    message = item.message
    return RawEvent(
        timestamp=ts.astimezone(UTC),
        level=normalize_level(item.level),
        message=truncate(message, max_chars),
        service=clean_name(item.service or defaults.service, "unknown"),
        environment=clean_name(item.environment or defaults.environment, "production"),
        host=clean_name(item.host or defaults.host, "", 255),
        attributes=item.attributes,
        trace_id=(item.trace_id or "").lower(),
        span_id=(item.span_id or "").lower(),
        request_id=item.request_id or "",
        exception_type=exc.type if exc else "",
        stack_trace=truncate(exc.stacktrace, max_chars * 4) if exc else "",
    )


def _attributes_json(attrs: dict[str, Any]) -> str:
    raw = orjson.dumps(attrs, default=str)
    if len(raw) > MAX_ATTRIBUTE_BYTES:
        return orjson.dumps({"_truncated": True, "_bytes": len(raw)}).decode()
    return raw.decode()


def _hour(ts: datetime) -> datetime:
    return ts.replace(minute=0, second=0, microsecond=0)


def _widen(seen: dict[str, tuple[datetime, datetime]], name: str, ts: datetime) -> None:
    first, last = seen.get(name, (ts, ts))
    seen[name] = (min(first, ts), max(last, ts))


async def ingest(
    container: Container,
    session: AsyncSession,
    config: ProjectConfig,
    items: Iterable[tuple[int, RawEvent | InvalidEventError]],
    *,
    source: str,
) -> IngestResult:
    started = time.perf_counter()
    settings = container.settings
    scope = config.scope
    now = datetime.now(UTC)
    rejected: list[RejectedEvent] = []
    rows: list[dict[str, Any]] = []
    live: list[dict[str, Any]] = []
    deltas: dict[str, GroupDelta] = {}
    services: dict[str, tuple[datetime, datetime]] = {}
    environments: dict[str, tuple[datetime, datetime]] = {}
    redaction = RedactionResult()
    redactor = config.redactor

    for index, item in items:
        if isinstance(item, InvalidEventError):
            rejected.append(RejectedEvent(index=index, reason=str(item)))
            continue
        try:
            check_window(item.timestamp, now, settings.max_past_days, settings.max_future_minutes)
        except InvalidEventError as exc:
            rejected.append(RejectedEvent(index=index, reason=str(exc)))
            continue
        before = redaction.total
        message = redactor.redact_text(item.message, redaction)
        stack = redactor.redact_text(item.stack_trace, redaction)
        attributes = redactor.redact_value(item.attributes, redaction)
        event_redactions = redaction.total - before
        event_id = uuid.uuid4()
        fingerprint = ""
        if item.is_error:
            fp = compute(
                exception_type=item.exception_type,
                message=message,
                stack_trace=stack,
                level=item.level,
            )
            fingerprint = fp.hash
            delta = deltas.get(fp.hash)
            if delta is None:
                delta = deltas[fp.hash] = GroupDelta(
                    fingerprint=fp.hash,
                    title=fp.title,
                    exception_type=fp.exception_type,
                    culprit=fp.culprit,
                    level=item.level,
                    first_seen=item.timestamp,
                    last_seen=item.timestamp,
                    sample_event_id=event_id,
                    sample_message=message[:2000],
                )
            delta.count += 1
            delta.services.add(item.service)
            delta.environments.add(item.environment)
            delta.hours[_hour(item.timestamp)] += 1
            delta.first_seen = min(delta.first_seen, item.timestamp)
            if item.timestamp >= delta.last_seen:
                delta.last_seen = item.timestamp
                delta.sample_event_id = event_id
                delta.sample_message = message[:2000]
            if item.level == "fatal":
                delta.level = "fatal"
        _widen(services, item.service, item.timestamp)
        _widen(environments, item.environment, item.timestamp)
        rows.append(
            {
                "org_id": str(scope.org_id),
                "project_id": str(scope.project_id),
                "event_id": str(event_id),
                "timestamp": ch_datetime(item.timestamp),
                "received_at": ch_datetime(now),
                "level": item.level,
                "severity": item.severity,
                "service": item.service,
                "environment": item.environment,
                "host": item.host,
                "message": message,
                "attributes": _attributes_json(attributes),
                "trace_id": item.trace_id,
                "span_id": item.span_id,
                "request_id": item.request_id,
                "exception_type": item.exception_type,
                "stack_trace": stack,
                "fingerprint": fingerprint,
                "redactions": min(event_redactions, 65535),
                "source": source,
            }
        )
        if len(live) < settings.live_publish_per_batch:
            live.append(
                {
                    "event_id": str(event_id),
                    "timestamp": item.timestamp.isoformat(),
                    "level": item.level,
                    "service": item.service,
                    "environment": item.environment,
                    "message": message[:2000],
                    "trace_id": item.trace_id,
                    "request_id": item.request_id,
                    "fingerprint": fingerprint,
                }
            )

    if rejected:
        metrics.ingest_rejected_total.labels(reason="invalid").inc(len(rejected))
    if not rows:
        return IngestResult(accepted=0, rejected=rejected)

    await LogRepository(container.clickhouse).insert(rows)
    group_ids = await ErrorGroupRepository(session).upsert(scope, list(deltas.values()))
    await ServiceRepository(session).touch(scope, services)
    await EnvironmentRepository(session).touch(scope, environments)
    await session.commit()

    if live:
        await container.hub.publish(
            project_topic(scope.project_id), {"type": "logs", "items": live}
        )

    metrics.ingested_events_total.labels(source=source).inc(len(rows))
    for category, n in redaction.counts.items():
        metrics.redactions_total.labels(category=category).inc(n)
    metrics.error_groups_touched_total.inc(len(group_ids))
    metrics.ingest_seconds.observe(time.perf_counter() - started)
    return IngestResult(
        accepted=len(rows),
        rejected=rejected,
        redactions=redaction.total,
        error_groups=len(group_ids),
        event_ids=[uuid.UUID(r["event_id"]) for r in rows],
    )
