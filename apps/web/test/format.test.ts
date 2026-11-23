import { describe, expect, it } from "vitest";

import {
  formatBytes,
  formatCost,
  formatCurrency,
  formatDate,
  formatDateTime,
  formatDuration,
  formatMs,
  formatNumber,
  formatPercent,
  formatRelative,
  formatTokenCount,
  initials,
  plural,
  shortId,
  UNPRICED_LABEL,
} from "@/lib/format";

describe("formatNumber", () => {
  it("groups thousands and rounds", () => {
    expect(formatNumber(14923)).toBe("14,923");
    expect(formatNumber(12.6)).toBe("13");
  });
  it("renders missing values as n/a", () => {
    expect(formatNumber(null)).toBe("n/a");
    expect(formatNumber(undefined)).toBe("n/a");
    expect(formatNumber(Number.NaN)).toBe("n/a");
  });
});

describe("formatBytes", () => {
  it("picks a unit", () => {
    expect(formatBytes(812)).toBe("812 B");
    expect(formatBytes(4300)).toBe("4.2 KB");
    expect(formatBytes(12 * 1024 * 1024)).toBe("12 MB");
    expect(formatBytes(null)).toBe("n/a");
  });
});

describe("formatTokenCount", () => {
  it("is exact below a thousand", () => {
    expect(formatTokenCount(0)).toBe("0");
    expect(formatTokenCount(812)).toBe("812");
  });
  it("abbreviates thousands, millions and billions", () => {
    expect(formatTokenCount(4200)).toBe("4.2k");
    expect(formatTokenCount(1000)).toBe("1k");
    expect(formatTokenCount(250_000)).toBe("250k");
    expect(formatTokenCount(1_340_000)).toBe("1.3M");
    expect(formatTokenCount(2_000_000_000)).toBe("2B");
  });
  it("handles missing values", () => {
    expect(formatTokenCount(undefined)).toBe("n/a");
    expect(formatTokenCount(Number.POSITIVE_INFINITY)).toBe("n/a");
  });
});

describe("formatCurrency", () => {
  it("uses two decimals for a dollar and up", () => {
    expect(formatCurrency(12.4)).toBe("$12.40");
    expect(formatCurrency(1234.5)).toBe("$1,234.50");
  });
  it("keeps the significant digits of fractions of a cent", () => {
    expect(formatCurrency(0.0123)).toBe("$0.0123");
    expect(formatCurrency(0.5)).toBe("$0.50");
    expect(formatCurrency(0.000042)).toBe("$0.000042");
  });
  it("renders zero as $0.00 and missing as n/a", () => {
    expect(formatCurrency(0)).toBe("$0.00");
    expect(formatCurrency(null)).toBe("n/a");
  });
});

describe("formatCost", () => {
  it("never shows an unpriced amount as free", () => {
    expect(formatCost(0, { unpriced: true })).toBe(UNPRICED_LABEL);
    expect(formatCost(null, { unpriced: true })).toBe("Unpriced");
  });
  it("keeps the priced part of a partly unpriced total", () => {
    expect(formatCost(0.42, { unpriced: true })).toBe("$0.42 + unpriced");
    expect(formatCost(1.5, { partial: true })).toBe("$1.50 + unpriced");
  });
  it("is a plain currency when everything is priced", () => {
    expect(formatCost(0)).toBe("$0.00");
    expect(formatCost(3.2)).toBe("$3.20");
  });
});

describe("dates", () => {
  it("formats valid dates and rejects invalid ones", () => {
    expect(formatDateTime("2026-05-01T10:30:00Z")).toMatch(/May 1/);
    expect(formatDate("2026-05-01T10:30:00Z")).toMatch(/2026/);
    expect(formatDateTime("not a date")).toBe("n/a");
    expect(formatDate(null)).toBe("n/a");
  });
  it("formats relative times", () => {
    const now = new Date("2026-05-01T12:00:00Z");
    expect(formatRelative("2026-05-01T11:59:50Z", now)).toBe("just now");
    expect(formatRelative("2026-05-01T11:55:00Z", now)).toBe("5m ago");
    expect(formatRelative("2026-05-01T09:00:00Z", now)).toBe("3h ago");
    expect(formatRelative("2026-04-29T12:00:00Z", now)).toBe("2d ago");
    expect(formatRelative("2026-05-01T13:00:00Z", now)).toBe("in 1h");
    expect(formatRelative(null, now)).toBe("Never");
  });
});

describe("durations", () => {
  it("formats seconds", () => {
    expect(formatDuration(45)).toBe("45s");
    expect(formatDuration(240)).toBe("4m");
    expect(formatDuration(4800)).toBe("1h 20m");
    expect(formatDuration(183_600)).toBe("2d 3h");
    expect(formatDuration(null)).toBe("n/a");
  });
  it("formats milliseconds", () => {
    expect(formatMs(0.42)).toBe("0.4 ms");
    expect(formatMs(320)).toBe("320 ms");
    expect(formatMs(1400)).toBe("1.4 s");
    expect(formatMs(125_000)).toBe("2m 5s");
    expect(formatMs(120_000)).toBe("2m");
    expect(formatMs(-1)).toBe("n/a");
    expect(formatMs(undefined)).toBe("n/a");
  });
});

describe("small helpers", () => {
  it("percent", () => {
    expect(formatPercent(0.0423)).toBe("4.2%");
    expect(formatPercent(0.5)).toBe("50%");
    expect(formatPercent(0)).toBe("0%");
    expect(formatPercent(0.0001)).toBe("<0.1%");
    expect(formatPercent(null)).toBe("n/a");
  });
  it("initials, plural, shortId", () => {
    expect(initials("Avery Chen")).toBe("AC");
    expect(initials("ada")).toBe("A");
    expect(initials("")).toBe("?");
    expect(plural(1, "line")).toBe("1 line");
    expect(plural(3, "line")).toBe("3 lines");
    expect(shortId("0123456789abcdef0123")).toBe("01234567...0123");
    expect(shortId("short")).toBe("short");
  });
});

describe("no banned dashes in output", () => {
  it("never emits an em or en dash", () => {
    const outputs = [
      formatMs(125_000),
      formatDuration(4800),
      formatCost(0.42, { unpriced: true }),
      formatRelative("2026-01-01T00:00:00Z"),
    ];
    for (const o of outputs) expect(o).not.toMatch(/[\u2013\u2014]/);
  });
});
