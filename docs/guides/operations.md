# Operations

## Health and metrics

- `GET /healthz`: the process is up. `GET /readyz`: Postgres, Redis and ClickHouse answer
  (503 otherwise).
- `GET /metrics` (api) and `:9464/metrics` (worker): `logmind_ingested_events_total{source}`,
  `logmind_ingest_seconds`, `logmind_ingest_rejected_total`, `logmind_redactions_total{category}`,
  `logmind_error_groups_touched_total`, `logmind_investigations_total{status}`,
  `logmind_model_tokens_total{direction}`, `logmind_citations_rejected_total`,
  `logmind_alerts_fired_total{kind}`, `logmind_alert_deliveries_total{channel,outcome}`,
  `logmind_worker_jobs_total{kind}`, `logmind_worker_alert_evaluations_total`.
- Logs are JSON on stdout with a request id (`x-request-id` is echoed back).

## Scaling

Run more api replicas for ingestion and search, more workers for investigations and alerts;
both are stateless. Jobs and rules are claimed with row locks, so workers never duplicate
work. ClickHouse is the component to size for volume: CPU for queries, disk for retention.

## Retention

Each project's `retention_days` is enforced hourly by the worker (a lightweight delete of
lines and rollup rows). A 400 day TTL on both tables is a backstop.

## Backups

Postgres: RDS automated backups and snapshots (`pg_dump` locally). ClickHouse: snapshot the
EBS data volume (AWS Backup or DLM) or `BACKUP TABLE ... TO S3`. Evidence packs: S3
versioning.

## Rotating secrets

`SESSION_SECRET` rotation signs everyone out. `API_KEY_PEPPER` rotation invalidates every API
key (re-issue them) and changes hash-mode redaction tokens. Provider keys and alert URLs are
re-sealed by editing them; with KMS, key rotation is automatic.

## Upgrades

`logmind migrate` (the migrate task) applies Postgres migrations, then any new ClickHouse
schema entries. Run it before rolling out api and worker.
