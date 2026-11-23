from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from logmind.core.schemas import ApiModel, Email


class SignupIn(ApiModel):
    org_name: str = Field(min_length=1, max_length=120)
    email: Email
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=200)


class LoginIn(ApiModel):
    email: Email
    password: str = Field(min_length=1, max_length=200)


class UserOut(ApiModel):
    id: uuid.UUID
    org_id: uuid.UUID
    email: str
    name: str
    role: str
    disabled: bool
    last_login_at: datetime | None
    created_at: datetime


class SessionOut(ApiModel):
    session_token: str
    user: UserOut


class UserIn(ApiModel):
    email: Email
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=200)
    role: str = Field("viewer", pattern="^(viewer|admin|owner)$")


class UserUpdate(ApiModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    role: str | None = Field(None, pattern="^(viewer|admin|owner)$")
    disabled: bool | None = None
