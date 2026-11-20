"""Load test for the Notes API (Locust).

    uv run locust -f load/locustfile.py --host http://127.0.0.1:8000 --headless -u 20 -r 10 -t 30s

One account is created when the test starts (registration is rate-limited per address, as it
should be) and every simulated user shares its token. Users mostly read (list, one note, the
feed) and sometimes write. The run exits with code 1 when the 95th percentile is above
P95_LIMIT_MS or more than MAX_FAILURE_RATIO of the requests fail: a pass/fail gate for CI.
"""

import random
import secrets
from typing import Any

import requests
from locust import HttpUser, between, events, task

P95_LIMIT_MS = 200
MAX_FAILURE_RATIO = 0.01
SHARED: dict[str, str] = {}


@events.test_start.add_listener
def create_account(environment: Any, **_kwargs: Any) -> None:
    """Register one user and log in once, before any simulated user starts."""
    email, password = f"load-{secrets.token_hex(4)}@example.com", secrets.token_urlsafe(16)
    host = environment.host
    requests.post(
        f"{host}/api/v1/auth/register",
        json={"email": email, "password": password},
        verify=False,
        timeout=10,
    )
    reply = requests.post(
        f"{host}/api/v1/auth/token",
        data={"username": email, "password": password},
        verify=False,
        timeout=10,
    )
    SHARED["authorization"] = f"Bearer {reply.json()['access_token']}"


class NotesUser(HttpUser):
    """A user who reads a lot and writes a little."""

    wait_time = between(0.05, 0.2)

    def on_start(self) -> None:
        """Use the shared token; accept the proxy's local certificate."""
        self.client.headers["Authorization"] = SHARED["authorization"]
        self.client.verify = False  # Caddy's internal CA in the local stack
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
