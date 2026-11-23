"""Errors raised by the explicit, synchronous ``send_batch`` path only.

The logging methods (``info``, ``error`` ...) and ``flush``/``close`` never raise: a
logging SDK must not be the reason an application fails. ``send_batch`` is the one call a
caller makes on purpose to learn what happened, so it raises ``IngestError``.
"""

from __future__ import annotations


class LogMindError(Exception):
    """Base class for every error this SDK raises."""


class IngestError(LogMindError):
    """A batch could not be delivered.

    ``status`` is the HTTP status (``None`` for a transport failure such as a refused
    connection or a timeout), ``code`` the API's error code when it sent one, and
    ``retryable`` whether the SDK would retry it (429, 408, 5xx, transport errors)."""

    def __init__(self, message: str, *, status: int | None, code: str, retryable: bool) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.retryable = retryable

    def __repr__(self) -> str:
        return f"IngestError(status={self.status!r}, code={self.code!r}, message={self.message!r})"
