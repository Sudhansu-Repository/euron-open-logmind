from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response

from logmind.alerts import service
from logmind.alerts.schemas import AlertCreated, AlertHistoryOut, AlertIn, AlertOut, AlertUpdate
from logmind.auth.dependencies import Admin, Viewer
from logmind.core.db import ProjectScope
from logmind.core.deps import ContainerDep, SessionDep
from logmind.projects.dependencies import ProjectQuery

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertOut], summary="List alert rules")
async def list_alerts(scope: ProjectQuery, session: SessionDep) -> list[AlertOut]:
    return [service.rule_out(r) for r in await service.list_rules(session, scope)]


@router.post("", response_model=AlertCreated, status_code=201, summary="Create an alert rule")
async def create_alert(
    body: AlertIn, actor: Admin, session: SessionDep, container: ContainerDep
) -> AlertCreated:
    return await service.create_rule(container, session, actor, body)


@router.get(
    "/history", response_model=list[AlertHistoryOut], summary="Recent firings across all rules"
)
async def all_history(
    scope: ProjectQuery, session: SessionDep, limit: Annotated[int, Query(ge=1, le=500)] = 50
) -> list[AlertHistoryOut]:
    return await service.history(session, scope, rule_id=None, limit=limit)


@router.get("/{rule_id}", response_model=AlertOut, summary="One alert rule")
async def get_alert(rule_id: uuid.UUID, actor: Viewer, session: SessionDep) -> AlertOut:
    return service.rule_out(await service.get_rule(session, actor.scope, rule_id))


@router.patch("/{rule_id}", response_model=AlertOut, summary="Change an alert rule")
async def update_alert(
    rule_id: uuid.UUID,
    body: AlertUpdate,
    actor: Admin,
    session: SessionDep,
    container: ContainerDep,
) -> AlertOut:
    return service.rule_out(await service.update_rule(container, session, actor, rule_id, body))


@router.delete("/{rule_id}", status_code=204, summary="Delete an alert rule")
async def delete_alert(rule_id: uuid.UUID, actor: Admin, session: SessionDep) -> Response:
    await service.delete_rule(session, actor, rule_id)
    return Response(status_code=204)


@router.get("/{rule_id}/history", response_model=list[AlertHistoryOut], summary="A rule's firings")
async def rule_history(
    rule_id: uuid.UUID,
    actor: Viewer,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[AlertHistoryOut]:
    rule = await service.get_rule(session, actor.scope, rule_id)
    return await service.history(
        session, ProjectScope(rule.org_id, rule.project_id), rule_id=rule.id, limit=limit
    )


@router.post(
    "/{rule_id}/test",
    response_model=AlertHistoryOut,
    summary="Send a test notification to every target",
)
async def test_alert(
    rule_id: uuid.UUID, actor: Admin, session: SessionDep, container: ContainerDep
) -> AlertHistoryOut:
    return await service.test_rule(container, session, actor, rule_id)
