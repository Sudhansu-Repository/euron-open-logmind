from __future__ import annotations

from fastapi import APIRouter

from logmind.auth.dependencies import Admin, Viewer
from logmind.core.deps import SessionDep
from logmind.orgs import service
from logmind.orgs.schemas import OrgOut, OrgUpdate

router = APIRouter(prefix="/api/v1/org", tags=["orgs"])


@router.get("", response_model=OrgOut, summary="Get the current organization")
async def get_org(actor: Viewer, session: SessionDep) -> OrgOut:
    return OrgOut.model_validate(await service.get_org(session, actor.scope))


@router.patch("", response_model=OrgOut, summary="Rename the current organization")
async def update_org(body: OrgUpdate, actor: Admin, session: SessionDep) -> OrgOut:
    return OrgOut.model_validate(await service.update_org(session, actor.scope, body, actor))
