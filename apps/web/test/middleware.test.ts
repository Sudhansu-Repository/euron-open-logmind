import { describe, expect, it } from "vitest";

import { contentSecurityPolicy, needsSignIn } from "@/middleware";

describe("middleware", () => {
  it("lets sign-in pages and the root through", () => {
    expect(needsSignIn("/")).toBe(false);
    expect(needsSignIn("/login")).toBe(false);
    expect(needsSignIn("/signup")).toBe(false);
  });
  it("gates every dashboard page", () => {
    for (const p of [
      "/overview",
      "/logs",
      "/errors/abc",
      "/investigations",
      "/settings",
      "/loginx",
    ])
      expect(needsSignIn(p)).toBe(true);
  });
  it("forbids framing and inline eval in production", () => {
    const csp = contentSecurityPolicy(true, "");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).not.toContain("unsafe-eval");
    expect(csp).toContain("connect-src 'self'");
  });
  it("allows the dev websocket and a configured socket override", () => {
    expect(contentSecurityPolicy(false, "")).toContain("ws:");
    expect(contentSecurityPolicy(true, "ws://api:6030")).toContain(
      "connect-src 'self' ws://api:6030"
    );
  });
});
