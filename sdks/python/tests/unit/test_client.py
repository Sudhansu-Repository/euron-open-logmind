from __future__ import annotations

import socket
import time

import httpx
import pytest

from euron_logmind import DEFAULT_ENDPOINT, IngestError, LogMind

from .helpers import API_KEY, BASE, Recorder, make_client


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LOGMIND_API_KEY", "LOGMIND_ENDPOINT", "LOGMIND_SERVICE", "LOGMIND_ENVIRONMENT"):
        monkeypatch.delenv(name, raising=False)


def wait_for(predicate: object, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():  # type: ignore[operator]
            return True
        time.sleep(0.005)
    return False


# Batching ---------------------------------------------------------------------


def test_lines_are_sent_once_batch_size_is_reached() -> None:
    rec = Recorder()
    client = make_client(rec, batch_size=3)
    for i in range(3):
        client.info(f"line {i}")
    assert wait_for(lambda: len(rec.requests) == 1)
    assert [line["message"] for line in rec.lines] == ["line 0", "line 1", "line 2"]
    client.close()


def test_batch_size_splits_lines_into_several_requests() -> None:
    rec = Recorder()
    client = make_client(rec, batch_size=2)
    for i in range(5):
        client.info(f"line {i}")
    assert client.flush(timeout=3)
    assert [len(body["logs"]) for body in rec.bodies] == [2, 2, 1]
    assert [line["message"] for line in rec.lines] == [f"line {i}" for i in range(5)]
    client.close()


def test_partial_batch_is_sent_after_the_flush_interval() -> None:
    rec = Recorder()
    client = make_client(rec, batch_size=100, flush_interval_s=0.05)
    client.info("lonely line")
    assert rec.requests == []
    assert wait_for(lambda: len(rec.requests) == 1, timeout=2)
    assert rec.lines[0]["message"] == "lonely line"
    client.close()


def test_nothing_is_sent_before_the_interval_without_flush() -> None:
    rec = Recorder()
    client = make_client(rec, batch_size=100, flush_interval_s=60)
    client.info("waiting")
    time.sleep(0.1)
    assert rec.requests == []
    assert client.stats.queued == 1
    client.close()
    assert len(rec.requests) == 1


def test_batch_size_is_clamped_to_the_api_limit() -> None:
    assert make_client(Recorder(), batch_size=50_000).batch_size == 1000
    assert make_client(Recorder(), batch_size=0).batch_size == 1


# Serialisation and defaults ---------------------------------------------------


def test_batch_defaults_carry_service_environment_and_host() -> None:
    rec = Recorder()
    with make_client(rec) as client:
        client.info("hello")
    assert rec.bodies[0]["defaults"] == {
        "service": "checkout",
        "environment": "test",
        "host": "web-1",
    }
    assert "service" not in rec.lines[0]


def test_default_host_and_environment() -> None:
    rec = Recorder()
    client = LogMind(api_key=API_KEY, transport=rec.transport, register_atexit=False)
    assert client.endpoint == DEFAULT_ENDPOINT
    assert client.environment == "production"
    assert client.host == socket.gethostname()
    assert client.service is None
    client.info("x")
    client.close()
    assert rec.bodies[0]["defaults"] == {"environment": "production", "host": socket.gethostname()}


def test_empty_host_is_left_out_of_defaults() -> None:
    rec = Recorder()
    with make_client(rec, host="", service=None) as client:
        client.info("x")
    assert rec.bodies[0]["defaults"] == {"environment": "test"}


def test_every_level_method() -> None:
    rec = Recorder()
    with make_client(rec) as client:
        client.trace("t")
        client.debug("d")
        client.info("i")
        client.warning("w1")
        client.warn("w2")
        client.error("e")
        client.critical("c")
        client.fatal("f")
        client.log("warning", "l1")
        client.log(40, "l2")
    assert [(line["message"], line["level"]) for line in rec.lines] == [
        ("t", "trace"),
        ("d", "debug"),
        ("i", "info"),
        ("w1", "warn"),
        ("w2", "warn"),
        ("e", "error"),
        ("c", "fatal"),
        ("f", "fatal"),
        ("l1", "warn"),
        ("l2", "error"),
    ]


def test_fields_attributes_and_correlation_ids() -> None:
    rec = Recorder()
    with make_client(rec) as client:
        client.info(
            "order placed",
            attributes={"order_id": 42, "amount": 19.99},
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            span_id="00f067aa0ba902b7",
            request_id="req-7",
            customer="acme",
            service="billing",
        )
    line = rec.lines[0]
    assert line["attributes"] == {"order_id": 42, "amount": 19.99, "customer": "acme"}
    assert line["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert line["span_id"] == "00f067aa0ba902b7"
    assert line["request_id"] == "req-7"
    assert line["service"] == "billing"  # a per-line override beats the batch default


def test_timestamp_is_captured_at_log_time_in_iso_8601() -> None:
    rec = Recorder()
    client = make_client(rec)
    client.info("early")
    logged_at = time.time()
    time.sleep(0.05)
    client.close()
    stamp = rec.lines[0]["timestamp"]
    assert stamp.endswith("Z") and "T" in stamp
    from datetime import datetime

    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    assert abs(parsed - logged_at) < 0.04


def test_explicit_timestamp() -> None:
    rec = Recorder()
    with make_client(rec) as client:
        client.info("old", timestamp=0)
    assert rec.lines[0]["timestamp"] == "1970-01-01T00:00:00.000000Z"


def test_exception_captures_type_message_and_traceback() -> None:
    rec = Recorder()
    with make_client(rec) as client:
        empty: dict[str, int] = {}
        try:
            empty["missing"]
        except KeyError:
            client.exception("lookup failed", order_id=1)
        try:
            raise TimeoutError("upstream took 30s")
        except TimeoutError:
            client.error("payment timed out", exc_info=True)
            client.exception()
        client.error("no exception here", exc_info=True)
    first, second, third, fourth = rec.lines
    assert first["level"] == "error"
    assert first["exception"]["type"] == "KeyError"
    assert "missing" in first["exception"]["message"]
    assert "Traceback" in first["exception"]["stacktrace"]
    assert first["attributes"] == {"order_id": 1}
    assert second["exception"]["type"] == "TimeoutError"
    assert second["exception"]["message"] == "upstream took 30s"
    assert third["message"] == "upstream took 30s"  # empty message falls back to the exception
    assert "exception" not in fourth


def test_exception_instance_can_be_passed() -> None:
    rec = Recorder()
    with make_client(rec) as client:
        client.error("handled elsewhere", exc_info=RuntimeError("late"))
    assert rec.lines[0]["exception"]["type"] == "RuntimeError"


def test_non_json_attribute_values_never_break_a_batch() -> None:
    rec = Recorder()
    with make_client(rec) as client:
        client.info("odd", attributes={"obj": object(), "nan": float("nan")})
        client.info("fine")
    assert len(rec.lines) == 2
    assert rec.lines[0]["attributes"]["nan"] == "nan"
    assert rec.lines[0]["attributes"]["obj"].startswith("<object object")


# Env defaults ----------------------------------------------------------------


def test_env_var_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGMIND_API_KEY", API_KEY)
    monkeypatch.setenv("LOGMIND_ENDPOINT", "http://logs.internal.test:6030/")
    monkeypatch.setenv("LOGMIND_SERVICE", "worker")
    monkeypatch.setenv("LOGMIND_ENVIRONMENT", "staging")
    rec = Recorder()
    client = LogMind(transport=rec.transport, register_atexit=False)
    assert client.enabled
    assert client.endpoint == "http://logs.internal.test:6030"
    assert client.service == "worker" and client.environment == "staging"
    client.info("from env")
    client.close()
    assert str(rec.requests[0].url) == "http://logs.internal.test:6030/api/v1/logs/batch"
    assert rec.requests[0].headers["authorization"] == f"Bearer {API_KEY}"


def test_explicit_arguments_beat_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGMIND_API_KEY", "lmk_env_env")
    monkeypatch.setenv("LOGMIND_ENDPOINT", "http://env.test")
    rec = Recorder()
    client = make_client(rec)
    client.info("x")
    client.close()
    assert rec.requests[0].url.host == "logmind.test"
    assert rec.requests[0].headers["authorization"] == f"Bearer {API_KEY}"


def test_missing_key_disables_the_client(capsys: pytest.CaptureFixture[str]) -> None:
    rec = Recorder()
    client = LogMind(transport=rec.transport, register_atexit=False)
    assert not client.enabled
    client.info("dropped")
    assert client.flush() is True
    assert client.close() is True
    assert rec.requests == []
    assert client.stats.dropped_closed == 1
    assert "no API key" in capsys.readouterr().err
    with pytest.raises(IngestError) as info:
        client.send_batch([{"message": "x"}])
    assert info.value.code == "disabled"


# Failure behaviour ------------------------------------------------------------


def test_retries_then_delivers() -> None:
    rec = Recorder(
        httpx.Response(503),
        httpx.Response(429, headers={"retry-after": "0"}),
        httpx.ConnectError("refused"),
    )
    with make_client(rec) as client:
        client.info("eventually")
    assert len(rec.requests) == 4
    stats = client.stats
    assert stats.accepted == 1 and stats.retries == 3 and stats.dropped_failed == 0


def test_unreachable_server_drops_after_retries_with_one_warning(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rec = Recorder(*[httpx.ConnectError("refused") for _ in range(20)])
    client = make_client(rec, max_retries=1, batch_size=1)
    client.info("a")
    client.info("b")
    assert client.flush(timeout=5)
    client.close()
    stats = client.stats
    assert stats.dropped_failed == 2 and stats.accepted == 0 and stats.retries == 2
    err = capsys.readouterr().err
    assert err.count("[euron-logmind]") == 1
    assert "after retries" in err


def test_bad_key_drops_batches_with_one_warning_and_never_leaks_the_key(
    capsys: pytest.CaptureFixture[str],
) -> None:
    unauthorized = httpx.Response(
        401,
        json={"error": {"code": "invalid_api_key", "message": "The API key is invalid or revoked"}},
    )
    rec = Recorder(unauthorized, unauthorized, unauthorized)
    client = make_client(rec, batch_size=1)
    for i in range(3):
        client.info(f"line {i}")
    assert client.flush(timeout=3)
    client.close()
    assert len(rec.requests) == 3  # one request per batch, no retries
    assert client.stats.dropped_failed == 3
    err = capsys.readouterr().err
    assert err.count("[euron-logmind]") == 1
    assert "401" in err and "invalid_api_key" in err
    assert API_KEY not in err and "0123456789abcdef" not in err


def test_server_side_rejections_are_counted(capsys: pytest.CaptureFixture[str]) -> None:
    rec = Recorder(
        httpx.Response(
            202,
            json={
                "accepted": 1,
                "rejected": [{"index": 1, "reason": "bad timestamp"}],
                "event_ids": ["e1"],
            },
        )
    )
    with make_client(rec) as client:
        client.info("ok")
        client.info("bad")
    assert client.stats.accepted == 1 and client.stats.rejected == 1
    assert "bad timestamp" in capsys.readouterr().err


def test_logging_never_raises_even_when_line_building_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import euron_logmind.client as client_module

    def boom(*args: object, **kwargs: object) -> dict[str, object]:
        raise RuntimeError("bug")

    monkeypatch.setattr(client_module, "build_line", boom)
    client = make_client(Recorder())
    client.info("x")
    client.close()
    assert "could not record" in capsys.readouterr().err


def test_unexpected_sender_error_does_not_kill_the_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = Recorder()
    client = make_client(rec, batch_size=1)
    assert client._sender is not None
    original = client._sender.send
    calls = {"n": 0}

    def flaky(lines: list[dict[str, object]], defaults: dict[str, str]) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("bug in sender")
        return original(lines, defaults)

    monkeypatch.setattr(client._sender, "send", flaky)
    client.info("first")
    client.info("second")
    assert client.flush(timeout=3)
    client.close()
    assert client.stats.dropped_failed == 1 and client.stats.accepted == 1


def test_warnings_survive_a_closed_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    class Closed:
        def write(self, _: str) -> int:
            raise ValueError("I/O operation on closed file")

    monkeypatch.setattr("sys.stderr", Closed())
    client = LogMind(register_atexit=False)  # warns about the missing key
    assert not client.enabled


# Queue overflow -----------------------------------------------------------------


def test_full_queue_drops_the_oldest_lines(capsys: pytest.CaptureFixture[str]) -> None:
    rec = Recorder()
    client = make_client(rec, max_queue=3, batch_size=100)
    for i in range(5):
        client.info(f"line {i}")
    assert client.stats.dropped_queue_full == 2
    assert client.stats.queued == 3
    client.close()
    assert [line["message"] for line in rec.lines] == ["line 2", "line 3", "line 4"]
    err = capsys.readouterr().err
    assert err.count("queue full") == 1 and "oldest" in err


# Flush and close ----------------------------------------------------------------


def test_flush_returns_true_when_drained_and_false_on_timeout() -> None:
    rec = Recorder()
    client = make_client(rec)
    assert client.flush() is True  # nothing queued
    client.info("x")
    assert client.flush(timeout=3) is True
    assert len(rec.requests) == 1

    def slow(request: httpx.Request) -> httpx.Response:
        time.sleep(0.5)
        return httpx.Response(202, json={"accepted": 1})

    rec2 = Recorder(slow)
    client2 = make_client(rec2)
    client2.info("slow")
    assert client2.flush(timeout=0.05) is False
    assert client2.flush(timeout=None) is True
    client.close()
    client2.close()


def test_close_flushes_and_is_idempotent() -> None:
    rec = Recorder()
    client = make_client(rec)
    client.info("a")
    client.info("b")
    assert client.close() is True
    assert len(rec.lines) == 2
    assert client.close() is True
    assert not client.enabled


def test_lines_after_close_are_dropped_and_counted() -> None:
    rec = Recorder()
    client = make_client(rec)
    client.close()
    client.info("late")
    assert client.stats.dropped_closed == 1
    assert rec.requests == []


def test_close_with_unreachable_server_respects_the_timeout() -> None:
    rec = Recorder(*[httpx.ConnectError("refused") for _ in range(100)])
    client = make_client(rec, max_retries=50, backoff_base_s=0.2)
    client.info("stuck")
    started = time.monotonic()
    assert client.close(timeout=0.3) is False
    assert time.monotonic() - started < 3
    stats = client.stats
    assert stats.queued == 0
    assert stats.dropped_failed + stats.dropped_closed == 1


def test_close_counts_lines_left_when_the_thread_is_gone() -> None:
    rec = Recorder()
    client = make_client(rec)
    client._closed = True  # simulate the worker having stopped
    with client._cond:
        client._cond.notify_all()
    assert client._thread is not None
    client._thread.join(2)
    client._closed = False
    client.info("orphan")
    assert client.flush(timeout=0.1) is False
    assert client.close(timeout=0.1) is False
    assert client.stats.dropped_closed == 1


def test_context_manager_closes() -> None:
    rec = Recorder()
    with make_client(rec) as client:
        client.info("inside")
    assert not client.enabled
    assert len(rec.requests) == 1


def test_atexit_hook_is_registered_and_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    registered: list[object] = []
    unregistered: list[object] = []
    monkeypatch.setattr("atexit.register", registered.append)
    monkeypatch.setattr("atexit.unregister", unregistered.append)
    rec = Recorder()
    client = LogMind(api_key=API_KEY, endpoint=BASE, transport=rec.transport)
    assert registered == [client._atexit_close]
    client.info("at exit")
    client._atexit_close()
    assert len(rec.lines) == 1
    assert unregistered == [client._atexit_close]


def test_repr_never_contains_the_key() -> None:
    client = make_client(Recorder())
    text = repr(client)
    assert "logmind.test" in text and API_KEY not in text and "lmk_" not in text
    client.close()


def test_sender_thread_is_a_daemon() -> None:
    client = make_client(Recorder())
    assert client._thread is not None and client._thread.daemon
    assert not client.is_sender_thread()
    client.close()


# send_batch ---------------------------------------------------------------------


def test_send_batch_returns_the_ingest_result() -> None:
    rec = Recorder()
    client = make_client(rec)
    result = client.send_batch(
        [
            {"message": "one", "level": "warning", "attributes": {"k": "v"}, "trace_id": "abc"},
            {"message": "two", "exception": ValueError("bad"), "timestamp": 0},
            {"message": "three"},
        ]
    )
    assert result.accepted == 3 and len(result.event_ids) == 3
    one, two, three = rec.lines
    assert one["level"] == "warn" and one["attributes"] == {"k": "v"} and one["trace_id"] == "abc"
    assert two["exception"]["type"] == "ValueError" and two["timestamp"].startswith("1970")
    assert three["level"] == "info"
    assert rec.bodies[0]["defaults"]["service"] == "checkout"
    client.close()


def test_send_batch_raises_on_failure() -> None:
    rec = Recorder(
        httpx.Response(401, json={"error": {"code": "invalid_api_key", "message": "revoked"}})
    )
    client = make_client(rec)
    with pytest.raises(IngestError) as info:
        client.send_batch([{"message": "x"}])
    assert info.value.status == 401
    client.close()


def test_send_batch_retries_with_real_sleep() -> None:
    rec = Recorder(httpx.Response(503))
    client = make_client(rec)
    assert client.send_batch([{"message": "x"}]).accepted == 1
    assert len(rec.requests) == 2
    client.close()
