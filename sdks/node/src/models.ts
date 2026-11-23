// Wire models: building one log line in LogMind's native shape and parsing the
// IngestResult the API answers with. Every field is clamped to the API's own limits
// before it is queued: the batch endpoint validates the whole body at once, so one
// oversized trace id would otherwise get the entire batch rejected and lose every line.

export const LEVELS = ["trace", "debug", "info", "warn", "error", "fatal"] as const;
export type Level = (typeof LEVELS)[number];

export const MAX_BATCH = 1000;
export const LIMITS = {
  message: 1_000_000,
  service: 120,
  environment: 120,
  host: 255,
  traceId: 64,
  spanId: 32,
  requestId: 128,
  excType: 200,
  excMessage: 4000,
  stacktrace: 64_000,
} as const;

const ALIASES: Record<string, Level> = {
  warning: "warn",
  critical: "fatal",
  err: "error",
  information: "info",
  notice: "info",
  panic: "fatal",
};

export type TimestampInput = Date | string | number;

/** Optional fields on every logging call. Any other key becomes an attribute:
 * `log.info("paid", { orderId: 42 })` sends `attributes: { orderId: 42 }`. */
export interface LogFields {
  attributes?: Record<string, unknown>;
  traceId?: string;
  spanId?: string;
  requestId?: string;
  /** A Date, an ISO 8601 string, or epoch milliseconds. Defaults to the time of the call. */
  timestamp?: TimestampInput;
  /** An error to attach as the line's structured exception. */
  error?: unknown;
  /** Per-line overrides of the client's defaults. */
  service?: string;
  environment?: string;
  host?: string;
  [key: string]: unknown;
}

export interface ExceptionPayload {
  type: string;
  message: string;
  stacktrace: string;
}

/** One `LogIn` object as sent on the wire. */
export interface WireLine {
  message: string;
  level: Level;
  timestamp: string;
  attributes?: Record<string, unknown>;
  trace_id?: string;
  span_id?: string;
  request_id?: string;
  service?: string;
  environment?: string;
  host?: string;
  exception?: ExceptionPayload;
}

export interface RejectedLine {
  index: number;
  reason: string;
}

/** The API's answer to one batch (HTTP 202). */
export interface IngestResult {
  accepted: number;
  rejected: RejectedLine[];
  redactions: number;
  errorGroups: number;
  eventIds: string[];
}

const KNOWN_FIELDS = new Set([
  "attributes",
  "traceId",
  "spanId",
  "requestId",
  "timestamp",
  "error",
  "service",
  "environment",
  "host",
]);

export function normalizeLevel(level: string): Level {
  const name = level.trim().toLowerCase();
  const aliased = ALIASES[name];
  if (aliased) return aliased;
  return (LEVELS as readonly string[]).includes(name) ? (name as Level) : "info";
}

export function isoTimestamp(value?: TimestampInput): string {
  if (value === undefined) return new Date().toISOString();
  if (typeof value === "string") return value;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? new Date().toISOString() : date.toISOString();
}

export function clamp(value: string, limit: number): string {
  return value.length <= limit ? value : value.slice(0, limit);
}

const MAX_DEPTH = 8;

/** A JSON-safe copy of an attribute value, taken when the line is logged: bigint, NaN,
 * Infinity, functions and symbols become strings, Dates ISO strings, Errors
 * `{name, message}`, Maps objects, Sets arrays, and a cycle is cut instead of crashing. */
export function jsonable(value: unknown, depth = 0, seen: WeakSet<object> = new WeakSet()): unknown {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (value === undefined) return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : String(value);
  if (typeof value === "bigint") return value.toString();
  if (typeof value === "function" || typeof value === "symbol") return String(value);
  if (value instanceof Date) return isoTimestamp(value);
  if (value instanceof Error) return { name: value.name, message: value.message };
  if (seen.has(value)) return "[Circular]";
  if (depth >= MAX_DEPTH) return "[Truncated]";
  seen.add(value);
  try {
    if (value instanceof Map) {
      const out: Record<string, unknown> = {};
      for (const [k, v] of value) out[String(k)] = jsonable(v, depth + 1, seen);
      return out;
    }
    if (value instanceof Set) return [...value].map((v) => jsonable(v, depth + 1, seen));
    if (ArrayBuffer.isView(value)) return `[${value.constructor.name} ${String(value.byteLength)} bytes]`;
    if (Array.isArray(value)) return value.map((v: unknown) => jsonable(v, depth + 1, seen));
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) out[k] = jsonable(v, depth + 1, seen);
    return out;
  } finally {
    seen.delete(value);
  }
}

/** `{type, message, stacktrace}` from `err.name`, `err.message` and `err.stack` (with
 * any `cause` chain appended). A thrown non-Error is described by its type and text. */
export function exceptionPayload(err: unknown): ExceptionPayload | undefined {
  if (err === undefined || err === null) return undefined;
  if (err instanceof Error) {
    let stack = err.stack ?? `${err.name}: ${err.message}`;
    let cause: unknown = err.cause;
    for (let hops = 0; cause !== undefined && cause !== null && hops < 5; hops += 1) {
      stack += `\nCaused by: ${cause instanceof Error ? (cause.stack ?? `${cause.name}: ${cause.message}`) : safeString(cause)}`;
      cause = cause instanceof Error ? cause.cause : undefined;
    }
    return {
      type: clamp(err.name || "Error", LIMITS.excType),
      message: clamp(err.message, LIMITS.excMessage),
      // Keep the tail when it is too long: the innermost frames matter most.
      stacktrace: stack.length <= LIMITS.stacktrace ? stack : stack.slice(-LIMITS.stacktrace),
    };
  }
  return { type: clamp(typeof err, LIMITS.excType), message: clamp(safeString(err), LIMITS.excMessage), stacktrace: "" };
}

// Fields are typed as strings, but plain JavaScript callers can pass anything.
function asText(value: unknown): string {
  return typeof value === "string" ? value : safeString(value);
}

function safeString(value: unknown): string {
  if (typeof value === "string") return value;
  // jsonable() output is always serialisable (no cycles, no bigint).
  const safe = jsonable(value);
  return typeof safe === "string" ? safe : JSON.stringify(safe);
}

export function buildLine(level: string, message: unknown, fields: LogFields = {}): WireLine {
  const exception = exceptionPayload(fields.error);
  let text = typeof message === "string" ? message : safeString(message);
  if (!text) text = exception?.message || exception?.type || "(empty message)";
  const line: WireLine = {
    message: clamp(text, LIMITS.message),
    level: normalizeLevel(level),
    timestamp: isoTimestamp(fields.timestamp),
  };
  const attributes: Record<string, unknown> = {};
  if (fields.attributes) Object.assign(attributes, fields.attributes);
  for (const [key, value] of Object.entries(fields)) {
    if (!KNOWN_FIELDS.has(key)) attributes[key] = value;
  }
  if (Object.keys(attributes).length > 0) line.attributes = jsonable(attributes) as Record<string, unknown>;
  if (fields.traceId) line.trace_id = clamp(asText(fields.traceId), LIMITS.traceId);
  if (fields.spanId) line.span_id = clamp(asText(fields.spanId), LIMITS.spanId);
  if (fields.requestId) line.request_id = clamp(asText(fields.requestId), LIMITS.requestId);
  if (fields.service) line.service = clamp(asText(fields.service), LIMITS.service);
  if (fields.environment) line.environment = clamp(asText(fields.environment), LIMITS.environment);
  if (fields.host) line.host = clamp(asText(fields.host), LIMITS.host);
  if (exception) line.exception = exception;
  return line;
}

function toInt(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) ? Math.trunc(n) : 0;
}

export function parseIngestResult(data: unknown): IngestResult {
  if (typeof data !== "object" || data === null) {
    return { accepted: 0, rejected: [], redactions: 0, errorGroups: 0, eventIds: [] };
  }
  const record = data as Record<string, unknown>;
  const rejected = Array.isArray(record.rejected)
    ? record.rejected
        .filter((r): r is Record<string, unknown> => typeof r === "object" && r !== null)
        .map((r) => ({ index: toInt(r.index), reason: typeof r.reason === "string" ? r.reason : "" }))
    : [];
  return {
    accepted: toInt(record.accepted),
    rejected,
    redactions: toInt(record.redactions),
    errorGroups: toInt(record.error_groups),
    eventIds: Array.isArray(record.event_ids) ? record.event_ids.map(String) : [],
  };
}

/** Combine the results of a batch that was sent in parts, re-basing rejected indexes. */
export function mergeResults(results: IngestResult[], offsets: number[]): IngestResult {
  return {
    accepted: results.reduce((n, r) => n + r.accepted, 0),
    rejected: results.flatMap((r, i) => r.rejected.map((x) => ({ index: x.index + (offsets[i] ?? 0), reason: x.reason }))),
    redactions: results.reduce((n, r) => n + r.redactions, 0),
    errorGroups: results.reduce((n, r) => n + r.errorGroups, 0),
    eventIds: results.flatMap((r) => r.eventIds),
  };
}
