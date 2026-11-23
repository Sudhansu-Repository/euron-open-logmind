"""Alert state decisions and the delivery channels, against in-process receivers."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import orjson

from logmind.alerts import channels
from logmind.alerts.evaluator import Measurement
from logmind.alerts.models import AlertRule
from logmind.alerts.service import _decide, rule_out
from logmind.core import mail
from logmind.core.config import Settings

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


def rule(**kw: Any) -> AlertRule:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "org_id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "name": "r",
        "kind": "threshold",
        "metric": "error_count",
        "query": "",
        "service": "",
        "environment": "",
        "threshold": 5.0,
        "window_minutes": 5,
        "sensitivity": 3.0,
        "min_count": 10,
        "baseline_hours": 24,
        "email_to": [],
        "cooldown_minutes": 30,
        "enabled": True,
        "state": "ok",
        "created_at": NOW,
    }
    base.update(kw)
    return AlertRule(**base)


def test_state_machine() -> None:
    breach, calm = Measurement(9, True), Measurement(1, False)
    assert _decide(rule(), breach, NOW) == "fired"
    firing = rule(state="firing", last_fired_at=NOW - timedelta(minutes=5))
    assert _decide(firing, breach, NOW) is None
    assert (
        _decide(rule(state="firing", last_fired_at=NOW - timedelta(minutes=31)), breach, NOW)
        == "fired"
    )
    assert _decide(firing, calm, NOW) == "resolved"
    assert _decide(rule(), calm, NOW) is None
    out = rule_out(rule(webhook_url_sealed=b"x"))
    assert out.has_webhook and not out.has_slack


NOTICE = channels.Notice(
    "alert.fired", "Checkout errors", "Storefront", "9 errors", "http://ui/alerts/1", {"value": 9}
)


async def test_webhook_signature_and_slack_payload() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204 if "hook" in str(request.url) else 500)

    settings = Settings(environment="test")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        ok = await channels.send_webhook(http, settings, "http://127.0.0.1/hook", "whsec_x", NOTICE)
        bad = await channels.send_slack(http, settings, "http://127.0.0.1/slack", NOTICE)
    assert ok["ok"] and ok["status"] == 204
    assert not bad["ok"] and "500" in bad["error"]
    req = seen[0]
    t, v1 = (p.split("=", 1)[1] for p in req.headers["x-logmind-signature"].split(","))
    expected = hmac.new(
        b"whsec_x", f"{t}.{req.content.decode()}".encode(), hashlib.sha256
    ).hexdigest()
    assert v1 == expected and req.headers["x-logmind-event"] == "alert.fired"
    assert orjson.loads(req.content)["value"] == 9
    slack = orjson.loads(seen[1].content)
    assert (
        "Checkout errors" in slack["text"]
        and slack["blocks"][1]["elements"][0]["url"] == "http://ui/alerts/1"
    )


async def test_unreachable_and_forbidden_receivers() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    settings = Settings(environment="test")
    async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as http:
        down = await channels.send_webhook(http, settings, "http://127.0.0.1/x", "s", NOTICE)
        meta = await channels.send_slack(http, settings, "http://metadata/x", NOTICE)
    assert not down["ok"] and "could not reach" in down["error"]
    assert not meta["ok"] and "forbidden" in meta["error"]


async def test_email_subjects() -> None:
    mail.OUTBOX.clear()
    settings = Settings(environment="test", mail_backend="log")
    for event, word in (
        ("alert.fired", "FIRING"),
        ("alert.resolved", "RESOLVED"),
        ("alert.test", "TEST"),
    ):
        n = channels.Notice(event, "R", "P", "s", "l", {})
        assert (await channels.send_email(settings, ["a@b.co"], n))["ok"]
        assert mail.OUTBOX[-1].subject == f"[LogMind] {word}: R (P)"
    broken = settings.model_copy(
        update={"mail_backend": "smtp", "smtp_host": "127.0.0.1", "smtp_port": 9}
    )
    assert not (await channels.send_email(broken, ["a@b.co"], NOTICE))["ok"]
