"""Application settings: environment variables (prefix NOTES_) and an optional .env file."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_KEYS = {"", "change-me"}


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
    api_key: SecretStr | None = None  # the admin router answers 503 until it is set
    cors_origins: list[str] = ["http://localhost:5173"]
    max_upload_bytes: int = Field(default=1_048_576, gt=0)
    http_timeout_seconds: float = Field(default=5.0, gt=0)
    database_url: SecretStr = SecretStr("postgresql+asyncpg://notes:notes@localhost:5432/notes")
    database_echo: bool = False  # log every SQL statement (development only)
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)

    @model_validator(mode="after")
    def require_real_key_in_production(self) -> Settings:
        """Refuse to start in production without a real API key."""
        key = None if self.api_key is None else self.api_key.get_secret_value()
        if self.environment == "production" and (key is None or key in PLACEHOLDER_KEYS):
            raise ValueError("NOTES_API_KEY must be set to a real secret in production")
        return self


@lru_cache
def get_settings() -> Settings:
    """The process-wide settings, read from the environment once and then cached."""
    return Settings()
