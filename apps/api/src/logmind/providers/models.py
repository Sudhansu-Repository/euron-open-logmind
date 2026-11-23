"""AI providers: one row per configured model connection for an organisation. The key is
sealed (``core/sealing.py``) under a context bound to the row, never returned by the API.
AI is optional (A5): an organisation with no enabled provider still ingests, searches and
groups errors; only the investigation endpoints explain that a provider is needed."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from logmind.core.db import Base, OrgScoped, TimestampMixin, new_id

PROVIDER_KINDS = ("openai", "anthropic", "gemini", "ollama", "openai_compatible", "mock")


class AiProvider(OrgScoped, TimestampMixin, Base):
    __tablename__ = "ai_providers"
    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_ai_providers_name"),
        CheckConstraint(
            "kind IN ('openai', 'anthropic', 'gemini', 'ollama', 'openai_compatible', 'mock')",
            name="ck_ai_providers_kind",
        ),
        Index(
            "uq_ai_providers_default", "org_id", unique=True, postgresql_where=text("is_default")
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    api_key_sealed: Mapped[bytes | None] = mapped_column(LargeBinary)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    timeout_s: Mapped[float] = mapped_column(Float, nullable=False, default=60.0)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_test_message: Mapped[str | None] = mapped_column(Text)
