import { mkdir } from "node:fs/promises";

import { request } from "@playwright/test";

import { authFile, BASE, PASSWORD, USERS, type Who } from "./helpers";

/**
 * Sign in once as the demo owner (and any other demo person this suite needs) through the
 * web app's own session bridge (POST /api/session, same as the real sign-in form), and
 * save the resulting httpOnly-cookie session for every suite. Signing in per test would
 * also work, but doing it once here keeps every spec file independent of sign-in timing.
 */
export default async function globalSetup(): Promise<void> {
  await mkdir(".auth", { recursive: true });
  for (const who of Object.keys(USERS) as Who[]) {
    const ctx = await request.newContext({ baseURL: BASE, extraHTTPHeaders: { origin: BASE } });
    const resp = await ctx.post("/api/session", { data: { action: "login", email: USERS[who], password: PASSWORD } });
    if (!resp.ok()) {
      throw new Error(`demo sign-in for ${USERS[who]} failed (${resp.status()}): ${await resp.text()}. Run make demo first.`);
    }
    await ctx.storageState({ path: authFile(who) });
    await ctx.dispose();
  }
}
