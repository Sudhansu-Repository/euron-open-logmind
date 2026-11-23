from __future__ import annotations

from fastapi import APIRouter, Query

from logmind.audit import service
from logmind.audit.schemas import AuditEntryOut
from logmind.auth.dependencies import Viewer
from logmind.core.deps import SessionDep
from logmind.core.schemas import Page, decode_cursor, encode_cursor

router = APIRouter(prefix="/api/v1/audit-log", tags=["audit"])


@router.get("", response_model=Page[AuditEntryOut], summary="List audit log entries")
async def list_audit_log(
    actor: Viewer,
    session: SessionDep,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    action: str | None = None,
) -> Page[AuditEntryOut]:
    decoded = decode_cursor(cursor)
    after_id = int(decoded) if decoded else None
    rows = await service.list_entries(
        session, actor.scope, after_id=after_id, limit=limit, action=action
    )
    page = rows[:limit]
    next_cursor = encode_cursor(page[-1].id) if len(rows) > limit else None
    return Page(items=[AuditEntryOut.model_validate(r) for r in page], next_cursor=next_cursor)
