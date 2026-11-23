"""Application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from logmind import __version__
from logmind.alerts.router import router as alerts_router
from logmind.analytics.router import router as analytics_router
from logmind.audit.router import router as audit_router
from logmind.auth.router import router as auth_router
from logmind.auth.router import users_router
from logmind.core.config import Settings, get_settings
from logmind.core.container import Container
from logmind.core.errors import install_error_handlers
from logmind.core.logs import configure_logging
from logmind.core.middleware import RequestContextMiddleware
from logmind.core.tracing import configure_tracing
from logmind.errors.router import router as errors_router
from logmind.health.router import router as health_router
from logmind.ingestion.router import router as ingestion_router
from logmind.investigations.router import router as investigations_router
from logmind.logs.router import router as logs_router
from logmind.orgs.router import router as orgs_router
from logmind.projects.router import environments_router
from logmind.projects.router import keys_router as api_keys_router
from logmind.projects.router import router as projects_router
from logmind.providers.router import router as providers_router
from logmind.services.router import router as services_router

DESCRIPTION = """
A self-hosted log intelligence platform. Send logs over HTTP, with the Python or Node.js
SDK, or from any OpenTelemetry SDK or Collector (OTLP/HTTP, protobuf or JSON); search them,
watch them live, see errors grouped by fingerprint, and ask an AI investigator why
something broke. Every claim in an investigation report cites real stored log lines,
which `GET /api/v1/ai/investigations/{id}/verify` re-reads and checks.

Ingestion (`POST /api/v1/logs`, `POST /api/v1/logs/batch`, `POST /v1/logs`) authenticates
with a project API key (`Authorization: Bearer lmk_<prefix>_<secret>`). Everything else
under `/api/v1` is the dashboard API behind a session (`POST /api/v1/auth/login`).
"""


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    configure_tracing(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container or Container.build(settings)
        try:
            yield
        finally:
            if container is None:
                await app.state.container.close()

    app = FastAPI(
        title="Euron Open LogMind",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    install_error_handlers(app)
    for router in (
        health_router,
        auth_router,
        users_router,
        orgs_router,
        projects_router,
        environments_router,
        api_keys_router,
        ingestion_router,
        logs_router,
        errors_router,
        services_router,
        analytics_router,
        investigations_router,
        providers_router,
        alerts_router,
        audit_router,
    ):
        app.include_router(router)

    app.add_middleware(GZipMiddleware, minimum_size=2048)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "authorization",
            "content-type",
            "content-encoding",
            "x-api-key",
            "x-logmind-sdk",
            "x-request-id",
        ],
        expose_headers=["x-request-id"],
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware)
    return app
