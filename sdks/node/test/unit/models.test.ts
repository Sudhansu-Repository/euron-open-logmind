import { describe, expect, it } from "vitest";

import {
  LIMITS,
  buildLine,
  clamp,
  exceptionPayload,
  isoTimestamp,
  jsonable,
  mergeResults,
  normalizeLevel,
  parseIngestResult,
} from "../../src/models.js";

describe("normalizeLevel", () => {
  it.each([
    ["info", "info"],
    ["INFO", "info"],
    [" Warn ", "warn"],
    ["warning", "warn"],
    ["critical", "fatal"],
    ["fatal", "fatal"],
    ["err", "error"],
    ["trace", "trace"],
    ["debug", "debug"],
    ["panic", "fatal"],
    ["notice", "info"],
    ["nonsense", "info"],
  ])("%s -> %s", (given, expected) => {
    expect(normalizeLevel(given)).toBe(expected);
  });
});

describe("isoTimestamp", () => {
  it("defaults to now in ISO 8601 UTC", () => {
    const stamp = isoTimestamp();
    expect(stamp).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
    expect(Math.abs(Date.parse(stamp) - Date.now())).toBeLessThan(5000);
  });

  it("accepts Dates, epoch milliseconds and strings", () => {
    expect(isoTimestamp(new Date(0))).toBe("1970-01-01T00:00:00.000Z");
    expect(isoTimestamp(1500)).toBe("1970-01-01T00:00:01.500Z");
    expect(isoTimestamp("2026-11-16T12:00:00+05:30")).toBe("2026-11-16T12:00:00+05:30");
  });

  it("replaces an invalid date with now", () => {
    expect(Math.abs(Date.parse(isoTimestamp(new Date("nope"))) - Date.now())).toBeLessThan(5000);
  });
});

describe("jsonable", () => {
  it("makes awkward values JSON safe", () => {
    const loop: Record<string, unknown> = { name: "loop" };
    loop.self = loop;
    const out = jsonable({
      n: 1,
      nan: Number.NaN,
      inf: Number.POSITIVE_INFINITY,
      big: 10n,
      fn: function named() {
        return 1;
      },
      sym: Symbol("s"),
      undef: undefined,
      when: new Date(0),
      err: new TypeError("bad"),
      map: new Map([["a", 1]]),
      set: new Set([1, 2]),
      bytes: new Uint8Array(3),
      list: [1, "two", null],
      loop,
    }) as Record<string, unknown>;
    expect(out.n).toBe(1);
    expect(out.nan).toBe("NaN");
    expect(out.inf).toBe("Infinity");
    expect(out.big).toBe("10");
    expect(out.fn).toContain("named");
    expect(out.sym).toBe("Symbol(s)");
    expect(out.undef).toBeNull();
    expect(out.when).toBe("1970-01-01T00:00:00.000Z");
    expect(out.err).toEqual({ name: "TypeError", message: "bad" });
    expect(out.map).toEqual({ a: 1 });
    expect(out.set).toEqual([1, 2]);
    expect(out.bytes).toBe("[Uint8Array 3 bytes]");
    expect(out.list).toEqual([1, "two", null]);
    expect(out.loop).toEqual({ name: "loop", self: "[Circular]" });
    expect(() => JSON.stringify(out)).not.toThrow();
  });

  it("keeps a repeated (non-circular) reference and cuts very deep nesting", () => {
    const shared = { k: 1 };
    expect(jsonable({ a: shared, b: shared })).toEqual({ a: { k: 1 }, b: { k: 1 } });
    let deep: Record<string, unknown> = { leaf: true };
    for (let i = 0; i < 20; i += 1) deep = { next: deep };
    expect(JSON.stringify(jsonable(deep))).toContain("[Truncated]");
  });
});

describe("exceptionPayload", () => {
  it("is undefined without an error", () => {
    expect(exceptionPayload(undefined)).toBeUndefined();
    expect(exceptionPayload(null)).toBeUndefined();
  });

  it("uses err.name, err.message and err.stack", () => {
    const err = new RangeError("out of range");
    const payload = exceptionPayload(err)!;
    expect(payload.type).toBe("RangeError");
    expect(payload.message).toBe("out of range");
    expect(payload.stacktrace).toBe(err.stack);
  });

  it("appends the cause chain", () => {
    const root = new Error("socket hang up");
    const err = new Error("payment failed", { cause: root });
    const payload = exceptionPayload(err)!;
    expect(payload.stacktrace).toContain("Caused by: Error: socket hang up");
    const plainCause = exceptionPayload(new Error("outer", { cause: { code: 42 } }))!;
    expect(plainCause.stacktrace).toContain('Caused by: {"code":42}');
    const stringCause = exceptionPayload(new Error("outer", { cause: "text" }))!;
    expect(stringCause.stacktrace).toContain("Caused by: text");
  });

  it("works without a stack and with custom names", () => {
    const err = new Error("no stack");
    Object.defineProperty(err, "stack", { value: undefined });
    err.name = "";
    const payload = exceptionPayload(err)!;
    expect(payload.type).toBe("Error");
    expect(payload.stacktrace).toBe(": no stack");
    const causeNoStack = new Error("inner");
    Object.defineProperty(causeNoStack, "stack", { value: undefined });
    expect(exceptionPayload(new Error("outer", { cause: causeNoStack }))!.stacktrace).toContain("Caused by: Error: inner");
  });

  it("describes thrown non-Errors", () => {
    expect(exceptionPayload("plain string")).toEqual({ type: "string", message: "plain string", stacktrace: "" });
    expect(exceptionPayload({ code: 7 })).toEqual({ type: "object", message: '{"code":7}', stacktrace: "" });
    expect(exceptionPayload(Symbol("x"))!.message).toBe("Symbol(x)");
  });

  it("clamps long fields and keeps the stack tail", () => {
    const err = new Error("m".repeat(LIMITS.excMessage + 5));
    err.stack = `${"s".repeat(LIMITS.stacktrace)}TAIL`;
    const payload = exceptionPayload(err)!;
    expect(payload.message).toHaveLength(LIMITS.excMessage);
    expect(payload.stacktrace).toHaveLength(LIMITS.stacktrace);
    expect(payload.stacktrace.endsWith("TAIL")).toBe(true);
  });
});

describe("buildLine", () => {
  it("builds a minimal line", () => {
    const line = buildLine("warning", "disk almost full");
    expect(Object.keys(line).sort()).toEqual(["level", "message", "timestamp"]);
    expect(line.level).toBe("warn");
  });

  it("maps camelCase fields to the wire and extra keys to attributes", () => {
    const line = buildLine("error", "order failed", {
      attributes: { orderId: 42 },
      customer: "acme",
      traceId: "t".repeat(100),
      spanId: "s".repeat(100),
      requestId: "req-1",
      timestamp: 0,
      error: new Error("bad"),
      service: "billing",
      environment: "staging",
      host: "web-2",
    });
    expect(line.attributes).toEqual({ orderId: 42, customer: "acme" });
    expect(line.trace_id).toHaveLength(LIMITS.traceId);
    expect(line.span_id).toHaveLength(LIMITS.spanId);
    expect(line.request_id).toBe("req-1");
    expect(line.timestamp).toBe("1970-01-01T00:00:00.000Z");
    expect(line.exception?.type).toBe("Error");
    expect(line).toMatchObject({ service: "billing", environment: "staging", host: "web-2" });
  });

  it("stringifies non-string messages and ids from plain JavaScript", () => {
    expect(buildLine("info", 42).message).toBe("42");
    expect(buildLine("info", { a: 1 }).message).toBe('{"a":1}');
    expect(buildLine("info", "x", { traceId: 123 as unknown as string }).trace_id).toBe("123");
  });

  it("never sends an empty message", () => {
    expect(buildLine("info", "").message).toBe("(empty message)");
    expect(buildLine("error", "", { error: new Error("boom") }).message).toBe("boom");
    expect(buildLine("error", "", { error: new Error("") }).message).toBe("Error");
  });

  it("truncates a huge message", () => {
    expect(buildLine("info", "z".repeat(LIMITS.message + 3)).message).toHaveLength(LIMITS.message);
  });

  it("clamp", () => {
    expect(clamp("abc", 3)).toBe("abc");
    expect(clamp("abcdef", 3)).toBe("abc");
  });
});

describe("IngestResult", () => {
  it("parses the API response", () => {
    expect(
      parseIngestResult({
        accepted: 2,
        rejected: [{ index: 1, reason: "bad timestamp" }, "junk", { index: "x" }],
        redactions: 3,
        error_groups: 1,
        event_ids: ["a", "b"],
      }),
    ).toEqual({
      accepted: 2,
      rejected: [
        { index: 1, reason: "bad timestamp" },
        { index: 0, reason: "" },
      ],
      redactions: 3,
      errorGroups: 1,
      eventIds: ["a", "b"],
    });
    expect(parseIngestResult(null)).toEqual({ accepted: 0, rejected: [], redactions: 0, errorGroups: 0, eventIds: [] });
    expect(parseIngestResult({})).toEqual({ accepted: 0, rejected: [], redactions: 0, errorGroups: 0, eventIds: [] });
  });

  it("merges parts and re-bases indexes", () => {
    const merged = mergeResults(
      [
        { accepted: 1, rejected: [{ index: 0, reason: "a" }], redactions: 1, errorGroups: 0, eventIds: ["1"] },
        { accepted: 2, rejected: [{ index: 1, reason: "b" }], redactions: 0, errorGroups: 2, eventIds: ["2", "3"] },
      ],
      [0, 5],
    );
    expect(merged).toEqual({
      accepted: 3,
      rejected: [
        { index: 0, reason: "a" },
        { index: 6, reason: "b" },
      ],
      redactions: 1,
      errorGroups: 2,
      eventIds: ["1", "2", "3"],
    });
    expect(mergeResults([{ accepted: 1, rejected: [{ index: 2, reason: "c" }], redactions: 0, errorGroups: 0, eventIds: [] }], []).rejected).toEqual([
      { index: 2, reason: "c" },
    ]);
  });
});
