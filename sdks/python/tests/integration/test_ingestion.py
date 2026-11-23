"""Against a live LogMind API: lines are accepted and stored (the API answers with one
event id per stored line), a handled exception is ingested, a bad key is refused, and the
background path delivers everything it queued."""

from __future__ import annotations

import logging
import uuid

import pytest

from euron_logmind import IngestError, LogMind, LogMindHandler

from .conftest import URL


def test_send_batch_is_accepted_with_event_ids(client: LogMind) -> None:
    marker = uuid.uuid4().hex
    result = client.send_batch(
        [
            {
                "message": f"integration info {marker}",
                "level": "info",
                "attributes": {"marker": marker},
            },
            {
                "message": f"integration warn {marker}",
                "level": "warn",
                "request_id": f"req-{marker[:8]}",
            },
        ]
    )
    assert result.accepted == 2
    assert result.rejected == []
    assert len(result.event_ids) == 2
    assert all(uuid.UUID(event_id) for event_id in result.event_ids)


def test_exception_is_ingested(client: LogMind) -> None:
    try:
        raise TimeoutError("upstream took too long")
    except TimeoutError as exc:
        result = client.send_batch(
            [{"message": "payment timed out", "level": "error", "exception": exc}]
        )
    assert result.accepted == 1
    assert len(result.event_ids) == 1


def test_background_path_delivers_everything(client: LogMind) -> None:
    logger = logging.getLogger("sdk.integration")
    logger.propagate = False
    handler = LogMindHandler(client)
    logger.addHandler(handler)
    try:
        for i in range(25):
            client.info(f"background line {i}", index=i)
        logger.warning("from the stdlib handler", extra={"source": "handler"})
        assert client.flush(timeout=15)
    finally:
        logger.removeHandler(handler)
    stats = client.stats
    assert stats.accepted == 26
    assert stats.dropped_failed == 0 and stats.rejected == 0


def test_bad_key_is_refused() -> None:
    log = LogMind(api_key="lmk_nope_notarealsecret", endpoint=URL, register_atexit=False)
    try:
        with pytest.raises(IngestError) as info:
            log.send_batch([{"message": "should be refused"}])
        assert info.value.status == 401
        assert not info.value.retryable
    finally:
        log.close()
