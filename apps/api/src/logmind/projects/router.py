from __future__ import annotations

import uuid

from fastapi import APIRouter

from logmind.auth.dependencies import Admin, Viewer
from logmind.core.deps import ContainerDep, SessionDep
from logmind.core.errors import NotFoundError
from logmind.projects import service
from logmind.projects.dependencies import ProjectQuery, build_redactor
from logmind.projects.repository import ProjectRepository
from logmind.projects.schemas import (
    EnvironmentOut,
    KeyCreated,
    KeyIn,
    KeyOut,
    ProjectIn,
    ProjectOut,
    ProjectUpdate,
    RedactionPreviewIn,
    RedactionPreviewOut,
)
from logmind.redaction.engine import RedactionResult

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])
keys_router = APIRouter(prefix="/api/v1/keys", tags=["projects"])
environments_router = APIRouter(prefix="/api/v1/environments", tags=["projects"])


@router.get("", response_model=list[ProjectOut], summary="List projects")
async def list_projects(
    actor: Viewer, session: SessionDep, include_archived: bool = False
) -> list[ProjectOut]:
    rows = await service.list_projects(session, actor.scope, include_archived=include_archived)
    return [ProjectOut.model_validate(p) for p in rows]


@router.get("/{project_id}", response_model=ProjectOut, summary="Get a project")
async def get_project(project_id: uuid.UUID, actor: Viewer, session: SessionDep) -> ProjectOut:
    return ProjectOut.model_validate(await service.get_project(session, actor.scope, project_id))


@router.post("", response_model=ProjectOut, status_code=201, summary="Create a project")
async def create_project(
    body: ProjectIn, actor: Admin, session: SessionDep, container: ContainerDep
) -> ProjectOut:
    out = await service.create_project(session, actor.scope, body, actor)
    await container.config_cache.invalidate()
    return ProjectOut.model_validate(out)


@router.patch(
    "/{project_id}",
    response_model=ProjectOut,
    summary="Update a project: retention, redaction policy, archive",
)
async def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    actor: Admin,
    session: SessionDep,
    container: ContainerDep,
) -> ProjectOut:
    out = await service.update_project(session, actor.scope, project_id, body, actor)
    await container.config_cache.invalidate()
    return ProjectOut.model_validate(out)


@router.post(
    "/{project_id}/redaction/preview",
    response_model=RedactionPreviewOut,
    summary="Show what the project's redaction policy does to a sample line",
)
async def preview_redaction(
    project_id: uuid.UUID,
    body: RedactionPreviewIn,
    actor: Viewer,
    session: SessionDep,
    container: ContainerDep,
) -> RedactionPreviewOut:
    project = await ProjectRepository(session).get_in_org(actor.scope, project_id)
    if project is None:
        raise NotFoundError("Project not found")
    redactor = build_redactor(project, container.settings.api_key_pepper)
    result = RedactionResult()
    text = redactor.redact_text(body.text, result)
    return RedactionPreviewOut(redacted=text, counts=dict(result.counts))


@environments_router.get(
    "", response_model=list[EnvironmentOut], summary="Environments seen on a project's logs"
)
async def list_environments(scope: ProjectQuery, session: SessionDep) -> list[EnvironmentOut]:
    rows = await service.list_environments(session, scope)
    return [EnvironmentOut.model_validate(e) for e in rows]


@keys_router.get("", response_model=list[KeyOut], summary="List API keys")
async def list_keys(
    actor: Viewer,
    session: SessionDep,
    project_id: uuid.UUID | None = None,
    include_revoked: bool = False,
) -> list[KeyOut]:
    return await service.list_keys(
        session, actor.scope, project_id=project_id, include_revoked=include_revoked
    )


@keys_router.post("", response_model=KeyCreated, status_code=201, summary="Create an API key")
async def create_key(
    body: KeyIn, actor: Admin, session: SessionDep, container: ContainerDep
) -> KeyCreated:
    out = await service.create_key(
        session, actor.scope, body, container.settings.api_key_pepper, actor
    )
    await container.config_cache.invalidate()
    return out


@keys_router.delete("/{key_id}", response_model=KeyOut, summary="Revoke an API key")
async def revoke_key(
    key_id: uuid.UUID, actor: Admin, session: SessionDep, container: ContainerDep
) -> KeyOut:
    out = await service.revoke_key(session, actor.scope, key_id, actor)
    await container.config_cache.invalidate()
    return out
