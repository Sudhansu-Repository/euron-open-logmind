"""Basic anomaly detection (A10): is this bucket's error count a genuine deviation from
the series' own history?

For every bucket, the baseline is the mean and standard deviation of the ``baseline``
buckets before it (never including itself, so a spike cannot hide inside its own
baseline). The deviation is a z-score with a floor on the spread: error counts are close
to Poisson, so the spread used is at least ``sqrt(mean)`` and at least ``min_std``, which
stops a quiet service going from 0 to 2 errors from looking like a 10-sigma event. A
bucket is anomalous when its z-score reaches ``threshold`` *and* it has at least
``min_count`` errors.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class Baseline:
    mean: float
    std: float
    samples: int


@dataclass(frozen=True, slots=True)
class Anomaly:
    at: datetime
    value: int
    expected: float
    zscore: float


def baseline(values: list[int]) -> Baseline:
    if not values:
        return Baseline(0.0, 0.0, 0)
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return Baseline(mean, math.sqrt(var), len(values))


def zscore(value: float, b: Baseline, min_std: float = 1.0) -> float:
    spread = max(b.std, math.sqrt(max(b.mean, 0.0)), min_std)
    return (value - b.mean) / spread


def fill(
    points: dict[datetime, int], start: datetime, end: datetime, step: timedelta
) -> list[tuple[datetime, int]]:
    """A dense series from ``start`` to ``end`` with zeros where nothing was logged."""
    out: list[tuple[datetime, int]] = []
    t = start
    while t <= end:
        out.append((t, points.get(t, 0)))
        t += step
    return out


def detect(
    series: list[tuple[datetime, int]],
    *,
    baseline_buckets: int,
    threshold: float = 3.0,
    min_count: int = 10,
    min_baseline: int = 6,
) -> list[Anomaly]:
    found: list[Anomaly] = []
    values = [v for _, v in series]
    for i, (at, value) in enumerate(series):
        history = values[max(0, i - baseline_buckets) : i]
        if len(history) < min_baseline or value < min_count:
            continue
        b = baseline(history)
        z = zscore(value, b)
        if z >= threshold:
            found.append(Anomaly(at, value, round(b.mean, 2), round(z, 2)))
    return found


def latest(
    series: list[tuple[datetime, int]],
    *,
    baseline_buckets: int,
    threshold: float = 3.0,
    min_count: int = 10,
) -> tuple[Anomaly | None, Baseline, int]:
    """The newest bucket against the buckets before it: what an alert rule evaluates."""
    if not series:
        return None, Baseline(0.0, 0.0, 0), 0
    *history_points, (at, value) = series
    history = [v for _, v in history_points][-baseline_buckets:]
    b = baseline(history)
    z = zscore(value, b) if history else 0.0
    if len(history) >= 6 and value >= min_count and z >= threshold:
        return Anomaly(at, value, round(b.mean, 2), round(z, 2)), b, value
    return None, b, value
