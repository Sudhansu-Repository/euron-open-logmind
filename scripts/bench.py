"""Ingestion and query benchmark against the running stack (make up && make demo).

    make bench
    (cd apps/api && uv run python ../../scripts/bench.py --out ../../docs/bench.json)

Signs in as the demo owner, creates a throwaway project and key, then measures:

* ingestion: batches of BATCH lines through POST /api/v1/logs/batch (redaction,
  fingerprinting, the ClickHouse insert and the Postgres upsert included), sequential and
  with CONCURRENCY clients;
* search: keyword searches and filtered searches over the project, and the histogram.

Numbers depend on the machine; the README quotes the ones this script wrote.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

API = os.environ.get("BENCH_API_URL", "http://localhost:6030")
EMAIL = "owner@lumen.example"
PASSWORD = os.environ.get("LM_DEMO_PASSWORD", "Demo-Owner-Pass-1")
SERVICES = ["checkout", "payments", "search", "auth", "inventory"]


def line(i: int) -> dict[str, Any]:
    level = "error" if i % 50 == 0 else ("warn" if i % 10 == 0 else "info")
    item: dict[str, Any] = {
        "message": f"GET /api/items/{i} 200 in {i % 90}ms user=u{i % 300}@example.com",
        "level": level,
        "service": SERVICES[i % len(SERVICES)],
        "request_id": f"req-{i}",
        "attributes": {"route": "/api/items", "bytes": i % 4096},
    }
    if level == "error":
        item["exception"] = {
            "type": "TimeoutError",
            "stacktrace": (
                'Traceback (most recent call last):\n  File "/app/handlers.py", line '
                f'{40 + i % 7}, in handle\n    call()\nTimeoutError: upstream timed out'
            ),
        }
    return item


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(len(ordered) * p))], 1)


async def main(out: str, batches: int, batch: int, concurrency: int) -> None:
    async with httpx.AsyncClient(base_url=API, timeout=60) as admin:
        token = (await admin.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})).json()["session_token"]
        admin.headers["authorization"] = f"Bearer {token}"
        project = (await admin.post("/api/v1/projects", json={"name": f"bench-{uuid.uuid4().hex[:6]}", "retention_days": 1})).json()
        key = (await admin.post("/api/v1/keys", json={"project_id": project["id"], "name": "bench"})).json()["key"]

        async with httpx.AsyncClient(base_url=API, timeout=60, headers={"authorization": f"Bearer {key}"}) as ingest:
            latencies: list[float] = []
            started = time.perf_counter()
            for b in range(batches):
                body = {"logs": [line(b * batch + i) for i in range(batch)]}
                t0 = time.perf_counter()
                resp = await ingest.post("/api/v1/logs/batch", json=body)
                latencies.append((time.perf_counter() - t0) * 1000)
                resp.raise_for_status()
            sequential_s = time.perf_counter() - started

            async def worker(offset: int) -> None:
                for b in range(batches // concurrency):
                    body = {"logs": [line(10_000_000 + (offset * 1000 + b) * batch + i) for i in range(batch)]}
                    (await ingest.post("/api/v1/logs/batch", json=body)).raise_for_status()

            started = time.perf_counter()
            await asyncio.gather(*(worker(w) for w in range(concurrency)))
            concurrent_s = time.perf_counter() - started
            concurrent_lines = (batches // concurrency) * concurrency * batch

        q = {"project_id": project["id"]}
        searches: dict[str, list[float]] = {"keyword": [], "filtered": [], "histogram": []}
        for _ in range(20):
            for name, path, params in (
                ("keyword", "/api/v1/logs", {**q, "q": "timed out", "limit": 100}),
                ("filtered", "/api/v1/logs", {**q, "level": "error", "service": "checkout", "limit": 100}),
                ("histogram", "/api/v1/logs/histogram", q),
            ):
                t0 = time.perf_counter()
                (await admin.get(path, params=params)).raise_for_status()
                searches[name].append((time.perf_counter() - t0) * 1000)
        total = (await admin.get("/api/v1/logs/histogram", params=q)).json()["total"]

    result = {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "lines_stored": total,
        "ingest": {
            "batch_size": batch,
            "sequential_lines_per_s": round(batches * batch / sequential_s),
            "batch_latency_ms_p50": pct(latencies, 0.5),
            "batch_latency_ms_p95": pct(latencies, 0.95),
            "concurrency": concurrency,
            "concurrent_lines_per_s": round(concurrent_lines / concurrent_s),
        },
        "query_ms_p50": {k: pct(v, 0.5) for k, v in searches.items()},
        "query_ms_p95": {k: pct(v, 0.95) for k, v in searches.items()},
    }
    with open(out, "w") as fh:
        json.dump(result, fh, indent=2)
        fh.write("\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="docs/bench.json")
    parser.add_argument("--batches", type=int, default=40)
    parser.add_argument("--batch", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=4)
    a = parser.parse_args()
    asyncio.run(main(a.out, a.batches, a.batch, a.concurrency))
