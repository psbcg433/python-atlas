"""BackgroundTasks after the response: the welcome email and the relay kick."""

from arq.connections import ArqRedis
from fastapi.testclient import TestClient

from helpers import FakeMailer, create, register
from notes_api.events import sign_webhook, verify_webhook


def test_welcome_email_is_sent_after_registration(
    anonymous: TestClient, mailer: FakeMailer
) -> None:
    """The response does not wait for the email; TestClient runs background tasks first."""
    assert register(anonymous, "new@example.com").status_code == 201
    assert mailer.sent == [("new@example.com", "Welcome to Notes")]


def test_writes_kick_the_relay(client: TestClient, fake_queue: ArqRedis) -> None:
    """After a write, a relay job is queued so events go out without waiting for the cron."""
    create(client)
    jobs = client.portal.call(fake_queue.queued_jobs)
    assert "relay_outbox" in {job.function for job in jobs}


def test_webhook_signatures_are_checked_with_a_time_window() -> None:
    """Wrong secret, changed body or an old timestamp fail verification."""
    header = sign_webhook("whsec_test", 1_000, b'{"id":1}')
    assert verify_webhook("whsec_test", header, b'{"id":1}', now=1_010)
    assert not verify_webhook("whsec_other", header, b'{"id":1}', now=1_010)
    assert not verify_webhook("whsec_test", header, b'{"id":2}', now=1_010)
    assert not verify_webhook("whsec_test", header, b'{"id":1}', now=2_000)
    assert not verify_webhook("whsec_test", "garbage", b"", now=0)
