# Quickstart (Node.js)

Sends a few structured lines and one captured exception (`err.name`, `err.message` and
`err.stack`, with the `cause` chain appended), then prints what the API accepted.

```bash
cd examples/node-quickstart
pnpm --dir ../../sdks/node install && pnpm --dir ../../sdks/node run build
pnpm install                                    # links @euron/logmind from ../../sdks/node
export LOGMIND_ENDPOINT=http://localhost:6030   # optional, this is the default
export LOGMIND_API_KEY=lmk_...                  # a project API key from the dashboard
pnpm start
```

Expected output against a running stack (`make up` in the project root):

```
sendBatch: accepted=1 eventIds=["..."]
background: drained=true accepted=4 dropped=0
search the dashboard for runId:1a2b3c4d
```

With no API running the script still finishes: the background lines are dropped with
one `[euron-logmind]` warning on stderr and `sendBatch` reports the failure. The SDK's
flush timer is unref'd, so it never keeps a finished script alive.

What to look for in the dashboard afterwards:

- Four lines from service `checkout`, environment `development`, sharing one `runId`.
- `payment failed` at level `error` with an `Error` exception whose stack ends in
  `Caused by: Error: ETIMEDOUT`, grouped into an error group.
