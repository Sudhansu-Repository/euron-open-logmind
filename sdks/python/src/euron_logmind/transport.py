"""Delivery of one batch to ``POST {endpoint}/api/v1/logs/batch``, with retries.

Retried: HTTP 408, 429 and 5xx, and transport errors (connection refused, DNS, timeouts),
with exponential backoff and jitter, honouring ``Retry-After``. Not retried: every other
4xx (a bad or revoked key, a malformed body), because sending the same request again cannot
succeed. A 413 is answered by splitting the batch in half and sending each half.
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from euron_logmind._version import SDK_HEADER, __version__
from euron_logmind.errors import IngestError
from euron_logmind.models import MAX_BATCH, IngestResult

BATCH_PATH = "/api/v1/logs/batch"
MAX_BACKOFF_S = 30.0
MAX_RETRY_AFTER_S = 60.0


def parse_retry_after(value: str | None, now: datetime | None = None) -> float | None:
    """Seconds to wait from a ``Retry-After`` header (delta seconds or an HTTP date)."""
    if not value:
        return None
    value = value.strip()
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        seconds = (when - (now or datetime.now(timezone.utc))).total_seconds()
    if seconds != seconds:  # NaN
        return None
    return max(0.0, min(seconds, MAX_RETRY_AFTER_S))


def backoff_delay(
    attempt: int,
    base_s: float,
    retry_after: float | None = None,
    rand: Callable[[], float] = random.random,
) -> float:
    """The wait before retry number ``attempt + 1``.

    ``Retry-After`` wins when the server sent one. Otherwise ``base * 2**attempt`` capped
    at 30 s, with jitter that keeps it between half and the full value, so many clients
    that failed together do not all come back in the same instant."""
    if retry_after is not None:
        return retry_after
    ceiling = min(MAX_BACKOFF_S, base_s * (2.0**attempt))
    return ceiling / 2 + rand() * ceiling / 2


def _error_from_response(resp: httpx.Response) -> IngestError:
    status = resp.status_code
    code = f"http_{status}"
    message = resp.reason_phrase or "request failed"
    try:
        body = resp.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        code = str(body["error"].get("code") or code)
        message = str(body["error"].get("message") or message)
    retryable = status in (408, 429) or status >= 500
    return IngestError(
        f"LogMind answered HTTP {status} ({code}): {message}",
        status=status,
        code=code,
        retryable=retryable,
    )


def encode_body(lines: list[dict[str, Any]], defaults: dict[str, str]) -> bytes:
    return json.dumps(
        {"logs": lines, "defaults": defaults}, ensure_ascii=False, default=str
    ).encode("utf-8")


class Sender:
    """Posts batches. ``sleep(seconds)`` returns ``True`` when the wait was cut short
    because the client is shutting down, which stops further retries."""

    def __init__(
        self,
        http: httpx.Client,
        api_key: str,
        *,
        max_retries: int,
        backoff_base_s: float,
        sleep: Callable[[float], bool],
        on_retry: Callable[[], None] = lambda: None,
    ) -> None:
        self._http = http
        self._headers = {
            "authorization": f"Bearer {api_key}",
            "content-type": "application/json",
            "x-logmind-sdk": SDK_HEADER,
            "user-agent": f"euron-logmind-python/{__version__}",
        }
        self.max_retries = max(0, max_retries)
        self.backoff_base_s = backoff_base_s
        self._sleep = sleep
        self._on_retry = on_retry

    def send(self, lines: list[dict[str, Any]], defaults: dict[str, str]) -> IngestResult:
        """Deliver ``lines`` (any count; split into requests of at most 1000) or raise
        :class:`IngestError` once retries are exhausted or the error is not retryable."""
        if len(lines) <= MAX_BATCH:
            return self._send_chunk(lines, defaults)
        results: list[IngestResult] = []
        offsets: list[int] = []
        for start in range(0, len(lines), MAX_BATCH):
            results.append(self._send_chunk(lines[start : start + MAX_BATCH], defaults))
            offsets.append(start)
        return IngestResult.merge(results, offsets)

    def _send_chunk(self, lines: list[dict[str, Any]], defaults: dict[str, str]) -> IngestResult:
        body = encode_body(lines, defaults)
        attempt = 0
        while True:
            retry_after: float | None = None
            try:
                resp = self._http.post(BATCH_PATH, content=body, headers=self._headers)
            except httpx.HTTPError as exc:
                # The exception text can carry the URL, never a header, so it is safe.
                error = IngestError(
                    f"Could not reach LogMind ({type(exc).__name__}: {exc})",
                    status=None,
                    code="transport_error",
                    retryable=True,
                )
            else:
                if 200 <= resp.status_code < 300:
                    try:
                        payload = resp.json()
                    except ValueError:
                        payload = {"accepted": len(lines)}
                    return IngestResult.from_json(payload)
                if resp.status_code == 413 and len(lines) > 1:
                    half = len(lines) // 2
                    first = self._send_chunk(lines[:half], defaults)
                    second = self._send_chunk(lines[half:], defaults)
                    return IngestResult.merge([first, second], [0, half])
                error = _error_from_response(resp)
                retry_after = parse_retry_after(resp.headers.get("retry-after"))
            if not error.retryable or attempt >= self.max_retries:
                raise error
            delay = backoff_delay(attempt, self.backoff_base_s, retry_after)
            attempt += 1
            self._on_retry()
            if self._sleep(delay):
                raise error
