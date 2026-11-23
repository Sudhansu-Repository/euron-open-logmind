# Python SDK

The full reference is [sdks/python/README.md](../../sdks/python/README.md).

```bash
pip install ./sdks/python        # euron-logmind
```

```python
import logging
from euron_logmind import LogMind, LogMindHandler

log = LogMind(api_key="lmk_...", endpoint="http://localhost:6030", service="checkout",
              environment="production")
log.info("order placed", order_id="o-42")
try:
    charge()
except Exception:
    log.exception("charge failed")        # type, message and traceback

logging.getLogger().addHandler(LogMindHandler(log))   # or route stdlib logging
log.close()
```

Lines are batched on a background thread and sent to `POST /api/v1/logs/batch`; failures are
retried with backoff and never raised into your application.
