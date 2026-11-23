"""People who sign in to the dashboard. Roles, from least to most power inside an
organisation: ``viewer`` (reads everything, runs investigations), ``admin`` (manages
projects, API keys, alert rules and AI providers), ``owner`` (admin plus user management).
Each account belongs to exactly one organisation, so the role on the user row is the
membership: there is no separate memberships table to keep in sync."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from logmind.core.db import Base, OrgScoped, TimestampMixin, new_id

ROLES = ("viewer", "admin", "owner")


class User(OrgScoped, TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="viewer")
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    session_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


# One account per email address across the install: sign-in needs no organisation picker.
# Enforced in the initial migration with a functional unique index on lower(email).
