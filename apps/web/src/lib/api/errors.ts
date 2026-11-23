/**
 * The API answers every failure with one envelope (core/errors.py):
 *   {"error": {"code", "type", "message", "details"}}
 * ApiError carries it through React Query so views can render the message and, where it
 * matters, the structured details (the validation errors of a form, for example).
 */

export interface ErrorEnvelope {
  error: {
    code: string;
    type?: string;
    message: string;
    details?: Record<string, unknown> | null;
  };
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly type: string;
  readonly details: Record<string, unknown>;

  constructor(opts: {
    status: number;
    code: string;
    message: string;
    type?: string;
    details?: Record<string, unknown> | null;
  }) {
    super(opts.message);
    this.name = "ApiError";
    this.status = opts.status;
    this.code = opts.code;
    this.type = opts.type ?? "api_error";
    this.details = opts.details ?? {};
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }

  get isForbidden(): boolean {
    return this.status === 403;
  }

  get isNetwork(): boolean {
    return this.status === 0;
  }
}

/** Codes this dashboard reacts to specifically. */
export const ERROR_CODES = {
  notSignedIn: "not_signed_in",
  sessionExpired: "session_expired",
  insufficientRole: "insufficient_role",
  invalidCredentials: "invalid_credentials",
  validation: "validation_error",
  noAiProvider: "no_ai_provider",
  logStoreUnavailable: "log_store_unavailable",
  apiUnreachable: "api_unreachable",
} as const;

export function isErrorEnvelope(body: unknown): body is ErrorEnvelope {
  if (typeof body !== "object" || body === null || !("error" in body)) return false;
  const err = (body as { error: unknown }).error;
  return (
    typeof err === "object" &&
    err !== null &&
    typeof (err as { message?: unknown }).message === "string" &&
    typeof (err as { code?: unknown }).code === "string"
  );
}

interface ValidationItem {
  loc?: Array<string | number>;
  msg?: string;
}

/** Turn the validation details into one readable line per field. */
export function validationMessages(details: Record<string, unknown>): string[] {
  const errors = details.errors;
  if (!Array.isArray(errors)) return [];
  return (errors as ValidationItem[])
    .filter((e) => typeof e?.msg === "string")
    .map((e) => {
      const loc = (e.loc ?? []).filter((p) => p !== "body" && p !== "query" && p !== "path");
      const field = loc.length ? `${loc.join(".")}: ` : "";
      return `${field}${e.msg}`;
    });
}

/** Build an ApiError from a status and whatever body came back (JSON or not). */
export function parseApiError(status: number, body: unknown): ApiError {
  if (isErrorEnvelope(body)) {
    const { code, type, message, details } = body.error;
    return new ApiError({ status, code, type, message, details: details ?? {} });
  }
  // FastAPI's default validation body, in case a route bypasses the envelope.
  if (
    typeof body === "object" &&
    body !== null &&
    Array.isArray((body as { detail?: unknown }).detail)
  ) {
    return new ApiError({
      status,
      code: ERROR_CODES.validation,
      type: "invalid_request_error",
      message: "Request validation failed",
      details: { errors: (body as { detail: unknown[] }).detail },
    });
  }
  return new ApiError({ status, code: `http_${status}`, message: fallbackMessage(status) });
}

export function fallbackMessage(status: number): string {
  if (status === 0) return "Cannot reach LogMind. Check your connection, then retry.";
  if (status === 401) return "Your session expired. Sign in again.";
  if (status === 403)
    return "Your role does not allow this action. Ask an owner of your organization.";
  if (status === 404) return "This item no longer exists, or it belongs to another organization.";
  if (status === 409) return "This conflicts with the current state. Reload and try again.";
  if (status === 429) return "Too many requests. Wait a moment, then retry.";
  if (status === 502 || status === 503 || status === 504)
    return "The LogMind API is not reachable from the dashboard server. Check that it is running, then retry.";
  if (status >= 500)
    return "The API hit an unexpected error. Retry, and check the API logs if it persists.";
  return `Request failed (HTTP ${status}).`;
}

/**
 * 401s that answer the sign-in form: the person is told exactly why (wrong password)
 * instead of "your session expired".
 */
export const SIGN_IN_ERRORS: ReadonlySet<string> = new Set([ERROR_CODES.invalidCredentials]);

/** The message to show a person for any thrown value, always actionable. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === ERROR_CODES.validation) {
      const lines = validationMessages(err.details);
      if (lines.length) return lines.join(". ");
    }
    if (err.status === 401 && !SIGN_IN_ERRORS.has(err.code)) return fallbackMessage(401);
    if (err.code === ERROR_CODES.insufficientRole)
      return `${err.message}. Ask an owner of your organization to change your role.`;
    return err.message || fallbackMessage(err.status);
  }
  // fetch rejects with a TypeError when the network fails; any other TypeError is a bug in
  // the page, and blaming the API for it would send people to the wrong place.
  if (err instanceof TypeError && /fetch|network|load failed/i.test(err.message))
    return fallbackMessage(0);
  if (err instanceof TypeError)
    return "This page hit a bug. Reload it; if it happens again, report it with what you clicked.";
  if (err instanceof Error && err.message) return err.message;
  return "Something went wrong. Retry in a moment.";
}

/** The organisation has no AI provider yet: the investigation UI links to Settings. */
export function isNoProvider(err: unknown): err is ApiError {
  return err instanceof ApiError && err.code === ERROR_CODES.noAiProvider;
}
