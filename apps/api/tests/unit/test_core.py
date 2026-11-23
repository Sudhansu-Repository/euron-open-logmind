"""Core plumbing: configuration guards, ClickHouse parameter binding, sealing, storage,
URL safety, mail, rate limiting when Redis is down, cursors and windows."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from redis.asyncio import Redis

from logmind.core import mail
from logmind.core.clickhouse import ch_datetime, format_param, parse_ch_datetime
from logmind.core.config import Settings
from logmind.core.errors import AppError
from logmind.core.net import canonical_host, check_url, is_private_host, resolves_safely
from logmind.core.ratelimit import hit
from logmind.core.sealing import LocalSealer
from logmind.core.storage import LocalStorage, ObjectNotFoundError
from logmind.logs.repository import LogFilter, like_pattern
from logmind.logs.service import decode_cursor, encode_cursor, pick_bucket, resolve_window
from logmind.services.service import status_for


def test_production_guard_refuses_demo_secrets() -> None:
    Settings(environment="development").guard()
    with pytest.raises(RuntimeError) as exc:
        Settings(environment="production", cors_origins=["*"]).guard()
    msg = str(exc.value)
    for needle in (
        "SESSION_SECRET",
        "COOKIE_SECURE",
        "CORS_ORIGINS",
        "MAIL_BACKEND",
        "STORAGE",
        "LOCAL_MASTER_KEY",
    ):
        assert needle in msg
    good = Settings(
        environment="production",
        session_secret="s" * 40,
        api_key_pepper="p" * 40,
        local_master_key="m" * 40,
        cookie_secure=True,
        mail_backend="ses",
        storage="s3",
        cors_origins="https://logs.example.com",
    )
    good.guard()
    assert good.cors_origins == ["https://logs.example.com"]
    with pytest.raises(RuntimeError, match="must differ"):
        good.model_copy(update={"api_key_pepper": "s" * 40}).guard()
    with pytest.raises(RuntimeError, match="AWS_ENDPOINT_URL"):
        good.model_copy(update={"cloud": "aws", "aws_endpoint_url": "http://x"}).guard()


def test_clickhouse_values() -> None:
    ts = datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=timezone(timedelta(hours=2)))
    assert ch_datetime(ts) == "2026-01-02 01:04:05.678000"
    assert parse_ch_datetime("2026-01-02 01:04:05.678000") == ts
    assert parse_ch_datetime("2026-01-02 01:04:05") == datetime(2026, 1, 2, 1, 4, 5, tzinfo=UTC)
    assert format_param(["a'b", "c\\d"]) == "['a\\'b','c\\\\d']"
    assert (
        format_param(True) == "1" and format_param(7) == "7" and format_param(ts).startswith("2026")
    )
    assert like_pattern("50%_off") == "%50\\%\\_off%"
    assert LogFilter(start=ts, end=ts, any_terms=["x"]).needs_raw
    assert not LogFilter(start=ts, end=ts, levels=["error"]).needs_raw


async def test_local_sealer_binds_context() -> None:
    sealer = LocalSealer("k" * 40)
    sealed = await sealer.seal("sk-secret", "row:1")
    assert b"sk-secret" not in sealed
    assert await sealer.open(sealed, "row:1") == "sk-secret"
    with pytest.raises(Exception):  # noqa: B017 the AEAD tag check fails
        await sealer.open(sealed, "row:2")
    with pytest.raises(ValueError):
        await sealer.open(b"\x09" + sealed[1:], "row:1")


async def test_local_storage(tmp_path: Path) -> None:
    store = LocalStorage(str(tmp_path))
    await store.put("a/b.json", b"{}", "application/json")
    assert await store.get("a/b.json") == b"{}"
    src = tmp_path / "src.bin"
    src.write_bytes(b"xyz")
    await store.put_file("c.bin", src, "application/octet-stream")
    out = tmp_path / "out.bin"
    await store.get_file("c.bin", out)
    assert out.read_bytes() == b"xyz"
    await store.delete("a/b.json")
    with pytest.raises(ObjectNotFoundError):
        await store.get("a/b.json")
    with pytest.raises(ObjectNotFoundError):
        await store.get_file("missing", out)
    with pytest.raises(ValueError):
        await store.put("../escape", b"", "x")


async def test_url_safety() -> None:
    assert check_url("https://hooks.slack.com/services/x/") == "https://hooks.slack.com/services/x"
    for bad in (
        "ftp://x",
        "http://",
        "http://169.254.169.254/x",
        "http://0xa9fea9fe/",
        "http://metadata/",
    ):
        with pytest.raises(ValueError):
            check_url(bad)
    assert canonical_host("2852039166") == "169.254.169.254"
    assert (
        is_private_host("mockai") and is_private_host("10.0.0.1") and not is_private_host("8.8.8.8")
    )
    assert not is_private_host("")
    assert await resolves_safely("http://127.0.0.1:1/x")
    assert not await resolves_safely("http://127.0.0.1:1/x", allow_private=False)
    assert not await resolves_safely("http://metadata/x")


async def test_mail_log_backend_and_failures(settings: Settings) -> None:
    mail.OUTBOX.clear()
    await mail.send(settings, "a@b.co", "subj", "text", "<p>html</p>")
    assert mail.OUTBOX[-1].subject == "subj"
    broken = settings.model_copy(
        update={"mail_backend": "smtp", "smtp_host": "127.0.0.1", "smtp_port": 9}
    )
    with pytest.raises(mail.MailError):
        await mail.send(broken, "a@b.co", "s", "t")


async def test_rate_limiter_fails_open_when_redis_is_down() -> None:
    redis = Redis.from_url("redis://127.0.0.1:9/0", socket_connect_timeout=0.2)
    await hit(redis, "login:x", 1)
    await hit(redis, "login:x", 1)
    await redis.aclose()


def test_cursors_windows_buckets_and_status() -> None:
    eid = uuid.uuid4()
    ts = datetime(2026, 1, 1, 12, 0, 0, 123456, tzinfo=UTC)
    assert decode_cursor(encode_cursor(ts, eid)) == (ts, eid)
    with pytest.raises(AppError):
        decode_cursor("nope")
    start, end = resolve_window(None, None)
    assert end - start == timedelta(hours=1)
    with pytest.raises(AppError):
        resolve_window(ts, ts)
    with pytest.raises(AppError):
        resolve_window(ts - timedelta(days=500), ts)
    assert pick_bucket(ts, ts + timedelta(minutes=10)) == 10
    assert pick_bucket(ts, ts + timedelta(hours=24)) == 900
    assert pick_bucket(ts, ts + timedelta(days=399)) == 86400
    assert status_for(0, 0, True) == "silent" and status_for(0, 0, False) == "healthy"
    assert status_for(100, 10, True) == "critical" and status_for(100, 3, True) == "degraded"
    assert status_for(100, 1, True) == "healthy"
