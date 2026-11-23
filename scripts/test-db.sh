#!/usr/bin/env bash
# Make sure the services the integration suite talks to are reachable: Postgres, Redis,
# ClickHouse and Mailpit.
# Reuses the Compose services when the stack is up; otherwise starts just those. Tests
# never use a host-installed Postgres or Redis.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/deploy/compose/.env"
port() { local v; v="$(grep -s "^$1=" "$ENV_FILE" | cut -d= -f2 || true)"; echo "${v:-$2}"; }

ready() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

missing=()
ready "$(port LM_PG_PORT 6042)" || missing+=(postgres)
ready "$(port LM_REDIS_PORT 6079)" || missing+=(redis)
ready "$(port LM_SMTP_PORT 6026)" || missing+=(mailpit)
ready "$(port LM_CLICKHOUSE_PORT 6023)" || missing+=(clickhouse)
((${#missing[@]})) || exit 0

"$ROOT/scripts/gen-local-env.sh" >/dev/null
echo "starting ${missing[*]}"
docker compose --env-file "$ENV_FILE" -f "$ROOT/deploy/compose/compose.yaml" \
  up -d --wait "${missing[@]}"
