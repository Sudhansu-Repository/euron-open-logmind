from __future__ import annotations

import uuid
from typing import Any

from pydantic import Field

from logmind.core.schemas import ApiModel


class ExceptionIn(ApiModel):
    type: str = Field("", max_length=200, description="e.g. TimeoutError, java.io.IOException")
    message: str = Field("", max_length=4000)
    stacktrace: str = Field("", max_length=64_000)


class LogIn(ApiModel):
    """One log line in LogMind's native shape. Only ``message`` is required."""

    message: str = Field(min_length=1, max_length=1_000_000)
    level: str = Field("info", max_length=16, description="trace, debug, info, warn, error, fatal")
    timestamp: str | int | float | None = Field(
        None, description="ISO 8601, or epoch seconds/ms/us/ns. Defaults to receipt time"
    )
    service: str | None = Field(None, max_length=120)
    environment: str | None = Field(None, max_length=120)
    host: str | None = Field(None, max_length=255)
    attributes: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = Field(None, max_length=64)
    span_id: str | None = Field(None, max_length=32)
    request_id: str | None = Field(None, max_length=128)
    exception: ExceptionIn | None = None


class BatchDefaults(ApiModel):
    service: str | None = Field(None, max_length=120)
    environment: str | None = Field(None, max_length=120)
    host: str | None = Field(None, max_length=255)


class BatchIn(ApiModel):
    logs: list[LogIn] = Field(min_length=1, max_length=10_000)
    defaults: BatchDefaults = Field(default_factory=BatchDefaults)


class RejectedEvent(ApiModel):
    index: int
    reason: str


class IngestResult(ApiModel):
    accepted: int
    rejected: list[RejectedEvent] = Field(default_factory=list)
    redactions: int = Field(0, description="Values redacted across the accepted events")
    error_groups: int = Field(0, description="Error groups created or updated")
    event_ids: list[uuid.UUID] = Field(default_factory=list)
