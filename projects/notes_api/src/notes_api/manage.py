"""Operator commands: run where the database is, never reachable over HTTP.

    python -m notes_api.manage promote-admin you@example.com
    python -m notes_api.manage demote-admin someone@example.com

In production they run in a one-off container of the current image (deploy/production/dc run
--rm --no-deps migrate python -m notes_api.manage ...), with the server's settings.
"""

import argparse
import asyncio
import sys
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from notes_api.core.config import Settings, get_settings
from notes_api.db import create_engine_from_settings, make_session_factory
from notes_api.models import User

type SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
ROLES = {"promote-admin": "admin", "demote-admin": "user"}


async def set_role(session_factory: SessionFactory, email: str, role: str) -> bool:
    """Give the account with this e-mail a role; False when there is no such account."""
    async with session_factory() as session, session.begin():
        user = await session.scalar(select(User).where(User.email == email.lower()))
        if user is None:
            return False
        user.role = role  # access tokens are checked against the stored role on every request
        return True


async def change_role(settings: Settings, email: str, role: str) -> bool:
    """set_role() on a short-lived engine built from the settings."""
    engine = create_engine_from_settings(settings)
    try:
        return await set_role(make_session_factory(engine), email, role)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None, settings: Settings | None = None) -> int:
    """Parse the command line, change the role, return the exit code (1: unknown account)."""
    parser = argparse.ArgumentParser(prog="python -m notes_api.manage", description=__doc__)
    parser.add_argument("command", choices=sorted(ROLES))
    parser.add_argument("email")
    arguments = parser.parse_args(argv)
    role = ROLES[arguments.command]
    if not asyncio.run(change_role(settings or get_settings(), arguments.email, role)):
        print(f"no account with e-mail {arguments.email}: register it first", file=sys.stderr)
        return 1
    print(f"{arguments.email.lower()}: role {role}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
