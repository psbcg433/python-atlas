"""Graceful shutdown: on SIGTERM Uvicorn stops accepting, finishes requests in flight, exits.

Orchestrators (Compose, Kubernetes, ECS) stop a container with SIGTERM, wait a grace period,
then SIGKILL. A rolling deploy only loses no requests if the process uses that grace period.
"""

import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

TESTS_DIR = Path(__file__).resolve().parent
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")


def free_port() -> int:
    """A TCP port nobody listens on right now."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def wait_until_live(base_url: str, process: subprocess.Popen[bytes]) -> None:
    """Poll /health/live until the server answers (or fail with its output)."""
    for _ in range(100):
        if process.poll() is not None:
            pytest.fail(
                f"server exited: {process.stdout.read().decode() if process.stdout else ''}"
            )
        try:
            if httpx.get(f"{base_url}/health/live", timeout=0.5).status_code == 200:
                return
        except httpx.TransportError:
            time.sleep(0.1)
    pytest.fail("server did not start")


def start_slow_server(database_path: Path) -> tuple[subprocess.Popen[bytes], str]:
    """Start Uvicorn with slow_app on a free port; return the process and its base URL."""
    port = free_port()
    env = {
        **os.environ,
        "NOTES_ENVIRONMENT": "test",
        "NOTES_DATABASE_URL": f"sqlite+aiosqlite:///{database_path}",
        "NOTES_LOG_JSON": "false",
        "NOTES_CHECK_MIGRATIONS": "false",
    }
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "slow_app:app",
        "--app-dir",
        str(TESTS_DIR),
        "--port",
        str(port),
        "--timeout-graceful-shutdown",
        "10",
        "--log-level",
        "warning",
    ]
    server = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return server, f"http://127.0.0.1:{port}"


def test_sigterm_lets_requests_in_flight_finish(tmp_path: Path) -> None:
    """A 1.5 s request started before SIGTERM still gets its 200; then the process exits.

    After a clean shutdown Uvicorn re-raises the signal it caught, so the exit status is
    "terminated by SIGTERM" (-15), the conventional result; 0 is accepted too.
    """
    server, base_url = start_slow_server(tmp_path / "shutdown.db")
    try:
        wait_until_live(base_url, server)
        results: dict[str, httpx.Response] = {}
        request = threading.Thread(
            target=lambda: results.update(
                slow=httpx.get(f"{base_url}/test/slow?seconds=1.5", timeout=10)
            )
        )
        request.start()
        time.sleep(0.4)  # the request is now in flight
        server.send_signal(signal.SIGTERM)
        request.join(timeout=10)
        exit_status = server.wait(timeout=10)
    finally:
        if server.poll() is None:
            server.kill()
    assert results["slow"].status_code == 200
    assert results["slow"].json() == {"slept": 1.5}
    assert exit_status in (0, -signal.SIGTERM)
    with pytest.raises(httpx.ConnectError):  # nothing listens any more
        httpx.get(f"{base_url}/health/live", timeout=1)
