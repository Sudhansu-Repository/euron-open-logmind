"""AI investigations, their follow-up turns, and model token usage.

Both ``ai_investigations`` and ``ai_investigation_turns`` double as the work queue (the
program's Postgres queue pattern): the API inserts a ``queued`` row, a worker claims it
with ``FOR UPDATE SKIP LOCKED`` and a lease, and a reaper requeues rows whose worker
stopped renewing. The evidence pack an investigation reasoned over lives in object
storage (``evidence_key``); the row keeps the counts that prove it was compressed (A4).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from logmind.core.db import Base, OrgScoped, TimestampMixin, new_id

STATUSES = ("queued", "running", "completed", "failed")


class QueueColumns:
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    claimed_by: Mapped[str | None] = mapped_column(String(120))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Investigation(QueueColumns, OrgScoped, TimestampMixin, Base):
    __tablename__ = "ai_investigations"
    __table_args__ = (
        Index("ix_ai_investigations_queue", "status", "created_at"),
        Index("ix_ai_investigations_project", "project_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    error_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("error_groups.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    window_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    incident_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    report: Mapped[dict[str, Any] | None] = mapped_column()
    evidence_key: Mapped[str | None] = mapped_column(String(300))
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    raw_lines: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    raw_tokens_estimate: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    context_tokens_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_citations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    grounded: Mapped[bool | None] = mapped_column(Boolean)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class InvestigationTurn(QueueColumns, OrgScoped, TimestampMixin, Base):
    """A follow-up question on an investigation (A12), answered over the same evidence
    pack plus, when the question needs it, more evidence appended to it."""

    __tablename__ = "ai_investigation_turns"
    __table_args__ = (Index("ix_ai_investigation_turns_queue", "status", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_investigations.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[dict[str, Any] | None] = mapped_column()
    evidence_key: Mapped[str | None] = mapped_column(String(300))
    added_evidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_citations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    grounded: Mapped[bool | None] = mapped_column(Boolean)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class AiUsage(OrgScoped, Base):
    """One row per model call: what it cost in tokens, and what it would have cost
    without evidence selection (``raw_tokens_estimate``)."""

    __tablename__ = "ai_usage"
    __table_args__ = (Index("ix_ai_usage_org_at", "org_id", "at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    investigation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    turn_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    usage_reported: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    context_tokens_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    raw_tokens_estimate: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
