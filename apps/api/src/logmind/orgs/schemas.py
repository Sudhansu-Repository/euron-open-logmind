from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from logmind.core.schemas import ApiModel


class OrgOut(ApiModel):
    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime


class OrgUpdate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
