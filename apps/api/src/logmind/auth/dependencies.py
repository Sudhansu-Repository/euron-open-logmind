"""Who is calling.

* **People** use the dashboard with ``Authorization: Bearer <session token>`` (issued by
  ``POST /api/v1/auth/login``). Roles rank ``viewer < admin < owner``.
* **Projects** (the SDK, OTLP exporters) use a project API key (``lmk_...``), checked by
  :mod:`logmind.projects.dependencies` since it resolves to a project, not just an
  organization.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy import select

from logmind.audit.service import Actor
from logmind.auth.models import User
from logmind.core.deps import ContainerDep, SessionDep
from logmind.core.errors import AuthenticationError, PermissionDeniedError
from logmind.core.security import SessionClaims, decode_session

ROLE_RANK = {"viewer": 0, "admin": 1, "owner": 2}


def bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else None
    return token or None


async def current_user(request: Request, container: ContainerDep, session: SessionDep) -> User:
    token = bearer(request)
    if not token:
        raise AuthenticationError("Sign in to continue", code="not_signed_in")
    claims: SessionClaims | None = decode_session(token, container.settings.session_secret)
    if claims is None:
        raise AuthenticationError("Your session expired. Sign in again", code="session_expired")
    user = await session.scalar(
        select(User).where(User.id == claims.user_id, User.org_id == claims.org_id)
    )
    if user is None or user.disabled or user.session_version != claims.session_version:
        raise AuthenticationError("Your session expired. Sign in again", code="session_expired")
    request.state.actor = Actor(user.org_id, user.id, user.email, user.role)
    request.state.user = user
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def has_role(role: str, required: str) -> bool:
    return ROLE_RANK.get(role, -1) >= ROLE_RANK[required]


def require_role(role: str) -> Callable[..., Coroutine[Any, Any, Actor]]:
    async def dependency(request: Request, user: CurrentUser) -> Actor:
        if not has_role(user.role, role):
            raise PermissionDeniedError(f"This needs the {role} role", code="insufficient_role")
        actor: Actor = request.state.actor
        return actor

    return dependency


Viewer = Annotated[Actor, Depends(require_role("viewer"))]
Admin = Annotated[Actor, Depends(require_role("admin"))]
Owner = Annotated[Actor, Depends(require_role("owner"))]
