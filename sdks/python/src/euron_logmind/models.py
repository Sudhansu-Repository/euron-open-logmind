"""Wire models: building one log line in LogMind's native shape, and parsing the
``IngestResult`` the API answers with.

Every field is clamped to the API's own limits here, before it is queued. The batch
endpoint validates the whole body at once, so one oversized ``trace_id`` would otherwise
get the entire batch rejected with a 422 and lose every other line in it.
"""

from __future__ import annotations

import logging
import sys
import traceback
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import TracebackType
from typing import Any

LEVELS = ("trace", "debug", "info", "warn", "error", "fatal")

# Limits from the API's ingestion schemas (apps/api/src/logmind/ingestion/schemas.py).
MAX_MESSAGE = 1_000_000
MAX_SERVICE = 120
MAX_ENVIRONMENT = 120
MAX_HOST = 255
MAX_TRACE_ID = 64
MAX_SPAN_ID = 32
MAX_REQUEST_ID = 128
MAX_EXC_TYPE = 200
MAX_EXC_MESSAGE = 4000
MAX_STACKTRACE = 64_000
MAX_BATCH = 1000

_ALIASES = {
    "warning": "warn",
    "critical": "fatal",
    "err": "error",
    "information": "info",
    "notice": "info",
    "panic": "fatal",
}

ExcInfoTuple = tuple[type[BaseException], BaseException, TracebackType | None]
ExcInfo = bool | BaseException | ExcInfoTuple | tuple[None, None, None] | None


def normalize_level(level: str | int) -> str:
    """Map a level name (any case, ``warning``/``critical`` aliases) or a stdlib logging
    level number to one of LogMind's six levels. Unknown names fall back to ``info``."""
    if isinstance(level, int):
        if level >= logging.CRITICAL:
            return "fatal"
        if level >= logging.ERROR:
            return "error"
        if level >= logging.WARNING:
            return "warn"
        if level >= logging.INFO:
            return "info"
        if level >= logging.DEBUG:
            return "debug"
        return "trace"
    name = str(level).strip().lower()
    name = _ALIASES.get(name, name)
    return name if name in LEVELS else "info"


def iso_timestamp(value: datetime | float | None = None) -> str:
    """An ISO 8601 UTC timestamp with microseconds and a ``Z`` suffix.

    ``value`` is a datetime (naive is taken as UTC) or epoch seconds; ``None`` means now."""
    if value is None:
        dt = datetime.now(timezone.utc)
    elif isinstance(value, datetime):
        dt = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        dt = dt.astimezone(timezone.utc)
    else:
        dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
    return dt.isoformat(timespec="microseconds").replace("+00:00", "Z")


_MAX_DEPTH = 8


def jsonable(value: Any, depth: int = 0) -> Any:
    """A JSON-safe copy of an attribute value.

    Done once, when the line is logged, so a value that changes later is captured as it
    was, a non-serialisable object becomes its ``str()``, a NaN or infinity becomes a
    string (``json.dumps`` would emit invalid JSON for it) and a self-referencing structure
    is cut at a fixed depth instead of crashing the sender."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return (
            value if value == value and value not in (float("inf"), float("-inf")) else str(value)
        )
    if depth >= _MAX_DEPTH:
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): jsonable(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [jsonable(v, depth + 1) for v in value]
    if isinstance(value, datetime):
        return iso_timestamp(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def clamp(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= limit else text[:limit]


def exception_payload(exc_info: ExcInfo) -> dict[str, str] | None:
    """``{type, message, stacktrace}`` for an exception, or ``None``.

    ``exc_info=True`` reads the exception currently being handled (``sys.exc_info()``),
    exactly like the stdlib ``logging`` module; outside an ``except`` block it is ``None``.
    """
    if exc_info is None or exc_info is False:
        return None
    if exc_info is True:
        current = sys.exc_info()
        if current[1] is None:
            return None
        exc = current[1]
    elif isinstance(exc_info, BaseException):
        exc = exc_info
    else:
        if exc_info[1] is None:
            return None
        exc = exc_info[1]
    cls = type(exc)
    name = (
        cls.__qualname__ if cls.__module__ == "builtins" else f"{cls.__module__}.{cls.__qualname__}"
    )
    stack = "".join(traceback.format_exception(cls, exc, exc.__traceback__))
    return {
        "type": name[:MAX_EXC_TYPE],
        "message": str(exc)[:MAX_EXC_MESSAGE],
        # Keep the tail: the innermost frames and the exception line are the useful part.
        "stacktrace": stack if len(stack) <= MAX_STACKTRACE else stack[-MAX_STACKTRACE:],
    }


def build_line(
    level: str | int,
    message: object,
    *,
    timestamp: datetime | float | None = None,
    attributes: Mapping[str, Any] | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    request_id: str | None = None,
    exc_info: ExcInfo = None,
    service: str | None = None,
    environment: str | None = None,
    host: str | None = None,
) -> dict[str, Any]:
    """One ``LogIn`` object, with only the fields that are set."""
    text = message if isinstance(message, str) else str(message)
    exception = exception_payload(exc_info)
    if not text:
        text = exception["type"] if exception else "(empty message)"
    line: dict[str, Any] = {
        "message": text[:MAX_MESSAGE],
        "level": normalize_level(level),
        "timestamp": iso_timestamp(timestamp),
    }
    if attributes:
        line["attributes"] = {str(k): jsonable(v) for k, v in attributes.items()}
    for key, value, limit in (
        ("trace_id", trace_id, MAX_TRACE_ID),
        ("span_id", span_id, MAX_SPAN_ID),
        ("request_id", request_id, MAX_REQUEST_ID),
        ("service", service, MAX_SERVICE),
        ("environment", environment, MAX_ENVIRONMENT),
        ("host", host, MAX_HOST),
    ):
        if value:
            line[key] = clamp(value, limit)
    if exception:
        line["exception"] = exception
    return line


@dataclass(frozen=True)
class RejectedLine:
    """A line the API refused, by its index in the batch that was sent."""

    index: int
    reason: str


@dataclass(frozen=True)
class IngestResult:
    """The API's answer to one batch (HTTP 202)."""

    accepted: int
    rejected: list[RejectedLine] = field(default_factory=list)
    redactions: int = 0
    error_groups: int = 0
    event_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_json(cls, data: Any) -> IngestResult:
        if not isinstance(data, dict):
            return cls(accepted=0)
        rejected = [
            RejectedLine(index=int(r.get("index", -1)), reason=str(r.get("reason", "")))
            for r in data.get("rejected") or []
            if isinstance(r, dict)
        ]
        return cls(
            accepted=int(data.get("accepted") or 0),
            rejected=rejected,
            redactions=int(data.get("redactions") or 0),
            error_groups=int(data.get("error_groups") or 0),
            event_ids=[str(e) for e in data.get("event_ids") or []],
        )

    @classmethod
    def merge(cls, results: list[IngestResult], offsets: list[int]) -> IngestResult:
        """Combine the results of a batch that was split in parts, re-basing indexes."""
        rejected = [
            RejectedLine(r.index + offset, r.reason)
            for result, offset in zip(results, offsets, strict=True)
            for r in result.rejected
        ]
        return cls(
            accepted=sum(r.accepted for r in results),
            rejected=rejected,
            redactions=sum(r.redactions for r in results),
            error_groups=sum(r.error_groups for r in results),
            event_ids=[e for r in results for e in r.event_ids],
        )


@dataclass(frozen=True)
class Stats:
    """Counters since the client was created. Every line is accounted for exactly once
    as ``accepted``, ``rejected``, ``dropped_queue_full``, ``dropped_failed``,
    ``dropped_closed`` or still ``queued``."""

    queued: int
    accepted: int
    rejected: int
    dropped_queue_full: int
    dropped_failed: int
    dropped_closed: int
    batches_sent: int
    retries: int
