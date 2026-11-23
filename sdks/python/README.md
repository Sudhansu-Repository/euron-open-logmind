# euron-logmind (Python)

The Python SDK for [Euron Open LogMind](../../README.md), the self-hosted log
intelligence platform. It ships structured log lines (levels, attributes, trace and
request ids, exceptions with tracebacks) to a LogMind API in batches from a background
thread. It is part of the open-source initiative of **ENGAGESPHERE TECHNOLOGY PRIVATE
LIMITED** and is MIT licensed.

```bash
pip install euron-logmind        # Python 3.10+, httpx is the only dependency
```

The package is not on PyPI yet. Until then install it from this repository:
`pip install ./sdks/python` or `uv pip install -e ./sdks/python`.

## Quickstart

```python
from euron_logmind import LogMind

log = LogMind(api_key="lmk_...", service="checkout")  # or set LOGMIND_API_KEY

log.info("order placed", order_id=42, amount=1999)  # extra kwargs become attributes
log.warning("inventory low", sku="SKU-1042", remaining=2)
log.info("payment authorised", trace_id="4bf92f3577b34da6a3ce929d0e0e4736", request_id="req-7")

try:
    charge_card(order)
except TimeoutError:
    log.exception("payment failed", order_id=42)  # type, message and traceback
    # same as: log.error("payment failed", exc_info=True, order_id=42)

log.close()  # or rely on the atexit hook
```

`with LogMind(...) as log:` closes (and flushes) deterministically at the end of the
block. Every example runs against `http://localhost:6030` by default (`make up` in the
project root); set `endpoint=` or `LOGMIND_ENDPOINT` for another deployment.

| What | Where |
| --- | --- |
| `log.debug/info/warning/error/critical(message, **fields)` | queue one line; `warn` and `fatal` are aliases, `trace` and `log(level, ...)` cover the rest |
| `log.exception(message, **fields)` | level `error` with the current exception attached |
| `attributes=`, `trace_id=`, `span_id=`, `request_id=`, `exc_info=`, `timestamp=` | per-line fields; `service=`/`environment=`/`host=` override the client defaults for one line |
| `log.flush(timeout)` | send everything queued now; `True` when the queue drained |
| `log.close(timeout)` | flush, stop the sender thread, release connections |
| `log.send_batch(logs)` | send now on the calling thread and return the API's `IngestResult` |
| `log.stats` | counters: `queued`, `accepted`, `rejected`, `dropped_queue_full`, `dropped_failed`, `dropped_closed`, `batches_sent`, `retries` |
| `LogMindHandler(log)` | a `logging.Handler` for the stdlib `logging` module |

## Configuration

| Argument | Env var | Default | Meaning |
| --- | --- | --- | --- |
| `api_key` | `LOGMIND_API_KEY` | none | project API key `lmk_<prefix>_<secret>`; without one the client is disabled |
| `endpoint` | `LOGMIND_ENDPOINT` | `http://localhost:6030` | LogMind API base URL |
| `service` | `LOGMIND_SERVICE` | none | default `service` for every line |
| `environment` | `LOGMIND_ENVIRONMENT` | `production` | default `environment` for every line |
| `host` | | `socket.gethostname()` | default `host` for every line (`""` to leave it out) |
| `batch_size` | | `100` | lines per request (capped at the API's 1000) |
| `flush_interval_s` | | `1.0` | longest a queued line waits before it is sent |
| `max_queue` | | `10000` | lines held in memory before the oldest are dropped |
| `timeout_s` | | `10` | per request timeout |
| `max_retries` | | `3` | retries per batch for retryable failures |
| `backoff_base_s` | | `0.5` | first backoff step (doubles per retry, capped at 30 s) |
| `transport` | | httpx default | an `httpx.BaseTransport` (tests use `httpx.MockTransport`) |
| `register_atexit` | | `True` | flush on interpreter exit |

Explicit arguments always win over env vars.

## Wire format

Every batch is one request:

```
POST {endpoint}/api/v1/logs/batch
Authorization: Bearer lmk_<prefix>_<secret>
Content-Type: application/json
x-logmind-sdk: python/0.1.0

{
  "logs": [
    {
      "message": "payment failed",
      "level": "error",
      "timestamp": "2026-11-16T12:30:00.123456Z",
      "attributes": {"order_id": 42},
      "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
      "request_id": "req-7",
      "exception": {"type": "TimeoutError", "message": "...", "stacktrace": "Traceback ..."}
    }
  ],
  "defaults": {"service": "checkout", "environment": "production", "host": "web-1"}
}
```

The API answers `202` with an `IngestResult`: `accepted`, `rejected` (`[{index, reason}]`),
`redactions`, `error_groups` and `event_ids`. Levels are `trace`, `debug`, `info`,
`warn`, `error` and `fatal` (`warning` and `critical` are mapped). Timestamps are taken
when the log call is made, in ISO 8601 UTC. Fields are clamped to the API's limits
before they are queued (a 4000 character exception message, a 64,000 character traceback
keeping its tail, and so on), and attribute values that JSON cannot represent (objects, NaN, sets,
bytes, cycles) are converted when the line is logged, so one odd value never gets a
whole batch refused.

## Behaviour on failure

Logging must never be the reason an application breaks, so the logging methods,
`flush` and `close` never raise.

| Situation | What happens |
| --- | --- |
| 429, 408, 5xx, connection refused, DNS failure, timeout | retried up to `max_retries` times with exponential backoff and jitter (half to the full step); a `Retry-After` header (seconds or HTTP date, capped at 60 s) replaces the computed wait |
| retries exhausted | the batch is dropped, counted in `stats.dropped_failed` |
| 401 (bad or revoked key), 400, 422, other 4xx | not retried (it cannot succeed); the batch is dropped and counted |
| 413 | the batch is split in half and each half is sent; a single line that is still too large is dropped |
| a line refused inside an accepted batch | counted in `stats.rejected` |
| queue full (`max_queue`) | the **oldest** queued line is dropped to make room for the new one (recent lines usually explain an incident), counted in `stats.dropped_queue_full` |
| no API key | the client is disabled: lines are dropped and counted, nothing is sent |

Each kind of problem prints **one** line on stderr, prefixed `[euron-logmind]`, the first
time it happens (not once per line or per batch). The API key never appears in a
warning, an error or the client's `repr`.

`flush(timeout)` returns `True` once every queued line was accepted, rejected or dropped,
`False` if the timeout passed first. `close()` cuts any retry wait short once its own
timeout passes, so shutdown is bounded even with the API down. A daemon thread does the
sending, so it never blocks interpreter exit; the `atexit` hook gives queued lines a 5
second grace period to ship.

`send_batch()` is the one call that does raise (`IngestError` with `status`, `code` and
`retryable`): it is the call to use when the caller wants to know what happened, for
example in a deploy script or a test.

## Logging integration

```python
import logging
from euron_logmind import LogMind, LogMindHandler

log = LogMind(service="checkout")
logging.getLogger().addHandler(LogMindHandler(log))
logging.getLogger().setLevel(logging.INFO)

logger = logging.getLogger("payments")
logger.warning("card declined for %s", "acme", extra={"order_id": 42, "request_id": "req-7"})
try:
    charge()
except Exception:
    logger.exception("charge failed")
```

| `LogRecord` | LogMind line |
| --- | --- |
| `levelno` | level (`DEBUG` debug, `INFO` info, `WARNING` warn, `ERROR` error, `CRITICAL` fatal, below `DEBUG` trace) |
| `getMessage()` | message, with `%` arguments applied |
| `exc_info` | structured `exception` (the traceback is not pasted into the message) |
| `created` | timestamp |
| `name`, `module`, `funcName`, `lineno`, `threadName` | attributes `logger`, `module`, `function`, `line`, `thread` (`include_location=False` keeps only `logger`) |
| `extra={...}` | attributes, except `trace_id`, `span_id` and `request_id`, which fill their own fields |

Records from `httpx`, `httpcore` and `euron_logmind` itself, and anything logged on the
SDK's sender thread, are skipped, so attaching the handler to the root logger cannot
create a feedback loop.

## Development

```bash
uv sync                                    # dev environment
uv run pytest                              # unit tests; integration tests skip without a server
uv run pytest --cov                        # with coverage
uv run ruff check && uv run ruff format --check && uv run mypy --strict src tests
LOGMIND_TEST_API_URL=http://localhost:6030 LOGMIND_TEST_API_KEY=lmk_... uv run pytest tests/integration
uv build                                   # wheel and sdist into dist/
```

The integration suite sends real batches to a running API and checks the `IngestResult`
(accepted count, one event id per line, a bad key refused with 401). It is skipped, not
failed, when `LOGMIND_TEST_API_URL` and `LOGMIND_TEST_API_KEY` are unset.
