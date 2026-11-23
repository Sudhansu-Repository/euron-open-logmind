# logmind (apps/api)

The FastAPI backend for Euron Open LogMind. See the project root README and
`docs/` for the product-level documentation; this package's own docstrings (start at
`src/logmind/main.py`) document the code layout.

## Quickstart

```bash
uv sync
uv run logmind migrate
uv run logmind serve
```

## Tests

```bash
uv run pytest tests/unit
uv run pytest tests/integration   # needs Postgres and Redis, see tests/integration/conftest.py
```
