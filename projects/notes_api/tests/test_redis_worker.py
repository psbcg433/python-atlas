"""End to end on a real Redis (testcontainer) with the real ARQ worker in burst mode.

Skipped without Docker. Run only these: `uv run pytest -m redis`.
"""

import asyncio

import pytest
import respx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from helpers import USER_EMAIL, FakeMailer, auth_headers, create, create_tables, fake_resolver
from notes_api.core.config import Settings
from notes_api.dependencies import get_mailer, get_resolver
from notes_api.events import SIGNATURE_HEADER, verify_webhook
from notes_api.main import create_app
from notes_api.worker import run_worker

pytestmark = pytest.mark.redis
HOOK = "https://hooks.example/notes"


@pytest.fixture
def real_settings(settings: Settings, redis_url: str) -> Settings:
    """The test settings, but with the real Redis."""
    return settings.model_copy(update={"redis_url": SecretStr(redis_url)})


def burst(settings: Settings) -> None:
    """Process every queued job (and the jobs they queue), then stop."""
    asyncio.run(run_worker(burst=True, settings=settings))


@respx.mock
def test_write_kick_relay_and_signed_webhook(real_settings: Settings) -> None:
    """A note change reaches the user's webhook through outbox → kick → relay → job."""
    receiver = respx.post(HOOK).respond(204)
    asyncio.run(create_tables(real_settings))
    app = create_app(real_settings)
    app.dependency_overrides[get_resolver] = lambda: fake_resolver
    app.dependency_overrides[get_mailer] = FakeMailer
    with TestClient(app) as client:
        client.headers.update(auth_headers(client, USER_EMAIL))
        secret = client.put("/api/v1/users/me/webhook", json={"url": HOOK}).json()["secret"]
        create(client, title="Real Redis")
        burst(real_settings)
        request = receiver.calls.last.request
        timestamp = int(request.headers[SIGNATURE_HEADER].split(",")[0][2:])
        assert verify_webhook(secret, request.headers[SIGNATURE_HEADER], request.content, timestamp)
        assert b'"type":"note.created"' in request.content

        export = client.post("/api/v1/exports").json()
        burst(real_settings)
        events = client.get(export["events_url"]).text
        assert '"status":"done","done":1,"total":1' in events
