"""Small helpers shared by the test modules."""

import ipaddress
from pathlib import Path
from typing import Any

from alembic.config import Config
from fastapi.testclient import TestClient

from notes_api.core.config import Settings
from notes_api.db import Base, create_engine_from_settings

USER_EMAIL = "user@example.com"
PASSWORD = "correct horse battery staple"
ANONYMOUS = {"Authorization": ""}  # overrides the client's default header
FAKE_DNS = {
    "docs.example": ["93.184.216.34"],
    "slow.example": ["93.184.216.35"],
    "intranet.example": ["10.0.0.7"],
    "metadata.example": ["169.254.169.254"],
    "mixed.example": ["93.184.216.36", "127.0.0.1"],
    "hooks.example": ["93.184.216.37"],
}


def create(client: TestClient, **fields: Any) -> dict[str, Any]:
    """POST a note (title defaults to "Buy tea") and return the created note."""
    response = client.post("/api/v1/notes", json={"title": "Buy tea", **fields})
    assert response.status_code == 201, response.text
    return response.json()


def ids(response: Any) -> list[int]:
    """Ids of the notes on a page."""
    assert response.status_code == 200, response.text
    return [note["id"] for note in response.json()["items"]]


def register(client: TestClient, email: str, password: str = PASSWORD) -> Any:
    """POST /auth/register (without the client's default credentials)."""
    body = {"email": email, "password": password}
    return client.post("/api/v1/auth/register", json=body, headers=ANONYMOUS)


def login(client: TestClient, email: str, password: str = PASSWORD, scope: str = "") -> Any:
    """POST /auth/token with the OAuth2 password form."""
    form = {"username": email, "password": password, "scope": scope}
    return client.post("/api/v1/auth/token", data=form, headers=ANONYMOUS)


def auth_headers(client: TestClient, email: str, scope: str = "") -> dict[str, str]:
    """Register (if needed) and log in; return a Bearer header."""
    register(client, email)
    response = login(client, email, scope=scope)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def fake_resolver(host: str) -> list[str]:
    """DNS for tests: IP literals resolve to themselves, a few names to fixed addresses."""
    try:
        return [str(ipaddress.ip_address(host))]
    except ValueError:
        pass
    if host not in FAKE_DNS:
        raise OSError(f"cannot resolve {host}")
    return FAKE_DNS[host]


async def create_tables(settings: Settings) -> None:
    """CREATE TABLE for every model (fast; the PostgreSQL tests run the Alembic migrations)."""
    engine = create_engine_from_settings(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


class FakeMailer:
    """A Mailer that keeps the messages."""

    def __init__(self) -> None:
        """Start with an empty outbox."""
        self.sent: list[tuple[str, str]] = []

    async def send(self, to: str, subject: str, body: str) -> None:
        """Record one message."""
        self.sent.append((to, subject))


PROJECT_DIR = Path(__file__).resolve().parent.parent
POSTGRES_IMAGE = "postgres:18-alpine"
REDIS_IMAGE = "redis:7.4"


def docker_available() -> bool:
    """True if a Docker daemon answers (the PostgreSQL / Redis tests need one, or CI services)."""
    try:
        import docker

        docker.from_env().ping()
    except Exception:
        return False
    return True


def postgres_alembic_config(url: str) -> Config:
    """alembic.ini pointed at a PostgreSQL URL."""
    config = Config(PROJECT_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    config.attributes["configure_logger"] = False
    return config
