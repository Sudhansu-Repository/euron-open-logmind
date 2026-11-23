# Security model

## What LogMind guarantees

1. **Redaction before persistence.** With a project's redaction on, every value of an
   enabled category is replaced in the message, the stack trace and every attribute value
   before the ClickHouse insert, before the error group sample is written, before the live
   stream publish, and therefore before any evidence pack or prompt is built.
2. **Tenant isolation, structurally.** Every Postgres query filters by organisation (and
   project), every ClickHouse query is built by one function that always adds the org and
   project of a verified scope. A key resolves to exactly one project; nothing a client sends
   can name another.
3. **Grounded AI output.** A statement in a report or answer is shown only if it cites an
   evidence id that exists in the pack, and each evidence id points at a stored line of the
   same project. `GET /verify` re-checks every cited line against ClickHouse.
4. **AI is optional.** With no provider configured, no model is ever called; everything but
   investigations works.
5. **Secrets stay sealed.** API key secrets are stored as a peppered HMAC; provider keys,
   webhook and Slack URLs and webhook signing secrets are sealed with KMS or AES-256-GCM
   under a context bound to the row; none is returned by any endpoint.

## Authentication and roles

Dashboard sessions are HS256 JWTs (12 hours) kept by the web app in an httpOnly, SameSite=Lax
cookie and sent to the API only as a Bearer header by the proxy route. A per-user
`session_version` revokes sessions on role change or disable. Roles: viewer (reads, runs
investigations), admin (projects, keys, redaction, providers, alerts, error status), owner
(people). Sign in and sign up are rate limited per address.

## Data sent to model providers

Only the evidence pack: at most `AI_MAX_EVIDENCE_ITEMS` lines, each cut to
`AI_MESSAGE_CHARS`, already redacted. Provider base URLs are refused when they point at
instance metadata, and, with `PROVIDER_ALLOW_PRIVATE=false` (the AWS default), at private
addresses. The built-in mock and a local Ollama keep everything inside the deployment.

## Outbound requests

Alert webhooks and Slack URLs are checked at creation and again at send time (a DNS name
that resolves to a metadata address is refused). Webhook bodies are signed with a per-rule
secret.

## Production boot guards

`ENVIRONMENT=production` refuses to start with placeholder or short secrets, equal session
secret and pepper, a placeholder local master key without KMS, an AWS endpoint override on
AWS, insecure cookies, wildcard CORS, the in-memory mail backend or local evidence storage.

## Headers and transport

Security headers on every API response (`nosniff`, `DENY` framing, no referrer, COOP,
permissions policy) and a per-request CSP from the web middleware. On AWS the ALB terminates
TLS, a WAF fronts it, RDS forces SSL, S3 denies non-TLS access.

## What it does not guarantee

- Recall of the recognizers: personal data in a format no recognizer covers (a name, a
  free-text address) is stored as sent. Add custom patterns per project.
- The correctness of a model's reasoning: grounding guarantees the evidence is real, not that
  the conclusion drawn from it is right. Reports carry a confidence and their evidence.
- Lines are not encrypted at the application level inside ClickHouse; use disk encryption
  (the AWS module encrypts the EBS volumes with KMS).
