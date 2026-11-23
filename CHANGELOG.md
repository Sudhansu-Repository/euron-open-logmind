# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-11-16

First release.

### Added

- **Log collection.** `POST /api/v1/logs` and `POST /api/v1/logs/batch` (up to 1000 lines)
  with project API keys (`lmk_<prefix>_<secret>`, peppered HMAC, never returned), and
  OTLP/HTTP at `POST /v1/logs` in both encodings an OpenTelemetry SDK or Collector sends
  (protobuf and JSON, gzip or deflate), mapped onto the OTel log data model. Timestamps
  are accepted as ISO 8601 or epoch seconds, milliseconds, microseconds or nanoseconds,
  within a configurable past and future window.
- **Python and Node.js SDKs** (`euron-logmind`, `@euron/logmind`): batching in the
  background, retries with backoff and `Retry-After`, bounded queues, exception capture, a
  stdlib `logging` handler, never raising into the host application.
- **PII and secret redaction at ingestion**, configurable per project: credentials (API
  keys, tokens, JWTs, private keys, passwords in assignments and URLs), emails, card
  numbers (Luhn), US SSNs and Aadhaar numbers (Verhoeff), IBANs (mod 97), phone numbers and
  IP addresses, plus custom patterns; mask or keyed-hash mode; applied to messages, stack
  traces and attribute values before anything is stored or published.
- **ClickHouse log store** with a per-minute rollup maintained by a materialized view,
  skip indexes for keyword, trace, request, fingerprint and event id filters, and
  per-project retention.
- **Log Explorer**: keyword search, service, environment and level filters, time ranges,
  keyset pagination, a level histogram, filter facets, and a line's full context (lines
  before and after from the same service, and the same trace or request).
- **Live Logs** over a WebSocket, filtered on the server by level, service and keyword.
- **Error Intelligence**: fingerprints from the exception type and top in-app frames
  (Python, JavaScript, Java and Go traces) or a message template; groups with first and
  last seen, occurrence counts, affected services and environments, hourly trends,
  resolve, ignore and regression detection.
- **AI Root Cause Analyzer**: evidence retrieval from the incident window (first and latest
  occurrence, earlier warnings and errors, correlated errors, change events, the same
  request), compression by message template under an item and token budget, a cited report
  (root cause, findings, timeline, fixes), citation validation that drops fabricated ids
  and uncited statements, `GET /verify` that re-reads every cited line from ClickHouse,
  follow-up questions that extend the evidence, and token usage per call.
- **AI providers**: OpenAI, Anthropic, Gemini, Ollama, any OpenAI-compatible endpoint and
  a deterministic built-in mock; keys sealed with KMS or a local master key.
- **Service Health** from logs alone: volume, errors, error rate, availability, status and
  spikes per service.
- **Anomaly detection** against each series' own trailing baseline.
- **Alert Management**: threshold rules (error count, error rate, line count, matching
  lines) and anomaly rules; email (SMTP, Mailpit locally, or SES), signed webhooks and Slack;
  cooldowns, recoveries and per-delivery outcomes.
- **Dashboard** (Next.js 15): overview, live logs, log explorer, services, errors, AI
  investigations, alerts, settings (projects, redaction, API keys, AI providers, people,
  audit log), light and dark themes, phone width.
- Multi-tenant organisations and projects with structural scoping in every repository,
  roles (viewer, admin, owner), an append-only audit log, rate-limited sign in.
- Docker Compose stack on Floci with the Terraform `local-floci` environment applied on
  every `make up`; `aws-dev` and `aws-prod` environments (VPC, RDS, ElastiCache, ClickHouse
  on EC2, S3, KMS, Secrets Manager, SES, ECS Fargate behind an ALB with WAF, CloudWatch).
