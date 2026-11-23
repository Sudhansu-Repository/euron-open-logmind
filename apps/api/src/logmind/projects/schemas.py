from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from logmind.core.schemas import ApiModel

# A nested quantifier (a repeated group that itself contains a repetition, e.g. ``(a+)+``)
# is the classic shape behind catastrophic backtracking. A heuristic, not a proof; the
# real backstop is the pattern length cap plus redaction running only against values
# already bounded at ingestion.
_NESTED_QUANTIFIER = re.compile(r"\([^()]*[+*][^()]*\)[+*]")

# Kept equal to redaction.recognizers.CATEGORIES (a unit test checks it).
RedactionCategory = Literal[
    "credential", "email", "payment_card", "government_id", "phone", "bank_account", "ip_address"
]


class CustomPatternIn(ApiModel):
    name: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9_]+$")
    pattern: str = Field(min_length=1, max_length=300)

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, v: str) -> str:
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"pattern is not a valid regular expression: {exc}") from None
        if _NESTED_QUANTIFIER.search(v):
            raise ValueError(
                "pattern has a repeated group that is itself repeated (e.g. (a+)+), which "
                "can backtrack catastrophically; simplify it"
            )
        return v


class ProjectIn(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field("", max_length=2000)
    retention_days: int = Field(14, ge=1, le=365)


class ProjectUpdate(ApiModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=2000)
    retention_days: int | None = Field(None, ge=1, le=365)
    redaction_enabled: bool | None = None
    redaction_categories: list[RedactionCategory] | None = None
    redaction_custom: list[CustomPatternIn] | None = Field(None, max_length=20)
    redaction_mode: Literal["mask", "hash"] | None = None
    archived: bool | None = None


class ProjectOut(ApiModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str
    retention_days: int
    redaction_enabled: bool
    redaction_categories: list[str]
    redaction_custom: list[CustomPatternIn]
    redaction_mode: str
    archived: bool
    created_at: datetime


class EnvironmentOut(ApiModel):
    name: str
    first_seen_at: datetime
    last_seen_at: datetime


class RedactionPreviewIn(ApiModel):
    text: str = Field(min_length=1, max_length=10_000)


class RedactionPreviewOut(ApiModel):
    redacted: str
    counts: dict[str, int]


class KeyIn(ApiModel):
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)


class KeyOut(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    prefix: str
    display: str
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


class KeyCreated(KeyOut):
    key: str = Field(description="The plaintext key. Shown once, at creation, never again.")
