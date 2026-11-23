"""How a request comes to act for one project.

* **Ingestion** (the SDKs, the HTTP API, OpenTelemetry exporters) authenticates with a
  project API key, ``Authorization: Bearer lmk_<prefix>_<secret>`` (or ``x-api-key``). The
  key alone resolves the organisation and the project; nothing the client sends can name
  another. Lookups go through the config cache, so a busy ingestion path does not query
  Postgres per request; revoking a key invalidates the cache cluster-wide.
* **Dashboard** routes take ``project_id`` as a query parameter, and :func:`project_scope`
  checks that the signed-in user's organisation owns it before building the
  :class:`ProjectScope` every repository then filters by (A8).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends, Query, Request
from sqlalchemy import update

from logmind.auth.dependencies import Viewer
from logmind.core.db import ProjectScope
from logmind.core.deps import ContainerDep, SessionDep
from logmind.core.errors import AuthenticationError, NotFoundError
from logmind.core.security import constant_time_equals, hash_key_secret, parse_api_key
from logmind.projects.models import ApiKey
from logmind.projects.repository import ApiKeyRepository, ProjectRepository
from logmind.redaction.engine import Redactor, compile_custom

SEEN_EVERY = timedelta(minutes=1)


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    """An immutable snapshot of what ingestion needs, safe to cache across requests."""

    org_id: uuid.UUID
    project_id: uuid.UUID
    api_key_id: uuid.UUID
    secret_hash: str
    revoked: bool
    archived: bool
    retention_days: int
    redactor: Redactor
    last_used_at: datetime | None

    @property
    def scope(self) -> ProjectScope:
        return ProjectScope(self.org_id, self.project_id)


def build_redactor(project: Any, hash_key: str) -> Redactor:
    return Redactor(
        enabled=bool(project.redaction_enabled),
        categories=list(project.redaction_categories or []),
        custom=compile_custom(list(project.redaction_custom or [])),
        mode=str(project.redaction_mode),
        hash_key=f"{hash_key}:{project.id}",
    )


def _presented_key(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return request.headers.get("x-api-key") or None


async def project_config(
    request: Request, container: ContainerDep, session: SessionDep
) -> ProjectConfig:
    raw = _presented_key(request)
    if not raw:
        raise AuthenticationError(
            "Send a project API key: Authorization: Bearer lmk_<prefix>_<secret>",
            code="api_key_required",
        )
    parsed = parse_api_key(raw)
    if parsed is None:
        raise AuthenticationError("The API key is malformed", code="invalid_api_key")
    prefix, secret = parsed

    async def load() -> ProjectConfig | None:
        key = await ApiKeyRepository(session).by_prefix(prefix)
        if key is None:
            return None
        project = await ProjectRepository(session).get(key.project_id)
        if project is None or project.org_id != key.org_id:
            return None
        return ProjectConfig(
            org_id=key.org_id,
            project_id=key.project_id,
            api_key_id=key.id,
            secret_hash=key.secret_hash,
            revoked=key.revoked_at is not None,
            archived=project.archived,
            retention_days=project.retention_days,
            redactor=build_redactor(project, container.settings.api_key_pepper),
            last_used_at=key.last_used_at,
        )

    config = await container.config_cache.get(f"key:{prefix}", load)
    expected = hash_key_secret(secret, container.settings.api_key_pepper)
    if config is None or config.revoked or not constant_time_equals(config.secret_hash, expected):
        raise AuthenticationError("The API key is invalid or revoked", code="invalid_api_key")
    if config.archived:
        raise AuthenticationError(
            "This project is archived; unarchive it in Settings to send logs again",
            code="project_archived",
        )
    now = datetime.now(UTC)
    if config.last_used_at is None or now - config.last_used_at > SEEN_EVERY:
        # Throttled to once a minute per key and done as a plain UPDATE, so the hot path
        # never loads the row just to stamp it.
        await session.execute(
            update(ApiKey).where(ApiKey.id == config.api_key_id).values(last_used_at=now)
        )
        await session.commit()
        object.__setattr__(config, "last_used_at", now)
    return config


ProjectKey = Annotated[ProjectConfig, Depends(project_config)]


async def project_scope(
    actor: Viewer,
    session: SessionDep,
    project_id: Annotated[uuid.UUID, Query(description="The project to act on")],
) -> ProjectScope:
    project = await ProjectRepository(session).get_in_org(actor.scope, project_id)
    if project is None:
        raise NotFoundError("Project not found", code="unknown_project")
    return ProjectScope(actor.org_id, project.id)


ProjectQuery = Annotated[ProjectScope, Depends(project_scope)]
