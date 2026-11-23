"""AI Root Cause Analyzer: queue, run, read back, follow up, verify.

``POST /api/v1/ai/investigate`` only queues (202); the worker runs it: collect and
compress evidence (``evidence.py``), store the pack, ask the organisation's provider,
validate every citation (``citations.py``), record token usage (A4). Follow-ups (A12) run
the same way over the same pack, with extra evidence appended when the question asks
about earlier events. ``verify`` re-reads every cited line from ClickHouse and compares it
with the snapshot in the report (A3): a report can prove its own grounding.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

import orjson
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from logmind.audit.service import Actor, audit
from logmind.core import metrics
from logmind.core.container import Container
from logmind.core.db import OrgScope, ProjectScope
from logmind.core.errors import AppError, ConflictError, NotFoundError
from logmind.core.storage import ObjectNotFoundError
from logmind.errors.models import ErrorGroup
from logmind.errors.repository import ErrorGroupRepository
from logmind.investigations import evidence as ev
from logmind.investigations.citations import (
    ReportFormatError,
    parse_json_object,
    validate_answer,
    validate_report,
)
from logmind.investigations.models import AiUsage, Investigation, InvestigationTurn
from logmind.investigations.prompt import followup_messages, investigate_messages
from logmind.investigations.schemas import (
    CitationCheck,
    EvidenceItemOut,
    InvestigateIn,
    InvestigationOut,
    InvestigationSummary,
    TurnOut,
    VerifyOut,
)
from logmind.logs.repository import LogRepository
from logmind.projects.repository import ProjectRepository
from logmind.providers import gateway
from logmind.providers import service as providers
from logmind.providers.types import ModelRequest, ModelResponse, ProviderError

log = logging.getLogger("logmind.investigations")

MAX_ATTEMPTS = 3
REPORT_MAX_TOKENS = 1500


def _key(inv: Investigation, turn: InvestigationTurn | None = None) -> str:
    base = f"evidence/{inv.org_id}/{inv.id}"
    return f"{base}/turn-{turn.seq}.json" if turn else f"{base}/pack.json"


def _parse_iso(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


# ---------------------------------------------------------------------------- create


async def create_investigation(
    container: Container, session: AsyncSession, actor: Actor, data: InvestigateIn
) -> Investigation:
    project = await ProjectRepository(session).get_in_org(actor.scope, data.project_id)
    if project is None:
        raise NotFoundError("Project not found", code="unknown_project")
    scope = ProjectScope(actor.org_id, project.id)
    group: ErrorGroup | None = None
    if data.error_group_id is not None:
        group = await ErrorGroupRepository(session).get_in(scope, data.error_group_id)
        if group is None:
            raise NotFoundError("Error group not found", code="error_group_not_found")
    elif not data.question.strip():
        raise AppError(
            "Pick an error group to explain, or ask a question", code="question_required"
        )
    provider = await providers.default_provider(session, actor.scope)
    inv = Investigation(
        org_id=actor.org_id,
        project_id=project.id,
        error_group_id=group.id if group else None,
        title=(group.title if group else data.question.strip())[:300],
        question=data.question.strip(),
        window_minutes=data.window_minutes or container.settings.ai_default_window_minutes,
        provider_name=provider.name,
        model=provider.model,
        created_by=actor.id,
    )
    session.add(inv)
    await session.flush()
    audit(session, actor, "investigation.created", "investigation", inv.id, title=inv.title)
    await session.commit()
    return inv


async def create_followup(
    session: AsyncSession, actor: Actor, investigation_id: uuid.UUID, question: str
) -> InvestigationTurn:
    inv = await get_investigation(session, actor.scope, investigation_id)
    if inv.status != "completed":
        raise ConflictError(
            "Ask follow-ups once the investigation has finished", code="investigation_not_ready"
        )
    seq = int(
        await session.scalar(
            select(func.coalesce(func.max(InvestigationTurn.seq), 0)).where(
                InvestigationTurn.investigation_id == inv.id
            )
        )
        or 0
    )
    turn = InvestigationTurn(
        org_id=inv.org_id,
        investigation_id=inv.id,
        seq=seq + 1,
        question=question.strip(),
        created_by=actor.id,
    )
    session.add(turn)
    await session.flush()
    audit(session, actor, "investigation.followup", "investigation", inv.id, seq=turn.seq)
    await session.commit()
    return turn


# ------------------------------------------------------------------------------ read


async def get_investigation(
    session: AsyncSession, scope: OrgScope, investigation_id: uuid.UUID
) -> Investigation:
    inv = await session.scalar(
        select(Investigation).where(
            Investigation.id == investigation_id, Investigation.org_id == scope.org_id
        )
    )
    if inv is None:
        raise NotFoundError("Investigation not found", code="investigation_not_found")
    return inv


def summary(inv: Investigation) -> InvestigationSummary:
    report = inv.report or {}
    return InvestigationSummary(
        id=inv.id,
        project_id=inv.project_id,
        error_group_id=inv.error_group_id,
        title=inv.title,
        question=inv.question,
        status=inv.status,
        error=inv.error,
        provider_name=inv.provider_name,
        model=inv.model,
        evidence_count=inv.evidence_count,
        raw_lines=inv.raw_lines,
        raw_tokens_estimate=inv.raw_tokens_estimate,
        context_tokens_estimate=inv.context_tokens_estimate,
        input_tokens=inv.input_tokens,
        output_tokens=inv.output_tokens,
        rejected_citations=inv.rejected_citations,
        grounded=inv.grounded,
        confidence=report.get("confidence") if report else None,
        root_cause=report.get("root_cause") if report else None,
        created_at=inv.created_at,
        started_at=inv.started_at,
        finished_at=inv.finished_at,
    )


async def list_investigations(
    session: AsyncSession, scope: ProjectScope, *, error_group_id: uuid.UUID | None, limit: int
) -> list[InvestigationSummary]:
    stmt = (
        select(Investigation)
        .where(Investigation.org_id == scope.org_id, Investigation.project_id == scope.project_id)
        .order_by(Investigation.created_at.desc())
        .limit(limit)
    )
    if error_group_id is not None:
        stmt = stmt.where(Investigation.error_group_id == error_group_id)
    return [summary(i) for i in (await session.scalars(stmt)).all()]


async def _load_pack(container: Container, key: str | None) -> ev.EvidencePack | None:
    if not key:
        return None
    try:
        return ev.EvidencePack.from_json(orjson.loads(await container.storage.get(key)))
    except ObjectNotFoundError:
        return None


async def _load_items(container: Container, key: str | None) -> list[ev.EvidenceItem]:
    if not key:
        return []
    try:
        data = orjson.loads(await container.storage.get(key))
    except ObjectNotFoundError:
        return []
    return [ev.EvidenceItem(**i) for i in data.get("items", [])]


def _item_out(i: ev.EvidenceItem) -> EvidenceItemOut:
    return EvidenceItemOut(
        ref=i.ref,
        event_id=uuid.UUID(i.event_id),
        timestamp=_parse_iso(i.timestamp) or datetime.now(UTC),
        service=i.service,
        level=i.level,
        kind=i.kind,
        message=i.message,
        count=i.count,
        last_timestamp=_parse_iso(i.last_timestamp),
    )


async def _turns(session: AsyncSession, inv: Investigation) -> list[InvestigationTurn]:
    rows = await session.scalars(
        select(InvestigationTurn)
        .where(
            InvestigationTurn.investigation_id == inv.id,
            InvestigationTurn.org_id == inv.org_id,
        )
        .order_by(InvestigationTurn.seq)
    )
    return list(rows.all())


async def investigation_out(
    container: Container, session: AsyncSession, scope: OrgScope, investigation_id: uuid.UUID
) -> InvestigationOut:
    inv = await get_investigation(session, scope, investigation_id)
    pack = await _load_pack(container, inv.evidence_key)
    turns = await _turns(session, inv)
    items = list(pack.items) if pack else []
    for t in turns:
        items.extend(await _load_items(container, t.evidence_key))
    return InvestigationOut(
        **summary(inv).model_dump(),
        window_start=inv.window_start,
        window_end=inv.window_end,
        incident_start=inv.incident_start,
        report=inv.report,
        evidence=[_item_out(i) for i in items],
        turns=[TurnOut.model_validate(t) for t in turns],
    )


# ------------------------------------------------------------------------------- run


async def _model_call(
    container: Container, session: AsyncSession, inv: Investigation, request_messages: Any
) -> tuple[str, ModelResponse]:
    provider = await providers.default_provider(session, OrgScope(inv.org_id))
    adapter = await gateway.adapter(container, provider)
    response = await gateway.complete(
        adapter,
        ModelRequest(
            model=provider.model,
            messages=request_messages,
            max_tokens=REPORT_MAX_TOKENS,
            temperature=0.0,
        ),
    )
    return provider.name, response


def _record_usage(
    session: AsyncSession,
    inv: Investigation,
    turn: InvestigationTurn | None,
    provider_name: str,
    response: ModelResponse,
    *,
    context_tokens: int,
    raw_tokens: int,
) -> None:
    session.add(
        AiUsage(
            org_id=inv.org_id,
            project_id=inv.project_id,
            investigation_id=inv.id,
            turn_id=turn.id if turn else None,
            kind="followup" if turn else "investigation",
            provider=provider_name,
            model=response.model or inv.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            usage_reported=response.usage_reported,
            context_tokens_estimate=context_tokens,
            raw_tokens_estimate=raw_tokens,
            at=datetime.now(UTC),
        )
    )
    metrics.model_tokens_total.labels(direction="input").inc(response.usage.input_tokens)
    metrics.model_tokens_total.labels(direction="output").inc(response.usage.output_tokens)


async def run_investigation(container: Container, investigation_id: uuid.UUID) -> None:
    async with container.db.sessionmaker() as session:
        inv = await session.get(Investigation, investigation_id)
        if inv is None or inv.status != "running":
            return
        scope = ProjectScope(inv.org_id, inv.project_id)
        try:
            group = (
                await ErrorGroupRepository(session).get_in(scope, inv.error_group_id)
                if inv.error_group_id
                else None
            )
            pack = await ev.collect(
                LogRepository(container.clickhouse),
                scope,
                container.settings,
                group=group,
                window_minutes=inv.window_minutes,
            )
            key = _key(inv)
            await container.storage.put(key, orjson.dumps(pack.to_json()), "application/json")
            inv.evidence_key = key
            inv.evidence_count = len(pack.items)
            inv.raw_lines = pack.raw_lines
            inv.raw_tokens_estimate = pack.raw_tokens_estimate
            inv.context_tokens_estimate = pack.context_tokens_estimate
            inv.window_start = _parse_iso(pack.window_start)
            inv.window_end = _parse_iso(pack.window_end)
            inv.incident_start = _parse_iso(pack.incident_start)
            provider_name, response = await _model_call(
                container, session, inv, investigate_messages(pack, inv.question)
            )
            _record_usage(
                session,
                inv,
                None,
                provider_name,
                response,
                context_tokens=pack.context_tokens_estimate,
                raw_tokens=pack.raw_tokens_estimate,
            )
            inv.provider_name = provider_name
            inv.model = response.model or inv.model
            inv.input_tokens = response.usage.input_tokens
            inv.output_tokens = response.usage.output_tokens
            report, validation = validate_report(parse_json_object(response.text), pack.refs())
            inv.report = report
            inv.rejected_citations = len(validation.rejected)
            inv.grounded = bool(report["root_cause"]) and not validation.discarded
            inv.status = "completed"
            metrics.citations_rejected_total.inc(len(validation.rejected))
        except (ProviderError, ReportFormatError, AppError) as exc:
            inv.status = "failed"
            inv.error = getattr(exc, "message", None) or str(exc)
            log.warning("investigation failed", extra={"id": str(inv.id), "error": inv.error})
        inv.finished_at = datetime.now(UTC)
        inv.lease_expires_at = None
        await session.commit()
        metrics.investigations_total.labels(status=inv.status).inc()


async def run_turn(container: Container, turn_id: uuid.UUID) -> None:
    async with container.db.sessionmaker() as session:
        turn = await session.get(InvestigationTurn, turn_id)
        if turn is None or turn.status != "running":
            return
        inv = await session.get(Investigation, turn.investigation_id)
        if inv is None or inv.org_id != turn.org_id:
            return
        scope = ProjectScope(inv.org_id, inv.project_id)
        try:
            pack = await _load_pack(container, inv.evidence_key)
            if pack is None:
                raise AppError("The investigation's evidence pack is missing; run it again")
            earlier = [t for t in await _turns(session, inv) if t.seq < turn.seq]
            extra: list[ev.EvidenceItem] = []
            for t in earlier:
                extra.extend(await _load_items(container, t.evidence_key))
            if any(
                w in turn.question.lower()
                for w in ("before", "change", "earlier", "deploy", "trigger")
            ):
                combined = ev.EvidencePack.from_json({**pack.to_json(), "items": []})
                combined.items = [*pack.items, *extra]
                fresh = await ev.collect_more_before(
                    LogRepository(container.clickhouse),
                    scope,
                    container.settings,
                    combined,
                    window_minutes=inv.window_minutes,
                )
                if fresh:
                    key = _key(inv, turn)
                    await container.storage.put(
                        key,
                        orjson.dumps({"items": [asdict(i) for i in fresh]}),
                        "application/json",
                    )
                    turn.evidence_key = key
                    turn.added_evidence = len(fresh)
                    extra.extend(fresh)
            history = [
                (t.question, str((t.answer or {}).get("answer", ""))) for t in earlier if t.answer
            ]
            messages = followup_messages(pack, extra, inv.report or {}, history, turn.question)
            provider_name, response = await _model_call(container, session, inv, messages)
            refs = {**pack.refs(), **{i.ref: i for i in extra}}
            context_tokens = ev.estimate_tokens("\n".join(m.content for m in messages))
            _record_usage(
                session,
                inv,
                turn,
                provider_name,
                response,
                context_tokens=context_tokens,
                raw_tokens=pack.raw_tokens_estimate,
            )
            answer, validation = validate_answer(parse_json_object(response.text), refs)
            turn.answer = answer
            turn.input_tokens = response.usage.input_tokens
            turn.output_tokens = response.usage.output_tokens
            turn.rejected_citations = len(validation.rejected)
            turn.grounded = bool(answer["findings"]) and not validation.discarded
            turn.status = "completed"
            metrics.citations_rejected_total.inc(len(validation.rejected))
        except (ProviderError, ReportFormatError, AppError) as exc:
            turn.status = "failed"
            turn.error = getattr(exc, "message", None) or str(exc)
        turn.finished_at = datetime.now(UTC)
        turn.lease_expires_at = None
        await session.commit()


# ----------------------------------------------------------------------------- queue


async def _claim[J: (Investigation, InvestigationTurn)](
    session: AsyncSession, model: type[J], worker_id: str, lease: datetime, now: datetime
) -> J | None:
    row = await session.scalar(
        select(model)
        .where(model.status == "queued")
        .order_by(model.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if row is None:
        return None
    row.status = "running"
    row.claimed_by = worker_id
    row.lease_expires_at = lease
    row.attempts += 1
    row.started_at = row.started_at or now
    return row


async def claim_next(
    session: AsyncSession, worker_id: str, lease_s: float
) -> tuple[str, uuid.UUID] | None:
    """Claim one queued investigation, else one queued follow-up. The row lock (``SKIP
    LOCKED``) is what keeps two workers from ever claiming the same job; the claim commits
    right away so the lock is held only for the claim."""
    now = datetime.now(UTC)
    lease = now + timedelta(seconds=lease_s)
    inv = await _claim(session, Investigation, worker_id, lease, now)
    if inv is not None:
        await session.commit()
        return "investigation", inv.id
    turn = await _claim(session, InvestigationTurn, worker_id, lease, now)
    if turn is not None:
        await session.commit()
        return "turn", turn.id
    await session.rollback()
    return None


async def _reap(
    session: AsyncSession, model: type[Investigation] | type[InvestigationTurn], now: datetime
) -> int:
    failed = await session.execute(
        update(model)
        .where(
            model.status == "running",
            model.lease_expires_at < now,
            model.attempts >= MAX_ATTEMPTS,
        )
        .values(
            status="failed",
            error="The worker stopped responding several times; try again",
            finished_at=now,
            lease_expires_at=None,
        )
    )
    requeued = await session.execute(
        update(model)
        .where(model.status == "running", model.lease_expires_at < now)
        .values(status="queued", claimed_by=None, lease_expires_at=None)
    )
    return int(getattr(failed, "rowcount", 0) or 0) + int(getattr(requeued, "rowcount", 0) or 0)


async def reap_expired(session: AsyncSession) -> int:
    """Jobs whose worker stopped before finishing: back to the queue, or failed once they
    have been tried ``MAX_ATTEMPTS`` times."""
    now = datetime.now(UTC)
    total = await _reap(session, Investigation, now) + await _reap(session, InvestigationTurn, now)
    await session.commit()
    return total


# ---------------------------------------------------------------------------- verify


def _all_citations(inv: Investigation, turns: list[InvestigationTurn]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for c in (inv.report or {}).get("citations", []):
        seen[c["ref"]] = c
    for t in turns:
        for c in (t.answer or {}).get("citations", []):
            seen.setdefault(c["ref"], c)
    return list(seen.values())


async def verify(
    container: Container, session: AsyncSession, scope: OrgScope, investigation_id: uuid.UUID
) -> VerifyOut:
    """Re-read every cited line from ClickHouse, through the investigation's own project
    scope, and compare it with the report's snapshot of that line."""
    inv = await get_investigation(session, scope, investigation_id)
    citations = _all_citations(inv, await _turns(session, inv))
    project_scope = ProjectScope(inv.org_id, inv.project_id)
    stamps = [_parse_iso(c["timestamp"]) for c in citations]
    valid = [s for s in stamps if s is not None]
    checks: list[CitationCheck] = []
    if valid:
        start = min(valid) - timedelta(seconds=1)
        end = max(valid) + timedelta(seconds=1)
        stored = await LogRepository(container.clickhouse).get_many(
            project_scope, [uuid.UUID(c["event_id"]) for c in citations], start, end
        )
        for c, ts in zip(citations, stamps, strict=True):
            line = stored.get(uuid.UUID(c["event_id"]))
            ts_ok = bool(line and ts and abs((line.timestamp - ts).total_seconds()) < 0.002)
            snapshot = str(c["message"]).removesuffix("...")
            msg_ok = bool(line) and _same_text(line.message if line else "", snapshot)
            checks.append(
                CitationCheck(
                    ref=c["ref"],
                    event_id=uuid.UUID(c["event_id"]),
                    found=line is not None,
                    timestamp_matches=ts_ok,
                    message_matches=msg_ok,
                    stored_message=line.message[:2000] if line else None,
                    verified=line is not None and ts_ok and msg_ok,
                )
            )
    verified = sum(1 for c in checks if c.verified)
    return VerifyOut(
        investigation_id=inv.id,
        checked=len(checks),
        verified=verified,
        all_verified=bool(checks) and verified == len(checks),
        citations=checks,
    )


def _same_text(stored: str, snapshot: str) -> bool:
    """The snapshot is the stored message with whitespace collapsed and, past the
    evidence length limit, cut; a stack trace head may follow a ``|``."""
    collapsed = " ".join(stored.split())
    head = snapshot.split(" | ")[0]
    return bool(head) and collapsed.startswith(head)
