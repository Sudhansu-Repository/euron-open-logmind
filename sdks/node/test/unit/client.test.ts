import { hostname } from "node:os";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_ENDPOINT, LogMind } from "../../src/client.js";
import { IngestError } from "../../src/errors.js";
import type * as models from "../../src/models.js";
import { API_KEY, BASE, fakeFetch, jsonResponse, makeClient, waitFor } from "./helpers.js";

const ENV_NAMES = ["LOGMIND_API_KEY", "LOGMIND_ENDPOINT", "LOGMIND_SERVICE", "LOGMIND_ENVIRONMENT"] as const;
const savedEnv: Record<string, string | undefined> = {};

beforeEach(() => {
  for (const name of ENV_NAMES) {
    savedEnv[name] = process.env[name];
    Reflect.deleteProperty(process.env, name);
  }
});

afterEach(() => {
  for (const name of ENV_NAMES) {
    const value = savedEnv[name];
    if (value === undefined) Reflect.deleteProperty(process.env, name);
    else process.env[name] = value;
  }
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("batching", () => {
  it("sends once batchSize lines are queued", async () => {
    const fake = fakeFetch();
    const log = makeClient(fake.fetch, { batchSize: 3 });
    log.info("line 0");
    log.info("line 1");
    expect(fake.requests).toHaveLength(0);
    log.info("line 2");
    expect(await waitFor(() => fake.requests.length === 1)).toBe(true);
    expect(fake.lines().map((l) => l.message)).toEqual(["line 0", "line 1", "line 2"]);
    await log.close();
  });

  it("splits by batchSize and keeps order", async () => {
    const fake = fakeFetch();
    const log = makeClient(fake.fetch, { batchSize: 2 });
    for (let i = 0; i < 5; i += 1) log.info(`line ${String(i)}`);
    expect(await log.flush()).toBe(true);
    expect(fake.requests.map((r) => r.body.logs.length)).toEqual([2, 2, 1]);
    expect(fake.lines().map((l) => l.message)).toEqual(["line 0", "line 1", "line 2", "line 3", "line 4"]);
    await log.close();
  });

  it("sends a partial batch after flushIntervalMs", async () => {
    vi.useFakeTimers();
    const fake = fakeFetch();
    const log = makeClient(fake.fetch, { batchSize: 100, flushIntervalMs: 1000 });
    log.info("lonely");
    await vi.advanceTimersByTimeAsync(999);
    expect(fake.requests).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(5);
    expect(fake.requests).toHaveLength(1);
    expect(log.stats.queued).toBe(0);
    await log.close();
  });

  it("re-arms the timer for lines left after a size-triggered send", async () => {
    vi.useFakeTimers();
    const fake = fakeFetch();
    const log = makeClient(fake.fetch, { batchSize: 2, flushIntervalMs: 500 });
    log.info("a");
    log.info("b");
    log.info("c");
    await vi.advanceTimersByTimeAsync(0);
    expect(fake.requests).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(600);
    expect(fake.requests).toHaveLength(2);
    expect(fake.lines().map((l) => l.message)).toEqual(["a", "b", "c"]);
    await log.close();
  });

  it("re-arms the timer when lines arrive while a batch is in flight", async () => {
    vi.useFakeTimers();
    let release: () => void = () => undefined;
    const gate = new Promise<void>((r) => {
      release = r;
    });
    const fake = fakeFetch(async (req) => {
      await gate;
      return Response.json({ accepted: req.body.logs.length }, { status: 202 });
    });
    const log = makeClient(fake.fetch, { batchSize: 1, flushIntervalMs: 500 });
    log.info("first");
    await vi.advanceTimersByTimeAsync(0);
    // batchSize 1 means "late" also triggers a drain, which waits behind the first batch
    log.info("late");
    release();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(600);
    expect(fake.lines().map((l) => l.message)).toEqual(["first", "late"]);
    await log.close();
  });

  it("clamps batchSize to the API limit", () => {
    expect(makeClient(fakeFetch().fetch, { batchSize: 50_000 }).batchSize).toBe(1000);
    expect(makeClient(fakeFetch().fetch, { batchSize: 0 }).batchSize).toBe(1);
  });
});

describe("serialisation and defaults", () => {
  it("sends service, environment and host as batch defaults", async () => {
    const fake = fakeFetch();
    const log = makeClient(fake.fetch);
    log.info("hello");
    await log.close();
    expect(fake.requests[0]!.body.defaults).toEqual({ service: "checkout", environment: "test", host: "web-1" });
    expect(fake.lines()[0]).not.toHaveProperty("service");
  });

  it("uses sensible defaults", async () => {
    const fake = fakeFetch();
    const log = new LogMind({ apiKey: API_KEY, fetch: fake.fetch, flushOnExit: false });
    expect(log.endpoint).toBe(DEFAULT_ENDPOINT);
    expect(log.environment).toBe("production");
    expect(log.host).toBe(hostname());
    expect(log.service).toBeUndefined();
    expect(log.flushIntervalMs).toBe(1000);
    expect(log.maxQueue).toBe(10_000);
    log.info("x");
    await log.close();
    expect(fake.requests[0]!.url).toBe("http://localhost:6030/api/v1/logs/batch");
    expect(fake.requests[0]!.body.defaults).toEqual({ environment: "production", host: hostname() });
  });

  it("leaves out an empty host and service", async () => {
    const fake = fakeFetch();
    const log = makeClient(fake.fetch, { host: "", service: "" });
    log.info("x");
    await log.close();
    expect(fake.requests[0]!.body.defaults).toEqual({ environment: "test" });
  });

  it("has a method per level", async () => {
    const fake = fakeFetch();
    const log = makeClient(fake.fetch);
    log.trace("t");
    log.debug("d");
    log.info("i");
    log.warn("w");
    log.error("e");
    log.fatal("f");
    log.log("warning", "l1");
    log.log("critical", "l2");
    await log.close();
    expect(fake.lines().map((l) => [l.message, l.level])).toEqual([
      ["t", "trace"],
      ["d", "debug"],
      ["i", "info"],
      ["w", "warn"],
      ["e", "error"],
      ["f", "fatal"],
      ["l1", "warn"],
      ["l2", "fatal"],
    ]);
  });

  it("maps fields, attributes and correlation ids", async () => {
    const fake = fakeFetch();
    const log = makeClient(fake.fetch);
    log.info("order placed", {
      attributes: { orderId: 42, amount: 19.99 },
      customer: "acme",
      traceId: "4bf92f3577b34da6a3ce929d0e0e4736",
      spanId: "00f067aa0ba902b7",
      requestId: "req-7",
      service: "billing",
    });
    await log.close();
    const line = fake.lines()[0]!;
    expect(line.attributes).toEqual({ orderId: 42, amount: 19.99, customer: "acme" });
    expect(line.trace_id).toBe("4bf92f3577b34da6a3ce929d0e0e4736");
    expect(line.span_id).toBe("00f067aa0ba902b7");
    expect(line.request_id).toBe("req-7");
    expect(line.service).toBe("billing");
  });

  it("captures the timestamp at call time as ISO 8601", async () => {
    const fake = fakeFetch();
    const log = makeClient(fake.fetch);
    const before = Date.now();
    log.info("early");
    const after = Date.now();
    await new Promise((r) => setTimeout(r, 30));
    log.info("explicit", { timestamp: new Date(0) });
    await log.close();
    const [early, explicit] = fake.lines();
    const at = Date.parse(early!.timestamp as string);
    expect(early!.timestamp).toMatch(/Z$/);
    expect(at).toBeGreaterThanOrEqual(before);
    expect(at).toBeLessThanOrEqual(after);
    expect(explicit!.timestamp).toBe("1970-01-01T00:00:00.000Z");
  });

  it("captureException uses err.name, err.message and err.stack", async () => {
    const fake = fakeFetch();
    const log = makeClient(fake.fetch);
    const err = new TypeError("cannot read properties of undefined");
    log.captureException(err, { orderId: 1 });
    log.captureException(new Error("db down"), { message: "query failed", requestId: "r1" });
    log.error("with error field", { error: new RangeError("bad") });
    await log.close();
    const [first, second, third] = fake.lines();
    expect(first!.level).toBe("error");
    expect(first!.message).toBe("cannot read properties of undefined");
    expect(first!.exception).toEqual({ type: "TypeError", message: "cannot read properties of undefined", stacktrace: err.stack });
    expect(first!.attributes).toEqual({ orderId: 1 });
    expect(second!.message).toBe("query failed");
    expect(second!.request_id).toBe("r1");
    expect(second!.exception.type).toBe("Error");
    expect(third!.exception.type).toBe("RangeError");
  });

  it("never lets an odd attribute break a batch", async () => {
    const fake = fakeFetch();
    const log = makeClient(fake.fetch);
    const loop: Record<string, unknown> = {};
    loop.self = loop;
    log.info("odd", { attributes: { big: 1n, nan: Number.NaN, loop } });
    log.info("fine");
    await log.close();
    expect(fake.lines()).toHaveLength(2);
    expect(fake.lines()[0]!.attributes).toEqual({ big: "1", nan: "NaN", loop: { self: "[Circular]" } });
  });
});

describe("env defaults", () => {
  it("reads LOGMIND_* variables", async () => {
    process.env.LOGMIND_API_KEY = API_KEY;
    process.env.LOGMIND_ENDPOINT = "http://logs.internal.test:6030/";
    process.env.LOGMIND_SERVICE = "worker";
    process.env.LOGMIND_ENVIRONMENT = "staging";
    const fake = fakeFetch();
    const log = new LogMind({ fetch: fake.fetch, flushOnExit: false });
    expect(log.enabled).toBe(true);
    expect(log.endpoint).toBe("http://logs.internal.test:6030");
    expect(log.service).toBe("worker");
    expect(log.environment).toBe("staging");
    log.info("from env");
    await log.close();
    expect(fake.requests[0]!.url).toBe("http://logs.internal.test:6030/api/v1/logs/batch");
    expect(fake.requests[0]!.headers.authorization).toBe(`Bearer ${API_KEY}`);
  });

  it("explicit options beat env", async () => {
    process.env.LOGMIND_API_KEY = "lmk_env_env";
    process.env.LOGMIND_ENDPOINT = "http://env.test";
    const fake = fakeFetch();
    const log = makeClient(fake.fetch);
    log.info("x");
    await log.close();
    expect(fake.requests[0]!.url.startsWith(BASE)).toBe(true);
    expect(fake.requests[0]!.headers.authorization).toBe(`Bearer ${API_KEY}`);
  });

  it("a missing key disables the client with one warning", async () => {
    const warnings: string[] = [];
    const fake = fakeFetch();
    const log = new LogMind({ fetch: fake.fetch, onWarning: (m) => warnings.push(m) });
    expect(log.enabled).toBe(false);
    log.info("dropped");
    expect(await log.flush()).toBe(true);
    expect(await log.close()).toBe(true);
    expect(fake.requests).toHaveLength(0);
    expect(log.stats.droppedClosed).toBe(1);
    expect(warnings).toEqual(["no API key (pass apiKey or set LOGMIND_API_KEY); logging is disabled"]);
    await expect(log.sendBatch([{ message: "x" }])).rejects.toMatchObject({ code: "disabled" });
  });

  it("disables itself without a fetch implementation", () => {
    const warnings: string[] = [];
    vi.stubGlobal("fetch", undefined);
    const log = new LogMind({ apiKey: API_KEY, onWarning: (m) => warnings.push(m) });
    vi.unstubAllGlobals();
    expect(log.enabled).toBe(false);
    expect(warnings[0]).toContain("no global fetch");
  });

  it("uses the global fetch by default", async () => {
    const fake = fakeFetch();
    vi.stubGlobal("fetch", fake.fetch);
    const log = new LogMind({ apiKey: API_KEY, flushOnExit: false });
    vi.unstubAllGlobals();
    log.info("global");
    await log.close();
    expect(fake.requests).toHaveLength(1);
  });

  it("writes warnings to stderr by default", () => {
    const write = vi.spyOn(process.stderr, "write").mockImplementation(() => true);
    new LogMind({ fetch: fakeFetch().fetch });
    expect(write).toHaveBeenCalledWith(expect.stringContaining("[euron-logmind] no API key"));
  });

  it("survives a broken stderr and a broken warning sink", () => {
    vi.spyOn(process.stderr, "write").mockImplementation(() => {
      throw new Error("EPIPE");
    });
    expect(() => new LogMind({ fetch: fakeFetch().fetch })).not.toThrow();
    expect(
      () =>
        new LogMind({
          fetch: fakeFetch().fetch,
          onWarning: () => {
            throw new Error("sink");
          },
        }),
    ).not.toThrow();
  });
});

describe("failure behaviour", () => {
  it("retries then delivers", async () => {
    const fake = fakeFetch(new Response("", { status: 503 }), jsonResponse(429, {}, { "retry-after": "0" }), new TypeError("fetch failed"));
    const log = makeClient(fake.fetch);
    log.info("eventually");
    await log.close();
    expect(fake.requests).toHaveLength(4);
    expect(log.stats).toMatchObject({ accepted: 1, retries: 3, droppedFailed: 0 });
  });

  it("drops after retries with one warning when unreachable", async () => {
    const warnings: string[] = [];
    const fake = fakeFetch(...Array.from({ length: 20 }, () => new TypeError("fetch failed")));
    const log = makeClient(fake.fetch, { maxRetries: 1, batchSize: 1, onWarning: (m) => warnings.push(m) });
    log.info("a");
    log.info("b");
    expect(await log.flush()).toBe(true);
    await log.close();
    expect(log.stats).toMatchObject({ droppedFailed: 2, accepted: 0, retries: 2 });
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toContain("after retries");
  });

  it("drops on a bad key with one warning and never leaks the key", async () => {
    const warnings: string[] = [];
    const unauthorized = () => jsonResponse(401, { error: { code: "invalid_api_key", message: "The API key is invalid or revoked" } });
    const fake = fakeFetch(unauthorized(), unauthorized(), unauthorized());
    const log = makeClient(fake.fetch, { batchSize: 1, onWarning: (m) => warnings.push(m) });
    log.info("1");
    log.info("2");
    log.info("3");
    await log.close();
    expect(fake.requests).toHaveLength(3);
    expect(log.stats.droppedFailed).toBe(3);
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toContain("401");
    expect(warnings[0]).toContain("invalid_api_key");
    expect(warnings.join("")).not.toContain("0123456789abcdef");
    expect(JSON.stringify(log)).not.toContain("lmk_");
  });

  it("counts server-side rejections", async () => {
    const warnings: string[] = [];
    const fake = fakeFetch(jsonResponse(202, { accepted: 1, rejected: [{ index: 1, reason: "bad timestamp" }], event_ids: ["e1"] }));
    const log = makeClient(fake.fetch, { onWarning: (m) => warnings.push(m) });
    log.info("ok");
    log.info("bad");
    await log.close();
    expect(log.stats).toMatchObject({ accepted: 1, rejected: 1, batchesSent: 1 });
    expect(warnings[0]).toContain("bad timestamp");
  });

  it("never throws when building a line fails", async () => {
    const warnings: string[] = [];
    const log = makeClient(fakeFetch().fetch, { onWarning: (m) => warnings.push(m) });
    const hostile = Object.defineProperty({}, "attributes", {
      enumerable: true,
      get() {
        throw new Error("bug");
      },
    }) as models.LogFields;
    expect(() => {
      log.info("x", hostile);
    }).not.toThrow();
    expect(() => {
      log.log("info", "y", hostile);
    }).not.toThrow();
    await log.close();
    expect(warnings[0]).toContain("could not record");
  });

  it("an unexpected error in delivery drops the batch and keeps going", async () => {
    const warnings: string[] = [];
    const fake = fakeFetch();
    const log = makeClient(fake.fetch, { batchSize: 1, onWarning: (m) => warnings.push(m) });
    const sender = (log as unknown as { sender: { send: (...a: unknown[]) => Promise<unknown> } }).sender;
    const original = sender.send.bind(sender);
    let calls = 0;
    sender.send = (...args: unknown[]) => {
      calls += 1;
      if (calls === 1) return Promise.reject(new RangeError("bug"));
      if (calls === 2) return Promise.reject("not an error"); // eslint-disable-line @typescript-eslint/prefer-promise-reject-errors
      return original(...args);
    };
    log.info("first");
    log.info("second");
    log.info("third");
    await log.close();
    expect(log.stats).toMatchObject({ droppedFailed: 2, accepted: 1 });
    expect(warnings).toEqual(["dropped 1 lines (RangeError)"]);
  });
});

describe("queue overflow", () => {
  it("drops the oldest lines when full", async () => {
    const warnings: string[] = [];
    const fake = fakeFetch();
    const log = makeClient(fake.fetch, { maxQueue: 3, batchSize: 100, onWarning: (m) => warnings.push(m) });
    for (let i = 0; i < 5; i += 1) log.info(`line ${String(i)}`);
    expect(log.stats).toMatchObject({ droppedQueueFull: 2, queued: 3 });
    await log.close();
    expect(fake.lines().map((l) => l.message)).toEqual(["line 2", "line 3", "line 4"]);
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toContain("oldest");
  });
});

describe("flush and close", () => {
  it("flush resolves true when drained and false on timeout", async () => {
    const fake = fakeFetch();
    const log = makeClient(fake.fetch);
    expect(await log.flush()).toBe(true);
    log.info("x");
    expect(await log.flush(1000)).toBe(true);
    expect(fake.requests).toHaveLength(1);

    const slow = fakeFetch(async (req) => {
      await new Promise((r) => setTimeout(r, 200));
      return Response.json({ accepted: req.body.logs.length }, { status: 202 });
    });
    const log2 = makeClient(slow.fetch);
    log2.info("slow");
    expect(await log2.flush(20)).toBe(false);
    expect(await log2.flush()).toBe(true);
    await log.close();
    await log2.close();
  });

  it("close flushes, is idempotent and drops later lines", async () => {
    const fake = fakeFetch();
    const log = makeClient(fake.fetch);
    log.info("a");
    log.info("b");
    expect(await log.close()).toBe(true);
    expect(fake.lines()).toHaveLength(2);
    expect(await log.close()).toBe(true);
    expect(log.enabled).toBe(false);
    log.info("late");
    expect(log.stats.droppedClosed).toBe(1);
    expect(fake.requests).toHaveLength(1);
  });

  it("a concurrent close waits for the same flush", async () => {
    const fake = fakeFetch();
    const log = makeClient(fake.fetch);
    log.info("a");
    const [first, second] = await Promise.all([log.close(), log.close()]);
    expect(first).toBe(true);
    expect(second).toBe(true);
    expect(fake.requests).toHaveLength(1);
  });

  it("close respects its timeout when the server is down", async () => {
    const fake = fakeFetch(...Array.from({ length: 200 }, () => new TypeError("fetch failed")));
    const log = makeClient(fake.fetch, { maxRetries: 50, backoffBaseMs: 200 });
    log.info("stuck");
    const started = Date.now();
    expect(await log.close(100)).toBe(false);
    expect(Date.now() - started).toBeLessThan(2000);
    await waitFor(() => log.stats.queued === 0);
    expect(log.stats.droppedFailed + log.stats.droppedClosed).toBe(1);
  });

  it("close drops lines still queued after the timeout", async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((r) => {
      release = r;
    });
    const fake = fakeFetch(async (req) => {
      await gate;
      return Response.json({ accepted: req.body.logs.length }, { status: 202 });
    });
    const log = makeClient(fake.fetch, { batchSize: 1 });
    log.info("in flight");
    log.info("waiting");
    expect(await log.close(20)).toBe(false);
    expect(log.stats.droppedClosed).toBe(1);
    release();
    await waitFor(() => log.stats.queued === 0);
    expect(log.stats.accepted).toBe(1);
  });

  it("flushes on beforeExit and removes the listener on close", async () => {
    const before = process.listenerCount("beforeExit");
    const fake = fakeFetch();
    const log = makeClient(fake.fetch, { flushOnExit: true });
    expect(process.listenerCount("beforeExit")).toBe(before + 1);
    process.emit("beforeExit", 0);
    expect(fake.requests).toHaveLength(0); // nothing queued, nothing sent
    log.info("at exit");
    process.emit("beforeExit", 0);
    expect(await waitFor(() => fake.requests.length === 1)).toBe(true);
    await log.close();
    expect(process.listenerCount("beforeExit")).toBe(before);
  });

  it("the flush timer is unref'd so it never keeps the process alive", () => {
    const fake = fakeFetch();
    const log = makeClient(fake.fetch, { flushIntervalMs: 60_000 });
    log.info("pending");
    const timer = (log as unknown as { timer: NodeJS.Timeout }).timer;
    expect(timer.hasRef()).toBe(false);
    void log.close();
  });

  it("toJSON never contains the key", () => {
    const log = makeClient(fakeFetch().fetch);
    expect(log.toJSON()).toEqual({ endpoint: BASE, service: "checkout", environment: "test", enabled: true });
    void log.close();
  });
});

describe("sendBatch", () => {
  it("returns the IngestResult", async () => {
    const fake = fakeFetch();
    const log = makeClient(fake.fetch);
    const result = await log.sendBatch([
      { message: "one", level: "warning", attributes: { k: "v" }, traceId: "abc" },
      { message: "two", exception: new Error("bad"), timestamp: 0 },
      { message: "three" },
    ]);
    expect(result.accepted).toBe(3);
    expect(result.eventIds).toHaveLength(3);
    const [one, two, three] = fake.lines();
    expect(one).toMatchObject({ level: "warn", attributes: { k: "v" }, trace_id: "abc" });
    expect(two!.exception.type).toBe("Error");
    expect(two!.timestamp).toBe("1970-01-01T00:00:00.000Z");
    expect(three!.level).toBe("info");
    expect(fake.requests[0]!.body.defaults.service).toBe("checkout");
    await log.close();
  });

  it("rejects with IngestError on failure", async () => {
    const fake = fakeFetch(jsonResponse(401, { error: { code: "invalid_api_key", message: "revoked" } }));
    const log = makeClient(fake.fetch);
    const err = (await log.sendBatch([{ message: "x" }]).catch((e: unknown) => e)) as IngestError;
    expect(err).toBeInstanceOf(IngestError);
    expect(err.status).toBe(401);
    await log.close();
  });
});
