"""Request and response models for AI providers."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from logmind.core.net import check_url
from logmind.core.schemas import ApiModel

ProviderKind = Literal["openai", "anthropic", "gemini", "ollama", "openai_compatible", "mock"]
NAME = r"^[a-z0-9][a-z0-9_-]{0,63}$"


class ProviderCreate(ApiModel):
    name: str = Field(pattern=NAME, description="Short and unique in the organisation")
    kind: ProviderKind
    model: str = Field("", max_length=200, description="e.g. gpt-4.1-mini (any for mock)")
    # Defaults per kind when omitted (required for openai_compatible; unused by mock).
    base_url: str | None = Field(None, max_length=500)
    api_key: str | None = Field(None, max_length=2000)
    timeout_s: float = Field(60.0, gt=0, le=1800)
    enabled: bool = True
    is_default: bool = False

    @field_validator("base_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        return check_url(v, "base_url") if v else None


class ProviderUpdate(ApiModel):
    model: str | None = Field(None, min_length=1, max_length=200)
    base_url: str | None = Field(None, max_length=500)
    # A new key replaces the stored one; an empty string removes it.
    api_key: str | None = Field(None, max_length=2000)
    timeout_s: float | None = Field(None, gt=0, le=1800)
    enabled: bool | None = None
    is_default: bool | None = None

    @field_validator("base_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        return check_url(v, "base_url") if v else None


class ProviderOut(ApiModel):
    id: uuid.UUID
    name: str
    kind: ProviderKind
    model: str
    base_url: str
    has_api_key: bool = Field(description="Whether a key is stored; the key is never returned")
    enabled: bool
    is_default: bool
    timeout_s: float
    last_test_at: datetime | None
    last_test_ok: bool | None
    last_test_message: str | None
    created_at: datetime


class ProviderTest(ApiModel):
    ok: bool
    message: str
    latency_ms: int
