"""Signup (creates an organization and its first owner), login, and session issuing."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from logmind.audit.service import Actor, audit
from logmind.auth.exceptions import (
    EmailTakenError,
    InvalidCredentialsError,
    WeakPasswordError,
)
from logmind.auth.models import User
from logmind.auth.schemas import LoginIn, SignupIn, UserIn, UserUpdate
from logmind.core.db import OrgScope, get_scoped
from logmind.core.errors import NotFoundError
from logmind.core.security import (
    hash_password,
    issue_session,
    password_problems,
    verify_password,
)
from logmind.core.text import slugify
from logmind.orgs.models import Organization


async def _unique_org_slug(session: AsyncSession, name: str) -> str:
    base = slugify(name)
    slug, i = base, 2
    while await session.scalar(select(Organization.id).where(Organization.slug == slug)):
        slug, i = f"{base}-{i}", i + 1
    return slug


async def signup(session: AsyncSession, data: SignupIn) -> tuple[User, Organization]:
    existing = await session.scalar(select(User).where(func.lower(User.email) == data.email))
    if existing is not None:
        raise EmailTakenError("An account with this email already exists")
    if problems := password_problems(data.password):
        raise WeakPasswordError("Password needs " + ", ".join(problems))
    org = Organization(name=data.org_name, slug=await _unique_org_slug(session, data.org_name))
    session.add(org)
    await session.flush()
    user = User(
        org_id=org.id,
        email=data.email,
        name=data.name,
        role="owner",
        password_hash=hash_password(data.password),
    )
    session.add(user)
    await session.flush()
    actor = Actor(org.id, user.id, user.email, user.role)
    audit(session, actor, "org.created", "organization", org.id, name=org.name)
    audit(session, actor, "user.created", "user", user.id, email=user.email, role=user.role)
    await session.commit()
    return user, org


async def login(session: AsyncSession, data: LoginIn) -> User:
    user = await session.scalar(select(User).where(func.lower(User.email) == data.email))
    if user is None or user.disabled or not verify_password(data.password, user.password_hash):
        raise InvalidCredentialsError("Incorrect email or password")
    user.last_login_at = datetime.now(UTC)
    await session.commit()
    return user


def session_token_for(user: User, secret: str, ttl_hours: int) -> str:
    return issue_session(user.id, user.org_id, user.role, user.session_version, secret, ttl_hours)


async def list_users(session: AsyncSession, scope: OrgScope) -> list[User]:
    stmt = select(User).where(User.org_id == scope.org_id).order_by(User.created_at)
    return list((await session.scalars(stmt)).all())


async def create_user(session: AsyncSession, scope: OrgScope, data: UserIn, actor: Actor) -> User:
    existing = await session.scalar(select(User).where(func.lower(User.email) == data.email))
    if existing is not None:
        raise EmailTakenError("An account with this email already exists")
    if problems := password_problems(data.password):
        raise WeakPasswordError("Password needs " + ", ".join(problems))
    user = User(
        org_id=scope.org_id,
        email=data.email,
        name=data.name,
        role=data.role,
        password_hash=hash_password(data.password),
    )
    session.add(user)
    await session.flush()
    audit(session, actor, "user.created", "user", user.id, email=user.email, role=user.role)
    await session.commit()
    return user


async def update_user(
    session: AsyncSession, scope: OrgScope, user_id: uuid.UUID, data: UserUpdate, actor: Actor
) -> User:
    user = await get_scoped(session, User, scope, user_id)
    if user is None:
        raise NotFoundError("User not found")
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(user, field, value)
    if changes:
        user.session_version += 1
    audit(
        session, actor, "user.updated", "user", user.id, **{k: str(v) for k, v in changes.items()}
    )
    await session.commit()
    return user
