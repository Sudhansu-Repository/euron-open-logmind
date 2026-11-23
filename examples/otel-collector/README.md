# OpenTelemetry Collector to LogMind

[`otelcol.yaml`](otelcol.yaml) is a complete Collector pipeline that ships logs to
LogMind over OTLP/HTTP. LogMind serves the standard OTLP logs path `/v1/logs` (protobuf
or JSON, optionally gzip), so the stock `otlphttp` exporter needs only the endpoint and
the project API key:

```yaml
exporters:
  otlphttp/logmind:
    logs_endpoint: http://localhost:6030/v1/logs
    headers:
      Authorization: "Bearer ${env:LOGMIND_API_KEY}"
```

Two receivers feed it:

- `otlp` on `:4317` (gRPC) and `:4318` (HTTP), for any app instrumented with an
  OpenTelemetry SDK (see [`../otel-python`](../otel-python) for one that talks to
  LogMind directly instead).
- `filelog`, tailing [`sample/app.jsonl`](sample/app.jsonl): each JSON line is parsed, its
  `level` becomes the record's severity, `msg` the body, an optional `time` key the
  timestamp (lines without one get the time they were read, which keeps the sample
  inside LogMind's 30 day acceptance window), and every other key (`invoice_id`,
  `attempt` ...) becomes an attribute. A `resource`
  processor tags the file's lines with `service.name=billing-worker`.

## Run it

With the Collector contrib binary (the `filelog` receiver is in contrib):

```bash
cd examples/otel-collector
export LOGMIND_API_KEY=lmk_...     # a project API key from the dashboard
otelcol-contrib --config otelcol.yaml
```

Or in Docker. Inside a container `localhost` is the container itself, so change
`logs_endpoint` to `http://host.docker.internal:6030/v1/logs` first (Docker Desktop; on
Linux add `--add-host=host.docker.internal:host-gateway`):

```bash
docker run --rm -e LOGMIND_API_KEY \
  -v "$PWD/otelcol.yaml:/etc/otelcol-contrib/config.yaml:ro" \
  -v "$PWD/sample:/sample:ro" -w / \
  otel/opentelemetry-collector-contrib:0.115.1
```

The five sample lines appear in the dashboard under service `billing-worker` within a
few seconds; the `email delivery failed` line is an error and lands in an error group.

## Pointing a real app at it

Replace `include: [./sample/*.jsonl]` with your own paths (for example
`/var/log/myapp/*.log`), adjust the `json_parser` (or use `regex_parser` for plain text
lines) and set `service.name` to your service. Every app already exporting OTLP can
instead target the Collector at `http://<collector>:4318`, or skip the Collector and
send to LogMind's `/v1/logs` directly.
