#!/usr/bin/env bash
# Run the API integration suite under every backend combination LogMind supports:
#
#   evidence storage:  local disk          | S3 on Floci
#   key sealing:       local AES-256-GCM   | KMS on Floci
#
# 2 x 2 = 4 runs, passed to the suite as STORAGE and KEY_MODE. Needs Floci with the
# local-floci Terraform applied (make up) for the S3 and KMS runs. Each combination gets
# its own Postgres and ClickHouse test databases, so a run never reuses another's state.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/deploy/compose/.env"
port() { local v; v="$(grep -s "^$1=" "$ENV_FILE" | cut -d= -f2 || true)"; echo "${v:-$2}"; }
FLOCI_URL="http://localhost:$(port LM_FLOCI_PORT 6066)"
PG="postgresql+asyncpg://logmind:logmind@localhost:$(port LM_PG_PORT 6042)"
CH="http://logmind:logmind@localhost:$(port LM_CLICKHOUSE_PORT 6023)"

if ! curl -sf -o /dev/null "$FLOCI_URL/"; then
  echo "Floci is not reachable at $FLOCI_URL. Start the stack first: make up" >&2
  exit 1
fi
"$ROOT/scripts/test-db.sh"

export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_REGION=us-east-1
export KMS_KEY_ID=alias/logmind-local EVIDENCE_BUCKET=logmind-local-evidence
export TEST_REDIS_URL="redis://localhost:$(port LM_REDIS_PORT 6079)/14"
export TEST_SMTP_PORT="$(port LM_SMTP_PORT 6026)"
export TEST_MAILPIT_URL="http://localhost:$(port LM_MAILPIT_PORT 6025)"
failed=()
runs=0
for storage in local s3; do
  for keys in local kms; do
    runs=$((runs + 1))
    echo
    echo "== storage=$storage keys=$keys"
    endpoint=""
    [[ "$storage" == s3 || "$keys" == kms ]] && endpoint="$FLOCI_URL"
    if ! (cd "$ROOT/apps/api" && STORAGE=$storage KEY_MODE=$keys AWS_ENDPOINT_URL="$endpoint" \
          TEST_DATABASE_URL="$PG/logmind_test_matrix_${storage}_${keys}" \
          TEST_CLICKHOUSE_URL="$CH/logmind_test_matrix_${storage}_${keys}" \
          uv run pytest tests/integration -m integration -q -p no:warnings -rf); then
      failed+=("storage=$storage keys=$keys")
    fi
  done
done
echo
if ((${#failed[@]})); then
  printf 'matrix: FAILED for %s\n' "${failed[@]}"
  exit 1
fi
echo "matrix: all $runs combinations passed"
