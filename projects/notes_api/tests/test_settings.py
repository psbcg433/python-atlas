"""pydantic-settings: environment variables, .env files, secrets and validation."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from notes_api.core.config import Settings, get_settings


def test_environment_variables_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """NOTES_* variables are read and converted (JSON for lists)."""
    monkeypatch.setenv("NOTES_DEBUG", "true")
    monkeypatch.setenv("NOTES_CORS_ORIGINS", '["https://a.example", "https://b.example"]')
    monkeypatch.setenv("NOTES_MAX_UPLOAD_BYTES", "4096")
    settings = Settings(_env_file=None)
    assert (settings.debug, settings.cors_origins, settings.max_upload_bytes) == (
        True,
        ["https://a.example", "https://b.example"],
        4096,
    )


def test_env_file_is_read_and_variables_win(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A .env file supplies values; a real environment variable overrides it."""
    env_file = tmp_path / ".env"
    env_file.write_text("NOTES_APP_NAME=From file\nNOTES_API_KEY=file-key\n", encoding="utf-8")
    monkeypatch.setenv("NOTES_API_KEY", "env-key")
    settings = Settings(_env_file=env_file)
    assert settings.app_name == "From file"
    assert settings.api_key is not None and settings.api_key.get_secret_value() == "env-key"


def test_secret_is_hidden_in_repr_and_dumps() -> None:
    """SecretStr never shows its value unless asked explicitly."""
    settings = Settings(_env_file=None, api_key="s3cret-value")
    assert "s3cret-value" not in repr(settings)
    assert settings.model_dump()["api_key"].get_secret_value() == "s3cret-value"
    assert settings.model_dump(mode="json")["api_key"] == "**********"


@pytest.mark.parametrize("key", [None, "change-me"])
def test_production_needs_a_real_key(key: str | None) -> None:
    """Missing or placeholder keys stop a production app from starting."""
    with pytest.raises(ValidationError, match="NOTES_API_KEY"):
        Settings(_env_file=None, environment="production", api_key=key)


def test_get_settings_is_cached() -> None:
    """The settings dependency builds Settings once per process."""
    get_settings.cache_clear()
    assert get_settings() is get_settings()
    get_settings.cache_clear()
