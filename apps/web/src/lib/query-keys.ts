/**
 * Query keys in one place, so invalidation after a mutation names exactly what it touched.
 * Keys are hierarchical: invalidating `qk.errors` refreshes every error list and detail.
 */
export const qk = {
  me: ["auth", "me"] as const,

  org: ["org"] as const,
  users: ["users"] as const,
  audit: ["audit"] as const,
  auditList: (action: string) => ["audit", "list", action] as const,
  ready: ["health", "ready"] as const,

  projects: ["projects"] as const,
  projectList: (includeArchived: boolean) => ["projects", "list", includeArchived] as const,
  project: (id: string) => ["projects", "detail", id] as const,
  environments: (projectId: string) => ["projects", "environments", projectId] as const,

  keys: ["keys"] as const,
  keyList: (projectId: string, includeRevoked: boolean) =>
    ["keys", "list", projectId, includeRevoked] as const,

  logs: ["logs"] as const,
  logSearch: (filters: object) => ["logs", "search", filters] as const,
  logHistogram: (filters: object) => ["logs", "histogram", filters] as const,
  logFacets: (projectId: string, window: string) => ["logs", "facets", projectId, window] as const,
  logLine: (projectId: string, id: string) => ["logs", "line", projectId, id] as const,
  logContext: (projectId: string, id: string) => ["logs", "context", projectId, id] as const,

  errors: ["errors"] as const,
  errorList: (filters: object) => ["errors", "list", filters] as const,
  error: (projectId: string, id: string) => ["errors", "detail", projectId, id] as const,

  services: ["services"] as const,
  serviceList: (projectId: string, hours: number) =>
    ["services", "list", projectId, hours] as const,

  overview: (projectId: string, hours: number) => ["overview", projectId, hours] as const,
  usage: (projectId: string, days: number) => ["usage", projectId, days] as const,

  investigations: ["investigations"] as const,
  investigationList: (projectId: string, groupId: string) =>
    ["investigations", "list", projectId, groupId] as const,
  investigation: (id: string) => ["investigations", "detail", id] as const,
  verify: (id: string) => ["investigations", "verify", id] as const,

  providers: ["providers"] as const,

  alerts: ["alerts"] as const,
  alertList: (projectId: string) => ["alerts", "list", projectId] as const,
  alert: (id: string) => ["alerts", "detail", id] as const,
  alertHistory: (projectId: string, ruleId: string) =>
    ["alerts", "history", projectId, ruleId] as const,
};

/** staleTime per kind of data, chosen deliberately. */
export const STALE = {
  live: 5_000,
  list: 15_000,
  config: 30_000,
  /** A completed investigation never changes except by a follow-up the user sends. */
  report: 60_000,
  static: 5 * 60_000,
} as const;
