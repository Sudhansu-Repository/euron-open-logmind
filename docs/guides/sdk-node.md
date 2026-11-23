# Node.js SDK

The full reference is [sdks/node/README.md](../../sdks/node/README.md).

```js
import { LogMind } from "@euron/logmind";

const log = new LogMind({ apiKey: process.env.LOGMIND_API_KEY, endpoint: "http://localhost:6030", service: "search" });
log.info("query served", { route: "/search", ms: 42 });
try {
  render();
} catch (err) {
  log.captureException(err, { route: "/search" });
}
await log.close();
```

Zero runtime dependencies, Node 18 or newer. Batches are flushed on a timer that never keeps
the process alive and once more before exit.
