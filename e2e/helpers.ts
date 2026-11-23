import { randomBytes } from "node:crypto";

import { type APIRequestContext, type Browser, type BrowserContext, expect, type Page, request } from "@playwright/test";

export const BASE = process.env.WEB_URL || "http://localhost:6010";
export const API_BASE = process.env.API_URL || "http://localhost:6030";
export const MAILPIT = process.env.MAILPIT_URL || "http://localhost:6025";
export const PASSWORD = process.env.LM_DEMO_PASSWORD || process.env.E2E_PASSWORD || "Demo-Owner-Pass-1";

/** The demo owner (make demo): Lumen Retail's owner. Every test creates its own project. */
export const USERS = {
  owner: "owner@lumen.example",
} as const;
export type Who = keyof typeof USERS;

/** Session files written by global-setup.ts, one per demo person. */
export const authFile = (who: Who) => `.auth/${who}.json`;

/** A per-run suffix so suites can run repeatedly against the same demo database. */
export const RUN = process.env.E2E_RUN || Date.now().toString(36).slice(-8);
let counter = 0;

/** A name unique to this run and call: e2e-<run>-<n>. */
export function unique(prefix = "e2e"): string {
  return `${prefix}-${RUN}-${++counter}`;
}

/** A W3C trace id (32 lowercase hex characters). */
export function newTraceId(): string {
  return randomBytes(16).toString("hex");
}

/** Fail the test on any console error the page reports. */
export function watchConsole(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

/** A browser context signed in as a demo person (their saved session). */
export async function contextAs(browser: Browser, who: Who = "owner"): Promise<BrowserContext> {
  return browser.newContext({ storageState: authFile(who), baseURL: BASE, viewport: { width: 1440, height: 900 } });
}

/** An API client signed in as a demo person (their saved session, cookie-based through the proxy). */
export async function apiAs(who: Who = "owner"): Promise<APIRequestContext> {
  return request.newContext({ baseURL: BASE, storageState: authFile(who) });
}

/** JSON from the dashboard's own proxy (/api/proxy/api/v1/...), asserting success. */
export async function call<T = unknown>(ctx: APIRequestContext, method: string, path: string, data?: unknown): Promise<T> {
  const resp = await ctx.fetch(`/api/proxy${path}`, { method, data });
  expect(resp.status(), `${method} ${path}: ${await resp.text()}`).toBeLessThan(300);
  return (resp.status() === 204 ? null : await resp.json()) as T;
}

/** Poll until ``fn`` returns something truthy. A transient exception (a navigation racing
 * a reload, a dropped connection) is swallowed and retried rather than failing the whole
 * wait immediately, since the condition it is waiting for may still become true. */
export async function eventually<T>(fn: () => Promise<T | null | undefined | false>, timeoutMs = 60_000): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  let last: unknown = null;
  while (Date.now() < deadline) {
    try {
      last = await fn();
      if (last) return last as T;
    } catch (e) {
      last = e instanceof Error ? e.message : e;
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`condition never held (last: ${JSON.stringify(last)?.slice(0, 200)})`);
}

export interface TestProject {
  id: string;
  name: string;
}

export interface TestKey {
  key: string;
  project_id: string;
}

/**
 * A fresh project and API key for one test, through the dashboard API (the session cookie),
 * as a developer would from Settings before wiring up an SDK. Each test gets its own project
 * so its logs, errors and alerts never collide with another test's or the demo data.
 */
export async function createProjectAndKey(admin: APIRequestContext): Promise<{ project: TestProject; key: string }> {
  const name = unique("e2e-project");
  const project = await call<TestProject>(admin, "POST", "/api/v1/projects", { name, description: "Created by an end-to-end test.", retention_days: 7 });
  const created = await call<{ key: string }>(admin, "POST", "/api/v1/keys", { project_id: project.id, name: `${name}-key` });
  return { project, key: created.key };
}

/** An HTTP client authenticated as a project (what the SDKs send): `Authorization: Bearer lmk_...`. */
export async function projectClient(apiKey: string): Promise<APIRequestContext> {
  return request.newContext({ baseURL: API_BASE, extraHTTPHeaders: { authorization: `Bearer ${apiKey}`, "x-logmind-sdk": "e2e" } });
}

export interface LogSpec {
  message: string;
  level?: string;
  service?: string;
  environment?: string;
  timestamp?: string;
  trace_id?: string;
  request_id?: string;
  attributes?: Record<string, unknown>;
  exception?: { type: string; message?: string; stacktrace?: string };
}

/** POST /api/v1/logs/batch with a project key, the call both SDKs make. */
export async function sendLogs(client: APIRequestContext, logs: LogSpec[]): Promise<{ accepted: number; event_ids: string[]; redactions: number }> {
  const resp = await client.post("/api/v1/logs/batch", { data: { logs } });
  expect(resp.status(), `ingest: ${await resp.text()}`).toBe(202);
  return resp.json();
}

/** Make the dashboard scope to a project (the persisted UI preference). */
export async function scopeTo(page: Page, projectId: string): Promise<void> {
  await page.addInitScript((id) => {
    window.localStorage.setItem("logmind.ui", JSON.stringify({ state: { sidebarCollapsed: false, projectId: id }, version: 1 }));
  }, projectId);
}

/** An incident with a real cause chain, timestamps relative to now. */
export function incident(service = "checkout"): LogSpec[] {
  const now = Date.now();
  const at = (minAgo: number) => new Date(now - minAgo * 60_000).toISOString();
  const lines: LogSpec[] = [];
  for (let i = 0; i < 60; i++) lines.push({ message: `GET /cart/${i} 200 in ${20 + (i % 9)}ms`, service: "gateway", timestamp: at(45 - i * 0.5) });
  lines.push({ message: "deploy started: payments version v9.1.0 rolling out", service: "payments", timestamp: at(22) });
  for (let k = 0; k < 15; k++) lines.push({ message: `db connection pool exhausted (max=20, waiting=${k + 3})`, level: "warn", service: "payments", timestamp: at(18 - k * 0.1) });
  for (let k = 0; k < 20; k++)
    lines.push({
      message: `order o-${k} failed: payment gateway timeout`,
      level: "error",
      service,
      timestamp: at(15 - k * 0.3),
      request_id: `req-${k}`,
      exception: {
        type: "PaymentGatewayTimeout",
        message: "upstream payments timed out after 5000ms",
        stacktrace: `Traceback (most recent call last):\n  File "/app/checkout/handlers.py", line ${40 + (k % 5)}, in place_order\n    payments.charge(order)\n  File "/app/checkout/clients/payments.py", line 112, in charge\n    raise PaymentGatewayTimeout()\nPaymentGatewayTimeout: upstream payments timed out after 5000ms`,
      },
    });
  return lines;
}
