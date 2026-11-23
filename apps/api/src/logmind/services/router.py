from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from logmind.core.deps import ContainerDep, SessionDep
from logmind.core.errors import NotFoundError
from logmind.projects.dependencies import ProjectQuery
from logmind.services import service
from logmind.services.schemas import ServiceHealthOut, ServicesOut

router = APIRouter(prefix="/api/v1/services", tags=["services"])


@router.get("", response_model=ServicesOut, summary="Health of every service, from its logs")
async def list_services(
    scope: ProjectQuery,
    session: SessionDep,
    container: ContainerDep,
    hours: Annotated[int, Query(ge=1, le=24 * 30)] = 24,
) -> ServicesOut:
    async def load() -> dict[str, Any]:
        out = await service.health(container.clickhouse, session, scope, hours)
        return out.model_dump(mode="json")

    payload = await container.rollup_cache.get_or_set(
        f"logmind:svc:{scope.project_id}:{hours}", load
    )
    return ServicesOut.model_validate(payload)


@router.get("/{name}", response_model=ServiceHealthOut, summary="Health of one service")
async def get_service(
    name: str,
    scope: ProjectQuery,
    session: SessionDep,
    container: ContainerDep,
    hours: Annotated[int, Query(ge=1, le=24 * 30)] = 24,
) -> ServiceHealthOut:
    out = await service.health(container.clickhouse, session, scope, hours, name=name)
    if not out.services:
        raise NotFoundError("No service with this name has sent logs to the project")
    return out.services[0]
