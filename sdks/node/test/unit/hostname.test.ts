// os.hostname() can throw on a misconfigured host; the client must still construct.

import { describe, expect, it, vi } from "vitest";

vi.mock("node:os", () => ({
  hostname: () => {
    throw new Error("uv_os_gethostname failed");
  },
}));

const { LogMind } = await import("../../src/client.js");

describe("host default", () => {
  it("leaves host unset when the hostname cannot be read", async () => {
    const log = new LogMind({ apiKey: "lmk_x_y", fetch: () => Promise.resolve(new Response("{}")), flushOnExit: false });
    expect(log.host).toBeUndefined();
    await log.close();
  });
});
