"""Services: every distinct ``service`` name a project's logs carry, registered on first
sight by ingestion. The health numbers themselves are computed from the ClickHouse rollup
(``services/service.py``); this table is the catalogue, with first and last seen times."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from logmind.core.db import Base, OrgScoped, new_id


class Service(OrgScoped, Base):
    __tablename__ = "services"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_services_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
