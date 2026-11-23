// Delivery of one batch to `POST {endpoint}/api/v1/logs/batch`, with retries.
//
// Retried: HTTP 408, 429 and 5xx, and transport errors (refused connection, DNS,
// timeouts), with exponential backoff and jitter, honouring `Retry-After`. Not retried:
// every other 4xx (a bad or revoked key, a malformed body), because sending the same
// request again cannot succeed. A 413 is answered by splitting the batch in half.

import { IngestError } from "./errors.js";
import { MAX_BATCH, mergeResults, parseIngestResult, type IngestResult, type WireLine } from "./models.js";
import { SDK_HEADER } from "./version.js";

export const BATCH_PATH = "/api/v1/logs/batch";
export const MAX_BACKOFF_MS = 30_000;
export const MAX_RETRY_AFTER_MS = 60_000;

export type FetchLike = (input: string, init: RequestInit) => Promise<Response>;

/** Resolves `true` when the wait was cut short because the client is closing. */
export type Sleep = (ms: number) => Promise<boolean>;

export interface BatchDefaults {
  service?: string;
  environment?: string;
  host?: string;
}

/** Milliseconds to wait from a `Retry-After` header (delta seconds or an HTTP date). */
export function parseRetryAfter(value: string | null, now: number = Date.now()): number | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (trimmed === "") return null;
  let ms: number;
  const seconds = Number(trimmed);
  if (Number.isFinite(seconds)) {
    ms = seconds * 1000;
  } else {
    const when = Date.parse(trimmed);
    if (Number.isNaN(when)) return null;
    ms = when - now;
  }
  return Math.max(0, Math.min(ms, MAX_RETRY_AFTER_MS));
}

/** `Retry-After` wins when present; otherwise `base * 2^attempt` capped at 30 s, with
 * jitter between half and the full value so clients that failed together spread out. */
export function backoffDelay(attempt: number, baseMs: number, retryAfterMs: number | null = null, rand: () => number = Math.random): number {
  if (retryAfterMs !== null) return retryAfterMs;
  const ceiling = Math.min(MAX_BACKOFF_MS, baseMs * 2 ** attempt);
  return ceiling / 2 + (rand() * ceiling) / 2;
}

async function errorFromResponse(resp: Response): Promise<IngestError> {
  const status = resp.status;
  let code = `http_${String(status)}`;
  let message = resp.statusText || "request failed";
  try {
    const body: unknown = await resp.json();
    if (typeof body === "object" && body !== null) {
      const err = (body as Record<string, unknown>).error;
      if (typeof err === "object" && err !== null) {
        const e = err as Record<string, unknown>;
        if (typeof e.code === "string" && e.code) code = e.code;
        if (typeof e.message === "string" && e.message) message = e.message;
      }
    }
  } catch {
    // not JSON: keep the status text
  }
  return new IngestError(`LogMind answered HTTP ${String(status)} (${code}): ${message}`, {
    status,
    code,
    retryable: status === 408 || status === 429 || status >= 500,
  });
}

function describe(err: unknown): string {
  if (err instanceof Error) {
    const cause = err.cause instanceof Error ? `: ${err.cause.message}` : "";
    return `${err.name}: ${err.message}${cause}`;
  }
  return String(err);
}

export interface SenderOptions {
  endpoint: string;
  apiKey: string;
  fetch: FetchLike;
  timeoutMs: number;
  maxRetries: number;
  backoffBaseMs: number;
  sleep: Sleep;
  onRetry?: () => void;
}

export class Sender {
  readonly maxRetries: number;
  private readonly url: string;
  private readonly headers: Record<string, string>;

  constructor(private readonly options: SenderOptions) {
    this.maxRetries = Math.max(0, options.maxRetries);
    this.url = `${options.endpoint}${BATCH_PATH}`;
    this.headers = {
      authorization: `Bearer ${options.apiKey}`,
      "content-type": "application/json",
      "x-logmind-sdk": SDK_HEADER,
    };
  }

  /** Deliver `lines` (any count; split into requests of at most 1000) or throw an
   * IngestError once retries are exhausted or the error is not retryable. */
  async send(lines: WireLine[], defaults: BatchDefaults): Promise<IngestResult> {
    if (lines.length <= MAX_BATCH) return this.sendChunk(lines, defaults);
    const results: IngestResult[] = [];
    const offsets: number[] = [];
    for (let start = 0; start < lines.length; start += MAX_BATCH) {
      results.push(await this.sendChunk(lines.slice(start, start + MAX_BATCH), defaults));
      offsets.push(start);
    }
    return mergeResults(results, offsets);
  }

  private async sendChunk(lines: WireLine[], defaults: BatchDefaults): Promise<IngestResult> {
    const body = JSON.stringify({ logs: lines, defaults });
    for (let attempt = 0; ; attempt += 1) {
      let error: IngestError;
      let retryAfter: number | null = null;
      const controller = new AbortController();
      const timer = setTimeout(() => {
        controller.abort();
      }, this.options.timeoutMs);
      timer.unref();
      try {
        const resp = await this.options.fetch(this.url, { method: "POST", headers: this.headers, body, signal: controller.signal });
        if (resp.ok) {
          let payload: unknown;
          try {
            payload = await resp.json();
          } catch {
            payload = { accepted: lines.length };
          }
          return parseIngestResult(payload);
        }
        if (resp.status === 413 && lines.length > 1) {
          const half = Math.floor(lines.length / 2);
          const first = await this.sendChunk(lines.slice(0, half), defaults);
          const second = await this.sendChunk(lines.slice(half), defaults);
          return mergeResults([first, second], [0, half]);
        }
        error = await errorFromResponse(resp);
        retryAfter = parseRetryAfter(resp.headers.get("retry-after"));
      } catch (err) {
        if (err instanceof IngestError) throw err;
        // The error text can carry the URL, never a header, so it is safe to report.
        error = new IngestError(`Could not reach LogMind (${describe(err)})`, { status: null, code: "transport_error", retryable: true });
      } finally {
        clearTimeout(timer);
      }
      if (!error.retryable || attempt >= this.maxRetries) throw error;
      this.options.onRetry?.();
      if (await this.options.sleep(backoffDelay(attempt, this.options.backoffBaseMs, retryAfter))) throw error;
    }
  }
}
