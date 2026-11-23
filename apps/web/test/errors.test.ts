import { describe, expect, it } from "vitest";

import {
  ApiError,
  errorMessage,
  fallbackMessage,
  isErrorEnvelope,
  isNoProvider,
  parseApiError,
  validationMessages,
} from "@/lib/api/errors";

const refusal = {
  error: {
    code: "no_ai_provider",
    type: "invalid_request_error",
    message:
      "AI investigations need an AI provider. An admin adds one under Settings, AI providers.",
    details: { project_id: "5f0c" },
  },
};

describe("parseApiError", () => {
  it("reads the API envelope", () => {
    const e = parseApiError(409, refusal);
    expect(e).toBeInstanceOf(ApiError);
    expect(e.status).toBe(409);
    expect(e.code).toBe("no_ai_provider");
    expect(e.type).toBe("invalid_request_error");
    expect(e.details).toEqual({ project_id: "5f0c" });
    expect(isNoProvider(e)).toBe(true);
  });

  it("defaults missing type and details", () => {
    const e = parseApiError(404, {
      error: { code: "not_found", message: "Error group not found" },
    });
    expect(e.type).toBe("api_error");
    expect(e.details).toEqual({});
    expect(isNoProvider(e)).toBe(false);
  });

  it("understands FastAPI's raw validation body", () => {
    const e = parseApiError(422, { detail: [{ loc: ["body", "name"], msg: "Field required" }] });
    expect(e.code).toBe("validation_error");
    expect(validationMessages(e.details)).toEqual(["name: Field required"]);
  });

  it("falls back on a status message for anything else", () => {
    expect(parseApiError(502, "<html>").message).toBe(fallbackMessage(502));
    expect(parseApiError(0, null).isNetwork).toBe(true);
    expect(parseApiError(401, null).isUnauthorized).toBe(true);
    expect(parseApiError(403, null).isForbidden).toBe(true);
    expect(parseApiError(418, null).code).toBe("http_418");
  });

  it("recognises envelopes strictly", () => {
    expect(isErrorEnvelope(refusal)).toBe(true);
    expect(isErrorEnvelope({ error: "x" })).toBe(false);
    expect(isErrorEnvelope({ error: { code: 1, message: "m" } })).toBe(false);
    expect(isErrorEnvelope(null)).toBe(false);
  });
});

describe("errorMessage", () => {
  it("joins validation errors into readable lines", () => {
    const e = parseApiError(422, {
      error: {
        code: "validation_error",
        message: "Request validation failed",
        details: {
          errors: [
            {
              loc: ["body", "redaction_rules", 0],
              msg: "Value error, Exactly one of pattern or field must be set",
            },
          ],
        },
      },
    });
    expect(errorMessage(e)).toBe(
      "redaction_rules.0: Value error, Exactly one of pattern or field must be set"
    );
  });

  it("turns any session 401 into a sign-in prompt but keeps a wrong password", () => {
    expect(
      errorMessage(
        parseApiError(401, {
          error: { code: "session_expired", message: "Your session expired. Sign in again" },
        })
      )
    ).toBe("Your session expired. Sign in again.");
    expect(
      errorMessage(
        parseApiError(401, {
          error: { code: "invalid_credentials", message: "Incorrect email or password" },
        })
      )
    ).toBe("Incorrect email or password");
  });

  it("says what to do about a role", () => {
    const e = parseApiError(403, {
      error: { code: "insufficient_role", message: "This needs the admin role" },
    });
    expect(errorMessage(e)).toMatch(/Ask an owner/);
  });

  it("separates network failures from page bugs", () => {
    expect(errorMessage(new TypeError("Failed to fetch"))).toBe(fallbackMessage(0));
    expect(errorMessage(new TypeError("x is undefined"))).toMatch(/bug/);
    expect(errorMessage(new Error("Plain"))).toBe("Plain");
    expect(errorMessage("weird")).toMatch(/Something went wrong/);
  });
});
