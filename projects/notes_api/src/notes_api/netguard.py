"""Outbound requests to user-supplied URLs (link previews, webhooks) without SSRF.

Checking a URL and then letting the HTTP client resolve the host again is not enough: the
DNS answer can change between the two lookups (DNS rebinding), so a name that was public for
the check can be 127.0.0.1 or 169.254.169.254 for the connection. PublicAddressBackend makes
the check where the connection is made: it resolves the host, refuses if any address is not
public, and connects to the address it checked. TLS still verifies the certificate against
the URL's host name (httpcore passes it as server_hostname), so HTTPS keeps working.
"""

import asyncio
import ipaddress
import socket
import urllib.parse
from collections.abc import Awaitable, Callable, Iterable

import httpcore
import httpx

type Resolver = Callable[[str], Awaitable[list[str]]]
type AddressCheck = Callable[[str], bool]
BLOCKED = "blocked: not a public address"


async def resolve_host(host: str) -> list[str]:
    """Every IP address a host name resolves to (getaddrinfo runs in a worker thread)."""
    infos = await asyncio.to_thread(socket.getaddrinfo, host, None, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def is_public_address(address: str) -> bool:
    """False for loopback, private, link-local, reserved, multicast and unspecified addresses."""
    ip = ipaddress.ip_address(address)
    return ip.is_global and not ip.is_multicast


async def check_public_url(url: str, resolver: Resolver = resolve_host) -> str | None:
    """None if the URL may be fetched, else the reason (an early, readable answer; the
    transport below enforces the same rule when it connects)."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return "only public http(s) URLs are fetched"
    try:
        addresses = await resolver(parsed.hostname)
    except OSError:
        return "host does not resolve"
    if not addresses or not all(is_public_address(address) for address in addresses):
        return BLOCKED
    return None


class PublicAddressBackend(httpcore.AsyncNetworkBackend):
    """An httpcore network backend that connects only to addresses it has just checked."""

    def __init__(
        self, resolver: Resolver = resolve_host, allowed: AddressCheck = is_public_address
    ) -> None:
        """Resolve with `resolver`; connect only if `allowed` accepts every address."""
        self.resolver = resolver
        self.allowed = allowed
        self.backend = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        """Resolve, check every address, connect to the first one (never to a fresh lookup)."""
        try:
            addresses = await self.resolver(host)
        except OSError as error:
            raise httpcore.ConnectError(f"host does not resolve: {host}") from error
        if not addresses or not all(self.allowed(address) for address in addresses):
            raise httpcore.ConnectError(f"{BLOCKED}: {host}")
        return await self.backend.connect_tcp(
            addresses[0], port, timeout, local_address, socket_options
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        """Never: a user-supplied URL must not reach a local socket."""
        raise httpcore.ConnectError(f"{BLOCKED}: unix socket {path}")

    async def sleep(self, seconds: float) -> None:
        """Used by httpcore between retries."""
        await self.backend.sleep(seconds)


def public_only_client(
    timeout: float,
    user_agent: str,
    resolver: Resolver = resolve_host,
    allowed: AddressCheck = is_public_address,
) -> httpx.AsyncClient:
    """An AsyncClient whose every connection goes through PublicAddressBackend.

    httpx has no public option for the network backend, so the transport's connection pool is
    rebuilt with one. trust_env=False: a proxy from HTTP(S)_PROXY would bypass the check, and
    redirects are never followed (a public URL could redirect to a private one).
    """
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    transport = httpx.AsyncHTTPTransport(limits=limits, trust_env=False)
    transport._pool = httpcore.AsyncConnectionPool(  # replaces the pool built with the default
        ssl_context=httpx.create_ssl_context(),
        max_connections=limits.max_connections,
        max_keepalive_connections=limits.max_keepalive_connections,
        keepalive_expiry=limits.keepalive_expiry,
        network_backend=PublicAddressBackend(resolver, allowed),
    )
    return httpx.AsyncClient(
        transport=transport,
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
        headers={"User-Agent": user_agent},
    )
