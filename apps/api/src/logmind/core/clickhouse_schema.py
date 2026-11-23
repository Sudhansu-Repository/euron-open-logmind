"""The ClickHouse schema, versioned like Alembic but without a framework: each entry runs
once, recorded in ``logmind_schema_migrations``, in order. ``logmind migrate`` applies
these after the Postgres migrations. Never edit an applied entry; append a new one.

``log_events`` is ordered by ``(org_id, project_id, timestamp, event_id)``: every query
the API makes starts with the tenant and a time range, so the primary key prunes to one
project's slice of one time window before anything else is read. Skip indexes cover the
other filters the explorer exposes (keyword search, trace and request ids, fingerprints,
event ids). ``log_rollup_1m`` is a per-minute pre-aggregate maintained by a materialized
view, so dashboards, service health and anomaly baselines never scan raw log lines.
"""

from __future__ import annotations

import logging

from logmind.core.clickhouse import ClickHouse

log = logging.getLogger("logmind.clickhouse.schema")

MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
CREATE TABLE IF NOT EXISTS log_events (
    org_id UUID,
    project_id UUID,
    event_id UUID,
    timestamp DateTime64(6, 'UTC'),
    received_at DateTime64(6, 'UTC'),
    level LowCardinality(String),
    severity UInt8,
    service LowCardinality(String),
    environment LowCardinality(String),
    host String,
    message String,
    attributes String,
    trace_id String,
    span_id String,
    request_id String,
    exception_type String,
    stack_trace String,
    fingerprint String,
    redactions UInt16,
    source LowCardinality(String),
    INDEX idx_message lower(message) TYPE ngrambf_v1(3, 65536, 2, 0) GRANULARITY 4,
    INDEX idx_trace trace_id TYPE bloom_filter GRANULARITY 4,
    INDEX idx_request request_id TYPE bloom_filter GRANULARITY 4,
    INDEX idx_fingerprint fingerprint TYPE bloom_filter GRANULARITY 4,
    INDEX idx_event event_id TYPE bloom_filter GRANULARITY 4
) ENGINE = MergeTree
PARTITION BY toYYYYMM(timestamp)
ORDER BY (org_id, project_id, timestamp, event_id)
TTL toDateTime(timestamp) + INTERVAL 400 DAY
""",
    ),
    (
        2,
        """
CREATE TABLE IF NOT EXISTS log_rollup_1m (
    org_id UUID,
    project_id UUID,
    service LowCardinality(String),
    environment LowCardinality(String),
    level LowCardinality(String),
    minute DateTime('UTC'),
    events UInt64
) ENGINE = SummingMergeTree
PARTITION BY toYYYYMM(minute)
ORDER BY (org_id, project_id, minute, service, environment, level)
TTL minute + INTERVAL 400 DAY
""",
    ),
    (
        3,
        """
CREATE MATERIALIZED VIEW IF NOT EXISTS log_rollup_1m_mv TO log_rollup_1m AS
SELECT org_id, project_id, service, environment, level,
       toStartOfMinute(timestamp) AS minute, count() AS events
FROM log_events
GROUP BY org_id, project_id, service, environment, level, minute
""",
    ),
]

_LEDGER = """
CREATE TABLE IF NOT EXISTS logmind_schema_migrations (
    version UInt32, applied_at DateTime DEFAULT now()
) ENGINE = MergeTree ORDER BY version
"""


async def apply(ch: ClickHouse) -> int:
    """Create the database if needed and run every pending entry. Returns how many ran.
    Each statement is idempotent (``IF NOT EXISTS``), so a crash between a statement and
    its ledger row is harmless: the rerun is a no-op and then records it."""
    await ch.command(f"CREATE DATABASE IF NOT EXISTS {ch.database}", database=False)
    await ch.command(_LEDGER)
    rows = await ch.query("SELECT version FROM logmind_schema_migrations")
    done = {int(r["version"]) for r in rows}
    ran = 0
    for version, ddl in MIGRATIONS:
        if version in done:
            continue
        await ch.command(ddl)
        await ch.command(f"INSERT INTO logmind_schema_migrations (version) VALUES ({version})")
        log.info("clickhouse migration applied", extra={"version": version})
        ran += 1
    return ran
