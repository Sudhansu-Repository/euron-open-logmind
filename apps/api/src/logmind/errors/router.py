from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from logmind.auth.dependencies import Admin
from logmind.core.deps import SessionDep
from logmind.errors import service
from logmind.errors.schemas import ErrorGroupOut, ErrorGroupPage, ErrorGroupUpdate
from logmind.projects.dependencies import ProjectQuery

router = APIRouter(prefix="/api/v1/errors", tags=["errors"])


@router.get("", response_model=ErrorGroupPage, summary="List error groups")
async def list_errors(
    scope: ProjectQuery,
    session: SessionDep,
    status: Literal["open", "resolved", "ignored"] | None = None,
    service_: Annotated[str | None, Query(alias="service", max_length=64)] = None,
    environment: Annotated[str | None, Query(max_length=64)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    since_hours: Annotated[int | None, Query(ge=1, le=24 * 400)] = None,
    sort: Literal["last_seen", "first_seen", "occurrences"] = "last_seen",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> ErrorGroupPage:
    return await service.list_groups(
        session,
        scope,
        status=status,
        service=service_,
        environment=environment,
        q=q,
        since_hours=since_hours,
        sort=sort,
        limit=limit,
        offset=offset,
    )


@router.get("/{group_id}", response_model=ErrorGroupOut, summary="One error group")
async def get_error(group_id: uuid.UUID, scope: ProjectQuery, session: SessionDep) -> ErrorGroupOut:
    return await service.group_out(session, scope, group_id)


@router.patch(
    "/{group_id}", response_model=ErrorGroupOut, summary="Resolve, ignore or reopen an error group"
)
async def update_error(
    group_id: uuid.UUID,
    body: ErrorGroupUpdate,
    scope: ProjectQuery,
    actor: Admin,
    session: SessionDep,
) -> ErrorGroupOut:
    return await service.set_status(session, scope, group_id, body.status, actor)
