"""The Log Explorer (search, filters, pagination, histogram, facets, context) and Error
Intelligence (A2), all with no AI provider configured (A5)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from tests.integration.conftest import Api, World
from tests.integration.helpers import JS_TYPEERROR, log, send, timeout_error

pytestmark = pytest.mark.integration


async def test_search_filters_and_keyset_pagination(api: Api, world: World) -> None:
    now = datetime.now(UTC)
    lines = [
        log(
            f"request {i} served",
            service=("api", "worker")[i % 2],
            ts=now - timedelta(seconds=i),
            level=("info", "warn", "error")[i % 3],
        )
        for i in range(60)
    ]
    lines.append(log("Payment DECLINED for card", service="api", ts=now, level="warn"))
    await send(api.client, world.key, lines)
    page = await api.ok("GET", "/api/v1/logs", params={**world.q, "q": "payment declined"})
    assert [i["message"] for i in page["items"]] == ["Payment DECLINED for card"]
    page = await api.ok(
        "GET", "/api/v1/logs", params={**world.q, "service": "worker", "level": ["error", "warn"]}
    )
    assert page["items"] and all(
        i["service"] == "worker" and i["level"] in ("warn", "error") for i in page["items"]
    )
    seen: list[str] = []
    cursor = None
    while True:
        params = {**world.q, "limit": 25}
        if cursor:
            params["cursor"] = cursor
        page = await api.ok("GET", "/api/v1/logs", params=params)
        seen += [i["event_id"] for i in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(seen) == 61 and len(set(seen)) == 61
    page = await api.ok("GET", "/api/v1/logs", params={**world.q, "limit": 5})
    times = [i["timestamp"] for i in page["items"]]
    assert times == sorted(times, reverse=True)
    resp = await api.client.get("/api/v1/logs", params={**world.q, "cursor": "!!bad"})
    assert resp.json()["error"]["code"] == "bad_cursor"
    resp = await api.client.get(
        "/api/v1/logs",
        params={**world.q, "start": now.isoformat(), "end": (now - timedelta(hours=1)).isoformat()},
    )
    assert resp.json()["error"]["code"] == "bad_window"


async def test_histogram_facets_and_time_window(api: Api, world: World) -> None:
    now = datetime.now(UTC)
    await send(
        api.client,
        world.key,
        [
            log("old", ts=now - timedelta(hours=3)),
            log("new e", level="error", ts=now - timedelta(minutes=5)),
            log("new i", ts=now - timedelta(minutes=4)),
        ],
    )
    hist = await api.ok("GET", "/api/v1/logs/histogram", params=world.q)
    assert hist["total"] == 2
    assert sum(b["error"] for b in hist["buckets"]) == 1
    hist = await api.ok(
        "GET",
        "/api/v1/logs/histogram",
        params={**world.q, "start": (now - timedelta(hours=4)).isoformat(), "q": "new"},
    )
    assert hist["total"] == 2
    facets = await api.ok("GET", "/api/v1/logs/facets", params=world.q)
    assert {f["value"]: f["count"] for f in facets["levels"]} == {"error": 1, "info": 1}


async def test_get_line_context_and_trace(api: Api, world: World) -> None:
    now = datetime.now(UTC)
    trace = uuid.uuid4().hex
    result = await send(
        api.client,
        world.key,
        [
            log("before 1", ts=now - timedelta(seconds=30)),
            log(
                "gateway received order",
                service="gateway",
                ts=now - timedelta(seconds=12),
                trace_id=trace,
            ),
            log(
                "the line",
                ts=now - timedelta(seconds=10),
                trace_id=trace,
                attributes={"order": {"id": 7}},
            ),
            log("after 1", ts=now - timedelta(seconds=5)),
        ],
    )
    target = result["event_ids"][2]
    line = await api.ok("GET", f"/api/v1/logs/{target}", params=world.q)
    assert line["attributes"] == {"order": {"id": 7}}
    ctx = await api.ok("GET", f"/api/v1/logs/{target}/context", params=world.q)
    assert [i["message"] for i in ctx["before"]] == ["before 1"]
    assert [i["message"] for i in ctx["after"]] == ["after 1"]
    assert [i["message"] for i in ctx["same_trace"]] == ["gateway received order"]
    resp = await api.client.get(f"/api/v1/logs/{uuid.uuid4()}", params=world.q)
    assert resp.status_code == 404
    page = await api.ok("GET", "/api/v1/logs", params={**world.q, "trace_id": trace.upper()})
    assert len(page["items"]) == 2


async def test_a2_similar_stack_traces_group_with_a_stable_fingerprint(
    api: Api, world: World
) -> None:
    now = datetime.now(UTC)
    first = now - timedelta(minutes=30)
    # Different line numbers, order ids, timestamps and services: still one bug.
    await send(
        api.client, world.key, [timeout_error(first + timedelta(minutes=i), i) for i in range(3)]
    )
    await send(
        api.client, world.key, [timeout_error(now - timedelta(minutes=1), 9, service="checkout-v2")]
    )
    await send(
        api.client,
        world.key,
        [
            log(
                "search failed",
                level="error",
                service="search",
                ts=now - timedelta(minutes=2),
                exception={"type": "", "stacktrace": JS_TYPEERROR.format(line=31)},
            ),
            log(
                "search failed again",
                level="error",
                service="search",
                ts=now - timedelta(minutes=1),
                exception={"type": "", "stacktrace": JS_TYPEERROR.format(line=77)},
            ),
            log("disk usage at 91%", level="error", service="search", ts=now),
            log("disk usage at 93%", level="error", service="search", ts=now),
        ],
    )
    groups = await api.ok("GET", "/api/v1/errors", params={**world.q, "sort": "occurrences"})
    by_title = {g["title"]: g for g in groups["items"]}
    assert groups["total"] == 3, list(by_title)
    timeout = next(g for g in groups["items"] if g["exception_type"] == "PaymentGatewayTimeout")
    assert timeout["occurrences"] == 4
    assert sorted(timeout["services"]) == ["checkout", "checkout-v2"]
    assert timeout["culprit"] == "charge (payments.py)"
    assert abs(datetime.fromisoformat(timeout["first_seen"]) - first) < timedelta(seconds=1)
    assert abs(
        datetime.fromisoformat(timeout["last_seen"]) - (now - timedelta(minutes=1))
    ) < timedelta(seconds=1)
    js = next(g for g in groups["items"] if g["exception_type"] == "TypeError")
    assert js["occurrences"] == 2 and js["culprit"] == "renderResults (render.js)"
    disk = next(
        g for g in groups["items"] if g["title"].startswith("error|") or "disk usage" in g["title"]
    )
    assert disk["occurrences"] == 2
    fingerprint = timeout["fingerprint"]
    # The same bug next week gets the same fingerprint, so it lands in the same group.
    await send(api.client, world.key, [timeout_error(now, 42)])
    again = await api.ok("GET", f"/api/v1/errors/{timeout['id']}", params=world.q)
    assert again["fingerprint"] == fingerprint and again["occurrences"] == 5
    assert sum(p["count"] for p in again["trend"]) == 5
    lines = await api.ok("GET", "/api/v1/logs", params={**world.q, "error_group_id": timeout["id"]})
    assert len(lines["items"]) == 5
    assert all(i["error_group_id"] == timeout["id"] for i in lines["items"])


async def test_resolve_ignore_and_regression(api: Api, world: World) -> None:
    now = datetime.now(UTC)
    await send(api.client, world.key, [timeout_error(now - timedelta(minutes=5), 1)])
    group = (await api.ok("GET", "/api/v1/errors", params=world.q))["items"][0]
    resolved = await api.ok(
        "PATCH", f"/api/v1/errors/{group['id']}", {"status": "resolved"}, params=world.q
    )
    assert resolved["status"] == "resolved" and resolved["resolved_at"]
    listed = await api.ok("GET", "/api/v1/errors", params={**world.q, "status": "open"})
    assert listed["total"] == 0
    await send(api.client, world.key, [timeout_error(datetime.now(UTC), 2)])
    back = await api.ok("GET", f"/api/v1/errors/{group['id']}", params=world.q)
    assert back["status"] == "open" and back["regressed_at"] is not None
    audit = await api.ok("GET", "/api/v1/audit-log", params={"action": "error_group"})
    assert [e["action"] for e in audit["items"]] == ["error_group.resolved"]


async def test_error_filters(api: Api, world: World) -> None:
    now = datetime.now(UTC)
    await send(
        api.client,
        world.key,
        [
            timeout_error(now, 1),
            log("x", level="error", service="auth", environment="staging", ts=now),
        ],
    )
    assert (await api.ok("GET", "/api/v1/errors", params={**world.q, "service": "auth"}))[
        "total"
    ] == 1
    assert (await api.ok("GET", "/api/v1/errors", params={**world.q, "environment": "staging"}))[
        "total"
    ] == 1
    assert (await api.ok("GET", "/api/v1/errors", params={**world.q, "q": "gateway"}))["total"] == 1
    assert (await api.ok("GET", "/api/v1/errors", params={**world.q, "since_hours": 1}))[
        "total"
    ] == 2
    resp = await api.client.get(f"/api/v1/errors/{uuid.uuid4()}", params=world.q)
    assert resp.status_code == 404
