import type { NextConfig } from "next";

/**
 * Same-origin deployment: the browser only ever talks to this origin.
 *
 * Authenticated API calls do NOT go through rewrites. The LogMind API reads the
 * session only from an `Authorization: Bearer` header (auth/dependencies.py `bearer()`),
 * and the dashboard keeps that token in an httpOnly cookie the browser JS never sees. A
 * rewrite cannot add a header, so every `/api/v1/*` call goes through this app's own
 * route handler at `/api/proxy/[...path]`, which reads the cookie on the server and
 * attaches the Bearer header (see src/app/api/proxy/[...path]/route.ts).
 *
 * What is rewritten here is only what needs no session header:
 *   /ws/logs         the Live Logs WebSocket, to the API's /api/v1/logs/live (auth travels
 *                    as `?token=` in the URL, minted by /api/session/ws-token), upgraded by
 *                    the Next server
 *   /healthz, /readyz, /docs, /openapi.json   the API's public probes and docs
 * The API pings every 25 seconds; the proxy timeout is well above that.
 *
 * API_URL is the API's address as this server reaches it (API_INTERNAL_URL is accepted
 * for older env files). Next resolves these destinations when it BUILDS the standalone
 * server, so infra/docker/web.Dockerfile passes API_URL as a build ARG.
 */
const apiInternal = (process.env.API_URL || process.env.API_INTERNAL_URL || "http://localhost:6030").replace(/\/+$/, "");

const prod = process.env.NODE_ENV === "production";

const nextConfig: NextConfig = {
  // One self-contained server bundle (`node server.js`), the unit a container image ships.
  output: "standalone",
  outputFileTracingRoot: __dirname,
  poweredByHeader: false,
  devIndicators: false,
  reactStrictMode: true,
  experimental: { proxyTimeout: 120_000 },
  async redirects() {
    // Browsers ask for /favicon.ico on their own; the app's icon is an SVG.
    return [{ source: "/favicon.ico", destination: "/icon.svg", permanent: true }];
  },
  async rewrites() {
    // afterFiles rewrites: the app's own route handlers (/api/healthz, /api/session,
    // /api/proxy) always win; nothing under /api is rewritten.
    return [
      { source: "/ws/logs", destination: `${apiInternal}/api/v1/logs/live` },
      { source: "/healthz", destination: `${apiInternal}/healthz` },
      { source: "/readyz", destination: `${apiInternal}/readyz` },
      { source: "/docs", destination: `${apiInternal}/docs` },
      { source: "/openapi.json", destination: `${apiInternal}/openapi.json` },
    ];
  },
  async headers() {
    const common = [
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
      { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
      // Browsers honour HSTS only over HTTPS, so this is inert on http://localhost.
      ...(prod ? [{ key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" }] : []),
    ];
    // The Content-Security-Policy (frame-ancestors 'none') is set per request in middleware.ts.
    return [{ source: "/:path*", headers: [...common, { key: "X-Frame-Options", value: "DENY" }] }];
  },
};

export default nextConfig;
