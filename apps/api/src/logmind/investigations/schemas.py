from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from logmind.core.schemas import ApiModel


class InvestigateIn(ApiModel):
    project_id: uuid.UUID
    error_group_id: uuid.UUID | None = Field(
        None, description="The error group to explain; omit to investigate a free question"
    )
    question: str = Field("", max_length=2000)
    window_minutes: int | None = Field(
        None, ge=5, le=1440, description="How far before the incident to look for causes"
    )


class FollowupIn(ApiModel):
    question: str = Field(min_length=3, max_length=2000)


class EvidenceItemOut(ApiModel):
    ref: str
    event_id: uuid.UUID
    timestamp: datetime
    service: str
    level: str
    kind: str
    message: str
    count: int
    last_timestamp: datetime | None


class TurnOut(ApiModel):
    id: uuid.UUID
    seq: int
    question: str
    status: str
    error: str | None
    answer: dict[str, Any] | None
    added_evidence: int
    rejected_citations: int
    grounded: bool | None
    input_tokens: int
    output_tokens: int
    created_at: datetime
    finished_at: datetime | None


class InvestigationSummary(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID
    error_group_id: uuid.UUID | None
    title: str
    question: str
    status: str
    error: str | None
    provider_name: str
    model: str
    evidence_count: int
    raw_lines: int
    raw_tokens_estimate: int
    context_tokens_estimate: int
    input_tokens: int
    output_tokens: int
    rejected_citations: int
    grounded: bool | None
    confidence: float | None = None
    root_cause: str | None = None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class InvestigationOut(InvestigationSummary):
    window_start: datetime | None
    window_end: datetime | None
    incident_start: datetime | None
    report: dict[str, Any] | None
    evidence: list[EvidenceItemOut]
    turns: list[TurnOut]


class CitationCheck(ApiModel):
    ref: str
    event_id: uuid.UUID
    found: bool = Field(description="The line exists in this project's stored logs")
    timestamp_matches: bool
    message_matches: bool
    stored_message: str | None
    verified: bool


class VerifyOut(ApiModel):
    investigation_id: uuid.UUID
    checked: int
    verified: int
    all_verified: bool
    citations: list[CitationCheck]


class UsageDay(ApiModel):
    day: datetime
    input_tokens: int
    output_tokens: int
    calls: int


class UsageOut(ApiModel):
    days: int
    input_tokens: int
    output_tokens: int
    calls: int
    investigations: int
    context_tokens_estimate: int
    raw_tokens_estimate: int
    saved_ratio: float = Field(description="1 - context/raw: the share of raw volume never sent")
    by_day: list[UsageDay]
    by_model: list[dict[str, Any]]
    ingested_lines: int
