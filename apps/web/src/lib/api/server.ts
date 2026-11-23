import { cookies } from "next/headers";

import { apiBaseUrl, SESSION_COOKIE } from "@/lib/session";

/**
 * Server-side access to the API for route handlers and server components. Reads the
 * httpOnly session cookie and attaches it as `Authorization: Bearer`, the only way the
 * API accepts a person's session. Never import this from a client component.
 */
export async function sessionToken(): Promise<string | null> {
  const store = await cookies();
  return store.get(SESSION_COOKIE)?.value || null;
}

export async function serverFetch(
  path: string,
  init: RequestInit & { token?: string | null } = {}
): Promise<Response> {
  const token = init.token === undefined ? await sessionToken() : init.token;
  const headers = new Headers(init.headers);
  headers.set("accept", "application/json");
  if (token) headers.set("authorization", `Bearer ${token}`);
  return fetch(`${apiBaseUrl()}${path}`, {
    ...init,
    headers,
    cache: "no-store",
    redirect: "manual",
  });
}
