from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from logmind.audit.service import Actor, audit
from logmind.core.db import OrgScope, ProjectScope
from logmind.core.errors import NotFoundError
from logmind.core.security import generate_api_key, key_display
from logmind.core.text import slugify
from logmind.projects.exceptions import UnknownProjectError
from logmind.projects.models import ApiKey, Environment, Project
from logmind.projects.repository import ApiKeyRepository, EnvironmentRepository, ProjectRepository
from logmind.projects.schemas import KeyCreated, KeyIn, KeyOut, ProjectIn, ProjectUpdate


async def _unique_slug(repo: ProjectRepository, scope: OrgScope, name: str) -> str:
    base = slugify(name)
    slug, i = base, 2
    while await repo.by_slug(scope, slug):
        slug, i = f"{base}-{i}", i + 1
    return slug


async def list_projects(
    session: AsyncSession, scope: OrgScope, *, include_archived: bool = False
) -> list[Project]:
    return await ProjectRepository(session).list_in_org(scope, include_archived=include_archived)


async def get_project(session: AsyncSession, scope: OrgScope, project_id: uuid.UUID) -> Project:
    project = await ProjectRepository(session).get_in_org(scope, project_id)
    if project is None:
        raise NotFoundError("Project not found")
    return project


async def create_project(
    session: AsyncSession, scope: OrgScope, data: ProjectIn, actor: Actor
) -> Project:
    repo = ProjectRepository(session)
    project = Project(
        org_id=scope.org_id,
        name=data.name,
        description=data.description,
        retention_days=data.retention_days,
        slug=await _unique_slug(repo, scope, data.name),
    )
    repo.add(project)
    await repo.flush()
    audit(session, actor, "project.created", "project", project.id, name=project.name)
    await session.commit()
    return project


async def update_project(
    session: AsyncSession, scope: OrgScope, project_id: uuid.UUID, data: ProjectUpdate, actor: Actor
) -> Project:
    project = await get_project(session, scope, project_id)
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if value is None and field != "description":
            continue
        setattr(project, field, value)
    audit(
        session,
        actor,
        "project.updated",
        "project",
        project.id,
        **{k: str(v) for k, v in changes.items()},
    )
    await session.commit()
    return project


async def list_environments(session: AsyncSession, scope: ProjectScope) -> list[Environment]:
    return await EnvironmentRepository(session).list_for(scope)


def key_to_out(key: ApiKey) -> KeyOut:
    return KeyOut(
        id=key.id,
        project_id=key.project_id,
        name=key.name,
        prefix=key.prefix,
        display=key_display(key.prefix),
        revoked_at=key.revoked_at,
        last_used_at=key.last_used_at,
        created_at=key.created_at,
    )


async def list_keys(
    session: AsyncSession,
    scope: OrgScope,
    *,
    project_id: uuid.UUID | None = None,
    include_revoked: bool = False,
) -> list[KeyOut]:
    keys = await ApiKeyRepository(session).list_in_org(
        scope, project_id=project_id, include_revoked=include_revoked
    )
    return [key_to_out(k) for k in keys]


async def create_key(
    session: AsyncSession, scope: OrgScope, data: KeyIn, pepper: str, actor: Actor
) -> KeyCreated:
    project = await ProjectRepository(session).get_in_org(scope, data.project_id)
    if project is None or project.archived:
        raise UnknownProjectError("Project does not exist or is archived")
    generated = generate_api_key(pepper)
    repo = ApiKeyRepository(session)
    key = ApiKey(
        org_id=scope.org_id,
        project_id=data.project_id,
        name=data.name,
        prefix=generated.prefix,
        secret_hash=generated.secret_hash,
        created_by=actor.id,
    )
    repo.add(key)
    await repo.flush()
    audit(session, actor, "api_key.created", "api_key", key.id, name=key.name, project=project.slug)
    await session.commit()
    return KeyCreated(**key_to_out(key).model_dump(), key=generated.plaintext)


async def revoke_key(
    session: AsyncSession, scope: OrgScope, key_id: uuid.UUID, actor: Actor
) -> KeyOut:
    key = await ApiKeyRepository(session).get_in_org(scope, key_id)
    if key is None:
        raise NotFoundError("API key not found")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        audit(session, actor, "api_key.revoked", "api_key", key.id, name=key.name)
        await session.commit()
    return key_to_out(key)
