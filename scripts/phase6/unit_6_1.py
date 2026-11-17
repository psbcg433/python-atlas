"""Unit 6.1 — HTTP and the Python Web Stack from Scratch (with Lab 6.1)."""

import importlib.util
from pathlib import Path

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells, writefile_cells


def _load_shop_api_source() -> str:
    """Return SHOP_API_SOURCE from the Phase 4 unit module (one copy of the server code).

    The module is loaded by file path, not through sys.path, so another phase's ``project.py``
    can never shadow it.
    """
    module_path = Path(__file__).resolve().parents[1] / "phase4" / "unit_4_6.py"
    spec = importlib.util.spec_from_file_location("phase4_unit_4_6", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SHOP_API_SOURCE


SHOP_API_SOURCE = _load_shop_api_source()

UNIT_SETUP_SOURCE = r'''
import asyncio
import base64
import contextlib
import dataclasses
import http
import http.client
import importlib
import importlib.util
import inspect
import json
import os
import platform
import re
import shutil
import socket
import ssl
import subprocess
import sys
import sysconfig
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Awaitable, Callable, Iterable, Iterator
from http import HTTPStatus
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx

REPO_ROOT = find_repo_root()
scratch_dir = REPO_ROOT / "notebooks" / "_scratch"  # git-ignored
PHASE6_DIR = scratch_dir / "phase6"
PHASE6_DIR.mkdir(parents=True, exist_ok=True)
os.chdir(REPO_ROOT / "notebooks")  # %%writefile cells use paths relative to notebooks/
if str(PHASE6_DIR) not in sys.path:
    sys.path.insert(0, str(PHASE6_DIR))
CHILD_ENV = {**os.environ, "PYTHON_COLORS": "0", "PYTHONUNBUFFERED": "1", "NO_COLOR": "1"}
CHILD_ENV.pop("FORCE_COLOR", None)


def has_module(name: str) -> bool:
    """True if the module can be imported (checked without importing it)."""
    return importlib.util.find_spec(name) is not None


OPTIONAL_PACKAGES = {
    name: has_module(name)
    for name in (
        "requests",
        "h2",
        "aiohttp",
        "websockets",
        "uvicorn",
        "starlette",
        "fastapi",
        "flask",
        "django",
        "litestar",
        "gunicorn",
    )
}
HAS_NODE = shutil.which("node") is not None
HAS_OPENSSL = shutil.which("openssl") is not None
SHOP_API = start_shop_api()  # the local API from Unit 4.6
'''

UNIT_SETUP_SOURCE_2 = r'''
def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"


def raised_message(thunk: Callable[[], object]) -> str:
    """Call thunk and return "ErrorName: message" (memory addresses hidden), or "no error"."""
    try:
        thunk()
    except Exception as error:
        return re.sub(r" at 0x[0-9a-f]+", "", f"{type(error).__name__}: {error}")
    return "no error"


def interpreter_label() -> str:
    """Implementation, version and build flavour: print it next to every benchmark."""
    free_threaded = bool(sysconfig.get_config_var("Py_GIL_DISABLED"))
    build = "free-threaded build" if free_threaded else "default (GIL) build"
    implementation = platform.python_implementation()
    return f"{implementation} {platform.python_version()}, {build}, {platform.machine()}"


class Timer:
    """Timing context manager (shared since Unit 1.14): reports on exit, keeps elapsed_seconds."""

    def __init__(self, label: str, report: Callable[[str], None] | None = print) -> None:
        """Remember the label and where to report the elapsed time."""
        self.label = label
        self.report = report
        self.elapsed_seconds = 0.0

    def __enter__(self) -> Timer:
        """Start the clock."""
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Stop the clock and report the elapsed milliseconds."""
        self.elapsed_seconds = time.perf_counter() - self._start
        if self.report is not None:
            self.report(f"{self.label} took {self.elapsed_seconds * 1000:.2f} ms")


def fresh_import(module_name: str) -> ModuleType:
    """Import a module saved by a %%writefile cell, always re-reading the file from disk."""
    for cached in (PHASE6_DIR / "__pycache__").glob(f"{module_name}.*.pyc"):
        cached.unlink()
    importlib.invalidate_caches()
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def mask_dates(text: str) -> str:
    """Replace HTTP Date header values and ephemeral port numbers with stable placeholders."""
    text = re.sub(r"(?im)^(date: ).*$", r"\1<date>", text)
    return re.sub(r"127\.0\.0\.1:\d+", "127.0.0.1:<port>", text)
'''

SERVER_HELPERS_SOURCE = r'''
NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def free_port() -> int:
    """Ask the OS for a free TCP port on 127.0.0.1 (bind to port 0, read it, release it)."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def wait_for_health(
    health_url: str, process: subprocess.Popen[bytes] | None = None, timeout: float = 15.0
) -> None:
    """Poll health_url until it answers 200; fail fast if the server process exits."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"server exited early with code {process.returncode}")
        try:
            with NO_PROXY_OPENER.open(health_url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.05)
    raise TimeoutError(f"{health_url} did not become healthy within {timeout} s")


@contextlib.contextmanager
def background_server(
    command: list[str],
    port: int,
    *,
    health_path: str = "/health",
    cwd: Path = PHASE6_DIR,
    extra_env: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> Iterator[str]:
    """Start a server process, wait for its health check, yield its base URL, always stop it."""
    log_path = PHASE6_DIR / f"server_{port}.log"
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            command,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=cwd,
            env={**CHILD_ENV, **(extra_env or {})},
        )
    base_url = f"http://127.0.0.1:{port}"
    started = False
    try:
        try:
            wait_for_health(base_url + health_path, process, timeout)
        except RuntimeError, TimeoutError:
            print(log_path.read_text(encoding="utf-8")[-2000:])  # show why it did not start
            raise
        started = True
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        if started:
            log_path.unlink(missing_ok=True)  # keep the log only when startup failed


def uvicorn_server(
    app_spec: str, *, app_dir: Path = PHASE6_DIR, extra_args: Iterable[str] = (), **options: Any
) -> contextlib.AbstractContextManager[str]:
    """Serve "module:attribute" with Uvicorn in a child process (see background_server)."""
    port = free_port()
    host_and_port = ["--host", "127.0.0.1", "--port", str(port)]
    command = [sys.executable, "-m", "uvicorn", app_spec, "--app-dir", str(app_dir), *host_and_port]
    command += ["--log-level", "warning", *extra_args]
    return background_server(command, port, **options)
'''

SETUP_REPORT_SOURCE = r"""
print(interpreter_label())
print(f"{SHOP_API=}")
found_flags = (f"{name} {'yes' if found else 'no'}" for name, found in OPTIONAL_PACKAGES.items())
print("optional packages: " + ", ".join(found_flags))
print(f"{HAS_NODE=}  {HAS_OPENSSL=}")
"""


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 6.1 — HTTP and the Python Web Stack from Scratch

            **Objectives**

            - Explain what happens between a browser and a Python function: TCP/IP, ports,
              DNS, TLS, and the `socket` API.
            - Read and write HTTP/1.1 messages by hand: request and status lines, headers,
              bodies, CRLF, keep-alive, chunked encoding, content negotiation.
            - Use method semantics and status codes correctly (safe vs idempotent; 401 vs 403;
              409, 422, 429) and design REST resources with pagination, versioning and
              idempotency keys.
            - Build an HTTP server on raw sockets three ways (blocking, a thread per
              connection, asyncio streams) and benchmark them, next to Node's `http` module.
            - Write a WSGI app and an ASGI app with no framework, add middleware to each, and
              serve them; see exactly what Uvicorn and FastAPI sit on.
            - Pick an HTTP client (`urllib`, `requests`, `httpx`, `aiohttp`) and use it well:
              connection reuse, timeouts, retries, streaming.

            **JS bridge**

            | Node.js | Python | The difference that bites |
            | --- | --- | --- |
            | `net.createServer` | `socket.create_server` / `asyncio.start_server` | Python's plain socket API is blocking by default; Node's is always event-driven |
            | `http.createServer((req, res) => …)` | a WSGI or ASGI callable | Python separates the **server** (Gunicorn, Uvicorn) from the **app** by a standard interface |
            | `req.on("data")` / streams | ASGI `receive()` messages with `more_body` | the body arrives as messages you pull, not events pushed at you |
            | Express / Fastify / NestJS | Flask / Starlette + FastAPI / Django, Litestar | FastAPI validates with type hints (like zod + NestJS DTOs) |
            | `fetch` / `undici` / `axios` | `httpx` (sync and async), `requests` | `requests` has **no default timeout**; always pass one |
            | `ws` / Socket.IO | ASGI `websocket` scope | WebSockets are part of the ASGI interface itself |

            Run the three setup cells before the sections below. The first is the local shop
            API from Unit 4.6 (copied unchanged): a `BaseHTTPRequestHandler` served by
            `ThreadingHTTPServer` in a daemon thread on `127.0.0.1:18046`, used as a real
            HTTP/1.1 server to talk to.
            """
        ),
        code(SHOP_API_SOURCE),
        md(
            """
            Unit setup, part 1: imports, the scratch folder `notebooks/_scratch/phase6/`
            (git-ignored; `%%writefile` cells save demo apps there), flags for optional
            packages, and `SHOP_API`, the base URL of the shop API.
            """
        ),
        code(UNIT_SETUP_SOURCE),
        md(
            """
            Unit setup, part 2: the error and timing helpers shared since earlier phases
            (`raised_error_name`, `raised_message`, `interpreter_label`, `Timer`),
            `fresh_import` (re-imports a `%%writefile` module) and `mask_dates`, which hides the
            parts of raw HTTP output that change on every run (the `Date` header, ports).
            """
        ),
        code(UNIT_SETUP_SOURCE_2),
        md(
            """
            Unit setup, part 3: the **server helpers** every Phase 6 unit uses.

            | Helper | What it does |
            | --- | --- |
            | `free_port()` | asks the OS for an unused port (bind to port 0) |
            | `wait_for_health(url, process)` | polls `url` until it answers 200; fails fast if the process died |
            | `background_server(command, port)` | context manager: starts the process, waits for `/health`, yields the base URL, **always** terminates the process in `finally` |
            | `uvicorn_server("module:app")` | `background_server` for `python -m uvicorn module:app` on a free port |

            Server output goes to a log file in the scratch folder (a pipe nobody reads can
            fill up and freeze the server); when a server fails to start, the helper prints the
            end of its log.
            """
        ),
        code(SERVER_HELPERS_SOURCE + "\n" + SETUP_REPORT_SOURCE),
    ]


def _networking_cells() -> list[NotebookNode]:
    """6.1.1 Networking basics."""
    return [
        md(
            """
            ### 6.1.1 Networking basics

            An HTTP request is the top of a stack of protocols. Each layer only talks to the
            layer below it:

            | Layer | Protocol | What it gives you | Python |
            | --- | --- | --- | --- |
            | Application | HTTP/1.1, HTTP/2, WebSocket | requests, responses, headers | `http.client`, `httpx`, your framework |
            | Security (optional) | TLS 1.2 / 1.3 | encryption, server identity (certificates) | `ssl` |
            | Transport | **TCP** (or UDP) | a reliable, ordered **byte stream** between two ports | `socket.SOCK_STREAM` |
            | Internet | IPv4 / IPv6 | delivery of packets between addresses | `socket.AF_INET`, `AF_INET6` |
            | Link | Ethernet, Wi-Fi, loopback | frames on one network | the OS |

            - A **port** (0–65535) picks the program on a host: 80 for HTTP, 443 for HTTPS, 8000
              is the Uvicorn default. A connection is identified by four numbers: client
              address and **ephemeral port** (picked by the OS), server address and port.
            - **DNS** turns a name into addresses. `getaddrinfo` returns every address to try
              (IPv6 and IPv4) for a name and port.
            - **TCP** is a byte stream with no message boundaries. Everything HTTP does to mark
              "where a request ends" (CRLF lines, `Content-Length`, chunked encoding) exists
              because TCP will not do it.
            - **TLS** sits between TCP and HTTP: a handshake agrees on keys and proves the
              server's identity with a certificate; then every byte is encrypted.

            ```mermaid
            flowchart LR
                Client["httpx / browser"] -->|"HTTP bytes"| TLSc["TLS"]
                TLSc -->|"encrypted bytes"| TCPc["TCP :54321"]
                TCPc -->|"IP packets"| TCPs["TCP :443"]
                TCPs --> TLSs["TLS"]
                TLSs -->|"HTTP bytes"| Server["Uvicorn → your app"]
            ```

            <details><summary>ASCII version</summary>

            ```text
            client app ──HTTP──▶ TLS ──▶ TCP (ephemeral port) ══ IP ══▶ TCP :443 ──▶ TLS ──▶ server app
            ```

            </details>

            `getaddrinfo` for `localhost` (no network needed). The list order and whether IPv6
            appears depend on the OS configuration:
            """
        ),
        code(
            """
            for family, kind, _proto, _canonical_name, address in socket.getaddrinfo(
                "localhost", 8000, type=socket.SOCK_STREAM
            ):
                print(f"{family.name:<9} {kind.name:<12} {address}")
            print(f"{socket.getservbyname('http')=}  {socket.getservbyname('https')=}")
            """
        ),
        md(
            """
            #### The socket API

            | Step | Server | Client | Node `net` |
            | --- | --- | --- | --- |
            | create | `socket.socket(AF_INET, SOCK_STREAM)` | same | `net.createServer()` / `new net.Socket()` |
            | address | `bind(("127.0.0.1", port))` | — | `server.listen(port)` |
            | wait | `listen(backlog)` then `accept()` → new socket per client | `connect((host, port))` | `"connection"` event |
            | talk | `recv(n)` / `sendall(data)` | same | `"data"` event / `write()` |
            | finish | `close()` | `close()` | `end()` |

            `socket.create_server` and `socket.create_connection` wrap the first three steps.
            Below, an echo server runs in a thread; the client sends bytes and reads them back.
            The client's port is an ephemeral port the OS picked, so it changes on every run:
            """
        ),
        code(
            '''
            def echo_once(server_socket: socket.socket) -> None:
                """Accept one client, echo what it sends in upper case, then close."""
                connection, _client_address = server_socket.accept()
                with connection:
                    data = connection.recv(1024)
                    connection.sendall(data.upper())


            with socket.create_server(("127.0.0.1", 0)) as echo_server:
                server_port = echo_server.getsockname()[1]
                echo_thread = threading.Thread(target=echo_once, args=(echo_server,))
                echo_thread.start()
                with socket.create_connection(("127.0.0.1", server_port), timeout=5) as client:
                    client.sendall(b"hello tcp")
                    reply = client.recv(1024)
                    client_port = client.getsockname()[1]
                echo_thread.join()
            print(f"{reply=}")
            print(f"the client got an ephemeral port from the OS: {client_port > 1024=}")
            '''
        ),
        md(
            """
            **TCP has no message boundaries.** The client below calls `sendall` twice; the
            server waits a moment and then reads once. It gets both writes glued together,
            because TCP delivers a stream of bytes, not messages. HTTP therefore needs its own
            framing: a blank line ends the headers, and `Content-Length` (or chunked encoding)
            says where the body ends. (On a loaded machine the read could, in rare cases, return
            only the first part; that is exactly why a server must loop until it has a whole
            request.)
            """
        ),
        code(
            '''
            def read_after_pause(server_socket: socket.socket, received: list[bytes]) -> None:
                """Accept one client, wait 100 ms so both writes arrive, then read once."""
                connection, _client_address = server_socket.accept()
                with connection:
                    time.sleep(0.1)
                    received.append(connection.recv(1024))


            received_chunks: list[bytes] = []
            with socket.create_server(("127.0.0.1", 0)) as stream_server:
                reader_thread = threading.Thread(target=read_after_pause, args=(stream_server, received_chunks))
                reader_thread.start()
                with socket.create_connection(stream_server.getsockname(), timeout=5) as client:
                    client.sendall(b"hello")
                    client.sendall(b"world")
                reader_thread.join()
            print(f"{received_chunks=}")
            '''
        ),
        md(
            """
            For contrast, **UDP** (`SOCK_DGRAM`) keeps message boundaries but promises no
            delivery or order. DNS queries use it, and so does HTTP/3 (through QUIC). Each
            `recvfrom` returns exactly one datagram:
            """
        ),
        code(
            """
            with (
                socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_server,
                socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_client,
            ):
                udp_server.bind(("127.0.0.1", 0))
                udp_server.settimeout(5)
                for datagram in (b"hello", b"world"):
                    udp_client.sendto(datagram, udp_server.getsockname())
                datagrams = [udp_server.recvfrom(1024)[0] for _ in range(2)]
            print(f"{datagrams=}")
            """
        ),
        md(
            """
            #### TLS in one cell

            A TLS 1.3 handshake, simplified: the client sends *ClientHello* (versions, ciphers,
            the server name it wants (**SNI**), the application protocols it speaks (**ALPN**:
            `h2`, `http/1.1`)); the server answers with its certificate and key share; both
            derive the same keys; from then on every record is encrypted. The client checks
            that the certificate is signed by a trusted authority **and** names the host it
            dialled.

            `ssl.create_default_context()` gives safe client defaults: certificate checks on,
            hostname checks on, old protocol versions off:
            """
        ),
        code(
            """
            client_context = ssl.create_default_context()
            print(f"{ssl.OPENSSL_VERSION=}")
            print(f"{client_context.minimum_version=}")
            print(f"{client_context.verify_mode=}  {client_context.check_hostname=}")
            print(f"{ssl.HAS_ALPN=}  {ssl.HAS_TLSv1_3=}")
            """
        ),
        md(
            """
            A real handshake on `127.0.0.1`. The cell creates a throwaway self-signed
            certificate for `localhost` with the `openssl` command (skipped if it is missing),
            starts a TLS echo server in a thread, and connects twice: once with the default
            context (fails: the certificate is not signed by a trusted authority), once with a
            context that trusts this one certificate. The negotiated version, cipher and ALPN
            protocol are printed. Nothing secret is stored: the key lives in the scratch folder
            and is regenerated every run.
            """
        ),
        code(
            '''
            def make_localhost_certificate(folder: Path) -> tuple[Path, Path] | None:
                """Create a 1-day self-signed certificate for localhost; None without openssl."""
                if not HAS_OPENSSL:
                    return None
                cert_path, key_path = folder / "localhost.crt", folder / "localhost.key"
                subprocess.run(
                    [
                        "openssl",
                        "req",
                        "-x509",
                        "-newkey",
                        "rsa:2048",
                        "-nodes",
                        "-days",
                        "1",
                        "-keyout",
                        str(key_path),
                        "-out",
                        str(cert_path),
                        "-subj",
                        "/CN=localhost",
                        "-addext",
                        "subjectAltName=DNS:localhost",
                    ],
                    check=True,
                    capture_output=True,
                )
                return cert_path, key_path


            def tls_echo_once(server_socket: socket.socket, server_context: ssl.SSLContext) -> None:
                """Accept one client, do the TLS handshake, echo one message."""
                connection, _client_address = server_socket.accept()
                try:
                    with server_context.wrap_socket(connection, server_side=True) as tls_connection:
                        tls_connection.sendall(tls_connection.recv(1024))
                except ssl.SSLError, OSError:  # the client rejected our certificate
                    connection.close()
            '''
        ),
        md("Run the two connections. (`except A, B:` without brackets is *new in 3.14*, PEP 758.)"),
        code(
            '''
            def tls_round_trip(client_context: ssl.SSLContext, server_context: ssl.SSLContext) -> str:
                """Connect to a one-shot TLS echo server; describe the session or the error."""
                with socket.create_server(("127.0.0.1", 0)) as tls_server:
                    server_thread = threading.Thread(target=tls_echo_once, args=(tls_server, server_context))
                    server_thread.start()
                    try:
                        with (
                            socket.create_connection(tls_server.getsockname(), timeout=5) as raw,
                            client_context.wrap_socket(raw, server_hostname="localhost") as tls,
                        ):
                            tls.sendall(b"secret")
                            echoed = tls.recv(1024)
                            protocol = tls.selected_alpn_protocol()
                            return f"{tls.version()} {tls.cipher()[0]} alpn={protocol} {echoed=}"
                    except ssl.SSLCertVerificationError as error:
                        return f"SSLCertVerificationError: {error.verify_message}"
                    finally:
                        server_thread.join()


            certificate = make_localhost_certificate(PHASE6_DIR)
            if certificate is None:
                print("SKIP: the openssl command is not installed, so no certificate can be made")
            else:
                server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
                server_context.load_cert_chain(*certificate)
                server_context.set_alpn_protocols(["http/1.1"])
                print("default context:", tls_round_trip(ssl.create_default_context(), server_context))
                trusting_context = ssl.create_default_context(cafile=certificate[0])
                trusting_context.set_alpn_protocols(["h2", "http/1.1"])
                print("trusting context:", tls_round_trip(trusting_context, server_context))
            '''
        ),
        md(
            """
            > **Note:** in production TLS usually ends at a load balancer or reverse proxy
            > (nginx, Caddy, a cloud load balancer) and Uvicorn speaks plain HTTP behind it.
            > Uvicorn can also terminate TLS itself (`--ssl-keyfile`, `--ssl-certfile`).
            """
        ),
    ]


def _http_anatomy_cells() -> list[NotebookNode]:
    """6.1.2 HTTP/1.1 anatomy."""
    return [
        md(
            """
            ### 6.1.2 HTTP/1.1 anatomy

            An HTTP/1.1 message is text lines ending in **CRLF** (`\\r\\n`), a blank line, then
            an optional body:

            ```text
            POST /notes?draft=true HTTP/1.1\\r\\n        ← request line: method, target, version
            Host: api.example.com\\r\\n                  ← headers: "Name: value"
            Content-Type: application/json\\r\\n
            Content-Length: 17\\r\\n
            \\r\\n                                       ← blank line: end of headers
            {"title": "Tea"}                         ← body: exactly Content-Length bytes

            HTTP/1.1 201 Created\\r\\n                   ← status line: version, code, reason
            Content-Type: application/json\\r\\n
            Location: /notes/7\\r\\n
            Content-Length: 25\\r\\n
            \\r\\n
            {"id": 7, "title": "Tea"}
            ```

            Header names are case-insensitive; the request line and headers are Latin-1 /
            ASCII bytes; the body is whatever `Content-Type` says (usually UTF-8 JSON).

            Below, a raw request is written by hand to the shop API's socket and the raw
            response is printed exactly as it arrives (the `Date` header is masked):
            """
        ),
        code(
            '''
            def raw_http_exchange(base_url: str, raw_request: bytes) -> bytes:
                """Send raw_request on a fresh TCP connection and return every byte of the reply."""
                address = urllib.parse.urlsplit(base_url)
                with socket.create_connection((address.hostname, address.port), timeout=5) as sock:
                    sock.sendall(raw_request)
                    reply = b""
                    while chunk := sock.recv(4096):  # the server closes: Connection: close
                        reply += chunk
                return reply


            raw_request = (
                b"GET /rates?base=INR HTTP/1.1\\r\\n"
                b"Host: 127.0.0.1\\r\\n"
                b"Accept: application/json\\r\\n"
                b"Connection: close\\r\\n"
                b"\\r\\n"
            )
            raw_reply = raw_http_exchange(SHOP_API, raw_request)
            print(mask_dates(raw_reply.decode("latin-1")))
            '''
        ),
        md(
            """
            The same reply with escapes visible: every line ends with `\\r\\n` and the head
            ends with `\\r\\n\\r\\n`. Splitting on that marker separates head and body; the
            body length matches `Content-Length`:
            """
        ),
        code(
            """
            head, _, body = raw_reply.partition(b"\\r\\n\\r\\n")
            status_line, *header_lines = head.split(b"\\r\\n")
            print(f"{status_line=}")
            print(f"{header_lines[0]=}")
            content_length = next(
                int(line.split(b":")[1]) for line in header_lines if line.lower().startswith(b"content-length")
            )
            print(f"{content_length=}  {len(body)=}")
            show_size("raw request bytes", raw_request)
            """
        ),
        md(
            """
            #### Method semantics

            | Method | Safe (no state change) | Idempotent (repeat = same effect) | Body | Typical use |
            | --- | --- | --- | --- | --- |
            | `GET` | yes | yes | no | read a resource or a list |
            | `HEAD` | yes | yes | no | headers only (size, `ETag`) |
            | `OPTIONS` | yes | yes | no | CORS preflight, allowed methods |
            | `POST` | no | **no** | yes | create, or "do this action" |
            | `PUT` | no | yes | yes | replace a resource at a known URL |
            | `PATCH` | no | not by rule (usually yes) | yes | change some fields |
            | `DELETE` | no | yes | rare | remove (the second call: 404 or 204, same server state) |

            **Safe** methods may be prefetched and cached. **Idempotent** requests can be
            retried after a timeout without fear; a `POST` cannot, unless it carries an
            idempotency key (6.1.3). `http.HTTPMethod` (*new in 3.11*) lists the methods with
            their descriptions:
            """
        ),
        code(
            """
            IDEMPOTENT_METHODS = {"GET", "HEAD", "OPTIONS", "PUT", "DELETE", "TRACE"}
            SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
            for method in (
                http.HTTPMethod.GET,
                http.HTTPMethod.POST,
                http.HTTPMethod.PUT,
                http.HTTPMethod.PATCH,
                http.HTTPMethod.DELETE,
            ):
                safe = "safe" if method in SAFE_METHODS else "unsafe"
                repeat = "idempotent" if method in IDEMPOTENT_METHODS else "not idempotent"
                print(f"{method:<7} {safe:<7} {repeat:<15} {method.description}")
            """
        ),
        md(
            """
            #### Status codes

            | Class | Meaning | Common codes |
            | --- | --- | --- |
            | 1xx | informational | 101 Switching Protocols (WebSocket upgrade) |
            | 2xx | success | 200 OK, 201 Created (+ `Location`), 202 Accepted, 204 No Content |
            | 3xx | redirection | 301/308 permanent, 302/307 temporary, 304 Not Modified |
            | 4xx | **client** error: fix the request | 400, 401, 403, 404, 405, 409, 413, 415, 422, 429 |
            | 5xx | **server** error: retrying may help | 500, 502, 503 (+ `Retry-After`), 504 |

            The pairs people mix up:

            | Code | Means | Example |
            | --- | --- | --- |
            | **401** Unauthorized | "who are you?": no or bad credentials; send `WWW-Authenticate` | missing or expired token |
            | **403** Forbidden | "I know who you are, and no" | a user deleting someone else's note |
            | **409** Conflict | the request clashes with the current state | username taken; stale version |
            | **422** Unprocessable Content | well-formed JSON, invalid values | `"limit": -5`; FastAPI's validation errors |
            | **429** Too Many Requests | rate limit hit; send `Retry-After` | 101st call in a minute |

            `HTTPStatus` (*`is_success`, `is_client_error`, … new in 3.12*) knows every code.
            *Changed in 3.13:* 422's phrase is now "Unprocessable Content" (RFC 9110), and 413
            is "Content Too Large":
            """
        ),
        code(
            """
            for status_code in (200, 201, 204, 301, 304, 400, 401, 403, 404, 409, 413, 422, 429, 503):
                status = HTTPStatus(status_code)
                kind = next(
                    label
                    for label, matches in (
                        ("success", status.is_success),
                        ("redirect", status.is_redirection),
                        ("client error", status.is_client_error),
                        ("server error", status.is_server_error),
                    )
                    if matches
                )
                print(f"{status.value} {status.phrase:<22} {kind}")
            """
        ),
        md(
            """
            #### Key headers

            | Header | Direction | Purpose |
            | --- | --- | --- |
            | `Host` | request | which site (required in HTTP/1.1: many sites share one IP) |
            | `Content-Type` / `Content-Length` | both | what the body is / how many bytes |
            | `Accept`, `Accept-Encoding`, `Accept-Language` | request | content negotiation |
            | `Authorization` | request | credentials (`Bearer <token>`) |
            | `Cookie` / `Set-Cookie` | request / response | session state |
            | `Cache-Control`, `ETag`, `If-None-Match` | both | caching and conditional requests (304) |
            | `Location` | response | the new resource (201) or the redirect target (3xx) |
            | `Retry-After` | response | when to retry (429, 503) |
            | `Connection`, `Keep-Alive` | both | reuse the TCP connection or close it |
            | `Transfer-Encoding: chunked` | both | body length not known in advance |

            **Keep-alive.** HTTP/1.1 connections stay open by default, so several requests
            can reuse one TCP (and TLS) handshake. The shop API counts TCP connections at
            `/connections`. Three requests on one `http.client.HTTPConnection` open one
            connection; three separate `urlopen` calls (which send `Connection: close`) open
            three:
            """
        ),
        code(
            '''
            def shop_connection_count() -> int:
                """How many TCP connections the shop API has accepted so far."""
                with NO_PROXY_OPENER.open(f"{SHOP_API}/connections", timeout=5) as response:
                    return json.load(response)["connections"]


            shop_address = urllib.parse.urlsplit(SHOP_API)
            before = shop_connection_count()
            keep_alive = http.client.HTTPConnection(shop_address.hostname, shop_address.port, timeout=5)
            for _ in range(3):
                keep_alive.request("GET", "/rates")
                keep_alive.getresponse().read()  # read the body before reusing the connection
            keep_alive.close()
            reused = shop_connection_count() - before - 1  # minus the counting request itself

            before = shop_connection_count()
            for _ in range(3):
                with NO_PROXY_OPENER.open(f"{SHOP_API}/rates", timeout=5) as response:
                    response.read()
            separate = shop_connection_count() - before - 1
            print(f"keep-alive: 3 requests used {reused} connection(s)")
            print(f"urlopen:    3 requests used {separate} connection(s)")
            '''
        ),
        md(
            """
            **Chunked transfer encoding.** When a server does not know the body length up
            front (a stream, a large export), it sends `Transfer-Encoding: chunked`: each
            chunk is its size in hex, CRLF, the bytes, CRLF; a zero-size chunk ends the body.
            A hand-written encoder and decoder (Uvicorn produces this automatically in 6.1.6):
            """
        ),
        code(
            '''
            def encode_chunked(parts: Iterable[bytes]) -> bytes:
                """Encode parts as an HTTP/1.1 chunked body (size in hex, CRLF, data, CRLF)."""
                encoded = b"".join(b"%x\\r\\n%s\\r\\n" % (len(part), part) for part in parts if part)
                return encoded + b"0\\r\\n\\r\\n"


            def decode_chunked(data: bytes) -> bytes:
                """Decode a complete chunked body back into the original bytes."""
                decoded, position = b"", 0
                while True:
                    line_end = data.index(b"\\r\\n", position)
                    size = int(data[position:line_end], 16)
                    if size == 0:
                        return decoded
                    decoded += data[line_end + 2 : line_end + 2 + size]
                    position = line_end + 2 + size + 2  # skip the data and its CRLF


            chunked_body = encode_chunked([b"first line\\n", b"second, longer line\\n"])
            print(f"{chunked_body=}")
            print(f"{decode_chunked(chunked_body)=}")
            '''
        ),
        md(
            """
            **Content negotiation.** The client lists what it accepts with quality values
            (`q`, default 1); the server picks the best match it can produce, or answers
            **406 Not Acceptable**. A small negotiator:
            """
        ),
        code(
            '''
            def negotiate(accept_header: str, available: list[str]) -> str | None:
                """Pick the available media type the Accept header prefers most (None → 406)."""
                preferences: list[tuple[float, str]] = []
                for item in accept_header.split(","):
                    media_type, *parameters = (piece.strip() for piece in item.split(";"))
                    quality = 1.0
                    for parameter in parameters:
                        name, _, value = parameter.partition("=")
                        if name.strip() == "q":
                            quality = float(value)
                    preferences.append((quality, media_type))
                for quality, media_type in sorted(preferences, key=lambda pair: -pair[0]):
                    for candidate in available:
                        pattern = media_type.replace("*", ".*")
                        if quality > 0 and re.fullmatch(pattern, candidate):
                            return candidate
                return None


            produced = ["application/json", "text/csv"]
            for accept in ("text/csv;q=0.9, application/json", "text/*", "*/*", "image/png"):
                print(f"{accept!r:<40} -> {negotiate(accept, produced)}")
            '''
        ),
        md(
            """
            #### HTTP/2 and HTTP/3

            | | HTTP/1.1 | HTTP/2 | HTTP/3 |
            | --- | --- | --- | --- |
            | Wire format | text lines | binary frames | binary frames |
            | Transport | TCP | TCP (+ TLS in practice) | **QUIC over UDP** (TLS 1.3 built in) |
            | Requests per connection | one at a time (pipelining unused) | many, **multiplexed** as streams | many, and a lost packet stalls only its own stream |
            | Headers | repeated as text | compressed (HPACK) | compressed (QPACK) |
            | Picked by | default | ALPN `h2` during the TLS handshake | `Alt-Svc` header, then QUIC |

            The semantics (methods, status codes, headers) are the same in all three; only
            the framing changes, so your FastAPI code never sees the difference. Uvicorn speaks
            HTTP/1.1 (and WebSocket); HTTP/2 and HTTP/3 are usually terminated by the proxy in
            front (or by servers such as Hypercorn and Granian).

            What an HTTP/1.1-only server does with the HTTP/2 *connection preface* (the fixed
            bytes an HTTP/2 client sends first when it already knows the server speaks h2):
            """
        ),
        code(
            """
            HTTP2_PREFACE = b"PRI * HTTP/2.0\\r\\n\\r\\nSM\\r\\n\\r\\n"
            preface_reply = raw_http_exchange(SHOP_API, HTTP2_PREFACE)
            print(mask_dates(preface_reply.decode("latin-1")).splitlines()[0])
            """
        ),
    ]


def _rest_cells() -> list[NotebookNode]:
    """6.1.3 REST design."""
    return [
        md(
            """
            ### 6.1.3 REST design

            REST models an API as **resources** (nouns with URLs) manipulated through the
            standard **verbs**. The Notes API (started in Unit 6.2) follows this table:

            | Verb | URL | CRUD | Success | Notes |
            | --- | --- | --- | --- | --- |
            | `GET` | `/notes` | read (list) | 200 | filtering, sorting, pagination in the query string |
            | `POST` | `/notes` | create | 201 + `Location: /notes/7` | not idempotent |
            | `GET` | `/notes/7` | read (one) | 200 / 404 | |
            | `PUT` | `/notes/7` | replace | 200 | send the whole resource |
            | `PATCH` | `/notes/7` | update | 200 | send only the changed fields |
            | `DELETE` | `/notes/7` | delete | 204 | |
            | `GET` | `/notes/7/tags` | sub-resource | 200 | nesting shows ownership; keep it shallow |

            Rules of thumb:

            - **Plural nouns, no verbs** in paths (`/notes`, not `/getNotes`); actions that do
              not fit CRUD become sub-resources (`POST /notes/7/archive`).
            - **Stateless:** every request carries everything needed (auth token, ids); the
              server keeps no per-client conversation state between requests, so any instance
              behind a load balancer can answer.
            - **Filtering and sorting** go in the query string:
              `GET /notes?tag=work&pinned=true&sort=-created_at`.
            - **Pagination:** `limit` + `offset` (simple, can skip or repeat rows when data
              changes) or a **cursor** (an opaque token for "after this row"; stable and fast).
              Return the total or a `next` link, and/or a `Link` header.
            - **Versioning:** in the path (`/v1/notes`, the most common), in a header
              (`Api-Version: 2`), or in the media type (`Accept: application/vnd.notes.v2+json`).
              Add fields freely; remove or rename only in a new version.
            - **Idempotency keys:** the client sends `Idempotency-Key: <uuid>` with a `POST`; the
              server stores the first response under that key and replays it for retries, so a
              timed-out payment or note creation is never done twice.

            Pagination helpers: an offset `Link` header and an opaque cursor (base64 of JSON,
            so clients cannot depend on its contents):
            """
        ),
        code(
            '''
            def pagination_links(base_url: str, total: int, limit: int, offset: int) -> str:
                """Build an RFC 8288 Link header with first/prev/next/last for limit/offset paging."""
                last_offset = max(0, (total - 1) // limit * limit)
                pages = {"first": 0, "last": last_offset}
                if offset > 0:
                    pages["prev"] = max(0, offset - limit)
                if offset + limit < total:
                    pages["next"] = offset + limit
                return ", ".join(
                    f'<{base_url}?limit={limit}&offset={page_offset}>; rel="{relation}"'
                    for relation, page_offset in pages.items()
                )


            def encode_cursor(position: dict[str, object]) -> str:
                """Opaque cursor: URL-safe base64 of compact JSON."""
                return base64.urlsafe_b64encode(json.dumps(position, separators=(",", ":")).encode()).decode()


            def decode_cursor(cursor: str) -> dict[str, object]:
                """Inverse of encode_cursor."""
                return json.loads(base64.urlsafe_b64decode(cursor))


            print(pagination_links("/notes", total=95, limit=20, offset=40))
            cursor = encode_cursor({"created_at": "2026-11-17T09:00:00Z", "id": 41})
            print(f"{cursor=}")
            print(f"{decode_cursor(cursor)=}")
            '''
        ),
        md(
            """
            An idempotency-key store in a few lines. The first request with a key runs the
            handler and remembers its response; a retry with the same key and the same body
            gets the stored response (the note is not created twice); the same key with a
            *different* body is a client bug, answered with **422**:
            """
        ),
        code(
            '''
            @dataclasses.dataclass
            class IdempotencyStore:
                """Remember (request fingerprint, response) per Idempotency-Key."""

                responses: dict[str, tuple[str, tuple[int, dict[str, object]]]] = dataclasses.field(
                    default_factory=dict
                )

                def run(
                    self,
                    key: str,
                    body: dict[str, object],
                    handler: Callable[[], tuple[int, dict[str, object]]],
                ) -> tuple[int, dict[str, object]]:
                    """Run handler once per key; replay its response for identical retries."""
                    fingerprint = json.dumps(body, sort_keys=True)
                    if key in self.responses:
                        stored_fingerprint, stored_response = self.responses[key]
                        if stored_fingerprint != fingerprint:
                            return 422, {"error": "Idempotency-Key reused with a different body"}
                        return stored_response
                    response = handler()
                    self.responses[key] = (fingerprint, response)
                    return response


            created_notes: list[dict[str, object]] = []


            def create_note(body: dict[str, object]) -> tuple[int, dict[str, object]]:
                """Pretend handler: store a note and answer 201."""
                created_notes.append({"id": len(created_notes) + 1, **body})
                return 201, created_notes[-1]


            store = IdempotencyStore()
            first = store.run("key-7f3a", {"title": "Tea"}, lambda: create_note({"title": "Tea"}))
            retry = store.run("key-7f3a", {"title": "Tea"}, lambda: create_note({"title": "Tea"}))
            misuse = store.run("key-7f3a", {"title": "Coffee"}, lambda: create_note({"title": "Coffee"}))
            print(f"{first=}\\n{retry=}\\n{misuse=}\\n{len(created_notes)=}")
            '''
        ),
        md(
            """
            #### REST vs RPC vs GraphQL

            | Style | Shape | Strengths | Costs | Python |
            | --- | --- | --- | --- | --- |
            | **REST** | resources + verbs, many URLs | HTTP caching, status codes, simple tooling, OpenAPI | over/under-fetching; several calls for a screen | FastAPI, Django REST framework |
            | **RPC** (JSON-RPC, gRPC) | one endpoint (or one per method), "call this function" | natural for actions; gRPC is fast and typed (Protobuf, HTTP/2) | no HTTP caching; errors hidden in bodies | `grpcio`, plain FastAPI `POST /rpc` |
            | **GraphQL** | one `POST /graphql`, client sends a query | client picks exactly the fields; one round trip | caching and rate limiting are harder; N+1 queries on the server | Strawberry, Graphene |

            The same question, "title of note 7", in the three styles:
            """
        ),
        code(
            """
            rest_request = "GET /notes/7"
            rpc_request = {"jsonrpc": "2.0", "method": "notes.get", "params": {"id": 7}, "id": 1}
            graphql_request = {"query": "query { note(id: 7) { title } }"}
            print(f"REST:    {rest_request}   (the response has every field of note 7)")
            print(f"RPC:     POST /rpc     {json.dumps(rpc_request)}")
            print(f"GraphQL: POST /graphql {json.dumps(graphql_request)}")
            """
        ),
    ]


RAW_HTTP_MODULE = r'''
%%writefile _scratch/phase6/raw_http.py
"""Hand-written HTTP/1.1 servers on raw sockets: blocking, thread-per-connection, asyncio.

Run one with:  python raw_http.py blocking|threaded|asyncio PORT
"""

import asyncio
import contextlib
import json
import socket
import sys
import threading
import time
from http import HTTPStatus
from urllib.parse import parse_qsl, urlsplit

type RouteResult = tuple[int, object, float]  # status, JSON payload, seconds of simulated I/O


def parse_head(head: bytes) -> tuple[str, str, dict[str, str]]:
    """Split a request head (without the blank line) into method, target and headers."""
    request_line, *header_lines = head.decode("latin-1").split("\r\n")
    method, target, _version = request_line.split(" ", 2)
    headers: dict[str, str] = {}
    for line in header_lines:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    return method, target, headers


def route(method: str, target: str, body: bytes) -> RouteResult:
    """The application: map (method, path) to (status, payload, simulated I/O wait)."""
    url = urlsplit(target)
    query = dict(parse_qsl(url.query))
    match method, url.path:
        case "GET", "/health":
            return 200, {"status": "ok"}, 0.0
        case "GET", "/hello":
            return 200, {"message": f"hello, {query.get('name', 'world')}"}, 0.0
        case "GET", "/slow":  # stands in for a database query or a call to another service
            milliseconds = float(query.get("ms", "50"))
            return 200, {"slept_ms": milliseconds}, milliseconds / 1000
        case "POST", "/echo":
            try:
                return 200, {"received": json.loads(body or b"null")}, 0.0
            except json.JSONDecodeError:
                return 400, {"error": "body is not valid JSON"}, 0.0
        case _:
            return 404, {"error": f"no route {method} {url.path}"}, 0.0


def build_response(status: int, payload: object) -> bytes:
    """Serialize a JSON response: status line, headers, blank line, body."""
    body = json.dumps(payload).encode()
    head = (
        f"HTTP/1.1 {status} {HTTPStatus(status).phrase}\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n"
        "\r\n"
    )
    return head.encode("latin-1") + body


def read_request(connection: socket.socket) -> tuple[str, str, bytes] | None:
    """Read one request: bytes up to the blank line, then Content-Length more bytes."""
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = connection.recv(65536)
        if not chunk:
            return None  # the client closed before sending a whole head
        data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    method, target, headers = parse_head(head)
    content_length = int(headers.get("content-length", "0"))
    while len(body) < content_length:
        chunk = connection.recv(65536)
        if not chunk:
            return None
        body += chunk
    return method, target, body[:content_length]


def handle_connection(connection: socket.socket) -> None:
    """Serve one request on a connection with blocking calls, then close it."""
    with connection:
        request = read_request(connection)
        if request is None:
            return
        status, payload, wait_seconds = route(*request)
        if wait_seconds:
            time.sleep(wait_seconds)  # blocking wait: this thread can do nothing else
        connection.sendall(build_response(status, payload))


def serve_blocking(port: int) -> None:
    """One connection at a time: later clients wait in the kernel's listen backlog."""
    with socket.create_server(("127.0.0.1", port), backlog=128) as server:
        while True:
            connection, _client_address = server.accept()
            handle_connection(connection)


def serve_threaded(port: int) -> None:
    """A new thread per connection: blocking code, but clients are served concurrently."""
    with socket.create_server(("127.0.0.1", port), backlog=128) as server:
        while True:
            connection, _client_address = server.accept()
            threading.Thread(target=handle_connection, args=(connection,), daemon=True).start()


async def handle_stream(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Serve one request with asyncio streams: every wait is an await."""
    try:
        head = await reader.readuntil(b"\r\n\r\n")
        method, target, headers = parse_head(head[:-4])
        body = await reader.readexactly(int(headers.get("content-length", "0")))
        status, payload, wait_seconds = route(method, target, body)
        if wait_seconds:
            await asyncio.sleep(wait_seconds)  # the loop serves other clients meanwhile
        writer.write(build_response(status, payload))
        await writer.drain()
    except asyncio.IncompleteReadError:
        pass  # the client went away
    finally:
        writer.close()
        with contextlib.suppress(ConnectionError):
            await writer.wait_closed()


async def serve_asyncio(port: int) -> None:
    """One thread, one event loop, any number of connections."""
    server = await asyncio.start_server(handle_stream, "127.0.0.1", port, backlog=128)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    mode, port_text = sys.argv[1], sys.argv[2]
    if mode == "asyncio":
        asyncio.run(serve_asyncio(int(port_text)))
    else:
        {"blocking": serve_blocking, "threaded": serve_threaded}[mode](int(port_text))
'''

NODE_HTTP_MODULE = r"""
%%writefile _scratch/phase6/node_http.mjs
// The same routes with Node's built-in http module, for the benchmark below.
import http from "node:http";

const port = Number(process.argv[2]);

http
  .createServer((request, response) => {
    const url = new URL(request.url, "http://127.0.0.1");
    const send = (status, payload) => {
      const body = JSON.stringify(payload);
      response.writeHead(status, {
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(body),
        Connection: "close",
      });
      response.end(body);
    };
    if (request.method === "GET" && url.pathname === "/health") return send(200, { status: "ok" });
    if (request.method === "GET" && url.pathname === "/slow") {
      const milliseconds = Number(url.searchParams.get("ms") ?? 50);
      return setTimeout(() => send(200, { slept_ms: milliseconds }), milliseconds);
    }
    send(404, { error: `no route ${request.method} ${url.pathname}` });
  })
  .listen(port, "127.0.0.1");
"""

WSGI_MODULE = r'''
%%writefile _scratch/phase6/wsgi_demo.py
"""A WSGI application and a WSGI middleware written by hand (PEP 3333)."""

import json
import time
import uuid
from collections.abc import Callable, Iterable
from typing import Any
from urllib.parse import parse_qs

type Environ = dict[str, Any]
type StartResponse = Callable[..., Callable[[bytes], object]]
type WSGIApp = Callable[[Environ, StartResponse], Iterable[bytes]]


def json_response(start_response: StartResponse, status: str, payload: object) -> list[bytes]:
    """Call start_response with JSON headers and return the body as a one-item list."""
    body = json.dumps(payload).encode()
    headers = [("Content-Type", "application/json"), ("Content-Length", str(len(body)))]
    start_response(status, headers)
    return [body]


def app(environ: Environ, start_response: StartResponse) -> Iterable[bytes]:
    """Route on REQUEST_METHOD and PATH_INFO; every value comes from the environ dict."""
    method, path = environ["REQUEST_METHOD"], environ.get("PATH_INFO", "/")
    query = parse_qs(environ.get("QUERY_STRING", ""))
    if (method, path) == ("GET", "/health"):
        return json_response(start_response, "200 OK", {"status": "ok"})
    if (method, path) == ("GET", "/hello"):
        name = query.get("name", ["world"])[0]
        request_id = environ.get("app.request_id")
        return json_response(start_response, "200 OK", {"message": f"hello, {name}", "id": request_id})
    if (method, path) == ("GET", "/slow"):
        time.sleep(float(query.get("ms", ["100"])[0]) / 1000)  # blocks this worker thread
        return json_response(start_response, "200 OK", {"slow": True})
    if (method, path) == ("POST", "/echo"):
        length = int(environ.get("CONTENT_LENGTH") or 0)
        raw_body = environ["wsgi.input"].read(length)  # a blocking file-like object
        return json_response(start_response, "200 OK", {"received": json.loads(raw_body or b"null")})
    return json_response(start_response, "404 Not Found", {"error": f"no route {method} {path}"})


class RequestIdMiddleware:
    """Give every request an id (the client's X-Request-ID, or a new one) and echo it back."""

    def __init__(self, app: WSGIApp, make_id: Callable[[], str] = lambda: uuid.uuid4().hex) -> None:
        """Wrap app; make_id creates ids for requests that bring none."""
        self.app = app
        self.make_id = make_id

    def __call__(self, environ: Environ, start_response: StartResponse) -> Iterable[bytes]:
        """Add the id to the environ (for the app) and to the response headers."""
        request_id = environ.get("HTTP_X_REQUEST_ID") or self.make_id()
        environ["app.request_id"] = request_id

        def start_response_with_id(
            status: str, headers: list[tuple[str, str]], exc_info: object = None
        ) -> Callable[[bytes], object]:
            """Call the server's start_response with one more header."""
            return start_response(status, [*headers, ("X-Request-ID", request_id)], exc_info)

        return self.app(environ, start_response_with_id)


application = RequestIdMiddleware(app)  # the object a WSGI server (Gunicorn, uWSGI) loads
'''

ASGI_MODULE = r'''
%%writefile _scratch/phase6/asgi_demo.py
"""An ASGI application written by hand: http, websocket and lifespan scopes, plus middleware."""

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from urllib.parse import parse_qs

type Scope = MutableMapping[str, Any]
type Message = MutableMapping[str, Any]
type Receive = Callable[[], Awaitable[Message]]
type Send = Callable[[Message], Awaitable[None]]
type ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

state: dict[str, Any] = {"requests": 0}  # filled in by the lifespan startup event


async def send_json(send: Send, status: int, payload: object) -> None:
    """Send a complete JSON response: one start message and one body message."""
    body = json.dumps(payload).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


async def read_body(receive: Receive) -> tuple[bytes, int]:
    """Collect the request body from http.request messages; return it and the message count."""
    body, message_count, more_body = b"", 0, True
    while more_body:
        message = await receive()
        body += message.get("body", b"")
        message_count += 1
        more_body = message.get("more_body", False)
    return body, message_count


async def lifespan(scope: Scope, receive: Receive, send: Send) -> None:
    """Startup and shutdown hooks: open pools here, close them on shutdown."""
    while True:
        message = await receive()
        if message["type"] == "lifespan.startup":
            state["started_at"] = time.time()
            await send({"type": "lifespan.startup.complete"})
        elif message["type"] == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.complete"})
            return


async def stream_lines(send: Send, count: int, delay: float) -> None:
    """Stream count lines, one body message each (more_body=True), delay seconds apart."""
    headers = [(b"content-type", b"text/plain; charset=utf-8")]  # no content-length: chunked
    await send({"type": "http.response.start", "status": 200, "headers": headers})
    for number in range(1, count + 1):
        line = f"line {number}\n".encode()
        await send({"type": "http.response.body", "body": line, "more_body": True})
        await asyncio.sleep(delay)
    await send({"type": "http.response.body", "body": b"", "more_body": False})


async def http_app(scope: Scope, receive: Receive, send: Send) -> None:
    """Route plain HTTP requests."""
    state["requests"] += 1
    method, path = scope["method"], scope["path"]
    query = {name: values[0] for name, values in parse_qs(scope["query_string"].decode()).items()}
    if (method, path) == ("GET", "/health"):
        await send_json(send, 200, {"status": "ok"})
    elif (method, path) == ("GET", "/hello"):
        await send_json(send, 200, {"message": f"hello, {query.get('name', 'world')}"})
    elif (method, path) == ("POST", "/echo"):
        body, message_count = await read_body(receive)
        await send_json(send, 200, {"bytes": len(body), "messages": message_count})
    elif (method, path) == ("GET", "/stream"):
        await stream_lines(send, int(query.get("count", "3")), float(query.get("delay", "0.1")))
    elif (method, path) == ("GET", "/stats"):
        lifespan_ran = "started_at" in state
        await send_json(send, 200, {"requests": state["requests"], "lifespan_ran": lifespan_ran})
    else:
        await send_json(send, 404, {"error": f"no route {method} {path}"})


async def websocket_app(scope: Scope, receive: Receive, send: Send) -> None:
    """Echo text frames on /ws; refuse any other path."""
    await receive()  # websocket.connect
    if scope["path"] != "/ws":
        await send({"type": "websocket.close", "code": 1008})
        return
    await send({"type": "websocket.accept"})
    while True:
        message = await receive()
        if message["type"] == "websocket.disconnect":
            return
        await send({"type": "websocket.send", "text": f"echo: {message.get('text')}"})


async def app(scope: Scope, receive: Receive, send: Send) -> None:
    """The ASGI entry point: one coroutine function for every kind of connection."""
    match scope["type"]:
        case "lifespan":
            await lifespan(scope, receive, send)
        case "http":
            await http_app(scope, receive, send)
        case "websocket":
            await websocket_app(scope, receive, send)


class RequestIdMiddleware:
    """ASGI version of the WSGI middleware: wrap send to add an X-Request-ID header."""

    def __init__(self, app: ASGIApp, make_id: Callable[[], str] = lambda: uuid.uuid4().hex) -> None:
        """Wrap app; make_id creates ids for requests that bring none."""
        self.app = app
        self.make_id = make_id

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass non-HTTP scopes through; add the header to http.response.start."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = dict(scope["headers"]).get(b"x-request-id", b"").decode() or self.make_id()

        async def send_with_id(message: Message) -> None:
            """Forward every message; add the header to http.response.start."""
            if message["type"] == "http.response.start":
                headers = [*message.get("headers", []), (b"x-request-id", request_id.encode())]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_id)


application = RequestIdMiddleware(app)  # the object Uvicorn loads
'''


def _raw_server_cells() -> list[NotebookNode]:
    """6.1.4 A raw socket HTTP server."""
    return [
        md(
            """
            ### 6.1.4 A raw socket HTTP server

            Everything a web server does, by hand, in one module:

            1. `accept()` a TCP connection;
            2. read bytes until the blank line (`\\r\\n\\r\\n`), then `Content-Length` more;
            3. **parse** the request line and headers (`parse_head`);
            4. **route** on `(method, path)` with `match` (the dict-dispatch idea from Unit
               1.6.14) and produce a JSON payload (`route`);
            5. **serialize** status line, headers and body (`build_response`) and `sendall`.

            `route` returns how long the request should "wait on I/O" (`/slow?ms=50` stands in
            for a database query) instead of sleeping itself, so each server can wait in its
            own way: `time.sleep` in the blocking and threaded servers, `await asyncio.sleep`
            in the asyncio one. The module ends with the three ways to serve connections:

            | Server | Concurrency | Cost per waiting client | Node equivalent |
            | --- | --- | --- | --- |
            | `serve_blocking` | none: one connection at a time | nothing (it just waits in the backlog) | — |
            | `serve_threaded` | one OS thread per connection | a thread (~8 MiB stack reserved) | — |
            | `serve_asyncio` | one thread, event loop, `asyncio.start_server` | a Task (~1 KB) | `http.createServer` |
            """
        ),
        *writefile_cells(
            RAW_HTTP_MODULE,
            [
                ("", "Part 1 of `raw_http.py`: imports and the request-head parser."),
                ("def route(", "Part 2: the application (`route`) and the response serializer."),
                (
                    "def read_request(",
                    "Part 3: read one request from a blocking socket and serve it.",
                ),
                (
                    "def serve_blocking(",
                    "Part 4: the blocking and threaded servers, and the asyncio handler.",
                ),
                (
                    "async def serve_asyncio(",
                    "Part 5: the asyncio server and the command-line entry point.",
                ),
            ],
        ),
        md(
            """
            The pieces are plain functions, so they can be called without any socket. Parse a
            head, route a request, serialize a response:
            """
        ),
        code(
            r"""
            raw_http = fresh_import("raw_http")
            print(raw_http.parse_head(b"GET /hello?name=Asha HTTP/1.1\r\nHost: x\r\nAccept: */*"))
            print(raw_http.route("GET", "/hello?name=Asha", b""))
            print(raw_http.route("DELETE", "/hello", b""))
            print(raw_http.build_response(201, {"id": 7}))
            """
        ),
        md(
            """
            Now as a real server. `background_server` runs `python raw_http.py blocking PORT`
            in a child process, waits until `GET /health` answers, and stops it at the end of
            the `with` block. Any HTTP client can talk to it, here the stdlib's `http.client`:
            """
        ),
        code(
            '''
            def raw_server_command(mode: str, port: int) -> list[str]:
                """Command line that runs one of the raw servers on port."""
                return [sys.executable, str(PHASE6_DIR / "raw_http.py"), mode, str(port)]


            port = free_port()
            with background_server(raw_server_command("blocking", port), port) as base_url:
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                for method, path, body in (
                    ("GET", "/hello?name=Ravi", None),
                    ("POST", "/echo", b'{"tea": 2}'),
                    ("POST", "/echo", b"{not json"),
                    ("GET", "/nowhere", None),
                ):
                    connection.request(method, path, body=body)
                    response = connection.getresponse()
                    print(f"{method:<4} {path:<17} -> {response.status} {response.read().decode()}")
                    connection.close()  # our server sends Connection: close
            '''
        ),
        md(
            """
            #### The same server in Node

            For comparison, Node's `http` module with the routes the benchmark uses. Node
            parses the request for you and calls the handler; the handler never blocks, because
            the only way to wait in Node is a callback or a promise (`setTimeout` here). That is
            the asyncio model with the event loop hidden:

            | Raw Python server | Node `http` |
            | --- | --- |
            | `parse_head` + `read_request` | done by Node's C parser (llhttp) before your callback |
            | `route` with `match` | `if (method === … && url.pathname === …)` |
            | `build_response` | `response.writeHead(status, headers)` + `response.end(body)` |
            | `await asyncio.sleep(…)` | `setTimeout(…)` |
            | `asyncio.start_server` | `http.createServer(handler).listen(port)` |
            """
        ),
        code(NODE_HTTP_MODULE),
        md(
            """
            #### Benchmark: 40 concurrent clients, each waiting 50 ms

            Each server gets 40 simultaneous `GET /slow?ms=50` requests from one
            `httpx.AsyncClient` (one connection per request, since the servers close them). If
            requests are served one after another, that takes 40 × 50 ms = 2 s; if the waits
            overlap, about 50 ms plus overhead. Node runs too when `node` is installed. Times
            vary by machine; the shape does not:
            """
        ),
        code(
            '''
            async def burst(base_url: str, path: str, request_count: int) -> float:
                """Send request_count concurrent GETs; return the wall time in seconds."""
                limits = httpx.Limits(max_connections=request_count)
                async with httpx.AsyncClient(
                    base_url=base_url, limits=limits, timeout=30, trust_env=False
                ) as client:
                    started = time.perf_counter()
                    responses = await asyncio.gather(*(client.get(path) for _ in range(request_count)))
                    elapsed = time.perf_counter() - started
                assert all(response.status_code == 200 for response in responses)
                return elapsed


            server_commands = {
                mode: lambda port, mode=mode: raw_server_command(mode, port)
                for mode in ("blocking", "threaded", "asyncio")
            }
            if HAS_NODE:
                server_commands["node http"] = lambda port: [
                    "node",
                    str(PHASE6_DIR / "node_http.mjs"),
                    str(port),
                ]
            print(interpreter_label())
            for label, make_command in server_commands.items():
                port = free_port()
                with background_server(make_command(port), port) as base_url:
                    seconds = await burst(base_url, "/slow?ms=50", request_count=40)
                print(f"{label:<10} 40 requests in {seconds:6.3f} s  ({40 / seconds:7.1f} req/s)")
            if not HAS_NODE:
                print("SKIP node http: the node command is not installed")
            '''
        ),
        md(
            """
            What to notice:

            - **blocking** serves one connection at a time: ~2 s. Every other client sits in
              the listen backlog while one request waits.
            - **threaded** overlaps the waits: each connection has its own thread, so 40 waits
              happen at once. It scales until thread count, memory and context switches hurt
              (thousands of connections).
            - **asyncio** overlaps them on **one thread**: while one request awaits, the loop
              serves the others. This is the model Uvicorn (and Node) use.
            - **node** lands in the same range as asyncio: same architecture.

            A real server also needs keep-alive, timeouts, request size limits, header
            validation, chunked bodies, `Expect: 100-continue`, HTTP pipelining and protection
            against slow clients. That is why you run Uvicorn or Gunicorn and only write the
            app.
            """
        ),
    ]


def _wsgi_cells() -> list[NotebookNode]:
    """6.1.5 WSGI (PEP 3333)."""
    return [
        md(
            """
            ### 6.1.5 WSGI (PEP 3333)

            WSGI (2003) split Python web programs into a **server** (parses HTTP, manages
            sockets and workers) and an **application** (your code), connected by one
            function signature:

            ```python
            def app(environ: dict, start_response: Callable) -> Iterable[bytes]: ...
            ```

            - `environ`: a dict with CGI-style keys (`REQUEST_METHOD`, `PATH_INFO`,
              `QUERY_STRING`, `CONTENT_LENGTH`, `HTTP_<HEADER_NAME>`) plus `wsgi.input`, a
              file-like object for the body.
            - `start_response(status, headers)`: call it once with `"200 OK"` and a list of
              `(name, value)` string pairs.
            - Return an **iterable of bytes**: the body. The server writes each item.

            Flask and Django are WSGI apps; Gunicorn, uWSGI and `wsgiref` are WSGI servers.
            The demo module has an app, a middleware that wraps it, and `application`, the
            wrapped app a server would load:
            """
        ),
        *writefile_cells(
            WSGI_MODULE,
            [
                ("", "Part 1 of `wsgi_demo.py`: imports, type aliases and a JSON helper."),
                ("def app(", "Part 2: the WSGI app; every request detail comes from `environ`."),
                (
                    "class RequestIdMiddleware:",
                    "Part 3: the middleware, and `application`, the app a server loads.",
                ),
            ],
        ),
        md(
            """
            A WSGI app is just a function, so you can call it directly with an environ and a
            `start_response` that records what it was given. `wsgiref.util.setup_testing_defaults`
            fills in the required keys:
            """
        ),
        code(
            '''
            import wsgiref.util

            wsgi_demo = fresh_import("wsgi_demo")


            def call_wsgi(
                wsgi_app: Callable[..., Iterable[bytes]],
                path: str,
                query: str = "",
                headers: dict[str, str] | None = None,
            ) -> tuple[str, list[tuple[str, str]], bytes]:
                """Call a WSGI app in-process; return (status, headers, body)."""
                environ: dict[str, Any] = {"PATH_INFO": path, "QUERY_STRING": query}
                for name, value in (headers or {}).items():
                    environ[f"HTTP_{name.upper().replace('-', '_')}"] = value
                wsgiref.util.setup_testing_defaults(environ)
                recorded: dict[str, Any] = {}

                def start_response(
                    status: str, response_headers: list[tuple[str, str]], exc_info: object = None
                ) -> Callable[[bytes], None]:
                    """Record the status and headers the app sent."""
                    recorded.update(status=status, headers=response_headers)
                    return lambda data: None  # the legacy write() callable

                body = b"".join(wsgi_app(environ, start_response))
                return recorded["status"], recorded["headers"], body


            print(call_wsgi(wsgi_demo.app, "/hello", "name=Meena"))
            print(call_wsgi(wsgi_demo.application, "/hello", headers={"X-Request-ID": "req-42"}))
            print(call_wsgi(wsgi_demo.app, "/missing")[0])
            '''
        ),
        md(
            """
            The keys a WSGI app reads most (a request with a header, through the testing
            defaults). Note how the `X-Request-ID` header became `HTTP_X_REQUEST_ID`:
            """
        ),
        code(
            """
            sample_environ: dict[str, Any] = {
                "PATH_INFO": "/hello",
                "QUERY_STRING": "name=Meena",
                "HTTP_X_REQUEST_ID": "req-42",
            }
            wsgiref.util.setup_testing_defaults(sample_environ)
            for key in (
                "REQUEST_METHOD",
                "PATH_INFO",
                "QUERY_STRING",
                "SERVER_PROTOCOL",
                "HTTP_HOST",
                "HTTP_X_REQUEST_ID",
                "wsgi.url_scheme",
                "wsgi.input",
            ):
                value = sample_environ[key]
                print(f"{key:<18} {value if isinstance(value, str) else type(value).__name__ + ' object'!r}")
            """
        ),
        md(
            """
            **Middleware** is an object with the same signature that wraps another app.
            `RequestIdMiddleware` changes the request (adds `app.request_id` to the environ)
            and the response (wraps `start_response` to append a header). Stacking is just
            nesting: `GzipMiddleware(RequestIdMiddleware(app))`. Express middleware calls
            `next()`; WSGI middleware calls the wrapped app.

            Serving it with the stdlib's reference server, `wsgiref.simple_server`, in a
            thread (shut down at the end of the cell):
            """
        ),
        code(
            '''
            import wsgiref.simple_server


            class QuietHandler(wsgiref.simple_server.WSGIRequestHandler):
                """Request handler that does not log every request to stderr."""

                def log_message(self, format: str, *args: object) -> None:
                    """Do nothing (the default writes one line per request to stderr)."""


            @contextlib.contextmanager
            def wsgiref_server(wsgi_app: Callable[..., Iterable[bytes]]) -> Iterator[str]:
                """Serve wsgi_app with wsgiref in a thread; yield the base URL; shut down after."""
                server = wsgiref.simple_server.make_server("127.0.0.1", 0, wsgi_app, handler_class=QuietHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    yield f"http://127.0.0.1:{server.server_port}"
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join()


            with (
                wsgiref_server(wsgi_demo.application) as base_url,
                httpx.Client(base_url=base_url, trust_env=False) as client,
            ):
                response = client.get("/hello", params={"name": "Asha"}, headers={"X-Request-ID": "abc"})
                print(response.status_code, response.json(), response.headers["x-request-id"])
                print(client.post("/echo", json={"cups": 3}).json())
            '''
        ),
        md(
            """
            #### Gunicorn

            Gunicorn is the standard production WSGI server on Linux and macOS (not Windows): a
            **pre-fork** model with a master process that starts `-w N` worker processes, each
            serving requests with its own copy of the app, and restarts workers that die or
            hang. `gunicorn -w 4 -b 0.0.0.0:8000 wsgi_demo:application`. With
            `-k uvicorn_worker.UvicornWorker` it manages Uvicorn workers for ASGI apps instead.
            Gunicorn is not a course dependency; the cell runs it only when it is installed.
            Uvicorn can also host a WSGI app (`--interface wsgi`, through a thread-pool
            adapter), which is what runs here either way:
            """
        ),
        code(
            """
            if OPTIONAL_PACKAGES["gunicorn"]:
                port = free_port()
                command = [
                    sys.executable,
                    "-m",
                    "gunicorn",
                    "-w",
                    "2",
                    "-b",
                    f"127.0.0.1:{port}",
                    "--chdir",
                    str(PHASE6_DIR),
                    "wsgi_demo:application",
                ]
                with background_server(command, port) as base_url:
                    print("gunicorn:", httpx.get(f"{base_url}/hello", trust_env=False).json())
            else:
                print("SKIP gunicorn: not installed (not a course dependency; `uv add gunicorn` to try it)")
            with uvicorn_server("wsgi_demo:application", extra_args=["--interface", "wsgi"]) as base_url:
                print("uvicorn --interface wsgi:", httpx.get(f"{base_url}/hello", trust_env=False).json())
            """
        ),
        md(
            """
            #### Limitations of WSGI

            - **One request = one blocked worker for its whole life.** The call returns only
              when the response is ready, so a request waiting 100 ms on a database holds a
              thread (or process) for 100 ms. `wsgiref` is single-threaded: five concurrent
              slow requests take five times as long.
            - **No WebSockets or long-lived connections.** A chat with 10 000 open sockets would
              need 10 000 threads; WSGI has no way to say "a message arrived".
            - **No async.** You cannot `await` inside a WSGI app; `wsgi.input` is a blocking
              file.
            - **Request/response only.** No lifespan (startup/shutdown) events; servers invent
              their own hooks.

            ASGI (next section) fixes all four. The cell measures the first limitation with
            five concurrent `GET /slow?ms=100` requests:
            """
        ),
        code(
            """
            async def concurrent_gets(base_url: str, path: str, request_count: int) -> float:
                \"\"\"Wall time for request_count concurrent GETs on fresh connections.\"\"\"
                async with httpx.AsyncClient(base_url=base_url, trust_env=False, timeout=30) as client:
                    started = time.perf_counter()
                    await asyncio.gather(*(client.get(path) for _ in range(request_count)))
                    return time.perf_counter() - started


            with wsgiref_server(wsgi_demo.app) as base_url:
                seconds = await asyncio.to_thread(asyncio.run, concurrent_gets(base_url, "/slow?ms=100", 5))
            print(f"wsgiref (1 thread), 5 x 100 ms requests: {seconds:.2f} s")
            """
        ),
        md(
            """
            > **Note:** the client runs in its own thread with its own loop
            > (`asyncio.to_thread(asyncio.run, …)`) only to keep it independent of the kernel's
            > loop; any HTTP client would show the same 0.5 s.
            """
        ),
    ]


def _asgi_cells() -> list[NotebookNode]:
    """6.1.6 ASGI."""
    return [
        md(
            """
            ### 6.1.6 ASGI

            ASGI (Asynchronous Server Gateway Interface) is WSGI redesigned around
            coroutines and **messages**:

            ```python
            async def app(scope: dict, receive: Callable[[], Awaitable[dict]],
                          send: Callable[[dict], Awaitable[None]]) -> None: ...
            ```

            - `scope`: what kind of connection this is and its details (`type`, `method`,
              `path`, `query_string` as bytes, `headers` as a list of `(bytes, bytes)` pairs).
            - `await receive()`: the next event **from** the client or server.
            - `await send(message)`: an event **to** the client.

            | Scope `type` | Messages the app receives | Messages the app sends |
            | --- | --- | --- |
            | `http` | `http.request` (`body`, `more_body`), `http.disconnect` | `http.response.start` (`status`, `headers`), `http.response.body` (`body`, `more_body`) |
            | `websocket` | `websocket.connect`, `websocket.receive` (`text`/`bytes`), `websocket.disconnect` | `websocket.accept`, `websocket.send`, `websocket.close` |
            | `lifespan` | `lifespan.startup`, `lifespan.shutdown` | `lifespan.startup.complete`, `lifespan.shutdown.complete` (or `.failed`) |

            Because the app is a coroutine, a request waiting on I/O costs a suspended task,
            not a thread; a WebSocket is just a long-running call that loops over `receive()`.
            Starlette, FastAPI, Django (3.0+) and Litestar are ASGI apps; Uvicorn, Hypercorn
            and Granian are ASGI servers.

            ```mermaid
            sequenceDiagram
                participant Client
                participant Uvicorn
                participant App as app(scope, receive, send)
                Client->>Uvicorn: GET /stream HTTP/1.1
                Uvicorn->>App: call with scope {type: http, path: /stream}
                App->>Uvicorn: send http.response.start (200, headers)
                App->>Uvicorn: send http.response.body (line 1, more_body=True)
                Uvicorn-->>Client: headers + chunk 1
                App->>Uvicorn: send http.response.body (line 2, more_body=True)
                Uvicorn-->>Client: chunk 2
                App->>Uvicorn: send http.response.body (b"", more_body=False)
                Uvicorn-->>Client: final 0-size chunk
            ```

            <details><summary>ASCII version</summary>

            ```text
            Client ──GET /stream──▶ Uvicorn ──scope──▶ app
                                    Uvicorn ◀── http.response.start (200)
            Client ◀──headers──────
                                    Uvicorn ◀── http.response.body "line 1" more_body=True
            Client ◀──chunk 1──────
                                    Uvicorn ◀── http.response.body b"" more_body=False
            Client ◀──0-size chunk─
            ```

            </details>

            The demo app handles all three scope types, streams a response with `more_body`,
            reads a request body that may arrive in several messages, and has an ASGI version
            of the request-id middleware (it wraps `send` instead of `start_response`):
            """
        ),
        *writefile_cells(
            ASGI_MODULE,
            [
                (
                    "",
                    "Part 1 of `asgi_demo.py`: type aliases, shared state, JSON and body helpers.",
                ),
                (
                    "async def lifespan(",
                    "Part 2: the lifespan protocol and a streamed response (`more_body`).",
                ),
                ("async def http_app(", "Part 3: the HTTP router and the WebSocket echo."),
                (
                    "async def app(",
                    "Part 4: the entry point that dispatches on `scope['type']`, and the middleware.",
                ),
            ],
        ),
        md(
            """
            #### Calling an ASGI app by hand

            No server needed: build a `scope`, give it a `receive` that returns prepared
            messages and a `send` that records what the app sends. This is what Uvicorn does,
            minus the sockets (and what Starlette's `TestClient` and `httpx.ASGITransport`
            do for tests):
            """
        ),
        code(
            r'''
            asgi_demo = fresh_import("asgi_demo")


            def http_scope(
                method: str, path: str, query: bytes = b"", headers: Iterable[tuple[bytes, bytes]] = ()
            ) -> dict[str, Any]:
                """A minimal ASGI http scope, as a server would build it."""
                return {
                    "type": "http",
                    "asgi": {"version": "3.0"},
                    "http_version": "1.1",
                    "method": method,
                    "scheme": "http",
                    "path": path,
                    "query_string": query,
                    "headers": list(headers),
                    "client": ("127.0.0.1", 50000),
                    "server": ("127.0.0.1", 8000),
                }
            '''
        ),
        md(
            """
            `call_asgi` plays the server: its `receive()` hands out prepared messages in order and its
            `send()` records everything the app sends back:
            """
        ),
        code(
            r'''
            async def call_asgi(
                app: Callable[..., Awaitable[None]],
                scope: dict[str, Any],
                incoming: Iterable[dict[str, Any]] = (),
            ) -> list[dict[str, Any]]:
                """Run app once: receive() returns the incoming messages in order; return what it sent."""
                pending = list(incoming) or [{"type": "http.request", "body": b"", "more_body": False}]
                sent: list[dict[str, Any]] = []

                async def receive() -> dict[str, Any]:
                    """The next prepared message, as a server would deliver it."""
                    return pending.pop(0)

                async def send(message: dict[str, Any]) -> None:
                    """Record one message the app sent."""
                    sent.append(message)

                await app(scope, receive, send)
                return sent


            for message in await call_asgi(asgi_demo.app, http_scope("GET", "/hello", b"name=Ravi")):
                print(message)
            '''
        ),
        md(
            """
            A request body in two messages (`more_body=True`, then `False`), as a server
            produces for a large or streamed upload; the app's `read_body` loop joins them:
            """
        ),
        code(
            """
            upload = [
                {"type": "http.request", "body": b'{"part": ', "more_body": True},
                {"type": "http.request", "body": b'"two"}', "more_body": False},
            ]
            echo_messages = await call_asgi(asgi_demo.app, http_scope("POST", "/echo"), upload)
            print(echo_messages[-1]["body"])
            """
        ),
        md(
            """
            A streamed response: one `http.response.start`, then several body messages with
            `more_body=True`, then an empty final one. The sleeps are set to 0 here:
            """
        ),
        code(
            """
            for message in await call_asgi(asgi_demo.app, http_scope("GET", "/stream", b"count=3&delay=0")):
                print(message)
            """
        ),
        md(
            """
            The **lifespan** scope: the server sends `lifespan.startup` before accepting any
            connection and `lifespan.shutdown` when it stops. This is where an app opens its
            database pool and HTTP clients (FastAPI's `lifespan=` parameter, Unit 6.3.10):
            """
        ),
        code(
            """
            lifespan_events = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]
            lifespan_scope = {"type": "lifespan", "asgi": {"version": "3.0"}}
            print(await call_asgi(asgi_demo.app, lifespan_scope, lifespan_events))
            print(f"{'started_at' in asgi_demo.state=}")
            """
        ),
        md(
            """
            The **websocket** scope: connect, two text frames, disconnect. The app accepts,
            echoes each frame, and returns when the client leaves:
            """
        ),
        code(
            """
            websocket_scope = {**http_scope("GET", "/ws"), "type": "websocket"}
            websocket_events = [
                {"type": "websocket.connect"},
                {"type": "websocket.receive", "text": "hello"},
                {"type": "websocket.receive", "text": "chai?"},
                {"type": "websocket.disconnect", "code": 1000},
            ]
            for message in await call_asgi(asgi_demo.app, websocket_scope, websocket_events):
                print(message)
            """
        ),
        md(
            """
            **ASGI middleware** wraps the app the same way WSGI middleware does, but it
            intercepts *messages*: `RequestIdMiddleware` replaces `send` with `send_with_id`,
            which adds a header to `http.response.start`. It passes `websocket` and `lifespan`
            scopes through untouched:
            """
        ),
        code(
            """
            scope_with_id = http_scope("GET", "/hello", headers=[(b"x-request-id", b"req-7")])
            start_message = (await call_asgi(asgi_demo.application, scope_with_id))[0]
            print(start_message["headers"])
            """
        ),
        md(
            """
            #### Uvicorn

            Uvicorn is the ASGI server: it accepts connections on an asyncio loop (uvloop
            when installed), parses HTTP/1.1 with `httptools` (or pure-Python `h11`), handles
            WebSocket upgrades (`websockets` / `wsproto`), turns bytes into scopes and messages,
            and runs the lifespan protocol.

            | Command | Meaning |
            | --- | --- |
            | `uvicorn asgi_demo:application` | import `application` from `asgi_demo` and serve it on 127.0.0.1:8000 |
            | `--reload` | restart on file changes (development only) |
            | `--workers 4` | four processes behind one socket |
            | `--host 0.0.0.0 --port 80` | listen on every interface |
            | `--proxy-headers`, `--forwarded-allow-ips` | trust `X-Forwarded-*` from a proxy |
            | `--interface wsgi` | host a WSGI app (6.1.5) |
            | `fastapi dev main.py` / `fastapi run` | FastAPI's CLI: Uvicorn with sensible defaults |

            The demo app under Uvicorn, for real. Notice in the output: Uvicorn added a `date`
            and `server` header; the middleware added `x-request-id`; the streamed response has
            **no `content-length`**, so Uvicorn used `transfer-encoding: chunked`, and the
            lines arrive ~0.2 s apart as the app sends them; `/stats` shows the lifespan
            startup ran:
            """
        ),
        code(
            """
            with (
                uvicorn_server("asgi_demo:application") as base_url,
                httpx.Client(base_url=base_url, trust_env=False, timeout=10) as client,
            ):
                hello = client.get("/hello", params={"name": "Asha"}, headers={"x-request-id": "r-1"})
                print(hello.json(), {name: hello.headers[name] for name in ("server", "x-request-id")})
                started = time.perf_counter()
                with client.stream("GET", "/stream", params={"count": 3, "delay": 0.2}) as streamed:
                    print(f"{streamed.headers.get('transfer-encoding')=}")
                    for line in streamed.iter_lines():
                        print(f"  +{time.perf_counter() - started:.1f} s  {line!r}")
                print(client.get("/stats").json())
            """
        ),
        md(
            """
            The WebSocket route through Uvicorn, with the `websockets` package's synchronous
            client (installed with `fastapi[standard]`; the cell skips without it):
            """
        ),
        code(
            """
            if OPTIONAL_PACKAGES["websockets"]:
                from websockets.sync.client import connect as websocket_connect

                with uvicorn_server("asgi_demo:application") as base_url:
                    with websocket_connect(base_url.replace("http://", "ws://") + "/ws") as websocket:
                        for text in ("hello", "chai?"):
                            websocket.send(text)
                            print(websocket.recv(timeout=5))
            else:
                print("SKIP websocket client: the websockets package is not installed")
            """
        ),
        md(
            """
            **Under the hood: how Uvicorn knows what you gave it.** `uvicorn.Config.load()`
            inspects the object: a **coroutine function**, or an object whose `__call__` is
            one, is ASGI 3; anything else is assumed to be the old two-step ASGI 2 style. It
            cannot tell a WSGI function from ASGI 2, which is why `--interface wsgi` exists:
            """
        ),
        code(
            """
            import uvicorn

            for label, candidate in (
                ("asgi_demo.app", asgi_demo.app),
                ("asgi_demo.application", asgi_demo.application),
                ("wsgi_demo.app", wsgi_demo.app),
            ):
                config = uvicorn.Config(app=candidate)
                config.load()
                call = candidate if inspect.isfunction(candidate) else type(candidate).__call__
                print(f"{label:<22} coroutine={inspect.iscoroutinefunction(call)!s:<5} -> {config.interface}")
            print(f"{inspect.signature(asgi_demo.app)=}")
            print(f"{uvicorn.__version__=}")
            """
        ),
    ]


def _framework_cells() -> list[NotebookNode]:
    """6.1.7 Framework landscape."""
    return [
        md(
            """
            ### 6.1.7 Framework landscape

            | Framework | Interface | Style | Validation / docs | Closest JS relative |
            | --- | --- | --- | --- | --- |
            | **Flask** (2010) | WSGI (async views run in a thread) | micro: routing + request/response, extensions for the rest | extensions (marshmallow, flask-smorest) | **Express** |
            | **Django** (2005) | WSGI and ASGI | batteries included: ORM, migrations, admin, auth, templates, forms | Django REST framework, django-ninja | NestJS + Prisma + AdminJS (Rails-like) |
            | **Starlette** (2018) | ASGI | lightweight toolkit: routing, middleware, WebSockets, `TestClient` | none built in | **Koa** / Fastify core |
            | **FastAPI** (2018) | ASGI (built on Starlette) | type hints drive validation, serialization, DI and docs | **Pydantic** + automatic **OpenAPI** | Fastify with JSON Schema, NestJS DTOs + zod |
            | **Litestar** (2021) | ASGI | opinionated: DI, layered config, msgspec or Pydantic, plugins | msgspec / Pydantic + OpenAPI | **NestJS** |

            How to choose: an existing Django shop or an admin-heavy product → Django; a JSON
            API with typed contracts → FastAPI (or Litestar); a tiny service or a lot of
            legacy WSGI → Flask. All of them run behind the same servers and proxies.

            **Express → FastAPI mapping**

            | Express | FastAPI |
            | --- | --- |
            | `const app = express()` | `app = FastAPI()` |
            | `app.get("/notes/:id", handler)` | `@app.get("/notes/{note_id}")` on a function |
            | `req.params.id` (string) | `note_id: int` parameter (converted and validated) |
            | `req.query.limit` | `limit: int = 20` parameter |
            | `express.json()` + `req.body` + zod/joi | a Pydantic model parameter |
            | `res.status(201).json(note)` | `status_code=201`; `return note` |
            | `app.use(middleware)` | `app.add_middleware(...)` or `@app.middleware("http")` |
            | `express.Router()` | `APIRouter()` (Unit 6.3) |
            | `next(err)` + error middleware | `raise HTTPException(...)`, `@app.exception_handler` |
            | `swagger-jsdoc` / `@nestjs/swagger` | built in: `/docs`, `/redoc`, `/openapi.json` |
            | Supertest | `TestClient` / `httpx.AsyncClient` (Unit 6.6) |

            The same endpoint, `GET /hello?name=…`, in each framework. Starlette and FastAPI
            are installed (FastAPI depends on Starlette), so they run through Starlette's
            `TestClient`, which calls the ASGI app in-process like `call_asgi` above. Flask,
            Django and Litestar are not course dependencies; their code is shown and run only if
            installed:
            """
        ),
        code(
            '''
            from fastapi import FastAPI
            from starlette.applications import Starlette
            from starlette.requests import Request
            from starlette.responses import JSONResponse
            from starlette.routing import Route
            from starlette.testclient import TestClient


            async def starlette_hello(request: Request) -> JSONResponse:
                """Starlette: you read the query string yourself and build the response."""
                return JSONResponse({"message": f"hello, {request.query_params.get('name', 'world')}"})


            starlette_app = Starlette(routes=[Route("/hello", starlette_hello)])

            fastapi_app = FastAPI()


            @fastapi_app.get("/hello")
            async def fastapi_hello(name: str = "world") -> dict[str, str]:
                """FastAPI: the parameter declares the query string; the return value becomes JSON."""
                return {"message": f"hello, {name}"}


            for label, asgi_app in (("Starlette", starlette_app), ("FastAPI", fastapi_app)):
                with TestClient(asgi_app) as client:
                    print(f"{label:<9}", client.get("/hello", params={"name": "Asha"}).json())
            '''
        ),
        md(
            """
            The others, guarded by `find_spec`. The Express version is printed for comparison:
            """
        ),
        code(
            '''
            OTHER_FRAMEWORK_SOURCES = {
                "flask": """
            from flask import Flask, request
            app = Flask(__name__)

            @app.get("/hello")
            def hello():
                return {"message": f"hello, {request.args.get('name', 'world')}"}
            """,
                "litestar": """
            from litestar import Litestar, get

            @get("/hello")
            async def hello(name: str = "world") -> dict[str, str]:
                return {"message": f"hello, {name}"}

            app = Litestar([hello])
            """,
                "django": """
            # views.py (+ urls.py: path("hello", views.hello))
            from django.http import JsonResponse

            def hello(request):
                return JsonResponse({"message": f"hello, {request.GET.get('name', 'world')}"})
            """,
            }
            EXPRESS_SOURCE = """
            app.get("/hello", (req, res) => {
              res.json({ message: `hello, ${req.query.name ?? "world"}` });
            });
            """
            for framework, source in OTHER_FRAMEWORK_SOURCES.items():
                status = "installed" if OPTIONAL_PACKAGES[framework] else "SKIP (not installed)"
                print(f"--- {framework}: {status}{source}")
            print(f"--- express (Node, for comparison){EXPRESS_SOURCE}")
            '''
        ),
        md(
            """
            The Flask snippet runs too when Flask is present (through its own test client):
            """
        ),
        code(
            """
            if OPTIONAL_PACKAGES["flask"]:
                flask_namespace: dict[str, Any] = {"__name__": "flask_hello"}
                exec(OTHER_FRAMEWORK_SOURCES["flask"], flask_namespace)
                flask_client = flask_namespace["app"].test_client()
                print("Flask    ", flask_client.get("/hello?name=Asha").get_json())
            else:
                print("SKIP Flask: not installed (`uv add flask` to run this cell)")
            """
        ),
    ]


def _http_client_cells() -> list[NotebookNode]:
    """6.1.8 HTTP clients."""
    return [
        md(
            """
            ### 6.1.8 HTTP clients

            | Client | Sync / async | HTTP/2 | Default timeout | Notes |
            | --- | --- | --- | --- | --- |
            | `urllib.request` | sync | no | **none** (blocks forever) | stdlib; clumsy API; fine for scripts with no dependencies |
            | `requests` | sync | no | **none** | the classic; `Session` for reuse; `HTTPAdapter` + `Retry` |
            | `httpx` | **both** (`Client`, `AsyncClient`) | yes (`httpx[http2]`) | 5 s | `requests`-like API; ASGI/WSGI transports for tests; FastAPI's test client builds on it |
            | `aiohttp` | async | no | 5 min total | client **and** server; very fast; asyncio only |

            Four habits matter more than the library:

            1. **Reuse a client** (`requests.Session`, `httpx.Client`): it keeps a connection
               pool, so later requests skip the TCP (and TLS) handshake.
            2. **Always set a timeout**, split into connect, read, write and pool waits.
            3. **Retry only what is safe to retry** (idempotent methods, connect errors, 502/503/
               504/429), with backoff and jitter (Unit 5.4.9).
            4. **Stream large bodies** instead of loading them into memory.

            The demos use the local shop API (`SHOP_API`): `/rates`, `/flaky/<key>?fail=N`
            (503 for the first N calls), `/slow?seconds=S`, `/connections`, `POST /echo`.

            **`urllib.request`**: a `Request` object, `urlopen`, and `HTTPError` for 4xx/5xx
            (it raises, unlike the others). `trust_env=False` / `ProxyHandler({})` keep proxy
            settings from the environment out of these local demos:
            """
        ),
        code(
            """
            rates_request = urllib.request.Request(
                f"{SHOP_API}/rates?base=INR", headers={"Accept": "application/json"}
            )
            with NO_PROXY_OPENER.open(rates_request, timeout=5) as response:
                print(response.status, json.load(response)["rates"])

            post_request = urllib.request.Request(
                f"{SHOP_API}/echo",
                data=json.dumps({"tea": 2}).encode(),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with NO_PROXY_OPENER.open(post_request, timeout=5) as response:
                print(response.status, json.load(response))
            try:
                NO_PROXY_OPENER.open(f"{SHOP_API}/status/404", timeout=5)
            except urllib.error.HTTPError as error:
                print(f"{type(error).__name__}: {error.code} {error.reason}")
            """
        ),
        md(
            """
            **`requests`**: a `Session` reuses connections (the shop API counts them), and an
            `HTTPAdapter` with `urllib3.Retry` retries 503s (`backoff_factor=0` keeps the demo
            fast; use a real backoff in production). `requests` has no default timeout, so
            every call passes one:
            """
        ),
        code(
            """
            if OPTIONAL_PACKAGES["requests"]:
                import requests
                from requests.adapters import HTTPAdapter
                from urllib3.util.retry import Retry

                with requests.Session() as session:
                    session.trust_env = False
                    before = shop_connection_count()
                    for _ in range(5):
                        session.get(f"{SHOP_API}/rates", timeout=5).raise_for_status()
                    new_connections = shop_connection_count() - before - 1
                    print(f"requests.Session: 5 requests, {new_connections} new connection(s)")

                    retry = Retry(total=3, status_forcelist=[503], backoff_factor=0, allowed_methods={"GET"})
                    session.mount("http://", HTTPAdapter(max_retries=retry))
                    flaky = session.get(f"{SHOP_API}/flaky/requests-demo?fail=2", timeout=5)
                    print(f"with Retry: {flaky.status_code} {flaky.json()}")
            else:
                print("SKIP requests: not installed")
            """
        ),
        md(
            """
            **`httpx`, sync.** `httpx.Client` with a `base_url`, a split `Timeout`, and
            connection reuse. A read timeout of 0.3 s against `/slow?seconds=1` raises
            `ReadTimeout`; `raise_for_status()` turns 4xx/5xx into `HTTPStatusError`:
            """
        ),
        code(
            """
            shop_timeout = httpx.Timeout(5.0, read=0.3)  # 5 s for connect/write/pool, 0.3 s per read
            with httpx.Client(base_url=SHOP_API, timeout=shop_timeout, trust_env=False) as client:
                before = shop_connection_count()
                rates = [client.get("/rates").json()["rates"]["USD"] for _ in range(5)]
                print(f"httpx.Client: {rates=}, {shop_connection_count() - before - 1} new connection(s)")
                print(raised_message(lambda: client.get("/slow", params={"seconds": 1})))
                print(raised_message(lambda: client.get("/status/503").raise_for_status()).splitlines()[0])
                print(f"{client.get('/rates').http_version=}")
            """
        ),
        md(
            """
            Without reuse, every top-level `httpx.get` opens (and closes) its own connection:
            """
        ),
        code(
            """
            before = shop_connection_count()
            for _ in range(5):
                httpx.get(f"{SHOP_API}/rates", trust_env=False)
            print(f"5 x httpx.get: {shop_connection_count() - before - 1} new connection(s)")
            """
        ),
        md(
            """
            **`httpx`, async.** The same API with `await`. Five 0.3 s requests run
            concurrently with `asyncio.gather` and take about 0.3 s, not 1.5 s (the shop
            API is threaded, so the server side overlaps too):
            """
        ),
        code(
            """
            async with httpx.AsyncClient(base_url=SHOP_API, timeout=5, trust_env=False) as async_client:
                with Timer("5 concurrent /slow?seconds=0.3"):
                    slow_replies = await asyncio.gather(
                        *(async_client.get("/slow", params={"seconds": 0.3}) for _ in range(5))
                    )
            print([reply.status_code for reply in slow_replies])
            """
        ),
        md(
            """
            **Retries.** `httpx.HTTPTransport(retries=N)` retries only **connection** failures
            (refused, DNS), never responses. For 503s, retry yourself (or with `tenacity`,
            Unit 4.6). Below: a closed port with transport retries, then a small retry loop with
            exponential backoff and full jitter around `/flaky`:
            """
        ),
        code(
            '''
            import random

            closed_port = free_port()  # nothing listens here
            with httpx.Client(transport=httpx.HTTPTransport(retries=2), trust_env=False) as client:
                with Timer("3 connection attempts", report=None) as attempts_timer:
                    outcome = raised_error_name(lambda: client.get(f"http://127.0.0.1:{closed_port}/"))
            print(f"{outcome} after transport retries ({attempts_timer.elapsed_seconds:.2f} s)")

            RETRYABLE_STATUS = {429, 502, 503, 504}


            def get_with_retries(
                client: httpx.Client, url: str, attempts: int = 4, base_delay: float = 0.01
            ) -> httpx.Response:
                """GET url, retrying retryable statuses with exponential backoff and full jitter."""
                rng = random.Random(42)
                for attempt in range(1, attempts + 1):
                    response = client.get(url)
                    if response.status_code not in RETRYABLE_STATUS or attempt == attempts:
                        return response
                    time.sleep(rng.uniform(0, base_delay * 2**attempt))
                raise AssertionError("unreachable")


            with httpx.Client(base_url=SHOP_API, timeout=5, trust_env=False) as client:
                flaky = get_with_retries(client, "/flaky/httpx-demo?fail=2")
            print(f"{flaky.status_code=} {flaky.json()=}")
            '''
        ),
        md(
            """
            **Streaming.** `client.stream(...)` returns before the body is read; iterate with
            `iter_bytes()`, `iter_text()` or `iter_lines()` and memory stays flat however large
            the body is. Uploads stream too: pass a generator as `content=` and httpx sends a
            chunked request, which arrives at the ASGI app as several `http.request` messages
            (the `/echo` route counts them). The ASGI demo app from 6.1.6 serves both, under
            Uvicorn:
            """
        ),
        code(
            '''
            def upload_parts() -> Iterator[bytes]:
                """A request body produced piece by piece (a file read in chunks, for example)."""
                for part_number in range(4):
                    yield f"part {part_number};".encode() * 1000


            with (
                uvicorn_server("asgi_demo:application") as base_url,
                httpx.Client(base_url=base_url, timeout=10, trust_env=False) as client,
            ):
                with client.stream("GET", "/stream", params={"count": 4, "delay": 0}) as streamed:
                    chunk_sizes = [len(chunk) for chunk in streamed.iter_raw()]
                print(f"download: {len(chunk_sizes)} chunk(s), sizes {chunk_sizes}")
                upload_reply = client.post("/echo", content=upload_parts())
                print(f"upload:   {upload_reply.json()}")
            '''
        ),
        md(
            """
            > **Note:** how many chunks arrive depends on timing: the server and the OS may
            > merge small writes. The total bytes do not change.

            **HTTP/2 and aiohttp.** `httpx.Client(http2=True)` needs the optional `h2`
            package (`uv add "httpx[http2]"`) and an HTTPS server that offers `h2` via ALPN;
            against the plain-HTTP shop API it would still use HTTP/1.1. `aiohttp` is an
            asyncio-only client (and server) that is not a course dependency. Both cells run
            only if the package is installed:
            """
        ),
        code(
            '''
            if OPTIONAL_PACKAGES["h2"]:
                with httpx.Client(http2=True, trust_env=False) as client:
                    print(f"http2=True against plain HTTP: {client.get(f'{SHOP_API}/rates').http_version}")
            else:
                print('SKIP HTTP/2: the h2 package is not installed (`uv add "httpx[http2]"`)')

            AIOHTTP_SOURCE = """
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(f"{SHOP_API}/rates") as response:
                    print(response.status, await response.json())
            """
            if OPTIONAL_PACKAGES["aiohttp"]:
                import aiohttp

                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                    async with session.get(f"{SHOP_API}/rates") as response:
                        print("aiohttp:", response.status, await response.json())
            else:
                print(f"SKIP aiohttp: not installed (`uv add aiohttp`). The code would be:{AIOHTTP_SOURCE}")
            '''
        ),
    ]


def _predict_cells() -> list[NotebookNode]:
    """Predict-the-output questions for Unit 6.1."""
    return [
        md(
            """
            ### Predict the output — Unit 6.1

            Three short questions on the details that bite.
            """
        ),
        *predict_cells(
            r"""
            raw = b"GET / HTTP/1.1\r\nHost: x\r\n\r\n"
            print(raw.split(b"\r\n"))
            """,
            r"""
            `[b'GET / HTTP/1.1', b'Host: x', b'', b'']`. The head ends with **two** CRLFs (one
            ends the last header line, one is the blank line), so splitting produces two empty
            pieces at the end. Parsers look for `\r\n\r\n` instead of splitting naively.
            """,
            r"""
            raw = b"GET / HTTP/1.1\r\nHost: x\r\n\r\n"
            print(raw.split(b"\r\n"))
            """,
        ),
        *predict_cells(
            """
            from http import HTTPStatus
            print(HTTPStatus(422).phrase, HTTPStatus(422).is_client_error)
            """,
            """
            `Unprocessable Content True` on Python 3.13+. Older versions say "Unprocessable
            Entity" (RFC 4918); 3.13 adopted the RFC 9110 name. 422 is a 4xx, so the client must
            change the request; FastAPI uses it for every validation error.
            """,
            """
            print(HTTPStatus(422).phrase, HTTPStatus(422).is_client_error)
            """,
        ),
        *predict_cells(
            """
            from wsgiref.validate import validator

            def app(environ, start_response):
                start_response("200 OK", [("Content-Type", "text/plain")])
                return "hello"   # a str, not a list of bytes

            # call validator(app) with a valid environ ...
            """,
            """
            `AssertionError: You should not return a string as your application iterator, ...`.
            A WSGI app must return an iterable of **bytes**. A `str` is iterable too (one
            character at a time), so without the validator a server would send `h`, `e`, `l`,
            ... as separate writes, or fail on the first `str`. `wsgiref.validate` catches the
            mistake at once: use it in tests of hand-written WSGI code.
            """,
            '''
            from wsgiref.validate import validator


            def str_returning_app(environ: dict[str, Any], start_response: Callable[..., object]) -> object:
                """Broken on purpose: returns a str instead of an iterable of bytes."""
                start_response("200 OK", [("Content-Type", "text/plain")])
                return "hello"


            validated_environ: dict[str, Any] = {"QUERY_STRING": ""}
            wsgiref.util.setup_testing_defaults(validated_environ)
            print(raised_message(lambda: validator(str_returning_app)(validated_environ, lambda *args: None)))
            ''',
        ),
    ]


def _lab_cells_part_1() -> list[NotebookNode]:
    """Lab 6.1 exercises 1-3."""
    return [
        md(
            """
            ### Lab 6.1

            Five exercises, from bytes on a socket to a micro-framework. Replace each
            `raise NotImplementedError`, then run the check cell; until then the checks print
            FAIL, which is expected. Three setup cells define `serve_raw(handler)` (a
            thread-per-connection socket server that passes each raw request to
            `handler(bytes) -> bytes`), `http_call(...)` (one request with `http.client`) and
            `ManualClock` (a fake clock for timing tests). `call_asgi` and `http_scope` from
            6.1.6 are reused.
            """
        ),
        code(
            r'''
            def read_raw_request(connection: socket.socket) -> bytes:
                """Read bytes up to the blank line, then Content-Length more bytes."""
                data = b""
                while b"\r\n\r\n" not in data and (chunk := connection.recv(65536)):
                    data += chunk
                if b"\r\n\r\n" not in data:
                    return data  # the client closed early; let the handler reject it
                match = re.search(rb"(?im)^content-length:\s*(\d+)", data)
                needed = data.index(b"\r\n\r\n") + 4 + (int(match[1]) if match else 0)
                while len(data) < needed and (chunk := connection.recv(65536)):
                    data += chunk
                return data


            def serve_one(connection: socket.socket, handler: Callable[[bytes], bytes]) -> None:
                """Answer one connection with handler(raw request); a crashing handler gives a plain 500."""
                with connection:
                    connection.settimeout(5)
                    raw_request = read_raw_request(connection)
                    try:
                        reply = handler(raw_request)
                    except Exception as error:  # a broken handler must not kill the thread noisily
                        reason = f"handler raised {type(error).__name__}".encode()  # plain text, no length
                        reply = b"HTTP/1.1 500 Internal Server Error\r\nContent-Type: text/plain\r\n"
                        reply += b"\r\n" + reason  # the server closes the connection after it
                    connection.sendall(reply)
            '''
        ),
        md(
            """
            Setup, part 2: the accept loop (one thread per connection) and `serve_raw`, a context manager
            that starts it in a thread, yields the port, and stops it at the end of the `with` block:
            """
        ),
        code(
            r'''
            def accept_loop(
                server: socket.socket, stopping: threading.Event, handler: Callable[[bytes], bytes]
            ) -> None:
                """Accept connections until stopping is set, serving each in its own thread."""
                while not stopping.is_set():
                    try:
                        connection, _address = server.accept()
                    except TimeoutError:
                        continue
                    threading.Thread(target=serve_one, args=(connection, handler), daemon=True).start()


            @contextlib.contextmanager
            def serve_raw(handler: Callable[[bytes], bytes]) -> Iterator[int]:
                """Serve handler(raw request) -> raw response on 127.0.0.1; yield the port; stop after."""
                server = socket.create_server(("127.0.0.1", 0))
                server.settimeout(0.1)  # so the accept loop notices the stop flag
                stopping = threading.Event()
                thread = threading.Thread(target=accept_loop, args=(server, stopping, handler), daemon=True)
                thread.start()
                try:
                    yield server.getsockname()[1]
                finally:
                    stopping.set()
                    thread.join()
                    server.close()
            '''
        ),
        md(
            """
            Setup, part 3: `http_call` (one request with `http.client`) and `ManualClock` (a fake clock that
            returns the readings you give it):
            """
        ),
        code(
            r'''
            def http_call(
                port: int,
                method: str,
                path: str,
                body: bytes | None = None,
                headers: dict[str, str] | None = None,
            ) -> tuple[int, dict[str, str], bytes]:
                """One request with http.client; return (status, lower-cased headers, body)."""
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                try:
                    connection.request(method, path, body=body, headers=headers or {})
                    response = connection.getresponse()
                    response_headers = {name.lower(): value for name, value in response.getheaders()}
                    return response.status, response_headers, response.read()
                finally:
                    connection.close()


            class ManualClock:
                """A clock that returns the given readings in order (for deterministic timing tests)."""

                def __init__(self, *readings: float) -> None:
                    """Store the readings to hand out."""
                    self.readings = list(readings)

                def __call__(self) -> float:
                    """Return the next reading."""
                    return self.readings.pop(0)
            '''
        ),
        md(
            """
            #### Exercise 1 — parse a raw HTTP request into a dataclass

            Write `parse_http_request(raw: bytes) -> HttpRequest`. Rules:

            - The head ends at the first `\\r\\n\\r\\n`; without one raise
              `ValueError("incomplete request")`.
            - The request line has exactly three parts `METHOD TARGET VERSION`; the method is
              upper-case letters; the version starts with `HTTP/1.`. Otherwise raise
              `ValueError("bad request line")`.
            - `path` is the target without the query; `query` maps each name to the **list**
              of its values (`?tag=a&tag=b` → `{"tag": ["a", "b"]}`), percent-decoded.
            - Header names are lower-cased; a line without `:` raises
              `ValueError("bad header line")`; a repeated header joins values with `", "`.
            - `body` is exactly `Content-Length` bytes (0 without the header); extra bytes
              are ignored; fewer raise `ValueError("body shorter than Content-Length")`.
            """
        ),
        md("Your solution:"),
        code(
            '''
            @dataclasses.dataclass(frozen=True)
            class HttpRequest:
                """A parsed HTTP/1.x request."""

                method: str
                path: str
                query: dict[str, list[str]]
                version: str
                headers: dict[str, str]
                body: bytes


            def parse_http_request(raw: bytes) -> HttpRequest:
                """Parse raw request bytes (head + body) into an HttpRequest."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 1:"),
        code(
            r'''
            sample_get = (
                b"GET /notes/search?tag=work&tag=home&q=green%20tea HTTP/1.1\r\n"
                b"Host: localhost\r\nAccept: application/json\r\nX-Tag: a\r\nx-tag: b\r\n\r\n"
            )
            sample_post = b'POST /echo HTTP/1.1\r\nContent-Length: 7\r\n\r\n{"a":1}EXTRA'


            def request_line_parts(raw: bytes) -> tuple[str, str, str]:
                """Method, path and version of a parsed request."""
                request = parse_http_request(raw)
                return request.method, request.path, request.version


            def parse_error(raw: bytes) -> str:
                """What parse_http_request raises for raw, as "ErrorName: message"."""
                return raised_message(lambda: parse_http_request(raw))
            '''
        ),
        md(
            """
            The parsing checks:
            """
        ),
        code(
            r"""
            run_checks(
                [
                    (
                        "method, path, version",
                        lambda: request_line_parts(sample_get),
                        ("GET", "/notes/search", "HTTP/1.1"),
                    ),
                    (
                        "query lists, decoded",
                        lambda: parse_http_request(sample_get).query,
                        {"tag": ["work", "home"], "q": ["green tea"]},
                    ),
                    (
                        "headers lower-cased, repeats joined",
                        lambda: parse_http_request(sample_get).headers,
                        {"host": "localhost", "accept": "application/json", "x-tag": "a, b"},
                    ),
                    ("no body without Content-Length", lambda: parse_http_request(sample_get).body, b""),
                    (
                        "body is exactly Content-Length bytes",
                        lambda: parse_http_request(sample_post).body,
                        b'{"a":1}',
                    ),
                ]
            )
            """
        ),
        md(
            """
            The error checks:
            """
        ),
        code(
            r"""
            run_checks(
                [
                    (
                        "incomplete head",
                        lambda: parse_error(b"GET / HTTP/1.1\r\nHost: x\r\n"),
                        "ValueError: incomplete request",
                    ),
                    (
                        "bad request line",
                        lambda: parse_error(b"get / HTTP/1.1\r\n\r\n"),
                        "ValueError: bad request line",
                    ),
                    (
                        "bad version",
                        lambda: parse_error(b"GET / SPDY/3\r\n\r\n"),
                        "ValueError: bad request line",
                    ),
                    (
                        "bad header line",
                        lambda: parse_error(b"GET / HTTP/1.1\r\nNoColon\r\n\r\n"),
                        "ValueError: bad header line",
                    ),
                    (
                        "short body",
                        lambda: parse_error(b"POST / HTTP/1.1\r\nContent-Length: 9\r\n\r\nabc"),
                        "ValueError: body shorter than Content-Length",
                    ),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 2 — a raw socket server with routing, JSON and 404

            Write `handle_raw_request(raw: bytes) -> bytes`, the whole application of a raw
            server: parse (use your `parse_http_request`), route, and return complete response
            bytes. Every response is JSON with `Content-Type: application/json`, a correct
            `Content-Length` and `Connection: close`, and a status line
            `HTTP/1.1 <code> <phrase>`. Routes over the `LAB_NOTES` dict below:

            | Request | Response |
            | --- | --- |
            | `GET /health` | 200 `{"status": "ok"}` |
            | `GET /notes` | 200, the list of notes sorted by id |
            | `GET /notes/<id>` | 200 the note; 404 `{"error": "note <id> not found"}` (also for a non-numeric id) |
            | `POST /echo` | 200 `{"received": <parsed JSON body>}`; 400 `{"error": "invalid JSON"}` |
            | known path, other method | 405 `{"error": "method not allowed"}` and an `Allow` header (`GET` or `POST`) |
            | anything else | 404 `{"error": "no route <METHOD> <path>"}` |
            | unparseable request | 400 `{"error": "<the ValueError message>"}` |

            The check cell serves your function with `serve_raw` and talks to it over a real
            socket with `http.client`.
            """
        ),
        code(
            """
            LAB_NOTES = {
                1: {"id": 1, "title": "Buy tea", "pinned": True},
                2: {"id": 2, "title": "Call Ravi", "pinned": False},
            }
            """
        ),
        md("Your solution:"),
        code(
            '''
            def handle_raw_request(raw: bytes) -> bytes:
                """Parse, route and answer one raw HTTP request with a JSON response."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 2:"),
        code(
            r'''
            def json_call(port: int, method: str, path: str, body: bytes | None = None) -> tuple[int, object]:
                """Status and decoded JSON body of one request (the body text if it is not JSON)."""
                status, _headers, raw_body = http_call(port, method, path, body)
                try:
                    return status, json.loads(raw_body)
                except json.JSONDecodeError:
                    return status, raw_body.decode(errors="replace")


            def raw_status_line(raw_request: bytes) -> bytes:
                """First line of handle_raw_request's answer to raw_request."""
                return handle_raw_request(raw_request).split(b"\r\n", 1)[0]


            LAB2_REQUESTS = [  # (method, path and a label after the space, body)
                ("GET", "/health", None),
                ("GET", "/notes", None),
                ("GET", "/notes/2", None),
                ("GET", "/notes/9", None),
                ("GET", "/notes/abc", None),
                ("POST", "/echo", b'{"cups": 2}'),
                ("POST", "/echo bad", b"{oops"),
                ("GET", "/nope", None),
            ]
            with serve_raw(handle_raw_request) as lab_port:
                lab2_answers = {
                    path: json_call(lab_port, method, path.split(" ")[0], body)
                    for method, path, body in LAB2_REQUESTS
                }
                lab2_delete = http_call(lab_port, "DELETE", "/health")
                lab2_health = http_call(lab_port, "GET", "/health")
            '''
        ),
        md(
            """
            The routing checks (the requests above went through a real socket):
            """
        ),
        code(
            r"""
            run_checks(
                [
                    ("GET /health", lambda: lab2_answers["/health"], (200, {"status": "ok"})),
                    ("GET /notes sorted", lambda: lab2_answers["/notes"], (200, [LAB_NOTES[1], LAB_NOTES[2]])),
                    ("GET /notes/2", lambda: lab2_answers["/notes/2"], (200, LAB_NOTES[2])),
                    (
                        "GET /notes/9 -> 404",
                        lambda: lab2_answers["/notes/9"],
                        (404, {"error": "note 9 not found"}),
                    ),
                    ("GET /notes/abc -> 404", lambda: lab2_answers["/notes/abc"][0], 404),
                    ("POST /echo", lambda: lab2_answers["/echo"], (200, {"received": {"cups": 2}})),
                    (
                        "POST /echo bad JSON -> 400",
                        lambda: lab2_answers["/echo bad"],
                        (400, {"error": "invalid JSON"}),
                    ),
                    (
                        "unknown route -> 404",
                        lambda: lab2_answers["/nope"],
                        (404, {"error": "no route GET /nope"}),
                    ),
                ]
            )
            """
        ),
        md(
            """
            The protocol checks (status line, headers, `Allow`):
            """
        ),
        code(
            r"""
            run_checks(
                [
                    (
                        "DELETE /health -> 405 + Allow",
                        lambda: (lab2_delete[0], lab2_delete[1].get("allow")),
                        (405, "GET"),
                    ),
                    ("JSON content type", lambda: lab2_health[1].get("content-type"), "application/json"),
                    ("Connection: close", lambda: lab2_health[1].get("connection"), "close"),
                    (
                        "Content-Length matches",
                        lambda: int(lab2_health[1]["content-length"]) == len(lab2_health[2]),
                        True,
                    ),
                    (
                        "status line has the phrase",
                        lambda: raw_status_line(b"GET /nope HTTP/1.1\r\n\r\n"),
                        b"HTTP/1.1 404 Not Found",
                    ),
                    (
                        "unparseable -> 400",
                        lambda: raw_status_line(b"garbage\r\n\r\n"),
                        b"HTTP/1.1 400 Bad Request",
                    ),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 3 — a WSGI timing middleware

            Write `TimingMiddleware(app, clock=time.perf_counter)`, a WSGI middleware that:

            - reads `clock()` when the request starts and again when the wrapped app calls
              `start_response`;
            - adds a `Server-Timing` header `app;dur=<milliseconds with one decimal>` (for
              readings 1.0 and 1.25: `app;dur=250.0`), keeping the app's status and headers;
            - appends the duration in **seconds** to `self.durations`;
            - passes `exc_info` through and returns the app's iterable unchanged (so the
              server still calls its `close()`).

            The checks call it through `wsgiref.validate.validator`, which rejects protocol
            mistakes.
            """
        ),
        md("Your solution:"),
        code(
            '''
            class TimingMiddleware:
                """WSGI middleware that reports app time in a Server-Timing header."""

                def __init__(
                    self, app: Callable[..., Iterable[bytes]], clock: Callable[[], float] = time.perf_counter
                ) -> None:
                    """Wrap app; clock returns seconds."""
                    self.app = app
                    self.clock = clock
                    self.durations: list[float] = []

                def __call__(
                    self, environ: dict[str, Any], start_response: Callable[..., object]
                ) -> Iterable[bytes]:
                    """Time the app up to its start_response call and add the header."""
                    raise NotImplementedError
            '''
        ),
        md("Check exercise 3:"),
        code(
            r'''
            from wsgiref.validate import validator


            class ClosingBody:
                """A WSGI body iterable that records whether close() was called."""

                closed = False

                def __iter__(self) -> Iterator[bytes]:
                    """Yield the one body chunk."""
                    yield b"made it"

                def close(self) -> None:
                    """Called by the server when it is done with the body."""
                    ClosingBody.closed = True


            def closing_app(environ: dict[str, Any], start_response: Callable[..., object]) -> ClosingBody:
                """A WSGI app whose body must be closed by the server."""
                start_response("201 Created", [("Content-Type", "text/plain"), ("X-App", "yes")])
                return ClosingBody()
            '''
        ),
        md(
            """
            `timed_call` runs a WSGI app through `wsgiref.validate.validator` and closes the body, as a
            server would; then the middleware runs with a fake clock (readings 1.0 and 1.25):
            """
        ),
        code(
            r'''
            def timed_call(app: Callable[..., Iterable[bytes]]) -> tuple[str, list[tuple[str, str]], bytes]:
                """Call app through wsgiref's validator; close the body like a server would."""
                environ: dict[str, Any] = {"QUERY_STRING": "", "PATH_INFO": "/hello", "SCRIPT_NAME": ""}
                wsgiref.util.setup_testing_defaults(environ)
                recorded: dict[str, Any] = {}

                def start_response(
                    status: str, headers: list[tuple[str, str]], exc_info: object = None
                ) -> Callable[[bytes], None]:
                    """Record what the app sent."""
                    recorded.update(status=status, headers=headers)
                    return lambda data: None

                body_iterable = validator(app)(environ, start_response)
                body = b"".join(body_iterable)
                body_iterable.close()
                return recorded["status"], recorded["headers"], body


            ClosingBody.closed = False
            timed = TimingMiddleware(closing_app, clock=ManualClock(1.0, 1.25))
            timed_result: tuple[str, list[tuple[str, str]], bytes] = ("not run", [], b"")
            try:
                timed_result = timed_call(timed)
            except Exception as error:
                timed_result = ("raised", [], type(error).__name__.encode())
            '''
        ),
        md(
            """
            Check exercise 3:
            """
        ),
        code(
            r'''
            def real_clock_timing() -> bool:
                """True if the middleware around wsgi_demo.app adds a well-formed header."""
                headers = dict(timed_call(TimingMiddleware(wsgi_demo.app))[1])
                return re.fullmatch(r"app;dur=\d+\.\d", headers.get("Server-Timing", "")) is not None


            run_checks(
                [
                    ("status kept", lambda: timed_result[0], "201 Created"),
                    (
                        "Server-Timing header",
                        lambda: dict(timed_result[1]).get("Server-Timing"),
                        "app;dur=250.0",
                    ),
                    ("app headers kept", lambda: dict(timed_result[1]).get("X-App"), "yes"),
                    ("body unchanged", lambda: timed_result[2], b"made it"),
                    ("duration recorded in seconds", lambda: timed.durations, [0.25]),
                    ("close() reaches the app's iterable", lambda: ClosingBody.closed, True),
                    ("works with the real clock", real_clock_timing, True),
                ]
            )
            '''
        ),
    ]


def _lab_cells_part_2() -> list[NotebookNode]:
    """Lab 6.1 exercises 4-5."""
    return [
        md(
            """
            #### Exercise 4 — a raw ASGI app with a streaming endpoint

            Write `countdown_app(scope, receive, send)`, a raw ASGI app (no framework):

            - **lifespan:** answer `lifespan.startup` with `lifespan.startup.complete` and
              `lifespan.shutdown` with `lifespan.shutdown.complete`, then return.
            - **`GET /countdown?start=N`** (N an integer from 1 to 10, default 3): status 200,
              header `content-type: text/plain; charset=utf-8`, then **one body message per
              line** with `more_body=True`: `"N\\n"`, …, `"1\\n"`, `"liftoff\\n"`, and finally an
              empty body with `more_body=False`. Await `asyncio.sleep(COUNTDOWN_TICK)` after
              each line.
            - Bad `start` (not an integer, or out of range): status 400, the same content type,
              and a single body message `b"start must be an integer from 1 to 10\\n"`.
            - Anything else: status 404 and a single body `b"not found\\n"`.
            """
        ),
        md("Your solution:"),
        code(
            '''
            COUNTDOWN_TICK = 0.0  # seconds between lines; set to 0.5 to watch it under Uvicorn


            async def countdown_app(
                scope: dict[str, Any],
                receive: Callable[[], Awaitable[dict[str, Any]]],
                send: Callable[[dict[str, Any]], Awaitable[None]],
            ) -> None:
                """Raw ASGI app: lifespan support and a streaming GET /countdown."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 4:"),
        code(
            r'''
            async def countdown_messages(query: bytes, path: str = "/countdown") -> list[dict[str, Any]]:
                """Messages countdown_app sends for one GET (a one-item error list if it raised)."""
                try:
                    return await call_asgi(countdown_app, http_scope("GET", path, query))
                except Exception as error:
                    return [{"type": f"raised {type(error).__name__}"}]


            text_plain = [(b"content-type", b"text/plain; charset=utf-8")]
            three = await countdown_messages(b"start=3")
            default = await countdown_messages(b"")
            bad = await countdown_messages(b"start=99")
            not_a_number = await countdown_messages(b"start=ten")
            missing = await countdown_messages(b"", path="/elsewhere")
            try:
                lifespan_events = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]
                lifespan_sent = await call_asgi(countdown_app, {"type": "lifespan"}, lifespan_events)
            except Exception as error:
                lifespan_sent = f"raised {type(error).__name__}"
            try:
                countdown_transport = httpx.ASGITransport(app=countdown_app)
                async with httpx.AsyncClient(transport=countdown_transport, base_url="http://lab") as client:
                    countdown_text = (await client.get("/countdown", params={"start": 2})).text
            except Exception as error:
                countdown_text = f"raised {type(error).__name__}"
            '''
        ),
        md(
            """
            Check exercise 4:
            """
        ),
        code(
            r"""
            run_checks(
                [
                    (
                        "start message",
                        lambda: three[0],
                        {"type": "http.response.start", "status": 200, "headers": text_plain},
                    ),
                    (
                        "one body message per line",
                        lambda: [message.get("body") for message in three[1:]],
                        [b"3\n", b"2\n", b"1\n", b"liftoff\n", b""],
                    ),
                    (
                        "more_body flags",
                        lambda: [message.get("more_body", False) for message in three[1:]],
                        [True, True, True, True, False],
                    ),
                    ("default start is 3", lambda: len(default), 6),
                    (
                        "out of range -> 400",
                        lambda: (bad[0].get("status"), bad[-1].get("body")),
                        (400, b"start must be an integer from 1 to 10\n"),
                    ),
                    ("not a number -> 400", lambda: not_a_number[0].get("status"), 400),
                    (
                        "unknown path -> 404",
                        lambda: (missing[0].get("status"), missing[-1].get("body")),
                        (404, b"not found\n"),
                    ),
                    (
                        "lifespan",
                        lambda: lifespan_sent,
                        [{"type": "lifespan.startup.complete"}, {"type": "lifespan.shutdown.complete"}],
                    ),
                    ("through httpx.ASGITransport", lambda: countdown_text, "2\n1\nliftoff\n"),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 5 — an ASGI micro-framework, compared with FastAPI

            Complete `MicroFramework` (aim for about 150 lines with `Request`) so this works:

            ```python
            app = MicroFramework()

            @app.route("/notes/{note_id}", methods=["GET"])
            async def get_note(request: Request, note_id: int) -> dict:
                return NOTES[note_id]
            ```

            Rules:

            - `route(path, methods=("GET",))` registers the handler and returns it unchanged.
              A `{name}` segment matches one path segment; the value is converted with the
              handler's annotation for `name` (`int` → `int(value)`; anything else stays `str`).
              A failed conversion means "no match".
            - The handler is called as `await handler(request, **path_params)`. It returns a
              dict or list (→ 200 JSON) or a `(status, payload)` tuple.
            - No route matches the path → 404 `{"detail": "Not Found"}`. The path matches but
              not the method → 405 `{"detail": "Method Not Allowed"}` with an `allow` header
              listing the allowed methods (sorted, comma-separated). The handler raises → 500
              `{"detail": "Internal Server Error"}`.
            - Every response has `content-type: application/json` and a `content-length`.
            - Lifespan events are answered with `.complete`.

            `Request` is given: `method`, `path`, `query` (first value per name), `headers`
            (lower-cased str dict), `await request.body()`, `await request.json()`.
            """
        ),
        code(
            '''
            class Request:
                """What a handler receives: the scope's data plus the body, read on demand."""

                def __init__(
                    self, scope: dict[str, Any], receive: Callable[[], Awaitable[dict[str, Any]]]
                ) -> None:
                    """Copy the useful parts of the scope."""
                    self.method: str = scope["method"]
                    self.path: str = scope["path"]
                    parsed = urllib.parse.parse_qs(scope["query_string"].decode())
                    self.query = {name: values[0] for name, values in parsed.items()}
                    self.headers = {name.decode().lower(): value.decode() for name, value in scope["headers"]}
                    self._receive = receive

                async def body(self) -> bytes:
                    """Read every http.request message and join the bodies."""
                    chunks, more_body = [], True
                    while more_body:
                        message = await self._receive()
                        chunks.append(message.get("body", b""))
                        more_body = message.get("more_body", False)
                    return b"".join(chunks)

                async def json(self) -> Any:
                    """The body parsed as JSON."""
                    return json.loads(await self.body() or b"null")
            '''
        ),
        md("Your solution:"),
        code(
            '''
            type Handler = Callable[..., Awaitable[object]]


            class MicroFramework:
                """A tiny ASGI framework: decorator routing, typed path parameters, JSON responses."""

                def __init__(self) -> None:
                    """Start with no routes."""
                    self.routes: list[tuple[str, frozenset[str], Handler]] = []

                def route(self, path: str, methods: Iterable[str] = ("GET",)) -> Callable[[Handler], Handler]:
                    """Decorator: register handler for path and methods."""
                    raise NotImplementedError

                async def __call__(
                    self,
                    scope: dict[str, Any],
                    receive: Callable[[], Awaitable[dict[str, Any]]],
                    send: Callable[[dict[str, Any]], Awaitable[None]],
                ) -> None:
                    """ASGI entry point."""
                    raise NotImplementedError
            '''
        ),
        md(
            """
            Check exercise 5. The check builds the same small Notes API twice, once on your
            framework and once on FastAPI, sends both the same requests, and compares status
            codes and JSON. One difference is expected and printed, not checked: FastAPI answers
            `GET /notes/abc` with **422** and a detailed validation error, because it validates
            path parameters instead of just failing to match them.
            """
        ),
        code(
            '''
            from fastapi import FastAPI, HTTPException


            def seed_notes() -> dict[int, dict[str, object]]:
                """Fresh copy of the demo data for each app."""
                return {1: {"id": 1, "title": "Buy tea"}, 2: {"id": 2, "title": "Call Ravi"}}


            def build_micro_notes() -> MicroFramework:
                """The Notes demo on MicroFramework."""
                notes, micro = seed_notes(), MicroFramework()

                @micro.route("/notes")
                async def list_notes(request: Request) -> list[dict[str, object]]:
                    """GET /notes."""
                    return list(notes.values())

                @micro.route("/notes", methods=["POST"])
                async def create_note(request: Request) -> tuple[int, dict[str, object]]:
                    """POST /notes: 201 and the new note."""
                    payload = await request.json()
                    note = {"id": max(notes) + 1, "title": payload["title"]}
                    notes[note["id"]] = note
                    return 201, note

                @micro.route("/notes/{note_id}")
                async def get_note(request: Request, note_id: int) -> object:
                    """GET /notes/{note_id}, or a 404 tuple."""
                    if note_id not in notes:
                        return 404, {"detail": f"note {note_id} not found"}
                    return notes[note_id]

                @micro.route("/boom")
                async def boom(request: Request) -> object:
                    """A handler with a bug: the framework must answer 500."""
                    raise RuntimeError("bug")

                return micro
            '''
        ),
        md("The FastAPI equivalent, and the comparison:"),
        code(
            r'''
            def build_fastapi_notes() -> FastAPI:
                """The same Notes demo on FastAPI."""
                notes, api = seed_notes(), FastAPI()

                @api.get("/notes")
                async def list_notes() -> list[dict[str, object]]:
                    """GET /notes."""
                    return list(notes.values())

                @api.post("/notes", status_code=201)
                async def create_note(payload: dict[str, str]) -> dict[str, object]:
                    """POST /notes: 201 and the new note."""
                    note = {"id": max(notes) + 1, "title": payload["title"]}
                    notes[note["id"]] = note
                    return note

                @api.get("/notes/{note_id}")
                async def get_note(note_id: int) -> dict[str, object]:
                    """GET /notes/{note_id}, or HTTP 404."""
                    if note_id not in notes:
                        raise HTTPException(status_code=404, detail=f"note {note_id} not found")
                    return notes[note_id]

                return api
            '''
        ),
        md(
            """
            Send both apps the same seven requests:
            """
        ),
        code(
            r'''
            COMPARISON_REQUESTS = [
                ("GET", "/notes", None),
                ("GET", "/notes/2", None),
                ("GET", "/notes/99", None),
                ("POST", "/notes", {"title": "Chai"}),
                ("GET", "/notes/3", None),
                ("DELETE", "/notes", None),
                ("GET", "/nope", None),
            ]


            async def responses_from(build_app: Callable[[], Callable[..., Awaitable[None]]]) -> object:
                """(status, json) for COMPARISON_REQUESTS sent to a fresh app, or the error raised."""
                answers = []
                try:
                    transport = httpx.ASGITransport(app=build_app(), raise_app_exceptions=False)
                    async with httpx.AsyncClient(transport=transport, base_url="http://lab") as client:
                        for method, path, body in COMPARISON_REQUESTS:
                            reply = await client.request(method, path, json=body)
                            answers.append((reply.status_code, reply.json()))
                except Exception as error:
                    return f"raised {type(error).__name__}"
                return answers


            fastapi_answers = await responses_from(build_fastapi_notes)
            micro_answers = await responses_from(build_micro_notes)
            '''
        ),
        md(
            """
            Three behaviours that only the micro-framework is checked for, then the checks:
            """
        ),
        code(
            r'''
            async def micro_extra() -> dict[str, object]:
                """Allow header, crash handling and a non-int path parameter on the micro app."""
                try:
                    transport = httpx.ASGITransport(app=build_micro_notes(), raise_app_exceptions=False)
                    async with httpx.AsyncClient(transport=transport, base_url="http://lab") as client:
                        not_allowed = await client.delete("/notes/1")
                        crashed = await client.get("/boom")
                        not_int = await client.get("/notes/abc")
                except Exception as error:
                    return {"error": f"raised {type(error).__name__}"}
                return {
                    "allow": not_allowed.headers.get("allow"),
                    "content-type": not_allowed.headers.get("content-type"),
                    "crash": (crashed.status_code, crashed.json()),
                    "not int": not_int.status_code,
                }


            def route_returns_handler() -> bool:
                """True if route() hands back the decorated function unchanged."""
                return MicroFramework().route("/x")(seed_notes) is seed_notes


            extra = await micro_extra()
            run_checks(
                [
                    ("same answers as FastAPI for 7 requests", lambda: micro_answers, fastapi_answers),
                    ("405 lists allowed methods", lambda: extra["allow"], "GET"),
                    (
                        "handler error -> 500 JSON",
                        lambda: extra["crash"],
                        (500, {"detail": "Internal Server Error"}),
                    ),
                    ("non-int path parameter -> 404", lambda: extra["not int"], 404),
                    ("JSON content type", lambda: extra["content-type"], "application/json"),
                    ("route() returns the handler", route_returns_handler, True),
                ]
            )
            '''
        ),
        md(
            """
            The difference FastAPI makes on a bad path parameter, and the size of your framework:
            """
        ),
        code(
            r"""
            fastapi_transport = httpx.ASGITransport(app=build_fastapi_notes())
            async with httpx.AsyncClient(transport=fastapi_transport, base_url="http://lab") as client:
                print(f"FastAPI answers GET /notes/abc with {(await client.get('/notes/abc')).status_code}")
            members = [getattr(member, "__func__", member) for member in vars(MicroFramework).values()]
            functions = [member for member in members if inspect.isfunction(member)]
            method_lines = sum(len(inspect.getsource(function).splitlines()) for function in functions)
            print(f"MicroFramework methods: {method_lines} lines (inspect.getsource needs a file for classes)")
            """
        ),
        md(
            """
            What the 150 lines leave out, and FastAPI provides: validation of query, header,
            cookie and body parameters with clear 422 errors; response models and
            serialization; dependency injection; OpenAPI docs; middleware, CORS, sessions;
            background tasks; WebSockets; exception handlers; and years of edge cases. The next
            unit uses all of it.
            """
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 6.1."""
    return [
        md(
            """
            ### Recap — Unit 6.1

            | Concept | One-line takeaway | JS / Node equivalent |
            | --- | --- | --- |
            | TCP/IP, ports, DNS | TCP is an ordered **byte stream**; HTTP adds its own framing | `net` module |
            | TLS | handshake (SNI, ALPN, certificate check), then encrypted records; often ended at a proxy | `tls` module |
            | HTTP/1.1 message | request/status line, headers, blank line (CRLF CRLF), body of `Content-Length` bytes or chunked | what `http` parses for you |
            | Methods and status codes | safe vs idempotent; 401 who-are-you vs 403 no; 409 conflict; 422 invalid values; 429 slow down | same semantics |
            | REST design | plural nouns + verbs; query-string filters; limit/offset or cursor; `/v1`; idempotency keys | same conventions |
            | Raw socket server | blocking (serial) vs a thread per connection vs asyncio streams (one thread, many waits) | `http.createServer` ≈ the asyncio version |
            | WSGI | `app(environ, start_response) -> Iterable[bytes]`; one worker per in-flight request; Gunicorn | Express on a blocking server (no real equivalent) |
            | ASGI | `async app(scope, receive, send)`; http, websocket, lifespan; `more_body` streams; Uvicorn | Node's event loop with a standard app interface |
            | Middleware | WSGI wraps `start_response`; ASGI wraps `send` / `receive` | `app.use((req, res, next) => …)` |
            | Frameworks | Flask (WSGI micro), Django (full stack), Starlette (ASGI toolkit), FastAPI (types → validation + docs), Litestar | Express, NestJS, Koa, Fastify |
            | HTTP clients | reuse a client, always set timeouts, retry only retryable failures, stream big bodies; httpx does sync and async | `fetch` / undici / axios |

            **Further reading**

            - [`socket`](https://docs.python.org/3/library/socket.html),
              [`ssl`](https://docs.python.org/3/library/ssl.html),
              [`http.client`](https://docs.python.org/3/library/http.client.html),
              [`http` (`HTTPStatus`, `HTTPMethod`)](https://docs.python.org/3/library/http.html),
              [`asyncio` streams](https://docs.python.org/3/library/asyncio-stream.html),
              [`wsgiref`](https://docs.python.org/3/library/wsgiref.html),
              [`urllib.request`](https://docs.python.org/3/library/urllib.request.html)
            - [PEP 3333](https://peps.python.org/pep-3333/) (WSGI),
              [PEP 758](https://peps.python.org/pep-0758/) (`except A, B` without brackets)
            - [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110) (HTTP semantics),
              [RFC 9112](https://www.rfc-editor.org/rfc/rfc9112) (HTTP/1.1),
              [RFC 8288](https://www.rfc-editor.org/rfc/rfc8288) (`Link` header)
            - [ASGI specification](https://asgi.readthedocs.io/), [Uvicorn](https://www.uvicorn.org/),
              [Starlette](https://www.starlette.io/), [HTTPX](https://www.python-httpx.org/),
              [Requests](https://requests.readthedocs.io/), [Gunicorn](https://gunicorn.org/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 6.1 and Lab 6.1."""
    return [
        *_overview_cells(),
        *_networking_cells(),
        *_http_anatomy_cells(),
        *_rest_cells(),
        *_raw_server_cells(),
        *_wsgi_cells(),
        *_asgi_cells(),
        *_framework_cells(),
        *_http_client_cells(),
        *_predict_cells(),
        *_lab_cells_part_1(),
        *_lab_cells_part_2(),
        *_recap_cells(),
    ]
