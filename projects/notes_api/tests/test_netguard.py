"""netguard: the SSRF rule holds where the connection is made, even when DNS changes."""

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import httpx
import pytest

from notes_api.netguard import BLOCKED, Resolver, check_public_url, public_only_client
from notes_api.services import LinkPreviewer

pytestmark = pytest.mark.anyio


class Recorder(BaseHTTPRequestHandler):
    """Answers every GET with a page and remembers the Host header of each request."""

    hosts: ClassVar[list[str]] = []

    def do_GET(self) -> None:
        """200 with a title."""
        type(self).hosts.append(self.headers["Host"])
        body = b"<title>internal admin</title>"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 (stdlib name)
        """No access log on stderr."""


@pytest.fixture
def internal_port() -> Iterator[int]:
    """A server on 127.0.0.1 standing in for something private (an admin page, metadata)."""
    Recorder.hosts = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def rebinding_dns() -> Resolver:
    """Public for the first lookup, 127.0.0.1 after it (what a rebinding attacker serves)."""
    answers = iter([["93.184.216.34"]])

    async def resolve(host: str) -> list[str]:
        """The next answer."""
        return next(answers, ["127.0.0.1"])

    return resolve


async def test_rebinding_is_refused_at_connect_time(internal_port: int) -> None:
    """The check passes on the first answer; the connection is refused on the second."""
    resolver, url = rebinding_dns(), f"http://rebind.example:{internal_port}/"
    assert await check_public_url(url, resolver) is None
    async with public_only_client(2, "test", resolver) as client:
        with pytest.raises(httpx.ConnectError, match=BLOCKED):
            await client.get(url)
    assert Recorder.hosts == []  # nothing reached the internal server


async def test_link_preview_reports_the_rebinding(internal_port: int) -> None:
    """LinkPreviewer: check_url() sees a public address, the connection is refused."""
    resolver, url = rebinding_dns(), f"http://rebind.example:{internal_port}/"
    async with public_only_client(2, "test", resolver) as client:
        preview = await LinkPreviewer(client, resolver).preview(url)
    assert (preview.title, preview.error) == (None, BLOCKED)
    assert Recorder.hosts == []


async def test_the_connection_goes_to_the_checked_address(internal_port: int) -> None:
    """With loopback allowed (tests only), a name no DNS server knows still works: the client
    connected to the address the backend checked instead of looking the name up itself."""

    async def pinned(host: str) -> list[str]:
        """The only answer."""
        return ["127.0.0.1"]

    async with public_only_client(2, "test", pinned, allowed=lambda address: True) as client:
        response = await client.get(f"http://pinned.invalid:{internal_port}/")
    assert response.status_code == 200
    assert Recorder.hosts == [f"pinned.invalid:{internal_port}"]  # the Host header keeps the name


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:9/", "http://169.254.169.254/latest/meta-data/", "http://[::1]:9/"]
)
async def test_private_ip_literals_are_refused(url: str) -> None:
    """An IP literal is checked like any resolved address."""

    async def literal(host: str) -> list[str]:
        """IP literals resolve to themselves."""
        return [host]

    async with public_only_client(2, "test", literal) as client:
        with pytest.raises(httpx.ConnectError, match=BLOCKED):
            await client.get(url)
