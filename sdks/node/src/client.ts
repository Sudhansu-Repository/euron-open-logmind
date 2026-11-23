// The LogMind client: queue log lines in memory and ship them in batches, so a log call
// costs microseconds and never waits on the network.
//
// Guarantees:
// - Never throws into the application. The logging methods, `flush` and `close` swallow
//   every error; problems are counted in `stats` and reported with one stderr line per
//   kind of problem (never per line, never with the API key).
// - Bounded memory. At most `maxQueue` lines wait; when full the OLDEST queued line is
//   dropped to make room (recent lines usually explain an incident), counted in
//   `stats.droppedQueueFull`.
// - Never keeps a process alive. The flush timer is unref'd; a best effort flush runs on
//   `beforeExit`, which Node emits when the event loop is about to empty.

import { hostname } from "node:os";

import { IngestError } from "./errors.js";
import {
  LIMITS,
  MAX_BATCH,
  buildLine,
  clamp,
  type ExceptionPayload,
  type IngestResult,
  type LogFields,
  type TimestampInput,
  type WireLine,
} from "./models.js";
import { Sender, type BatchDefaults, type FetchLike } from "./transport.js";

export const DEFAULT_ENDPOINT = "http://localhost:6030";
export const DEFAULT_ENVIRONMENT = "production";

export interface LogMindOptions {
  /** A project API key, `lmk_<prefix>_<secret>`. Defaults to `LOGMIND_API_KEY`. */
  apiKey?: string;
  /** Defaults to `LOGMIND_ENDPOINT`, then `http://localhost:6030`. */
  endpoint?: string;
  /** Defaults to `LOGMIND_SERVICE`. */
  service?: string;
  /** Defaults to `LOGMIND_ENVIRONMENT`, then `production`. */
  environment?: string;
  /** Defaults to `os.hostname()`. Pass `""` to leave it out. */
  host?: string;
  batchSize?: number;
  flushIntervalMs?: number;
  maxQueue?: number;
  timeoutMs?: number;
  maxRetries?: number;
  backoffBaseMs?: number;
  /** A fetch implementation; defaults to the global `fetch` (Node 18+). */
  fetch?: FetchLike;
  /** Flush on `beforeExit` (default true). */
  flushOnExit?: boolean;
  /** Where the one-line warnings go; defaults to stderr. */
  onWarning?: (message: string) => void;
}

/** One line for `sendBatch`, in LogMind's native shape with camelCase field names. */
export interface LogInput extends Omit<LogFields, "error"> {
  message: string;
  level?: string;
  timestamp?: TimestampInput;
  exception?: unknown;
}

export interface Stats {
  queued: number;
  accepted: number;
  rejected: number;
  droppedQueueFull: number;
  droppedFailed: number;
  droppedClosed: number;
  batchesSent: number;
  retries: number;
}

export type { ExceptionPayload };

function env(name: string): string | undefined {
  const value = process.env[name]?.trim();
  return value ? value : undefined;
}

function defaultWarn(message: string): void {
  try {
    process.stderr.write(`[euron-logmind] ${message}\n`);
  } catch {
    // stderr unavailable: nothing else to do
  }
}

export class LogMind {
  readonly endpoint: string;
  readonly service: string | undefined;
  readonly environment: string;
  readonly host: string | undefined;
  readonly batchSize: number;
  readonly flushIntervalMs: number;
  readonly maxQueue: number;

  private readonly sender: Sender | null;
  private readonly warnSink: (message: string) => void;
  private readonly warned = new Set<string>();
  private buffer: WireLine[] = [];
  private inflight = 0;
  private timer: NodeJS.Timeout | null = null;
  private draining: Promise<void> | null = null;
  private closing = false;
  private closed = false;
  private readonly abort = new AbortController();
  private readonly counts = {
    accepted: 0,
    rejected: 0,
    droppedQueueFull: 0,
    droppedFailed: 0,
    droppedClosed: 0,
    batchesSent: 0,
    retries: 0,
  };
  private readonly onBeforeExit: (() => void) | null = null;

  constructor(options: LogMindOptions = {}) {
    this.warnSink = options.onWarning ?? defaultWarn;
    const apiKey = options.apiKey ?? env("LOGMIND_API_KEY");
    this.endpoint = (options.endpoint ?? env("LOGMIND_ENDPOINT") ?? DEFAULT_ENDPOINT).replace(/\/+$/, "");
    const service = options.service ?? env("LOGMIND_SERVICE");
    this.service = service ? clamp(service, LIMITS.service) : undefined;
    this.environment = clamp(options.environment ?? env("LOGMIND_ENVIRONMENT") ?? DEFAULT_ENVIRONMENT, LIMITS.environment);
    const host = options.host ?? safeHostname();
    this.host = host ? clamp(host, LIMITS.host) : undefined;
    this.batchSize = Math.max(1, Math.min(Math.floor(options.batchSize ?? 100), MAX_BATCH));
    this.flushIntervalMs = Math.max(10, options.flushIntervalMs ?? 1000);
    this.maxQueue = Math.max(1, Math.floor(options.maxQueue ?? 10_000));

    const fetchImpl = options.fetch ?? (typeof fetch === "function" ? fetch : undefined);
    if (!apiKey || !fetchImpl) {
      this.sender = null;
      this.warnOnce(
        "disabled",
        apiKey ? "no global fetch (Node 18+ required); logging is disabled" : "no API key (pass apiKey or set LOGMIND_API_KEY); logging is disabled",
      );
      return;
    }
    this.sender = new Sender({
      endpoint: this.endpoint,
      apiKey,
      fetch: fetchImpl,
      timeoutMs: options.timeoutMs ?? 10_000,
      maxRetries: options.maxRetries ?? 3,
      backoffBaseMs: options.backoffBaseMs ?? 500,
      sleep: (ms) => this.sleep(ms),
      onRetry: () => {
        this.counts.retries += 1;
      },
    });
    if (options.flushOnExit ?? true) {
      this.onBeforeExit = () => {
        if (this.buffer.length > 0 && !this.closed) void this.flush();
      };
      process.on("beforeExit", this.onBeforeExit);
    }
  }

  /** `false` when the client has no API key or has been closed. */
  get enabled(): boolean {
    return this.sender !== null && !this.closing;
  }

  get stats(): Stats {
    return { queued: this.buffer.length + this.inflight, ...this.counts };
  }

  log(level: string, message: unknown, fields?: LogFields): void {
    try {
      this.enqueue(buildLine(level, message, fields));
    } catch (err) {
      this.warnOnce("build", `could not record a log line (${err instanceof Error ? err.name : typeof err})`);
    }
  }

  trace(message: unknown, fields?: LogFields): void {
    this.log("trace", message, fields);
  }

  debug(message: unknown, fields?: LogFields): void {
    this.log("debug", message, fields);
  }

  info(message: unknown, fields?: LogFields): void {
    this.log("info", message, fields);
  }

  warn(message: unknown, fields?: LogFields): void {
    this.log("warn", message, fields);
  }

  /** `error("...", { error: err })` attaches the error's name, message and stack. */
  error(message: unknown, fields?: LogFields): void {
    this.log("error", message, fields);
  }

  fatal(message: unknown, fields?: LogFields): void {
    this.log("fatal", message, fields);
  }

  /** Log an error at level `error` using `err.name`, `err.message` and `err.stack`.
   * The line's message is `fields.message` when given, else the error's own message. */
  captureException(err: unknown, fields: LogFields & { message?: string } = {}): void {
    const { message, ...rest } = fields;
    this.log("error", message ?? "", { ...rest, error: err });
  }

  /** Send everything queued now. Resolves `true` when the queue drained (every line was
   * accepted, rejected or dropped) within `timeoutMs`; never rejects. */
  async flush(timeoutMs?: number): Promise<boolean> {
    if (!this.sender) return true;
    const work = this.drain(true);
    if (timeoutMs === undefined) {
      await work;
      return this.buffer.length === 0 && this.inflight === 0;
    }
    let timer: NodeJS.Timeout | undefined;
    const timeout = new Promise<false>((resolve) => {
      timer = setTimeout(() => {
        resolve(false);
      }, timeoutMs);
      timer.unref();
    });
    try {
      const finished = await Promise.race([work.then(() => true as const), timeout]);
      return finished && this.buffer.length === 0 && this.inflight === 0;
    } finally {
      clearTimeout(timer);
    }
  }

  /** Flush (waiting up to `timeoutMs`), then stop. Lines logged afterwards are dropped
   * and counted. Safe to call more than once. Resolves whether everything was sent. */
  async close(timeoutMs = 5000): Promise<boolean> {
    if (this.closed || this.closing) return this.closed ? true : this.flush(timeoutMs);
    this.closing = true;
    if (this.onBeforeExit) process.removeListener("beforeExit", this.onBeforeExit);
    const drained = await this.flush(timeoutMs);
    this.closed = true;
    this.abort.abort();
    this.clearTimer();
    if (this.buffer.length > 0) {
      this.counts.droppedClosed += this.buffer.length;
      this.buffer = [];
    }
    return drained;
  }

  /** Send `logs` now, bypassing the queue, and resolve the API's IngestResult
   * (`accepted`, `rejected`, `eventIds` ...). Unlike the logging methods this rejects
   * with an IngestError when the batch cannot be delivered, because the caller asked. */
  async sendBatch(logs: LogInput[]): Promise<IngestResult> {
    if (!this.sender) {
      throw new IngestError("The client is disabled (no API key)", { status: null, code: "disabled", retryable: false });
    }
    const lines = logs.map(({ message, level, exception, ...fields }) => buildLine(level ?? "info", message, { ...fields, error: exception }));
    return this.sender.send(lines, this.defaults());
  }

  // Internals -------------------------------------------------------------------

  private defaults(): BatchDefaults {
    const out: BatchDefaults = {};
    if (this.service) out.service = this.service;
    if (this.environment) out.environment = this.environment;
    if (this.host) out.host = this.host;
    return out;
  }

  private enqueue(line: WireLine): void {
    if (!this.sender || this.closing) {
      this.counts.droppedClosed += 1;
      return;
    }
    if (this.buffer.length >= this.maxQueue) {
      this.buffer.shift();
      this.counts.droppedQueueFull += 1;
      this.warnOnce("queue_full", `queue full (${String(this.maxQueue)} lines); dropping the oldest lines (see stats.droppedQueueFull)`);
    }
    this.buffer.push(line);
    if (this.buffer.length >= this.batchSize) {
      void this.drain(false);
    } else if (!this.timer) {
      this.timer = setTimeout(() => {
        this.timer = null;
        void this.drain(true);
      }, this.flushIntervalMs);
      this.timer.unref();
    }
  }

  private clearTimer(): void {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }

  /** Send batches one at a time. `all` sends a final partial batch too; otherwise only
   * full batches go now and the remainder waits for the timer. Never rejects. */
  private drain(all: boolean): Promise<void> {
    const previous = this.draining ?? Promise.resolve();
    const next = previous.then(async () => {
      while (this.sender && this.buffer.length > 0 && (all || this.buffer.length >= this.batchSize)) {
        const batch = this.buffer.splice(0, this.batchSize);
        if (this.buffer.length === 0) this.clearTimer();
        this.inflight += batch.length;
        try {
          await this.deliver(batch);
        } finally {
          this.inflight -= batch.length;
        }
      }
    });
    const settled = next.catch(() => undefined);
    this.draining = settled;
    void settled.then(() => {
      if (this.draining === settled) this.draining = null;
    });
    return settled;
  }

  private async deliver(batch: WireLine[]): Promise<void> {
    if (!this.sender) return;
    let result: IngestResult;
    try {
      result = await this.sender.send(batch, this.defaults());
    } catch (err) {
      this.counts.droppedFailed += batch.length;
      if (err instanceof IngestError) {
        if (err.retryable) this.warnOnce("unreachable", `dropped ${String(batch.length)} lines after retries: ${err.message}`);
        else this.warnOnce(`http_${String(err.status)}_${err.code}`, `dropped ${String(batch.length)} lines: ${err.message}`);
      } else {
        this.warnOnce("unexpected", `dropped ${String(batch.length)} lines (${err instanceof Error ? err.name : typeof err})`);
      }
      return;
    }
    this.counts.batchesSent += 1;
    this.counts.accepted += result.accepted;
    this.counts.rejected += result.rejected.length;
    const first = result.rejected[0];
    if (first) this.warnOnce("rejected", `LogMind rejected ${String(result.rejected.length)} line(s) in a batch, first: ${first.reason}`);
  }

  private sleep(ms: number): Promise<boolean> {
    if (this.abort.signal.aborted) return Promise.resolve(true);
    return new Promise((resolve) => {
      const onAbort = (): void => {
        clearTimeout(timer);
        resolve(true);
      };
      const timer = setTimeout(() => {
        this.abort.signal.removeEventListener("abort", onAbort);
        resolve(false);
      }, ms);
      // Deliberately ref'd: a caller awaiting sendBatch or flush must not see the process
      // exit in the middle of a retry. Waits are bounded (maxRetries, 30 s cap) and close
      // cuts them short, so this never holds a process open indefinitely.
      this.abort.signal.addEventListener("abort", onAbort, { once: true });
    });
  }

  private warnOnce(key: string, message: string): void {
    if (this.warned.has(key)) return;
    this.warned.add(key);
    try {
      this.warnSink(message);
    } catch {
      // a broken warning sink must not break logging
    }
  }

  /** Never prints the key. */
  toJSON(): Record<string, unknown> {
    return { endpoint: this.endpoint, service: this.service, environment: this.environment, enabled: this.enabled };
  }
}

function safeHostname(): string | undefined {
  try {
    return hostname();
  } catch {
    return undefined;
  }
}
