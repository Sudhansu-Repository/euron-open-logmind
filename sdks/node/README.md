# @euron/logmind (Node.js)

The Node.js SDK for [Euron Open LogMind](../../README.md), the self-hosted log
intelligence platform. It ships structured log lines (levels, attributes, trace and
request ids, errors with stacks) to a LogMind API in batches. ESM with bundled types,
Node 18+ (global `fetch`), zero runtime dependencies. It is part of the open-source
initiative of **ENGAGESPHERE TECHNOLOGY PRIVATE LIMITED** and is MIT licensed.

```bash
pnpm add @euron/logmind        # or npm install / yarn add
```

The package is not on npm yet. Until then build and link it from this repository:
`pnpm --dir sdks/node install && pnpm --dir sdks/node build`, then depend on
`"@euron/logmind": "link:<path>/sdks/node"` (see `examples/node-quickstart`).

## Quickstart

```ts
import { LogMind } from "@euron/logmind";

const log = new LogMind({ apiKey: "lmk_...", service: "checkout" }); // or set LOGMIND_API_KEY

log.info("order placed", { orderId: 42, amount: 1999 }); // extra keys become attributes
log.warn("inventory low", { sku: "SKU-1042", remaining: 2 });
log.info("payment authorised", { traceId: "4bf92f3577b34da6a3ce929d0e0e4736", requestId: "req-7" });

try {
  await chargeCard(order);
} catch (err) {
  log.captureException(err, { message: "payment failed", orderId: 42 }); // name, message, stack
}

await log.close(); // flush and stop; a best effort flush also runs on beforeExit
```

Every example runs against `http://localhost:6030` by default (`make up` in the project
root); set `endpoint` or `LOGMIND_ENDPOINT` for another deployment.

| What | Where |
| --- | --- |
| `log.trace/debug/info/warn/error/fatal(message, fields?)` | queue one line; `log.log(level, message, fields?)` takes any level name |
| `log.captureException(err, fields?)` | level `error` with `err.name`, `err.message` and `err.stack` (plus the `cause` chain); `fields.message` sets the line's message |
| `fields` | `attributes`, `traceId`, `spanId`, `requestId`, `timestamp` (Date, ISO string or epoch ms), `error`, per-line `service`/`environment`/`host`; any other key becomes an attribute |
| `await log.flush(timeoutMs?)` | send everything queued now; `true` when the queue drained |
| `await log.close(timeoutMs = 5000)` | flush, then stop; later lines are dropped and counted |
| `await log.sendBatch(logs)` | send now and resolve the API's `IngestResult` |
| `log.stats` | `queued`, `accepted`, `rejected`, `droppedQueueFull`, `droppedFailed`, `droppedClosed`, `batchesSent`, `retries` |

## Configuration

| Option | Env var | Default | Meaning |
| --- | --- | --- | --- |
| `apiKey` | `LOGMIND_API_KEY` | none | project API key `lmk_<prefix>_<secret>`; without one the client is disabled |
| `endpoint` | `LOGMIND_ENDPOINT` | `http://localhost:6030` | LogMind API base URL |
| `service` | `LOGMIND_SERVICE` | none | default `service` for every line |
| `environment` | `LOGMIND_ENVIRONMENT` | `production` | default `environment` for every line |
| `host` | | `os.hostname()` | default `host` for every line (`""` to leave it out) |
| `batchSize` | | `100` | lines per request (capped at the API's 1000) |
| `flushIntervalMs` | | `1000` | longest a queued line waits before it is sent |
| `maxQueue` | | `10000` | lines held in memory before the oldest are dropped |
| `timeoutMs` | | `10000` | per request timeout (the request is aborted) |
| `maxRetries` | | `3` | retries per batch for retryable failures |
| `backoffBaseMs` | | `500` | first backoff step (doubles per retry, capped at 30 s) |
| `fetch` | | global `fetch` | a fetch implementation (tests pass a fake) |
| `flushOnExit` | | `true` | flush on `beforeExit` |
| `onWarning` | | stderr | where the one-line warnings go |

Explicit options always win over env vars.

## Wire format

Every batch is one request:

```
POST {endpoint}/api/v1/logs/batch
Authorization: Bearer lmk_<prefix>_<secret>
Content-Type: application/json
x-logmind-sdk: node/0.1.0

{
  "logs": [
    {
      "message": "payment failed",
      "level": "error",
      "timestamp": "2026-11-16T12:30:00.123Z",
      "attributes": {"orderId": 42},
      "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
      "request_id": "req-7",
      "exception": {"type": "TimeoutError", "message": "...", "stacktrace": "TimeoutError: ...\n    at ..."}
    }
  ],
  "defaults": {"service": "checkout", "environment": "production", "host": "web-1"}
}
```

The API answers `202` with an `IngestResult`, returned as `{accepted, rejected:
[{index, reason}], redactions, errorGroups, eventIds}`. Levels are `trace`, `debug`,
`info`, `warn`, `error` and `fatal` (`warning` and `critical` are mapped). Timestamps
are taken when the log call is made. Fields are clamped to the API's limits before they
are queued, and attribute values JSON cannot represent (bigint, NaN, Map, Set, Error,
typed arrays, cycles) are converted when the line is logged, so one odd value never gets
a whole batch refused.

## Behaviour on failure

Logging must never be the reason an application breaks, so the logging methods,
`flush` and `close` never throw and never reject.

| Situation | What happens |
| --- | --- |
| 429, 408, 5xx, refused connection, DNS failure, timeout | retried up to `maxRetries` times with exponential backoff and jitter (half to the full step); a `Retry-After` header (seconds or HTTP date, capped at 60 s) replaces the computed wait |
| retries exhausted | the batch is dropped, counted in `stats.droppedFailed` |
| 401 (bad or revoked key), 400, 422, other 4xx | not retried (it cannot succeed); the batch is dropped and counted |
| 413 | the batch is split in half and each half is sent; a single line that is still too large is dropped |
| a line refused inside an accepted batch | counted in `stats.rejected` |
| queue full (`maxQueue`) | the **oldest** queued line is dropped to make room for the new one, counted in `stats.droppedQueueFull` |
| no API key | the client is disabled: lines are dropped and counted, nothing is sent |

Each kind of problem produces **one** warning line (stderr by default, prefixed
`[euron-logmind]`) the first time it happens, not once per line. The API key never
appears in a warning, an error or `JSON.stringify(log)`.

The flush timer is `unref()`'d, so a queued line never keeps a finished process alive.
When the event loop empties, Node emits `beforeExit` and the SDK flushes what is left
(best effort: a process that calls `process.exit()` skips `beforeExit`, so call
`await log.close()` in your shutdown path). `close(timeoutMs)` cuts any retry wait short
once its timeout passes, so shutdown is bounded even with the API down. Batches are sent
one at a time, in order.

`sendBatch()` is the one call that does reject (`IngestError` with `status`, `code` and
`retryable`): use it when the caller wants to know what happened.

## Logging integration

The SDK has no logger dependency. To forward an existing logger, call the client from
its transport or hook. For example with a minimal console-style wrapper:

```ts
import { LogMind } from "@euron/logmind";

const log = new LogMind({ service: "api" });

export const logger = {
  info: (msg: string, fields?: Record<string, unknown>) => log.info(msg, fields),
  warn: (msg: string, fields?: Record<string, unknown>) => log.warn(msg, fields),
  error: (msg: string, err?: unknown, fields?: Record<string, unknown>) => log.error(msg, { ...fields, error: err }),
};

process.on("SIGTERM", () => {
  void log.close().then(() => process.exit(0));
});
```

Apps instrumented with the OpenTelemetry JS SDK can skip this package and export logs
over OTLP/HTTP to `{endpoint}/v1/logs` (see `examples/otel-collector`).

## Development

```bash
pnpm install
pnpm test               # unit tests (fake fetch, no network)
pnpm test:coverage      # with v8 coverage
pnpm lint && pnpm typecheck
pnpm build              # dist/ (ESM + .d.ts)
LOGMIND_TEST_API_URL=http://localhost:6030 LOGMIND_TEST_API_KEY=lmk_... pnpm test:integration
```

The integration suite sends real batches to a running API and checks the `IngestResult`
(accepted count, one event id per line, a bad key refused with 401). It is skipped, not
failed, when `LOGMIND_TEST_API_URL` and `LOGMIND_TEST_API_KEY` are unset.
