"""Projects, environments and API keys. Every query filters by org_id (structural tenant
scoping), except the one prefix lookup that establishes which org a key belongs to."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from logmind.core.db import OrgScope, ProjectScope, get_scoped, scoped
from logmind.core.repository import Repository
from logmind.projects.models import ApiKey, Environment, Project


class ProjectRepository(Repository[Project]):
    model = Project

    async def get_in_org(self, scope: OrgScope, project_id: uuid.UUID) -> Project | None:
        return await get_scoped(self.session, Project, scope, project_id)

    async def list_in_org(
        self, scope: OrgScope, *, include_archived: bool = False
    ) -> list[Project]:
        stmt = scoped(select(Project), Project, scope).order_by(Project.name)
        if not include_archived:
            stmt = stmt.where(Project.archived.is_(False))
        return list((await self.session.scalars(stmt)).all())

    async def by_slug(self, scope: OrgScope, slug: str) -> Project | None:
        stmt = scoped(select(Project), Project, scope).where(Project.slug == slug)
        return await self.session.scalar(stmt)

    async def list_all_active(self) -> list[Project]:
        """Every active project across every org: only for the worker's retention task,
        which then acts on each project through that project's own scope."""
        stmt = select(Project).where(Project.archived.is_(False))
        return list((await self.session.scalars(stmt)).all())


class EnvironmentRepository(Repository[Environment]):
    model = Environment

    async def list_for(self, scope: ProjectScope) -> list[Environment]:
        stmt = (
            select(Environment)
            .where(Environment.org_id == scope.org_id, Environment.project_id == scope.project_id)
            .order_by(Environment.name)
        )
        return list((await self.session.scalars(stmt)).all())

    async def touch(self, scope: ProjectScope, seen: dict[str, tuple[datetime, datetime]]) -> None:
        """Register environments seen in one batch: one upsert statement per batch."""
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
            for name, (first, last) in seen.items()
        ]
        stmt = insert(Environment).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_environments_name",
            set_={
                "last_seen_at": func.greatest(Environment.last_seen_at, stmt.excluded.last_seen_at),
                "first_seen_at": func.least(Environment.first_seen_at, stmt.excluded.first_seen_at),
            },
        )
        await self.session.execute(stmt)


class ApiKeyRepository(Repository[ApiKey]):
    model = ApiKey

    async def get_in_org(self, scope: OrgScope, key_id: uuid.UUID) -> ApiKey | None:
        return await get_scoped(self.session, ApiKey, scope, key_id)

    async def list_in_org(
        self, scope: OrgScope, *, project_id: uuid.UUID | None = None, include_revoked: bool = False
    ) -> list[ApiKey]:
        stmt = scoped(select(ApiKey), ApiKey, scope).order_by(ApiKey.created_at.desc())
        if project_id is not None:
            stmt = stmt.where(ApiKey.project_id == project_id)
        if not include_revoked:
            stmt = stmt.where(ApiKey.revoked_at.is_(None))
        return list((await self.session.scalars(stmt)).all())

    async def by_prefix(self, prefix: str) -> ApiKey | None:
        """Not org-scoped: this is the lookup that *establishes* which org a request
        belongs to, from the key alone. Every subsequent query in the request uses the
        resolved project's scope."""
        return await self.session.scalar(select(ApiKey).where(ApiKey.prefix == prefix))
