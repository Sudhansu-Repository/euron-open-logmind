import { describe, expect, it } from "vitest";

import {
  apiBaseUrl,
  cookieSecure,
  forwardHeaders,
  isSameOrigin,
  SESSION_COOKIE,
  SESSION_MAX_AGE_S,
  sessionCookieOptions,
  unreachableBody,
  upstreamPath,
} from "@/lib/session";

describe("session cookie", () => {
  it("is named lm_session and httpOnly", () => {
    expect(SESSION_COOKIE).toBe("lm_session");
    expect(sessionCookieOptions(true)).toEqual({
      httpOnly: true,
      secure: true,
      sameSite: "lax",
      path: "/",
      maxAge: SESSION_MAX_AGE_S,
    });
    expect(sessionCookieOptions(false).secure).toBe(false);
  });
  it("is Secure on HTTPS, directly or behind a proxy, and honours COOKIE_SECURE", () => {
    expect(cookieSecure("https:", null, undefined)).toBe(true);
    expect(cookieSecure("http:", "https", undefined)).toBe(true);
    expect(cookieSecure("http:", "https, http", undefined)).toBe(true);
    expect(cookieSecure("http:", null, undefined)).toBe(false);
    expect(cookieSecure("http:", "http", undefined)).toBe(false);
    expect(cookieSecure("http:", null, "true")).toBe(true);
    expect(cookieSecure("https:", null, "false")).toBe(false);
  });
});

describe("apiBaseUrl", () => {
  it("prefers API_URL, then API_INTERNAL_URL, then the local default, without a trailing slash", () => {
    expect(apiBaseUrl({ API_URL: "http://api:8080/" })).toBe("http://api:8080");
    expect(apiBaseUrl({ API_INTERNAL_URL: "http://internal:1" })).toBe("http://internal:1");
    expect(apiBaseUrl({})).toBe("http://localhost:6030");
    expect(apiBaseUrl({ API_URL: "", API_INTERNAL_URL: "http://b" })).toBe("http://b");
  });
});

describe("upstreamPath", () => {
  it("only proxies /api/v1 routes", () => {
    expect(upstreamPath(["api", "v1", "logs"])).toBe("/api/v1/logs");
    expect(upstreamPath(["api", "v1", "errors", "abc", "history"])).toBe(
      "/api/v1/errors/abc/history"
    );
    expect(upstreamPath(["api", "v1"])).toBeNull();
    expect(upstreamPath(["healthz"])).toBeNull();
    expect(upstreamPath(["api", "v2", "x"])).toBeNull();
    expect(upstreamPath(["ws", "live"])).toBeNull();
  });
  it("refuses traversal", () => {
    expect(upstreamPath(["api", "v1", "..", "..", "docs"])).toBeNull();
    expect(upstreamPath(["api", "v1", "a/b"])).toBeNull();
    expect(upstreamPath(["api", "v1", ""])).toBeNull();
  });
  it("encodes segments", () => {
    expect(upstreamPath(["api", "v1", "logs", "a b"])).toBe("/api/v1/logs/a%20b");
  });
});

describe("isSameOrigin", () => {
  it("allows reads and same-origin writes", () => {
    expect(isSameOrigin("GET", "https://evil.example", "debug.local")).toBe(true);
    expect(isSameOrigin("POST", "http://localhost:5210", "localhost:5210")).toBe(true);
    expect(isSameOrigin("POST", null, "localhost:5210")).toBe(true);
  });
  it("refuses cross-site writes", () => {
    expect(isSameOrigin("POST", "https://evil.example", "localhost:5210")).toBe(false);
    expect(isSameOrigin("DELETE", "garbage", "localhost:5210")).toBe(false);
    expect(isSameOrigin("PATCH", "http://localhost:5210", null)).toBe(false);
  });
});

describe("forwardHeaders", () => {
  it("adds the Bearer token and forwards only what the API needs", () => {
    const h = forwardHeaders(
      new Headers({
        "content-type": "application/json",
        cookie: "lm_session=secret",
        "x-forwarded-for": "1.2.3.4",
      }),
      "tok"
    );
    expect(h.get("authorization")).toBe("Bearer tok");
    expect(h.get("content-type")).toBe("application/json");
    expect(h.get("x-forwarded-for")).toBe("1.2.3.4");
    expect(h.get("cookie")).toBeNull();
  });
  it("sends no authorization without a session", () => {
    expect(forwardHeaders(new Headers(), null).get("authorization")).toBeNull();
  });
  it("answers unreachable with the API's envelope shape", () => {
    expect(unreachableBody().error.code).toBe("api_unreachable");
  });
});
