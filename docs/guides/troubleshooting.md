# Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `503 log_store_unavailable` | ClickHouse is down or unreachable. `make ps`, `make logs SERVICE=clickhouse`. The SDKs retry with backoff meanwhile |
| `401 invalid_api_key` right after creating a key | The key was copied incompletely (it is shown once). Revocations apply within `CONFIG_CACHE_TTL_S` |
| Lines rejected with "more than 30 days in the past" | Backfills older than `MAX_PAST_DAYS` are refused; raise it for a one-off import |
| An OTLP exporter gets 415 or 400 | Use OTLP/HTTP (not gRPC) with `application/x-protobuf` or `application/json` |
| "AI investigations need an AI provider" | Add one in Settings, AI providers. Search, grouping and alerts work without it |
| An investigation failed with a provider error | Settings, AI providers, Test: it makes one small call and shows the provider's message |
| An investigation stays queued | No worker is running: `make logs SERVICE=worker` |
| Live logs says "Disconnected" | The session expired (sign in again) or `CORS_ORIGINS` does not list the dashboard origin |
| No alert email locally | Mail goes to Mailpit at http://localhost:6025; rules are evaluated every `ALERT_INTERVAL_S` |
| Integration tests fail with timeouts or SIGKILL and no app error | Usually host contention from other Docker stacks; rerun when the host is quieter |
| `make up` fails in `tf-local-floci` | Floci was not healthy yet or its volume is stale: `make down && make up` |
