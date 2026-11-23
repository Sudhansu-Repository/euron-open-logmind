"""A10 at the unit level: the baseline math."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from logmind.analytics.anomaly import baseline, detect, fill, latest, zscore

T0 = datetime(2026, 11, 16, tzinfo=UTC)
STEP = timedelta(minutes=5)


def series(values: list[int]) -> list[tuple[datetime, int]]:
    return [(T0 + STEP * i, v) for i, v in enumerate(values)]


def test_baseline_and_zscore_floor() -> None:
    b = baseline([2, 4, 4, 4, 5, 5, 7, 9])
    assert b.mean == 5 and b.std == 2 and b.samples == 8
    assert baseline([]).samples == 0
    # A quiet series cannot produce a huge z from a couple of errors: the spread is floored.
    quiet = baseline([0, 0, 0, 0, 0, 0])
    assert zscore(2, quiet) == 2.0
    assert zscore(9, baseline([4] * 10)) == 2.5  # sqrt(mean) floor


def test_detect_flags_only_real_spikes() -> None:
    normal = [3, 4, 2, 5, 3, 4, 3, 2, 4, 3]
    assert detect(series([*normal, 6]), baseline_buckets=10) == []
    found = detect(series([*normal, 40, 4]), baseline_buckets=10)
    assert len(found) == 1 and found[0].value == 40 and found[0].zscore > 3
    assert found[0].at == T0 + STEP * 10
    # Needs enough history and enough errors.
    assert detect(series([0, 0, 50]), baseline_buckets=10) == []
    assert detect(series([0] * 10 + [8]), baseline_buckets=10, min_count=10) == []


def test_latest_and_fill() -> None:
    a, b, v = latest(series([3, 4, 2, 5, 3, 4, 3, 30]), baseline_buckets=20)
    assert a is not None and v == 30 and round(b.mean, 2) == 3.43
    none, _, _ = latest(series([3, 4, 2, 5, 3, 4, 3, 4]), baseline_buckets=20)
    assert none is None
    empty = latest([], baseline_buckets=3)
    assert empty[0] is None and empty[2] == 0
    dense = fill({T0 + STEP: 5}, T0, T0 + STEP * 2, STEP)
    assert dense == [(T0, 0), (T0 + STEP, 5), (T0 + STEP * 2, 0)]
