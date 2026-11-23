import createClient from "openapi-fetch";

import { ApiError, parseApiError } from "./errors";
import type { paths } from "./schema";

/**
 * Where the browser sends API calls: this app's own proxy route, never the API directly.
 *
 * The LogMind API authenticates people only by `Authorization: Bearer <session>`.
 * The dashboard keeps that session token in an httpOnly cookie (`lm_session`) so page
 * JavaScript can never read it; the route handler at /api/proxy/[...path] reads the
 * cookie on the server and adds the Bearer header before forwarding to API_URL. So a
 * call to `/api/v1/logs` here travels as `/api/proxy/api/v1/logs`.
 */
export const PROXY_BASE = "/api/proxy";

/** Typed client for the dashboard, generated from docs/api/openapi.yaml (`pnpm gen:api`). */
export const api = createClient<paths>({ baseUrl: PROXY_BASE, credentials: "same-origin" });

interface FetchResult<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

/**
 * Await an openapi-fetch call and return its data, or throw an ApiError built from the
 * envelope. Network failures become status 0 so the UI can say "cannot reach the API".
 */
export async function unwrap<T>(call: Promise<FetchResult<T>>): Promise<T> {
  let result: FetchResult<T>;
  try {
    result = await call;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw parseApiError(0, null);
  }
  if (!result.response.ok) {
    throw parseApiError(result.response.status, result.error);
  }
  return result.data as T;
}

/** JSON request to one of this app's own route handlers (the session bridge). */
export async function appFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      credentials: "same-origin",
      headers: { "content-type": "application/json", ...(init.headers ?? {}) },
      cache: "no-store",
    });
  } catch {
    throw parseApiError(0, null);
  }
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) throw parseApiError(response.status, body);
  return body as T;
}
