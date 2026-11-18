"""Shared fixtures: each test gets its own app, SQLite file and fake Redis, and a logged-in user."""

import asyncio
import secrets
from collections.abc import Iterator
from pathlib import Path

import fakeredis
import pytest
from arq.connections import ArqRedis
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from helpers import USER_EMAIL, FakeMailer, auth_headers, create_tables, fake_resolver
from notes_api.core.config import Settings
from notes_api.dependencies import get_mailer, get_queue, get_redis, get_resolver
from notes_api.main import create_app


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests on asyncio (the anyio pytest plugin ships with anyio)."""
    return "asyncio"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Test settings: a fresh SQLite file, a generated JWT secret, cheap Argon2 parameters."""
    return Settings(
        _env_file=None,
        environment="test",
        cors_origins=["http://localhost:5173"],
        max_upload_bytes=2048,
        database_url=SecretStr(f"sqlite+aiosqlite:///{tmp_path / 'notes.db'}"),
        jwt_secret=SecretStr(secrets.token_urlsafe(32)),
        password_time_cost=1,
        password_memory_kib=64,
        admin_emails=["admin@example.com"],
        login_rate_limit=10,
        cookie_secure=False,  # TestClient talks plain HTTP
    )


@pytest.fixture
def redis_server() -> fakeredis.FakeServer:
    """One in-memory Redis server per test, shared by the text and the queue clients."""
    return fakeredis.FakeServer()


@pytest.fixture
def fake_redis(redis_server: fakeredis.FakeServer) -> fakeredis.FakeAsyncRedis:
    """The text client (decoded strings), as the app uses it."""
    return fakeredis.FakeAsyncRedis(server=redis_server, decode_responses=True)


@pytest.fixture
def fake_queue(redis_server: fakeredis.FakeServer) -> ArqRedis:
    """An ARQ client on the same fake server (bytes, pickled jobs)."""
    return ArqRedis(connection_pool=fakeredis.FakeAsyncRedis(server=redis_server).connection_pool)


@pytest.fixture
def mailer() -> FakeMailer:
    """Records emails instead of sending them."""
    return FakeMailer()


@pytest.fixture
def app(
    settings: Settings,
    fake_redis: fakeredis.FakeAsyncRedis,
    fake_queue: ArqRedis,
    mailer: FakeMailer,
) -> FastAPI:
    """A fresh app on an empty database, with fake Redis, queue, mailer and DNS."""
    asyncio.run(create_tables(settings))
    application = create_app(settings)
    application.dependency_overrides[get_redis] = lambda: fake_redis
    application.dependency_overrides[get_queue] = lambda: fake_queue
    application.dependency_overrides[get_mailer] = lambda: mailer
    application.dependency_overrides[get_resolver] = lambda: fake_resolver
    return application


@pytest.fixture
def anonymous(app: FastAPI) -> Iterator[TestClient]:
    """A TestClient without credentials; entering it runs the lifespan."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def client(anonymous: TestClient) -> TestClient:
    """The same client, logged in as an ordinary user (Authorization header on every call)."""
    anonymous.headers.update(auth_headers(anonymous, USER_EMAIL))
    return anonymous


@pytest.fixture
def admin_headers(anonymous: TestClient) -> dict[str, str]:
    """Bearer headers of an admin (admin@example.com is in admin_emails)."""
    return auth_headers(anonymous, "admin@example.com")
