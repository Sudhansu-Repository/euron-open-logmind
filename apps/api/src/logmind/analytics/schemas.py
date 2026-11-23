from __future__ import annotations

from datetime import datetime

from pydantic import Field

from logmind.alerts.schemas import AlertHistoryOut
from logmind.core.schemas import ApiModel
from logmind.errors.schemas import ErrorGroupOut
from logmind.investigations.schemas import InvestigationSummary
from logmind.logs.schemas import HistogramOut


class AnomalyOut(ApiModel):
    at: datetime
    service: str
    value: int = Field(description="Errors in the five-minute window")
    expected: float = Field(description="The baseline mean for the window")
    zscore: float


class ServiceSummary(ApiModel):
    name: str
    status: str
    total: int
    errors: int
    error_rate: float


class OverviewOut(ApiModel):
    hours: int
    lines: int
    lines_previous: int
    errors: int
    errors_previous: int
    warnings: int
    error_rate: float
    redactions: int
    open_error_groups: int
    new_error_groups: int
    histogram: HistogramOut
    top_errors: list[ErrorGroupOut]
    services: list[ServiceSummary]
    anomalies: list[AnomalyOut]
    investigations: list[InvestigationSummary]
    alerts: list[AlertHistoryOut]
    firing_alerts: int
    ai_tokens_30d: int
    ai_provider_configured: bool
