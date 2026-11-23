"""Turn whatever a client sent (native JSON, SDK batches, OTLP records) into one
:class:`RawEvent` shape: a known level, a UTC timestamp inside the accepted window,
bounded strings, string trace ids. Everything downstream (redaction, fingerprinting,
storage) works on this shape only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

LEVELS = ("trace", "debug", "info", "warn", "error", "fatal")
# OTLP SeverityNumber ranges: 1-4 trace, 5-8 debug, 9-12 info, 13-16 warn, 17-20 error,
# 21-24 fatal. The stored severity is the first number of each range.
SEVERITY = {"trace": 1, "debug": 5, "info": 9, "warn": 13, "error": 17, "fatal": 21}
_ALIASES = {
    "trace": "trace",
    "verbose": "trace",
    "debug": "debug",
    "info": "info",
    "information": "info",
    "notice": "info",
    "log": "info",
    "warn": "warn",
    "warning": "warn",
    "error": "error",
    "err": "error",
    "exception": "error",
    "critical": "fatal",
    "crit": "fatal",
    "fatal": "fatal",
    "alert": "fatal",
    "emergency": "fatal",
    "panic": "fatal",
}
ERROR_LEVELS = frozenset({"error", "fatal"})
_NAME = re.compile(r"[^A-Za-z0-9_.:/-]+")


class InvalidEventError(ValueError):
    """One event could not be accepted; the message says why (returned to the client)."""


def normalize_level(value: str | None, severity_number: int | None = None) -> str:
    if value:
        level = _ALIASES.get(value.strip().lower())
        if level:
            return level
    if severity_number:
        if severity_number >= 21:
            return "fatal"
        if severity_number >= 17:
            return "error"
        if severity_number >= 13:
            return "warn"
        if severity_number >= 9:
            return "info"
        if severity_number >= 5:
            return "debug"
        return "trace"
    return "info"


def parse_timestamp(value: Any) -> datetime | None:
    """ISO 8601 text, or epoch seconds, milliseconds, microseconds or nanoseconds (told
    apart by magnitude). ``None`` when absent."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, int | float) or (isinstance(value, str) and value.isdigit()):
        n = float(value)
        if n > 1e17:
            n /= 1e9
        elif n > 1e14:
            n /= 1e6
        elif n > 1e11:
            n /= 1e3
        return datetime.fromtimestamp(n, UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise InvalidEventError(f"timestamp {value[:40]!r} is not ISO 8601 or epoch") from exc
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    raise InvalidEventError("timestamp must be ISO 8601 text or an epoch number")


def clean_name(value: str | None, default: str, max_len: int = 64) -> str:
    """Service, environment and host names: printable, bounded, never empty."""
    if not value:
        return default
    cleaned = _NAME.sub("-", value.strip())[:max_len].strip("-")
    return cleaned or default


@dataclass(slots=True)
class RawEvent:
    timestamp: datetime
    level: str
    message: str
    service: str
    environment: str
    host: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""
    span_id: str = ""
    request_id: str = ""
    exception_type: str = ""
    stack_trace: str = ""

    @property
    def severity(self) -> int:
        return SEVERITY[self.level]

    @property
    def is_error(self) -> bool:
        return self.level in ERROR_LEVELS or bool(self.stack_trace)


def check_window(ts: datetime, now: datetime, max_past_days: int, max_future_minutes: int) -> None:
    if ts < now - timedelta(days=max_past_days):
        raise InvalidEventError(f"timestamp is more than {max_past_days} days in the past")
    if ts > now + timedelta(minutes=max_future_minutes):
        raise InvalidEventError(
            f"timestamp is more than {max_future_minutes} minutes in the future (clock skew?)"
        )


def truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 12] + " [truncated]"
