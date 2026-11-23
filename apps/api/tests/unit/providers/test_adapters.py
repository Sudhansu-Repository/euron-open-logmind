"""Every provider adapter's wire format against the mock AI service, in process (no
network): requests are shaped right, answers and token usage are read back, errors are
classified for retries."""

from __future__ import annotations

import httpx
import pytest

from logmind.providers import gateway
from logmind.providers.adapters import ProviderConfig, adapter_for
from logmind.providers.types import Message, ModelRequest, ProviderError, classify_status
from mockai.app import app as mock_app

REQ = ModelRequest(
    model="mock-analyst",
    messages=(Message("system", "TASK: ping"), Message("user", "say ok")),
    max_tokens=8,
    temperature=0.0,
)


@pytest.fixture
async def http() -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock_app), base_url="http://mock")
    await client.post("http://mock/_mock/reset")
    return client


@pytest.mark.parametrize(
    ("kind", "base"),
    [
        ("openai", "/v1"),
        ("openai_compatible", "/v1"),
        ("anthropic", "/anthropic"),
        ("gemini", "/gemini"),
        ("ollama", "/ollama"),
        ("mock", ""),
    ],
)
async def test_round_trip(http: httpx.AsyncClient, kind: str, base: str) -> None:
    adapter = adapter_for(
        ProviderConfig(kind=kind, base_url=f"http://mock{base}", api_key="k-1"), http
    )
    resp = await adapter.complete(REQ)
    assert resp.text == "ok"
    assert resp.usage.input_tokens > 0 and resp.usage.output_tokens > 0
    assert await adapter.list_models()


async def test_errors_are_classified_and_retried(http: httpx.AsyncClient) -> None:
    adapter = adapter_for(ProviderConfig(kind="openai", base_url="http://mock/v1"), http)
    await http.post("http://mock/_mock/fail", params={"status": 503, "times": 1})
    assert (await gateway.complete(adapter, REQ)).text == "ok"
    await http.post("http://mock/_mock/fail", params={"status": 401, "times": 1})
    with pytest.raises(ProviderError) as exc:
        await gateway.complete(adapter, REQ)
    assert exc.value.code == "provider_auth" and not exc.value.retryable
    assert classify_status(429) == (True, "rate_limited")
    assert classify_status(404) == (False, "model_not_found")
    assert classify_status(400) == (False, "provider_rejected")


async def test_transport_failure() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as http:
        adapter = adapter_for(ProviderConfig(kind="anthropic", base_url="http://x"), http)
        with pytest.raises(ProviderError) as exc:
            await adapter.complete(REQ)
    assert exc.value.code == "provider_timeout" and exc.value.retryable
