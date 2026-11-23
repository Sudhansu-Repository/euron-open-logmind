"""Integration harness: the real app in-process against real Postgres, Redis and
ClickHouse (Compose containers, see scripts/test-db.sh), with the mock AI service served
over real HTTP from a background thread.

    make test-integration

Safety: the suite drops and recreates its databases, so it refuses any Postgres database
or ClickHouse database whose name does not contain "test", and any non-local host unless
ALLOW_REMOTE_TEST_DB=true.
"""

from __future__ import annotations

import asyncio
import os
import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest
import uvicorn
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from logmind.core.clickhouse import ClickHouse
from logmind.core.clickhouse_schema import apply as apply_clickhouse
from logmind.core.config import Settings
from logmind.main import create_app

TEST_DB = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://logmind:logmind@localhost:6042/logmind_test"
)
TEST_REDIS = os.environ.get("TEST_REDIS_URL", "redis://localhost:6079/15")
TEST_CLICKHOUSE_BASE = os.environ.get(
    "TEST_CLICKHOUSE_URL", "http://logmind:logmind@localhost:6023/logmind_test"
)
# One ClickHouse database per test session: a fresh name means no session waits for the
# previous one's DROP to finish (a SYNC drop blocks behind any pending lightweight-delete
# mutation the retention test left), and each session drops its own on exit.
TEST_CLICKHOUSE = f"{TEST_CLICKHOUSE_BASE}_{os.getpid()}"
OWNER = {
    "org_name": "Lumen Retail",
    "email": "owner@lumen.test",
    "name": "Owner",
    "password": "Owner-Pass-123",
}
TABLES = (
    "ai_usage, ai_investigation_turns, ai_investigations, ai_providers, alert_history, "
    "alert_rules, error_occurrences, error_groups, services, environments, api_keys, "
    "projects, audit_log, users, organizations"
)
pytestmark = pytest.mark.integration


def _guard(url: str, what: str) -> None:
    parsed = urlparse(url.replace("+asyncpg", ""))
    if "test" not in (parsed.path or ""):
        raise RuntimeError(f"refusing {what} {parsed.path!r}: its name must contain 'test'")
    if (
        parsed.hostname not in ("localhost", "127.0.0.1", "postgres", "clickhouse")
        and os.environ.get("ALLOW_REMOTE_TEST_DB") != "true"
    ):
        raise RuntimeError(f"refusing a non-local test {what} (set ALLOW_REMOTE_TEST_DB=true)")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="session")
def mock_url() -> Iterator[str]:
    port = _free_port()
    config = uvicorn.Config("mockai.app:app", host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="session")
async def database() -> AsyncIterator[str]:
    _guard(TEST_DB, "database")
    _guard(TEST_CLICKHOUSE, "ClickHouse database")
    admin_url = TEST_DB.rsplit("/", 1)[0] + "/postgres"
    name = TEST_DB.rsplit("/", 1)[1]
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    await engine.dispose()
    from logmind.migrations.runner import upgrade

    await asyncio.to_thread(upgrade, TEST_DB)
    ch = ClickHouse(TEST_CLICKHOUSE, timeout_s=120)
    await ch.command(f"DROP DATABASE IF EXISTS {ch.database}", database=False)
    await apply_clickhouse(ch)
    yield TEST_DB
    await ch.command(f"DROP DATABASE IF EXISTS {ch.database}", database=False)
    await ch.close()


@pytest.fixture
def settings(database: str) -> Settings:
    storage = os.environ.get("STORAGE", "local")
    return Settings(
        environment="test",
        database_url=database,
        redis_url=TEST_REDIS,
        clickhouse_url=TEST_CLICKHOUSE,
        session_secret="test-only-session-secret-with-32-plus-bytes",
        api_key_pepper="test-only-api-key-pepper-with-32-plus-bytes",
        local_master_key="test-only-local-master-key-with-32-plus-bytes",
        cors_origins=["http://localhost:6010"],
        storage=storage,
        key_mode=os.environ.get("KEY_MODE", "local"),
        aws_endpoint_url=os.environ.get("AWS_ENDPOINT_URL") or None,
        s3_force_path_style=True,
        evidence_bucket=os.environ.get("EVIDENCE_BUCKET", "logmind-local-evidence"),
        local_storage_dir=os.environ.get("TEST_STORAGE_DIR", "/tmp/logmind-test-evidence"),  # noqa: S108
        mail_backend="log",
        login_attempts_per_minute=1000,
        alert_interval_s=1.0,
        max_past_days=30,
    )


async def _reset(settings: Settings, mock_url: str) -> None:
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    await engine.dispose()
    ch = ClickHouse(settings.clickhouse_url, timeout_s=120)
    for table in ("log_events", "log_rollup_1m"):
        await ch.command(f"TRUNCATE TABLE IF EXISTS {table}")
    await ch.close()
    from redis.asyncio import Redis

    redis = Redis.from_url(settings.redis_url)
    await redis.flushdb()
    await redis.aclose()
    async with httpx.AsyncClient() as client:
        await client.post(f"{mock_url}/_mock/reset")
    from logmind.core import mail

    mail.OUTBOX.clear()


@dataclass
class Api:
    """A signed-in owner client plus helpers for common setup."""

    client: httpx.AsyncClient
    app: FastAPI
    mock_url: str

    @property
    def container(self) -> Any:
        return self.app.state.container

    async def ok(
        self, method: str, path: str, json: Any = None, status: int | None = None, **kw: Any
    ) -> Any:
        resp = await self.client.request(method, path, json=json, **kw)
        expected = status or (201 if method == "POST" and resp.status_code == 201 else 200)
        assert resp.status_code == expected, f"{method} {path}: {resp.status_code} {resp.text}"
        return resp.json() if resp.content else None

    async def mock(self, path: str) -> Any:
        async with httpx.AsyncClient() as c:
            return (await c.get(f"{self.mock_url}{path}")).json()


@pytest.fixture
async def app(settings: Settings, mock_url: str) -> AsyncIterator[FastAPI]:
    await _reset(settings, mock_url)
    application = create_app(settings)
    async with LifespanManager(application, startup_timeout=60, shutdown_timeout=30):
        yield application


def asgi_client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=60)


@pytest.fixture
async def api(app: FastAPI, mock_url: str) -> AsyncIterator[Api]:
    async with asgi_client(app) as client:
        resp = await client.post("/api/v1/auth/signup", json=OWNER)
        assert resp.status_code == 201, resp.text
        client.headers["authorization"] = f"Bearer {resp.json()['session_token']}"
        yield Api(client, app, mock_url)


@dataclass
class World:
    """A configured organisation: a project with an API key, ready to ingest."""

    project_id: str
    key: str
    key_id: str

    @property
    def headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self.key}"}

    @property
    def q(self) -> dict[str, str]:
        return {"project_id": self.project_id}


@pytest.fixture
async def world(api: Api) -> World:
    project = await api.ok("POST", "/api/v1/projects", {"name": "Storefront"})
    key = await api.ok("POST", "/api/v1/keys", {"project_id": project["id"], "name": "ingest"})
    return World(project_id=project["id"], key=key["key"], key_id=key["id"])


@pytest.fixture
async def mock_provider(api: Api) -> dict[str, Any]:
    out: dict[str, Any] = await api.ok(
        "POST", "/api/v1/ai/providers", {"name": "mock", "kind": "mock"}, status=201
    )
    return out
