"""Application settings: environment variables (prefix NOTES_) and an optional .env file."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_SECRETS = {"", "change-me"}
MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    """Every configurable value of the Notes API, validated once at startup."""

    model_config = SettingsConfigDict(
        env_prefix="NOTES_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Notes API"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    cors_origins: list[str] = ["http://localhost:5173"]
    max_upload_bytes: int = Field(default=1_048_576, gt=0)
    http_timeout_seconds: float = Field(default=5.0, gt=0)
    database_url: SecretStr = SecretStr("postgresql+asyncpg://notes:notes@localhost:5432/notes")
    database_echo: bool = False  # log every SQL statement (development only)
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)
    database_pgbouncer: bool = False  # behind PgBouncer (transaction pooling): no statement cache
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")

    # Authentication: an HS256 secret (required in production; a random one per process otherwise)
    jwt_secret: SecretStr | None = None
    jwt_issuer: str = "notes-api"
    jwt_audience: str = "notes-api"
    access_token_minutes: int = Field(default=15, ge=1)
    refresh_token_days: int = Field(default=14, ge=1)
    password_time_cost: int = Field(default=3, ge=1)  # Argon2id parameters (tests lower them)
    password_memory_kib: int = Field(default=65_536, ge=32)  # Argon2 needs 8 KiB per lane (4)
    admin_emails: list[str] = []  # these addresses get the admin role when they register
    login_rate_limit: int = Field(default=5, ge=1)  # attempts per window, per IP + email
    login_rate_window_seconds: int = Field(default=60, ge=1)
    cookie_secure: bool = True  # session cookie only over HTTPS (False for local HTTP)

    # Third-party login (OpenID Connect, Authorization Code + PKCE); disabled until configured
    oauth_client_id: str | None = None
    oauth_client_secret: SecretStr | None = None
    oauth_authorize_url: str | None = None
    oauth_token_url: str | None = None
    oauth_jwks_url: str | None = None
    oauth_issuer: str | None = None
    oauth_redirect_url: str = "http://localhost:8000/api/v1/auth/oauth/callback"

    # Background work, real time and caching (Unit 6.6)
    webhook_timeout_seconds: float = Field(default=5.0, gt=0)
    webhook_max_attempts: int = Field(default=5, ge=1)  # then the event is dead-lettered
    cache_ttl_seconds: int = Field(default=60, ge=1)
    ws_heartbeat_seconds: float = Field(default=20.0, gt=0)
    export_ttl_seconds: int = Field(default=3600, ge=60)

    # Observability (Unit 6.7)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = True  # one JSON object per line; False: coloured console output
    metrics_enabled: bool = (
        True  # GET /metrics (keep it off the public internet: the proxy blocks it)
    )
    otel_exporter: Literal["none", "console", "otlp", "memory"] = "none"
    otel_endpoint: str = "http://localhost:4318/v1/traces"  # OTLP over HTTP (a collector)
    sentry_dsn: SecretStr | None = None  # error tracking is off unless a DSN is configured
    check_migrations: bool = True  # /health/startup: the database must be at the newest revision

    @property
    def oauth_enabled(self) -> bool:
        """True when every OpenID Connect setting is present."""
        required = (self.oauth_client_id, self.oauth_authorize_url, self.oauth_token_url)
        return all(required) and bool(self.oauth_jwks_url and self.oauth_issuer)

    @model_validator(mode="after")
    def require_real_secrets_in_production(self) -> Settings:
        """Refuse to start in production with a missing or weak JWT secret or insecure cookies."""
        if self.environment != "production":
            return self
        secret = None if self.jwt_secret is None else self.jwt_secret.get_secret_value()
        if secret is None or secret in PLACEHOLDER_SECRETS or len(secret) < MIN_JWT_SECRET_LENGTH:
            raise ValueError(
                f"NOTES_JWT_SECRET must be a random secret of at least {MIN_JWT_SECRET_LENGTH} "
                "characters in production"
            )
        if not self.cookie_secure:
            raise ValueError("NOTES_COOKIE_SECURE must be true in production")
        return self


SECRETS_DIR = Path("/run/secrets")  # where Docker, Compose and Kubernetes mount secret files


@lru_cache
def get_settings() -> Settings:
    """The process-wide settings, read once and cached (12-factor: config from the environment).

    Order of precedence: environment variables, then .env, then secret files in /run/secrets
    (a file named notes_jwt_secret holds NOTES_JWT_SECRET), then the defaults.
    """
    if SECRETS_DIR.is_dir():
        return Settings(_secrets_dir=SECRETS_DIR)  # type: ignore[call-arg]  # a pydantic-settings init option
    return Settings()
