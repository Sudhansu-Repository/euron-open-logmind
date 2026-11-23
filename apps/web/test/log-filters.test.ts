import { describe, expect, it } from "vitest";

import {
  activeCount,
  apiQuery,
  EMPTY_FILTERS,
  filtersFromParams,
  filtersToParams,
  toggle,
} from "@/features/logs/filters";

describe("log filters", () => {
  it("round-trips through the URL", () => {
    const f = {
      ...EMPTY_FILTERS,
      q: "timeout",
      levels: ["error", "fatal"],
      services: ["checkout"],
      environments: ["production"],
      range: "24h" as const,
      traceId: "abc",
      requestId: "r1",
      errorGroupId: "g1",
    };
    const p = filtersToParams(f);
    expect(filtersFromParams(p)).toEqual(f);
    expect(filtersToParams(EMPTY_FILTERS).toString()).toBe("");
  });

  it("falls back to one hour for an unknown range", () => {
    expect(filtersFromParams(new URLSearchParams("range=1y")).range).toBe("1h");
  });

  it("builds the API query with a resolved window", () => {
    const now = Date.UTC(2026, 0, 1, 12);
    const q = apiQuery("p1", { ...EMPTY_FILTERS, q: "x", levels: ["error"], range: "15m" }, now);
    expect(q).toMatchObject({
      project_id: "p1",
      q: "x",
      level: ["error"],
      service: undefined,
      end: "2026-01-01T12:00:00.000Z",
      start: "2026-01-01T11:45:00.000Z",
    });
  });

  it("toggles and counts", () => {
    expect(toggle(["a"], "b")).toEqual(["a", "b"]);
    expect(toggle(["a", "b"], "a")).toEqual(["b"]);
    expect(activeCount({ ...EMPTY_FILTERS, q: "x", levels: ["error", "warn"], traceId: "t" })).toBe(
      4
    );
    expect(activeCount(EMPTY_FILTERS)).toBe(0);
  });
});
