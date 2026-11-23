import { describe, expect, it } from "vitest";

import * as sdk from "../../src/index.js";

describe("public entry point", () => {
  it("exports the client, errors and constants", () => {
    expect(sdk.LogMind).toBeTypeOf("function");
    expect(new sdk.IngestError("x", { status: 401, code: "c", retryable: false })).toBeInstanceOf(sdk.LogMindError);
    expect(sdk.DEFAULT_ENDPOINT).toBe("http://localhost:6030");
    expect(sdk.DEFAULT_ENVIRONMENT).toBe("production");
    expect(sdk.LEVELS).toEqual(["trace", "debug", "info", "warn", "error", "fatal"]);
    expect(sdk.VERSION).toBe("0.1.0");
  });
});
