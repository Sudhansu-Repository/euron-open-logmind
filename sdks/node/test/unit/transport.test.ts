import { describe, expect, it } from "vitest";

import { IngestError } from "../../src/errors.js";
import { buildLine, type WireLine } from "../../src/models.js";
import { BATCH_PATH, MAX_BACKOFF_MS, MAX_RETRY_AFTER_MS, Sender, backoffDelay, parseRetryAfter, type FetchLike } from "../../src/transport.js";
import { API_KEY, BASE, fakeFetch, jsonResponse } from "./helpers.js";

function makeSender(fetchImpl: FetchLike, options: { maxRetries?: number; abort?: boolean; timeoutMs?: number } = {}) {
  const sleeps: number[] = [];
  let retries = 0;
  const sender = new Sender({
    endpoint: BASE,
    apiKey: API_KEY,
    fetch: fetchImpl,
    timeoutMs: options.timeoutMs ?? 1000,
    maxRetries: options.maxRetries ?? 3,
    backoffBaseMs: 500,
    sleep: (ms) => {
      sleeps.push(ms);
      return Promise.resolve(options.abort ?? false);
    },
    onRetry: () => {
      retries += 1;
    },
  });
  return { sender, sleeps, retries: () => retries };
}

function lines(n: number): WireLine[] {
  return Array.from({ length: n }, (_, i) => buildLine("info", `line ${String(i)}`));
}

const DEFAULTS = { service: "checkout" };

describe("parseRetryAfter", () => {
  it("parses seconds and HTTP dates, clamped", () => {
    expect(parseRetryAfter(null)).toBeNull();
    expect(parseRetryAfter("")).toBeNull();
    expect(parseRetryAfter("   ")).toBeNull();
    expect(parseRetryAfter("3")).toBe(3000);
    expect(parseRetryAfter("1.5")).toBe(1500);
    expect(parseRetryAfter("-4")).toBe(0);
    expect(parseRetryAfter("100000")).toBe(MAX_RETRY_AFTER_MS);
    expect(parseRetryAfter("soon")).toBeNull();
    const now = Date.parse("2026-11-16T12:00:00Z");
    expect(parseRetryAfter("Mon, 16 Nov 2026 12:00:07 GMT", now)).toBe(7000);
  });
});

describe("backoffDelay", () => {
  it("grows exponentially with jitter and caps", () => {
    expect(backoffDelay(0, 500, null, () => 0)).toBe(250);
    expect(backoffDelay(0, 500, null, () => 1)).toBe(500);
    expect(backoffDelay(3, 500, null, () => 1)).toBe(4000);
    expect(backoffDelay(20, 500, null, () => 1)).toBe(MAX_BACKOFF_MS);
    expect(backoffDelay(2, 500, 9000)).toBe(9000);
    for (let attempt = 0; attempt < 5; attempt += 1) {
      const value = backoffDelay(attempt, 1000);
      expect(value).toBeGreaterThanOrEqual((1000 * 2 ** attempt) / 2);
      expect(value).toBeLessThanOrEqual(1000 * 2 ** attempt);
    }
  });
});

describe("Sender", () => {
  it("posts a batch with the contract headers", async () => {
    const fake = fakeFetch();
    const { sender, sleeps } = makeSender(fake.fetch);
    const result = await sender.send(lines(3), DEFAULTS);
    expect(result.accepted).toBe(3);
    expect(result.eventIds).toHaveLength(3);
    expect(sleeps).toEqual([]);
    const req = fake.requests[0]!;
    expect(req.url).toBe(`${BASE}${BATCH_PATH}`);
    expect(req.method).toBe("POST");
    expect(req.headers.authorization).toBe(`Bearer ${API_KEY}`);
    expect(req.headers["content-type"]).toBe("application/json");
    expect(req.headers["x-logmind-sdk"]).toBe("node/0.1.0");
    expect(req.body.defaults).toEqual(DEFAULTS);
    expect(req.body.logs.map((l) => l.message)).toEqual(["line 0", "line 1", "line 2"]);
  });

  it("retries 5xx then succeeds", async () => {
    const fake = fakeFetch(new Response("", { status: 503 }), new Response("", { status: 500 }));
    const { sender, sleeps, retries } = makeSender(fake.fetch);
    expect((await sender.send(lines(1), DEFAULTS)).accepted).toBe(1);
    expect(fake.requests).toHaveLength(3);
    expect(sleeps).toHaveLength(2);
    expect(sleeps[0]).toBeGreaterThanOrEqual(250);
    expect(sleeps[0]).toBeLessThanOrEqual(500);
    expect(sleeps[1]).toBeGreaterThanOrEqual(500);
    expect(retries()).toBe(2);
  });

  it("honours Retry-After on 429", async () => {
    const fake = fakeFetch(jsonResponse(429, { error: { code: "rate_limited", message: "slow down" } }, { "retry-after": "2" }));
    const { sender, sleeps } = makeSender(fake.fetch);
    expect((await sender.send(lines(1), DEFAULTS)).accepted).toBe(1);
    expect(sleeps).toEqual([2000]);
  });

  it("retries transport errors", async () => {
    const fake = fakeFetch(new TypeError("fetch failed", { cause: new Error("ECONNREFUSED") }), new Error("socket hang up"));
    const { sender, sleeps } = makeSender(fake.fetch);
    expect((await sender.send(lines(1), DEFAULTS)).accepted).toBe(1);
    expect(sleeps).toHaveLength(2);
  });

  it("gives up after maxRetries", async () => {
    const fake = fakeFetch(...Array.from({ length: 10 }, () => new Response("", { status: 503 })));
    const { sender, sleeps } = makeSender(fake.fetch, { maxRetries: 2 });
    const err = (await sender.send(lines(1), DEFAULTS).catch((e: unknown) => e)) as IngestError;
    expect(err).toBeInstanceOf(IngestError);
    expect(err.status).toBe(503);
    expect(err.retryable).toBe(true);
    expect(fake.requests).toHaveLength(3);
    expect(sleeps).toHaveLength(2);
  });

  it("reports an exhausted transport error without a status and without the key", async () => {
    const fake = fakeFetch(new TypeError("fetch failed", { cause: new Error("ECONNREFUSED") }));
    const { sender } = makeSender(fake.fetch, { maxRetries: 0 });
    const err = (await sender.send(lines(1), DEFAULTS).catch((e: unknown) => e)) as IngestError;
    expect(err.status).toBeNull();
    expect(err.code).toBe("transport_error");
    expect(err.message).toContain("ECONNREFUSED");
    expect(err.message).not.toContain(API_KEY);
  });

  it("describes a thrown non-Error", async () => {
    const odd: FetchLike = async () => {
      await Promise.resolve();
      throw "plain"; // eslint-disable-line @typescript-eslint/only-throw-error
    };
    const { sender } = makeSender(odd, { maxRetries: 0 });
    const err = (await sender.send(lines(1), DEFAULTS).catch((e: unknown) => e)) as IngestError;
    expect(err.message).toContain("plain");
  });

  it("does not retry 401 and reads the error body", async () => {
    const fake = fakeFetch(jsonResponse(401, { error: { code: "invalid_api_key", message: "The API key is invalid or revoked" } }));
    const { sender, sleeps } = makeSender(fake.fetch);
    const err = (await sender.send(lines(2), DEFAULTS).catch((e: unknown) => e)) as IngestError;
    expect(err.status).toBe(401);
    expect(err.code).toBe("invalid_api_key");
    expect(err.message).toContain("revoked");
    expect(err.retryable).toBe(false);
    expect(err.name).toBe("IngestError");
    expect(fake.requests).toHaveLength(1);
    expect(sleeps).toEqual([]);
  });

  it("handles a 4xx without a JSON body or with an odd one", async () => {
    const fake = fakeFetch(new Response("<html>nope</html>", { status: 422 }), jsonResponse(400, { error: "flat" }));
    const { sender } = makeSender(fake.fetch);
    const first = (await sender.send(lines(1), DEFAULTS).catch((e: unknown) => e)) as IngestError;
    expect(first.code).toBe("http_422");
    const second = (await sender.send(lines(1), DEFAULTS).catch((e: unknown) => e)) as IngestError;
    expect(second.code).toBe("http_400");
  });

  it("stops retrying when the sleep is aborted", async () => {
    const fake = fakeFetch(new Response("", { status: 503 }), new Response("", { status: 503 }));
    const { sender, sleeps } = makeSender(fake.fetch, { abort: true });
    await expect(sender.send(lines(1), DEFAULTS)).rejects.toBeInstanceOf(IngestError);
    expect(fake.requests).toHaveLength(1);
    expect(sleeps).toHaveLength(1);
  });

  it("splits a batch in half on 413", async () => {
    const fake = fakeFetch(jsonResponse(413, { error: { code: "payload_too_large", message: "too big" } }));
    const { sender } = makeSender(fake.fetch);
    expect((await sender.send(lines(4), DEFAULTS)).accepted).toBe(4);
    expect(fake.requests.map((r) => r.body.logs.length)).toEqual([4, 2, 2]);
  });

  it("drops a single line that is still too large", async () => {
    const fake = fakeFetch(new Response("", { status: 413 }));
    const { sender } = makeSender(fake.fetch);
    const err = (await sender.send(lines(1), DEFAULTS).catch((e: unknown) => e)) as IngestError;
    expect(err.status).toBe(413);
  });

  it("propagates a failure inside a split half", async () => {
    const fake = fakeFetch(new Response("", { status: 413 }), jsonResponse(401, { error: { code: "invalid_api_key", message: "no" } }));
    const { sender } = makeSender(fake.fetch);
    const err = (await sender.send(lines(2), DEFAULTS).catch((e: unknown) => e)) as IngestError;
    expect(err.status).toBe(401);
    expect(fake.requests).toHaveLength(2);
  });

  it("splits more than 1000 lines into several requests", async () => {
    const fake = fakeFetch();
    const { sender } = makeSender(fake.fetch);
    const result = await sender.send(lines(2500), DEFAULTS);
    expect(fake.requests.map((r) => r.body.logs.length)).toEqual([1000, 1000, 500]);
    expect(result.accepted).toBe(2500);
    expect(result.eventIds).toHaveLength(2500);
  });

  it("counts every line when a success has no JSON body", async () => {
    const fake = fakeFetch(new Response("ok", { status: 202 }));
    const { sender } = makeSender(fake.fetch);
    expect((await sender.send(lines(3), DEFAULTS)).accepted).toBe(3);
  });

  it("aborts a request that exceeds the timeout and retries it", async () => {
    const hang = (_req: unknown, signal: AbortSignal | null | undefined): Promise<Response> =>
      new Promise((_resolve, reject) => {
        signal?.addEventListener("abort", () => {
          reject(new DOMException("This operation was aborted", "AbortError"));
        });
      });
    const fake = fakeFetch(hang);
    const { sender, sleeps } = makeSender(fake.fetch, { timeoutMs: 20 });
    expect((await sender.send(lines(1), DEFAULTS)).accepted).toBe(1);
    expect(fake.requests).toHaveLength(2);
    expect(sleeps).toHaveLength(1);
  });
});
