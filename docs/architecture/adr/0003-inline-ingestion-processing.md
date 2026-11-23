# 0003: Redact, fingerprint and group inside the ingestion request

**Status:** accepted

**Context.** The plan named ingestion processing among the background workers.

**Decision.** Redaction, fingerprinting, the ClickHouse insert and the error group upsert run
in the request. Redaction has to happen before anything is persisted, and a queue is
persistence: queueing raw lines would store unredacted personal data and secrets. Doing it
inline also means 202 means "stored and searchable", which the SDKs and A1 rely on.

**Consequences.** Ingestion latency includes one ClickHouse insert and one Postgres
transaction per batch (measured in the README). The ClickHouse insert comes first: a Postgres
failure after it yields a 503 and a client retry, duplicating lines rather than losing them.
The background worker handles the genuinely slow work: AI investigations, alert evaluation and
retention.
