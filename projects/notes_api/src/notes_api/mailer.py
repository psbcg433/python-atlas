"""Outgoing email behind a Protocol; the default mailer only logs (no SMTP in the course)."""

import logging
from typing import Protocol

logger = logging.getLogger("notes_api.mailer")


class Mailer(Protocol):
    """Anything that can send a message."""

    async def send(self, to: str, subject: str, body: str) -> None:
        """Deliver one email."""
        ...


class LogMailer:
    """Writes emails to the log (production would use an email API, called from a worker)."""

    async def send(self, to: str, subject: str, body: str) -> None:
        """Log instead of sending."""
        logger.info("email to=%s subject=%s", to, subject)


async def send_welcome_email(mailer: Mailer, email: str) -> None:
    """The BackgroundTasks job run after registration: failures must not break signup."""
    try:
        await mailer.send(email, "Welcome to Notes", "Your account is ready.")
    except Exception:  # a background task has nobody to report to: log and move on
        logger.exception("welcome email to %s failed", email)
