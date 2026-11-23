"""Database engine, session factory and the declarative base shared by every domain.

Tenant scoping is structural (A8): every tenant-owned table carries ``org_id`` through
:class:`OrgScoped`, and repositories take an :class:`OrgScope` (or a :class:`ProjectScope`
for project-owned data) and filter with it, so a query that forgets the organisation does
not type-check against the repository API. Never a per-route check, always a structural
filter in the repository layer. The same scope types drive the ClickHouse log repository.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Select, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


def new_id() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    type_annotation_map = {
        dict[str, Any]: JSONB,
        list[str]: JSONB,
        list[Any]: JSONB,
        list[dict[str, Any]]: JSONB,
    }


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OrgScoped:
    """A row owned by one organisation. Deleting the organisation deletes its rows."""

    @declared_attr
    def org_id(cls) -> Mapped[uuid.UUID]:  # noqa: N805 SQLAlchemy declared_attr convention
        return mapped_column(
            UUID(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )


@dataclass(frozen=True, slots=True)
class OrgScope:
    """The organisation a request or a job acts for. Repositories filter every query by it."""

    org_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class ProjectScope:
    """One project inside one organisation: the scope of every log query and every
    project-owned row. Built only from a verified API key or from a project id the
    caller's organisation was checked to own (``projects/dependencies.py``)."""

    org_id: uuid.UUID
    project_id: uuid.UUID

    @property
    def org(self) -> OrgScope:
        return OrgScope(self.org_id)


def scoped[M: OrgScoped](stmt: Select[M], model: type[M], scope: OrgScope) -> Select[M]:
    """Add the structural ``org_id`` filter to a single-entity ``select(Model)``."""
    return stmt.where(model.org_id == scope.org_id)


async def get_scoped[M: OrgScoped](
    session: AsyncSession, model: type[M], scope: OrgScope, id_: Any
) -> M | None:
    """A row by primary key, or ``None`` when it belongs to another organisation."""
    row = await session.get(model, id_)
    if row is None or row.org_id != scope.org_id:
        return None
    return row


class Database:
    """Owns the engine and session factory for one application instance."""

    def __init__(self, url: str, *, pool_size: int = 10, max_overflow: int = 20) -> None:
        self.url = url
        self.engine: AsyncEngine = create_async_engine(
            url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=True,
            pool_recycle=1800,
            hide_parameters=True,
        )
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessionmaker() as session:
            yield session

    async def dispose(self) -> None:
        await self.engine.dispose()


def import_all_models() -> None:
    """Import every domain's models so Base.metadata is complete (Alembic, tests, worker)."""
    from logmind.alerts import models as _alerts  # noqa: F401
    from logmind.audit import models as _audit  # noqa: F401
    from logmind.auth import models as _auth  # noqa: F401
    from logmind.errors import models as _errors  # noqa: F401
    from logmind.investigations import models as _investigations  # noqa: F401
    from logmind.orgs import models as _orgs  # noqa: F401
    from logmind.projects import models as _projects  # noqa: F401
    from logmind.providers import models as _providers  # noqa: F401
    from logmind.services import models as _services  # noqa: F401
