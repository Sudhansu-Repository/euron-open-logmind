"""Alert Management: rule CRUD, evaluation and delivery (A9, A10).

Evaluation is claim-then-deliver. A worker locks a due rule (``FOR UPDATE SKIP LOCKED``,
so with several workers each rule is evaluated by exactly one per interval), measures it,
records the state change and its history row, and commits; only then does it deliver,
and the delivery outcomes are written back to that history row. A slow webhook therefore
never holds a lock, and a crash mid-delivery cannot fire the same alert twice.

State: ``ok`` -> breach -> ``firing`` (notify "fired"); ``firing`` -> recovery -> ``ok``
(notify "resolved"). While firing, nothing is re-sent; once the cooldown has passed a
continuing breach notifies again as a reminder.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from logmind.alerts import channels
from logmind.alerts.evaluator import Measurement, measure
from logmind.alerts.models import AlertHistory, AlertRule
from logmind.alerts.schemas import AlertCreated, AlertHistoryOut, AlertIn, AlertOut, AlertUpdate
from logmind.audit.service import Actor, audit
from logmind.core import metrics
from logmind.core.container import Container
from logmind.core.db import OrgScope, ProjectScope, get_scoped
from logmind.core.errors import NotFoundError
from logmind.logs.repository import LogRepository
from logmind.projects.models import Project
from logmind.projects.repository import ProjectRepository

log = logging.getLogger("logmind.alerts")


def _ctx(rule_id: uuid.UUID, what: str) -> str:
    return f"alert_rule:{rule_id}:{what}"


def rule_out(rule: AlertRule) -> AlertOut:
    return AlertOut(
        id=rule.id,
        project_id=rule.project_id,
        name=rule.name,
        kind=rule.kind,
        metric=rule.metric,
        query=rule.query,
        service=rule.service,
        environment=rule.environment,
        threshold=rule.threshold,
        window_minutes=rule.window_minutes,
        sensitivity=rule.sensitivity,
        min_count=rule.min_count,
        baseline_hours=rule.baseline_hours,
        email_to=list(rule.email_to),
        has_webhook=rule.webhook_url_sealed is not None,
        has_slack=rule.slack_url_sealed is not None,
        cooldown_minutes=rule.cooldown_minutes,
        enabled=rule.enabled,
        state=rule.state,
        last_value=rule.last_value,
        last_evaluated_at=rule.last_evaluated_at,
        last_fired_at=rule.last_fired_at,
        created_at=rule.created_at,
    )


async def get_rule(session: AsyncSession, scope: OrgScope, rule_id: uuid.UUID) -> AlertRule:
    rule = await get_scoped(session, AlertRule, scope, rule_id)
    if rule is None:
        raise NotFoundError("Alert rule not found", code="alert_not_found")
    return rule


async def list_rules(session: AsyncSession, scope: ProjectScope) -> list[AlertRule]:
    rows = await session.scalars(
        select(AlertRule)
        .where(AlertRule.org_id == scope.org_id, AlertRule.project_id == scope.project_id)
        .order_by(AlertRule.created_at)
    )
    return list(rows.all())


async def create_rule(
    container: Container, session: AsyncSession, actor: Actor, data: AlertIn
) -> AlertCreated:
    project = await ProjectRepository(session).get_in_org(actor.scope, data.project_id)
    if project is None:
        raise NotFoundError("Project not found", code="unknown_project")
    rule = AlertRule(
        id=uuid.uuid4(),
        org_id=actor.org_id,
        project_id=project.id,
        name=data.name,
        kind=data.kind,
        metric=data.metric,
        query=data.query.strip(),
        service=data.service.strip(),
        environment=data.environment.strip(),
        threshold=data.threshold,
        window_minutes=data.window_minutes,
        sensitivity=data.sensitivity,
        min_count=data.min_count,
        baseline_hours=data.baseline_hours,
        email_to=list(data.email_to),
        cooldown_minutes=data.cooldown_minutes,
        enabled=data.enabled,
        created_by=actor.id,
    )
    secret: str | None = None
    if data.webhook_url:
        secret = "whsec_" + secrets.token_urlsafe(24)
        rule.webhook_url_sealed = await container.sealer.seal(
            data.webhook_url, _ctx(rule.id, "webhook")
        )
        rule.webhook_secret_sealed = await container.sealer.seal(secret, _ctx(rule.id, "secret"))
    if data.slack_url:
        rule.slack_url_sealed = await container.sealer.seal(data.slack_url, _ctx(rule.id, "slack"))
    session.add(rule)
    await session.flush()
    audit(session, actor, "alert.created", "alert_rule", rule.id, name=rule.name, kind=rule.kind)
    await session.commit()
    await session.refresh(rule)
    return AlertCreated(**rule_out(rule).model_dump(), webhook_secret=secret)


async def update_rule(
    container: Container,
    session: AsyncSession,
    actor: Actor,
    rule_id: uuid.UUID,
    data: AlertUpdate,
) -> AlertRule:
    rule = await get_rule(session, actor.scope, rule_id)
    changes = data.model_dump(exclude_unset=True)
    for field in (
        "name",
        "query",
        "service",
        "environment",
        "threshold",
        "window_minutes",
        "sensitivity",
        "min_count",
        "baseline_hours",
        "cooldown_minutes",
        "enabled",
    ):
        if changes.get(field) is not None:
            setattr(rule, field, changes[field])
    if data.email_to is not None:
        rule.email_to = list(data.email_to)
    if data.webhook_url is not None:
        if data.webhook_url:
            rule.webhook_url_sealed = await container.sealer.seal(
                data.webhook_url, _ctx(rule.id, "webhook")
            )
            if rule.webhook_secret_sealed is None:
                rule.webhook_secret_sealed = await container.sealer.seal(
                    "whsec_" + secrets.token_urlsafe(24), _ctx(rule.id, "secret")
                )
        else:
            rule.webhook_url_sealed = None
    if data.slack_url is not None:
        rule.slack_url_sealed = (
            await container.sealer.seal(data.slack_url, _ctx(rule.id, "slack"))
            if data.slack_url
            else None
        )
    audit(session, actor, "alert.updated", "alert_rule", rule.id, fields=sorted(changes))
    await session.commit()
    return rule


async def delete_rule(session: AsyncSession, actor: Actor, rule_id: uuid.UUID) -> None:
    rule = await get_rule(session, actor.scope, rule_id)
    await session.delete(rule)
    audit(session, actor, "alert.deleted", "alert_rule", rule.id, name=rule.name)
    await session.commit()


async def history(
    session: AsyncSession, scope: ProjectScope, *, rule_id: uuid.UUID | None, limit: int
) -> list[AlertHistoryOut]:
    stmt = (
        select(AlertHistory, AlertRule.name)
        .join(AlertRule, AlertRule.id == AlertHistory.rule_id)
        .where(AlertHistory.org_id == scope.org_id, AlertHistory.project_id == scope.project_id)
        .order_by(AlertHistory.at.desc())
        .limit(limit)
    )
    if rule_id is not None:
        stmt = stmt.where(AlertHistory.rule_id == rule_id)
    out: list[AlertHistoryOut] = []
    for row, name in (await session.execute(stmt)).all():
        item = AlertHistoryOut.model_validate(row)
        item.rule_name = name
        out.append(item)
    return out


# ------------------------------------------------------------------------ evaluation


def _decide(rule: AlertRule, m: Measurement, now: datetime) -> str | None:
    """``"fired"``, ``"resolved"`` or ``None`` (nothing to tell anyone)."""
    if m.breached:
        cooled = rule.last_fired_at is None or now - rule.last_fired_at >= timedelta(
            minutes=rule.cooldown_minutes
        )
        if rule.state != "firing" or cooled:
            return "fired"
        return None
    if rule.state == "firing":
        return "resolved"
    return None


async def _notice(
    container: Container, session: AsyncSession, rule: AlertRule, entry: AlertHistory
) -> channels.Notice:
    project = await session.get(Project, rule.project_id)
    project_name = project.name if project else "project"
    link = f"{container.settings.public_url}/alerts/{rule.id}?project={rule.project_id}"
    return channels.Notice(
        event=f"alert.{entry.event}",
        rule_name=rule.name,
        project_name=project_name,
        summary=entry.message,
        link=link,
        payload={
            "alert": {"id": str(rule.id), "name": rule.name, "kind": rule.kind},
            "project": {"id": str(rule.project_id), "name": project_name},
            "value": entry.value,
            "threshold": entry.threshold,
            "expected": entry.expected,
            "zscore": entry.zscore,
            "message": entry.message,
            "at": entry.at.isoformat(),
            "link": link,
        },
    )


async def deliver(
    container: Container, session: AsyncSession, rule: AlertRule, entry: AlertHistory
) -> list[dict[str, Any]]:
    notice = await _notice(container, session, rule, entry)
    outcomes: list[dict[str, Any]] = []
    if rule.email_to:
        outcomes.append(await channels.send_email(container.settings, list(rule.email_to), notice))
    if rule.webhook_url_sealed is not None and rule.webhook_secret_sealed is not None:
        url = await container.sealer.open(rule.webhook_url_sealed, _ctx(rule.id, "webhook"))
        secret = await container.sealer.open(rule.webhook_secret_sealed, _ctx(rule.id, "secret"))
        outcomes.append(
            await channels.send_webhook(container.http, container.settings, url, secret, notice)
        )
    if rule.slack_url_sealed is not None:
        url = await container.sealer.open(rule.slack_url_sealed, _ctx(rule.id, "slack"))
        outcomes.append(await channels.send_slack(container.http, container.settings, url, notice))
    for o in outcomes:
        metrics.alert_deliveries_total.labels(
            channel=o["channel"], outcome="ok" if o["ok"] else "failed"
        ).inc()
    return outcomes


async def _evaluate_locked(
    container: Container, session: AsyncSession, rule: AlertRule, now: datetime
) -> AlertHistory | None:
    scope = ProjectScope(rule.org_id, rule.project_id)
    m = await measure(LogRepository(container.clickhouse), scope, rule, now)
    rule.last_value = m.value
    rule.last_evaluated_at = now
    event = _decide(rule, m, now)
    entry: AlertHistory | None = None
    if event is not None:
        entry = AlertHistory(
            org_id=rule.org_id,
            rule_id=rule.id,
            project_id=rule.project_id,
            at=now,
            event=event,
            value=m.value,
            threshold=m.threshold,
            expected=m.expected,
            zscore=m.zscore,
            message=m.description,
            deliveries=[],
        )
        session.add(entry)
        if event == "fired":
            rule.state = "firing"
            rule.last_fired_at = now
            metrics.alerts_fired_total.labels(kind=rule.kind).inc()
        else:
            rule.state = "ok"
    return entry


async def evaluate_due(container: Container, *, limit: int = 100, force: bool = False) -> int:
    """Evaluate every enabled rule not evaluated in the last ``alert_interval_s``. Each
    rule is claimed with its own row lock, so concurrent workers split the rules between
    them instead of double firing. Returns how many rules were evaluated."""
    now = datetime.now(UTC)
    due_before = now - timedelta(seconds=container.settings.alert_interval_s * 0.9)
    evaluated = 0
    for _ in range(limit):
        async with container.db.sessionmaker() as session:
            stmt = select(AlertRule).where(AlertRule.enabled.is_(True))
            if not force:
                stmt = stmt.where(
                    or_(
                        AlertRule.last_evaluated_at.is_(None),
                        AlertRule.last_evaluated_at < due_before,
                    )
                )
            else:
                stmt = stmt.where(
                    or_(AlertRule.last_evaluated_at.is_(None), AlertRule.last_evaluated_at < now)
                )
            rule = await session.scalar(
                stmt.order_by(AlertRule.last_evaluated_at.nulls_first())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if rule is None:
                break
            try:
                entry = await _evaluate_locked(container, session, rule, now)
            except Exception as exc:
                log.warning(
                    "alert rule evaluation failed, continuing",
                    extra={"rule_id": str(rule.id), "error": str(exc)[:300]},
                )
                await session.rollback()
                async with container.db.sessionmaker() as s2:
                    r2 = await s2.get(AlertRule, rule.id)
                    if r2 is not None:
                        r2.last_evaluated_at = now
                        await s2.commit()
                continue
            await session.commit()
            evaluated += 1
            if entry is not None:
                entry.deliveries = await deliver(container, session, rule, entry)
                await session.commit()
    return evaluated


async def test_rule(
    container: Container, session: AsyncSession, actor: Actor, rule_id: uuid.UUID
) -> AlertHistoryOut:
    """Measure the rule now and send a clearly marked test notification to every target,
    without changing its state."""
    rule = await get_rule(session, actor.scope, rule_id)
    now = datetime.now(UTC)
    m = await measure(
        LogRepository(container.clickhouse), ProjectScope(rule.org_id, rule.project_id), rule, now
    )
    entry = AlertHistory(
        org_id=rule.org_id,
        rule_id=rule.id,
        project_id=rule.project_id,
        at=now,
        event="test",
        value=m.value,
        threshold=m.threshold,
        expected=m.expected,
        zscore=m.zscore,
        message=f"Test notification. Right now: {m.description}",
        deliveries=[],
    )
    session.add(entry)
    await session.flush()
    entry.deliveries = await deliver(container, session, rule, entry)
    audit(session, actor, "alert.tested", "alert_rule", rule.id)
    await session.commit()
    out = AlertHistoryOut.model_validate(entry)
    out.rule_name = rule.name
    return out
