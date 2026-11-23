from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from logmind.analytics import service
from logmind.analytics.schemas import AnomalyOut, OverviewOut
from logmind.auth.dependencies import Viewer
from logmind.core.db import ProjectScope
from logmind.core.deps import ContainerDep, SessionDep
from logmind.core.errors import NotFoundError
from logmind.investigations.models import AiUsage, Investigation
from logmind.investigations.schemas import UsageDay, UsageOut
from logmind.logs.repository import LogFilter, LogRepository
from logmind.projects.dependencies import ProjectQuery
from logmind.projects.repository import ProjectRepository

router = APIRouter(prefix="/api/v1", tags=["analytics"])


@router.get(
    "/analytics/overview", response_model=OverviewOut, summary="Everything the Overview shows"
)
async def overview(
    scope: ProjectQuery,
    session: SessionDep,
    container: ContainerDep,
    hours: Annotated[int, Query(ge=1, le=24 * 7)] = 24,
) -> OverviewOut:
    async def load() -> dict[str, Any]:
        out = await service.overview(container.clickhouse, session, scope, hours)
        return out.model_dump(mode="json")

    payload = await container.rollup_cache.get_or_set(
        f"logmind:overview:{scope.project_id}:{hours}", load
    )
    return OverviewOut.model_validate(payload)


@router.get(
    "/analytics/anomalies",
    response_model=list[AnomalyOut],
    summary="Error spikes against each service's own baseline",
)
async def anomalies(
    scope: ProjectQuery,
    container: ContainerDep,
    hours: Annotated[int, Query(ge=1, le=24 * 7)] = 24,
) -> list[AnomalyOut]:
    return await service.anomalies(container.clickhouse, scope, hours, datetime.now(UTC))


@router.get("/usage", response_model=UsageOut, summary="AI token usage and ingestion volume")
async def usage(
    actor: Viewer,
    session: SessionDep,
    container: ContainerDep,
    project_id: uuid.UUID | None = None,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> UsageOut:
    since = datetime.now(UTC) - timedelta(days=days)
    projects = await ProjectRepository(session).list_in_org(actor.scope, include_archived=True)
    if project_id is not None:
        projects = [p for p in projects if p.id == project_id]
        if not projects:
            raise NotFoundError("Project not found", code="unknown_project")
    ids = [p.id for p in projects]
    base = [AiUsage.org_id == actor.org_id, AiUsage.at >= since, AiUsage.project_id.in_(ids)]
    totals = (
        await session.execute(
            select(
                func.coalesce(func.sum(AiUsage.input_tokens), 0),
                func.coalesce(func.sum(AiUsage.output_tokens), 0),
                func.count(),
                func.coalesce(func.sum(AiUsage.context_tokens_estimate), 0),
                func.coalesce(func.sum(AiUsage.raw_tokens_estimate), 0),
            ).where(*base)
        )
    ).one()
    day = func.date_trunc("day", AiUsage.at)
    by_day = (
        await session.execute(
            select(
                day, func.sum(AiUsage.input_tokens), func.sum(AiUsage.output_tokens), func.count()
            )
            .where(*base)
            .group_by(day)
            .order_by(day)
        )
    ).all()
    by_model = (
        await session.execute(
            select(
                AiUsage.provider,
                AiUsage.model,
                func.sum(AiUsage.input_tokens),
                func.sum(AiUsage.output_tokens),
                func.count(),
            )
            .where(*base)
            .group_by(AiUsage.provider, AiUsage.model)
        )
    ).all()
    investigations = await session.scalar(
        select(func.count()).where(
            Investigation.org_id == actor.org_id,
            Investigation.created_at >= since,
            Investigation.project_id.in_(ids),
        )
    )
    repo = LogRepository(container.clickhouse)
    lines = 0
    for p in projects:
        lines += await repo.count(
            ProjectScope(actor.org_id, p.id), LogFilter(start=since, end=datetime.now(UTC))
        )
    context, raw = int(totals[3]), int(totals[4])
    return UsageOut(
        days=days,
        input_tokens=int(totals[0]),
        output_tokens=int(totals[1]),
        calls=int(totals[2]),
        investigations=int(investigations or 0),
        context_tokens_estimate=context,
        raw_tokens_estimate=raw,
        saved_ratio=round(1 - context / raw, 4) if raw else 0.0,
        by_day=[
            UsageDay(day=d, input_tokens=int(i or 0), output_tokens=int(o or 0), calls=int(c))
            for d, i, o, c in by_day
        ],
        by_model=[
            {
                "provider": prov,
                "model": model,
                "input_tokens": int(i or 0),
                "output_tokens": int(o or 0),
                "calls": int(c),
            }
            for prov, model, i, o, c in by_model
        ],
        ingested_lines=lines,
    )
