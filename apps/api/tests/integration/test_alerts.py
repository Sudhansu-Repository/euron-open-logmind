"""A9 (alert rules fire real notifications against live ingested data) and A10 (the
anomaly detector flags a genuine deviation from its own baseline)."""

from __future__ import annotations

import hashlib
import hmac
import os
import random
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from logmind.alerts.service import evaluate_due
from logmind.core import mail
from tests.integration.conftest import Api, World
from tests.integration.helpers import log, send, timeout_error

pytestmark = pytest.mark.integration


async def _rule(api: Api, world: World, **body: object) -> dict[str, Any]:
    out: dict[str, Any] = await api.ok(
        "POST", "/api/v1/alerts", {"project_id": world.project_id, **body}, status=201
    )
    return out


async def test_a9_threshold_rule_fires_email_webhook_and_slack_then_resolves(
    api: Api, world: World
) -> None:
    rule = await _rule(
        api,
        world,
        name="Checkout errors",
        metric="error_count",
        service="checkout",
        threshold=5,
        window_minutes=5,
        email_to=["oncall@lumen.test"],
        webhook_url=f"{api.mock_url}/hooks/a9",
        slack_url=f"{api.mock_url}/hooks/a9-slack",
    )
    assert rule["webhook_secret"].startswith("whsec_")
    assert rule["has_webhook"] and rule["has_slack"]
    container = api.container
    # Below the threshold: evaluated, nothing sent.
    await send(api.client, world.key, [timeout_error(datetime.now(UTC), i) for i in range(3)])
    assert await evaluate_due(container, force=True) == 1
    assert list(mail.OUTBOX) == []
    # Live data crosses it.
    await send(api.client, world.key, [timeout_error(datetime.now(UTC), i) for i in range(4)])
    await evaluate_due(container, force=True)
    history = await api.ok("GET", f"/api/v1/alerts/{rule['id']}/history")
    fired = history[0]
    assert fired["event"] == "fired" and fired["value"] == 7
    assert {d["channel"]: d["ok"] for d in fired["deliveries"]} == {
        "email": True,
        "webhook": True,
        "slack": True,
    }
    assert [m.to for m in mail.OUTBOX] == ["oncall@lumen.test"]
    assert "FIRING" in mail.OUTBOX[0].subject and "7 errors" in mail.OUTBOX[0].text
    hooks = await api.mock("/hooks/a9")
    assert len(hooks) == 1
    sig = hooks[0]["headers"]["x-logmind-signature"]
    t, v1 = (p.split("=", 1)[1] for p in sig.split(","))
    expected = hmac.new(
        rule["webhook_secret"].encode(), f"{t}.{hooks[0]['raw']}".encode(), hashlib.sha256
    ).hexdigest()
    assert hmac.compare_digest(v1, expected)
    assert hooks[0]["body"]["event"] == "alert.fired" and hooks[0]["body"]["value"] == 7
    slack = await api.mock("/hooks/a9-slack")
    assert "Checkout errors" in slack[0]["body"]["text"]
    # Still breached inside the cooldown: no second notification.
    await evaluate_due(container, force=True)
    assert len(await api.mock("/hooks/a9")) == 1
    state = await api.ok("GET", f"/api/v1/alerts/{rule['id']}")
    assert state["state"] == "firing"
    # Recovery: shrink the window past the errors and the rule resolves.
    await api.ok("PATCH", f"/api/v1/alerts/{rule['id']}", {"threshold": 100})
    await evaluate_due(container, force=True)
    history = await api.ok("GET", f"/api/v1/alerts/{rule['id']}/history")
    assert [h["event"] for h in history] == ["resolved", "fired"]
    assert (await api.mock("/hooks/a9"))[-1]["body"]["event"] == "alert.resolved"


async def test_threshold_metrics(api: Api, world: World) -> None:
    now = datetime.now(UTC)
    await send(
        api.client,
        world.key,
        [log("ok", ts=now)] * 6
        + [log("payment declined", level="warn", ts=now)] * 2
        + [log("boom", level="error", ts=now)] * 2,
    )
    for metric, threshold, query in [
        ("log_count", 9, ""),
        ("error_rate", 19, ""),
        ("matching_count", 1, "declined"),
    ]:
        await _rule(
            api,
            world,
            name=metric,
            metric=metric,
            threshold=threshold,
            query=query,
            email_to=["a@lumen.test"],
        )
    await evaluate_due(api.container, force=True)
    rules = {r["name"]: r for r in await api.ok("GET", "/api/v1/alerts", params=world.q)}
    assert rules["log_count"]["last_value"] == 10 and rules["log_count"]["state"] == "firing"
    assert rules["error_rate"]["last_value"] == 20.0 and rules["error_rate"]["state"] == "firing"
    assert rules["matching_count"]["last_value"] == 2
    recent = await api.ok("GET", "/api/v1/alerts/history", params=world.q)
    assert {h["rule_name"] for h in recent} == {"log_count", "error_rate", "matching_count"}


async def _backfill_baseline(api: Api, world: World, now: datetime, hours: int = 6) -> None:
    rng = random.Random(7)
    lines = []
    for m in range(hours * 60, 6, -1):
        ts = now - timedelta(minutes=m)
        for _ in range(rng.choice([0, 0, 1, 1, 2])):
            lines.append(log("cart sync failed: retrying", level="error", service="cart", ts=ts))
        lines.append(log("cart heartbeat", service="cart", ts=ts))
    for i in range(0, len(lines), 900):
        await send(api.client, world.key, lines[i : i + 900])


async def test_a10_anomaly_rule_flags_a_real_spike_against_its_own_baseline(
    api: Api, world: World
) -> None:
    now = datetime.now(UTC)
    await _backfill_baseline(api, world, now)
    rule = await _rule(
        api,
        world,
        name="Cart error spike",
        kind="anomaly",
        service="cart",
        baseline_hours=6,
        sensitivity=3,
        min_count=10,
        webhook_url=f"{api.mock_url}/hooks/a10",
    )
    # Normal behaviour: no anomaly.
    await send(
        api.client,
        world.key,
        [
            log(
                "cart sync failed: retrying",
                level="error",
                service="cart",
                ts=now - timedelta(minutes=2),
            )
        ]
        * 3,
    )
    await evaluate_due(api.container, force=True)
    assert (await api.ok("GET", f"/api/v1/alerts/{rule['id']}"))["state"] == "ok"
    # An injected spike: 60 errors in the last few minutes.
    await send(
        api.client,
        world.key,
        [
            log(
                "cart sync failed: upstream 503",
                level="error",
                service="cart",
                ts=datetime.now(UTC) - timedelta(seconds=s),
            )
            for s in range(60)
        ],
    )
    await evaluate_due(api.container, force=True)
    fired = (await api.ok("GET", f"/api/v1/alerts/{rule['id']}/history"))[0]
    assert fired["event"] == "fired"
    assert fired["value"] >= 60 and fired["expected"] < 10 and fired["zscore"] >= 3
    assert "baseline" in fired["message"]
    assert len(await api.mock("/hooks/a10")) == 1
    # The overview's detector scan finds the same spike.
    anomalies = await api.ok("GET", "/api/v1/analytics/anomalies", params=world.q)
    # Aligned five-minute buckets can split the spike in two; together they hold it all.
    cart = [a for a in anomalies if a["service"] == "cart"]
    assert cart and sum(a["value"] for a in cart) >= 60, anomalies


async def test_alert_validation_test_send_and_delete(api: Api, world: World) -> None:
    resp = await api.client.post(
        "/api/v1/alerts", json={"project_id": world.project_id, "name": "no target"}
    )
    assert resp.status_code == 422
    resp = await api.client.post(
        "/api/v1/alerts",
        json={
            "project_id": world.project_id,
            "name": "x",
            "email_to": ["a@b.co"],
            "webhook_url": "http://169.254.169.254/latest",
        },
    )
    assert resp.status_code == 422
    rule = await _rule(
        api,
        world,
        name="Test me",
        threshold=1000,
        email_to=["team@lumen.test"],
        slack_url=f"{api.mock_url}/hooks/t",
    )
    sent = await api.ok("POST", f"/api/v1/alerts/{rule['id']}/test")
    assert sent["event"] == "test" and all(d["ok"] for d in sent["deliveries"])
    assert "TEST" in mail.OUTBOX[-1].subject
    assert (await api.ok("GET", f"/api/v1/alerts/{rule['id']}"))["state"] == "ok"
    await api.ok("PATCH", f"/api/v1/alerts/{rule['id']}", {"slack_url": "", "enabled": False})
    updated = await api.ok("GET", f"/api/v1/alerts/{rule['id']}")
    assert updated["has_slack"] is False and updated["enabled"] is False
    await api.ok("DELETE", f"/api/v1/alerts/{rule['id']}", status=204)
    assert (await api.client.get(f"/api/v1/alerts/{rule['id']}")).status_code == 404


async def test_failed_delivery_is_recorded_and_does_not_stop_other_channels(
    api: Api, world: World
) -> None:
    await _rule(
        api,
        world,
        name="Broken hook",
        threshold=0,
        email_to=["a@lumen.test"],
        webhook_url="http://127.0.0.1:9/nothing-listens-here",
    )
    await send(api.client, world.key, [log("boom", level="error")])
    await evaluate_due(api.container, force=True)
    entry = (await api.ok("GET", "/api/v1/alerts/history", params=world.q))[0]
    outcomes = {d["channel"]: d for d in entry["deliveries"]}
    assert outcomes["email"]["ok"] is True
    assert outcomes["webhook"]["ok"] is False and "could not reach" in outcomes["webhook"]["error"]


@pytest.mark.skipif(
    not os.environ.get("TEST_MAILPIT_URL"), reason="needs Mailpit (make test-integration)"
)
async def test_a9_email_reaches_mailpit_over_smtp(api: Api, world: World) -> None:
    container = api.container
    container.settings.mail_backend = "smtp"
    container.settings.smtp_host = "localhost"
    container.settings.smtp_port = int(os.environ.get("TEST_SMTP_PORT", "6026"))
    mailpit = os.environ["TEST_MAILPIT_URL"]
    recipient = f"sre-{random.randint(1000, 9999)}@lumen.test"
    await _rule(api, world, name="SMTP rule", threshold=0, email_to=[recipient])
    await send(api.client, world.key, [log("boom", level="error")])
    await evaluate_due(container, force=True)
    async with httpx.AsyncClient() as c:
        found = (
            await c.get(f"{mailpit}/api/v1/search", params={"query": f"to:{recipient}"})
        ).json()
    assert found["messages_count"] == 1
    assert "SMTP rule" in found["messages"][0]["Subject"]
