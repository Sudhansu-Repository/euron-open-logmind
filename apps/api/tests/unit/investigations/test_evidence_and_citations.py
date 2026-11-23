"""A3, A4, A12 at the unit level: evidence selection and compression, citation checks,
the deterministic analyst and the prompts."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from logmind.core.config import Settings
from logmind.investigations import mock_analyst
from logmind.investigations.citations import (
    ReportFormatError,
    parse_json_object,
    validate_answer,
    validate_report,
)
from logmind.investigations.evidence import (
    EvidenceItem,
    EvidencePack,
    _Candidate,
    estimate_tokens,
    find_incident_start,
    select_items,
)
from logmind.investigations.prompt import followup_messages, investigate_messages

T0 = datetime(2026, 11, 16, 10, 0, tzinfo=UTC)


def cand(
    kind: str, minutes: float, msg: str, count: int = 1, service: str = "svc", level: str = "warn"
) -> _Candidate:
    return _Candidate(
        kind, uuid.uuid4(), T0 + timedelta(minutes=minutes), service, level, msg, count=count
    )


def pack(items: list[EvidenceItem]) -> EvidencePack:
    return EvidencePack(
        items=items,
        window_start="2026-11-16T09:00:00.000Z",
        window_end="2026-11-16T10:30:00.000Z",
        incident_start="2026-11-16T10:05:00.000Z",
        raw_lines=12000,
        raw_tokens_estimate=400000,
        candidates=len(items),
        context_tokens_estimate=900,
        group={"title": "Timeout", "services": ["checkout"], "occurrences": 40},
    )


def test_incident_start_is_the_start_of_the_current_burst() -> None:
    times = [T0 - timedelta(hours=5), T0, T0 + timedelta(minutes=5), T0 + timedelta(minutes=12)]
    assert find_incident_start(times) == T0
    assert find_incident_start([]) is None


def test_selection_ranks_caps_budgets_and_numbers_in_time_order() -> None:
    settings = Settings(
        environment="test", ai_max_evidence_items=5, ai_max_context_tokens=500, ai_message_chars=80
    )
    dup = cand("trace", 9, "same line")
    candidates = [
        cand("trace", 1, "trace " * 40),
        cand("preceding", 3, "db pool exhausted", count=400),
        cand("change", 2, "deploy v2"),
        cand("first_occurrence", 5, "timeout", level="error"),
        cand("occurrence", 8, "timeout again", level="error"),
        cand("correlated", 6, "auth 500", level="error"),
        cand("preceding", 4, "slow query"),
        dup,
        _Candidate("trace", dup.event_id, dup.timestamp, "svc", "info", "same line"),
    ]
    items = select_items(candidates, settings)
    assert len(items) == 5
    assert [i.ref for i in items] == ["E1", "E2", "E3", "E4", "E5"]
    assert [i.timestamp for i in items] == sorted(i.timestamp for i in items)
    kinds = {i.kind for i in items}
    assert {"first_occurrence", "occurrence", "change"} <= kinds and "trace" not in kinds
    pool = next(i for i in items if i.kind == "preceding" and i.count == 400)
    assert pool.message == "db pool exhausted"
    assert all(len(i.message) <= 80 for i in items)
    assert estimate_tokens("abcd" * 10) == 10
    tight = select_items(
        candidates,
        Settings(
            environment="test",
            ai_max_context_tokens=500,
            ai_max_evidence_items=40,
            ai_message_chars=4000,
        ),
    )
    assert sum(estimate_tokens(i.message) + 30 for i in tight) <= 500


def test_pack_round_trip_and_render() -> None:
    item = EvidenceItem(
        "E1",
        str(uuid.uuid4()),
        "2026-11-16T10:00:00.000Z",
        "db",
        "warn",
        "preceding",
        "pool",
        3,
        "2026-11-16T10:01:00.000Z",
    )
    p = pack([item])
    assert EvidencePack.from_json(p.to_json()) == p
    assert "count=3 last=2026-11-16T10:01:00.000Z :: pool" in p.render()
    assert p.refs() == {"E1": item}


def _items() -> list[EvidenceItem]:
    rows = [
        (
            "E1",
            "09:40",
            "payments",
            "info",
            "change",
            1,
            "deploy started: payments version v2.14.0",
        ),
        (
            "E2",
            "09:44",
            "payments",
            "warn",
            "preceding",
            25,
            "db connection pool exhausted (max=20)",
        ),
        ("E3", "09:45", "search", "warn", "preceding", 3, "cache miss ratio high"),
        (
            "E4",
            "09:47",
            "checkout",
            "error",
            "first_occurrence",
            40,
            "order failed: payment gateway timeout | Traceback",
        ),
        ("E5", "09:57", "checkout", "error", "occurrence", 1, "order failed again"),
        ("E6", "09:50", "auth", "error", "correlated", 2, "token refresh failed"),
    ]
    return [
        EvidenceItem(r, str(uuid.uuid4()), f"2026-11-16T{t}:00.000Z", s, lv, k, m, c)
        for r, t, s, lv, k, c, m in rows
    ]


def test_mock_analyst_finds_the_chain_and_cites_it() -> None:
    p = pack(_items())
    system, user = investigate_messages(p, "")
    assert system.content.startswith("TASK: investigate")
    data = json.loads(mock_analyst.respond(system.content, [("user", user.content)]))
    assert data["root_cause_evidence"] == ["E1", "E2", "E4"]
    assert "v2.14.0" in data["root_cause"] and data["confidence"] == 0.78
    report, v = validate_report(data, p.refs())
    assert v.rejected == [] and v.discarded == []
    assert [e["at"] for e in report["timeline"]] == sorted(e["at"] for e in report["timeline"])
    assert {c["ref"] for c in report["citations"]} >= {"E1", "E2", "E4", "E5"}
    assert any("pool" in f for f in report["suggested_fixes"])


def test_mock_analyst_without_a_cause_and_with_an_empty_pack() -> None:
    only = [i for i in _items() if i.kind in ("first_occurrence", "occurrence")]
    data = mock_analyst.investigate(pack(only).render())
    assert data["confidence"] == 0.35
    assert mock_analyst.investigate("")["root_cause"] == ""
    assert json.loads(mock_analyst.respond("TASK: other", []))["answer"]
    assert mock_analyst.respond("TASK: ping", []) == "ok"


@pytest.mark.parametrize(
    ("question", "expect"),
    [
        ("What changed before this started?", "E1"),
        ("Is it still happening?", "E5"),
        ("Which other services were affected?", "E6"),
        ("Explain again", "E4"),
    ],
)
def test_mock_followups(question: str, expect: str) -> None:
    p = pack(_items())
    system, user = followup_messages(
        p, [], {"root_cause": "x", "summary": "y"}, [("q", "a")], question
    )
    assert system.content.startswith("TASK: followup") and "Earlier follow-ups" in user.content
    data = json.loads(mock_analyst.respond(system.content, [("user", user.content)]))
    answer, v = validate_answer(data, p.refs())
    assert any(expect in f["evidence"] for f in answer["findings"]), answer
    assert v.rejected == []


def test_followup_about_changes_with_no_change_lines() -> None:
    items = [i for i in _items() if i.kind != "change"]
    data = mock_analyst.followup(pack(items).render() + "\nQuestion: what changed before?")
    assert "No deploy" in str(data["answer"])


def test_citations_drop_fabrications_and_ungrounded_statements() -> None:
    refs = pack(_items()).refs()
    data = {
        "summary": "s",
        "root_cause": "made up",
        "root_cause_evidence": ["E99"],
        "confidence": 7,
        "findings": [
            {"statement": "real", "evidence": ["e2", "[E4]", "E2"]},
            {"statement": "fake", "evidence": ["E42", 3]},
            {"statement": "", "evidence": ["E1"]},
            "not a dict",
        ],
        "timeline": [{"description": "t", "evidence": ["E5", "E1"]}],
        "suggested_fixes": ["a", ""],
        "follow_up_questions": ["q"],
    }
    report, v = validate_report(data, refs)
    assert report["findings"] == [{"statement": "real", "evidence": ["E2", "E4"]}]
    assert report["root_cause"] == "" and report["confidence"] == 0.0
    assert set(v.rejected) == {"E99", "E42", "3"}
    assert set(report["discarded"]) == {"fake", "made up"}
    assert report["timeline"][0]["at"] == refs["E1"].timestamp
    assert report["suggested_fixes"] == ["a"]
    answer, _ = validate_answer({"answer": "a", "findings": [], "confidence": "x"}, refs)
    assert answer["confidence"] == 0.0


def test_lenient_json_parsing() -> None:
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('Sure! {"a": {"b": 2}} hope it helps') == {"a": {"b": 2}}
    for bad in ("no json here", "{broken", "[1, 2]"):
        with pytest.raises(ReportFormatError):
            parse_json_object(bad)
