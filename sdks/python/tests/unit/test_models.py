from __future__ import annotations

import logging
import math
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from euron_logmind.models import (
    MAX_EXC_MESSAGE,
    MAX_MESSAGE,
    MAX_SPAN_ID,
    MAX_STACKTRACE,
    MAX_TRACE_ID,
    IngestResult,
    RejectedLine,
    build_line,
    clamp,
    exception_payload,
    iso_timestamp,
    jsonable,
    normalize_level,
)


class CustomError(Exception):
    pass


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("info", "info"),
        ("INFO", "info"),
        (" Warn ", "warn"),
        ("warning", "warn"),
        ("critical", "fatal"),
        ("fatal", "fatal"),
        ("err", "error"),
        ("trace", "trace"),
        ("debug", "debug"),
        ("panic", "fatal"),
        ("nonsense", "info"),
        (logging.DEBUG, "debug"),
        (logging.INFO, "info"),
        (logging.WARNING, "warn"),
        (logging.ERROR, "error"),
        (logging.CRITICAL, "fatal"),
        (5, "trace"),
        (25, "info"),
    ],
)
def test_normalize_level(given: str | int, expected: str) -> None:
    assert normalize_level(given) == expected


def test_iso_timestamp_now_is_utc_z() -> None:
    stamp = iso_timestamp()
    assert stamp.endswith("Z")
    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    assert abs((datetime.now(timezone.utc) - parsed).total_seconds()) < 5


def test_iso_timestamp_from_epoch_and_datetimes() -> None:
    assert iso_timestamp(0) == "1970-01-01T00:00:00.000000Z"
    assert iso_timestamp(1.5) == "1970-01-01T00:00:01.500000Z"
    naive = datetime(2026, 11, 16, 12, 30, 0)
    assert iso_timestamp(naive) == "2026-11-16T12:30:00.000000Z"
    ist = datetime(2026, 11, 16, 18, 0, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert iso_timestamp(ist) == "2026-11-16T12:30:00.000000Z"


def test_jsonable_handles_awkward_values() -> None:
    loop: dict[str, Any] = {}
    loop["self"] = loop
    out = jsonable(
        {
            "n": 1,
            "f": 1.5,
            "nan": math.nan,
            "inf": math.inf,
            "b": True,
            "none": None,
            "bytes": b"caf\xc3\xa9",
            "tuple": (1, 2),
            "set": {3},
            "when": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "obj": CustomError("boom"),
            "loop": loop,
            5: "int key",
        }
    )
    assert out["n"] == 1 and out["f"] == 1.5 and out["b"] is True and out["none"] is None
    assert out["nan"] == "nan" and out["inf"] == "inf"
    assert out["bytes"] == "café"
    assert out["tuple"] == [1, 2] and out["set"] == [3]
    assert out["when"] == "2026-01-01T00:00:00.000000Z"
    assert out["obj"] == "boom"
    assert out["5"] == "int key"
    # the self reference is cut at a fixed depth instead of recursing forever
    depth = 0
    node: Any = out["loop"]
    while isinstance(node, dict):
        node = node["self"]
        depth += 1
    assert isinstance(node, str) and depth < 10


def test_clamp() -> None:
    assert clamp(None, 3) is None
    assert clamp("abc", 3) == "abc"
    assert clamp("abcdef", 3) == "abc"


def test_exception_payload_variants() -> None:
    assert exception_payload(None) is None
    assert exception_payload(False) is None
    assert exception_payload(True) is None  # nothing is being handled
    assert exception_payload((None, None, None)) is None
    try:
        raise CustomError("card declined")
    except CustomError as exc:
        current = exception_payload(True)
        from_instance = exception_payload(exc)
        from_tuple = exception_payload(sys.exc_info())
    assert current is not None and from_instance is not None and from_tuple is not None
    assert current["type"].endswith("test_models.CustomError")
    assert current["message"] == "card declined"
    assert "Traceback (most recent call last)" in current["stacktrace"]
    assert "raise CustomError" in current["stacktrace"]
    assert from_instance == current == from_tuple


def test_exception_payload_builtin_type_has_no_module_prefix() -> None:
    payload = exception_payload(ValueError("bad"))
    assert payload is not None
    assert payload["type"] == "ValueError"
    assert payload["stacktrace"].strip() == "ValueError: bad"


def test_exception_payload_clamps_long_fields() -> None:
    payload = exception_payload(ValueError("x" * (MAX_EXC_MESSAGE + 10)))
    assert payload is not None
    assert len(payload["message"]) == MAX_EXC_MESSAGE
    huge = ValueError("y" * (MAX_STACKTRACE + 100))
    payload = exception_payload(huge)
    assert payload is not None
    assert len(payload["stacktrace"]) == MAX_STACKTRACE
    assert payload["stacktrace"].endswith("y\n")  # the tail is kept


def test_build_line_minimal() -> None:
    line = build_line("warning", "disk almost full")
    assert set(line) == {"message", "level", "timestamp"}
    assert line["level"] == "warn"
    assert line["message"] == "disk almost full"


def test_build_line_full_and_clamped() -> None:
    line = build_line(
        "error",
        42,
        timestamp=0,
        attributes={"order_id": 7},
        trace_id="t" * 100,
        span_id="s" * 100,
        request_id="req-1",
        exc_info=ValueError("bad"),
        service="checkout",
        environment="staging",
        host="web-2",
    )
    assert line["message"] == "42"
    assert line["timestamp"] == "1970-01-01T00:00:00.000000Z"
    assert line["attributes"] == {"order_id": 7}
    assert len(line["trace_id"]) == MAX_TRACE_ID
    assert len(line["span_id"]) == MAX_SPAN_ID
    assert line["request_id"] == "req-1"
    assert line["service"] == "checkout"
    assert line["environment"] == "staging"
    assert line["host"] == "web-2"
    assert line["exception"]["type"] == "ValueError"


def test_build_line_empty_message_is_never_sent_empty() -> None:
    assert build_line("info", "")["message"] == "(empty message)"
    assert build_line("error", "", exc_info=KeyError("k"))["message"] == "KeyError"


def test_build_line_truncates_huge_message() -> None:
    assert len(build_line("info", "z" * (MAX_MESSAGE + 5))["message"]) == MAX_MESSAGE


def test_ingest_result_parsing() -> None:
    result = IngestResult.from_json(
        {
            "accepted": 2,
            "rejected": [{"index": 1, "reason": "message is empty"}, "junk"],
            "redactions": 3,
            "error_groups": 1,
            "event_ids": ["a", "b"],
        }
    )
    assert result.accepted == 2
    assert result.rejected == [RejectedLine(1, "message is empty")]
    assert result.redactions == 3 and result.error_groups == 1
    assert result.event_ids == ["a", "b"]
    assert IngestResult.from_json("not a dict") == IngestResult(accepted=0)
    assert IngestResult.from_json({}) == IngestResult(accepted=0)


def test_ingest_result_merge_rebases_indexes() -> None:
    first = IngestResult(accepted=1, rejected=[RejectedLine(0, "a")], event_ids=["1"], redactions=1)
    second = IngestResult(
        accepted=2, rejected=[RejectedLine(1, "b")], event_ids=["2", "3"], error_groups=2
    )
    merged = IngestResult.merge([first, second], [0, 5])
    assert merged.accepted == 3
    assert merged.rejected == [RejectedLine(0, "a"), RejectedLine(6, "b")]
    assert merged.event_ids == ["1", "2", "3"]
    assert merged.redactions == 1 and merged.error_groups == 2
