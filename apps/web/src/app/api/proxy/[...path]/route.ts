import { cookies } from "next/headers";
import { type NextRequest } from "next/server";

import {
  apiBaseUrl,
  forwardHeaders,
  isSameOrigin,
  SESSION_COOKIE,
  unreachableBody,
  upstreamPath,
} from "@/lib/session";

/**
 * The authenticated API proxy: the key architectural difference from the AgentGuard
 * reference.
 *
 * Every TanStack Query hook calls `/api/proxy/api/v1/...` on this origin. This handler
 * reads the httpOnly `lm_session` cookie on the server, adds `Authorization: Bearer
 * <token>` (the only credential the LogMind API accepts for people,
 * auth/dependencies.py `bearer()`), forwards the request to `${API_URL}/api/v1/...`, and
 * streams the answer back unchanged (status, JSON body, error envelope). next.config.ts
 * rewrites cannot do this because a rewrite cannot add a header, which is why /api/v1 is
 * deliberately NOT rewritten there.
 *
 * When the API answers 401 the session is over (expired, user disabled, session version
 * bumped), so the cookie is cleared here too and the middleware sends the next page load
 * to /login.
 */
export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ path: string[] }> };

async function handle(req: NextRequest, ctx: Ctx): Promise<Response> {
  const { path } = await ctx.params;
  const target = upstreamPath(path ?? []);
  if (!target) {
    return Response.json(
      {
        error: {
          code: "not_found",
          type: "invalid_request_error",
          message: "Only /api/v1 routes are proxied.",
          details: {},
        },
      },
      { status: 404 }
    );
  }
  if (!isSameOrigin(req.method, req.headers.get("origin"), req.headers.get("host"))) {
    return Response.json(
      {
        error: {
          code: "cross_site_request",
          type: "invalid_request_error",
          message: "Use the LogMind dashboard itself.",
          details: {},
        },
      },
      { status: 403 }
    );
  }
  const store = await cookies();
  const token = store.get(SESSION_COOKIE)?.value || null;
  const hasBody = req.method !== "GET" && req.method !== "HEAD";

  let upstream: Response;
  try {
    upstream = await fetch(`${apiBaseUrl()}${target}${req.nextUrl.search}`, {
      method: req.method,
      headers: forwardHeaders(req.headers, token),
      body: hasBody ? await req.arrayBuffer() : undefined,
      cache: "no-store",
      redirect: "manual",
    });
  } catch {
    return Response.json(unreachableBody(), {
      status: 503,
      headers: { "cache-control": "no-store" },
    });
  }

  const headers = new Headers({ "cache-control": "no-store" });
  const type = upstream.headers.get("content-type");
  if (type) headers.set("content-type", type);
  const rid = upstream.headers.get("x-request-id");
  if (rid) headers.set("x-request-id", rid);
  const retry = upstream.headers.get("retry-after");
  if (retry) headers.set("retry-after", retry);

  if (upstream.status === 401 && token) store.delete(SESSION_COOKIE);

  // 204 and 304 carry no body; passing one would throw.
  const body = upstream.status === 204 || upstream.status === 304 ? null : upstream.body;
  return new Response(body, { status: upstream.status, headers });
}

export const GET = handle;
export const POST = handle;
export const PATCH = handle;
export const PUT = handle;
export const DELETE = handle;
