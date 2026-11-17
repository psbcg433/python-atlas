"""Shared fixtures: every test gets its own app and its own SQLite database file."""

import asyncio
import secrets
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from helpers import create_tables
from notes_api.core.config import Settings
from notes_api.main import create_app


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests on asyncio (the anyio pytest plugin ships with anyio)."""
    return "asyncio"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Test settings: no .env file, a key generated for this run, a fresh SQLite file."""
    return Settings(
        _env_file=None,
        environment="test",
        api_key=SecretStr(secrets.token_urlsafe(16)),
        cors_origins=["http://localhost:5173"],
        max_upload_bytes=2048,
        database_url=SecretStr(f"sqlite+aiosqlite:///{tmp_path / 'notes.db'}"),
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    """A fresh app on an empty database for each test."""
    asyncio.run(create_tables(settings))
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """A TestClient; entering it runs the lifespan (startup and shutdown)."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def admin_headers(settings: Settings) -> dict[str, str]:
    """Headers carrying the valid API key."""
    assert settings.api_key is not None
    return {"X-API-Key": settings.api_key.get_secret_value()}
