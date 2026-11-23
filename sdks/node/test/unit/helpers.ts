// Shared test doubles: a fake `fetch` that records every batch the SDK sends and answers
// with scripted responses, so no test touches the network.

import { LogMind, type LogMindOptions } from "../../src/client.js";
import type { FetchLike } from "../../src/transport.js";

export const BASE = "http://logmind.test";
export const API_KEY = "lmk_testprefix_0123456789abcdef";

export interface CapturedRequest {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: { logs: Record<string, any>[]; defaults: Record<string, string> };
}

type Step = Response | Error | ((req: CapturedRequest, signal: AbortSignal | null | undefined) => Response | Promise<Response>);

export function accepted(req: CapturedRequest): Response {
  const n = req.body.logs.length;
  return Response.json(
    {
      accepted: n,
      rejected: [],
      redactions: 0,
      error_groups: 0,
      event_ids: Array.from({ length: n }, (_, i) => `00000000-0000-4000-8000-${String(i).padStart(12, "0")}`),
    },
    { status: 202 },
  );
}

export function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });
}

/** `script` is consumed one step per request; once exhausted every request is accepted. */
export function fakeFetch(...script: Step[]): { fetch: FetchLike; requests: CapturedRequest[]; lines: () => Record<string, any>[] } {
  const requests: CapturedRequest[] = [];
  const queue = [...script];
  const fetchImpl: FetchLike = async (input, init) => {
    const req: CapturedRequest = {
      url: input,
      method: init.method ?? "GET",
      headers: { ...(init.headers as Record<string, string>) },
      body: JSON.parse(init.body as string),
    };
    requests.push(req);
    await Promise.resolve();
    const step = queue.shift() ?? accepted;
    if (step instanceof Error) throw step;
    if (step instanceof Response) return step;
    return step(req, init.signal);
  };
  return { fetch: fetchImpl, requests, lines: () => requests.flatMap((r) => r.body.logs) };
}

export function makeClient(fetchImpl: FetchLike, options: Partial<LogMindOptions> = {}): LogMind {
  return new LogMind({
    apiKey: API_KEY,
    endpoint: BASE,
    service: "checkout",
    environment: "test",
    host: "web-1",
    flushIntervalMs: 60_000,
    backoffBaseMs: 1,
    flushOnExit: false,
    onWarning: () => undefined,
    fetch: fetchImpl,
    ...options,
  });
}

export async function waitFor(predicate: () => boolean, timeoutMs = 2000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return true;
    await new Promise((r) => setTimeout(r, 5));
  }
  return predicate();
}
