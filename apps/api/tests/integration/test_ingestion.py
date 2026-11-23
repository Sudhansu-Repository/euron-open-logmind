"""A1 and A6: logs sent over the native API, the batch API and OTLP (protobuf, JSON,
gzip) are stored and queryable as soon as the request returns."""

from __future__ import annotations

import gzip
import time
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import orjson
import pytest
from opentelemetry._logs import LogRecord, SeverityNumber
from opentelemetry.exporter.otlp.proto.common._log_encoder import encode_logs
from opentelemetry.sdk._logs import ReadableLogRecord
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.util.instrumentation import InstrumentationScope

from tests.integration.conftest import Api, World
from tests.integration.helpers import log, send

pytestmark = pytest.mark.integration


async def test_a1_a_line_sent_over_the_api_is_searchable_when_the_request_returns(
    api: Api, world: World
) -> None:
    started = time.perf_counter()
    resp = await api.client.post(
        "/api/v1/logs",
        json=log("checkout completed for cart 991", service="checkout"),
        headers=world.headers,
    )
    assert resp.status_code == 202, resp.text
    event_id = resp.json()["event_ids"][0]
    page = await api.ok("GET", "/api/v1/logs", params={**world.q, "q": "cart 991"})
    elapsed = time.perf_counter() - started
    assert [i["event_id"] for i in page["items"]] == [event_id]
    assert page["items"][0]["service"] == "checkout"
    assert page["items"][0]["source"] == "api"
    assert elapsed < 5, f"ingest to searchable took {elapsed:.2f}s"


async def test_batch_ingestion_applies_defaults_and_reports_rejections(
    api: Api, world: World
) -> None:
    now = datetime.now(UTC)
    result = await send(
        api.client,
        world.key,
        [
            {"message": "worker booted", "level": "INFO"},
            {
                "message": "slow query 1200ms",
                "level": "warning",
                "timestamp": int(now.timestamp() * 1000),
            },
            {"message": "too old", "timestamp": (now - timedelta(days=90)).isoformat()},
            {"message": "future", "timestamp": (now + timedelta(hours=2)).isoformat()},
            {"message": "bad ts", "timestamp": "yesterday"},
        ],
        defaults={"service": "billing-worker", "environment": "staging", "host": "node-3"},
    )
    assert result["accepted"] == 2
    assert sorted(r["index"] for r in result["rejected"]) == [2, 3, 4]
    page = await api.ok("GET", "/api/v1/logs", params={**world.q, "service": "billing-worker"})
    levels = sorted(i["level"] for i in page["items"])
    assert levels == ["info", "warn"]
    assert {i["environment"] for i in page["items"]} == {"staging"}
    assert {i["host"] for i in page["items"]} == {"node-3"}


async def test_batch_size_limit_and_auth_errors(api: Api, world: World) -> None:
    too_many = [{"message": f"line {i}"} for i in range(1001)]
    resp = await api.client.post(
        "/api/v1/logs/batch", json={"logs": too_many}, headers=world.headers
    )
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "payload_too_large"
    resp = await api.client.post(
        "/api/v1/logs", json={"message": "x"}, headers={"authorization": ""}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "api_key_required"
    resp = await api.client.post(
        "/api/v1/logs", json={"message": "x"}, headers={"authorization": "Bearer nope"}
    )
    assert resp.json()["error"]["code"] == "invalid_api_key"
    resp = await api.client.post(
        "/api/v1/logs", json={"message": "x"}, headers={"authorization": "", "x-api-key": world.key}
    )
    assert resp.status_code == 202


async def test_sdk_header_marks_the_source(api: Api, world: World) -> None:
    resp = await api.client.post(
        "/api/v1/logs/batch",
        json={"logs": [{"message": "from the sdk"}]},
        headers={**world.headers, "x-logmind-sdk": "python/0.1.0"},
    )
    assert resp.status_code == 202
    page = await api.ok("GET", "/api/v1/logs", params={**world.q, "q": "from the sdk"})
    assert page["items"][0]["source"] == "sdk"


def _otel_records() -> list[ReadableLogRecord]:
    resource = Resource.create(
        {
            "service.name": "ledger",
            "deployment.environment.name": "production",
            "host.name": "ip-10-0-1-7",
        }
    )
    scope = InstrumentationScope("ledger.app", "1.0.0")
    now_ns = time.time_ns()
    records = []
    for i, (sev, text, body_attrs) in enumerate(
        [
            (SeverityNumber.INFO, "ledger posted batch 77", {"batch.size": 40}),
            (
                SeverityNumber.ERROR,
                "posting failed",
                {
                    "exception.type": "LedgerLockTimeout",
                    "exception.message": "lock wait timeout exceeded",
                    "exception.stacktrace": 'Traceback (most recent call last):\n  File "/srv/ledger/post.py", line 12, in post\n    db.lock()\nLedgerLockTimeout: lock wait timeout exceeded',
                    "request_id": "req-ledger-1",
                },
            ),
        ]
    ):
        record = LogRecord(
            timestamp=now_ns + i,
            observed_timestamp=now_ns + i,
            trace_id=0x4BF92F3577B34DA6A3CE929D0E0E4736,
            span_id=0x00F067AA0BA902B7,
            severity_text=sev.name,
            severity_number=sev,
            body=text,
            attributes=cast("dict[str, Any]", body_attrs),
        )
        records.append(ReadableLogRecord(record, resource=resource, instrumentation_scope=scope))
    return records


async def test_a6_otlp_protobuf_from_the_official_encoder(api: Api, world: World) -> None:
    """The exact bytes an OpenTelemetry SDK's OTLPLogExporter sends."""
    body = encode_logs(_otel_records()).SerializeToString()
    resp = await api.client.post(
        "/v1/logs",
        content=gzip.compress(body),
        headers={
            **world.headers,
            "content-type": "application/x-protobuf",
            "content-encoding": "gzip",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/x-protobuf"
    page = await api.ok("GET", "/api/v1/logs", params={**world.q, "service": "ledger"})
    items = {i["message"]: i for i in page["items"]}
    assert set(items) == {"ledger posted batch 77", "posting failed"}
    err = items["posting failed"]
    assert err["level"] == "error"
    assert err["exception_type"] == "LedgerLockTimeout"
    assert err["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert err["span_id"] == "00f067aa0ba902b7"
    assert err["request_id"] == "req-ledger-1"
    assert err["host"] == "ip-10-0-1-7"
    assert err["source"] == "otlp"
    assert err["error_group_id"] is not None
    assert items["ledger posted batch 77"]["attributes"]["batch.size"] == 40


async def test_a6_otlp_json_and_partial_success(api: Api, world: World) -> None:
    now_ns = str(time.time_ns())
    doc = {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "gateway"}},
                        {"key": "deployment.environment", "value": {"stringValue": "staging"}},
                    ]
                },
                "scopeLogs": [
                    {
                        "logRecords": [
                            {
                                "timeUnixNano": now_ns,
                                "severityNumber": 13,
                                "severityText": "WARN",
                                "body": {"stringValue": "upstream latency 900ms"},
                                "attributes": [
                                    {"key": "http.route", "value": {"stringValue": "/cart"}},
                                    {"key": "retries", "value": {"intValue": "2"}},
                                ],
                                "traceId": "5B8EFFF798038103D269B633813FC60C",
                                "spanId": "EEE19B7EC3C1B174",
                            },
                            {"timeUnixNano": now_ns, "severityNumber": 9},
                            {
                                "timeUnixNano": now_ns,
                                "body": {
                                    "kvlistValue": {
                                        "values": [{"key": "k", "value": {"boolValue": True}}]
                                    }
                                },
                            },
                        ]
                    }
                ],
            }
        ]
    }
    resp = await api.client.post(
        "/api/v1/otlp/v1/logs",
        content=orjson.dumps(doc),
        headers={**world.headers, "content-type": "application/json"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["partialSuccess"]["rejectedLogRecords"] == "1"
    page = await api.ok("GET", "/api/v1/logs", params={**world.q, "service": "gateway"})
    msgs = {i["message"]: i for i in page["items"]}
    warn = msgs["upstream latency 900ms"]
    assert warn["level"] == "warn"
    assert warn["environment"] == "staging"
    assert warn["trace_id"] == "5b8efff798038103d269b633813fc60c"
    assert warn["attributes"]["retries"] == 2
    assert '{"k":true}' in msgs


async def test_otlp_rejects_garbage(api: Api, world: World) -> None:
    resp = await api.client.post(
        "/v1/logs",
        content=b"\xff\xfenot protobuf",
        headers={**world.headers, "content-type": "application/x-protobuf"},
    )
    assert resp.status_code == 400
    resp = await api.client.post(
        "/v1/logs",
        content=b"{not json",
        headers={**world.headers, "content-type": "application/json"},
    )
    assert resp.status_code == 400
    resp = await api.client.post(
        "/v1/logs",
        content=b"x",
        headers={**world.headers, "content-encoding": "br"},
    )
    assert resp.json()["error"]["code"] == "bad_encoding"


async def test_revoked_and_archived_keys_stop_ingestion(api: Api, world: World) -> None:
    await api.ok("DELETE", f"/api/v1/keys/{world.key_id}")
    resp = await api.client.post("/api/v1/logs", json={"message": "x"}, headers=world.headers)
    assert resp.status_code == 401
    key = await api.ok("POST", "/api/v1/keys", {"project_id": world.project_id, "name": "k2"})
    await api.ok("PATCH", f"/api/v1/projects/{world.project_id}", {"archived": True})
    resp = await api.client.post(
        "/api/v1/logs", json={"message": "x"}, headers={"authorization": f"Bearer {key['key']}"}
    )
    assert resp.json()["error"]["code"] == "project_archived"


async def test_services_and_environments_are_registered(api: Api, world: World) -> None:
    await send(
        api.client,
        world.key,
        [
            log("a", service="search", environment="production"),
            log("b", service="auth", environment="staging"),
        ],
    )
    envs = await api.ok("GET", "/api/v1/environments", params=world.q)
    assert sorted(e["name"] for e in envs) == ["production", "staging"]
    services = await api.ok("GET", "/api/v1/services", params=world.q)
    assert sorted(s["name"] for s in services["services"]) == ["auth", "search"]
