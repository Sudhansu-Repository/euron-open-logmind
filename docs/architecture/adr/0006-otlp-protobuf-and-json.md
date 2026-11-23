# 0006: OTLP/HTTP in both encodings at the standard path

**Status:** accepted

OpenTelemetry exporters and the Collector's `otlphttp` exporter default to protobuf, often
gzip compressed, and append `/v1/logs` to the configured endpoint. LogMind accepts protobuf
(decoded with the official `opentelemetry-proto` classes) and JSON at `/v1/logs`, gzip or
deflate, so pointing an exporter at the API's base URL works with no adapter (A6). gRPC is
roadmap.
