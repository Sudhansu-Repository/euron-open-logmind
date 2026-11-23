# Contributing

Thanks for helping improve Euron Open LogMind. This guide covers the workflow, the bar a
change has to clear, and the conventions the codebase follows.

## Ground rules

- **Open an issue first** for anything larger than a bug fix or a docs tweak, so we can
  agree on the approach before you invest time.
- **One concern per pull request.** A refactor and a feature are two PRs.
- **Security issues go through private reporting**, never a public issue. That includes any
  way for one organisation to read another's logs, for a secret or personal value to reach
  storage past a project's redaction policy, or for an AI report to show a claim that cites
  no real log line. See [SECURITY.md](SECURITY.md).
- By contributing you agree your work is released under the [MIT License](LICENSE).

## Development setup

Requirements: Docker, Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 20 or newer
and pnpm 9 (`corepack enable`).

```bash
make up          # Postgres, Redis, ClickHouse, Floci (provisioned by Terraform), Mailpit,
                 # the mock AI service, api, worker, web
make demo        # Lumen Retail: 24 hours of logs from seven services, an incident with a
                 # real cause chain, alert rules, and a finished AI investigation
make test        # unit tests (API and web)
```

[docs/guides/quickstart-local.md](docs/guides/quickstart-local.md) walks through the local
stack in detail.

## Before you open a pull request

Each of these must pass:

```bash
make lint typecheck test
make test-integration                  # the API and worker against real Postgres, Redis,
                                       # ClickHouse and Mailpit
make test-matrix                       # when you touched evidence storage or key sealing
make e2e                               # when you touched a dashboard flow
make tf-validate tf-lint tf-security   # when you touched infra/terraform
make tf-aws-on-floci                   # same: apply and destroy aws-dev against Floci
make openapi                           # when you changed an endpoint (the drift test checks it)
make sanitize                          # no credentials, account ids, hostnames or dashes
```

Changes to the SDKs run their own suites: `uv run pytest` in `sdks/python` and `pnpm test`
in `sdks/node`.

## Conventions

**Package by domain.** `apps/api/src/logmind/<domain>/` owns its `router.py` (HTTP only),
`service.py` (rules), `repository.py` (the only code that queries) and `models.py`.
Dependencies point inward; a domain calls another domain's service, never its tables.

**Tenant scoping is structural.** Every Postgres query on a tenant-owned table filters by
`org_id` (and `project_id` where the row belongs to a project), and every ClickHouse query
goes through `logs/repository.py`, whose `_where()` always starts with the org and project
of a `ProjectScope`. Add an integration test that a second organisation cannot see new
data. The cross-org reads that exist (`ApiKeyRepository.by_prefix` and the worker's
`list_all_active` and alert claim) establish or iterate scope; do not add another without a
reason documented at the call site.

**Redaction happens before persistence.** Anything that stores or publishes log content (a
new column, a new attribute mapping, a new queue) must take the value after
`Redactor.redact_*` ran in `ingestion/service.py`. Never add a path that writes raw input
first and cleans it later.

**AI never speaks without evidence.** A new report section or answer field the model fills
must go through `investigations/citations.py`: ids it cites must exist in the evidence pack,
statements without a valid id are discarded, and times come from the cited lines. Add a test
with the mock's `[mock:fabricate]` trigger proving a fabricated citation is dropped.

**AI is optional.** Ingestion, search, grouping, services and alerts must keep working with
no AI provider configured. Nothing outside `investigations/` and `providers/` may call a
model.

**Values are bound, never spliced.** ClickHouse statements use `{name:Type}` placeholders
and `ClickHouse.query(sql, params)`; table names are allowlisted. Never format a value into
SQL text.

**Secrets never leave.** No endpoint, log line, audit record or error may carry a project
API key's secret, a session token, a provider key or a webhook URL. Keys are compared in
constant time and stored as a peppered HMAC; provider keys and alert URLs are sealed.

**Configuration is validated.** A new setting goes in `core/config.py`, is documented in
[docs/guides/configuration.md](docs/guides/configuration.md) in the same PR, and a
security-relevant one is enforced by `Settings.guard()` at boot.

**Schema changes are new migrations.** Postgres: a new Alembic revision under
`apps/api/src/logmind/migrations/versions/`. ClickHouse: a new numbered entry appended to
`core/clickhouse_schema.py`. Never edit an applied one.

**Comments explain why.** The code says what it does. Comments are for the constraint or
the trade-off that made it this way.

**Style.** ruff and mypy `--strict` for Python; ESLint, Prettier and TypeScript strict for
the web and the Node.js SDK. No em dashes or en dashes anywhere (the sanitization check
enforces it).

## Commit messages

Imperative mood with an optional scope: `ingestion: redact attribute values before the
insert`, `alerts: claim each due rule with its own row lock`. Explain the why in the body
when it is not obvious.

## Architecture decisions

Significant decisions are recorded in [docs/architecture/adr/](docs/architecture/adr/). If
your change reverses or extends one, add a new ADR rather than editing the old one.
