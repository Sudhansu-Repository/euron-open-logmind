/**
 * The session bridge between the browser and the LogMind API, as pure helpers the
 * route handlers, the middleware and the tests share.
 *
 * Why a bridge: the API issues the session token in the JSON body of /auth/login and
 * /auth/signup and reads it only from `Authorization: Bearer` (it sets no cookie). The
 * dashboard keeps the token in its own httpOnly cookie, `lm_session`, set by this app's
 * /api/session route handler, so page JavaScript never holds it. Every authenticated API
 * call goes through /api/proxy, which reads the cookie server side and adds the header.
 * The one narrow exception is /api/session/ws-token, which hands the same token back for
 * the single purpose of opening the live WebSocket (the API reads it from `?token=`).
 *
 * Nothing here decodes the token: the frontend has no secret to verify it with, and the
 * API checks it on every call.
 */

/** Name of the dashboard's httpOnly session cookie. */
export const SESSION_COOKIE = "lm_session";

/**
 * Cookie lifetime. Matches the API's default `session_ttl_hours` (12, core/config.py); the
 * API rejects an expired token regardless, and the proxy clears the cookie when it does.
 */
export const SESSION_MAX_AGE_S = 12 * 60 * 60;

export interface SessionCookieOptions {
  httpOnly: true;
  secure: boolean;
  sameSite: "lax";
  path: "/";
  maxAge: number;
}

export function sessionCookieOptions(
  secure: boolean,
  maxAge = SESSION_MAX_AGE_S
): SessionCookieOptions {
  return { httpOnly: true, secure, sameSite: "lax", path: "/", maxAge };
}

/**
 * Whether to mark the cookie Secure. `COOKIE_SECURE=true|false` decides when set (the same
 * switch the API's compose env uses); otherwise the request decides: HTTPS directly, or
 * behind a load balancer that says so in X-Forwarded-Proto. A Secure cookie on a plain HTTP
 * origin other than localhost is dropped by browsers, which would make sign-in silently
 * fail on an HTTP-only deployment.
 */
export function cookieSecure(
  protocol: string,
  forwardedProto: string | null,
  env: string | undefined = process.env.COOKIE_SECURE
): boolean {
  if (env === "true") return true;
  if (env === "false") return false;
  const proto = (forwardedProto?.split(",")[0]?.trim() || protocol.replace(/:$/, "")).toLowerCase();
  return proto === "https";
}

/** The API's base URL as this server reaches it, without a trailing slash. */
export function apiBaseUrl(env: Record<string, string | undefined> = process.env): string {
  return (env.API_URL || env.API_INTERNAL_URL || "http://localhost:6030").replace(/\/+$/, "");
}

/**
 * Only the versioned REST API may be proxied: /api/proxy/api/v1/... maps to
 * {API_URL}/api/v1/.... Anything else (path traversal, other prefixes) is refused, so the
 * proxy can never be pointed at another route of the API host with the session attached.
 */
export function upstreamPath(segments: readonly string[]): string | null {
  if (segments.length < 3 || segments[0] !== "api" || segments[1] !== "v1") return null;
  for (const s of segments) {
    if (!s || s === "." || s === ".." || s.includes("/") || s.includes("\\")) return null;
  }
  return `/${segments.map((s) => encodeURIComponent(s)).join("/")}`;
}

/**
 * Defence in depth against cross-site requests that change state. The session cookie is
 * SameSite=Lax, so browsers already omit it from cross-site POSTs; this also refuses a
 * mutating request whose Origin names another site.
 */
export function isSameOrigin(method: string, origin: string | null, host: string | null): boolean {
  if (method === "GET" || method === "HEAD" || method === "OPTIONS") return true;
  if (!origin) return true;
  if (!host) return false;
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

/** Request headers worth forwarding to the API (content type, client IP for the audit log). */
export function forwardHeaders(incoming: Headers, token: string | null): Headers {
  const out = new Headers();
  const type = incoming.get("content-type");
  if (type) out.set("content-type", type);
  out.set("accept", "application/json");
  const xff = incoming.get("x-forwarded-for");
  if (xff) out.set("x-forwarded-for", xff);
  const rid = incoming.get("x-request-id");
  if (rid) out.set("x-request-id", rid);
  if (token) out.set("authorization", `Bearer ${token}`);
  return out;
}

/** The envelope the bridge answers with when the API cannot be reached. */
export function unreachableBody(): {
  error: { code: string; type: string; message: string; details: Record<string, unknown> };
} {
  return {
    error: {
      code: "api_unreachable",
      type: "api_error",
      message:
        "The dashboard server cannot reach the LogMind API. Check that the API is running and that API_URL points at it, then retry.",
      details: {},
    },
  };
}
