"""The demo seed (``make demo``): a real HTTP client of the running API, never a direct
database write, so the demo data goes through the same ingestion, redaction, grouping,
investigation and alerting paths a real deployment uses.

It creates "Lumen Retail" with three people, two projects and a mock AI provider (the
mock AI service over the OpenAI-compatible wire format), backfills 24 hours of logs from
seven services, then plays an incident in the last 40 minutes: a payments deploy, the
payments database connection pool running dry, checkout timing out against payments and
an error spike the anomaly rule catches. It runs one AI investigation on the checkout
error group, asks a follow-up, and prints the logins.
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

DEMO_PASSWORD = os.environ.get("LOGMIND_DEMO_PASSWORD", "Demo-Owner-Pass-1")
OWNER_EMAIL = "owner@lumen.example"
PEOPLE = [
    ("sre@lumen.example", "Priya Raman", "admin"),
    ("viewer@lumen.example", "Tom Okafor", "viewer"),
]
SERVICES = ["api-gateway", "checkout", "payments", "inventory", "search", "auth", "notifications"]
ROUTES = ["/cart", "/checkout", "/products", "/search", "/login", "/orders", "/account"]

PY_TIMEOUT = """Traceback (most recent call last):
  File "/app/checkout/handlers.py", line {a}, in place_order
    result = payments.charge(order)
  File "/app/checkout/clients/payments.py", line {b}, in charge
    return self._post("/charge", body)
  File "/usr/local/lib/python3.12/site-packages/httpx/_client.py", line 1544, in post
    raise ReadTimeout(message)
PaymentGatewayTimeout: upstream payments timed out after 5000ms"""

JS_TYPEERROR = """TypeError: Cannot read properties of undefined (reading 'price')
    at renderResults (/srv/search/src/render.js:{a}:17)
    at async handle (/srv/search/src/handler.js:88:9)
    at Layer.handle (/srv/search/node_modules/express/lib/router/layer.js:95:5)"""

PY_KEYERROR = """Traceback (most recent call last):
  File "/app/inventory/sync.py", line {a}, in apply_delta
    stock[sku] -= delta["qty"]
KeyError: 'qty'"""


def _ts(t: datetime) -> str:
    return t.isoformat()


def _baseline(now: datetime, rng: random.Random) -> list[dict[str, Any]]:
    """24 hours of ordinary traffic, busier in the daytime, with the usual background of
    warnings and a few known errors."""
    lines: list[dict[str, Any]] = []
    start = now - timedelta(hours=24)
    minute = 0
    while minute < 24 * 60:
        t = start + timedelta(minutes=minute)
        hour = t.hour
        busy = 3 if 8 <= hour <= 22 else 1
        for _ in range(busy * 2):
            svc = rng.choice(SERVICES)
            route = rng.choice(ROUTES)
            ms = int(rng.lognormvariate(3.4, 0.5))
            lines.append(
                {
                    "timestamp": _ts(t + timedelta(seconds=rng.randint(0, 59))),
                    "level": "info",
                    "service": svc,
                    "message": f"GET {route} 200 in {ms}ms",
                    "request_id": f"req-{uuid.uuid4().hex[:12]}",
                    "attributes": {"http.route": route, "duration_ms": ms},
                }
            )
        if rng.random() < 0.25:
            lines.append(
                {
                    "timestamp": _ts(t),
                    "level": "warn",
                    "service": "api-gateway",
                    "message": f"slow upstream response from inventory: {rng.randint(800, 1500)}ms",
                }
            )
        if rng.random() < 0.06:
            lines.append(
                {
                    "timestamp": _ts(t),
                    "level": "error",
                    "service": "search",
                    "message": "search results render failed",
                    "exception": {
                        "type": "",
                        "stacktrace": JS_TYPEERROR.format(a=rng.randint(20, 90)),
                    },
                }
            )
        if rng.random() < 0.03:
            lines.append(
                {
                    "timestamp": _ts(t),
                    "level": "error",
                    "service": "inventory",
                    "message": "stock delta could not be applied",
                    "exception": {
                        "type": "KeyError",
                        "stacktrace": PY_KEYERROR.format(a=rng.randint(40, 60)),
                    },
                }
            )
        if rng.random() < 0.04:
            email = rng.choice(["maria.lopez@example.com", "j.chen@example.org", "sam@example.net"])
            lines.append(
                {
                    "timestamp": _ts(t),
                    "level": "info",
                    "service": "auth",
                    "message": f"password reset requested for {email}",
                    "attributes": {"user": {"email": email}, "token": uuid.uuid4().hex},
                }
            )
        if rng.random() < 0.02:
            lines.append(
                {
                    "timestamp": _ts(t),
                    "level": "info",
                    "service": "payments",
                    "message": "card 4111 1111 1111 1111 authorised for order "
                    + uuid.uuid4().hex[:8],
                }
            )
        if minute % 240 == 0:
            lines.append(
                {
                    "timestamp": _ts(t),
                    "level": "info",
                    "service": "notifications",
                    "message": "digest emails queued for 1240 recipients",
                }
            )
        minute += 1
    return lines


def _incident(now: datetime, rng: random.Random) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    deploy = now - timedelta(minutes=38)
    lines.append(
        {
            "timestamp": _ts(deploy),
            "level": "info",
            "service": "payments",
            "message": "deploy started: payments version v2.14.0 rolling out (3 replicas)",
            "attributes": {"version": "v2.14.0", "previous": "v2.13.4"},
        }
    )
    lines.append(
        {
            "timestamp": _ts(deploy + timedelta(minutes=2)),
            "level": "info",
            "service": "payments",
            "message": "config loaded: db.pool.max=20 db.pool.timeout=2s",
        }
    )
    pool = now - timedelta(minutes=33)
    for k in range(48):
        lines.append(
            {
                "timestamp": _ts(pool + timedelta(seconds=k * 30)),
                "level": "warn",
                "service": "payments",
                "message": f"db connection pool exhausted (max=20, waiting={4 + k % 17})",
            }
        )
    first = now - timedelta(minutes=30)
    for k in range(230):
        t = first + timedelta(seconds=k * 7 + rng.randint(0, 5))
        if t > now:
            break
        order = uuid.uuid4().hex[:10]
        trace = uuid.uuid4().hex
        lines.append(
            {
                "timestamp": _ts(t - timedelta(milliseconds=5200)),
                "level": "info",
                "service": "api-gateway",
                "message": f"POST /checkout received for order {order}",
                "trace_id": trace,
            }
        )
        lines.append(
            {
                "timestamp": _ts(t),
                "level": "error",
                "service": "checkout",
                "message": f"order {order} failed: payment gateway timeout",
                "trace_id": trace,
                "request_id": f"req-{order}",
                "exception": {
                    "type": "PaymentGatewayTimeout",
                    "message": "upstream payments timed out after 5000ms",
                    "stacktrace": PY_TIMEOUT.format(a=40 + k % 6, b=110 + k % 3),
                },
            }
        )
        if k % 9 == 0:
            lines.append(
                {
                    "timestamp": _ts(t + timedelta(seconds=1)),
                    "level": "error",
                    "service": "notifications",
                    "message": f"order confirmation not sent for {order}: order not found",
                }
            )
    return lines


class Seeder:
    def __init__(self, api_url: str, mock_url: str) -> None:
        self.api = httpx.AsyncClient(base_url=api_url, timeout=60)
        self.mock_url = mock_url.rstrip("/")

    async def close(self) -> None:
        await self.api.aclose()

    async def call(self, method: str, path: str, **kw: Any) -> Any:
        resp = await self.api.request(method, path, **kw)
        if resp.status_code >= 400:
            raise RuntimeError(f"{method} {path}: {resp.status_code} {resp.text[:300]}")
        return resp.json() if resp.content else None

    async def send(self, key: str, lines: list[dict[str, Any]]) -> int:
        accepted = 0
        for i in range(0, len(lines), 1000):
            out = await self.call(
                "POST",
                "/api/v1/logs/batch",
                json={"logs": lines[i : i + 1000], "defaults": {"environment": "production"}},
                headers={"authorization": f"Bearer {key}", "x-logmind-sdk": "demo-seed"},
            )
            accepted += int(out["accepted"])
        return accepted

    async def wait(self, inv_id: str, *, turn: bool = False) -> dict[str, Any]:
        for _ in range(120):
            inv: dict[str, Any] = await self.call("GET", f"/api/v1/ai/investigations/{inv_id}")
            status = inv["turns"][-1]["status"] if turn and inv["turns"] else inv["status"]
            if status in ("completed", "failed"):
                return inv
            await asyncio.sleep(1)
        raise RuntimeError(
            "the worker did not finish the investigation in 2 minutes (make logs SERVICE=worker)"
        )

    async def run(self) -> None:
        resp = await self.api.post(
            "/api/v1/auth/login", json={"email": OWNER_EMAIL, "password": DEMO_PASSWORD}
        )
        if resp.status_code == 200:
            print("The demo organisation already exists; nothing to do.")
            self._print_logins()
            return
        session = await self.call(
            "POST",
            "/api/v1/auth/signup",
            json={
                "org_name": "Lumen Retail",
                "email": OWNER_EMAIL,
                "name": "Alex Morgan",
                "password": DEMO_PASSWORD,
            },
        )
        self.api.headers["authorization"] = f"Bearer {session['session_token']}"
        for email, name, role in PEOPLE:
            await self.call(
                "POST",
                "/api/v1/users",
                json={"email": email, "name": name, "password": DEMO_PASSWORD, "role": role},
            )
        store = await self.call(
            "POST",
            "/api/v1/projects",
            json={
                "name": "Storefront",
                "description": "The customer-facing shop: web, checkout, payments",
                "retention_days": 14,
            },
        )
        tools = await self.call(
            "POST",
            "/api/v1/projects",
            json={
                "name": "Internal Tools",
                "description": "Back office and batch jobs",
                "retention_days": 7,
            },
        )
        key = (
            await self.call(
                "POST",
                "/api/v1/keys",
                json={"project_id": store["id"], "name": "production services"},
            )
        )["key"]
        tools_key = (
            await self.call(
                "POST", "/api/v1/keys", json={"project_id": tools["id"], "name": "batch jobs"}
            )
        )["key"]
        await self.call(
            "POST",
            "/api/v1/ai/providers",
            json={
                "name": "mock-gateway",
                "kind": "openai_compatible",
                "model": "mock-analyst",
                "base_url": f"{self.mock_url}/v1",
                "api_key": "demo-key-not-a-secret",
                "is_default": True,
            },
        )
        now = datetime.now(UTC)
        rng = random.Random(20)
        print("Sending 24 hours of logs from 7 services ...")
        sent = await self.send(key, _baseline(now, rng))
        sent += await self.send(key, _incident(now, rng))
        sent += await self.send(
            tools_key,
            [
                {
                    "timestamp": _ts(now - timedelta(minutes=m * 30)),
                    "level": "info",
                    "service": "nightly-export",
                    "message": f"export batch {m} written: {rng.randint(800, 1200)} rows",
                }
                for m in range(40)
            ],
        )
        print(f"  {sent} lines accepted")
        await self.call(
            "POST",
            "/api/v1/alerts",
            json={
                "project_id": store["id"],
                "name": "Checkout error rate",
                "metric": "error_count",
                "service": "checkout",
                "threshold": 20,
                "window_minutes": 10,
                "email_to": ["oncall@lumen.example"],
                "slack_url": f"{self.mock_url}/hooks/slack-oncall",
            },
        )
        await self.call(
            "POST",
            "/api/v1/alerts",
            json={
                "project_id": store["id"],
                "name": "Error spike (anomaly)",
                "kind": "anomaly",
                "sensitivity": 3,
                "min_count": 10,
                "baseline_hours": 24,
                "email_to": ["oncall@lumen.example"],
                "webhook_url": f"{self.mock_url}/hooks/pager",
            },
        )
        await self.call(
            "POST",
            "/api/v1/alerts",
            json={
                "project_id": store["id"],
                "name": "Inventory warnings",
                "metric": "matching_count",
                "query": "slow upstream",
                "threshold": 500,
                "window_minutes": 60,
                "email_to": ["platform@lumen.example"],
            },
        )
        groups = await self.call(
            "GET", "/api/v1/errors", params={"project_id": store["id"], "sort": "occurrences"}
        )
        by_type = {g["exception_type"]: g for g in groups["items"]}
        if "KeyError" in by_type:
            await self.call(
                "PATCH",
                f"/api/v1/errors/{by_type['KeyError']['id']}",
                params={"project_id": store["id"]},
                json={"status": "resolved"},
            )
        target = by_type.get("PaymentGatewayTimeout")
        if target is not None:
            print("Running an AI investigation on the checkout timeouts ...")
            inv = await self.call(
                "POST",
                "/api/v1/ai/investigate",
                json={"project_id": store["id"], "error_group_id": target["id"]},
            )
            done = await self.wait(inv["id"])
            print(
                f"  {done['status']}: {(done.get('report') or {}).get('root_cause', done.get('error'))}"
            )
            if done["status"] == "completed":
                await self.call(
                    "POST",
                    f"/api/v1/ai/investigations/{inv['id']}/followup",
                    json={"question": "What changed before this started?"},
                )
                await self.wait(inv["id"], turn=True)
        self._print_logins()

    def _print_logins(self) -> None:
        print("")
        print("  Demo logins (password for all: " + DEMO_PASSWORD + ")")
        print(f"    owner   {OWNER_EMAIL}")
        for email, _, role in PEOPLE:
            print(f"    {role:<7} {email}")


async def run(api_url: str, mock_url: str) -> None:
    seeder = Seeder(api_url, mock_url)
    try:
        await seeder.run()
    except (RuntimeError, httpx.HTTPError) as exc:
        print(f"demo seed failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        await seeder.close()
