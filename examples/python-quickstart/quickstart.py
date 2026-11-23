"""Euron Open LogMind quickstart (Python).

Sends a few structured lines, a handled exception, and a record through the stdlib
``logging`` handler, then prints what the API accepted. Configured only through env:

    LOGMIND_API_KEY   a project API key (lmk_<prefix>_<secret>), required to send
    LOGMIND_ENDPOINT  defaults to http://localhost:6030
"""

from __future__ import annotations

import logging
import uuid

from euron_logmind import IngestError, LogMind, LogMindHandler


def charge_card(order_id: int) -> None:
    raise TimeoutError(f"payment gateway did not answer for order {order_id} within 30s")


def main() -> None:
    run_id = uuid.uuid4().hex[:8]
    log = LogMind(service="checkout", environment="development")

    # 1. Plain structured lines: extra keyword arguments become attributes.
    log.info("checkout started", run_id=run_id, cart_items=3)
    log.warning("inventory low", run_id=run_id, sku="SKU-1042", remaining=2)
    log.debug("pricing rules applied", run_id=run_id, rules=["vat-in", "promo-diwali"])

    # 2. A handled exception: type, message and traceback are sent as a structured field.
    try:
        charge_card(order_id=42)
    except TimeoutError:
        log.exception("payment failed", run_id=run_id, order_id=42, request_id=f"req-{run_id}")

    # 3. The stdlib logging handler: existing logging calls ship to LogMind unchanged.
    logger = logging.getLogger("checkout.shipping")
    logger.setLevel(logging.INFO)
    logger.addHandler(LogMindHandler(log))
    logger.info("label printed for order %s", 42, extra={"run_id": run_id, "carrier": "bluedart"})

    # 4. send_batch is synchronous and returns the API's IngestResult.
    try:
        result = log.send_batch(
            [{"message": "quickstart finished", "attributes": {"run_id": run_id}}]
        )
        print(f"send_batch: accepted={result.accepted} event_ids={result.event_ids}")
    except IngestError as exc:
        print(f"send_batch failed: {exc.message}")

    drained = log.close(timeout=10)
    stats = log.stats
    print(
        f"background: drained={drained} accepted={stats.accepted} "
        f"dropped={stats.dropped_failed + stats.dropped_queue_full + stats.dropped_closed}"
    )
    print(f"search the dashboard for run_id:{run_id}")


if __name__ == "__main__":
    main()
