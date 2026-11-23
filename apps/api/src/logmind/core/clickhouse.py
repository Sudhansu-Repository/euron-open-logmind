"""ClickHouse over its HTTP interface: the store for ``log_events`` (docs/PLAN.md).

ClickHouse is the source of truth for log lines; Postgres holds every relational row
(organisations, projects, error groups, investigations). This client is deliberately thin:
parameterised queries (ClickHouse's own ``{name:Type}`` placeholders, sent as
``param_<name>``, so a value is never spliced into SQL text), JSONEachRow inserts into an
allowlisted set of tables, and DDL for the schema runner. Tenant scoping is not done here
but one layer up, in ``logs/repository.py``, which is the only module that builds log
queries and always adds the org and project filter.

A failure (connection refused, timeout, a non-200 answer) raises
:class:`ClickHouseError`, which ``core/errors.py`` maps to a 503 with an actionable
message: unlike an optional accelerator, logs cannot be served from anywhere else.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx
import orjson

log = logging.getLogger("logmind.clickhouse")

# The only tables rows are ever inserted into; checked before the table name is
# interpolated (table identifiers cannot be bound as parameters).
INSERTABLE_TABLES = frozenset({"log_events"})


class ClickHouseError(Exception):
    """ClickHouse could not be reached or refused the statement."""


def ch_datetime(value: datetime) -> str:
    """ClickHouse's DateTime64 text form. Every timestamp here is UTC, so the offset is
    converted, then dropped (``isoformat()``'s ``T`` and ``+00:00`` fail to parse)."""
    if value.tzinfo is not None:
        value = value.astimezone(UTC)
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")


def parse_ch_datetime(value: str) -> datetime:
    """The inverse of :func:`ch_datetime` for values read back with FORMAT JSON."""
    text = value.replace("T", " ").rstrip("Z")
    fmt = "%Y-%m-%d %H:%M:%S.%f" if "." in text else "%Y-%m-%d %H:%M:%S"
    return datetime.strptime(text, fmt).replace(tzinfo=UTC)


def _quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def format_param(value: Any) -> str:
    """A Python value as ClickHouse's HTTP parameter text for its declared type."""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, datetime):
        return ch_datetime(value)
    if isinstance(value, list | tuple):
        return "[" + ",".join(_quote(str(v)) for v in value) + "]"
    return str(value)


class ClickHouse:
    """One pooled HTTP client per process. ``clickhouse_url`` carries the user and
    password as URL userinfo and the database as its path, never logged."""

    def __init__(self, url: str, *, timeout_s: float = 10.0) -> None:
        parsed = httpx.URL(url)
        self.database = parsed.path.strip("/") or "default"
        self._base = str(parsed.copy_with(userinfo=b"", path="/"))
        auth = (parsed.username, parsed.password) if parsed.username else None
        self._client = httpx.AsyncClient(
            base_url=self._base,
            auth=auth,
            timeout=httpx.Timeout(timeout_s, connect=3.0),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def ping(self) -> bool:
        try:
            resp = await self._client.get("/ping")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def _post(
        self, sql: bytes | str, params: dict[str, str], *, database: bool = True
    ) -> httpx.Response:
        query: dict[str, str] = dict(params)
        if database:
            query["database"] = self.database
        try:
            resp = await self._client.post("/", params=query, content=sql)
        except httpx.HTTPError as exc:
            raise ClickHouseError(f"ClickHouse is unreachable: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise ClickHouseError(f"ClickHouse refused the statement: {resp.text[:300]}")
        return resp

    async def command(self, sql: str, *, database: bool = True) -> None:
        """DDL and mutations (no result set)."""
        await self._post(sql, {}, database=database)

    async def query_command(self, sql: str, params: dict[str, Any]) -> None:
        """A parameterised statement with no result set (lightweight deletes)."""
        bound = {f"param_{k}": format_param(v) for k, v in params.items()}
        await self._post(sql, bound)

    async def insert(self, table: str, rows: list[dict[str, Any]]) -> None:
        if table not in INSERTABLE_TABLES:
            raise ValueError(f"not an insertable table: {table!r}")
        if not rows:
            return
        body = b"\n".join(orjson.dumps(row) for row in rows)
        # The INSERT statement rides in the URL; the rows are the body.
        await self._post(
            body,
            {
                "query": f"INSERT INTO {table} FORMAT JSONEachRow",
                "date_time_input_format": "best_effort",
            },
        )

    async def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Rows as dicts. ``sql`` uses ``{name:Type}`` placeholders bound from ``params``;
        the statement must not carry its own FORMAT clause."""
        bound = {f"param_{k}": format_param(v) for k, v in (params or {}).items()}
        bound["output_format_json_quote_64bit_integers"] = "0"
        resp = await self._post(sql + "\nFORMAT JSON", bound)
        data = orjson.loads(resp.content)
        rows: list[dict[str, Any]] = data.get("data", [])
        return rows
