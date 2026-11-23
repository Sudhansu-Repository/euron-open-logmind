"""Error groups. Every read filters by the project scope; the ingestion upsert writes
only rows carrying the scope's own org and project ids."""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Select, UnaryExpression, case, func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import insert

from logmind.core.db import ProjectScope
from logmind.core.repository import Repository
from logmind.errors.models import ErrorGroup, ErrorOccurrence


@dataclass(slots=True)
class GroupDelta:
    """What one ingestion batch adds to one fingerprint."""

    fingerprint: str
    title: str
    exception_type: str
    culprit: str
    level: str
    first_seen: datetime
    last_seen: datetime
    sample_event_id: uuid.UUID
    sample_message: str
    count: int = 0
    services: set[str] = field(default_factory=set)
    environments: set[str] = field(default_factory=set)
    hours: Counter[datetime] = field(default_factory=Counter)


class ErrorGroupRepository(Repository[ErrorGroup]):
    model = ErrorGroup

    def _scoped(self, scope: ProjectScope) -> Select[ErrorGroup]:
        return select(ErrorGroup).where(
            ErrorGroup.org_id == scope.org_id, ErrorGroup.project_id == scope.project_id
        )

    async def upsert(self, scope: ProjectScope, deltas: list[GroupDelta]) -> dict[str, uuid.UUID]:
        """One statement for the whole batch, rows sorted by fingerprint so concurrent
        batches lock in the same order (no deadlocks). Returns fingerprint to group id."""
        if not deltas:
            return {}
        deltas = sorted(deltas, key=lambda d: d.fingerprint)
        rows = [
            {
                "id": uuid.uuid4(),
                "org_id": scope.org_id,
                "project_id": scope.project_id,
                "fingerprint": d.fingerprint,
                "title": d.title,
                "exception_type": d.exception_type,
                "culprit": d.culprit,
                "level": d.level,
                "services": sorted(d.services),
                "environments": sorted(d.environments),
                "first_seen": d.first_seen,
                "last_seen": d.last_seen,
                "occurrences": d.count,
                "sample_event_id": d.sample_event_id,
                "sample_message": d.sample_message,
                "status": "open",
            }
            for d in deltas
        ]
        base = insert(ErrorGroup).values(rows)
        ex = base.excluded
        newer = ex.last_seen >= ErrorGroup.last_seen
        regressed = (ErrorGroup.status == "resolved") & (ex.last_seen > ErrorGroup.resolved_at)
        stmt = base.on_conflict_do_update(
            constraint="uq_error_groups_fingerprint",
            set_={
                "occurrences": ErrorGroup.occurrences + ex.occurrences,
                "first_seen": func.least(ErrorGroup.first_seen, ex.first_seen),
                "last_seen": func.greatest(ErrorGroup.last_seen, ex.last_seen),
                "services": literal_column(
                    "ARRAY(SELECT DISTINCT unnest(error_groups.services || excluded.services))"
                ),
                "environments": literal_column(
                    "ARRAY(SELECT DISTINCT unnest(error_groups.environments "
                    "|| excluded.environments))"
                ),
                "sample_event_id": case(
                    (newer, ex.sample_event_id), else_=ErrorGroup.sample_event_id
                ),
                "sample_message": case((newer, ex.sample_message), else_=ErrorGroup.sample_message),
                "level": case((ex.level == "fatal", "fatal"), else_=ErrorGroup.level),
                "status": case((regressed, "open"), else_=ErrorGroup.status),
                "regressed_at": case((regressed, func.now()), else_=ErrorGroup.regressed_at),
            },
        ).returning(ErrorGroup.id, ErrorGroup.fingerprint)
        result = await self.session.execute(stmt)
        ids = {str(fp): gid for gid, fp in result.all()}
        occ_rows = sorted(
            (
                {"org_id": scope.org_id, "group_id": ids[d.fingerprint], "hour": hour, "count": n}
                for d in deltas
                for hour, n in d.hours.items()
            ),
            key=lambda r: (str(r["group_id"]), r["hour"]),
        )
        if occ_rows:
            occ = insert(ErrorOccurrence).values(occ_rows)
            occ = occ.on_conflict_do_update(
                constraint="uq_error_occurrences_hour",
                set_={"count": ErrorOccurrence.count + occ.excluded.count},
            )
            await self.session.execute(occ)
        return ids

    async def get_in(self, scope: ProjectScope, group_id: uuid.UUID) -> ErrorGroup | None:
        row: ErrorGroup | None = await self.session.scalar(
            self._scoped(scope).where(ErrorGroup.id == group_id)
        )
        return row

    async def search(
        self,
        scope: ProjectScope,
        *,
        status: str | None,
        service: str | None,
        environment: str | None,
        q: str | None,
        since: datetime | None,
        sort: str,
        limit: int,
        offset: int,
    ) -> tuple[list[ErrorGroup], int]:
        stmt = self._scoped(scope)
        if status:
            stmt = stmt.where(ErrorGroup.status == status)
        if service:
            stmt = stmt.where(ErrorGroup.services.contains([service]))
        if environment:
            stmt = stmt.where(ErrorGroup.environments.contains([environment]))
        if since is not None:
            stmt = stmt.where(ErrorGroup.last_seen >= since)
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(ErrorGroup.title).like(like),
                    func.lower(ErrorGroup.culprit).like(like),
                    func.lower(ErrorGroup.sample_message).like(like),
                )
            )
        total = await self.count(stmt)
        columns: dict[str, Any] = {
            "last_seen": ErrorGroup.last_seen,
            "first_seen": ErrorGroup.first_seen,
            "occurrences": ErrorGroup.occurrences,
        }
        order: UnaryExpression[Any] = columns[sort].desc()
        stmt = stmt.order_by(order, ErrorGroup.id).limit(limit).offset(offset)
        return list((await self.session.scalars(stmt)).all()), total

    async def trends(
        self, scope: ProjectScope, group_ids: list[uuid.UUID], since: datetime
    ) -> dict[uuid.UUID, list[tuple[datetime, int]]]:
        """Hourly counts per group since ``since``, for every group in one query."""
        if not group_ids:
            return {}
        stmt = (
            select(ErrorOccurrence.group_id, ErrorOccurrence.hour, ErrorOccurrence.count)
            .where(
                ErrorOccurrence.org_id == scope.org_id,
                ErrorOccurrence.group_id.in_(group_ids),
                ErrorOccurrence.hour >= since,
            )
            .order_by(ErrorOccurrence.hour)
        )
        out: dict[uuid.UUID, list[tuple[datetime, int]]] = {g: [] for g in group_ids}
        for gid, hour, count in (await self.session.execute(stmt)).all():
            out[gid].append((hour, int(count)))
        return out

    async def counts(self, scope: ProjectScope, since: datetime) -> dict[str, int]:
        stmt = (
            select(ErrorGroup.status, func.count())
            .where(
                ErrorGroup.org_id == scope.org_id,
                ErrorGroup.project_id == scope.project_id,
                ErrorGroup.last_seen >= since,
            )
            .group_by(ErrorGroup.status)
        )
        return {str(s): int(n) for s, n in (await self.session.execute(stmt)).all()}

    async def new_since(self, scope: ProjectScope, since: datetime) -> int:
        stmt = select(func.count()).where(
            ErrorGroup.org_id == scope.org_id,
            ErrorGroup.project_id == scope.project_id,
            ErrorGroup.first_seen >= since,
        )
        return int(await self.session.scalar(stmt) or 0)
