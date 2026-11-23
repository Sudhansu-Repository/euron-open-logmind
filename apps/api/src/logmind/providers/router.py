from __future__ import annotations

import uuid

from fastapi import APIRouter, Response

from logmind.auth.dependencies import Admin, Viewer
from logmind.core.deps import ContainerDep, SessionDep
from logmind.providers import service
from logmind.providers.schemas import ProviderCreate, ProviderOut, ProviderTest, ProviderUpdate

router = APIRouter(prefix="/api/v1/ai/providers", tags=["ai providers"])


@router.get("", response_model=list[ProviderOut], summary="List AI providers")
async def list_providers(actor: Viewer, session: SessionDep) -> list[ProviderOut]:
    return [service.provider_out(p) for p in await service.list_providers(session, actor.scope)]


@router.post("", response_model=ProviderOut, status_code=201, summary="Add an AI provider")
async def create_provider(
    body: ProviderCreate, actor: Admin, session: SessionDep, container: ContainerDep
) -> ProviderOut:
    return service.provider_out(await service.create_provider(container, session, actor, body))


@router.patch("/{provider_id}", response_model=ProviderOut, summary="Change an AI provider")
async def update_provider(
    provider_id: uuid.UUID,
    body: ProviderUpdate,
    actor: Admin,
    session: SessionDep,
    container: ContainerDep,
) -> ProviderOut:
    row = await service.update_provider(container, session, actor, provider_id, body)
    return service.provider_out(row)


@router.delete("/{provider_id}", status_code=204, summary="Remove an AI provider")
async def delete_provider(provider_id: uuid.UUID, actor: Admin, session: SessionDep) -> Response:
    await service.delete_provider(session, actor, provider_id)
    return Response(status_code=204)


@router.post(
    "/{provider_id}/test", response_model=ProviderTest, summary="Make one small call to check it"
)
async def test_provider(
    provider_id: uuid.UUID, actor: Admin, session: SessionDep, container: ContainerDep
) -> ProviderTest:
    return await service.test_provider(container, session, actor, provider_id)
