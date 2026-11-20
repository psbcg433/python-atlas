"""Shared fixtures: an app per test (SQLite file, fakeredis), clients, PostgreSQL and Redis."""

import asyncio
import os
import secrets
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import fakeredis
import httpx
import pytest
from alembic import command
from arq.connections import ArqRedis
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import settings as hypothesis_settings
from pydantic import SecretStr

from helpers import (
    PASSWORD,
    POSTGRES_IMAGE,
    REDIS_IMAGE,
    USER_EMAIL,
    FakeMailer,
    auth_headers,
    create_tables,
    docker_available,
    fake_resolver,
    postgres_alembic_config,
)
from notes_api.core.config import Settings
from notes_api.dependencies import get_mailer, get_queue, get_redis, get_resolver
from notes_api.main import create_app

# No example database for Hypothesis (Schemathesis uses it): every run tries the same cases.
hypothesis_settings.register_profile("notes", database=None)
hypothesis_settings.load_profile("notes")


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
        check_migrations=False,  # the test schema comes from create_all, not Alembic
        otel_exporter="memory",  # spans are kept on app.state.span_exporter
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


@pytest.fixture
async def async_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """httpx.AsyncClient calling the app in this event loop (ASGITransport), with its lifespan."""
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            http.headers.update(await async_auth_headers(http, USER_EMAIL))
            yield http


async def async_auth_headers(http: httpx.AsyncClient, email: str) -> dict[str, str]:
    """Register and log in through the async client; return a Bearer header."""
    await http.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    form = {"username": email, "password": PASSWORD}
    token = (await http.post("/api/v1/auth/token", data=form)).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """A PostgreSQL database migrated to head: the CI service, or a testcontainer."""
    if url := os.environ.get("NOTES_TEST_DATABASE_URL"):
        command.upgrade(postgres_alembic_config(url), "head")
        yield url
        return
    if not docker_available():
        pytest.skip("no NOTES_TEST_DATABASE_URL and Docker is not available")
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as container:
        url = container.get_connection_url()
        command.upgrade(postgres_alembic_config(url), "head")
        yield url


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    """A real Redis: the CI service, or a testcontainer."""
    if url := os.environ.get("NOTES_TEST_REDIS_URL"):
        yield url
        return
    if not docker_available():
        pytest.skip("no NOTES_TEST_REDIS_URL and Docker is not available")
    from testcontainers.community.redis import RedisContainer

    with RedisContainer(REDIS_IMAGE) as container:
        host, port = container.get_container_host_ip(), container.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"
