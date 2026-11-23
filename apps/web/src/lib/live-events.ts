/**
 * The live log stream (`/api/v1/logs/live`, logs/router.py) sends `ready` on connect,
 * `ping` keepalives about every 25 s, and `{"type": "logs", "items": [...]}` with the lines
 * a batch just stored (already redacted, already filtered by the level, service and
 * keyword the socket was opened with). This module is the pure part: parse a frame, keep
 * a bounded buffer, how long to wait before reconnecting, and when to give up.
 */

export interface LiveLine {
  event_id: string;
  timestamp: string;
  level: string;
  service: string;
  environment: string;
  message: string;
  trace_id: string;
  request_id: string;
  fingerprint: string;
}

export type LiveEvent = { type: "ready" } | { type: "ping" } | { type: "logs"; items: LiveLine[] };

function asLine(v: unknown): LiveLine | null {
  if (typeof v !== "object" || v === null) return null;
  const r = v as Record<string, unknown>;
  if (
    typeof r.event_id !== "string" ||
    typeof r.message !== "string" ||
    typeof r.timestamp !== "string"
  )
    return null;
  const s = (k: string) => (typeof r[k] === "string" ? (r[k] as string) : "");
  return {
    event_id: r.event_id,
    timestamp: r.timestamp,
    message: r.message,
    level: s("level") || "info",
    service: s("service"),
    environment: s("environment"),
    trace_id: s("trace_id"),
    request_id: s("request_id"),
    fingerprint: s("fingerprint"),
  };
}

/** Parse one frame; anything malformed is ignored. */
export function parseLiveEvent(raw: unknown): LiveEvent | null {
  if (typeof raw !== "string" || raw.length > 2_000_000) return null;
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) return null;
  const ev = data as Record<string, unknown>;
  if (ev.type === "ready" || ev.type === "ping") return { type: ev.type };
  if (ev.type === "logs" && Array.isArray(ev.items)) {
    return { type: "logs", items: ev.items.map(asLine).filter((l): l is LiveLine => l !== null) };
  }
  return null;
}

/** Newest first, at most `max` lines, no duplicates. */
export function appendLines(buffer: LiveLine[], incoming: LiveLine[], max = 500): LiveLine[] {
  const seen = new Set(buffer.map((l) => l.event_id));
  const fresh = incoming
    .filter((l) => !seen.has(l.event_id))
    .sort((a, b) => b.timestamp.localeCompare(a.timestamp));
  return [...fresh, ...buffer].slice(0, max);
}

/** Exponential backoff with full jitter, capped: 1 s, 2 s, 4 s ... up to 30 s. */
export function reconnectDelay(attempt: number, random: () => number = Math.random): number {
  const base = Math.min(30_000, 1000 * 2 ** Math.max(0, attempt));
  return Math.round(base / 2 + (random() * base) / 2);
}

export type SocketStatus = "idle" | "connecting" | "open" | "closed" | "refused";

/**
 * The WebSocket URL. Sockets go through this origin: next.config.ts rewrites `/ws/logs`
 * to the API's `/api/v1/logs/live`. The session token rides in the query string because
 * the API reads it from `?token=` (browsers cannot set headers on a WebSocket handshake).
 */
export function socketUrl(
  location: { protocol: string; host: string },
  token: string,
  query: { projectId: string; levels?: string[]; services?: string[]; q?: string }
): string {
  const base = `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws/logs`;
  const params = new URLSearchParams({ token, project_id: query.projectId });
  for (const l of query.levels ?? []) params.append("level", l);
  for (const s of query.services ?? []) params.append("service", s);
  if (query.q) params.set("q", query.q);
  return `${base}?${params.toString()}`;
}
