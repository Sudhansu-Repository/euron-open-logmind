# Quickstart (Python)

Sends a few structured lines, one handled exception (with its type, message and
traceback as a structured field) and one record through the stdlib `logging` handler,
then prints what the API accepted.

```bash
cd examples/python-quickstart
pip install -e ../../sdks/python     # or: uv pip install -e ../../sdks/python
export LOGMIND_ENDPOINT=http://localhost:6030   # optional, this is the default
export LOGMIND_API_KEY=lmk_...                  # a project API key from the dashboard
python quickstart.py
```

Expected output against a running stack (`make up` in the project root):

```
send_batch: accepted=1 event_ids=['...']
background: drained=True accepted=5 dropped=0
search the dashboard for run_id:1a2b3c4d
```

With no API running the script still finishes: the background lines are dropped with
one `[euron-logmind]` warning on stderr and `send_batch` reports the failure, because
a logging SDK never crashes the application it runs in.

What to look for in the dashboard afterwards:

- Five lines from service `checkout`, environment `development`, sharing one `run_id`.
- `payment failed` at level `error` with a `TimeoutError` exception and its traceback,
  grouped into an error group.
- `label printed for order 42` with `logger: checkout.shipping` and `carrier` attributes,
  sent by the stdlib handler.
