"""The background worker: AI investigations and follow-ups (claimed from the Postgres
queue with ``FOR UPDATE SKIP LOCKED``), alert rule evaluation (each rule row-locked by one
worker per interval) and retention (per-project deletes in ClickHouse).

Any number of worker processes can run at once: every job and every rule is claimed with
a row lock, so two workers never do the same work, and an investigation whose worker dies
is requeued by the lease reaper. Ingestion processing (redaction, fingerprinting, grouping)
deliberately does not run here; it runs in the request, before anything is stored (see
``ingestion/service.py`` for why).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import socket
import time
import uuid
from datetime import UTC, datetime, timedelta

from prometheus_client import Counter

from logmind.alerts.service import evaluate_due
from logmind.core.config import Settings, get_settings
from logmind.core.container import Container
from logmind.core.db import ProjectScope, import_all_models
from logmind.core.logs import configure_logging
from logmind.core.tracing import configure_tracing
from logmind.investigations import service as investigations
from logmind.logs.repository import LogRepository
from logmind.projects.repository import ProjectRepository

log = logging.getLogger("logmind.worker")

jobs_total = Counter("logmind_worker_jobs_total", "Jobs run by the worker", ["kind"])
alert_evaluations_total = Counter(
    "logmind_worker_alert_evaluations_total", "Alert rules evaluated by the worker"
)


async def run_one_job(container: Container, worker_id: str) -> bool:
    """Claim and run at most one investigation or follow-up. True when one ran."""
    async with container.db.sessionmaker() as session:
        claimed = await investigations.claim_next(
            session, worker_id, container.settings.job_lease_s
        )
    if claimed is None:
        return False
    kind, job_id = claimed
    log.info("job.started", extra={"kind": kind, "job_id": str(job_id)})
    if kind == "investigation":
        await investigations.run_investigation(container, job_id)
    else:
        await investigations.run_turn(container, job_id)
    jobs_total.labels(kind=kind).inc()
    log.info("job.finished", extra={"kind": kind, "job_id": str(job_id)})
    return True


async def drain_jobs(container: Container, worker_id: str = "inline", limit: int = 50) -> int:
    """Run queued jobs until none is left (tests and the demo seed use this)."""
    ran = 0
    while ran < limit and await run_one_job(container, worker_id):
        ran += 1
    return ran


async def apply_retention(container: Container) -> int:
    """Delete each project's lines older than its retention, through its own scope."""
    async with container.db.sessionmaker() as session:
        projects = await ProjectRepository(session).list_all_active()
    repo = LogRepository(container.clickhouse)
    now = datetime.now(UTC)
    for p in projects:
        try:
            await repo.delete_older_than(
                ProjectScope(p.org_id, p.id), now - timedelta(days=p.retention_days)
            )
        except Exception as exc:
            log.warning(
                "retention failed for a project, continuing",
                extra={"project_id": str(p.id), "error": str(exc)[:300]},
            )
    return len(projects)


async def run_forever(container: Container, stop: asyncio.Event, worker_id: str) -> None:
    settings = container.settings
    next_alerts = 0.0
    next_retention = time.monotonic() + 60
    next_reap = 0.0
    while not stop.is_set():
        now = time.monotonic()
        try:
            if now >= next_reap:
                async with container.db.sessionmaker() as session:
                    await investigations.reap_expired(session)
                next_reap = now + 30
            if now >= next_alerts:
                n = await evaluate_due(container)
                alert_evaluations_total.inc(n)
                next_alerts = now + settings.alert_interval_s
            if now >= next_retention:
                await apply_retention(container)
                next_retention = now + settings.retention_interval_s
            if await run_one_job(container, worker_id):
                continue
        except Exception:
            log.exception("worker cycle failed; continuing")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_interval_s)


async def main(settings: Settings | None = None) -> None:
    from prometheus_client import start_http_server

    settings = settings or get_settings()
    configure_logging(settings.log_level)
    configure_tracing(settings, service="logmind-worker")
    import_all_models()
    if settings.worker_metrics_port:
        start_http_server(settings.worker_metrics_port)
    container = Container.build(settings)
    worker_id = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    log.info("worker started", extra={"worker_id": worker_id})
    try:
        await run_forever(container, stop, worker_id)
    finally:
        await container.close()
        log.info("worker stopped", extra={"worker_id": worker_id})


def run() -> None:
    asyncio.run(main())
