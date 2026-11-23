from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from logmind.auth.dependencies import Viewer
from logmind.core.deps import ContainerDep, SessionDep
from logmind.investigations import service
from logmind.investigations.schemas import (
    FollowupIn,
    InvestigateIn,
    InvestigationOut,
    InvestigationSummary,
    TurnOut,
    VerifyOut,
)
from logmind.projects.dependencies import ProjectQuery

router = APIRouter(prefix="/api/v1/ai", tags=["ai investigations"])


@router.post(
    "/investigate",
    response_model=InvestigationSummary,
    status_code=202,
    summary="Start an AI root cause investigation (runs in the background)",
)
async def investigate(
    body: InvestigateIn, actor: Viewer, session: SessionDep, container: ContainerDep
) -> InvestigationSummary:
    inv = await service.create_investigation(container, session, actor, body)
    return service.summary(inv)


@router.get(
    "/investigations", response_model=list[InvestigationSummary], summary="List investigations"
)
async def list_investigations(
    scope: ProjectQuery,
    session: SessionDep,
    error_group_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[InvestigationSummary]:
    return await service.list_investigations(
        session, scope, error_group_id=error_group_id, limit=limit
    )


@router.get(
    "/investigations/{investigation_id}",
    response_model=InvestigationOut,
    summary="An investigation: report, cited evidence, follow-ups, token usage",
)
async def get_investigation(
    investigation_id: uuid.UUID, actor: Viewer, session: SessionDep, container: ContainerDep
) -> InvestigationOut:
    return await service.investigation_out(container, session, actor.scope, investigation_id)


@router.post(
    "/investigations/{investigation_id}/followup",
    response_model=TurnOut,
    status_code=202,
    summary="Ask a follow-up question, answered over the same evidence",
)
async def followup(
    investigation_id: uuid.UUID, body: FollowupIn, actor: Viewer, session: SessionDep
) -> TurnOut:
    turn = await service.create_followup(session, actor, investigation_id, body.question)
    return TurnOut.model_validate(turn)


@router.get(
    "/investigations/{investigation_id}/verify",
    response_model=VerifyOut,
    summary="Re-read every cited log line from storage and compare it with the report",
)
async def verify(
    investigation_id: uuid.UUID, actor: Viewer, session: SessionDep, container: ContainerDep
) -> VerifyOut:
    return await service.verify(container, session, actor.scope, investigation_id)
