from __future__ import annotations

from datetime import datetime

from pydantic import Field

from logmind.core.schemas import ApiModel


class HealthPoint(ApiModel):
    at: datetime
    total: int
    errors: int


class ServiceHealthOut(ApiModel):
    name: str
    status: str = Field(description="healthy, degraded, critical or silent")
    first_seen_at: datetime
    last_seen_at: datetime
    total: int
    errors: int
    warnings: int
    error_rate: float
    recent_error_rate: float = Field(description="Error rate over the last 15 minutes")
    availability: float = Field(
        description="Share of 5-minute windows with logs whose error rate stayed under 5%"
    )
    anomalies: int
    open_error_groups: int
    series: list[HealthPoint]


class ServicesOut(ApiModel):
    hours: int
    services: list[ServiceHealthOut]
