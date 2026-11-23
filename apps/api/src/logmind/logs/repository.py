"""The only module that queries ``log_events`` and ``log_rollup_1m`` in ClickHouse.

Every statement is built through :meth:`LogRepository._where`, which always starts with
``org_id = {org} AND project_id = {project}`` from the :class:`ProjectScope` the caller
must pass (A8). There is no method that takes raw SQL or an org id from a request; the
tenant filter cannot be forgotten because there is no way to build a query without it.
Values are bound as ClickHouse query parameters, never spliced into SQL text.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import orjson

from logmind.core.clickhouse import ClickHouse, ch_datetime, parse_ch_datetime
from logmind.core.db import ProjectScope

_COLUMNS = (
    "toString(event_id) AS eid, timestamp, received_at, level, service, environment, host, "
    "message, attributes, trace_id, span_id, request_id, exception_type, stack_trace, "
    "fingerprint, redactions, source"
)


@dataclass(frozen=True, slots=True)
class ServiceBucket:
    service: str
    bucket: datetime
    total: int
    errors: int
    warnings: int


@dataclass(slots=True)
class StoredEvent:
    event_id: uuid.UUID
    timestamp: datetime
    received_at: datetime
    level: str
    service: str
    environment: str
    host: str
    message: str
    attributes: dict[str, Any]
    trace_id: str
    span_id: str
    request_id: str
    exception_type: str
    stack_trace: str
    fingerprint: str
    redactions: int
    source: str


def _row(r: dict[str, Any]) -> StoredEvent:
    try:
        attrs = orjson.loads(r.get("attributes") or "{}")
    except orjson.JSONDecodeError:
        attrs = {}
    return StoredEvent(
        event_id=uuid.UUID(r["eid"]),
        timestamp=parse_ch_datetime(r["timestamp"]),
        received_at=parse_ch_datetime(r["received_at"]),
        level=r["level"],
        service=r["service"],
        environment=r["environment"],
        host=r["host"],
        message=r["message"],
        attributes=attrs if isinstance(attrs, dict) else {},
        trace_id=r["trace_id"],
        span_id=r["span_id"],
        request_id=r["request_id"],
        exception_type=r["exception_type"],
        stack_trace=r["stack_trace"],
        fingerprint=r["fingerprint"],
        redactions=int(r["redactions"]),
        source=r["source"],
    )


def like_pattern(term: str) -> str:
    escaped = term.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@dataclass(slots=True)
class LogFilter:
    start: datetime
    end: datetime
    q: str = ""
    services: list[str] = field(default_factory=list)
    environments: list[str] = field(default_factory=list)
    levels: list[str] = field(default_factory=list)
    trace_id: str = ""
    request_id: str = ""
    fingerprint: str = ""
    # Lines whose message contains at least one of these words (case-insensitive).
    any_terms: list[str] = field(default_factory=list)
    # Lines that are not in this error group (evidence retrieval looks around a group).
    exclude_fingerprint: str = ""

    @property
    def needs_raw(self) -> bool:
        """Whether a count must scan log lines (the rollup has no message or ids)."""
        return bool(
            self.q
            or self.trace_id
            or self.request_id
            or self.fingerprint
            or self.any_terms
            or self.exclude_fingerprint
        )


class LogRepository:
    def __init__(self, ch: ClickHouse) -> None:
        self.ch = ch

    @staticmethod
    def _where(
        scope: ProjectScope, f: LogFilter, params: dict[str, Any], *, time_col: str = "timestamp"
    ) -> str:
        params["org"] = str(scope.org_id)
        params["project"] = str(scope.project_id)
        params["start"] = ch_datetime(f.start)
        params["end"] = ch_datetime(f.end)
        clauses = [
            "org_id = {org:UUID}",
            "project_id = {project:UUID}",
            f"{time_col} >= {{start:DateTime64(6)}}",
            f"{time_col} <= {{end:DateTime64(6)}}",
        ]
        if f.services:
            params["services"] = f.services
            clauses.append("service IN {services:Array(String)}")
        if f.environments:
            params["environments"] = f.environments
            clauses.append("environment IN {environments:Array(String)}")
        if f.levels:
            params["levels"] = f.levels
            clauses.append("level IN {levels:Array(String)}")
        if time_col == "timestamp":
            for i, term in enumerate(t for t in f.q.split() if t):
                params[f"q{i}"] = like_pattern(term)
                clauses.append(
                    f"(lower(message) LIKE {{q{i}:String}} OR lower(exception_type) LIKE "
                    f"{{q{i}:String}} OR lower(stack_trace) LIKE {{q{i}:String}})"
                )
            if f.trace_id:
                params["trace_id"] = f.trace_id.lower()
                clauses.append("trace_id = {trace_id:String}")
            if f.request_id:
                params["request_id"] = f.request_id
                clauses.append("request_id = {request_id:String}")
            if f.fingerprint:
                params["fingerprint"] = f.fingerprint
                clauses.append("fingerprint = {fingerprint:String}")
            if f.exclude_fingerprint:
                params["xfp"] = f.exclude_fingerprint
                clauses.append("fingerprint != {xfp:String}")
            if f.any_terms:
                ors = []
                for i, term in enumerate(f.any_terms):
                    params[f"a{i}"] = like_pattern(term)
                    ors.append(f"lower(message) LIKE {{a{i}:String}}")
                clauses.append("(" + " OR ".join(ors) + ")")
        return " AND ".join(clauses)

    async def insert(self, rows: list[dict[str, Any]]) -> None:
        await self.ch.insert("log_events", rows)

    async def search(
        self,
        scope: ProjectScope,
        f: LogFilter,
        *,
        limit: int,
        before: tuple[datetime, uuid.UUID] | None = None,
        ascending: bool = False,
    ) -> list[StoredEvent]:
        """Newest first (or oldest first), keyset-paginated on ``(timestamp, event_id)``."""
        params: dict[str, Any] = {"limit": limit}
        where = self._where(scope, f, params)
        if before is not None:
            params["cts"] = ch_datetime(before[0])
            params["cid"] = str(before[1])
            op = ">" if ascending else "<"
            where += f" AND (timestamp, event_id) {op} ({{cts:DateTime64(6)}}, {{cid:UUID}})"
        order = "ASC" if ascending else "DESC"
        sql = (
            f"SELECT {_COLUMNS} FROM log_events WHERE {where} "
            f"ORDER BY timestamp {order}, event_id {order} LIMIT {{limit:UInt32}}"
        )
        return [_row(r) for r in await self.ch.query(sql, params)]

    async def get(
        self, scope: ProjectScope, event_id: uuid.UUID, start: datetime, end: datetime
    ) -> StoredEvent | None:
        params: dict[str, Any] = {"event_id": str(event_id)}
        where = self._where(scope, LogFilter(start=start, end=end), params)
        sql = (
            f"SELECT {_COLUMNS} FROM log_events WHERE {where} "
            "AND event_id = {event_id:UUID} LIMIT 1"
        )
        rows = await self.ch.query(sql, params)
        return _row(rows[0]) if rows else None

    async def get_many(
        self, scope: ProjectScope, event_ids: list[uuid.UUID], start: datetime, end: datetime
    ) -> dict[uuid.UUID, StoredEvent]:
        if not event_ids:
            return {}
        params: dict[str, Any] = {"ids": [str(e) for e in event_ids]}
        where = self._where(scope, LogFilter(start=start, end=end), params)
        sql = f"SELECT {_COLUMNS} FROM log_events WHERE {where} AND event_id IN {{ids:Array(UUID)}}"
        return {e.event_id: e for e in (_row(r) for r in await self.ch.query(sql, params))}

    async def count(self, scope: ProjectScope, f: LogFilter) -> int:
        params: dict[str, Any] = {}
        if f.needs_raw:
            where = self._where(scope, f, params)
            sql = f"SELECT count() AS n FROM log_events WHERE {where}"
        else:
            where = self._where(scope, f, params, time_col="minute")
            sql = f"SELECT sum(events) AS n FROM log_rollup_1m WHERE {where}"
        rows = await self.ch.query(sql, params)
        return int(rows[0]["n"] or 0) if rows else 0

    async def histogram(
        self, scope: ProjectScope, f: LogFilter, bucket_s: int
    ) -> list[tuple[datetime, str, int]]:
        """``(bucket_start, level, count)``; from the per-minute rollup unless a filter
        needs the log lines themselves."""
        params: dict[str, Any] = {"bucket": bucket_s}
        if f.needs_raw:
            where = self._where(scope, f, params)
            sql = (
                "SELECT toStartOfInterval(timestamp, toIntervalSecond({bucket:UInt32})) AS b, "
                f"level, count() AS n FROM log_events WHERE {where} "
                "GROUP BY b, level ORDER BY b"
            )
        else:
            where = self._where(scope, f, params, time_col="minute")
            sql = (
                "SELECT toStartOfInterval(minute, toIntervalSecond({bucket:UInt32})) AS b, "
                f"level, sum(events) AS n FROM log_rollup_1m WHERE {where} "
                "GROUP BY b, level ORDER BY b"
            )
        return [
            (parse_ch_datetime(r["b"]), str(r["level"]), int(r["n"]))
            for r in await self.ch.query(sql, params)
        ]

    async def service_stats(
        self, scope: ProjectScope, f: LogFilter, bucket_s: int
    ) -> list[ServiceBucket]:
        """Per service and bucket: total lines and error lines, from the rollup."""
        params: dict[str, Any] = {"bucket": bucket_s}
        where = self._where(scope, f, params, time_col="minute")
        sql = (
            "SELECT service, toStartOfInterval(minute, toIntervalSecond({bucket:UInt32})) AS b, "
            "sum(events) AS total, sumIf(events, level IN ('error', 'fatal')) AS errors, "
            "sumIf(events, level = 'warn') AS warnings "
            f"FROM log_rollup_1m WHERE {where} GROUP BY service, b ORDER BY service, b"
        )
        return [
            ServiceBucket(
                service=str(r["service"]),
                bucket=parse_ch_datetime(r["b"]),
                total=int(r["total"]),
                errors=int(r["errors"]),
                warnings=int(r["warnings"]),
            )
            for r in await self.ch.query(sql, params)
        ]

    async def facet(self, scope: ProjectScope, f: LogFilter, column: str) -> list[tuple[str, int]]:
        """Distinct values with counts for a filter sidebar (service, environment, level)."""
        if column not in ("service", "environment", "level"):
            raise ValueError(f"not a facet column: {column!r}")
        params: dict[str, Any] = {}
        where = self._where(scope, f, params, time_col="minute")
        sql = (
            f"SELECT {column} AS v, sum(events) AS n FROM log_rollup_1m WHERE {where} "
            "GROUP BY v ORDER BY n DESC LIMIT 100"
        )
        return [(str(r["v"]), int(r["n"])) for r in await self.ch.query(sql, params)]

    async def volume(self, scope: ProjectScope, f: LogFilter) -> tuple[int, int]:
        """``(lines, total message characters)`` in a window: the raw volume an
        investigation would have to read if it did no evidence selection (A4)."""
        params: dict[str, Any] = {}
        where = self._where(scope, f, params)
        sql = (
            "SELECT count() AS n, sum(length(message) + length(stack_trace)) AS chars "
            f"FROM log_events WHERE {where}"
        )
        rows = await self.ch.query(sql, params)
        if not rows:
            return 0, 0
        return int(rows[0]["n"] or 0), int(rows[0]["chars"] or 0)

    async def redaction_total(self, scope: ProjectScope, f: LogFilter) -> int:
        params: dict[str, Any] = {}
        where = self._where(scope, f, params)
        rows = await self.ch.query(
            f"SELECT sum(redactions) AS n FROM log_events WHERE {where}", params
        )
        return int(rows[0]["n"] or 0) if rows else 0

    async def templates(
        self, scope: ProjectScope, f: LogFilter, *, limit: int
    ) -> list[dict[str, Any]]:
        """Distinct messages (first 160 characters, digits folded) with their count, first
        and last time, service, level and one representative event id. This is the core
        of context compression: 400 identical timeout lines become one item with a count."""
        params: dict[str, Any] = {"limit": limit}
        where = self._where(scope, f, params)
        sql = (
            "SELECT service, level, "
            "replaceRegexpAll(substring(message, 1, 160), '[0-9a-fA-F]*[0-9][0-9a-fA-F]*', '#') "
            "AS template, "
            "count() AS n, min(timestamp) AS first_ts, max(timestamp) AS last_ts, "
            "toString(argMin(event_id, timestamp)) AS first_id, "
            "substring(argMin(message, timestamp), 1, 600) AS first_message "
            f"FROM log_events WHERE {where} "
            "GROUP BY service, level, template ORDER BY first_ts LIMIT {limit:UInt32}"
        )
        return [
            {
                "service": str(r["service"]),
                "level": str(r["level"]),
                "template": str(r["template"]),
                "count": int(r["n"]),
                "first_ts": parse_ch_datetime(r["first_ts"]),
                "last_ts": parse_ch_datetime(r["last_ts"]),
                "first_id": uuid.UUID(r["first_id"]),
                "first_message": str(r["first_message"]),
            }
            for r in await self.ch.query(sql, params)
        ]

    async def delete_older_than(self, scope: ProjectScope, cutoff: datetime) -> None:
        """Retention: a lightweight delete of one project's lines before ``cutoff``."""
        params: dict[str, Any] = {
            "org": str(scope.org_id),
            "project": str(scope.project_id),
            "cutoff": ch_datetime(cutoff),
        }
        where = (
            "org_id = {org:UUID} AND project_id = {project:UUID} AND "
            "timestamp < {cutoff:DateTime64(6)}"
        )
        await self.ch.query_command(f"DELETE FROM log_events WHERE {where}", params)
        rollup_where = where.replace("timestamp", "minute")
        await self.ch.query_command(f"DELETE FROM log_rollup_1m WHERE {rollup_where}", params)
