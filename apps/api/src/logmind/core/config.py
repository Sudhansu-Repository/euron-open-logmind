"""Runtime configuration, validated once at boot.

Every setting comes from the environment, through this module only (section 2.1 of the
program's rules: no ``os.environ`` reads elsewhere). Security-relevant settings are
checked by ``Settings.guard`` so a misconfigured production deployment refuses to start
instead of running with demo secrets.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

INSECURE_SECRETS = {"", "change-me", "replace-with-output-of-make-env", "dev", "secret"}


def _insecure(value: str) -> bool:
    return value in INSECURE_SECRETS or "not-for-production" in value or len(value) < 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    environment: Literal["development", "test", "production"] = "development"
    cloud: Literal["local", "floci", "aws"] = Field("local", alias="LOGMIND_CLOUD")
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://logmind:logmind@localhost:6042/logmind"
    db_pool_size: int = 10
    db_max_overflow: int = 20

    redis_url: str = "redis://localhost:6079/0"

    # ClickHouse holds log_events, the one high-volume table (docs/PLAN.md). Credentials
    # ride as URL userinfo and the path is the database, the DATABASE_URL convention.
    clickhouse_url: str = "http://logmind:logmind@localhost:6023/logmind"
    clickhouse_timeout_s: float = Field(10.0, gt=0, le=120)

    # Signing secret for dashboard sessions and pepper for API key hashes. Separate values
    # so rotating sessions does not invalidate every project key.
    session_secret: str = "dev-session-secret-not-for-production"  # noqa: S105
    api_key_pepper: str = "dev-api-key-pepper-not-for-production"
    session_ttl_hours: int = 12
    cookie_secure: bool = False
    signup_enabled: bool = True
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:6010"]
    )
    public_url: str = "http://localhost:6010"

    # AI provider keys and alert channel secrets are sealed before storage.
    key_mode: Literal["local", "kms"] = "local"
    local_master_key: str = "dev-local-master-key-not-for-production"
    kms_key_id: str = "alias/logmind-local"

    aws_region: str = "us-east-1"
    aws_endpoint_url: str | None = None
    s3_force_path_style: bool = False
    # Investigation evidence packs live in object storage; rows keep only the key.
    storage: Literal["local", "s3"] = "local"
    evidence_bucket: str = "logmind-local-evidence"
    local_storage_dir: str = "./.data/evidence"

    # Alert email: "log" (in-memory outbox, tests), "smtp" (Mailpit locally), "ses" (AWS).
    mail_backend: Literal["log", "smtp", "ses"] = "log"
    mail_from: str = "LogMind Alerts <alerts@logmind.local>"
    smtp_host: str = "localhost"
    smtp_port: int = Field(1025, ge=1, le=65535)

    # Ingestion limits. A batch is one ClickHouse insert and one Postgres upsert.
    max_batch_events: int = Field(1000, ge=1, le=10_000)
    max_message_chars: int = Field(16_000, ge=256, le=1_000_000)
    max_body_bytes: int = Field(5_000_000, ge=10_000)
    # Ingestion accepts timestamps this far in the past (backfills) and future (skew).
    max_past_days: int = Field(30, ge=1, le=3650)
    max_future_minutes: int = Field(10, ge=0, le=1440)
    live_publish_per_batch: int = Field(200, ge=0, le=5000)

    # AI investigation budgets (A4): evidence selection and compression happen before any
    # prompt is built, and these bound what reaches the model.
    ai_max_evidence_items: int = Field(40, ge=5, le=400)
    ai_max_context_tokens: int = Field(3000, ge=500, le=100_000)
    ai_message_chars: int = Field(280, ge=80, le=4000)
    ai_default_window_minutes: int = Field(60, ge=5, le=1440)
    model_timeout_s: float = Field(120.0, gt=0, le=1800)
    # Model providers on private networks (a local Ollama or vLLM) are normal.
    provider_allow_private: bool = True

    # Config cache (API key lookup, project redaction settings): short in-process TTL
    # backed by a Redis version stamp.
    config_cache_ttl_s: float = 5.0
    # Dashboard aggregate response cache.
    rollup_cache_ttl_s: float = 10.0

    webhook_timeout_s: float = 10.0
    login_attempts_per_minute: int = Field(10, ge=1, le=1000)

    otel_enabled: bool = False

    # HTTP server: keep idle connections open longer than the load balancer does (the ALB
    # idle timeout is 300 s on AWS), or a reused connection can meet a closed socket (502).
    http_keep_alive_s: int = Field(5, ge=1, le=3600)
    # Proxies whose X-Forwarded-For is trusted: the Compose network locally, the VPC CIDR
    # on AWS. The login rate limit keys on the client address, so this must not be "*"
    # where clients can reach the api directly.
    forwarded_allow_ips: str = "127.0.0.1"

    # The worker: investigation jobs are polled every ``worker_poll_interval_s``; alert
    # rules are evaluated every ``alert_interval_s``; retention runs every hour.
    worker_poll_interval_s: float = Field(1.0, gt=0, le=60)
    alert_interval_s: float = Field(30.0, gt=0, le=3600)
    retention_interval_s: float = Field(3600.0, gt=0)
    worker_metrics_port: int = Field(9464, ge=0, le=65535)
    job_lease_s: float = Field(300.0, ge=10, le=3600)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    def guard(self) -> None:
        """Refuse to boot in production with demo secrets or unsafe options."""
        if self.environment != "production":
            return
        problems: list[str] = []
        for name in ("session_secret", "api_key_pepper"):
            if _insecure(getattr(self, name)):
                problems.append(f"{name.upper()} must be a random value of at least 32 chars")
        if self.session_secret == self.api_key_pepper:
            problems.append("SESSION_SECRET and API_KEY_PEPPER must differ")
        if self.key_mode == "local" and _insecure(self.local_master_key):
            problems.append("LOCAL_MASTER_KEY must be set (or use KEY_MODE=kms)")
        if self.cloud == "aws" and self.aws_endpoint_url:
            problems.append("AWS_ENDPOINT_URL must be unset when LOGMIND_CLOUD=aws")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true in production")
        if "*" in self.cors_origins:
            problems.append("CORS_ORIGINS must list the dashboard's origins, not *")
        if self.mail_backend == "log":
            problems.append("MAIL_BACKEND must be smtp or ses in production")
        if self.storage == "local":
            problems.append("STORAGE must be s3 in production (replicas share evidence packs)")
        if problems:
            raise RuntimeError("unsafe production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.guard()
    return settings
