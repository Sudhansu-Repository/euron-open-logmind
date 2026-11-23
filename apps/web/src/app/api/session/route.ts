import { cookies } from "next/headers";
import { type NextRequest } from "next/server";

import {
  apiBaseUrl,
  cookieSecure,
  isSameOrigin,
  SESSION_COOKIE,
  sessionCookieOptions,
  unreachableBody,
} from "@/lib/session";

/**
 * The session bridge (diverges from the AgentGuard reference on purpose).
 *
 * AgentGuard's API sets its own session cookie, which the browser then sends straight to
 * the API through same-origin rewrites. LogMind's API sets no cookie: /auth/login
 * and /auth/signup return `{session_token, user}` in the body, and every later call must
 * carry `Authorization: Bearer <token>`. So this handler does the sign-in on the server:
 *
 *   POST   {action: "login", email, password}
 *          {action: "signup", org_name, name, email, password}
 *          calls the API, stores session_token in the httpOnly `lm_session` cookie and
 *          answers with `{user}` only. The token is never in a response the page reads.
 *   DELETE clears the cookie (sign out).
 *
 * Signing in here instead of accepting a token from the page also closes login CSRF: no
 * other site can plant its own session token in this cookie.
 */
export const dynamic = "force-dynamic";

const NO_STORE = { "cache-control": "no-store" };

function errorJson(status: number, code: string, message: string) {
  return Response.json(
    { error: { code, type: "invalid_request_error", message, details: {} } },
    { status, headers: NO_STORE }
  );
}

export async function POST(req: NextRequest) {
  if (!isSameOrigin("POST", req.headers.get("origin"), req.headers.get("host"))) {
    return errorJson(403, "cross_site_request", "Sign in from the LogMind dashboard itself.");
  }
  let body: Record<string, unknown>;
  try {
    body = (await req.json()) as Record<string, unknown>;
  } catch {
    return errorJson(400, "bad_request", "Send the sign-in form as JSON.");
  }
  const { action, ...fields } = body;
  if (action !== "login" && action !== "signup")
    return errorJson(400, "bad_request", "Unknown session action.");

  let upstream: Response;
  try {
    upstream = await fetch(`${apiBaseUrl()}/api/v1/auth/${action}`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        accept: "application/json",
        ...(req.headers.get("x-forwarded-for")
          ? { "x-forwarded-for": req.headers.get("x-forwarded-for") as string }
          : {}),
      },
      body: JSON.stringify(fields),
      cache: "no-store",
    });
  } catch {
    return Response.json(unreachableBody(), { status: 503, headers: NO_STORE });
  }

  let data: unknown = null;
  try {
    data = await upstream.json();
  } catch {
    data = null;
  }
  if (!upstream.ok) return Response.json(data, { status: upstream.status, headers: NO_STORE });

  const session = data as { session_token?: unknown; user?: unknown } | null;
  if (!session || typeof session.session_token !== "string" || !session.user) {
    return errorJson(
      502,
      "bad_gateway",
      "The API answered sign-in without a session. Check that API_URL points at the LogMind API."
    );
  }
  const store = await cookies();
  store.set(
    SESSION_COOKIE,
    session.session_token,
    sessionCookieOptions(cookieSecure(req.nextUrl.protocol, req.headers.get("x-forwarded-proto")))
  );
  return Response.json({ user: session.user }, { status: upstream.status, headers: NO_STORE });
}

export async function DELETE(req: NextRequest) {
  if (!isSameOrigin("DELETE", req.headers.get("origin"), req.headers.get("host"))) {
    return errorJson(403, "cross_site_request", "Sign out from the LogMind dashboard itself.");
  }
  const store = await cookies();
  store.delete(SESSION_COOKIE);
  return Response.json({ ok: true }, { headers: NO_STORE });
}
