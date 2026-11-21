"""Load test for the Notes API (Locust).

    uv run locust -f load/locustfile.py --host https://<NOTES_HOST> --headless -u 50 -r 10 -t 2m \
        --csv load/results/live

A pool of accounts is registered when the test starts, at the pace the API's registration
limit allows (5 a minute per address), one account for every two simulated users, so the
per-user limits (120 writes a minute) are never the bottleneck; NOTES_LOAD_ACCOUNTS overrides
the size. The accounts delete themselves when the test stops. Users mostly read (list, one
note, the feed) and sometimes write. The run exits with code 1 when the 95th percentile is
above P95_LIMIT_MS or more than MAX_FAILURE_RATIO of the requests fail: a pass/fail gate.
Certificates are verified, except for localhost (Caddy's local CA in the rehearsal stack).
"""

import itertools
import math
import os
import random
import secrets
from typing import Any
from urllib.parse import urlsplit

from accounts import Account, delete_accounts, register_accounts
from locust import HttpUser, between, events, task

P95_LIMIT_MS = int(os.environ.get("NOTES_LOAD_P95_MS", "200"))
MAX_FAILURE_RATIO = float(os.environ.get("NOTES_LOAD_MAX_FAILURE_RATIO", "0.01"))
USERS_PER_ACCOUNT = 2  # about 40 writes a minute each: an account stays under its 120
LOCAL_HOSTS = {"localhost", "127.0.0.1"}
POOL: list[Account] = []
TURN = itertools.count()


def verify_tls(host: str) -> bool:
    """Verify certificates for real hosts; not for Caddy's local CA."""
    return urlsplit(host).hostname not in LOCAL_HOSTS


def pool_size(environment: Any) -> int:
    """NOTES_LOAD_ACCOUNTS, else one account per USERS_PER_ACCOUNT simulated users."""
    if configured := os.environ.get("NOTES_LOAD_ACCOUNTS"):
        return int(configured)
    users = getattr(environment.parsed_options, "num_users", None) or 50
    return math.ceil(users / USERS_PER_ACCOUNT)


@events.init.add_listener
def create_accounts(environment: Any, **_kwargs: Any) -> None:
    """Register and log in the pool when Locust starts: "init" finishes before the run (and
    its --run-time clock) begins, so the minutes of registration do not eat into the test."""
    host = environment.host
    POOL[:] = register_accounts(host, pool_size(environment), verify_tls(host))


@events.test_stop.add_listener
def remove_accounts(environment: Any, **_kwargs: Any) -> None:
    """Delete the pool's accounts (and with them every note the run wrote)."""
    deleted = delete_accounts(environment.host, POOL, verify_tls(environment.host))
    print(f"deleted {deleted}/{len(POOL)} load-test accounts")


class NotesUser(HttpUser):
    """A user who reads a lot and writes a little."""

    wait_time = between(0.05, 0.2)

    def on_start(self) -> None:
        """Take the next account of the pool (round robin) and the TLS setting."""
        account = POOL[next(TURN) % len(POOL)]
        self.client.headers.update(account.headers)
        self.client.verify = verify_tls(self.host)
        self.note_ids: list[int] = []

    @task(5)
    def list_notes(self) -> None:
        """The most common request."""
        self.client.get("/api/v1/notes?limit=20", name="/api/v1/notes")

    @task(3)
    def read_note(self) -> None:
        """One note (cache and ETag path)."""
        if self.note_ids:
            note_id = random.choice(self.note_ids)
            self.client.get(f"/api/v1/notes/{note_id}", name="/api/v1/notes/{id}")

    @task(1)
    def create_note(self) -> None:
        """A write: database transaction, outbox row, cache invalidation."""
        reply = self.client.post("/api/v1/notes", json={"title": f"Load {secrets.token_hex(3)}"})
        if reply.status_code == 201:
            self.note_ids.append(reply.json()["id"])

    @task(1)
    def feed(self) -> None:
        """Keyset pagination."""
        self.client.get("/api/v1/notes/feed?limit=10", name="/api/v1/notes/feed")


@events.quitting.add_listener
def enforce_slo(environment: Any, **_kwargs: Any) -> None:
    """Fail the run (exit code 1) when the latency or error budget is blown."""
    total = environment.stats.total
    p95 = total.get_response_time_percentile(0.95) or 0
    if total.fail_ratio > MAX_FAILURE_RATIO or p95 > P95_LIMIT_MS:
        environment.process_exit_code = 1
