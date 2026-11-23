"""What an alert rule measures, against live data in ClickHouse.

Threshold rules measure one number over the last ``window_minutes``. Anomaly rules sum
errors over five-minute windows ending now (sliding, built from the per-minute rollup)
and compare the newest window with the ``baseline_hours`` of windows before it
(``analytics/anomaly.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from logmind.alerts.models import AlertRule
from logmind.analytics.anomaly import latest
from logmind.core.db import ProjectScope
from logmind.logs.repository import LogFilter, LogRepository

ANOMALY_WINDOW = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class Measurement:
    value: float
    breached: bool
    threshold: float | None = None
    expected: float | None = None
    zscore: float | None = None
    description: str = ""


def _filter(
    rule: AlertRule,
    start: datetime,
    end: datetime,
    *,
    levels: list[str] | None = None,
    q: str = "",
) -> LogFilter:
    return LogFilter(
        start=start,
        end=end,
        q=q,
        services=[rule.service] if rule.service else [],
        environments=[rule.environment] if rule.environment else [],
        levels=levels or [],
    )


def _subject(rule: AlertRule) -> str:
    parts = [rule.service or "all services"]
    if rule.environment:
        parts.append(rule.environment)
    return " in ".join(parts)


async def measure(
    repo: LogRepository, scope: ProjectScope, rule: AlertRule, now: datetime | None = None
) -> Measurement:
    now = now or datetime.now(UTC)
    if rule.kind == "anomaly":
        return await _anomaly(repo, scope, rule, now)
    start = now - timedelta(minutes=rule.window_minutes)
    errors = ["error", "fatal"]
    if rule.metric == "error_count":
        value = float(await repo.count(scope, _filter(rule, start, now, levels=errors)))
        what = "errors"
    elif rule.metric == "log_count":
        value = float(await repo.count(scope, _filter(rule, start, now)))
        what = "log lines"
    elif rule.metric == "matching_count":
        value = float(await repo.count(scope, _filter(rule, start, now, q=rule.query)))
        what = f'lines matching "{rule.query}"'
    else:
        total = await repo.count(scope, _filter(rule, start, now))
        err = await repo.count(scope, _filter(rule, start, now, levels=errors))
        value = round(100.0 * err / total, 2) if total else 0.0
        what = "% errors"
    breached = value > rule.threshold
    unit = "" if rule.metric == "error_rate" else " "
    return Measurement(
        value=value,
        breached=breached,
        threshold=rule.threshold,
        description=(
            f"{value:g}{unit}{what} in the last {rule.window_minutes} min for {_subject(rule)} "
            f"({'above' if breached else 'within'} the threshold of {rule.threshold:g})"
        ),
    )


async def _anomaly(
    repo: LogRepository, scope: ProjectScope, rule: AlertRule, now: datetime
) -> Measurement:
    start = now - timedelta(hours=rule.baseline_hours) - ANOMALY_WINDOW
    rows = await repo.histogram(scope, _filter(rule, start, now, levels=["error", "fatal"]), 60)
    per_minute: dict[datetime, int] = {}
    for at, _level, n in rows:
        per_minute[at] = per_minute.get(at, 0) + n
    # Five-minute windows ending at ``now``, oldest first; the last is the current one.
    windows: list[tuple[datetime, int]] = []
    step = int(ANOMALY_WINDOW.total_seconds() // 60)
    end_minute = now.replace(second=0, microsecond=0)
    count = int(rule.baseline_hours * 60 // step) + 1
    for i in range(count - 1, -1, -1):
        w_end = end_minute - timedelta(minutes=i * step)
        total = sum(per_minute.get(w_end - timedelta(minutes=m), 0) for m in range(step))
        windows.append((w_end, total))
    anomaly, base, value = latest(
        windows,
        baseline_buckets=count - 1,
        threshold=rule.sensitivity,
        min_count=rule.min_count,
    )
    z = anomaly.zscore if anomaly else None
    return Measurement(
        value=float(value),
        breached=anomaly is not None,
        expected=round(base.mean, 2),
        zscore=z,
        description=(
            f"{value} errors in the last 5 min for {_subject(rule)}; the {rule.baseline_hours} h "
            f"baseline is {base.mean:.1f} per 5 min"
            + (f" ({z:.1f} standard deviations above it)" if z is not None else "")
        ),
    )
