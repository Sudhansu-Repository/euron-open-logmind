"""Ingestion endpoints, authenticated with a project API key.

* ``POST /api/v1/logs``: one line in LogMind's native JSON shape.
* ``POST /api/v1/logs/batch``: up to ``MAX_BATCH_EVENTS`` lines (the SDKs use this).
* ``POST /v1/logs``: OTLP/HTTP, protobuf or JSON, optionally gzip, at the path every
  OpenTelemetry exporter appends to its endpoint by default, so a Collector pointed at
  ``http://<logmind-api>`` needs no path setting (A6). ``/api/v1/otlp/v1/logs`` is the same
  handler under the API prefix.
"""

from __future__ import annotations

import gzip
import zlib
from datetime import UTC, datetime

import orjson
from fastapi import APIRouter, Request, Response
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceResponse

from logmind.core.deps import ContainerDep, SessionDep
from logmind.core.errors import AppError, PayloadTooLargeError
from logmind.ingestion import otlp
from logmind.ingestion.normalize import InvalidEventError, RawEvent
from logmind.ingestion.schemas import BatchDefaults, BatchIn, IngestResult, LogIn
from logmind.ingestion.service import from_native, ingest
from logmind.projects.dependencies import ProjectKey

router = APIRouter(tags=["ingestion"])


def _native(
    logs: list[LogIn], defaults: BatchDefaults, max_chars: int
) -> list[tuple[int, RawEvent | InvalidEventError]]:
    now = datetime.now(UTC)
    out: list[tuple[int, RawEvent | InvalidEventError]] = []
    for i, item in enumerate(logs):
        try:
            out.append((i, from_native(item, defaults, now, max_chars)))
        except InvalidEventError as exc:
            out.append((i, exc))
    return out


@router.post(
    "/api/v1/logs",
    response_model=IngestResult,
    status_code=202,
    summary="Send one log line",
)
async def send_log(
    body: LogIn, config: ProjectKey, session: SessionDep, container: ContainerDep
) -> IngestResult:
    items = _native([body], BatchDefaults(), container.settings.max_message_chars)
    return await ingest(container, session, config, items, source="api")


@router.post(
    "/api/v1/logs/batch",
    response_model=IngestResult,
    status_code=202,
    summary="Send a batch of log lines (the SDKs use this)",
)
async def send_batch(
    body: BatchIn,
    request: Request,
    config: ProjectKey,
    session: SessionDep,
    container: ContainerDep,
) -> IngestResult:
    limit = container.settings.max_batch_events
    if len(body.logs) > limit:
        raise PayloadTooLargeError(
            f"A batch holds at most {limit} lines; split it and send the rest separately",
            details={"max_batch_events": limit},
        )
    source = "sdk" if request.headers.get("x-logmind-sdk") else "api"
    items = _native(body.logs, body.defaults, container.settings.max_message_chars)
    return await ingest(container, session, config, items, source=source)


async def _read_body(request: Request, max_bytes: int) -> bytes:
    raw = await request.body()
    if len(raw) > max_bytes:
        raise PayloadTooLargeError(f"The request body is larger than {max_bytes} bytes")
    encoding = request.headers.get("content-encoding", "").lower()
    if encoding == "gzip":
        try:
            raw = gzip.decompress(raw)
        except (OSError, EOFError) as exc:
            raise AppError("The gzip body could not be decompressed", code="bad_encoding") from exc
    elif encoding == "deflate":
        try:
            raw = zlib.decompress(raw)
        except zlib.error as exc:
            raise AppError(
                "The deflate body could not be decompressed", code="bad_encoding"
            ) from exc
    elif encoding not in ("", "identity"):
        raise AppError(f"Unsupported content encoding {encoding!r}", code="bad_encoding")
    if len(raw) > max_bytes * 10:
        raise PayloadTooLargeError("The decompressed body is too large")
    return raw


@router.post(
    "/v1/logs",
    summary="OTLP/HTTP logs (protobuf or JSON)",
    responses={200: {"description": "ExportLogsServiceResponse (protobuf or JSON)"}},
)
@router.post("/api/v1/otlp/v1/logs", include_in_schema=False)
async def otlp_logs(
    request: Request, config: ProjectKey, session: SessionDep, container: ContainerDep
) -> Response:
    settings = container.settings
    raw = await _read_body(request, settings.max_body_bytes)
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    now = datetime.now(UTC)
    try:
        if content_type == "application/json":
            parsed = list(otlp.parse_json(raw, now=now, max_chars=settings.max_message_chars))
        else:
            parsed = list(otlp.parse_protobuf(raw, now=now, max_chars=settings.max_message_chars))
    except InvalidEventError as exc:
        raise AppError(str(exc), code="invalid_otlp") from exc
    if len(parsed) > settings.max_batch_events * 10:
        raise PayloadTooLargeError("Too many log records in one export; lower the batch size")
    result = await ingest(container, session, config, parsed, source="otlp")
    rejected = len(result.rejected)
    message = result.rejected[0].reason if result.rejected else ""
    if content_type == "application/json":
        body: dict[str, object] = {}
        if rejected:
            body["partialSuccess"] = {"rejectedLogRecords": str(rejected), "errorMessage": message}
        return Response(orjson.dumps(body), media_type="application/json")
    response = ExportLogsServiceResponse()
    if rejected:
        response.partial_success.rejected_log_records = rejected
        response.partial_success.error_message = message
    return Response(response.SerializeToString(), media_type="application/x-protobuf")
