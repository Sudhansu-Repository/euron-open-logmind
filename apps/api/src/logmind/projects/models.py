"""Projects (the scope of an API key, of every log line and of every error group),
their environments and their API keys.

A project carries the settings ingestion needs on every request: retention and the
redaction policy (A7). Both are read through the config cache, never per request from
Postgres.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from logmind.core.db import Base, OrgScoped, TimestampMixin, new_id

DEFAULT_REDACTION_CATEGORIES = ["credential", "email", "payment_card", "government_id", "phone"]


class Project(OrgScoped, TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("org_id", "slug", name="uq_projects_org_slug"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Log lines older than this are deleted by the worker's retention task.
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    # A7: on by default. When on, every message, attribute value and stack trace is
    # scanned and matching values are replaced before anything is stored.
    redaction_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    redaction_categories: Mapped[list[str]] = mapped_column(
        nullable=False, default=lambda: list(DEFAULT_REDACTION_CATEGORIES)
    )
    # Extra per-project patterns: [{"name": str, "pattern": str}].
    redaction_custom: Mapped[list[dict[str, Any]]] = mapped_column(nullable=False, default=list)
    # "mask" writes [REDACTED:category]; "hash" writes a short keyed hash, so equal values
    # stay correlatable across lines without being readable.
    redaction_mode: Mapped[str] = mapped_column(String(8), nullable=False, default="mask")
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Environment(OrgScoped, Base):
    """An environment name seen on this project's logs (registered on first sight)."""

    __tablename__ = "environments"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_environments_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ApiKey(OrgScoped, TimestampMixin, Base):
    __tablename__ = "api_keys"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
