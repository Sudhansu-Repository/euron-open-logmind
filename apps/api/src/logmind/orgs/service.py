from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from logmind.audit.service import Actor, audit
from logmind.core.db import OrgScope
from logmind.core.errors import NotFoundError
from logmind.orgs.models import Organization
from logmind.orgs.schemas import OrgUpdate


async def get_org(session: AsyncSession, scope: OrgScope) -> Organization:
    # Organization itself is not OrgScoped (an org does not have an org_id): the scope's
    # own org_id IS the primary key here, so this is a plain by-id lookup, not a
    # structural tenant filter.
    org = await session.get(Organization, scope.org_id)
    if org is None:
        raise NotFoundError("Organization not found")
    return org


async def update_org(
    session: AsyncSession, scope: OrgScope, data: OrgUpdate, actor: Actor
) -> Organization:
    org = await get_org(session, scope)
    org.name = data.name
    audit(session, actor, "org.updated", "organization", org.id, name=org.name)
    await session.commit()
    return org
