"""Error Intelligence reads: grouped errors with first and last seen, occurrence counts,
affected services and environments, hourly trends; and status changes (resolve, ignore,
reopen). No AI involved (A5)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from logmind.audit.service import Actor, audit
from logmind.core.db import ProjectScope
from logmind.core.errors import NotFoundError
from logmind.errors.models import ErrorGroup
from logmind.errors.repository import ErrorGroupRepository
from logmind.errors.schemas import ErrorGroupOut, ErrorGroupPage, TrendPoint

TREND_HOURS = 24


def _out(group: ErrorGroup, trend: list[tuple[datetime, int]]) -> ErrorGroupOut:
    out = ErrorGroupOut.model_validate(group)
    out.trend = [TrendPoint(hour=h, count=n) for h, n in trend]
    return out


async def list_groups(
    session: AsyncSession,
    scope: ProjectScope,
    *,
    status: str | None,
    service: str | None,
    environment: str | None,
    q: str | None,
    since_hours: int | None,
    sort: str,
    limit: int,
    offset: int,
) -> ErrorGroupPage:
    repo = ErrorGroupRepository(session)
    since = datetime.now(UTC) - timedelta(hours=since_hours) if since_hours else None
    groups, total = await repo.search(
        scope,
        status=status,
        service=service,
        environment=environment,
        q=q,
        since=since,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    trend_since = datetime.now(UTC) - timedelta(hours=TREND_HOURS)
    trends = await repo.trends(scope, [g.id for g in groups], trend_since)
    return ErrorGroupPage(items=[_out(g, trends.get(g.id, [])) for g in groups], total=total)


async def get_group(session: AsyncSession, scope: ProjectScope, group_id: uuid.UUID) -> ErrorGroup:
    group = await ErrorGroupRepository(session).get_in(scope, group_id)
    if group is None:
        raise NotFoundError("Error group not found", code="error_group_not_found")
    return group


async def group_out(
    session: AsyncSession, scope: ProjectScope, group_id: uuid.UUID
) -> ErrorGroupOut:
    group = await get_group(session, scope, group_id)
    since = max(group.first_seen, group.last_seen - timedelta(days=7)) - timedelta(hours=1)
    trends = await ErrorGroupRepository(session).trends(scope, [group.id], since)
    return _out(group, trends.get(group.id, []))


async def set_status(
    session: AsyncSession, scope: ProjectScope, group_id: uuid.UUID, status: str, actor: Actor
) -> ErrorGroupOut:
    group = await get_group(session, scope, group_id)
    if group.status != status:
        group.status = status
        group.resolved_at = datetime.now(UTC) if status == "resolved" else None
        audit(session, actor, f"error_group.{status}", "error_group", group.id, title=group.title)
        await session.commit()
    return await group_out(session, scope, group_id)
