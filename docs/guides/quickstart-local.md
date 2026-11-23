# Quickstart (local)

Requirements: Docker with about 4 GB of memory for the stack. Nothing else runs on the host;
uv and pnpm are only needed to run tests outside containers.

```bash
git clone https://github.com/euron-sde-team/euron-open-logmind
cd euron-open-logmind
make up      # builds the images, starts Postgres, Redis, ClickHouse, Mailpit, Floci, the mock
             # AI service; applies the local-floci Terraform; migrates; starts api, worker, web
make demo    # Lumen Retail: 24 h of logs, an incident, alert rules, an AI investigation
```

Open http://localhost:6010 and sign in as `owner@lumen.example` with `Demo-Owner-Pass-1`.

| URL | What |
| --- | --- |
| http://localhost:6010 | Dashboard |
| http://localhost:6030/docs | API reference (OpenAPI) |
| http://localhost:6025 | Mailpit: alert emails |
| http://localhost:6050/hooks/slack-oncall | What the demo's Slack target received |

## Send your own logs

Create a project and a key in Settings, then:

```bash
export LOGMIND_API_KEY=lmk_...
curl -X POST http://localhost:6030/api/v1/logs \
  -H "Authorization: Bearer $LOGMIND_API_KEY" -H "content-type: application/json" \
  -d '{"message": "payment declined for order 42", "level": "warn", "service": "checkout"}'
```

Python: `pip install ./sdks/python`, then

```python
from euron_logmind import LogMind
log = LogMind(api_key="lmk_...", endpoint="http://localhost:6030", service="checkout")
log.error("charge failed", order_id="o-42")
log.close()
```

OpenTelemetry: point any OTLP/HTTP exporter at `http://localhost:6030` with the header
`Authorization: Bearer lmk_...` (see `examples/otel-collector`).

## Stop

```bash
make down    # stops everything and deletes its data
```
