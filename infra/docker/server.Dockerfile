# syntax=docker/dockerfile:1.7
# ─────────────────────────────────────────────────────────────────────────────
# The server image: the API, the background worker, the CLI and the mock AI/LLM
# service (one image, one entrypoint):
#   docker build -f infra/docker/server.Dockerfile --target server -t logmind-server apps/api
#
#   logmind serve         the API (default command)
#   logmind worker        background jobs: AI investigations, alert rule evaluation,
#                         hourly retention
#   logmind migrate       Postgres migrations (Alembic), then the ClickHouse schema
#   logmind create-admin  create the first organisation and owner
#   logmind seed-demo     seed realistic demo data
#   logmind openapi       print the OpenAPI document
#   uvicorn mockai.app:app      mock model and LLM provider stand-in for the SDKs and e2e
# ─────────────────────────────────────────────────────────────────────────────
ARG PYTHON_IMAGE=python:3.12.13-slim-bookworm

FROM ghcr.io/astral-sh/uv:0.11.19 AS uv

FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /uvx /bin/
# Fewer parallel downloads and patient reads, so a slow link finishes each wheel instead
# of stalling every stream past the timeout (override with --build-arg).
ARG UV_CONCURRENT_DOWNLOADS=4
ARG UV_HTTP_TIMEOUT=300
# Bytecode is compiled here because the runtime root filesystem is read-only.
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv UV_HTTP_RETRIES=8
WORKDIR /src
# Dependencies first (cached until uv.lock changes), then the project itself. --locked
# fails the build if uv.lock is out of date with pyproject.toml instead of re-resolving.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project
COPY pyproject.toml uv.lock README.md* ./
COPY src src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

FROM ${PYTHON_IMAGE} AS server
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=UTC PORT=8080 \
    HOME=/app
# /data/evidence is owned by the app user so a named volume mounted there (Compose,
# STORAGE=local) inherits that ownership.
# tini reaps zombies and forwards SIGTERM, so services drain and finish in-flight work.
RUN apt-get update && apt-get install -y --no-install-recommends tini ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 logmind \
 && useradd --system --uid 10001 --gid logmind --home-dir /app --no-create-home \
      --shell /usr/sbin/nologin logmind \
 && mkdir -p /app /data/evidence \
 && chown -R logmind:logmind /app /data/evidence
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
USER 10001:10001
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=3 \
  CMD python -c "import os, sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT', '8080'), timeout=2).status == 200 else 1)"
ENTRYPOINT ["/usr/bin/tini", "--", "logmind"]
EXPOSE 8080 9464
CMD ["serve", "--host", "0.0.0.0", "--port", "8080"]
