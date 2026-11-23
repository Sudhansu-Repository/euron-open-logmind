"""Alert rules and their history (A9).

A rule watches one project's live ingested data: a **threshold** on a metric over a
sliding window (error count, error rate, line count, or lines matching keywords), or an
**anomaly** rule comparing the latest five minutes of errors with the same series' own
baseline (A10). Notification targets are email addresses (Mailpit locally, SES on AWS),
a signed webhook and a Slack incoming webhook; the two URLs and the webhook signing secret
are sealed, never returned. ``alert_history`` is append-only: one row per firing and per
recovery, with the outcome of every delivery.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from logmind.core.db import Base, OrgScoped, TimestampMixin, new_id

KINDS = ("threshold", "anomaly")
METRICS = ("error_count", "error_rate", "log_count", "matching_count")


class AlertRule(OrgScoped, TimestampMixin, Base):
    __tablename__ = "alert_rules"
    __table_args__ = (Index("ix_alert_rules_due", "enabled", "last_evaluated_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    metric: Mapped[str] = mapped_column(String(24), nullable=False, default="error_count")
    query: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    service: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    environment: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    window_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    # Anomaly rules: how many standard deviations, the fewest errors that can count, and
    # how much history forms the baseline.
    sensitivity: Mapped[float] = mapped_column(Float, nullable=False, default=3.0)
    min_count: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    baseline_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    email_to: Mapped[list[str]] = mapped_column(ARRAY(String(320)), nullable=False, default=list)
    webhook_url_sealed: Mapped[bytes | None] = mapped_column(LargeBinary)
    webhook_secret_sealed: Mapped[bytes | None] = mapped_column(LargeBinary)
    slack_url_sealed: Mapped[bytes | None] = mapped_column(LargeBinary)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    state: Mapped[str] = mapped_column(String(8), nullable=False, default="ok")
    last_value: Mapped[float | None] = mapped_column(Float)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class AlertHistory(OrgScoped, Base):
    __tablename__ = "alert_history"
    __table_args__ = (
        Index("ix_alert_history_rule", "rule_id", "at"),
        Index("ix_alert_history_project", "project_id", "at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # "fired", "resolved" or "test".
    event: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float | None] = mapped_column(Float)
    expected: Mapped[float | None] = mapped_column(Float)
    zscore: Mapped[float | None] = mapped_column(Float)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    deliveries: Mapped[list[dict[str, Any]]] = mapped_column(nullable=False, default=list)
