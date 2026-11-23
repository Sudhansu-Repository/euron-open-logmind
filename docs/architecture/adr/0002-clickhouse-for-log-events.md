# 0002: ClickHouse for log lines, Postgres for everything relational

**Status:** accepted

**Context.** The program's default stack is Postgres only. A log platform stores millions of
lines per project per day and its queries are scans over time windows with filters and
aggregations.

**Decision.** `log_events` lives in ClickHouse (MergeTree ordered by org, project and time,
with skip indexes and a per-minute rollup); every relational row lives in Postgres. ClickHouse
is required, not an optional accelerator: there is no Postgres fallback for log lines.

**Consequences.** One more store to run. AWS has no managed ClickHouse, so `aws-dev` and
`aws-prod` run it on an EC2 instance with an encrypted data volume, reachable only from the
api and worker. Tenant scoping is enforced in one repository class instead of by foreign
keys.
