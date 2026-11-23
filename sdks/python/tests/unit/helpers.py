"""Shared test doubles: an ``httpx.MockTransport`` that records every batch the SDK sends
and answers with scripted responses, so no test touches the network."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from typing import Any

import httpx

from euron_logmind import LogMind

BASE = "http://logmind.test"
API_KEY = "lmk_testprefix_0123456789abcdef"

Responder = Callable[[httpx.Request], httpx.Response]


def accepted(request: httpx.Request) -> httpx.Response:
    logs = json.loads(request.content)["logs"]
    return httpx.Response(
        202,
        json={
            "accepted": len(logs),
            "rejected": [],
            "redactions": 0,
            "error_groups": 0,
            "event_ids": [f"00000000-0000-4000-8000-{i:012d}" for i in range(len(logs))],
        },
    )


class Recorder:
    """Captures requests. ``script`` is consumed one response per request; once it is
    exhausted every request is accepted."""

    def __init__(self, *script: Responder | httpx.Response | Exception) -> None:
        self.requests: list[httpx.Request] = []
        self._script = list(script)
        self._lock = threading.Lock()
        self.event = threading.Event()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            self.requests.append(request)
            step = self._script.pop(0) if self._script else accepted
        self.event.set()
        if isinstance(step, Exception):
            raise step
        if isinstance(step, httpx.Response):
            return step
        return step(request)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    @property
    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]

    @property
    def lines(self) -> list[dict[str, Any]]:
        return [line for body in self.bodies for line in body["logs"]]


def make_client(recorder: Recorder, **kwargs: Any) -> LogMind:
    options: dict[str, Any] = {
        "api_key": API_KEY,
        "endpoint": BASE,
        "service": "checkout",
        "environment": "test",
        "host": "web-1",
        "flush_interval_s": 60.0,
        "backoff_base_s": 0.001,
        "register_atexit": False,
        "transport": recorder.transport,
    }
    options.update(kwargs)
    return LogMind(**options)
