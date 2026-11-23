from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from logmind.auth import service
from logmind.auth.dependencies import CurrentUser, Owner
from logmind.auth.schemas import LoginIn, SessionOut, SignupIn, UserIn, UserOut, UserUpdate
from logmind.core.deps import ContainerDep, SessionDep, client_ip
from logmind.core.errors import PermissionDeniedError
from logmind.core.ratelimit import hit

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
users_router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.post(
    "/signup",
    response_model=SessionOut,
    status_code=201,
    summary="Create an organization and its owner",
)
async def signup(
    body: SignupIn, request: Request, session: SessionDep, container: ContainerDep
) -> SessionOut:
    if not container.settings.signup_enabled:
        raise PermissionDeniedError(
            "Sign up is turned off on this installation. Ask an owner to invite you",
            code="signup_disabled",
        )
    await hit(
        container.redis,
        f"signup:{client_ip(request)}",
        container.settings.login_attempts_per_minute,
    )
    user, _org = await service.signup(session, body)
    token = service.session_token_for(
        user, container.settings.session_secret, container.settings.session_ttl_hours
    )
    return SessionOut(session_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=SessionOut, summary="Sign in")
async def login(
    body: LoginIn, request: Request, session: SessionDep, container: ContainerDep
) -> SessionOut:
    await hit(
        container.redis, f"login:{client_ip(request)}", container.settings.login_attempts_per_minute
    )
    user = await service.login(session, body)
    token = service.session_token_for(
        user, container.settings.session_secret, container.settings.session_ttl_hours
    )
    return SessionOut(session_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut, summary="The signed-in user")
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@users_router.get("", response_model=list[UserOut], summary="List organization users")
async def list_users(actor: Owner, session: SessionDep) -> list[UserOut]:
    return [UserOut.model_validate(u) for u in await service.list_users(session, actor.scope)]


@users_router.post("", response_model=UserOut, status_code=201, summary="Invite a user")
async def create_user(body: UserIn, actor: Owner, session: SessionDep) -> UserOut:
    return UserOut.model_validate(await service.create_user(session, actor.scope, body, actor))


@users_router.patch("/{user_id}", response_model=UserOut, summary="Update a user")
async def update_user(
    user_id: uuid.UUID, body: UserUpdate, actor: Owner, session: SessionDep
) -> UserOut:
    return UserOut.model_validate(
        await service.update_user(session, actor.scope, user_id, body, actor)
    )
