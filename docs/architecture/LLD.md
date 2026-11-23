# Low-level design

## Backend layout (`apps/api/src/logmind/`)

| Package | Owns |
| --- | --- |
| `core/` | Settings and boot guards, the Postgres engine and scope types (`OrgScope`, `ProjectScope`), the ClickHouse HTTP client and its versioned schema, Redis, the config and rollup caches, the live pub/sub hub, key sealing (local AES-GCM or KMS), object storage (local or S3), mail (log, SMTP, SES), URL safety, rate limiting, Prometheus metrics, error envelope, JSON logs, request ids |
| `auth/`, `orgs/`, `audit/` | Sign up, sign in, sessions (JWT with a per-user version for revocation), users and roles, the organisation, the append-only audit log |
| `projects/` | Projects (retention, redaction policy), environments, API keys; `dependencies.py` turns an API key or a `project_id` query parameter into a `ProjectScope` |
| `redaction/` | Recognizers, checksums and the `Redactor` applied at ingestion |
| `ingestion/` | Native and OTLP endpoints, normalisation, the ingestion pipeline |
| `logs/` | `LogRepository` (every ClickHouse query), search, histogram, facets, context, the live WebSocket |
| `errors/` | Fingerprinting, error groups and hourly occurrences, status changes |
| `services/` | Service catalogue and health |
| `analytics/` | Anomaly math, the overview, usage |
| `providers/` | AI provider rows (sealed keys), adapters per wire format, retries |
| `investigations/` | Evidence and compression, prompts, the mock analyst, citation validation, the queue, verification |
| `alerts/` | Rules, evaluation, channels, history |
| `worker.py` | The loop: claim jobs, reap leases, evaluate due rules, apply retention |
| `cli.py` | `serve`, `worker`, `migrate`, `create-admin`, `seed-demo`, `openapi` |
| `demo/seed.py` | The Lumen Retail demo, a real HTTP client of the API |
| `../mockai/` | The mock AI service and webhook sink |

Each domain follows router (HTTP only) to service (rules) to repository (queries) to models.

## Scoping

```python
@dataclass(frozen=True)
class ProjectScope:
    org_id: UUID
    project_id: UUID
```

`ProjectQuery` (a FastAPI dependency) builds it from `?project_id=` after checking the
signed-in user's organisation owns the project (404 otherwise). `ProjectKey` builds it from an
API key. `LogRepository._where(scope, filter, params)` is the only way a log query gets a
WHERE clause, and it always starts with `org_id = {org:UUID} AND project_id = {project:UUID}`.

## Queue

`ai_investigations` and `ai_investigation_turns` carry `status`, `attempts`, `claimed_by` and
`lease_expires_at`. `claim_next` selects the oldest `queued` row `FOR UPDATE SKIP LOCKED`,
marks it `running` with a lease and commits at once. `reap_expired` puts rows whose lease
passed back to `queued`, or marks them `failed` after three attempts.

## Frontend layout (`apps/web/src/`)

| Path | What |
| --- | --- |
| `app/` | Thin routes; `api/session` (sign in, sign out, the httpOnly `lm_session` cookie), `api/proxy/[...path]` (adds the Bearer header), `api/session/ws-token` (the token for the live socket) |
| `features/<domain>/` | `api.ts` (TanStack Query hooks), pure helpers (`filters.ts`, `form.ts`, `report.ts`), `components/` |
| `components/` | Shared composites: badges, charts, empty and error states, the app shell |
| `components/ui/` | shadcn primitives on Base UI |
| `lib/` | Generated API types, the client, labels, query keys, the live stream helpers, formatting, roles |

`next.config.ts` rewrites `/ws/logs` to the API's `/api/v1/logs/live`, `/healthz`, `/readyz`,
`/docs` and `/openapi.json`; everything authenticated goes through the proxy route.
