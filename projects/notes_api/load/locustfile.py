"""Load test for the Notes API (Locust).

    uv run locust -f load/locustfile.py --host https://<NOTES_HOST> --headless -u 50 -r 10 -t 2m \
        --csv load/results/live

One account is created when the test starts (registration is rate-limited per address, as it
should be) and every simulated user shares its token. Users mostly read (list, one note, the
feed) and sometimes write. The run exits with code 1 when the 95th percentile is above
P95_LIMIT_MS or more than MAX_FAILURE_RATIO of the requests fail: a pass/fail gate for CI.
Certificates are verified, except for localhost (Caddy's local CA in the rehearsal stack).
"""

import os
import random
import secrets
from typing import Any
from urllib.parse import urlsplit

import requests
from locust import HttpUser, between, events, task

P95_LIMIT_MS = int(os.environ.get("NOTES_LOAD_P95_MS", "200"))
MAX_FAILURE_RATIO = float(os.environ.get("NOTES_LOAD_MAX_FAILURE_RATIO", "0.01"))
LOCAL_HOSTS = {"localhost", "127.0.0.1"}
SHARED: dict[str, Any] = {}


def verify_tls(host: str) -> bool:
    """Verify certificates for real hosts; not for Caddy's local CA."""
    return urlsplit(host).hostname not in LOCAL_HOSTS


@events.test_start.add_listener
def create_account(environment: Any, **_kwargs: Any) -> None:
    """Register one user (load-<random>@example.com) and log in once, before any user starts."""
    email, password = f"load-{secrets.token_hex(4)}@example.com", secrets.token_urlsafe(16)
    host, verify = environment.host, verify_tls(environment.host)
    requests.post(
        f"{host}/api/v1/auth/register",
        json={"email": email, "password": password},
        verify=verify,
        timeout=10,
    )
    reply = requests.post(
        f"{host}/api/v1/auth/token",
        data={"username": email, "password": password},
        verify=verify,
        timeout=10,
    )
    SHARED["authorization"] = f"Bearer {reply.json()['access_token']}"
    SHARED["verify"] = verify


class NotesUser(HttpUser):
    """A user who reads a lot and writes a little."""

    wait_time = between(0.05, 0.2)

    def on_start(self) -> None:
        """Use the shared token and the TLS setting chosen at test start."""
        self.client.headers["Authorization"] = SHARED["authorization"]
        self.client.verify = SHARED["verify"]
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
