from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from euron_logmind import IngestError
from euron_logmind.models import build_line
from euron_logmind.transport import (
    BATCH_PATH,
    MAX_BACKOFF_S,
    MAX_RETRY_AFTER_S,
    Sender,
    backoff_delay,
    encode_body,
    parse_retry_after,
)

from .helpers import API_KEY, BASE, Recorder


def make_sender(
    recorder: Recorder, max_retries: int = 3, abort: bool = False
) -> tuple[Sender, list[float]]:
    sleeps: list[float] = []

    def sleep(seconds: float) -> bool:
        sleeps.append(seconds)
        return abort

    http = httpx.Client(base_url=BASE, transport=recorder.transport)
    return Sender(http, API_KEY, max_retries=max_retries, backoff_base_s=0.5, sleep=sleep), sleeps


def lines(n: int) -> list[dict[str, object]]:
    return [build_line("info", f"line {i}") for i in range(n)]


DEFAULTS = {"service": "checkout"}


def test_parse_retry_after() -> None:
    assert parse_retry_after(None) is None
    assert parse_retry_after("") is None
    assert parse_retry_after("3") == 3.0
    assert parse_retry_after(" 1.5 ") == 1.5
    assert parse_retry_after("-4") == 0.0
    assert parse_retry_after("100000") == MAX_RETRY_AFTER_S
    assert parse_retry_after("nan") is None
    assert parse_retry_after("soon") is None
    now = datetime(2026, 11, 16, 12, 0, 0, tzinfo=timezone.utc)
    later = (now + timedelta(seconds=7)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    assert parse_retry_after(later, now=now) == pytest.approx(7.0)
    assert parse_retry_after("Mon, 16 Nov 2026 12:00:07", now=now) == pytest.approx(7.0)


def test_backoff_delay_grows_with_jitter_and_caps() -> None:
    assert backoff_delay(0, 0.5, rand=lambda: 0.0) == 0.25
    assert backoff_delay(0, 0.5, rand=lambda: 1.0) == 0.5
    assert backoff_delay(3, 0.5, rand=lambda: 1.0) == 4.0
    assert backoff_delay(20, 0.5, rand=lambda: 1.0) == MAX_BACKOFF_S
    assert backoff_delay(2, 0.5, retry_after=9.0) == 9.0
    for attempt in range(5):
        value = backoff_delay(attempt, 1.0)
        assert 2**attempt / 2 <= value <= 2**attempt


def test_send_posts_batch_with_headers() -> None:
    rec = Recorder()
    sender, sleeps = make_sender(rec)
    result = sender.send(lines(3), DEFAULTS)
    assert result.accepted == 3 and len(result.event_ids) == 3
    assert sleeps == []
    request = rec.requests[0]
    assert request.method == "POST"
    assert request.url.path == BATCH_PATH
    assert request.headers["authorization"] == f"Bearer {API_KEY}"
    assert request.headers["content-type"] == "application/json"
    assert request.headers["x-logmind-sdk"] == "python/0.1.0"
    assert request.headers["user-agent"].startswith("euron-logmind-python/")
    body = json.loads(request.content)
    assert body["defaults"] == DEFAULTS
    assert [line["message"] for line in body["logs"]] == ["line 0", "line 1", "line 2"]


def test_retries_5xx_then_succeeds() -> None:
    rec = Recorder(httpx.Response(503), httpx.Response(500))
    sender, sleeps = make_sender(rec)
    assert sender.send(lines(1), DEFAULTS).accepted == 1
    assert len(rec.requests) == 3
    assert len(sleeps) == 2
    assert 0.25 <= sleeps[0] <= 0.5 and 0.5 <= sleeps[1] <= 1.0


def test_retry_after_is_honoured_on_429() -> None:
    rec = Recorder(
        httpx.Response(
            429,
            headers={"retry-after": "2"},
            json={"error": {"code": "rate_limited", "message": "slow down"}},
        )
    )
    sender, sleeps = make_sender(rec)
    assert sender.send(lines(1), DEFAULTS).accepted == 1
    assert sleeps == [2.0]


def test_transport_errors_are_retried() -> None:
    rec = Recorder(httpx.ConnectError("refused"), httpx.ReadTimeout("slow"))
    sender, sleeps = make_sender(rec)
    assert sender.send(lines(1), DEFAULTS).accepted == 1
    assert len(sleeps) == 2


def test_gives_up_after_max_retries() -> None:
    rec = Recorder(*[httpx.Response(503) for _ in range(10)])
    sender, sleeps = make_sender(rec, max_retries=2)
    with pytest.raises(IngestError) as info:
        sender.send(lines(1), DEFAULTS)
    assert info.value.status == 503 and info.value.retryable
    assert len(rec.requests) == 3 and len(sleeps) == 2


def test_transport_error_exhausted_has_no_status() -> None:
    rec = Recorder(httpx.ConnectError("refused"))
    sender, _ = make_sender(rec, max_retries=0)
    with pytest.raises(IngestError) as info:
        sender.send(lines(1), DEFAULTS)
    assert info.value.status is None
    assert info.value.code == "transport_error"
    assert API_KEY not in str(info.value)


def test_401_is_not_retried_and_reads_error_body() -> None:
    rec = Recorder(
        httpx.Response(
            401,
            json={
                "error": {"code": "invalid_api_key", "message": "The API key is invalid or revoked"}
            },
        )
    )
    sender, sleeps = make_sender(rec)
    with pytest.raises(IngestError) as info:
        sender.send(lines(2), DEFAULTS)
    assert info.value.status == 401
    assert info.value.code == "invalid_api_key"
    assert "revoked" in info.value.message
    assert not info.value.retryable
    assert len(rec.requests) == 1 and sleeps == []
    assert "IngestError(status=401" in repr(info.value)


def test_4xx_without_json_body() -> None:
    rec = Recorder(httpx.Response(422, text="<html>nope</html>"))
    sender, _ = make_sender(rec)
    with pytest.raises(IngestError) as info:
        sender.send(lines(1), DEFAULTS)
    assert info.value.code == "http_422"


def test_abort_during_backoff_stops_retrying() -> None:
    rec = Recorder(httpx.Response(503), httpx.Response(503))
    sender, sleeps = make_sender(rec, abort=True)
    with pytest.raises(IngestError):
        sender.send(lines(1), DEFAULTS)
    assert len(rec.requests) == 1 and len(sleeps) == 1


def test_413_splits_the_batch_in_half() -> None:
    rec = Recorder(
        httpx.Response(413, json={"error": {"code": "payload_too_large", "message": "too big"}})
    )
    sender, _ = make_sender(rec)
    result = sender.send(lines(4), DEFAULTS)
    assert result.accepted == 4
    sizes = [len(body["logs"]) for body in rec.bodies]
    assert sizes == [4, 2, 2]


def test_413_on_a_single_line_is_dropped() -> None:
    rec = Recorder(httpx.Response(413))
    sender, _ = make_sender(rec)
    with pytest.raises(IngestError) as info:
        sender.send(lines(1), DEFAULTS)
    assert info.value.status == 413


def test_more_than_1000_lines_are_split_into_requests() -> None:
    rec = Recorder()
    sender, _ = make_sender(rec)
    result = sender.send(lines(2500), DEFAULTS)
    assert [len(body["logs"]) for body in rec.bodies] == [1000, 1000, 500]
    assert result.accepted == 2500 and len(result.event_ids) == 2500


def test_success_without_json_body_counts_all_lines() -> None:
    rec = Recorder(httpx.Response(202, text="ok"))
    sender, _ = make_sender(rec)
    assert sender.send(lines(3), DEFAULTS).accepted == 3


def test_encode_body_is_utf8_json() -> None:
    body = encode_body([{"message": "café"}], {"host": "h"})
    assert json.loads(body.decode("utf-8")) == {
        "logs": [{"message": "café"}],
        "defaults": {"host": "h"},
    }
