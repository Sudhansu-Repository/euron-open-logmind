# Data model

## PostgreSQL

| Table | Purpose | Key columns and indexes |
| --- | --- | --- |
| `organizations` | Tenant boundary | `slug` unique |
| `users` | People; the role is the membership (one organisation per account) | `lower(email)` unique, `org_id`, `session_version` |
| `projects` | One application's logs and settings | `(org_id, slug)` unique; `retention_days`, `redaction_enabled`, `redaction_categories`, `redaction_custom`, `redaction_mode` |
| `environments` | Environment names seen per project | `(project_id, name)` unique |
| `api_keys` | Ingestion keys | `prefix` unique, `secret_hash` (peppered HMAC), `revoked_at` |
| `services` | Service names seen per project | `(project_id, name)` unique, first and last seen |
| `error_groups` | One row per fingerprint per project | `(project_id, fingerprint)` unique, `(project_id, last_seen)`; `occurrences`, `services[]`, `environments[]`, `status`, `regressed_at` |
| `error_occurrences` | Hourly counts per group | `(group_id, hour)` unique |
| `ai_providers` | Model connections per organisation | `(org_id, name)` unique, one default per org (partial unique index), `api_key_sealed` |
| `ai_investigations` | Reports and the queue | `(status, created_at)`, `(project_id, created_at)`; window, report JSON, `evidence_key`, raw and context estimates, tokens, `grounded` |
| `ai_investigation_turns` | Follow-ups and their queue | `(status, created_at)`; `seq`, answer JSON, `added_evidence` |
| `ai_usage` | One row per model call | `(org_id, at)` |
| `alert_rules` | Threshold and anomaly rules | `(enabled, last_evaluated_at)`; sealed webhook and Slack URLs and secret, `state` |
| `alert_history` | Firings, recoveries, tests with delivery outcomes | `(rule_id, at)`, `(project_id, at)` |
| `audit_log` | Every mutation; updates refused by a trigger | `org_id`, keyset on `id` |

Every tenant-owned table has `org_id` with `ON DELETE CASCADE` from `organizations`.

## ClickHouse

```sql
log_events (
  org_id UUID, project_id UUID, event_id UUID,
  timestamp DateTime64(6, 'UTC'), received_at DateTime64(6, 'UTC'),
  level LowCardinality(String), severity UInt8,
  service LowCardinality(String), environment LowCardinality(String), host String,
  message String, attributes String,             -- JSON text, already redacted
  trace_id String, span_id String, request_id String,
  exception_type String, stack_trace String, fingerprint String,
  redactions UInt16, source LowCardinality(String)  -- api | sdk | otlp
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(timestamp)
ORDER BY (org_id, project_id, timestamp, event_id)
TTL toDateTime(timestamp) + INTERVAL 400 DAY
-- skip indexes: ngrambf on lower(message); bloom filters on trace_id, request_id,
-- fingerprint, event_id

log_rollup_1m (org_id, project_id, service, environment, level, minute, events)
ENGINE = SummingMergeTree, filled by the materialized view log_rollup_1m_mv
```

Per-project retention runs hourly in the worker as a lightweight `DELETE` on both tables. The
400 day TTL is a backstop for projects deleted without retention running.

## Object storage

`evidence/<org>/<investigation>/pack.json` (the numbered evidence pack and window statistics)
and `evidence/<org>/<investigation>/turn-<n>.json` (items a follow-up added). S3 with SSE-KMS
on AWS and Floci, local disk otherwise.
