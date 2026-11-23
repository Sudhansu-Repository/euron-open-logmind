"""The service catalogue, scoped by project."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from logmind.core.db import ProjectScope
from logmind.core.repository import Repository
from logmind.services.models import Service


class ServiceRepository(Repository[Service]):
    model = Service

    async def list_for(self, scope: ProjectScope) -> list[Service]:
        stmt = (
            select(Service)
            .where(Service.org_id == scope.org_id, Service.project_id == scope.project_id)
            .order_by(Service.name)
        )
        return list((await self.session.scalars(stmt)).all())

    async def get_by_name(self, scope: ProjectScope, name: str) -> Service | None:
        stmt = select(Service).where(
            Service.org_id == scope.org_id,
            Service.project_id == scope.project_id,
            Service.name == name,
        )
        return await self.session.scalar(stmt)

    async def touch(self, scope: ProjectScope, seen: dict[str, tuple[datetime, datetime]]) -> None:
        """Register the services one batch carried: one upsert per batch, sorted."""
        if not seen:
            return
        rows = [
            {
                "id": uuid.uuid4(),
                "org_id": scope.org_id,
                "project_id": scope.project_id,
                "name": name,
                "first_seen_at": first,
                "last_seen_at": last,
            }
            for name, (first, last) in sorted(seen.items())
        ]
        stmt = insert(Service).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_services_name",
            set_={
                "last_seen_at": func.greatest(Service.last_seen_at, stmt.excluded.last_seen_at),
                "first_seen_at": func.least(Service.first_seen_at, stmt.excluded.first_seen_at),
            },
        )
        await self.session.execute(stmt)
