/**
 * The Log Explorer's filters, round-tripped through the URL so a search can be shared as a
 * link. Pure functions, unit tested.
 */

export const RANGES = {
  "15m": 15 * 60_000,
  "1h": 3_600_000,
  "6h": 6 * 3_600_000,
  "24h": 24 * 3_600_000,
  "7d": 7 * 24 * 3_600_000,
} as const;
export type RangeKey = keyof typeof RANGES;

export interface LogFilters {
  q: string;
  levels: string[];
  services: string[];
  environments: string[];
  range: RangeKey;
  traceId: string;
  requestId: string;
  errorGroupId: string;
}

export const EMPTY_FILTERS: LogFilters = {
  q: "",
  levels: [],
  services: [],
  environments: [],
  range: "1h",
  traceId: "",
  requestId: "",
  errorGroupId: "",
};

export function filtersFromParams(params: URLSearchParams): LogFilters {
  const range = params.get("range") ?? "1h";
  return {
    q: params.get("q") ?? "",
    levels: params.getAll("level"),
    services: params.getAll("service"),
    environments: params.getAll("environment"),
    range: (range in RANGES ? range : "1h") as RangeKey,
    traceId: params.get("trace_id") ?? "",
    requestId: params.get("request_id") ?? "",
    errorGroupId: params.get("error_group_id") ?? "",
  };
}

export function filtersToParams(f: LogFilters): URLSearchParams {
  const p = new URLSearchParams();
  if (f.q) p.set("q", f.q);
  for (const l of f.levels) p.append("level", l);
  for (const s of f.services) p.append("service", s);
  for (const e of f.environments) p.append("environment", e);
  if (f.range !== "1h") p.set("range", f.range);
  if (f.traceId) p.set("trace_id", f.traceId);
  if (f.requestId) p.set("request_id", f.requestId);
  if (f.errorGroupId) p.set("error_group_id", f.errorGroupId);
  return p;
}

/** The API query for a filter set, with the time window resolved against `now`. */
export function apiQuery(projectId: string, f: LogFilters, now: number) {
  return {
    project_id: projectId,
    q: f.q || undefined,
    level: f.levels.length ? f.levels : undefined,
    service: f.services.length ? f.services : undefined,
    environment: f.environments.length ? f.environments : undefined,
    start: new Date(now - RANGES[f.range]).toISOString(),
    end: new Date(now).toISOString(),
    trace_id: f.traceId || undefined,
    request_id: f.requestId || undefined,
    error_group_id: f.errorGroupId || undefined,
  };
}

export function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

export function activeCount(f: LogFilters): number {
  return (
    (f.q ? 1 : 0) +
    f.levels.length +
    f.services.length +
    f.environments.length +
    (f.traceId ? 1 : 0) +
    (f.requestId ? 1 : 0) +
    (f.errorGroupId ? 1 : 0)
  );
}
