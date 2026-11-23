# Examples

Each example sends logs to a local LogMind API (`make up` in the project root, API on
`http://localhost:6030`) and is configured only through environment variables, so no
`.env` file is needed.

| Example | Shows |
| --- | --- |
| [python-quickstart](python-quickstart/) | the Python SDK: structured lines, a handled exception with its traceback, the stdlib `logging` handler, and `send_batch` returning the `IngestResult` |
| [node-quickstart](node-quickstart/) | the Node.js SDK: structured lines, `captureException` with the `cause` chain, and `sendBatch` |
| [otel-collector](otel-collector/) | an OpenTelemetry Collector config: OTLP and `filelog` receivers, `otlphttp` exporter to LogMind's `/v1/logs` |
| [otel-python](otel-python/) | the OpenTelemetry Python SDK exporting logs straight to LogMind with `OTLPLogExporter` |

## Credentials

Create a project in the dashboard, copy its API key (`lmk_<prefix>_<secret>`, shown once)
and export it:

```bash
export LOGMIND_API_KEY=lmk_...
export LOGMIND_ENDPOINT=http://localhost:6030   # optional, this is the default
```

The SDK examples also run with no API up: lines are dropped with a single warning on
stderr, never an exception, because a logging SDK must not break the application it runs
in.
