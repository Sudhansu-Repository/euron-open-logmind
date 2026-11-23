# OpenTelemetry Python to LogMind

An app that already uses OpenTelemetry does not need the LogMind SDK: LogMind serves the
standard OTLP/HTTP logs path, so the stock `OTLPLogExporter` can post to it directly.
[`app.py`](app.py) sets up a `LoggerProvider` with a `BatchLogRecordProcessor`, points
the exporter at `http://localhost:6030/v1/logs` with the project API key in the
`Authorization` header, and bridges stdlib `logging` through OpenTelemetry's
`LoggingHandler`.

```bash
cd examples/otel-python
pip install -r requirements.txt     # or: uv pip install -r requirements.txt
export LOGMIND_API_KEY=lmk_...      # a project API key from the dashboard
export LOGMIND_OTLP_ENDPOINT=http://localhost:6030/v1/logs   # optional, this is the default
python app.py
```

The exporter part is just this:

```python
exporter = OTLPLogExporter(
    endpoint="http://localhost:6030/v1/logs",
    headers={"Authorization": f"Bearer {api_key}"},
)
provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
```

The same works without code changes through the standard OpenTelemetry env vars, for
example with auto-instrumentation:

```bash
export OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://localhost:6030/v1/logs
export OTEL_EXPORTER_OTLP_LOGS_HEADERS="Authorization=Bearer lmk_..."
export OTEL_EXPORTER_OTLP_LOGS_PROTOCOL=http/protobuf
```

Unlike the LogMind SDKs, the OpenTelemetry exporter retries an unreachable endpoint in
the foreground of `force_flush`, so with no API running the script waits on those retries
for a while before it prints `could not export` and exits with status 1. Start the stack
first.

What to look for in the dashboard afterwards: three records from service
`inventory-api` (taken from the `service.name` resource attribute), sharing one `run_id`
attribute, the last one at level `error` with the `KeyError` exception and traceback
carried in OpenTelemetry's `exception.*` attributes.
