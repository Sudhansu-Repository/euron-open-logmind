from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from logmind.core.net import check_url
from logmind.core.schemas import ApiModel, Email

Kind = Literal["threshold", "anomaly"]
Metric = Literal["error_count", "error_rate", "log_count", "matching_count"]


class _Targets(ApiModel):
    @field_validator("webhook_url", "slack_url", check_fields=False)
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        return check_url(v, "url") if v else v


class AlertIn(_Targets):
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    kind: Kind = "threshold"
    metric: Metric = "error_count"
    query: str = Field("", max_length=300, description="Keywords, for matching_count")
    service: str = Field("", max_length=64, description="Only this service (empty: all)")
    environment: str = Field("", max_length=64)
    threshold: float = Field(0.0, ge=0)
    window_minutes: int = Field(5, ge=1, le=1440)
    sensitivity: float = Field(3.0, ge=1.5, le=20)
    min_count: int = Field(10, ge=1, le=1_000_000)
    baseline_hours: int = Field(24, ge=1, le=24 * 14)
    email_to: list[Email] = Field(default_factory=list, max_length=20)
    webhook_url: str | None = Field(None, max_length=1000)
    slack_url: str | None = Field(None, max_length=1000)
    cooldown_minutes: int = Field(30, ge=1, le=1440)
    enabled: bool = True

    @model_validator(mode="after")
    def _shape(self) -> AlertIn:
        if not (self.email_to or self.webhook_url or self.slack_url):
            raise ValueError("Add at least one notification target: email, webhook or Slack")
        if self.kind == "threshold" and self.metric == "matching_count" and not self.query.strip():
            raise ValueError("A matching_count rule needs keywords in query")
        return self


class AlertUpdate(_Targets):
    name: str | None = Field(None, min_length=1, max_length=120)
    query: str | None = Field(None, max_length=300)
    service: str | None = Field(None, max_length=64)
    environment: str | None = Field(None, max_length=64)
    threshold: float | None = Field(None, ge=0)
    window_minutes: int | None = Field(None, ge=1, le=1440)
    sensitivity: float | None = Field(None, ge=1.5, le=20)
    min_count: int | None = Field(None, ge=1, le=1_000_000)
    baseline_hours: int | None = Field(None, ge=1, le=24 * 14)
    email_to: list[Email] | None = Field(None, max_length=20)
    webhook_url: str | None = Field(None, max_length=1000, description="Empty string removes it")
    slack_url: str | None = Field(None, max_length=1000, description="Empty string removes it")
    cooldown_minutes: int | None = Field(None, ge=1, le=1440)
    enabled: bool | None = None


class AlertOut(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    kind: str
    metric: str
    query: str
    service: str
    environment: str
    threshold: float
    window_minutes: int
    sensitivity: float
    min_count: int
    baseline_hours: int
    email_to: list[str]
    has_webhook: bool
    has_slack: bool
    cooldown_minutes: int
    enabled: bool
    state: str
    last_value: float | None
    last_evaluated_at: datetime | None
    last_fired_at: datetime | None
    created_at: datetime


class AlertCreated(AlertOut):
    webhook_secret: str | None = Field(
        None, description="Verifies X-LogMind-Signature. Shown once, at creation"
    )


class AlertHistoryOut(ApiModel):
    id: uuid.UUID
    rule_id: uuid.UUID
    rule_name: str = ""
    at: datetime
    event: str
    value: float
    threshold: float | None
    expected: float | None
    zscore: float | None
    message: str
    deliveries: list[dict[str, Any]]
