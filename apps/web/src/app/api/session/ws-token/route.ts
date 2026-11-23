import { type NextRequest } from "next/server";

import { sessionToken } from "@/lib/api/server";

/**
 * The one place the session token reaches page JavaScript, and why.
 *
 * Live Logs is a WebSocket. Browsers cannot set an Authorization header on a WebSocket
 * handshake, and the API reads the session from `?token=` on that route
 * (logs/router.py), never from a cookie. So the live view asks this route for the token
 * right before it opens the socket and uses it only to build that URL.
 *
 * This grants nothing new: it is the same token, scoped to the same user and organization,
 * with the same expiry, that already authenticates every proxied call. It is only handed to
 * same-origin requests (browsers refuse to let another site read this response, and the
 * Sec-Fetch-Site check below refuses it outright), and is never cached.
 */
export const dynamic = "force-dynamic";

const NO_STORE = { "cache-control": "no-store, private", pragma: "no-cache" };

export async function GET(req: NextRequest) {
  const site = req.headers.get("sec-fetch-site");
  if (site && site !== "same-origin") {
    return Response.json(
      {
        error: {
          code: "cross_site_request",
          type: "invalid_request_error",
          message: "Not available cross-site.",
          details: {},
        },
      },
      { status: 403, headers: NO_STORE }
    );
  }
  const token = await sessionToken();
  if (!token) {
    return Response.json(
      {
        error: {
          code: "not_signed_in",
          type: "authentication_error",
          message: "Sign in to continue",
          details: {},
        },
      },
      { status: 401, headers: NO_STORE }
    );
  }
  return Response.json({ token }, { headers: NO_STORE });
}
