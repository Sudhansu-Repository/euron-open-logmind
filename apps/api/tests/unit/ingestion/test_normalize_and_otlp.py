"""Ingestion normalisation and both OTLP encodings, without a server."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import orjson
import pytest
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest

from logmind.ingestion import otlp
from logmind.ingestion.normalize import (
    InvalidEventError,
    RawEvent,
    check_window,
    clean_name,
    normalize_level,
    parse_timestamp,
    truncate,
)

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("text", "number", "level"),
    [
        ("WARNING", None, "warn"),
        ("Critical", None, "fatal"),
        ("err", None, "error"),
        ("", 3, "trace"),
        ("", 6, "debug"),
        ("", 10, "info"),
        ("", 14, "warn"),
        ("", 18, "error"),
        ("", 22, "fatal"),
        ("weird", None, "info"),
        (None, None, "info"),
    ],
)
def test_levels(text: str | None, number: int | None, level: str) -> None:
    assert normalize_level(text, number) == level


def test_timestamps_in_every_unit() -> None:
    base = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    s = base.timestamp()
    for value in (s, int(s * 1e3), int(s * 1e6), int(s * 1e9), str(int(s))):
        assert abs(parse_timestamp(value) - base) < timedelta(milliseconds=1)  # type: ignore[operator]
    assert parse_timestamp("2026-01-02T03:04:05Z") == base
    assert parse_timestamp("2026-01-02T03:04:05").tzinfo is not None  # type: ignore[union-attr]
    assert parse_timestamp(None) is None and parse_timestamp("") is None
    assert parse_timestamp(base.replace(tzinfo=None)) == base
    with pytest.raises(InvalidEventError):
        parse_timestamp("yesterday")
    with pytest.raises(InvalidEventError):
        parse_timestamp([1])


def test_window_names_and_truncation() -> None:
    check_window(NOW, NOW, 30, 10)
    with pytest.raises(InvalidEventError, match="past"):
        check_window(NOW - timedelta(days=31), NOW, 30, 10)
    with pytest.raises(InvalidEventError, match="future"):
        check_window(NOW + timedelta(minutes=11), NOW, 30, 10)
    assert clean_name(" my svc!! ", "x") == "my-svc"
    assert clean_name(None, "unknown") == "unknown" and clean_name("!!!", "d") == "d"
    assert truncate("a" * 50, 30).endswith("[truncated]") and len(truncate("a" * 50, 30)) == 30
    ev = RawEvent(NOW, "warn", "m", "s", "e", stack_trace="x")
    assert ev.severity == 13 and ev.is_error


def _proto() -> bytes:
    req = ExportLogsServiceRequest()
    rl = req.resource_logs.add()
    attr = rl.resource.attributes.add()
    attr.key, attr.value.string_value = "service.name", "billing"
    env = rl.resource.attributes.add()
    env.key, env.value.string_value = "deployment.environment", "prod-eu"
    region = rl.resource.attributes.add()
    region.key, region.value.string_value = "cloud.region", "eu-west-1"
    rec = rl.scope_logs.add().log_records.add()
    rec.time_unix_nano = time.time_ns()
    rec.severity_number = 17
    rec.body.string_value = "charge failed"
    rec.trace_id = bytes.fromhex("4bf92f3577b34da6a3ce929d0e0e4736")
    a = rec.attributes.add()
    a.key, a.value.string_value = "exception.type", "CardDeclined"
    b = rec.attributes.add()
    b.key = "tags"
    b.value.array_value.values.add().int_value = 3
    c = rec.attributes.add()
    c.key = "blob"
    c.value.bytes_value = b"\x01\x02"
    d = rec.attributes.add()
    d.key = "kv"
    kv = d.value.kvlist_value.values.add()
    kv.key, kv.value.bool_value = "ok", True
    empty = rl.scope_logs[0].log_records.add()
    empty.time_unix_nano = time.time_ns()
    data: bytes = req.SerializeToString()
    return data


def test_protobuf_mapping() -> None:
    parsed = list(otlp.parse_protobuf(_proto(), now=NOW, max_chars=1000))
    (i0, ev), (i1, err) = parsed
    assert isinstance(ev, RawEvent) and isinstance(err, InvalidEventError)
    assert (i0, i1) == (0, 1)
    assert ev.service == "billing" and ev.environment == "prod-eu" and ev.level == "error"
    assert ev.exception_type == "CardDeclined" and ev.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert (
        ev.attributes["tags"] == [3]
        and ev.attributes["blob"] == "AQI="
        and ev.attributes["kv"] == {"ok": True}
    )
    assert ev.attributes["resource"] == {"cloud.region": "eu-west-1"}
    with pytest.raises(InvalidEventError):
        list(otlp.parse_protobuf(b"\xff\xff\xff", now=NOW, max_chars=10))


def test_json_mapping_values_and_errors() -> None:
    doc = {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": "web"}}]
                },
                "scopeLogs": [
                    {
                        "logRecords": [
                            {
                                "observedTimeUnixNano": str(time.time_ns()),
                                "severityText": "ERROR",
                                "attributes": [
                                    {"key": "exception.message", "value": {"stringValue": "boom"}},
                                    {"key": "d", "value": {"doubleValue": 1.5}},
                                    {"key": "b", "value": {"bytesValue": "AQI="}},
                                    {
                                        "key": "arr",
                                        "value": {"arrayValue": {"values": [{"boolValue": False}]}},
                                    },
                                    {"key": "requestId", "value": {"stringValue": "r-1"}},
                                    {"key": "n", "value": {}},
                                ],
                            },
                            {"timeUnixNano": "nope", "body": {"stringValue": "fallback time"}},
                            {"attributes": [{"value": {"stringValue": "no key"}}]},
                        ]
                    }
                ],
            }
        ]
    }
    parsed = list(otlp.parse_json(orjson.dumps(doc), now=NOW, max_chars=100))
    ev = parsed[0][1]
    assert isinstance(ev, RawEvent)
    assert ev.message == "boom" and ev.request_id == "r-1"
    assert ev.attributes == {"d": 1.5, "b": "AQI=", "arr": [False], "n": None, "requestId": "r-1"}
    assert isinstance(parsed[1][1], RawEvent) and parsed[1][1].timestamp == NOW
    assert isinstance(parsed[2][1], InvalidEventError)
    with pytest.raises(InvalidEventError):
        list(otlp.parse_json(b"[]", now=NOW, max_chars=10))
    with pytest.raises(InvalidEventError):
        list(otlp.parse_json(b"{", now=NOW, max_chars=10))
