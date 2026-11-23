"""Notification delivery: email, signed webhook, Slack. One attempt per channel per
event, each outcome recorded on the history row; a failing channel never stops the
others.

Webhook signature (the program's scheme, as in AgentGuard and AgentDebugger)::

    X-LogMind-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256 of "<t>.<body>">
    X-LogMind-Event: alert.fired | alert.resolved | alert.test
    X-LogMind-Delivery: <uuid>, for the receiver to drop repeats
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
import orjson

from logmind.core import mail
from logmind.core.config import Settings
from logmind.core.net import resolves_safely
from logmind.core.security import hmac_hex


@dataclass(frozen=True, slots=True)
class Notice:
    event: str
    rule_name: str
    project_name: str
    summary: str
    link: str
    payload: dict[str, Any]


def sign(secret: str, timestamp: int, body: bytes) -> str:
    return f"t={timestamp},v1={hmac_hex(secret, f'{timestamp}.{body.decode()}')}"


def _outcome(channel: str, ok: bool, status: int | None = None, error: str = "") -> dict[str, Any]:
    return {"channel": channel, "ok": ok, "status": status, "error": error[:300]}


async def send_email(settings: Settings, to: list[str], notice: Notice) -> dict[str, Any]:
    word = {"alert.fired": "FIRING", "alert.resolved": "RESOLVED"}.get(notice.event, "TEST")
    subject = f"[LogMind] {word}: {notice.rule_name} ({notice.project_name})"
    text = f"{notice.summary}\n\nOpen in LogMind: {notice.link}\n"
    html = (
        f"<p><strong>{word}</strong>: {notice.rule_name} ({notice.project_name})</p>"
        f'<p>{notice.summary}</p><p><a href="{notice.link}">Open in LogMind</a></p>'
    )
    try:
        for address in to:
            await mail.send(settings, address, subject, text, html)
    except mail.MailError as exc:
        return _outcome("email", False, error=str(exc))
    return _outcome("email", True)


async def _post(
    http: httpx.AsyncClient, url: str, body: bytes, headers: dict[str, str], wait_s: float
) -> tuple[bool, int | None, str]:
    if not await resolves_safely(url, allow_private=True):
        return False, None, "the URL resolves to a forbidden address"
    try:
        resp = await http.post(url, content=body, headers=headers, timeout=wait_s)
    except httpx.HTTPError as exc:
        return False, None, f"could not reach the receiver: {type(exc).__name__}"
    ok = 200 <= resp.status_code < 300
    return ok, resp.status_code, "" if ok else f"the receiver answered {resp.status_code}"


async def send_webhook(
    http: httpx.AsyncClient, settings: Settings, url: str, secret: str, notice: Notice
) -> dict[str, Any]:
    body = orjson.dumps({"event": notice.event, **notice.payload})
    headers = {
        "content-type": "application/json",
        "x-logmind-event": notice.event,
        "x-logmind-delivery": str(uuid.uuid4()),
        "x-logmind-signature": sign(secret, int(time.time()), body),
    }
    ok, status, error = await _post(http, url, body, headers, settings.webhook_timeout_s)
    return _outcome("webhook", ok, status, error)


async def send_slack(
    http: httpx.AsyncClient, settings: Settings, url: str, notice: Notice
) -> dict[str, Any]:
    icon = {"alert.fired": ":rotating_light:", "alert.resolved": ":white_check_mark:"}.get(
        notice.event, ":test_tube:"
    )
    text = f"{icon} *{notice.rule_name}* ({notice.project_name})\n{notice.summary}"
    body = orjson.dumps(
        {
            "text": text,
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": text}},
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open in LogMind"},
                            "url": notice.link,
                        }
                    ],
                },
            ],
        }
    )
    ok, status, error = await _post(
        http, url, body, {"content-type": "application/json"}, settings.webhook_timeout_s
    )
    return _outcome("slack", ok, status, error)
