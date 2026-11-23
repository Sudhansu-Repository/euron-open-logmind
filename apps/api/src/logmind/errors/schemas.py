from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from logmind.core.schemas import ApiModel


class TrendPoint(ApiModel):
    hour: datetime
    count: int


class ErrorGroupOut(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID
    fingerprint: str
    title: str
    exception_type: str
    culprit: str
    level: str
    services: list[str]
    environments: list[str]
    first_seen: datetime
    last_seen: datetime
    occurrences: int
    sample_event_id: uuid.UUID
    sample_message: str
    status: str
    resolved_at: datetime | None
    regressed_at: datetime | None
    trend: list[TrendPoint] = Field(default_factory=list, description="Hourly counts, last 24 h")


class ErrorGroupPage(ApiModel):
    items: list[ErrorGroupOut]
    total: int


class ErrorGroupUpdate(ApiModel):
    status: Literal["open", "resolved", "ignored"]
