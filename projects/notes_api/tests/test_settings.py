"""pydantic-settings: environment variables, .env files, secrets and production rules."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from notes_api.core.config import Settings, get_settings

STRONG_SECRET = "x" * 40


def test_environment_variables_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """NOTES_* variables are read and converted (JSON for lists)."""
    monkeypatch.setenv("NOTES_DEBUG", "true")
    monkeypatch.setenv("NOTES_CORS_ORIGINS", '["https://a.example", "https://b.example"]')
    monkeypatch.setenv("NOTES_ACCESS_TOKEN_MINUTES", "5")
    settings = Settings(_env_file=None)
    assert (settings.debug, settings.cors_origins, settings.access_token_minutes) == (
        True,
        ["https://a.example", "https://b.example"],
        5,
    )


def test_env_file_is_read_and_variables_win(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A .env file supplies values; a real environment variable overrides it."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "NOTES_APP_NAME=From file\nNOTES_JWT_SECRET=file-secret\n", encoding="utf-8"
    )
    monkeypatch.setenv("NOTES_JWT_SECRET", "env-secret")
    settings = Settings(_env_file=env_file)
    assert settings.app_name == "From file"
    assert (
        settings.jwt_secret is not None and settings.jwt_secret.get_secret_value() == "env-secret"
    )


def test_secrets_are_hidden_in_repr_and_dumps() -> None:
    """SecretStr never shows its value unless asked explicitly."""
    settings = Settings(_env_file=None, jwt_secret="s3cret-value")
    assert "s3cret-value" not in repr(settings)
    assert settings.model_dump(mode="json")["jwt_secret"] == "**********"
    assert "notes:notes@" not in repr(settings)  # the database password is a secret too


@pytest.mark.parametrize("secret", [None, "change-me", "too-short"])
def test_production_needs_a_strong_jwt_secret(secret: str | None) -> None:
    """Missing, placeholder or short secrets stop a production app from starting."""
    with pytest.raises(ValidationError, match="NOTES_JWT_SECRET"):
        Settings(_env_file=None, environment="production", jwt_secret=secret)


def test_production_needs_secure_cookies() -> None:
    """Session cookies must be HTTPS-only in production."""
    with pytest.raises(ValidationError, match="NOTES_COOKIE_SECURE"):
        Settings(
            _env_file=None, environment="production", jwt_secret=STRONG_SECRET, cookie_secure=False
        )


def test_oauth_is_enabled_only_when_fully_configured() -> None:
    """Every OpenID Connect setting must be present."""
    partial = Settings(_env_file=None, oauth_client_id="notes")
    assert partial.oauth_enabled is False
    full = partial.model_copy(
        update={
            "oauth_authorize_url": "https://id.example/authorize",
            "oauth_token_url": "https://id.example/token",
            "oauth_jwks_url": "https://id.example/jwks",
            "oauth_issuer": "https://id.example",
        }
    )
    assert full.oauth_enabled is True


def test_get_settings_is_cached() -> None:
    """The settings reader builds Settings once per process."""
    get_settings.cache_clear()
    assert get_settings() is get_settings()
    get_settings.cache_clear()
