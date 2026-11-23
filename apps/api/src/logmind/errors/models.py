"""Error groups (A2) and their hourly occurrence counts.

One ``error_groups`` row per distinct fingerprint per project, upserted from every
ingestion batch in one statement (``occurrences`` incremented atomically, ``first_seen``
and ``last_seen`` widened, affected services and environments unioned). The individual
occurrences are the log lines themselves in ClickHouse (``log_events.fingerprint``);
``error_occurrences`` keeps per-hour counts so the dashboard can draw a group's trend
without scanning log lines.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from logmind.core.db import Base, OrgScoped, new_id

STATUSES = ("open", "resolved", "ignored")


class ErrorGroup(OrgScoped, Base):
    __tablename__ = "error_groups"
    __table_args__ = (
        UniqueConstraint("project_id", "fingerprint", name="uq_error_groups_fingerprint"),
        Index("ix_error_groups_project_last_seen", "project_id", "last_seen"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    exception_type: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    culprit: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    level: Mapped[str] = mapped_column(String(8), nullable=False)
    services: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False, default=list)
    environments: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False, default=list)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occurrences: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    sample_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    sample_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when a resolved group receives a new occurrence (a regression).
    regressed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ErrorOccurrence(OrgScoped, Base):
    """Occurrences of one group in one hour."""

    __tablename__ = "error_occurrences"
    __table_args__ = (UniqueConstraint("group_id", "hour", name="uq_error_occurrences_hour"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("error_groups.id", ondelete="CASCADE"), nullable=False
    )
    hour: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
