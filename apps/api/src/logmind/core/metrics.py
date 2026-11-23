"""Prometheus metrics for the domain counters and latencies that matter in operation:
ingestion volume and latency, redactions, error groups, investigations, model tokens and
alert deliveries. The API serves them at ``/metrics``; the worker on its own port."""

from __future__ import annotations

from prometheus_client import Counter, Histogram

ingested_events_total = Counter("logmind_ingested_events_total", "Log events stored", ["source"])
ingest_rejected_total = Counter(
    "logmind_ingest_rejected_total", "Log events rejected at ingestion", ["reason"]
)
ingest_seconds = Histogram(
    "logmind_ingest_seconds",
    "Ingestion request latency (validate, redact, fingerprint, store)",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
redactions_total = Counter("logmind_redactions_total", "Values redacted at ingestion", ["category"])
error_groups_touched_total = Counter(
    "logmind_error_groups_touched_total", "Error group upserts from ingestion"
)
investigations_total = Counter(
    "logmind_investigations_total", "AI investigations finished", ["status"]
)
model_tokens_total = Counter("logmind_model_tokens_total", "Model tokens used", ["direction"])
citations_rejected_total = Counter(
    "logmind_citations_rejected_total", "Model citations dropped because no evidence matched"
)
alerts_fired_total = Counter("logmind_alerts_fired_total", "Alert rule firings", ["kind"])
alert_deliveries_total = Counter(
    "logmind_alert_deliveries_total", "Alert notification deliveries", ["channel", "outcome"]
)
