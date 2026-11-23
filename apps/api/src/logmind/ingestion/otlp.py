"""OTLP logs, both encodings an OpenTelemetry SDK or Collector sends (A6):

* ``application/x-protobuf``: the default of every ``otlphttp`` exporter, decoded with
  the official ``opentelemetry-proto`` message classes;
* ``application/json``: the OTLP/JSON mapping (hex trace and span ids, 64-bit integers as
  strings).

Both are mapped onto :class:`~logmind.ingestion.normalize.RawEvent` following the OTel
log data model and semantic conventions: ``service.name``, ``deployment.environment``
(``.name``) and ``host.name`` from the resource; ``severityNumber``/``severityText`` for
the level; ``body`` for the message; ``exception.type``/``.message``/``.stacktrace``
attributes for errors; ``traceId``/``spanId`` for correlation.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import orjson
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue

from logmind.ingestion.normalize import (
    InvalidEventError,
    RawEvent,
    clean_name,
    normalize_level,
    truncate,
)

REQUEST_ID_KEYS = ("request_id", "request.id", "http.request_id", "requestId", "x-request-id")


def _json_any(value: dict[str, Any] | None) -> Any:
    if not value:
        return None
    if "stringValue" in value:
        return value["stringValue"]
    if "boolValue" in value:
        return bool(value["boolValue"])
    if "intValue" in value:
        return int(value["intValue"])
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "arrayValue" in value:
        return [_json_any(v) for v in (value["arrayValue"] or {}).get("values", [])]
    if "kvlistValue" in value:
        return {
            kv["key"]: _json_any(kv.get("value"))
            for kv in (value["kvlistValue"] or {}).get("values", [])
        }
    if "bytesValue" in value:
        return value["bytesValue"]
    return None


def _proto_any(value: AnyValue) -> Any:
    kind = value.WhichOneof("value")
    if kind is None:
        return None
    if kind == "array_value":
        return [_proto_any(v) for v in value.array_value.values]
    if kind == "kvlist_value":
        return {kv.key: _proto_any(kv.value) for kv in value.kvlist_value.values}
    if kind == "bytes_value":
        return base64.b64encode(value.bytes_value).decode()
    return getattr(value, kind)


def _nanos(value: Any) -> datetime | None:
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(n / 1e9, UTC) if n > 0 else None


def _record_to_event(
    resource: dict[str, Any],
    attributes: dict[str, Any],
    *,
    time_ns: Any,
    observed_ns: Any,
    severity_number: int,
    severity_text: str,
    body: Any,
    trace_id: str,
    span_id: str,
    now: datetime,
    max_chars: int,
) -> RawEvent:
    ts = _nanos(time_ns) or _nanos(observed_ns) or now
    exc_type = str(attributes.pop("exception.type", "") or "")
    exc_message = str(attributes.pop("exception.message", "") or "")
    stack = str(attributes.pop("exception.stacktrace", "") or "")
    if isinstance(body, str):
        message = body
    elif body is None:
        message = exc_message or exc_type or ""
    else:
        message = orjson.dumps(body).decode()
    if not message:
        raise InvalidEventError("log record has no body")
    request_id = ""
    for key in REQUEST_ID_KEYS:
        if attributes.get(key):
            request_id = str(attributes[key])
            break
    env = resource.get("deployment.environment.name") or resource.get("deployment.environment")
    extra_resource = {
        k: v
        for k, v in resource.items()
        if k not in ("service.name", "deployment.environment", "deployment.environment.name")
    }
    if extra_resource:
        attributes = {**attributes, "resource": extra_resource}
    return RawEvent(
        timestamp=ts,
        level=normalize_level(severity_text, severity_number),
        message=truncate(message, max_chars),
        service=clean_name(str(resource.get("service.name") or ""), "unknown"),
        environment=clean_name(str(env or ""), "production"),
        host=clean_name(str(resource.get("host.name") or ""), "", 255),
        attributes=attributes,
        trace_id=trace_id.lower()[:64],
        span_id=span_id.lower()[:32],
        request_id=request_id[:128],
        exception_type=exc_type[:200],
        stack_trace=truncate(stack, max_chars * 4),
    )


Parsed = Iterator[tuple[int, RawEvent | InvalidEventError]]


def parse_json(body: bytes, *, now: datetime, max_chars: int) -> Parsed:
    try:
        doc = orjson.loads(body)
    except orjson.JSONDecodeError as exc:
        raise InvalidEventError("the body is not valid OTLP/JSON") from exc
    if not isinstance(doc, dict):
        raise InvalidEventError("the body is not an OTLP ExportLogsServiceRequest")
    index = 0
    for rl in doc.get("resourceLogs") or []:
        resource = {
            a["key"]: _json_any(a.get("value"))
            for a in (rl.get("resource") or {}).get("attributes") or []
        }
        for sl in rl.get("scopeLogs") or []:
            for rec in sl.get("logRecords") or []:
                try:
                    attrs = {
                        a["key"]: _json_any(a.get("value")) for a in rec.get("attributes") or []
                    }
                    yield (
                        index,
                        _record_to_event(
                            resource,
                            attrs,
                            time_ns=rec.get("timeUnixNano"),
                            observed_ns=rec.get("observedTimeUnixNano"),
                            severity_number=int(rec.get("severityNumber") or 0),
                            severity_text=str(rec.get("severityText") or ""),
                            body=_json_any(rec.get("body")),
                            trace_id=str(rec.get("traceId") or ""),
                            span_id=str(rec.get("spanId") or ""),
                            now=now,
                            max_chars=max_chars,
                        ),
                    )
                except (InvalidEventError, KeyError, TypeError, ValueError) as exc:
                    yield index, InvalidEventError(str(exc) or "malformed log record")
                index += 1


def parse_protobuf(body: bytes, *, now: datetime, max_chars: int) -> Parsed:
    request = ExportLogsServiceRequest()
    try:
        request.ParseFromString(body)
    except Exception as exc:  # protobuf raises DecodeError, a bare Exception subclass
        raise InvalidEventError("the body is not a valid OTLP protobuf message") from exc
    index = 0
    for rl in request.resource_logs:
        resource = {a.key: _proto_any(a.value) for a in rl.resource.attributes}
        for sl in rl.scope_logs:
            for rec in sl.log_records:
                try:
                    attrs = {a.key: _proto_any(a.value) for a in rec.attributes}
                    yield (
                        index,
                        _record_to_event(
                            resource,
                            attrs,
                            time_ns=rec.time_unix_nano,
                            observed_ns=rec.observed_time_unix_nano,
                            severity_number=int(rec.severity_number),
                            severity_text=rec.severity_text,
                            body=_proto_any(rec.body),
                            trace_id=rec.trace_id.hex(),
                            span_id=rec.span_id.hex(),
                            now=now,
                            max_chars=max_chars,
                        ),
                    )
                except InvalidEventError as exc:
                    yield index, exc
                index += 1
