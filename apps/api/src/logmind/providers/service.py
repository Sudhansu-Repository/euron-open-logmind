"""AI providers: create, change, test, choose the organisation's default.

Keys are sealed with the key sealer (local AES-GCM or KMS) under a context bound to the
provider id, so a sealed value copied to another row does not open. Base URLs never point
at instance metadata (``check_url`` at the boundary, ``resolves_safely`` at call time).
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from logmind.audit.service import Actor, audit
from logmind.core.container import Container
from logmind.core.db import OrgScope, get_scoped
from logmind.core.errors import AppError, ConflictError, NotFoundError
from logmind.core.net import host_of, is_private_host, resolves_safely
from logmind.providers.adapters import (
    DEFAULT_BASE_URLS,
    DEFAULT_MODELS,
    ProviderConfig,
    adapter_for,
)
from logmind.providers.models import AiProvider
from logmind.providers.schemas import ProviderCreate, ProviderOut, ProviderTest, ProviderUpdate
from logmind.providers.types import Message, ModelRequest, ProviderError


class NoProviderError(AppError):
    status_code = 409
    code = "no_ai_provider"


def _ctx(provider_id: uuid.UUID) -> str:
    return f"ai_provider:{provider_id}:api_key"


def provider_out(p: AiProvider) -> ProviderOut:
    return ProviderOut(
        id=p.id,
        name=p.name,
        kind=p.kind,
        model=p.model,
        base_url=p.base_url,
        has_api_key=p.api_key_sealed is not None,
        enabled=p.enabled,
        is_default=p.is_default,
        timeout_s=p.timeout_s,
        last_test_at=p.last_test_at,
        last_test_ok=p.last_test_ok,
        last_test_message=p.last_test_message,
        created_at=p.created_at,
    )


async def _check_reachable(container: Container, url: str) -> None:
    allow_private = container.settings.provider_allow_private
    if not allow_private and is_private_host(host_of(url)):
        raise AppError(
            "The provider URL is a private address, which this deployment does not allow "
            "(PROVIDER_ALLOW_PRIVATE=false)",
            code="provider_private",
        )
    if not await resolves_safely(url, allow_private=allow_private):
        raise AppError(
            "The provider URL resolves to a forbidden address", code="provider_forbidden"
        )


async def config_of(container: Container, p: AiProvider) -> ProviderConfig:
    key = (
        await container.sealer.open(p.api_key_sealed, _ctx(p.id))
        if p.api_key_sealed is not None
        else None
    )
    if p.kind != "mock":
        await _check_reachable(container, p.base_url)
    return ProviderConfig(
        kind=p.kind,
        base_url=p.base_url,
        api_key=key,
        timeout_s=min(p.timeout_s, container.settings.model_timeout_s),
    )


async def list_providers(session: AsyncSession, scope: OrgScope) -> list[AiProvider]:
    rows = await session.scalars(
        select(AiProvider)
        .where(AiProvider.org_id == scope.org_id)
        .order_by(AiProvider.is_default.desc(), AiProvider.name)
    )
    return list(rows.all())


async def get_provider(
    session: AsyncSession, scope: OrgScope, provider_id: uuid.UUID
) -> AiProvider:
    row = await get_scoped(session, AiProvider, scope, provider_id)
    if row is None:
        raise NotFoundError("AI provider not found")
    return row


async def default_provider(session: AsyncSession, scope: OrgScope) -> AiProvider:
    """The organisation's default enabled provider, else its oldest enabled one."""
    row = await session.scalar(
        select(AiProvider)
        .where(AiProvider.org_id == scope.org_id, AiProvider.enabled.is_(True))
        .order_by(AiProvider.is_default.desc(), AiProvider.created_at)
        .limit(1)
    )
    if row is None:
        raise NoProviderError(
            "AI investigations need an AI provider. An admin adds one under Settings, "
            "AI providers (the built-in mock works without a key). Log search, error "
            "grouping and alerts work without one",
        )
    return row


async def _clear_default(session: AsyncSession, scope: OrgScope) -> None:
    await session.execute(
        update(AiProvider)
        .where(AiProvider.org_id == scope.org_id, AiProvider.is_default.is_(True))
        .values(is_default=False)
    )


async def create_provider(
    container: Container, session: AsyncSession, actor: Actor, data: ProviderCreate
) -> AiProvider:
    scope = actor.scope
    if await session.scalar(
        select(AiProvider.id).where(AiProvider.org_id == scope.org_id, AiProvider.name == data.name)
    ):
        raise ConflictError("A provider with this name exists", code="provider_name_taken")
    base_url = data.base_url or DEFAULT_BASE_URLS.get(data.kind, "")
    if data.kind == "openai_compatible" and not base_url:
        raise AppError("An OpenAI-compatible provider needs its base URL", code="base_url_required")
    if data.kind == "mock":
        base_url = ""
    else:
        await _check_reachable(container, base_url)
    model = data.model.strip() or DEFAULT_MODELS.get(data.kind, "")
    if not model:
        raise AppError("Name the model to use, e.g. llama-3.3-70b", code="model_required")
    first = not await session.scalar(
        select(AiProvider.id).where(AiProvider.org_id == scope.org_id).limit(1)
    )
    row = AiProvider(
        id=uuid.uuid4(),
        org_id=scope.org_id,
        name=data.name,
        kind=data.kind,
        base_url=base_url,
        model=model,
        enabled=data.enabled,
        timeout_s=data.timeout_s,
    )
    if data.is_default or first:
        await _clear_default(session, scope)
        row.is_default = True
    if data.api_key:
        row.api_key_sealed = await container.sealer.seal(data.api_key, _ctx(row.id))
    session.add(row)
    audit(
        session, actor, "ai_provider.created", "ai_provider", row.id, name=row.name, kind=row.kind
    )
    await session.commit()
    return row


async def update_provider(
    container: Container,
    session: AsyncSession,
    actor: Actor,
    provider_id: uuid.UUID,
    data: ProviderUpdate,
) -> AiProvider:
    row = await get_provider(session, actor.scope, provider_id)
    changes = data.model_dump(exclude_unset=True)
    if data.base_url is not None and row.kind != "mock":
        await _check_reachable(container, data.base_url)
        row.base_url = data.base_url
    if data.model is not None:
        row.model = data.model
    if data.timeout_s is not None:
        row.timeout_s = data.timeout_s
    if data.enabled is not None:
        row.enabled = data.enabled
    if data.api_key is not None:
        row.api_key_sealed = (
            await container.sealer.seal(data.api_key, _ctx(row.id)) if data.api_key else None
        )
    if data.is_default:
        await _clear_default(session, actor.scope)
        row.is_default = True
    elif data.is_default is False:
        row.is_default = False
    audit(
        session,
        actor,
        "ai_provider.updated",
        "ai_provider",
        row.id,
        fields=sorted(k for k in changes if k != "api_key")
        + (["api_key"] if "api_key" in changes else []),
    )
    await session.commit()
    return row


async def delete_provider(session: AsyncSession, actor: Actor, provider_id: uuid.UUID) -> None:
    row = await get_provider(session, actor.scope, provider_id)
    await session.delete(row)
    audit(session, actor, "ai_provider.deleted", "ai_provider", row.id, name=row.name)
    await session.commit()


async def test_provider(
    container: Container, session: AsyncSession, actor: Actor, provider_id: uuid.UUID
) -> ProviderTest:
    """One tiny real model call, so a wrong key or model shows up here, not mid-incident."""
    row = await get_provider(session, actor.scope, provider_id)
    started = time.perf_counter()
    try:
        adapter = adapter_for(await config_of(container, row), container.http)
        await adapter.complete(
            ModelRequest(
                model=row.model,
                messages=(
                    Message("system", "TASK: ping"),
                    Message("user", "Reply with the single word: ok"),
                ),
                max_tokens=8,
            )
        )
        ok, message = True, "The provider answered"
    except ProviderError as exc:
        ok, message = False, exc.message
    except AppError as exc:
        ok, message = False, exc.message
    latency = int((time.perf_counter() - started) * 1000)
    row.last_test_at = datetime.now(UTC)
    row.last_test_ok = ok
    row.last_test_message = message[:500]
    await session.commit()
    return ProviderTest(ok=ok, message=message, latency_ms=latency)
