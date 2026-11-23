# Configuration

Every setting is an environment variable read by `apps/api/src/logmind/core/config.py`
(the api, the worker and the CLI share it). Locally, `deploy/compose/compose.yaml` and the
Floci overlay set them; on AWS, Terraform passes plain values as task environment and secrets
from Secrets Manager. With `ENVIRONMENT=production`, unsafe values refuse to boot
([security.md](../architecture/security.md#production-boot-guards)).

## Core

| Variable | Default | Meaning |
| --- | --- | --- |
| `ENVIRONMENT` | `development` | `development`, `test` or `production` (enables the boot guards) |
| `LOGMIND_CLOUD` | `local` | `local`, `floci` or `aws`; `aws` forbids `AWS_ENDPOINT_URL` |
| `LOG_LEVEL` | `INFO` | JSON logs to stdout |
| `DATABASE_URL` | local Postgres | `postgresql+asyncpg://...` |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `10` / `20` | Per process |
| `REDIS_URL` | local Redis | Caches, rate limits, live stream |
| `CLICKHOUSE_URL` | local ClickHouse | `http://user:password@host:8123/database`; the log store, required |
| `CLICKHOUSE_TIMEOUT_S` | `10` | Per statement |

## Security

| Variable | Default | Meaning |
| --- | --- | --- |
| `SESSION_SECRET` | dev placeholder | Signs sessions; 32 or more random characters in production |
| `API_KEY_PEPPER` | dev placeholder | Peppers API key hashes and redaction hashes; must differ from the session secret |
| `SESSION_TTL_HOURS` | `12` | Session lifetime |
| `COOKIE_SECURE` | `false` | Must be `true` in production |
| `SIGNUP_ENABLED` | `true` | Self-service organisation sign up |
| `CORS_ORIGINS` | `http://localhost:6010` | Comma separated dashboard origins; also checked on the live WebSocket |
| `PUBLIC_URL` | `http://localhost:6010` | Used in alert links |
| `KEY_MODE` | `local` | `local` (AES-256-GCM with `LOCAL_MASTER_KEY`) or `kms` |
| `LOCAL_MASTER_KEY` | dev placeholder | Seals provider keys and alert URLs when `KEY_MODE=local` |
| `KMS_KEY_ID` | `alias/logmind-local` | KMS key for `KEY_MODE=kms` |
| `LOGIN_ATTEMPTS_PER_MINUTE` | `10` | Per client address, for sign in and sign up |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Proxies whose `X-Forwarded-For` is trusted (the VPC CIDR on AWS) |
| `HTTP_KEEP_ALIVE_S` | `5` | Keep longer than the load balancer's idle timeout (310 on AWS) |

## AWS and storage

| Variable | Default | Meaning |
| --- | --- | --- |
| `AWS_REGION` | `us-east-1` | |
| `AWS_ENDPOINT_URL` | unset | Floci locally; unset on AWS |
| `S3_FORCE_PATH_STYLE` | `false` | `true` for Floci |
| `STORAGE` | `local` | Evidence packs: `local` or `s3` (required in production) |
| `EVIDENCE_BUCKET` | `logmind-local-evidence` | |
| `LOCAL_STORAGE_DIR` | `./.data/evidence` | |

## Mail

| Variable | Default | Meaning |
| --- | --- | --- |
| `MAIL_BACKEND` | `log` | `log` (in-memory outbox, tests), `smtp` (Mailpit locally) or `ses` |
| `MAIL_FROM` | `LogMind Alerts <alerts@logmind.local>` | |
| `SMTP_HOST` / `SMTP_PORT` | `localhost` / `1025` | |

## Ingestion

| Variable | Default | Meaning |
| --- | --- | --- |
| `MAX_BATCH_EVENTS` | `1000` | Lines per native batch (413 above) |
| `MAX_MESSAGE_CHARS` | `16000` | Longer messages are truncated; stack traces get four times this |
| `MAX_BODY_BYTES` | `5000000` | Request body, before decompression (ten times after) |
| `MAX_PAST_DAYS` / `MAX_FUTURE_MINUTES` | `30` / `10` | Accepted timestamp window |
| `LIVE_PUBLISH_PER_BATCH` | `200` | Lines per batch sent to the live stream |

## AI investigations

| Variable | Default | Meaning |
| --- | --- | --- |
| `AI_MAX_EVIDENCE_ITEMS` | `40` | Evidence items per pack |
| `AI_MAX_CONTEXT_TOKENS` | `3000` | Token budget for the evidence |
| `AI_MESSAGE_CHARS` | `280` | Each item's message is cut to this |
| `AI_DEFAULT_WINDOW_MINUTES` | `60` | How far before the incident to look |
| `MODEL_TIMEOUT_S` | `120` | Upper bound for any provider call |
| `PROVIDER_ALLOW_PRIVATE` | `true` | Allow providers on private addresses (a local Ollama); `false` on AWS by default |

AI providers themselves (kind, model, base URL, key) are configured per organisation in
Settings, AI providers, not through the environment.

## Caches and worker

| Variable | Default | Meaning |
| --- | --- | --- |
| `CONFIG_CACHE_TTL_S` | `5` | In-process project config cache |
| `ROLLUP_CACHE_TTL_S` | `10` | Redis cache of overview and service health |
| `WEBHOOK_TIMEOUT_S` | `10` | Alert webhook and Slack calls |
| `WORKER_POLL_INTERVAL_S` | `1` | Idle wait between queue polls |
| `ALERT_INTERVAL_S` | `30` | How often each rule is evaluated (20 locally) |
| `RETENTION_INTERVAL_S` | `3600` | How often retention runs |
| `JOB_LEASE_S` | `300` | An investigation's lease before the reaper requeues it |
| `WORKER_METRICS_PORT` | `9464` | The worker's `/metrics` |
| `OTEL_ENABLED` | `false` | Export LogMind's own traces with the standard `OTEL_*` variables |

## Compose host ports

`deploy/compose/.env` may override `LM_WEB_PORT` (6010), `LM_API_PORT` (6030), `LM_PG_PORT`
(6042), `LM_REDIS_PORT` (6079), `LM_CLICKHOUSE_PORT` (6023), `LM_MAILPIT_PORT` (6025),
`LM_SMTP_PORT` (6026), `LM_MOCK_AI_PORT` (6050), `LM_FLOCI_PORT` (6066), and
`LM_DEMO_PASSWORD`, `LM_ALERT_INTERVAL_S`, `LM_LOG_LEVEL`, `LM_MAIL_BACKEND`.
