"""Citation discipline (A3, A12): what the model says only reaches a user when it is
backed by evidence that exists.

The model's JSON is parsed leniently (code fences and leading prose are tolerated), then
every finding, timeline entry and the root cause is checked against the evidence pack:
an id the pack does not contain is dropped and counted as rejected; a statement left
without any valid id is removed from the report and listed under ``discarded``. Every
surviving citation is resolved to the stored line it points at (event id, timestamp,
service, level, message), so the report carries its own proof and the verify endpoint can
re-read each line from ClickHouse and compare.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import orjson

from logmind.investigations.evidence import EvidenceItem

_REF = re.compile(r"^E\d{1,4}$")


class ReportFormatError(ValueError):
    """The model's answer is not the JSON object it was asked for."""


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ReportFormatError("the model did not answer with a JSON object")
    try:
        data = orjson.loads(cleaned[start : end + 1])
    except orjson.JSONDecodeError as exc:
        raise ReportFormatError("the model's JSON could not be parsed") from exc
    if not isinstance(data, dict):
        raise ReportFormatError("the model did not answer with a JSON object")
    return data


@dataclass(slots=True)
class Validation:
    refs: dict[str, EvidenceItem]
    rejected: list[str] = field(default_factory=list)
    discarded: list[str] = field(default_factory=list)
    used: set[str] = field(default_factory=set)

    def check(self, raw: Any) -> list[str]:
        """The valid ids among ``raw``; anything else is recorded as rejected."""
        valid: list[str] = []
        for r in raw if isinstance(raw, list) else []:
            ref = str(r).strip().strip("[]").upper()
            if _REF.match(ref) and ref in self.refs:
                if ref not in valid:
                    valid.append(ref)
            else:
                self.rejected.append(str(r)[:20])
        self.used.update(valid)
        return valid

    def citations(self) -> list[dict[str, Any]]:
        def order(ref: str) -> int:
            return int(ref[1:])

        return [
            {
                "ref": ref,
                "event_id": self.refs[ref].event_id,
                "timestamp": self.refs[ref].timestamp,
                "service": self.refs[ref].service,
                "level": self.refs[ref].level,
                "kind": self.refs[ref].kind,
                "count": self.refs[ref].count,
                "message": self.refs[ref].message,
            }
            for ref in sorted(self.used, key=order)
        ]


def _text(value: Any, limit: int = 2000) -> str:
    return str(value or "").strip()[:limit]


def _statements(items: Any, v: Validation, key: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        text = _text(item.get(key), 600)
        if not text:
            continue
        refs = v.check(item.get("evidence"))
        if refs:
            out.append({key: text, "evidence": refs})
        else:
            v.discarded.append(text)
    return out


def _confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def validate_report(
    data: dict[str, Any], refs: dict[str, EvidenceItem]
) -> tuple[dict[str, Any], Validation]:
    v = Validation(refs)
    findings = _statements(data.get("findings"), v, "statement")
    timeline = _statements(data.get("timeline"), v, "description")
    # The server, not the model, decides when each timeline entry happened: the time of
    # the earliest line it cites.
    for entry in timeline:
        entry["at"] = min(refs[r].timestamp for r in entry["evidence"])
    timeline.sort(key=lambda e: e["at"])
    root_refs = v.check(data.get("root_cause_evidence"))
    root_cause = _text(data.get("root_cause"), 600)
    if root_cause and not root_refs:
        v.discarded.append(root_cause)
        root_cause = ""
    report = {
        "summary": _text(data.get("summary"), 1200),
        "root_cause": root_cause,
        "root_cause_evidence": root_refs,
        "confidence": _confidence(data.get("confidence")) if root_cause else 0.0,
        "impact": _text(data.get("impact"), 600),
        "findings": findings,
        "timeline": timeline,
        "suggested_fixes": [_text(s, 400) for s in data.get("suggested_fixes") or [] if _text(s)][
            :6
        ],
        "follow_up_questions": [
            _text(s, 300) for s in data.get("follow_up_questions") or [] if _text(s)
        ][:5],
        "citations": v.citations(),
        "discarded": v.discarded[:20],
        "rejected_citations": v.rejected[:50],
    }
    return report, v


def validate_answer(
    data: dict[str, Any], refs: dict[str, EvidenceItem]
) -> tuple[dict[str, Any], Validation]:
    v = Validation(refs)
    findings = _statements(data.get("findings"), v, "statement")
    answer = {
        "answer": _text(data.get("answer"), 2000),
        "findings": findings,
        "confidence": _confidence(data.get("confidence")) if findings else 0.0,
        "citations": v.citations(),
        "discarded": v.discarded[:20],
        "rejected_citations": v.rejected[:50],
    }
    return answer, v
