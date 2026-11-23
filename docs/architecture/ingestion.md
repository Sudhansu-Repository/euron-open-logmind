# Ingestion, redaction and error fingerprinting

## Formats

| Endpoint | Body |
| --- | --- |
| `POST /api/v1/logs` | One `LogIn`: `message` (required), `level`, `timestamp`, `service`, `environment`, `host`, `attributes`, `trace_id`, `span_id`, `request_id`, `exception {type, message, stacktrace}` |
| `POST /api/v1/logs/batch` | `{"logs": [LogIn...], "defaults": {service, environment, host}}`, up to `MAX_BATCH_EVENTS` (1000) |
| `POST /v1/logs` (and `/api/v1/otlp/v1/logs`) | OTLP `ExportLogsServiceRequest`, `application/x-protobuf` (the exporter default) or `application/json`, optionally `gzip` or `deflate` |

OTLP mapping follows the OTel log data model: `service.name`, `deployment.environment(.name)`
and `host.name` from the resource (other resource attributes are kept under
`attributes.resource`), `severityNumber`/`severityText` for the level, `body` for the message
(non-string bodies are JSON encoded), `exception.type`, `exception.message` and
`exception.stacktrace` attributes for errors, `traceId`/`spanId` as lowercase hex. Invalid
records are reported back as `partialSuccess.rejectedLogRecords` and never fail the batch.

## Pipeline

1. **Normalise**: level aliases (`warning`, `critical`, OTLP numbers), timestamps in any
   unit, names cleaned and bounded, oversized messages and traces truncated.
2. **Window check**: lines older than `MAX_PAST_DAYS` or more than `MAX_FUTURE_MINUTES` ahead
   are rejected with a reason, per line.
3. **Redact** with the project's policy (below).
4. **Fingerprint** error lines (below).
5. **Store**: one ClickHouse insert, then one Postgres transaction for groups, occurrences,
   services and environments, rows sorted so concurrent batches lock in the same order.
6. **Publish** up to `LIVE_PUBLISH_PER_BATCH` lines to the project's live channel.

Why this runs in the request and not on a background queue: redaction must happen before
persistence, and a queue is persistence. See
[ADR-0003](adr/0003-inline-ingestion-processing.md).

## Redaction

Recognizers are adapted from Euron Open PIIShield, keeping only those that hold up on log
text. Checksummed categories only fire when the checksum passes, so an order id is not a card
number.

| Category | Recognises | Default |
| --- | --- | --- |
| `credential` | Private key blocks, JWTs, AWS, OpenAI, Anthropic, GitHub, Google, Slack and LogMind keys, `Bearer`/`Basic` tokens, passwords in URLs, `password=`/`secret:`/`api_key=` style assignments; whole values of attributes named `password`, `token`, `authorization`, `cookie` and similar | On |
| `email` | `name@domain.tld` | On |
| `payment_card` | 13 to 19 digits passing Luhn | On |
| `government_id` | US SSNs (SSA rules), Aadhaar (Verhoeff) | On |
| `phone` | International prefix or bracketed area code forms | On |
| `bank_account` | IBANs passing mod 97 | Off |
| `ip_address` | IPv4 | Off |

Plus up to 20 custom patterns per project (validated, nested quantifiers refused). Mode
`mask` writes `[REDACTED:<category>]`; `hash` writes `[<category>:<8 hex>]`, an HMAC keyed per
project, so equal values stay correlatable. Each line records how many values were redacted.

## Fingerprints

The fingerprint is the SHA-256 (first 32 hex) of:

- with a stack trace: the exception type plus the top six **in-app** frames as
  `function@file`, no line numbers. Python (`File "...", line N, in f`, reversed to most recent
  first), JavaScript (`at f (file.js:1:2)`), Java (`at pkg.Class.method(File.java:1)`) and Go
  frames are parsed; frames in `site-packages`, `node_modules`, the runtime or the JDK are
  skipped unless nothing else is left;
- without one: the exception type (or the level) plus the message template, with uuids,
  emails, addresses, URLs, hex ids, quoted strings, numbers and redaction tokens replaced by
  placeholders.

The service is not part of the key, so one bug in two services is one group listing both.
