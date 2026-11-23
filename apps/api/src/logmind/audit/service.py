"""``audit()`` adds a record to the caller's session, so it commits (or rolls back) with
the change it describes: a change without its audit record cannot be committed."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import orjson
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logmind.audit.models import AuditLog
from logmind.core.db import OrgScope


@dataclass(frozen=True, slots=True)
class Actor:
    """Who did something: a person (by role) or a project API key. Always scoped to one
    organisation."""

    org_id: uuid.UUID
    id: uuid.UUID | None
    email: str | None
    role: str
    ip: str | None = None
    kind: str = "user"
    project_id: uuid.UUID | None = None

    @property
    def scope(self) -> OrgScope:
        return OrgScope(self.org_id)

    @property
    def label(self) -> str:
        return self.email or self.kind


def system_actor(org_id: uuid.UUID, name: str = "system") -> Actor:
    return Actor(org_id, None, name, "system", kind="system")


def _json_safe(value: Any) -> Any:
    return orjson.loads(orjson.dumps(value, default=str))


def audit(
    session: AsyncSession,
    actor: Actor,
    action: str,
    target_type: str | None = None,
    target_id: object | None = None,
    /,
    **details: Any,
) -> None:
    session.add(
        AuditLog(
            org_id=actor.org_id,
            actor_type=actor.kind,
            actor_id=str(actor.id) if actor.id else None,
            actor_name=actor.label,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            details=_json_safe(details),
            ip=actor.ip,
        )
    )


async def list_entries(
    session: AsyncSession,
    scope: OrgScope,
    *,
    after_id: int | None,
    limit: int,
    action: str | None = None,
) -> list[AuditLog]:
    """Newest first, keyset-paginated on id."""
    stmt = (
        select(AuditLog)
        .where(AuditLog.org_id == scope.org_id)
        .order_by(AuditLog.id.desc())
        .limit(limit + 1)
    )
    if after_id is not None:
        stmt = stmt.where(AuditLog.id < after_id)
    if action:
        stmt = stmt.where(AuditLog.action.startswith(action))
    return list((await session.scalars(stmt)).all())
