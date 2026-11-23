"""Shared helpers for the integration suite: log payloads, an incident scenario with a
real cause chain, and running queued worker jobs inline."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from logmind.worker import drain_jobs

PY_TIMEOUT = """Traceback (most recent call last):
  File "/app/checkout/handlers.py", line {line}, in place_order
    result = payments.charge(order)
  File "/app/checkout/clients/payments.py", line {line2}, in charge
    return self._post("/charge", body)
  File "/usr/lib/python3.12/site-packages/httpx/_client.py", line 1544, in post
    raise TimeoutException(message)
PaymentGatewayTimeout: upstream payments timed out after {ms}ms (order {order})"""

JS_TYPEERROR = """TypeError: Cannot read properties of undefined (reading 'price')
    at renderResults (/srv/search/src/render.js:{line}:17)
    at handle (/srv/search/src/handler.js:88:9)
    at Layer.handle (/srv/search/node_modules/express/lib/router/layer.js:95:5)"""


def iso(ts: datetime) -> str:
    return ts.astimezone(UTC).isoformat()


def log(
    message: str,
    *,
    level: str = "info",
    service: str = "checkout",
    environment: str = "production",
    ts: datetime | None = None,
    **extra: Any,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "message": message,
        "level": level,
        "service": service,
        "environment": environment,
    }
    if ts is not None:
        out["timestamp"] = iso(ts)
    out.update(extra)
    return out


def timeout_error(ts: datetime, n: int, service: str = "checkout") -> dict[str, Any]:
    order = uuid.uuid4().hex[:10]
    return log(
        f"order {order} failed: payment gateway timeout",
        level="error",
        service=service,
        ts=ts,
        request_id=f"req-{order}",
        trace_id=uuid.uuid4().hex,
        exception={
            "type": "PaymentGatewayTimeout",
            "message": f"upstream payments timed out after 5000ms (order {order})",
            "stacktrace": PY_TIMEOUT.format(
                line=40 + n % 7, line2=110 + n % 3, ms=5000, order=order
            ),
        },
    )


async def send(
    client: httpx.AsyncClient, key: str, logs: list[dict[str, Any]], **kw: Any
) -> dict[str, Any]:
    resp = await client.post(
        "/api/v1/logs/batch", json={"logs": logs, **kw}, headers={"authorization": f"Bearer {key}"}
    )
    assert resp.status_code == 202, resp.text
    data: dict[str, Any] = resp.json()
    return data


def incident(now: datetime, noise: int = 300) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """A realistic incident: steady noise, a deploy, a payments connection pool running
    dry, then checkout timing out. Returns the lines and the facts a correct root cause
    must cite (the deploy line, the pool line, the first timeout)."""
    start = now - timedelta(minutes=50)
    lines: list[dict[str, Any]] = []
    for i in range(noise):
        ts = start + timedelta(seconds=i * 2900 / max(noise, 1))
        svc = ("checkout", "inventory", "search", "auth")[i % 4]
        lines.append(log(f"GET /api/items/{i} 200 in {20 + i % 30}ms", service=svc, ts=ts))
    deploy_ts = now - timedelta(minutes=22)
    lines.append(
        log(
            "deploy started: payments version v2.14.0 rolling out", service="payments", ts=deploy_ts
        )
    )
    pool_ts = now - timedelta(minutes=18)
    for k in range(25):
        lines.append(
            log(
                f"db connection pool exhausted (max=20, waiting={5 + k})",
                level="warn",
                service="payments",
                ts=pool_ts + timedelta(seconds=k * 10),
            )
        )
    first_ts = now - timedelta(minutes=15)
    for k in range(40):
        lines.append(timeout_error(first_ts + timedelta(seconds=k * 15), k))
    return lines, {"deploy_ts": deploy_ts, "pool_ts": pool_ts, "first_ts": first_ts}


async def run_jobs(app: Any) -> int:
    return await drain_jobs(app.state.container)
