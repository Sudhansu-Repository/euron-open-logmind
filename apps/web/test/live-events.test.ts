import { describe, expect, it } from "vitest";

import {
  appendLines,
  parseLiveEvent,
  reconnectDelay,
  socketUrl,
  type LiveLine,
} from "@/lib/live-events";

const line = (id: string, ts: string, extra: Partial<LiveLine> = {}): LiveLine => ({
  event_id: id,
  timestamp: ts,
  level: "info",
  service: "checkout",
  environment: "production",
  message: `m ${id}`,
  trace_id: "",
  request_id: "",
  fingerprint: "",
  ...extra,
});

describe("parseLiveEvent", () => {
  it("reads control frames and log batches", () => {
    expect(parseLiveEvent('{"type":"ready"}')).toEqual({ type: "ready" });
    expect(parseLiveEvent('{"type":"ping"}')).toEqual({ type: "ping" });
    const ev = parseLiveEvent(
      JSON.stringify({
        type: "logs",
        items: [
          { event_id: "a", timestamp: "2026-01-01T00:00:00Z", message: "hi", level: "error" },
          { bad: true },
        ],
      })
    );
    expect(ev?.type).toBe("logs");
    if (ev?.type === "logs") {
      expect(ev.items).toHaveLength(1);
      expect(ev.items[0]).toMatchObject({ event_id: "a", level: "error", service: "" });
    }
  });

  it("ignores anything malformed", () => {
    for (const raw of [42, "not json", "[]", '{"type":1}', '{"type":"other"}', '{"type":"logs"}'])
      expect(parseLiveEvent(raw)).toBeNull();
  });
});

describe("appendLines", () => {
  it("keeps newest first, drops duplicates and caps the buffer", () => {
    const buf = [line("b", "2026-01-01T00:00:02Z"), line("a", "2026-01-01T00:00:01Z")];
    const out = appendLines(
      buf,
      [
        line("c", "2026-01-01T00:00:03Z"),
        line("b", "2026-01-01T00:00:02Z"),
        line("d", "2026-01-01T00:00:04Z"),
      ],
      3
    );
    expect(out.map((l) => l.event_id)).toEqual(["d", "c", "b"]);
  });
});

describe("socket helpers", () => {
  it("backs off with jitter up to 30 s", () => {
    expect(reconnectDelay(0, () => 0)).toBe(500);
    expect(reconnectDelay(0, () => 1)).toBe(1000);
    expect(reconnectDelay(10, () => 1)).toBe(30_000);
  });

  it("builds the same-origin URL with the filters", () => {
    const url = socketUrl({ protocol: "https:", host: "logs.example.com" }, "t k", {
      projectId: "p1",
      levels: ["error", "warn"],
      services: ["api"],
      q: "boom",
    });
    expect(url).toBe(
      "wss://logs.example.com/ws/logs?token=t+k&project_id=p1&level=error&level=warn&service=api&q=boom"
    );
    expect(socketUrl({ protocol: "http:", host: "localhost:6010" }, "x", { projectId: "p" })).toBe(
      "ws://localhost:6010/ws/logs?token=x&project_id=p"
    );
  });
});
