"""OpenTelemetry Python SDK logs exported straight to Euron Open LogMind.

No LogMind package is involved: a standard ``LoggerProvider`` with the OTLP/HTTP
``OTLPLogExporter`` posts to LogMind's ``/v1/logs`` endpoint, and the OpenTelemetry
``LoggingHandler`` bridges the stdlib ``logging`` module into it. Configured through env:

    LOGMIND_API_KEY        a project API key (lmk_<prefix>_<secret>), required
    LOGMIND_OTLP_ENDPOINT  defaults to http://localhost:6030/v1/logs
"""

from __future__ import annotations

import logging
import os
import sys
import uuid

from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource


def main() -> int:
    api_key = os.environ.get("LOGMIND_API_KEY", "")
    if not api_key:
        print("set LOGMIND_API_KEY to a project API key (lmk_...)", file=sys.stderr)
        return 2
    endpoint = os.environ.get("LOGMIND_OTLP_ENDPOINT", "http://localhost:6030/v1/logs")

    provider = LoggerProvider(
        resource=Resource.create(
            {
                "service.name": "inventory-api",
                "service.version": "1.4.2",
                "deployment.environment": "development",
            }
        )
    )
    # timeout bounds each export, retries included, so an unreachable API cannot hang exit.
    exporter = OTLPLogExporter(
        endpoint=endpoint, headers={"Authorization": f"Bearer {api_key}"}, timeout=10
    )
    provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
    set_logger_provider(provider)

    # Bridge stdlib logging into OpenTelemetry. Attributes come from ``extra=``.
    logging.getLogger().addHandler(LoggingHandler(level=logging.INFO, logger_provider=provider))
    logging.getLogger().setLevel(logging.INFO)
    log = logging.getLogger("inventory.api")

    run_id = uuid.uuid4().hex[:8]
    log.info("stock check", extra={"run_id": run_id, "sku": "SKU-1042", "warehouse": "BLR-2"})
    log.warning("stock below threshold", extra={"run_id": run_id, "sku": "SKU-1042", "on_hand": 3})
    try:
        {"BLR-2": 3}["DEL-1"]
    except KeyError:
        log.exception("unknown warehouse", extra={"run_id": run_id, "warehouse": "DEL-1"})

    # Export everything before exiting.
    flushed = provider.force_flush(timeout_millis=15_000)
    provider.shutdown()
    if not flushed:
        print(f"could not export to {endpoint} (is LogMind running?)", file=sys.stderr)
        return 1
    print(f"sent 3 records over OTLP to {endpoint}; search the dashboard for run_id:{run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
