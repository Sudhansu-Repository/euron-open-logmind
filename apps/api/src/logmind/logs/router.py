"""Log Explorer and Live Logs.

``GET /api/v1/logs`` searches one project's lines (keyword, service, environment, level,
time range, trace or request id, error group), newest first with keyset pagination.
``GET /api/v1/logs/live`` is a WebSocket that streams lines as they are ingested; it
authenticates with the dashboard session token (``?token=``) because browsers cannot set
headers on a WebSocket, and checks that the token's organisation owns the project.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import datetime
from typing import Annotated, Any

import orjson
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from logmind.auth.models import User
from logmind.core.container import Container
from logmind.core.db import OrgScope
from logmind.core.deps import ContainerDep, SessionDep
from logmind.core.errors import NotFoundError
from logmind.core.hub import project_topic
from logmind.core.security import decode_session
from logmind.errors.repository import ErrorGroupRepository
from logmind.logs import service
from logmind.logs.repository import LogFilter
from logmind.logs.schemas import FacetsOut, HistogramOut, LogContextOut, LogEventOut, LogPage
from logmind.projects.dependencies import ProjectQuery
from logmind.projects.repository import ProjectRepository

router = APIRouter(prefix="/api/v1/logs", tags=["logs"])

PING_S = 25


async def log_filter(
    session: SessionDep,
    scope: ProjectQuery,
    q: Annotated[str, Query(max_length=500, description="Keywords; every word must match")] = "",
    service_: Annotated[list[str] | None, Query(alias="service")] = None,
    environment: Annotated[list[str] | None, Query()] = None,
    level: Annotated[list[str] | None, Query()] = None,
    start: datetime | None = None,
    end: datetime | None = None,
    trace_id: Annotated[str, Query(max_length=64)] = "",
    request_id: Annotated[str, Query(max_length=128)] = "",
    error_group_id: uuid.UUID | None = None,
) -> LogFilter:
    window_start, window_end = service.resolve_window(start, end)
    fingerprint = ""
    if error_group_id is not None:
        group = await ErrorGroupRepository(session).get_in(scope, error_group_id)
        if group is None:
            raise NotFoundError("Error group not found")
        fingerprint = group.fingerprint
    return LogFilter(
        start=window_start,
        end=window_end,
        q=q.strip(),
        services=service_ or [],
        environments=environment or [],
        levels=level or [],
        trace_id=trace_id.strip(),
        request_id=request_id.strip(),
        fingerprint=fingerprint,
    )


Filter = Annotated[LogFilter, Depends(log_filter)]


@router.get("", response_model=LogPage, summary="Search log lines")
async def search_logs(
    scope: ProjectQuery,
    f: Filter,
    session: SessionDep,
    container: ContainerDep,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> LogPage:
    return await service.search(container.clickhouse, session, scope, f, limit=limit, cursor=cursor)


@router.get("/histogram", response_model=HistogramOut, summary="Line counts by level over time")
async def histogram(scope: ProjectQuery, f: Filter, container: ContainerDep) -> HistogramOut:
    return await service.histogram(container.clickhouse, scope, f)


@router.get("/facets", response_model=FacetsOut, summary="Services, environments and levels")
async def facets(scope: ProjectQuery, f: Filter, container: ContainerDep) -> FacetsOut:
    return await service.facets(container.clickhouse, scope, f)


@router.get("/{event_id}", response_model=LogEventOut, summary="One log line")
async def get_log(
    event_id: uuid.UUID,
    scope: ProjectQuery,
    session: SessionDep,
    container: ContainerDep,
    at: Annotated[datetime | None, Query(description="The line's timestamp, if known")] = None,
) -> LogEventOut:
    return await service.get_event(container.clickhouse, session, scope, event_id, at)


@router.get(
    "/{event_id}/context",
    response_model=LogContextOut,
    summary="A line with its neighbours from the same service and its trace",
)
async def get_context(
    event_id: uuid.UUID,
    scope: ProjectQuery,
    session: SessionDep,
    container: ContainerDep,
    at: datetime | None = None,
    size: Annotated[int, Query(ge=1, le=100)] = 15,
) -> LogContextOut:
    return await service.context(container.clickhouse, session, scope, event_id, at, size)


async def _refuse(ws: WebSocket, code: int) -> None:
    """Accept, then close with an application code, so the browser can tell "sign in
    again" (4401) from "not your project" (4404) from a network error."""
    await ws.accept()
    await ws.close(code=code)


def _matches(item: dict[str, Any], levels: set[str], services: set[str], q: str) -> bool:
    if levels and item.get("level") not in levels:
        return False
    if services and item.get("service") not in services:
        return False
    return not (q and q not in str(item.get("message", "")).lower())


@router.websocket("/live")
async def live(ws: WebSocket) -> None:
    container: Container = ws.app.state.container
    origin = ws.headers.get("origin")
    if origin is not None and origin not in container.settings.cors_origins:
        await _refuse(ws, 4403)
        return
    token = ws.query_params.get("token")
    claims = decode_session(token, container.settings.session_secret) if token else None
    if claims is None:
        await _refuse(ws, 4401)
        return
    try:
        project_id = uuid.UUID(ws.query_params.get("project_id", ""))
    except ValueError:
        await _refuse(ws, 4404)
        return
    async with container.db.sessionmaker() as session:
        user = await session.scalar(
            select(User).where(User.id == claims.user_id, User.org_id == claims.org_id)
        )
        if user is None or user.disabled or user.session_version != claims.session_version:
            await _refuse(ws, 4401)
            return
        project = await ProjectRepository(session).get_in_org(OrgScope(claims.org_id), project_id)
    if project is None:
        await _refuse(ws, 4404)
        return
    levels = {v for v in ws.query_params.getlist("level") if v}
    services = {v for v in ws.query_params.getlist("service") if v}
    q = ws.query_params.get("q", "").strip().lower()

    await ws.accept()
    try:
        async with container.hub.subscribe(project_topic(project.id)) as queue:
            await ws.send_text(orjson.dumps({"type": "ready"}).decode())

            async def outbound() -> None:
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=PING_S)
                    except TimeoutError:
                        await ws.send_text('{"type":"ping"}')
                        continue
                    items = [i for i in event.get("items", []) if _matches(i, levels, services, q)]
                    if items:
                        await ws.send_text(orjson.dumps({"type": "logs", "items": items}).decode())

            async def inbound() -> None:
                while True:
                    await ws.receive_text()  # the client only sends keepalives

            tasks = [asyncio.create_task(outbound()), asyncio.create_task(inbound())]
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
    except WebSocketDisconnect:
        return
