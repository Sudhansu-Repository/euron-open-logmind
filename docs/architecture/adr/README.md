# Architecture decision records

| ADR | Decision |
| --- | --- |
| [0001](0001-mit-licence.md) | MIT licence |
| [0002](0002-clickhouse-for-log-events.md) | ClickHouse for log lines, Postgres for everything relational |
| [0003](0003-inline-ingestion-processing.md) | Redact, fingerprint and group inside the ingestion request |
| [0004](0004-postgres-queue-for-investigations.md) | A Postgres queue for investigations, not Celery |
| [0005](0005-citations-validated-server-side.md) | Citations validated server side; uncited statements discarded |
| [0006](0006-otlp-protobuf-and-json.md) | OTLP/HTTP in both encodings at the standard path |
| [0007](0007-deterministic-mock-analyst.md) | A deterministic mock analyst shared by the in-process provider and the mock service |
