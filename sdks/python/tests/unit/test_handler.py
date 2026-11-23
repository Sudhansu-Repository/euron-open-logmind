from __future__ import annotations

import logging
import threading
from collections.abc import Iterator

import pytest

from euron_logmind import LogMindHandler

from .helpers import Recorder, make_client


@pytest.fixture
def logger() -> Iterator[logging.Logger]:
    log = logging.getLogger("tests.payments")
    log.setLevel(1)
    log.propagate = False
    yield log
    for handler in list(log.handlers):
        log.removeHandler(handler)


def test_records_are_mapped_to_lines(logger: logging.Logger) -> None:
    rec = Recorder()
    client = make_client(rec)
    logger.addHandler(LogMindHandler(client))
    logger.debug("d")
    logger.info("charged %s for %d", "acme", 42)
    logger.warning("w")
    logger.error("e")
    logger.critical("c")
    logger.log(5, "very fine")
    client.close()
    assert [(line["message"], line["level"]) for line in rec.lines] == [
        ("d", "debug"),
        ("charged acme for 42", "info"),
        ("w", "warn"),
        ("e", "error"),
        ("c", "fatal"),
        ("very fine", "trace"),
    ]
    attrs = rec.lines[1]["attributes"]
    assert attrs["logger"] == "tests.payments"
    assert attrs["module"] == "test_handler"
    assert attrs["function"] == "test_records_are_mapped_to_lines"
    assert isinstance(attrs["line"], int)
    assert attrs["thread"] == threading.current_thread().name


def test_extra_fields_become_attributes_and_ids_are_promoted(logger: logging.Logger) -> None:
    rec = Recorder()
    client = make_client(rec)
    logger.addHandler(LogMindHandler(client, include_location=False))
    logger.info(
        "card declined",
        extra={
            "order_id": 42,
            "customer": {"tier": "gold"},
            "trace_id": "t1",
            "span_id": "s1",
            "request_id": "r1",
        },
    )
    client.close()
    line = rec.lines[0]
    assert line["attributes"] == {
        "logger": "tests.payments",
        "order_id": 42,
        "customer": {"tier": "gold"},
    }
    assert (line["trace_id"], line["span_id"], line["request_id"]) == ("t1", "s1", "r1")


def test_exc_info_becomes_a_structured_exception(logger: logging.Logger) -> None:
    rec = Recorder()
    client = make_client(rec)
    logger.addHandler(LogMindHandler(client))
    try:
        raise ConnectionError("db down")
    except ConnectionError:
        logger.exception("query failed")
    client.close()
    line = rec.lines[0]
    assert line["level"] == "error"
    assert line["message"] == "query failed"  # no traceback text inside the message
    assert line["exception"]["type"] == "ConnectionError"
    assert line["exception"]["message"] == "db down"
    assert "raise ConnectionError" in line["exception"]["stacktrace"]


def test_record_time_is_used_as_timestamp(logger: logging.Logger) -> None:
    rec = Recorder()
    client = make_client(rec)
    handler = LogMindHandler(client)
    record = logger.makeRecord("tests.payments", logging.INFO, __file__, 1, "old", (), None)
    record.created = 0.0
    handler.handle(record)
    client.close()
    assert rec.lines[0]["timestamp"] == "1970-01-01T00:00:00.000000Z"


def test_handler_level_filters(logger: logging.Logger) -> None:
    rec = Recorder()
    client = make_client(rec)
    logger.addHandler(LogMindHandler(client, level=logging.WARNING))
    logger.info("skipped")
    logger.warning("kept")
    client.close()
    assert [line["message"] for line in rec.lines] == ["kept"]


def test_sdk_and_http_loggers_are_ignored() -> None:
    rec = Recorder()
    client = make_client(rec)
    handler = LogMindHandler(client)
    for name in ("httpx", "httpcore.connection", "euron_logmind.client"):
        handler.handle(logging.LogRecord(name, logging.INFO, __file__, 1, "loop", None, None))
    client.close()
    assert rec.requests == []


def test_root_handler_does_not_feed_back_its_own_http_logging() -> None:
    root = logging.getLogger()
    previous = root.level
    rec = Recorder()
    client = make_client(rec, batch_size=1)
    handler = LogMindHandler(client)
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        logging.getLogger("tests.app").info("one line")
        assert client.flush(timeout=3)
    finally:
        root.removeHandler(handler)
        root.setLevel(previous)
        client.close()
    assert [line["message"] for line in rec.lines] == ["one line"]


def test_records_on_the_sender_thread_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = Recorder()
    client = make_client(rec)
    monkeypatch.setattr(client, "is_sender_thread", lambda: True)
    LogMindHandler(client).handle(
        logging.LogRecord("app", logging.INFO, __file__, 1, "x", None, None)
    )
    monkeypatch.undo()
    client.close()
    assert rec.requests == []


def test_handler_flush_flushes_the_client(logger: logging.Logger) -> None:
    rec = Recorder()
    client = make_client(rec)
    handler = LogMindHandler(client)
    logger.addHandler(handler)
    logger.info("flush me")
    handler.flush()
    assert len(rec.requests) == 1
    client.close()


def test_broken_record_goes_to_handle_error(
    logger: logging.Logger, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = Recorder()
    client = make_client(rec)
    handler = LogMindHandler(client)
    errors: list[logging.LogRecord] = []
    monkeypatch.setattr(handler, "handleError", errors.append)
    record = logging.LogRecord("app", logging.INFO, __file__, 1, "%d", ("not a number",), None)
    handler.emit(record)
    client.close()
    assert errors == [record]
