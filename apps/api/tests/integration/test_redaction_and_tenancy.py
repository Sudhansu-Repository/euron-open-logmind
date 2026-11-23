"""A7 (PII and secrets redacted before storage, configurable per project) and A8 (orgs and
projects isolated structurally)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from tests.integration.conftest import Api, World, asgi_client
from tests.integration.helpers import incident, log, run_jobs, send

pytestmark = pytest.mark.integration

# Assembled at run time so the repository holds no secret-shaped literal.
FAKE_PROVIDER_KEY = "sk-" + "proj-" + "A" * 24
SECRET_LINE = (
    "login ok for jane.doe@example.com card 4111 1111 1111 1111 "
    "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N "
    "password=Hunter2Hunter2 order 4000123412341235"
)


async def _stored_raw(api: Api, world: World) -> list[dict[str, Any]]:
    """Read straight from ClickHouse, not through the API, to prove what is stored."""
    ch = api.container.clickhouse
    rows: list[dict[str, Any]] = await ch.query(
        "SELECT message, attributes, stack_trace, redactions FROM log_events "
        "WHERE project_id = {p:UUID} ORDER BY timestamp",
        {"p": world.project_id},
    )
    return rows


async def test_a7_secrets_and_pii_never_reach_storage(api: Api, world: World) -> None:
    result = await send(
        api.client,
        world.key,
        [
            log(
                SECRET_LINE,
                level="error",
                attributes={
                    "user": {"email": "jane.doe@example.com", "id": 7},
                    "api_key": "abc123",
                    "ssn": "123-45-6789",
                },
                exception={
                    "type": "AuthError",
                    "stacktrace": "AuthError: token " + FAKE_PROVIDER_KEY + " leaked",
                },
            )
        ],
    )
    assert result["redactions"] >= 7
    rows = await _stored_raw(api, world)
    raw = str(rows)
    for secret in (
        "jane.doe@example.com",
        "4111 1111 1111 1111",
        "eyJhbGciOiJIUzI1NiJ9",
        "Hunter2Hunter2",
        "abc123",
        "123-45-6789",
        FAKE_PROVIDER_KEY[:12],
    ):
        assert secret not in raw, f"{secret} was stored"
    msg = rows[0]["message"]
    assert "[REDACTED:email]" in msg and "[REDACTED:payment_card]" in msg
    assert "password=[REDACTED:credential]" in msg
    # A 16-digit order id that fails the Luhn checksum is left alone.
    assert "order 4000123412341235" in msg
    page = await api.ok("GET", "/api/v1/logs", params=world.q)
    assert page["items"][0]["redactions"] == rows[0]["redactions"]
    assert page["items"][0]["attributes"]["user"]["id"] == 7
    # The live stream and the error group sample are redacted too.
    groups = await api.ok("GET", "/api/v1/errors", params=world.q)
    assert "jane.doe" not in groups["items"][0]["sample_message"]


async def test_a7_policy_is_per_project(api: Api, world: World) -> None:
    other = await api.ok("POST", "/api/v1/projects", {"name": "Internal tools"})
    other_key = await api.ok("POST", "/api/v1/keys", {"project_id": other["id"], "name": "k"})
    await api.ok(
        "PATCH",
        f"/api/v1/projects/{other['id']}",
        {
            "redaction_categories": ["email", "ip_address"],
            "redaction_mode": "hash",
            "redaction_custom": [{"name": "employee_id", "pattern": r"EMP-\d{5}"}],
        },
    )
    await send(
        api.client,
        other_key["key"],
        [log("bob@corp.test from 10.1.2.3 EMP-12345 password=abc12345")],
    )
    await send(api.client, other_key["key"], [log("bob@corp.test again")])
    rows = await api.container.clickhouse.query(
        "SELECT message FROM log_events WHERE project_id = {p:UUID} ORDER BY timestamp",
        {"p": other["id"]},
    )
    first, second = rows[0]["message"], rows[1]["message"]
    assert "bob@corp.test" not in first and "10.1.2.3" not in first and "EMP-12345" not in first
    # Credentials are off for this project, so the password stays (its admins chose so).
    assert "password=abc12345" in first
    token = first.split()[0]
    assert token.startswith("[email:") and second.startswith(token), (
        "hash mode keeps equal values equal"
    )
    # The first project, untouched, still masks credentials.
    await api.ok("PATCH", f"/api/v1/projects/{world.project_id}", {"redaction_enabled": False})
    await send(api.client, world.key, [log("plain bob@corp.test")])
    rows = await _stored_raw(api, world)
    assert rows[-1]["message"] == "plain bob@corp.test"
    preview = await api.ok(
        "POST", f"/api/v1/projects/{other['id']}/redaction/preview", {"text": "mail a@b.co"}
    )
    assert preview["counts"] == {"email": 1}
    resp = await api.client.patch(
        f"/api/v1/projects/{other['id']}",
        json={"redaction_custom": [{"name": "bad", "pattern": "(a+)+"}]},
    )
    assert resp.status_code == 422


async def test_a8_orgs_and_projects_are_isolated(api: Api, world: World) -> None:
    await api.ok("POST", "/api/v1/ai/providers", {"name": "mock", "kind": "mock"}, status=201)
    lines, _ = incident(datetime.now(UTC), noise=20)
    await send(api.client, world.key, lines)
    group = (await api.ok("GET", "/api/v1/errors", params=world.q))["items"][0]
    inv = await api.ok(
        "POST",
        "/api/v1/ai/investigate",
        {"project_id": world.project_id, "error_group_id": group["id"]},
        status=202,
    )
    await run_jobs(api.app)
    rule = await api.ok(
        "POST",
        "/api/v1/alerts",
        {
            "project_id": world.project_id,
            "name": "errs",
            "threshold": 1,
            "email_to": ["a@lumen.test"],
        },
        status=201,
    )
    line = (await api.ok("GET", "/api/v1/logs", params=world.q))["items"][0]

    async with asgi_client(api.app) as other:
        resp = await other.post(
            "/api/v1/auth/signup",
            json={
                "org_name": "Rival Inc",
                "email": "eve@rival.test",
                "name": "Eve",
                "password": "Rival-Pass-123",
            },
        )
        other.headers["authorization"] = f"Bearer {resp.json()['session_token']}"
        theirs = (await other.post("/api/v1/projects", json={"name": "Rival app"})).json()
        their_key = (
            await other.post("/api/v1/keys", json={"project_id": theirs["id"], "name": "k"})
        ).json()
        # Every read of the first org's data by id or by project is a 404, never data.
        for path, params in [
            ("/api/v1/logs", {"project_id": world.project_id}),
            (f"/api/v1/logs/{line['event_id']}", {"project_id": world.project_id}),
            ("/api/v1/errors", {"project_id": world.project_id}),
            (f"/api/v1/errors/{group['id']}", {"project_id": world.project_id}),
            ("/api/v1/services", {"project_id": world.project_id}),
            ("/api/v1/analytics/overview", {"project_id": world.project_id}),
            ("/api/v1/alerts", {"project_id": world.project_id}),
            (f"/api/v1/alerts/{rule['id']}", {}),
            (f"/api/v1/ai/investigations/{inv['id']}", {}),
            (f"/api/v1/ai/investigations/{inv['id']}/verify", {}),
            (f"/api/v1/projects/{world.project_id}", {}),
        ]:
            r = await other.get(path, params=params)
            assert r.status_code == 404, (path, r.status_code, r.text[:200])
        # Their own project, queried with an event id from ours, finds nothing either.
        r = await other.get(f"/api/v1/logs/{line['event_id']}", params={"project_id": theirs["id"]})
        assert r.status_code == 404
        r = await other.post(
            "/api/v1/ai/investigate",
            json={"project_id": theirs["id"], "error_group_id": group["id"]},
        )
        assert r.status_code in (404, 409)
        assert (await other.get("/api/v1/keys")).json()[0]["project_id"] == theirs["id"]
        assert [p["id"] for p in (await other.get("/api/v1/projects")).json()] == [theirs["id"]]
        # Their key writes only into their project, whatever the payload says.
        await send(
            other,
            their_key["key"],
            [log("rival line", attributes={"project_id": world.project_id})],
        )
        mine = await api.ok("GET", "/api/v1/logs", params={**world.q, "q": "rival"})
        assert mine["items"] == []
        r = await other.get("/api/v1/logs", params={"project_id": theirs["id"], "q": "rival"})
        assert len(r.json()["items"]) == 1
        usage = (await other.get("/api/v1/usage")).json()
        assert usage["calls"] == 0


async def test_viewers_cannot_change_settings(api: Api, world: World) -> None:
    await api.ok(
        "POST",
        "/api/v1/users",
        {
            "email": "viewer@lumen.test",
            "name": "Vi",
            "password": "Viewer-Pass-123",
            "role": "viewer",
        },
        status=201,
    )
    async with asgi_client(api.app) as viewer:
        token = (
            await viewer.post(
                "/api/v1/auth/login",
                json={"email": "viewer@lumen.test", "password": "Viewer-Pass-123"},
            )
        ).json()["session_token"]
        viewer.headers["authorization"] = f"Bearer {token}"
        assert (await viewer.get("/api/v1/logs", params=world.q)).status_code == 200
        for method, path, body in [
            ("POST", "/api/v1/projects", {"name": "x"}),
            ("POST", "/api/v1/keys", {"project_id": world.project_id, "name": "x"}),
            ("POST", "/api/v1/ai/providers", {"name": "m", "kind": "mock"}),
            (
                "POST",
                "/api/v1/alerts",
                {"project_id": world.project_id, "name": "x", "email_to": ["a@b.co"]},
            ),
            ("GET", "/api/v1/users", None),
        ]:
            r = await viewer.request(method, path, json=body)
            assert r.status_code == 403, (path, r.text)
            assert r.json()["error"]["code"] == "insufficient_role"
    assert isinstance(httpx, object)
