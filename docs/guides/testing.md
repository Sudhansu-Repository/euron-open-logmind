# Testing

Every suite runs locally against Docker; none needs a provider key or an AWS account. AI
features are tested against the deterministic mock analyst (in process and over the mock AI
service's four wire formats).

| Suite | Where | Run |
| --- | --- | --- |
| API static | ruff, ruff format, mypy `--strict` on `src` and `tests` | `make lint typecheck` |
| API unit | `apps/api/tests/unit`: fingerprints, redaction and checksums, normalisation and OTLP decoding, anomaly math, evidence selection and compression, citation validation, the mock analyst, prompts, provider adapters against the mock service in process, alert state and channels, ClickHouse parameter binding, config guards, sealing, storage, URL safety, the OpenAPI drift check | `make test` |
| API integration | `apps/api/tests/integration`: the app in process against real Postgres, Redis, ClickHouse and Mailpit, the mock AI service over real HTTP | `make test-integration` |
| Backend matrix | The integration suite under evidence storage local or S3 (Floci) and key sealing local or KMS (Floci) | `make test-matrix` |
| Web | Vitest: filters, alert form, report helpers, live stream parsing, labels, session bridge, middleware, roles, errors, formatting | `cd apps/web && pnpm test` |
| SDKs | `sdks/python` (pytest) and `sdks/node` (Vitest), unit plus integration tests that run when `LOGMIND_TEST_API_URL` and `LOGMIND_TEST_API_KEY` are set | `uv run pytest`, `pnpm test` |
| End to end | Playwright against `make up && make demo` | `make e2e` |
| Infrastructure | validate, tflint, checkov on all three environments; the full `aws-dev` applied, re-planned and destroyed on Floci | `make tf-validate tf-lint tf-security tf-aws-on-floci` |
| Sanitization | Secrets, account ids, env files, em and en dashes | `make sanitize` |
| Browser QA | Puppeteer over every page, light and dark, desktop and phone | `make qa` |

## Acceptance criteria

Each criterion in [PLAN.md](../PLAN.md) is an automated test:

| Criterion | Test |
| --- | --- |
| A1 logs visible within seconds | `test_ingestion.py::test_a1_a_line_sent_over_the_api_is_searchable_when_the_request_returns`; e2e `01-ingest-explore-live` (live view and explorer) |
| A2 stable error groups | `test_logs_and_errors.py::test_a2_similar_stack_traces_group_with_a_stable_fingerprint`; unit `errors/test_fingerprint.py`; e2e `02-error-grouping` |
| A3 every cited line is real | `test_investigations.py::test_a3_a11_every_cited_line_is_real_and_the_cause_chain_is_found`, `::test_a3_fabricated_citations_are_dropped_not_shown`; e2e `03-ai-investigation` (Verify citations) |
| A4 compression and token usage | `test_investigations.py::test_a4_context_is_compressed_and_tokens_are_recorded` |
| A5 works with no AI | `test_investigations.py::test_a5_investigation_needs_a_provider_but_everything_else_works_without` |
| A6 OTLP ingestion | `test_ingestion.py::test_a6_otlp_protobuf_from_the_official_encoder`, `::test_a6_otlp_json_and_partial_success`; e2e `01-ingest-explore-live` |
| A7 redaction before storage, per project | `test_redaction_and_tenancy.py::test_a7_secrets_and_pii_never_reach_storage`, `::test_a7_policy_is_per_project`; e2e `05-redaction-settings` |
| A8 tenant isolation | `test_redaction_and_tenancy.py::test_a8_orgs_and_projects_are_isolated` |
| A9 real alert notifications | `test_alerts.py::test_a9_threshold_rule_fires_email_webhook_and_slack_then_resolves`, `::test_a9_email_reaches_mailpit_over_smtp`; e2e `04-alerts` (Mailpit) |
| A10 anomaly against its own baseline | `test_alerts.py::test_a10_anomaly_rule_flags_a_real_spike_against_its_own_baseline`; unit `analytics/test_anomaly.py` |
| A11 works with the mock and no keys | `test_investigations.py::test_a11_every_provider_wire_format_against_the_mock_service` (OpenAI-compatible, Anthropic, Gemini, Ollama), and every investigation test |
| A12 grounded follow-ups | `test_investigations.py::test_a12_followup_cites_real_lines_and_adds_earlier_evidence`, `::test_followup_fabrication_is_rejected_and_needs_a_finished_investigation`; e2e `03-ai-investigation` |

## Notes

- The integration suite refuses any Postgres or ClickHouse database whose name does not
  contain `test`, and non-local hosts unless `ALLOW_REMOTE_TEST_DB=true`. Each session gets
  its own ClickHouse database.
- On a machine running many other Docker stacks, a test can fail on a Redis connect timeout
  or a slow ClickHouse answer with no application error. That is host contention; rerun.
- `make bench` measures ingestion and query latency on the running stack and writes
  `docs/bench.json`.
