"""A pool of throw-away accounts for load tests, created and deleted through the public API.

The API limits each user (120 writes a minute by default) and registration (5 a minute per
client address), so a load test needs several accounts, registered at the pace the API allows,
and must remove them afterwards. The same code serves the rehearsal and the live server.
"""

import dataclasses
import secrets
import time
from collections.abc import Callable

import requests

REGISTER, TOKEN, ME = "/api/v1/auth/register", "/api/v1/auth/token", "/api/v1/users/me"


@dataclasses.dataclass
class Account:
    """One load-test user: its credentials and a current access token."""

    email: str
    password: str
    token: str = ""

    @property
    def headers(self) -> dict[str, str]:
        """The Authorization header for this account."""
        return {"Authorization": f"Bearer {self.token}"}


def log_in(session: requests.Session, host: str, account: Account) -> None:
    """Get a fresh access token (they last 15 minutes)."""
    form = {"username": account.email, "password": account.password}
    reply = session.post(f"{host}{TOKEN}", data=form, timeout=10)
    reply.raise_for_status()
    account.token = reply.json()["access_token"]


def register_accounts(
    host: str, count: int, verify: bool, say: Callable[[str], None] = print
) -> list[Account]:
    """Register and log in `count` accounts load-<run>-<n>@example.com; on 429, wait for the
    Retry-After the API sends (one window per 5 accounts with the default limit)."""
    run = secrets.token_hex(3)
    accounts = [
        Account(f"load-{run}-{number}@example.com", secrets.token_urlsafe(16))
        for number in range(count)
    ]
    with requests.Session() as session:
        session.verify = verify
        for number, account in enumerate(accounts, start=1):
            body = {"email": account.email, "password": account.password}
            reply = session.post(f"{host}{REGISTER}", json=body, timeout=10)
            while reply.status_code == 429:
                wait = int(reply.headers.get("Retry-After", "5"))
                say(f"registered {number - 1}/{count}; the registration limit asks for {wait} s")
                time.sleep(wait)
                reply = session.post(f"{host}{REGISTER}", json=body, timeout=10)
            reply.raise_for_status()
        for account in accounts:  # after all registrations: every token is fresh at the start
            log_in(session, host, account)
    say(f"registered {count}/{count} accounts (load-{run}-*@example.com)")
    return accounts


def delete_accounts(host: str, accounts: list[Account], verify: bool) -> int:
    """DELETE /users/me for each account (logging in again if its token expired); the
    database removes their notes, tokens and events. Returns how many were deleted."""
    deleted = 0
    with requests.Session() as session:
        session.verify = verify
        for account in accounts:
            reply = session.delete(f"{host}{ME}", headers=account.headers, timeout=10)
            if reply.status_code == 401:
                log_in(session, host, account)
                reply = session.delete(f"{host}{ME}", headers=account.headers, timeout=10)
            deleted += reply.status_code == 204
    return deleted
