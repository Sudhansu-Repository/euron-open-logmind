# Euron Open LogMind: Plan

## Purpose

A developer connects an application to LogMind and asks, in plain language, why it
failed. LogMind investigates the actual evidence, logs, stack traces, deployment
timing, and returns a root cause explanation that cites the specific log lines and
events that support it, not a generic summary. The hard guarantee: every AI
investigation report is grounded in real, retrievable evidence from the user's own
logs, and the system works for collection, search, and error grouping even with no AI
configured at all.

## Comparable products

| Product | License | Self-hosted AI root cause analysis? |
| --- | --- | --- |
| Grafana Loki | AGPLv3, genuinely free OSS | None. Log storage and LogQL only; no AI investigation at any tier. |
| SigNoz | MIT core, separate proprietary `ee/` license for SSO/RBAC | None found, open-source or enterprise. |
| Sentry | FSL (not OSI open source; converts to Apache after 2 years) | Seer (its AI root-cause feature) is cloud-only, unavailable to self-hosted Sentry at any license tier. |
| ClickStack (ClickHouse) | Open-source core exists, but AI Notebooks/AI-SRE investigation is beta and scoped to ClickHouse Cloud only | None in the self-hosted bundle. |
| OpenObserve | AGPLv3 core, paid Enterprise for SSO/RBAC | None found. |

**The whitespace**: every genuinely self-hostable open-source log tool has no AI
investigation feature at all. Every product that has shipped real AI root-cause
analysis (Sentry Seer, ClickHouse AI Notebooks) gates it to a cloud/managed tier, not
available to self-hosters at any price. LogMind's bet is to be the first to ship that
capability self-hosted, under a real open-source license, with no cloud dependency
required.

## Acceptance criteria (0.1.0)

1. **A1**: Fresh install, `make demo`, and a developer can send logs via the API or an
   SDK and see them in the Log Explorer within seconds.
2. **A2**: Error log lines with similar stack traces are automatically grouped into one
   error group with a stable fingerprint, first-seen/last-seen, and occurrence count.
3. **A3**: An AI investigation (`POST /api/v1/ai/investigate`) for a real error group
   returns a root cause report whose every cited piece of evidence (a log line, a
   timestamp, a deployment event) is independently verifiable against the actual stored
   logs for that time window, not fabricated or paraphrased from thin air.
4. **A4**: The investigation does not send the entire raw log volume to the LLM,
   evidence selection and context compression happen first; token usage per
   investigation is recorded and visible to the user.
5. **A5**: LogMind works for ingestion, search, filtering, and error grouping with zero
   AI provider configured, AI is an additional layer, never a requirement for the base
   product.
6. **A6**: Log ingestion accepts the OTLP log data model directly (an OpenTelemetry
   Collector or SDK can send logs with no custom adapter), in addition to the
   LogMind-native HTTP API and SDKs.
7. **A7**: PII and secret-shaped values in ingested log content are detected and
   redacted before storage, configurable per project.
8. **A8**: Organizations and their projects are fully isolated, structurally, at the
   repository layer, not by per-route discipline, the same pattern as every other
   project in this program.
9. **A9**: An alert rule (error rate threshold, anomaly) fires a real notification
   (email via Mailpit locally, Slack/webhook) when its condition is met against live
   ingested data, not a static demo value.
10. **A10**: A basic anomaly detector flags a genuine deviation (an injected error spike
    in the demo seed) against its own historical baseline.
11. **A11**: The AI investigation feature operates correctly against the mock AI
    provider with zero external API keys configured, so the full demo and e2e suite run
    with no live credentials.
12. **A12**: A follow-up question on an existing investigation ("what changed before
    this started") is answered using the same evidence-citation discipline as the
    original report, not a disconnected new investigation.

## Scope for 0.1.0

In scope (from the blueprint's own MVP checklist, module list 1 to 4 and 7 to 9, plus
the security requirements):

- Log Collector: HTTP ingestion API, batch ingestion, OTLP-compatible endpoint.
- Python and Node.js SDKs (`client.error(...)`, `client.info(...)`).
- Log Explorer: live streaming, keyword search, filters (service, environment, level,
  timestamp), JSON log visualization.
- Error Intelligence: fingerprinting, grouping, first/last seen, affected
  services/environments.
- AI Root Cause Analyzer: evidence retrieval, context compression, investigation
  report with cited evidence, follow-up questions, token usage tracking.
- Service Health Monitoring: basic per-service error rate, request volume, uptime from
  ingested data (no external APM agent).
- Alert Management: threshold and anomaly alert rules; email (Mailpit locally) and
  webhook/Slack notifications.
- Basic anomaly detection: statistical baseline comparison for error rate spikes.
- Multi-provider AI (OpenAI, Anthropic, Gemini, Ollama, OpenAI-compatible) plus a
  deterministic mock provider, the program's established pattern.
- PII/secret redaction at ingestion, reusing PIIShield's detection patterns where they
  fit log content rather than structured documents.
- Multi-tenant org/project isolation, API keys, audit log.
- Web dashboard: overview, live logs, log explorer, errors, AI investigations,
  services, alerts, settings.

Roadmap (explicitly out of 0.1.0, per the blueprint's own phase 4 to 6 plus stretch
modules): Incident Management as a dedicated tracked-object workflow (0.1.0 only emits
alerts; formal incident timelines/assignment are roadmap), deployment-event correlation,
Kubernetes DaemonSet/Helm collection, Fluent Bit integration, metrics/trace correlation
beyond logs, custom dashboard builder, scheduled reports and CSV/PDF export, Java and PHP
SDKs (Python and Node only in 0.1.0), local model (Ollama) as a fully offline default
rather than one of several provider options.

## Architecture

Backend (FastAPI, package-by-domain per program convention): `ingestion/` (HTTP + OTLP
endpoints, API keys), `logs/` (ClickHouse-backed storage and query engine),
`errors/` (fingerprinting, grouping), `investigations/` (AI root cause, evidence
retrieval, context builder, provider adapters), `alerts/` (rule evaluation, anomaly
baseline, notification dispatch), `orgs/`, `projects/`, `auth/`, `core/`.

Storage: PostgreSQL for all relational metadata (orgs, users, projects, api_keys,
error_groups, alert_rules, ai_investigations, audit_logs); ClickHouse for the
high-volume `log_events` table itself, following the blueprint's own reasoning (never
put millions of log rows in Postgres) and this program's precedent of running
domain-appropriate storage backends locally in Docker with an equivalent Terraform
module for AWS (ClickHouse itself has no first-class AWS managed service, so the
`aws-dev`/`aws-prod` Terraform runs it as a plain EC2-hosted container, documented
clearly as such, consistent with how other non-RDS-backed services in this program are
handled).

Background workers (the program's own FastAPI-native queue pattern, not Celery):
ingestion processing (parsing, PII redaction, fingerprinting), the AI investigation
engine, and alert rule evaluation.

## Data model

organizations, users, memberships, projects, environments, api_keys, services,
log_events (ClickHouse), error_groups, error_occurrences, alert_rules, alert_history,
ai_investigations, ai_usage, audit_logs, sessions.

## API surface

`POST /api/v1/logs`, `POST /api/v1/logs/batch`, `GET /api/v1/logs`,
`GET /api/v1/logs/live` (WebSocket), `GET /api/v1/errors`, `GET /api/v1/errors/{id}`,
`POST /api/v1/ai/investigate`, `GET /api/v1/ai/investigations`,
`GET /api/v1/ai/investigations/{id}`, `POST /api/v1/ai/investigations/{id}/followup`,
`GET /api/v1/services`, `GET /api/v1/alerts`, `POST /api/v1/alerts`,
`GET /api/v1/analytics/overview`, `GET /api/v1/usage`, an OTLP-compatible log endpoint.

## Screens

Overview, Live Logs, Log Explorer, Errors, AI Investigations, Services, Alerts,
Settings (users, projects, retention, API keys, AI providers).

## Test plan

Unit tests for fingerprinting, evidence retrieval/context compression, redaction rules,
alert rule evaluation, anomaly baseline math. Integration tests against real
Postgres/ClickHouse/Floci in Docker, covering every endpoint and tenant isolation.
E2E (Playwright): send logs via SDK, see them appear, trigger an error group, run an AI
investigation against the mock provider, verify cited evidence, trigger an alert.
Terraform validate/tflint/checkov across local-floci/aws-dev/aws-prod, plus
tf-aws-on-floci.

## Ports (project #20, base 4000 + 20*100 = 6000)

web 6010, api 6030, postgres 6042, redis 6079, floci 6066, mailpit 6025, mock AI 6050,
clickhouse 6023, tf-aws-on-floci 6096.
