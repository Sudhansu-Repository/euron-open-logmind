// Against a live LogMind API: lines are accepted and stored (one event id per stored
// line), a captured exception is ingested, a bad key is refused, and the background path
// delivers everything it queued. Skipped unless LOGMIND_TEST_API_URL and
// LOGMIND_TEST_API_KEY are set, matching the Python SDK's integration suite.

import { randomUUID } from "node:crypto";

import { afterEach, describe, expect, it } from "vitest";

import { LogMind } from "../../src/client.js";
import { IngestError } from "../../src/errors.js";

const URL = process.env.LOGMIND_TEST_API_URL ?? "";
const API_KEY = process.env.LOGMIND_TEST_API_KEY ?? "";

const maybeDescribe = URL && API_KEY ? describe : describe.skip;

const active: LogMind[] = [];
afterEach(async () => {
  await Promise.all(active.splice(0).map((log) => log.close(15_000)));
});

function makeClient(apiKey = API_KEY): LogMind {
  const log = new LogMind({ apiKey, endpoint: URL, service: "sdk-node-integration", environment: "test", flushIntervalMs: 200, flushOnExit: false });
  active.push(log);
  return log;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

maybeDescribe("LogMind against a live API", () => {
  it("accepts a batch and returns event ids", async () => {
    const marker = randomUUID();
    const result = await makeClient().sendBatch([
      { message: `integration info ${marker}`, level: "info", attributes: { marker } },
      { message: `integration warn ${marker}`, level: "warn", requestId: `req-${marker.slice(0, 8)}` },
    ]);
    expect(result.accepted).toBe(2);
    expect(result.rejected).toEqual([]);
    expect(result.eventIds).toHaveLength(2);
    for (const id of result.eventIds) expect(id).toMatch(UUID);
  });

  it("ingests a captured exception", async () => {
    const result = await makeClient().sendBatch([{ message: "payment timed out", level: "error", exception: new Error("upstream took too long") }]);
    expect(result.accepted).toBe(1);
    expect(result.eventIds).toHaveLength(1);
  });

  it("delivers everything queued on the background path", async () => {
    const log = makeClient();
    for (let i = 0; i < 25; i += 1) log.info(`background line ${String(i)}`, { index: i });
    log.captureException(new TypeError("handled"), { source: "integration" });
    expect(await log.flush(15_000)).toBe(true);
    expect(log.stats).toMatchObject({ accepted: 26, droppedFailed: 0, rejected: 0 });
  });

  it("refuses a bad key with 401", async () => {
    const err = (await makeClient("lmk_nope_notarealsecret")
      .sendBatch([{ message: "should be refused" }])
      .catch((e: unknown) => e)) as IngestError;
    expect(err).toBeInstanceOf(IngestError);
    expect(err.status).toBe(401);
    expect(err.retryable).toBe(false);
  });
});
