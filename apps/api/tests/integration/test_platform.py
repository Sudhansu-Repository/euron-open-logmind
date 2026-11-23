"""Auth, organisations, projects and keys, the audit log, health probes, service health
and the overview, the worker's queue and retention, and the live log stream."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from httpx_ws import AsyncWebSocketSession, WebSocketDisconnect, aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport

from logmind.investigations import service as investigations
from logmind.worker import apply_retention, run_one_job
from tests.integration.conftest import OWNER, Api, World, asgi_client
from tests.integration.helpers import incident, log, send, timeout_error

pytestmark = pytest.mark.integration


async def test_health_probes_and_metrics(api: Api) -> None:
    assert (await api.ok("GET", "/healthz")) == {"status": "ok"}
    ready = await api.ok("GET", "/readyz")
    assert ready == {"status": "ok", "postgres": True, "redis": True, "clickhouse": True}
    resp = await api.client.get("/metrics")
    assert resp.status_code == 200 and "logmind_ingested_events_total" in resp.text


async def test_signup_login_users_and_sessions(api: Api) -> None:
    async with asgi_client(api.app) as anon:
        r = await anon.post("/api/v1/auth/signup", json={**OWNER, "org_name": "Dup"})
        assert r.json()["error"]["code"] == "email_taken"
        r = await anon.post(
            "/api/v1/auth/signup",
            json={**OWNER, "email": "w@lumen.test", "password": "weakpassword"},
        )
        assert r.json()["error"]["code"] == "weak_password"
        r = await anon.post(
            "/api/v1/auth/login", json={"email": OWNER["email"], "password": "wrong-Pass-1"}
        )
        assert r.status_code == 401
        r = await anon.get("/api/v1/auth/me")
        assert r.json()["error"]["code"] == "not_signed_in"
        r = await anon.get("/api/v1/auth/me", headers={"authorization": "Bearer junk"})
        assert r.json()["error"]["code"] == "session_expired"
    me = await api.ok("GET", "/api/v1/auth/me")
    assert me["role"] == "owner"
    user = await api.ok(
        "POST",
        "/api/v1/users",
        {"email": "sre@lumen.test", "name": "SRE", "password": "Sre-Pass-1234", "role": "admin"},
        status=201,
    )
    users = await api.ok("GET", "/api/v1/users")
    assert {u["email"] for u in users} == {OWNER["email"], "sre@lumen.test"}
    async with asgi_client(api.app) as sre:
        token = (
            await sre.post(
                "/api/v1/auth/login", json={"email": "sre@lumen.test", "password": "Sre-Pass-1234"}
            )
        ).json()["session_token"]
        sre.headers["authorization"] = f"Bearer {token}"
        assert (await sre.get("/api/v1/auth/me")).status_code == 200
        await api.ok("PATCH", f"/api/v1/users/{user['id']}", {"disabled": True})
        assert (await sre.get("/api/v1/auth/me")).status_code == 401
    org = await api.ok("PATCH", "/api/v1/org", {"name": "Lumen Retail Group"})
    assert org["name"] == "Lumen Retail Group"
    assert (await api.ok("GET", "/api/v1/org"))["slug"] == "lumen-retail"


async def test_login_is_rate_limited(api: Api) -> None:
    api.container.settings.login_attempts_per_minute = 3
    async with asgi_client(api.app) as anon:
        codes = [
            (
                await anon.post(
                    "/api/v1/auth/login", json={"email": "x@lumen.test", "password": "Nope-Pass-1"}
                )
            ).status_code
            for _ in range(8)
        ]
    # A fixed window may roll over once during the loop, so count rather than index.
    assert codes[:3] == [401, 401, 401] and codes.count(429) >= 3


async def test_projects_keys_and_audit_log(api: Api, world: World) -> None:
    second = await api.ok("POST", "/api/v1/projects", {"name": "Storefront", "retention_days": 30})
    assert second["slug"] == "storefront-2"
    assert second["redaction_enabled"] is True and "credential" in second["redaction_categories"]
    keys = await api.ok("GET", "/api/v1/keys", params={"project_id": world.project_id})
    assert keys[0]["display"].startswith("lmk_") and "key" not in keys[0]
    resp = await api.client.post(
        "/api/v1/keys", json={"project_id": str(uuid.uuid4()), "name": "x"}
    )
    assert resp.status_code == 404
    await api.ok("PATCH", f"/api/v1/projects/{second['id']}", {"archived": True})
    assert len(await api.ok("GET", "/api/v1/projects")) == 1
    assert len(await api.ok("GET", "/api/v1/projects", params={"include_archived": True})) == 2
    audit = await api.ok("GET", "/api/v1/audit-log", params={"limit": 3})
    assert audit["items"][0]["action"] == "project.updated" and audit["next_cursor"]
    nxt = await api.ok("GET", "/api/v1/audit-log", params={"cursor": audit["next_cursor"]})
    actions = [e["action"] for e in nxt["items"]]
    assert "org.created" in actions and "user.created" in actions


async def test_services_health_and_overview(api: Api, world: World) -> None:
    now = datetime.now(UTC)
    lines = [log("tick", service="inventory", ts=now - timedelta(minutes=m)) for m in range(1, 120)]
    lines += [timeout_error(now - timedelta(minutes=2, seconds=s), s) for s in range(12)]
    lines += [log("ok", service="checkout", ts=now - timedelta(minutes=3))] * 20
    await send(api.client, world.key, lines)
    services = {
        s["name"]: s for s in (await api.ok("GET", "/api/v1/services", params=world.q))["services"]
    }
    assert services["inventory"]["status"] == "healthy"
    assert services["inventory"]["availability"] == 1.0
    checkout = services["checkout"]
    assert checkout["status"] == "critical" and checkout["errors"] == 12
    assert checkout["open_error_groups"] == 1
    one = await api.ok("GET", "/api/v1/services/checkout", params=world.q)
    assert one["total"] == 32
    assert (await api.client.get("/api/v1/services/nope", params=world.q)).status_code == 404
    overview = await api.ok("GET", "/api/v1/analytics/overview", params=world.q)
    assert overview["lines"] == 151 and overview["errors"] == 12
    assert overview["new_error_groups"] == 1 and overview["top_errors"][0]["occurrences"] == 12
    assert overview["histogram"]["total"] == 151
    assert {s["name"] for s in overview["services"]} == {"inventory", "checkout"}


async def test_worker_claims_each_job_once_and_reaps_dead_leases(
    api: Api,
    world: World,
    mock_provider: dict[str, Any],
) -> None:
    lines, _ = incident(datetime.now(UTC), noise=20)
    await send(api.client, world.key, lines)
    group = (await api.ok("GET", "/api/v1/errors", params=world.q))["items"][0]
    for _ in range(3):
        await api.ok(
            "POST",
            "/api/v1/ai/investigate",
            {"project_id": world.project_id, "error_group_id": group["id"]},
            status=202,
        )
    container = api.container

    async def claim(worker: str) -> tuple[str, uuid.UUID] | None:
        async with container.db.sessionmaker() as session:
            return await investigations.claim_next(session, worker, 300)

    claimed = await asyncio.gather(*(claim(f"w{i}") for i in range(5)))
    got = [c[1] for c in claimed if c is not None]
    assert len(got) == 3 and len(set(got)) == 3
    # Their workers "die": leases expire, the reaper puts them back on the queue.
    async with container.db.sessionmaker() as session:
        from sqlalchemy import update

        from logmind.investigations.models import Investigation

        await session.execute(
            update(Investigation).values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()
        assert await investigations.reap_expired(session) == 3
    ran = 0
    while await run_one_job(container, "survivor"):
        ran += 1
    assert ran == 3
    listed = await api.ok("GET", "/api/v1/ai/investigations", params=world.q)
    assert {i["status"] for i in listed} == {"completed"}


async def test_retention_deletes_only_old_lines_of_each_project(api: Api, world: World) -> None:
    await api.ok("PATCH", f"/api/v1/projects/{world.project_id}", {"retention_days": 1})
    now = datetime.now(UTC)
    await send(
        api.client, world.key, [log("ancient", ts=now - timedelta(days=3)), log("fresh", ts=now)]
    )
    assert await apply_retention(api.container) == 1
    ch = api.container.clickhouse
    for _ in range(30):
        rows = await ch.query(
            "SELECT message FROM log_events WHERE project_id = {p:UUID}", {"p": world.project_id}
        )
        if len(rows) == 1:
            break
        await asyncio.sleep(0.5)
    assert [r["message"] for r in rows] == ["fresh"]


async def test_live_stream_delivers_new_lines_with_filters(api: Api, world: World) -> None:
    token = api.client.headers["authorization"].removeprefix("Bearer ")
    transport = ASGIWebSocketTransport(app=api.app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://testserver") as client,
        aconnect_ws(
            f"/api/v1/logs/live?token={token}&project_id={world.project_id}&level=error",
            client,
            session_class=AsyncWebSocketSession,
        ) as ws,
    ):
        ready = await ws.receive_json()
        assert ready["type"] == "ready"
        await send(api.client, world.key, [log("info line"), log("live boom", level="error")])
        event = await asyncio.wait_for(ws.receive_json(), timeout=10)
        assert event["type"] == "logs"
        assert [i["message"] for i in event["items"]] == ["live boom"]


@pytest.mark.parametrize(("query", "code"), [("token=junk", 4401), ("project_id=other", 4404)])
async def test_live_stream_refuses_bad_tokens_and_foreign_projects(
    api: Api, world: World, query: str, code: int
) -> None:
    token = api.client.headers["authorization"].removeprefix("Bearer ")
    if query == "project_id=other":
        query = f"token={token}&project_id={uuid.uuid4()}"
    else:
        query = f"{query}&project_id={world.project_id}"
    transport = ASGIWebSocketTransport(app=api.app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://testserver") as client,
        aconnect_ws(
            f"/api/v1/logs/live?{query}", client, session_class=AsyncWebSocketSession
        ) as ws,
    ):
        with pytest.raises(WebSocketDisconnect) as excinfo:
            await ws.receive()
        assert excinfo.value.code == code
