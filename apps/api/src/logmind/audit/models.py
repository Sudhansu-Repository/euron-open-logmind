"""The audit_log table: append-only, never edited or deleted (enforced by a database
trigger installed in the initial migration, same pattern as the program's other
projects)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from logmind.core.db import Base, OrgScoped


class AuditLog(OrgScoped, Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64))
    actor_name: Mapped[str | None] = mapped_column(String(320))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    uuid_id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, nullable=False, unique=True)
