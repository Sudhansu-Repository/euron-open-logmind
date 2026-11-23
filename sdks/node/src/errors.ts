// Errors raised by the explicit `sendBatch` path only. The logging methods, `flush` and
// `close` never throw: a logging SDK must not be the reason an application fails.

export class LogMindError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "LogMindError";
  }
}

/** A batch could not be delivered. `status` is `null` for a transport failure (refused
 * connection, DNS, timeout); `retryable` says whether the SDK would retry it. */
export class IngestError extends LogMindError {
  readonly status: number | null;
  readonly code: string;
  readonly retryable: boolean;

  constructor(message: string, options: { status: number | null; code: string; retryable: boolean }) {
    super(message);
    this.name = "IngestError";
    this.status = options.status;
    this.code = options.code;
    this.retryable = options.retryable;
  }
}
