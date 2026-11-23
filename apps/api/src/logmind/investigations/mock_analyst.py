"""The deterministic mock analyst (A11): how the built-in ``mock`` provider and the
``mockai`` service answer LogMind's prompts, with no model and no key.

It reads the evidence pack back out of the prompt (the ``[E1] <time> service=... level=...
kind=... :: message`` lines ``evidence.py`` renders), and reasons the way the prompt asks a
model to: the first occurrence is the symptom; the best-scoring earlier signal from
another service (connection pools, timeouts, refusals, exhaustion) is the likely cause; a
change event before that (a deploy, a config change) is the likely trigger. Every
statement cites the ids it used, so the server's citation checks apply to the mock exactly
as they do to a real model. A question containing ``[mock:fabricate]`` makes it cite an id
that does not exist, which the tests use to prove fabricated citations are dropped.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass

_LINE = re.compile(
    r"^\[(?P<ref>E\d+)\] (?P<ts>\S+) service=(?P<service>\S+) level=(?P<level>\S+) "
    r"kind=(?P<kind>\S+)(?: count=(?P<count>\d+))?(?: last=(?P<last>\S+))? :: (?P<msg>.*)$",
    re.MULTILINE,
)
_QUESTION = re.compile(r"^Question: (?P<q>.*)$", re.MULTILINE)
CAUSE_WORDS = (
    "pool",
    "exhausted",
    "timeout",
    "timed out",
    "refused",
    "unavailable",
    "deadlock",
    "out of memory",
    "oom",
    "latency",
    "slow",
    "saturat",
    "throttl",
    "503",
    "connection",
    "disk",
    "quota",
    "circuit",
    "retry",
)
RELEASE_WORDS = ("deploy", "release", "rollout", "rolling out", "version")
CHANGE_WORDS = ("before", "change", "changed", "deploy", "release", "earlier", "trigger", "version")


@dataclass(frozen=True, slots=True)
class Item:
    ref: str
    ts: str
    service: str
    level: str
    kind: str
    count: int
    msg: str


def parse_items(text: str) -> list[Item]:
    return [
        Item(
            m["ref"],
            m["ts"],
            m["service"],
            m["level"],
            m["kind"],
            int(m["count"] or 1),
            m["msg"].strip(),
        )
        for m in _LINE.finditer(text)
    ]


def _hms(ts: str) -> str:
    """``2026-11-16T14:30:48.349Z`` as ``14:30:48 UTC``."""
    return f"{ts[11:19]} UTC" if len(ts) >= 19 else ts


def _short(msg: str, n: int = 110) -> str:
    head = msg.split(" | ")[0]
    return head if len(head) <= n else head[: n - 3] + "..."


def _cause_score(item: Item) -> float:
    lowered = item.msg.lower()
    score = 3.0 * sum(1 for w in CAUSE_WORDS if w in lowered)
    score += {"fatal": 2, "error": 1.5, "warn": 1}.get(item.level, 0)
    score += min(math.log10(max(item.count, 1)), 3)
    return score


def _analyse(items: list[Item]) -> tuple[Item | None, Item | None, Item | None, Item | None]:
    first = next((i for i in items if i.kind == "first_occurrence"), None)
    latest = next((i for i in reversed(items) if i.kind == "occurrence"), None)
    target_ts = first.ts if first else (items[-1].ts if items else "")
    target_service = first.service if first else ""
    signals = [
        i
        for i in items
        if i.kind in ("preceding", "correlated")
        and i.ts <= target_ts
        and (i.service != target_service or not target_service)
    ]
    signals = signals or [i for i in items if i.kind in ("preceding", "correlated")]
    cause = max(signals, key=_cause_score) if signals else None
    if cause is not None and _cause_score(cause) < 3:
        cause = None
    before = cause.ts if cause else target_ts
    changes = [i for i in items if i.kind == "change" and i.ts <= before]
    # A deploy or release explains more than a routine config line logged during it.
    releases = [i for i in changes if any(w in i.msg.lower() for w in RELEASE_WORDS)]
    change = (releases or changes)[-1] if changes else None
    return first, latest, cause, change


def _fixes(cause: Item | None, first: Item | None) -> list[str]:
    text = ((cause.msg if cause else "") + " " + (first.msg if first else "")).lower()
    fixes: list[str] = []
    if "pool" in text:
        fixes.append(
            "Check the database connection pool settings and look for connections that are "
            "not returned (a leak), especially in code changed by the latest release."
        )
    if "timeout" in text or "timed out" in text:
        fixes.append(
            "Put a timeout budget and a circuit breaker on the upstream call so callers fail "
            "fast instead of piling up."
        )
    if "refused" in text or "unavailable" in text:
        fixes.append("Confirm the upstream service is running and passing its health checks.")
    if "memory" in text or "oom" in text:
        fixes.append("Profile memory use and raise the container memory limit if needed.")
    fixes.append("Roll back the most recent change to the failing path if the errors continue.")
    return fixes[:4]


def investigate(text: str) -> dict[str, object]:
    items = parse_items(text)
    question = (m["q"] if (m := _QUESTION.search(text)) else "").lower()
    if not items:
        return {
            "summary": "The evidence pack is empty, so there is nothing to explain yet.",
            "root_cause": "",
            "root_cause_evidence": [],
            "confidence": 0.0,
            "impact": "",
            "findings": [],
            "timeline": [],
            "suggested_fixes": ["Widen the window or wait for more logs."],
            "follow_up_questions": [],
        }
    first, latest, cause, change = _analyse(items)
    symptom = first or items[-1]
    findings: list[dict[str, object]] = [
        {
            "statement": (
                f"{symptom.service} started failing at {_hms(symptom.ts)} with "
                f'"{_short(symptom.msg)}"'
                + (f" ({symptom.count} times in this burst)" if symptom.count > 1 else "")
            ),
            "evidence": [symptom.ref] + ([latest.ref] if latest else []),
        }
    ]
    timeline: list[dict[str, object]] = []
    root_refs = [symptom.ref]
    if cause:
        findings.append(
            {
                "statement": (
                    f'{cause.service} logged "{_short(cause.msg)}"'
                    + (f" {cause.count} times" if cause.count > 1 else "")
                    + f" starting {_hms(cause.ts)}, before the first failure"
                ),
                "evidence": [cause.ref],
            }
        )
        root_refs.insert(0, cause.ref)
    if change:
        findings.append(
            {
                "statement": (
                    f'A change was logged shortly before: "{_short(change.msg)}" ({change.service})'
                ),
                "evidence": [change.ref],
            }
        )
        root_refs.insert(0, change.ref)
        timeline.append({"description": f"Change in {change.service}", "evidence": [change.ref]})
    if cause:
        timeline.append(
            {
                "description": f"{cause.service} degraded: {_short(cause.msg, 70)}",
                "evidence": [cause.ref],
            }
        )
    timeline.append({"description": f"{symptom.service} begins failing", "evidence": [symptom.ref]})
    if latest:
        timeline.append({"description": "Latest occurrence", "evidence": [latest.ref]})
    if cause and change:
        root = (
            f"{_short(change.msg, 80)} was followed by {cause.service} reporting "
            f'"{_short(cause.msg, 80)}", which made {symptom.service} fail.'
        )
        confidence = 0.78
    elif cause:
        root = (
            f'{cause.service} reported "{_short(cause.msg, 90)}" just before {symptom.service} '
            "started failing; the failures are downstream of it."
        )
        confidence = 0.62
    else:
        root = (
            f"The evidence shows the failure in {symptom.service} itself; no earlier signal "
            "from another service explains it."
        )
        confidence = 0.35
    if "[mock:fabricate]" in question:
        findings.append({"statement": "An unrelated cache node crashed.", "evidence": ["E999"]})
    services = sorted(
        {i.service for i in items if i.kind in ("first_occurrence", "occurrence", "correlated")}
    )
    return {
        "summary": (
            f'{symptom.service} is failing with "{_short(symptom.msg, 80)}". '
            + (
                f"It follows a degradation in {cause.service}."
                if cause
                else "No upstream cause was found in the window."
            )
        ),
        "root_cause": root,
        "root_cause_evidence": root_refs,
        "confidence": confidence,
        "impact": "Requests handled by "
        + ", ".join(services or [symptom.service])
        + " during the incident window.",
        "findings": findings,
        "timeline": timeline,
        "suggested_fixes": _fixes(cause, first),
        "follow_up_questions": [
            "What changed before this started?",
            "Is it still happening?",
            "Which other services were affected?",
        ],
    }


def followup(text: str) -> dict[str, object]:
    items = parse_items(text)
    question = (m["q"] if (m := _QUESTION.search(text)) else "").lower()
    first, latest, cause, _ = _analyse(items)
    findings: list[dict[str, object]] = []
    if any(w in question for w in CHANGE_WORDS):
        anchor = first.ts if first else (items[-1].ts if items else "")
        changes = [i for i in items if i.kind == "change" and i.ts <= anchor]
        if changes:
            for c in changes[-3:]:
                findings.append(
                    {
                        "statement": f'{_hms(c.ts)}: {c.service} logged "{_short(c.msg)}"',
                        "evidence": [c.ref],
                    }
                )
            answer = (
                f"Before the failures began, {len(changes)} change event(s) were logged; the most "
                f'recent was "{_short(changes[-1].msg, 90)}" in {changes[-1].service} '
                f"at {_hms(changes[-1].ts)}."
            )
        else:
            earlier = [i for i in items if i.kind == "preceding" and i.ts <= anchor]
            for e in earlier[:3]:
                findings.append(
                    {
                        "statement": f'{_hms(e.ts)}: {e.service} logged "{_short(e.msg)}"',
                        "evidence": [e.ref],
                    }
                )
            answer = "No deploy or configuration change was logged before the failures began." + (
                " The earliest warning signs are listed below." if earlier else ""
            )
    elif "still" in question or "now" in question or "ongoing" in question:
        last = latest or first
        if last:
            findings.append(
                {
                    "statement": f"The latest occurrence is at {_hms(last.ts)}",
                    "evidence": [last.ref],
                }
            )
        answer = (
            f"The most recent occurrence in the evidence is at {_hms(last.ts)}."
            if last
            else "No occurrences are in the evidence."
        )
    elif "service" in question or "affected" in question or "other" in question:
        hit = [i for i in items if i.kind in ("first_occurrence", "occurrence", "correlated")]
        for i in hit[:4]:
            findings.append({"statement": f'{i.service}: "{_short(i.msg)}"', "evidence": [i.ref]})
        answer = (
            "Affected services: " + ", ".join(sorted({i.service for i in hit})) + "."
            if hit
            else "Only one service appears in the evidence."
        )
    else:
        if first:
            findings.append(
                {
                    "statement": f"{first.service} failed first at {_hms(first.ts)}",
                    "evidence": [first.ref],
                }
            )
        if cause:
            findings.append(
                {"statement": f'{cause.service}: "{_short(cause.msg)}"', "evidence": [cause.ref]}
            )
        answer = (
            "The evidence points to the same chain as the original report."
            if findings
            else "The evidence does not answer this."
        )
    if "[mock:fabricate]" in question:
        findings.append({"statement": "A disk filled up on an unnamed host.", "evidence": ["E999"]})
    return {"answer": answer, "findings": findings, "confidence": 0.7 if findings else 0.0}


def respond(system: str, turns: list[tuple[str, str]]) -> str:
    """The answer to a prompt given its ``system`` text and ``(role, content)`` turns."""
    user = "\n".join(content for role, content in turns if role == "user")
    if system.startswith("TASK: investigate"):
        return json.dumps(investigate(user))
    if system.startswith("TASK: followup"):
        return json.dumps(followup(user))
    if system.startswith("TASK: ping"):
        return "ok"
    return json.dumps({"answer": "This mock only answers LogMind prompts."})
