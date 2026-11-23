"""Evidence retrieval and context compression (A3, A4).

An investigation never hands the model the raw log volume. It asks ClickHouse a handful
of targeted questions about the incident window and turns the answers into a small,
numbered evidence pack:

* the **first occurrence** of the current burst of the error group, and its latest one;
* **preceding signals**: warnings and errors from any service shortly before the first
  occurrence, collapsed by message template (400 identical lines become one item with a
  count, its first time and its last time);
* **correlated errors** in other services during the burst, collapsed the same way;
* **change events**: lines mentioning deploys, releases, versions, config, migrations,
  restarts, rollouts and feature flags before the burst;
* the **request trace** of the first occurrence (lines sharing its trace or request id).

Each item points at one real stored line (``event_id``), so every citation the model makes
(``E3``) resolves to a line anyone can open in the Log Explorer. Items are ranked, trimmed
to ``AI_MAX_EVIDENCE_ITEMS`` and to a token budget (``AI_MAX_CONTEXT_TOKENS``), and long
messages are cut to ``AI_MESSAGE_CHARS``. The pack records how much raw volume it stands
for, so the saving is visible.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from logmind.core.config import Settings
from logmind.core.db import ProjectScope
from logmind.errors.models import ErrorGroup
from logmind.logs.repository import LogFilter, LogRepository, StoredEvent

CHANGE_TERMS = [
    "deploy",
    "release",
    "rollout",
    "rolled out",
    "version",
    "config",
    "migration",
    "restart",
    "feature flag",
    "scaled",
]
# A gap this long between two occurrences ends a burst when walking back from the latest.
BURST_GAP = timedelta(minutes=15)
MAX_LOOKBACK = timedelta(hours=6)

PRIORITY = {
    "first_occurrence": 100,
    "occurrence": 90,
    "change": 80,
    "preceding": 60,
    "correlated": 50,
    "trace": 30,
}


@dataclass(slots=True)
class EvidenceItem:
    ref: str
    event_id: str
    timestamp: str
    service: str
    level: str
    kind: str
    message: str
    count: int = 1
    last_timestamp: str | None = None

    def render(self) -> str:
        extra = f" count={self.count}" if self.count > 1 else ""
        if self.last_timestamp and self.count > 1:
            extra += f" last={self.last_timestamp}"
        return (
            f"[{self.ref}] {self.timestamp} service={self.service} level={self.level} "
            f"kind={self.kind}{extra} :: {self.message}"
        )


@dataclass(slots=True)
class EvidencePack:
    items: list[EvidenceItem]
    window_start: str
    window_end: str
    incident_start: str
    raw_lines: int
    raw_tokens_estimate: int
    candidates: int
    context_tokens_estimate: int
    group: dict[str, Any] = field(default_factory=dict)

    def refs(self) -> dict[str, EvidenceItem]:
        return {i.ref: i for i in self.items}

    def render(self) -> str:
        return "\n".join(i.render() for i in self.items)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> EvidencePack:
        items = [EvidenceItem(**i) for i in data.get("items", [])]
        return cls(**{**data, "items": items})


def estimate_tokens(text: str) -> int:
    """About four characters per token for English and log text; providers report the
    real number after the call, this is the budget used before it."""
    return max(1, math.ceil(len(text) / 4))


def _iso(ts: datetime) -> str:
    return ts.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _cut(text: str, limit: int) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= limit else one_line[: limit - 3] + "..."


def _stack_head(stack: str, frames: int = 3) -> str:
    lines = [ln.strip() for ln in stack.strip().splitlines() if ln.strip()]
    if not lines:
        return ""
    keep = lines[-frames - 1 :] if lines[0].startswith("Traceback") else lines[: frames + 1]
    return " | ".join(keep)


@dataclass(slots=True)
class _Candidate:
    kind: str
    event_id: uuid.UUID
    timestamp: datetime
    service: str
    level: str
    message: str
    count: int = 1
    last_timestamp: datetime | None = None

    @property
    def score(self) -> float:
        base = PRIORITY[self.kind]
        if self.level in ("error", "fatal"):
            base += 5
        return base + min(math.log10(max(self.count, 1)) * 4, 12)


def find_incident_start(occurrences: list[datetime]) -> datetime | None:
    """Walk back from the latest occurrence until a gap of ``BURST_GAP``: the start of
    the current burst, not the first time this error was ever seen."""
    if not occurrences:
        return None
    times = sorted(occurrences)
    start = times[-1]
    for ts in reversed(times[:-1]):
        if start - ts > BURST_GAP:
            break
        start = ts
    return start


async def collect(
    repo: LogRepository,
    scope: ProjectScope,
    settings: Settings,
    *,
    group: ErrorGroup | None,
    window_minutes: int,
    now: datetime | None = None,
) -> EvidencePack:
    now = now or datetime.now(UTC)
    lookback = timedelta(minutes=window_minutes)
    candidates: list[_Candidate] = []
    first: StoredEvent | None = None

    if group is not None:
        end = group.last_seen + timedelta(minutes=2)
        occ_filter = LogFilter(
            start=max(group.first_seen, group.last_seen - MAX_LOOKBACK) - timedelta(seconds=1),
            end=end,
            fingerprint=group.fingerprint,
        )
        recent = await repo.search(scope, occ_filter, limit=2000)
        incident_start = find_incident_start([e.timestamp for e in recent]) or group.first_seen
        window_start = incident_start - lookback
        burst = [e for e in recent if e.timestamp >= incident_start]
        if burst:
            first = min(burst, key=lambda e: e.timestamp)
            latest = max(burst, key=lambda e: e.timestamp)
            head = _stack_head(first.stack_trace)
            candidates.append(
                _Candidate(
                    "first_occurrence",
                    first.event_id,
                    first.timestamp,
                    first.service,
                    first.level,
                    first.message + (f" | {head}" if head else ""),
                    count=len(burst),
                    last_timestamp=latest.timestamp,
                )
            )
            if latest.event_id != first.event_id:
                candidates.append(
                    _Candidate(
                        "occurrence",
                        latest.event_id,
                        latest.timestamp,
                        latest.service,
                        latest.level,
                        latest.message,
                    )
                )
        exclude = group.fingerprint
    else:
        end = now
        incident_start = now - lookback
        window_start = incident_start
        exclude = ""

    raw_lines, raw_chars = await repo.volume(scope, LogFilter(start=window_start, end=end))

    async def templates(f: LogFilter, kind: str, limit: int) -> None:
        for t in await repo.templates(scope, f, limit=limit):
            candidates.append(
                _Candidate(
                    kind,
                    t["first_id"],
                    t["first_ts"],
                    t["service"],
                    t["level"],
                    t["first_message"],
                    count=t["count"],
                    last_timestamp=t["last_ts"],
                )
            )

    # Around a group: signals up to just after the first occurrence. For a free question
    # there is no first occurrence, so the whole window counts.
    signal_end = incident_start + timedelta(minutes=2) if group is not None else end
    await templates(
        LogFilter(
            start=window_start,
            end=signal_end,
            levels=["warn", "error", "fatal"],
            exclude_fingerprint=exclude,
        ),
        "preceding",
        30,
    )
    if group is not None:
        await templates(
            LogFilter(
                start=signal_end,
                end=end,
                levels=["error", "fatal"],
                exclude_fingerprint=exclude,
            ),
            "correlated",
            15,
        )
    await templates(
        LogFilter(
            start=window_start,
            end=signal_end,
            levels=["info", "warn", "debug"],
            any_terms=CHANGE_TERMS,
        ),
        "change",
        10,
    )
    if first is not None and (first.trace_id or first.request_id):
        trace = await repo.search(
            scope,
            LogFilter(
                start=first.timestamp - timedelta(minutes=10),
                end=first.timestamp + timedelta(minutes=2),
                trace_id=first.trace_id,
                request_id="" if first.trace_id else first.request_id,
            ),
            limit=15,
            ascending=True,
        )
        for e in trace:
            candidates.append(
                _Candidate("trace", e.event_id, e.timestamp, e.service, e.level, e.message)
            )

    items = select_items(candidates, settings)
    rendered = "\n".join(i.render() for i in items)
    return EvidencePack(
        items=items,
        window_start=_iso(window_start),
        window_end=_iso(end),
        incident_start=_iso(incident_start),
        raw_lines=raw_lines,
        raw_tokens_estimate=math.ceil(raw_chars / 4) + raw_lines * 12,
        candidates=len(candidates),
        context_tokens_estimate=estimate_tokens(rendered) if items else 0,
        group=_group_summary(group),
    )


def _group_summary(group: ErrorGroup | None) -> dict[str, Any]:
    if group is None:
        return {}
    return {
        "id": str(group.id),
        "title": group.title,
        "exception_type": group.exception_type,
        "culprit": group.culprit,
        "services": list(group.services),
        "occurrences": group.occurrences,
        "first_seen": _iso(group.first_seen),
        "last_seen": _iso(group.last_seen),
    }


def select_items(
    candidates: list[_Candidate], settings: Settings, *, start_ref: int = 1
) -> list[EvidenceItem]:
    """Deduplicate by event id, keep the highest-ranked items that fit the item cap and
    the token budget, then number them in time order (E1 is the earliest)."""
    seen: set[uuid.UUID] = set()
    unique: list[_Candidate] = []
    for c in sorted(candidates, key=lambda c: -c.score):
        if c.event_id in seen:
            continue
        seen.add(c.event_id)
        unique.append(c)
    chosen: list[_Candidate] = []
    budget = settings.ai_max_context_tokens
    used = 0
    for c in unique:
        if len(chosen) >= settings.ai_max_evidence_items:
            break
        line_tokens = estimate_tokens(_cut(c.message, settings.ai_message_chars)) + 30
        if used + line_tokens > budget:
            continue
        chosen.append(c)
        used += line_tokens
    chosen.sort(key=lambda c: (c.timestamp, str(c.event_id)))
    return [
        EvidenceItem(
            ref=f"E{start_ref + i}",
            event_id=str(c.event_id),
            timestamp=_iso(c.timestamp),
            service=c.service,
            level=c.level,
            kind=c.kind,
            message=_cut(c.message, settings.ai_message_chars),
            count=c.count,
            last_timestamp=_iso(c.last_timestamp) if c.last_timestamp else None,
        )
        for i, c in enumerate(chosen)
    ]


async def collect_more_before(
    repo: LogRepository,
    scope: ProjectScope,
    settings: Settings,
    pack: EvidencePack,
    *,
    window_minutes: int,
) -> list[EvidenceItem]:
    """For a follow-up about what happened earlier ("what changed before this
    started"): change events and warnings in a wider window before the incident, numbered
    after the pack's existing items. Lines already in the pack are not repeated."""
    incident_start = datetime.fromisoformat(pack.incident_start.replace("Z", "+00:00"))
    start = incident_start - timedelta(minutes=window_minutes * 3)
    candidates: list[_Candidate] = []
    for f, kind in (
        (
            LogFilter(start=start, end=incident_start, any_terms=CHANGE_TERMS),
            "change",
        ),
        (
            LogFilter(start=start, end=incident_start, levels=["warn", "error", "fatal"]),
            "preceding",
        ),
    ):
        for t in await repo.templates(scope, f, limit=20):
            candidates.append(
                _Candidate(
                    kind,
                    t["first_id"],
                    t["first_ts"],
                    t["service"],
                    t["level"],
                    t["first_message"],
                    count=t["count"],
                    last_timestamp=t["last_ts"],
                )
            )
    known = {i.event_id for i in pack.items}
    fresh = [c for c in candidates if str(c.event_id) not in known]
    budget_settings = settings.model_copy(
        update={"ai_max_evidence_items": max(5, settings.ai_max_evidence_items // 3)}
    )
    return select_items(fresh, budget_settings, start_ref=len(pack.items) + 1)
