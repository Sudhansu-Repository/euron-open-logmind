"""The LogMind client: queue log lines in memory and ship them in batches from one
background thread, so a log call costs microseconds and never waits on the network.

Guarantees:

* **Never raises into the application.** The logging methods, ``flush`` and ``close``
  swallow every error. Problems are counted in :attr:`LogMind.stats` and reported with a
  single line on stderr per kind of problem (never per line, never with the API key).
* **Bounded memory.** At most ``max_queue`` lines wait in memory. When the queue is full
  the **oldest** queued line is dropped to make room for the new one (recent lines are
  usually the ones that explain an incident) and ``stats.dropped_queue_full`` counts it.
* **Ships on exit.** An ``atexit`` hook calls :meth:`LogMind.close`, which flushes with a
  grace period, so a short script that never calls ``close`` still delivers its lines.
"""

from __future__ import annotations

import atexit
import os
import socket
import sys
import threading
import time
from collections import deque
from collections.abc import Mapping, Sequence
from datetime import datetime
from types import TracebackType
from typing import Any

import httpx

from euron_logmind.errors import IngestError
from euron_logmind.models import (
    MAX_BATCH,
    MAX_ENVIRONMENT,
    MAX_HOST,
    MAX_SERVICE,
    ExcInfo,
    IngestResult,
    Stats,
    build_line,
    clamp,
)
from euron_logmind.transport import Sender

DEFAULT_ENDPOINT = "http://localhost:6030"
DEFAULT_ENVIRONMENT = "production"
ATEXIT_TIMEOUT_S = 5.0

_LINE_KEYS = (
    "timestamp",
    "attributes",
    "trace_id",
    "span_id",
    "request_id",
    "service",
    "environment",
    "host",
)


def _blocking_sleep(seconds: float) -> bool:
    time.sleep(seconds)
    return False


def _env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


class LogMind:
    """Ship log lines to a LogMind API.

    ``api_key``, ``endpoint``, ``service`` and ``environment`` fall back to the
    ``LOGMIND_API_KEY``, ``LOGMIND_ENDPOINT``, ``LOGMIND_SERVICE`` and
    ``LOGMIND_ENVIRONMENT`` environment variables. Without an API key the client is
    disabled: it prints one warning, drops every line and never touches the network.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        endpoint: str | None = None,
        service: str | None = None,
        environment: str | None = None,
        host: str | None = None,
        batch_size: int = 100,
        flush_interval_s: float = 1.0,
        max_queue: int = 10_000,
        timeout_s: float = 10.0,
        max_retries: int = 3,
        backoff_base_s: float = 0.5,
        transport: httpx.BaseTransport | None = None,
        register_atexit: bool = True,
    ) -> None:
        self._api_key = api_key or _env("LOGMIND_API_KEY")
        self.endpoint = (endpoint or _env("LOGMIND_ENDPOINT") or DEFAULT_ENDPOINT).rstrip("/")
        self.service = clamp(service or _env("LOGMIND_SERVICE"), MAX_SERVICE)
        self.environment = clamp(
            environment or _env("LOGMIND_ENVIRONMENT") or DEFAULT_ENVIRONMENT, MAX_ENVIRONMENT
        )
        self.host = clamp(host if host is not None else socket.gethostname(), MAX_HOST)
        self.batch_size = max(1, min(int(batch_size), MAX_BATCH))
        self.flush_interval_s = max(0.01, float(flush_interval_s))
        self.max_queue = max(1, int(max_queue))

        self._cond = threading.Condition()
        self._buffer: deque[dict[str, Any]] = deque()
        self._first_queued_at = 0.0
        self._inflight = 0
        self._flush_requested = False
        self._closing = False
        self._closed = False
        self._abort = threading.Event()
        self._warned: set[str] = set()
        self._counts = {
            "accepted": 0,
            "rejected": 0,
            "dropped_queue_full": 0,
            "dropped_failed": 0,
            "dropped_closed": 0,
            "batches_sent": 0,
            "retries": 0,
        }
        self._thread: threading.Thread | None = None
        self._http: httpx.Client | None = None
        self._sender: Sender | None = None

        if not self._api_key:
            self._warn_once(
                "no_key",
                "no API key (pass api_key= or set LOGMIND_API_KEY); logging is disabled",
            )
            return
        self._http = httpx.Client(base_url=self.endpoint, timeout=timeout_s, transport=transport)
        self._sender = Sender(
            self._http,
            self._api_key,
            max_retries=max_retries,
            backoff_base_s=backoff_base_s,
            sleep=self._abort.wait,
            on_retry=self._count_retry,
        )
        self._thread = threading.Thread(target=self._run, name="euron-logmind-sender", daemon=True)
        self._thread.start()
        self._atexit_registered = register_atexit
        if register_atexit:
            atexit.register(self._atexit_close)

    # Public logging API --------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """``False`` when the client has no API key or has been closed."""
        return self._sender is not None and not self._closing

    def log(
        self,
        level: str | int,
        message: object,
        *,
        attributes: Mapping[str, Any] | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        request_id: str | None = None,
        exc_info: ExcInfo = None,
        timestamp: datetime | float | None = None,
        service: str | None = None,
        environment: str | None = None,
        host: str | None = None,
        **fields: Any,
    ) -> None:
        """Queue one line. Extra keyword arguments become attributes:
        ``log.info("paid", order_id=42)`` sends ``attributes={"order_id": 42}``."""
        try:
            attrs = {**attributes, **fields} if attributes else fields
            line = build_line(
                level,
                message,
                timestamp=timestamp,
                attributes=attrs,
                trace_id=trace_id,
                span_id=span_id,
                request_id=request_id,
                exc_info=exc_info,
                service=service,
                environment=environment,
                host=host,
            )
            self._enqueue(line)
        except Exception as exc:
            self._warn_once("build", f"could not record a log line ({type(exc).__name__})")

    def trace(self, message: object, **fields: Any) -> None:
        self.log("trace", message, **fields)

    def debug(self, message: object, **fields: Any) -> None:
        self.log("debug", message, **fields)

    def info(self, message: object, **fields: Any) -> None:
        self.log("info", message, **fields)

    def warning(self, message: object, **fields: Any) -> None:
        self.log("warn", message, **fields)

    warn = warning

    def error(self, message: object, **fields: Any) -> None:
        """``error("...", exc_info=True)`` attaches the exception being handled."""
        self.log("error", message, **fields)

    def critical(self, message: object, **fields: Any) -> None:
        self.log("fatal", message, **fields)

    fatal = critical

    def exception(self, message: object = "", **fields: Any) -> None:
        """Log at ``error`` with the current exception's type, message and traceback.
        Call it inside an ``except`` block; an empty message uses the exception text."""
        fields.setdefault("exc_info", True)
        if not message:
            current = sys.exc_info()[1]
            message = str(current) if current is not None and str(current) else ""
        self.log("error", message, **fields)

    # Delivery control ----------------------------------------------------------

    def flush(self, timeout: float | None = 10.0) -> bool:
        """Send everything queued now. Returns ``True`` when the queue drained (every line
        was accepted, rejected or dropped) within ``timeout`` seconds."""
        if self._sender is None:
            return True
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            if self._thread is None or not self._thread.is_alive():
                return not self._buffer and self._inflight == 0
            self._flush_requested = True
            self._cond.notify_all()
            while self._buffer or self._inflight:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self._cond.wait(remaining)
        return True

    def close(self, timeout: float = ATEXIT_TIMEOUT_S) -> bool:
        """Flush (waiting up to ``timeout`` seconds), stop the sender thread and release
        the HTTP connection pool. Lines logged afterwards are dropped and counted.
        Safe to call more than once. Returns whether everything queued was delivered."""
        with self._cond:
            if self._closed:
                return True
            self._closing = True
        drained = self.flush(timeout)
        with self._cond:
            self._closed = True
            self._abort.set()
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        with self._cond:
            if self._buffer:
                self._counts["dropped_closed"] += len(self._buffer)
                self._buffer.clear()
        if self._http is not None:
            self._http.close()
        if getattr(self, "_atexit_registered", False):
            atexit.unregister(self._atexit_close)
        return drained

    def send_batch(self, logs: Sequence[Mapping[str, Any]]) -> IngestResult:
        """Send ``logs`` now, on the calling thread, bypassing the queue, and return the
        API's :class:`IngestResult` (``accepted``, ``rejected``, ``event_ids`` ...).

        Each item is a ``LogIn``-shaped mapping: ``message`` plus any of ``level``,
        ``timestamp``, ``attributes``, ``trace_id``, ``span_id``, ``request_id``,
        ``exception`` (an exception instance) and per-line ``service``/``environment``/
        ``host``. Unlike the logging methods this raises :class:`IngestError` when the
        batch cannot be delivered, because the caller asked to know."""
        if self._sender is None or self._http is None or self._api_key is None:
            raise IngestError(
                "The client is disabled (no API key)", status=None, code="disabled", retryable=False
            )
        lines = []
        for item in logs:
            kwargs = {k: item[k] for k in _LINE_KEYS if k in item}
            lines.append(
                build_line(
                    item.get("level", "info"),
                    item.get("message", ""),
                    exc_info=item.get("exception"),
                    **kwargs,
                )
            )
        sender = Sender(
            self._http,
            self._api_key,
            max_retries=self._sender.max_retries,
            backoff_base_s=self._sender.backoff_base_s,
            sleep=_blocking_sleep,
        )
        return sender.send(lines, self._defaults())

    @property
    def stats(self) -> Stats:
        with self._cond:
            return Stats(queued=len(self._buffer) + self._inflight, **self._counts)

    def __enter__(self) -> LogMind:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def __repr__(self) -> str:
        # Never print the key, not even a prefix of it.
        return (
            f"LogMind(endpoint={self.endpoint!r}, service={self.service!r}, "
            f"environment={self.environment!r}, enabled={self.enabled})"
        )

    def is_sender_thread(self) -> bool:
        """``True`` on this client's background thread (used to avoid feedback loops
        when the stdlib handler would otherwise capture the SDK's own HTTP logging)."""
        return self._thread is not None and threading.current_thread() is self._thread

    # Internals -----------------------------------------------------------------

    def _defaults(self) -> dict[str, str]:
        out: dict[str, str] = {}
        if self.service:
            out["service"] = self.service
        if self.environment:
            out["environment"] = self.environment
        if self.host:
            out["host"] = self.host
        return out

    def _enqueue(self, line: dict[str, Any]) -> None:
        with self._cond:
            if self._sender is None or self._closing:
                self._counts["dropped_closed"] += 1
                return
            if len(self._buffer) >= self.max_queue:
                self._buffer.popleft()
                self._counts["dropped_queue_full"] += 1
                overflow = True
            else:
                overflow = False
            if not self._buffer:
                self._first_queued_at = time.monotonic()
                self._cond.notify_all()
            self._buffer.append(line)
            if len(self._buffer) >= self.batch_size:
                self._cond.notify_all()
        if overflow:
            self._warn_once(
                "queue_full",
                f"queue full ({self.max_queue} lines); dropping the oldest lines "
                "(see stats.dropped_queue_full)",
            )

    def _take_batch(self) -> list[dict[str, Any]] | None:
        """Block until a batch is due, then take it. ``None`` means stop."""
        with self._cond:
            while True:
                if self._closed:
                    return None
                if self._buffer:
                    due = self._first_queued_at + self.flush_interval_s
                    remaining = due - time.monotonic()
                    if (
                        self._flush_requested
                        or len(self._buffer) >= self.batch_size
                        or remaining <= 0
                    ):
                        count = min(self.batch_size, len(self._buffer))
                        batch = [self._buffer.popleft() for _ in range(count)]
                        self._inflight += count
                        self._first_queued_at = time.monotonic()
                        return batch
                    self._cond.wait(remaining)
                else:
                    self._flush_requested = False
                    self._cond.wait()

    def _run(self) -> None:
        while True:
            batch = self._take_batch()
            if batch is None:
                return
            try:
                self._deliver(batch)
            finally:
                with self._cond:
                    self._inflight -= len(batch)
                    self._cond.notify_all()

    def _deliver(self, batch: list[dict[str, Any]]) -> None:
        assert self._sender is not None
        try:
            result = self._sender.send(batch, self._defaults())
        except IngestError as exc:
            self._count("dropped_failed", len(batch))
            if exc.retryable:
                self._warn_once(
                    "unreachable",
                    f"dropped {len(batch)} lines after retries: {exc.message}",
                )
            else:
                self._warn_once(
                    f"http_{exc.status}_{exc.code}",
                    f"dropped {len(batch)} lines: {exc.message}",
                )
            return
        except Exception as exc:  # a bug must never kill the sender thread
            self._count("dropped_failed", len(batch))
            self._warn_once("unexpected", f"dropped {len(batch)} lines ({type(exc).__name__})")
            return
        with self._cond:
            self._counts["batches_sent"] += 1
            self._counts["accepted"] += result.accepted
            self._counts["rejected"] += len(result.rejected)
        if result.rejected:
            first = result.rejected[0]
            self._warn_once(
                "rejected",
                f"LogMind rejected {len(result.rejected)} line(s) in a batch, "
                f"first: {first.reason}",
            )

    def _count(self, key: str, amount: int = 1) -> None:
        with self._cond:
            self._counts[key] += amount

    def _count_retry(self) -> None:
        self._count("retries")

    def _warn_once(self, key: str, message: str) -> None:
        with self._cond:
            if key in self._warned:
                return
            self._warned.add(key)
        try:
            sys.stderr.write(f"[euron-logmind] {message}\n")
        except Exception:  # stderr closed at interpreter shutdown
            return

    def _atexit_close(self) -> None:
        self.close(timeout=ATEXIT_TIMEOUT_S)
