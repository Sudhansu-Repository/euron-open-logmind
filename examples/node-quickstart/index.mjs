// Euron Open LogMind quickstart (Node.js).
//
// Sends a few structured lines and a captured exception, then prints what the API
// accepted. Configured only through env:
//
//   LOGMIND_API_KEY   a project API key (lmk_<prefix>_<secret>), required to send
//   LOGMIND_ENDPOINT  defaults to http://localhost:6030

import { randomUUID } from "node:crypto";

import { IngestError, LogMind } from "@euron/logmind";

function chargeCard(orderId) {
  throw new Error(`payment gateway did not answer for order ${orderId} within 30s`, {
    cause: new Error("ETIMEDOUT"),
  });
}

const runId = randomUUID().slice(0, 8);
const log = new LogMind({ service: "checkout", environment: "development" });

// 1. Plain structured lines: extra keys become attributes.
log.info("checkout started", { runId, cartItems: 3 });
log.warn("inventory low", { runId, sku: "SKU-1042", remaining: 2 });
log.debug("pricing rules applied", { runId, rules: ["vat-in", "promo-diwali"] });

// 2. A handled exception: err.name, err.message and err.stack (with the cause chain).
try {
  chargeCard(42);
} catch (err) {
  log.captureException(err, { message: "payment failed", runId, orderId: 42, requestId: `req-${runId}` });
}

// 3. sendBatch is awaited and resolves the API's IngestResult.
try {
  const result = await log.sendBatch([{ message: "quickstart finished", attributes: { runId } }]);
  console.log(`sendBatch: accepted=${result.accepted} eventIds=${JSON.stringify(result.eventIds)}`);
} catch (err) {
  console.log(`sendBatch failed: ${err instanceof IngestError ? err.message : String(err)}`);
}

const drained = await log.close(10_000);
const { accepted, droppedFailed, droppedQueueFull, droppedClosed } = log.stats;
console.log(`background: drained=${drained} accepted=${accepted} dropped=${droppedFailed + droppedQueueFull + droppedClosed}`);
console.log(`search the dashboard for runId:${runId}`);
