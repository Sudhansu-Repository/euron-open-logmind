from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from logmind.core.schemas import ApiModel


class LogEventOut(ApiModel):
    event_id: uuid.UUID
    timestamp: datetime
    received_at: datetime
    level: str
    service: str
    environment: str
    host: str
    message: str
    attributes: dict[str, Any]
    trace_id: str
    span_id: str
    request_id: str
    exception_type: str
    stack_trace: str
    fingerprint: str
    redactions: int
    source: str
    error_group_id: uuid.UUID | None = Field(
        None, description="The error group this line belongs to, when it is an error"
    )


class LogPage(ApiModel):
    items: list[LogEventOut]
    next_cursor: str | None = Field(None, description="Pass as ?cursor= for older lines")
    took_ms: float


class HistogramBucket(ApiModel):
    at: datetime
    trace: int = 0
    debug: int = 0
    info: int = 0
    warn: int = 0
    error: int = 0
    fatal: int = 0


class HistogramOut(ApiModel):
    bucket_seconds: int
    buckets: list[HistogramBucket]
    total: int


class FacetValue(ApiModel):
    value: str
    count: int


class FacetsOut(ApiModel):
    services: list[FacetValue]
    environments: list[FacetValue]
    levels: list[FacetValue]


class LogContextOut(ApiModel):
    event: LogEventOut
    before: list[LogEventOut]
    after: list[LogEventOut]
    same_trace: list[LogEventOut]
