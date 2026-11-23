"""A3, A4, A5, A11, A12: AI investigations against the mock provider, with every
citation checked against the stored logs, the compression measured, and follow-ups held
to the same citation discipline."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from tests.integration.conftest import Api, World
from tests.integration.helpers import incident, log, run_jobs, send

pytestmark = pytest.mark.integration


async def _incident_group(
    api: Api, world: World, noise: int = 300
) -> tuple[dict[str, Any], dict[str, Any]]:
    lines, facts = incident(datetime.now(UTC), noise=noise)
    for i in range(0, len(lines), 900):
        await send(api.client, world.key, lines[i : i + 900])
    groups = await api.ok("GET", "/api/v1/errors", params={**world.q, "q": "PaymentGatewayTimeout"})
    assert groups["total"] == 1
    return groups["items"][0], facts


async def _investigate(api: Api, world: World, group_id: str, question: str = "") -> dict[str, Any]:
    queued = await api.ok(
        "POST",
        "/api/v1/ai/investigate",
        {"project_id": world.project_id, "error_group_id": group_id, "question": question},
        status=202,
    )
    assert queued["status"] == "queued"
    assert await run_jobs(api.app) == 1
    out: dict[str, Any] = await api.ok("GET", f"/api/v1/ai/investigations/{queued['id']}")
    return out


async def test_a5_investigation_needs_a_provider_but_everything_else_works_without(
    api: Api, world: World
) -> None:
    group, _ = await _incident_group(api, world, noise=40)
    resp = await api.client.post(
        "/api/v1/ai/investigate",
        json={"project_id": world.project_id, "error_group_id": group["id"]},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "no_ai_provider"
    assert "Settings" in resp.json()["error"]["message"]
    page = await api.ok("GET", "/api/v1/logs", params={**world.q, "q": "pool exhausted"})
    assert len(page["items"]) == 25
    overview = await api.ok("GET", "/api/v1/analytics/overview", params=world.q)
    assert overview["ai_provider_configured"] is False
    assert overview["open_error_groups"] == 1


async def test_a3_a11_every_cited_line_is_real_and_the_cause_chain_is_found(
    api: Api,
    world: World,
    mock_provider: dict[str, Any],
) -> None:
    group, _ = await _incident_group(api, world)
    inv = await _investigate(api, world, group["id"])
    assert inv["status"] == "completed", inv["error"]
    report = inv["report"]
    assert inv["grounded"] is True
    assert report["citations"], "the report cites nothing"
    cited = {c["ref"]: c for c in report["citations"]}
    for section in ("findings", "timeline"):
        for entry in report[section]:
            assert entry["evidence"] and all(r in cited for r in entry["evidence"])
    assert report["root_cause_evidence"]
    root_messages = " ".join(cited[r]["message"] for r in report["root_cause_evidence"])
    assert "deploy started: payments version v2.14.0" in root_messages
    assert "connection pool exhausted" in root_messages
    # Independently, through the public log API: every cited event id is a stored line of
    # this project with the same timestamp and text.
    for c in report["citations"]:
        line = await api.ok(
            "GET", f"/api/v1/logs/{c['event_id']}", params={**world.q, "at": c["timestamp"]}
        )
        assert " ".join(line["message"].split()).startswith(
            c["message"].split(" | ")[0].removesuffix("...")
        )
        assert line["service"] == c["service"]
    verified = await api.ok("GET", f"/api/v1/ai/investigations/{inv['id']}/verify")
    assert verified["all_verified"] is True
    assert verified["checked"] == len(report["citations"])
    # The evidence shown with the report is the same set of real lines.
    evidence_ids = {e["event_id"] for e in inv["evidence"]}
    assert {c["event_id"] for c in report["citations"]} <= evidence_ids


async def test_a3_fabricated_citations_are_dropped_not_shown(
    api: Api,
    world: World,
    mock_provider: dict[str, Any],
) -> None:
    group, _ = await _incident_group(api, world, noise=40)
    inv = await _investigate(api, world, group["id"], question="Why? [mock:fabricate]")
    assert inv["status"] == "completed"
    assert inv["rejected_citations"] >= 1
    assert "E999" in inv["report"]["rejected_citations"]
    assert "An unrelated cache node crashed." in inv["report"]["discarded"]
    assert all("cache node" not in f["statement"] for f in inv["report"]["findings"]), (
        "a statement with only a fabricated citation reached the report"
    )
    assert inv["grounded"] is False


async def test_a4_context_is_compressed_and_tokens_are_recorded(
    api: Api,
    world: World,
    mock_provider: dict[str, Any],
) -> None:
    group, _ = await _incident_group(api, world, noise=900)
    inv = await _investigate(api, world, group["id"])
    assert inv["raw_lines"] >= 900
    assert 0 < inv["evidence_count"] <= 40
    assert inv["context_tokens_estimate"] <= 3000
    assert inv["context_tokens_estimate"] * 5 < inv["raw_tokens_estimate"]
    assert inv["input_tokens"] > 0 and inv["output_tokens"] > 0
    # 25 identical pool warnings reach the model as one item with a count.
    pool = [e for e in inv["evidence"] if "pool exhausted" in e["message"]]
    assert len(pool) == 1 and pool[0]["count"] == 25
    usage = await api.ok("GET", "/api/v1/usage", params={"days": 7})
    assert usage["calls"] == 1
    assert usage["input_tokens"] == inv["input_tokens"]
    assert usage["saved_ratio"] > 0.8
    assert usage["ingested_lines"] >= 900


async def test_a12_followup_cites_real_lines_and_adds_earlier_evidence(
    api: Api,
    world: World,
    mock_provider: dict[str, Any],
) -> None:
    group, _ = await _incident_group(api, world)
    # An earlier change outside the original window: only a "before" question finds it.
    from datetime import timedelta

    await send(
        api.client,
        world.key,
        [
            log(
                "config change: payments pool max lowered from 50 to 20",
                service="payments",
                ts=datetime.now(UTC) - timedelta(minutes=140),
            )
        ],
    )
    inv = await _investigate(api, world, group["id"])
    turn = await api.ok(
        "POST",
        f"/api/v1/ai/investigations/{inv['id']}/followup",
        {"question": "What changed before this started?"},
        status=202,
    )
    assert turn["status"] == "queued"
    assert await run_jobs(api.app) == 1
    inv = await api.ok("GET", f"/api/v1/ai/investigations/{inv['id']}")
    answered = inv["turns"][0]
    assert answered["status"] == "completed"
    assert answered["grounded"] is True
    assert answered["added_evidence"] >= 1
    cited = answered["answer"]["citations"]
    assert any("config change: payments pool max lowered" in c["message"] for c in cited)
    assert any("deploy started" in c["message"] for c in cited)
    verified = await api.ok("GET", f"/api/v1/ai/investigations/{inv['id']}/verify")
    assert verified["all_verified"] is True
    assert verified["checked"] >= len(cited)
    usage = await api.ok("GET", "/api/v1/usage")
    assert usage["calls"] == 2


async def test_followup_fabrication_is_rejected_and_needs_a_finished_investigation(
    api: Api,
    world: World,
    mock_provider: dict[str, Any],
) -> None:
    group, _ = await _incident_group(api, world, noise=20)
    queued = await api.ok(
        "POST",
        "/api/v1/ai/investigate",
        {"project_id": world.project_id, "error_group_id": group["id"]},
        status=202,
    )
    resp = await api.client.post(
        f"/api/v1/ai/investigations/{queued['id']}/followup", json={"question": "why though?"}
    )
    assert resp.status_code == 409
    await run_jobs(api.app)
    await api.ok(
        "POST",
        f"/api/v1/ai/investigations/{queued['id']}/followup",
        {"question": "Is it still happening? [mock:fabricate]"},
        status=202,
    )
    await run_jobs(api.app)
    inv = await api.ok("GET", f"/api/v1/ai/investigations/{queued['id']}")
    turn = inv["turns"][0]
    assert "E999" in turn["answer"]["rejected_citations"]
    assert turn["grounded"] is False


@pytest.mark.parametrize(
    ("kind", "base", "family"),
    [
        ("openai_compatible", "/v1", "v1"),
        ("anthropic", "/anthropic", "anthropic"),
        ("gemini", "/gemini", "gemini"),
        ("ollama", "/ollama", "ollama"),
    ],
)
async def test_a11_every_provider_wire_format_against_the_mock_service(
    api: Api, world: World, kind: str, base: str, family: str
) -> None:
    await api.ok(
        "POST",
        "/api/v1/ai/providers",
        {
            "name": f"mock-{family}",
            "kind": kind,
            "model": "mock-analyst",
            "base_url": f"{api.mock_url}{base}",
            "api_key": "sk-test-sealed-value-123",
        },
        status=201,
    )
    providers = await api.ok("GET", "/api/v1/ai/providers")
    assert providers[0]["has_api_key"] is True
    assert "api_key" not in providers[0]
    test = await api.ok("POST", f"/api/v1/ai/providers/{providers[0]['id']}/test")
    assert test["ok"] is True, test
    group, _ = await _incident_group(api, world, noise=30)
    inv = await _investigate(api, world, group["id"])
    assert inv["status"] == "completed", inv["error"]
    assert inv["grounded"] is True
    assert inv["provider_name"] == f"mock-{family}"
    auth = await api.mock("/_mock/auth")
    assert "sk-test-sealed-value-123" in auth[family]
    calls = await api.mock("/_mock/calls")
    investigate_calls = [c for c in calls if c["task"] == "TASK: investigate"]
    assert investigate_calls and investigate_calls[-1]["prompt_chars"] < 16_000


async def test_provider_failure_marks_the_investigation_failed(api: Api, world: World) -> None:
    await api.ok(
        "POST",
        "/api/v1/ai/providers",
        {
            "name": "flaky",
            "kind": "openai_compatible",
            "model": "m",
            "base_url": f"{api.mock_url}/v1",
        },
        status=201,
    )
    import httpx

    async with httpx.AsyncClient() as c:
        await c.post(f"{api.mock_url}/_mock/fail", params={"status": 401, "times": 5})
    group, _ = await _incident_group(api, world, noise=10)
    inv = await _investigate(api, world, group["id"])
    assert inv["status"] == "failed"
    assert "401" in inv["error"]


async def test_free_question_investigation_and_listing(
    api: Api,
    world: World,
    mock_provider: dict[str, Any],
) -> None:
    await _incident_group(api, world, noise=20)
    resp = await api.client.post("/api/v1/ai/investigate", json={"project_id": world.project_id})
    assert resp.json()["error"]["code"] == "question_required"
    queued = await api.ok(
        "POST",
        "/api/v1/ai/investigate",
        {
            "project_id": world.project_id,
            "question": "Why did checkout get slow?",
            "window_minutes": 60,
        },
        status=202,
    )
    await run_jobs(api.app)
    inv = await api.ok("GET", f"/api/v1/ai/investigations/{queued['id']}")
    assert inv["status"] == "completed"
    assert inv["evidence_count"] > 0
    listed = await api.ok("GET", "/api/v1/ai/investigations", params=world.q)
    assert [i["id"] for i in listed] == [queued["id"]]
