from __future__ import annotations

from datetime import datetime
from typing import Any

from logmind.core.schemas import ApiModel


class AuditEntryOut(ApiModel):
    id: int
    at: datetime
    actor_type: str
    actor_id: str | None
    actor_name: str | None
    action: str
    target_type: str | None
    target_id: str | None
    details: dict[str, Any]
    ip: str | None
