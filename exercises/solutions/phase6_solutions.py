"""Reference solutions for Phase 6 labs.

Run from the repository root:

    uv run python exercises/solutions/phase6_solutions.py            # every lab
    uv run python exercises/solutions/phase6_solutions.py "Lab 6.1"  # one lab

Each check_lab_6_N() repeats the notebook's check cells, so the notebook and this file test the
same things. Each solution sits between ``# >>> Lab 6.N exercise K`` and ``# <<<`` markers, so a
harness can paste it into the notebook's stub cell. Every server in these checks runs on
127.0.0.1 (a socket server thread, or an ASGI app called in-process); nothing touches the network.
"""

import asyncio
import contextlib
import dataclasses
import http.client
import inspect
import json
import re
import socket
import sys
import threading
import time
import urllib.parse
import wsgiref.util
from collections.abc import Awaitable, Callable, Iterable, Iterator
from datetime import UTC, date, datetime
from http import HTTPStatus
from typing import Annotated, Any, Literal
from wsgiref.validate import validator

import httpx
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.testclient import TestClient
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

type TestCase = tuple[str, Callable[[], object], object]


def run_checks(test_cases: list[TestCase]) -> None:
    """Run (label, thunk, expected) cases and print PASS/FAIL for each. Never raises."""
    passed_count = 0
    for label, thunk, expected in test_cases:
        try:
            actual = thunk()
        except Exception as error:  # a check must never stop the run
            print(f"FAIL  {label}: raised {type(error).__name__}: {error}")
            continue
        if actual == expected:
            passed_count += 1
            print(f"PASS  {label}")
        else:
            print(f"FAIL  {label}: expected {expected!r}, got {actual!r}")
    print(f"{passed_count}/{len(test_cases)} checks passed")


def validation_problems(thunk: Callable[[], object]) -> list[tuple[str, str]] | str:
    """Run thunk; list (dotted location, error type) for each validation problem, or "no error"."""
    try:
        thunk()
    except ValidationError as error:
        return [(".".join(map(str, problem["loc"])), problem["type"]) for problem in error.errors()]
    return "no error"


def raised_message(thunk: Callable[[], object]) -> str:
    """Call thunk and return "ErrorName: message" (memory addresses hidden), or "no error"."""
    try:
        thunk()
    except Exception as error:
        return re.sub(r" at 0x[0-9a-f]+", "", f"{type(error).__name__}: {error}")
    return "no error"


# ----- Lab 6.1: helpers from Unit 6.1.6 and the lab setup cell -----


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


LAB_NOTES = {
    1: {"id": 1, "title": "Buy tea", "pinned": True},
    2: {"id": 2, "title": "Call Ravi", "pinned": False},
}


# >>> Lab 6.1 exercise 1
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
    head, separator, rest = raw.partition(b"\r\n\r\n")
    if not separator:
        raise ValueError("incomplete request")
    request_line, *header_lines = head.decode("latin-1").split("\r\n")
    parts = request_line.split(" ")
    if (
        len(parts) != 3
        or not re.fullmatch(r"[A-Z]+", parts[0])
        or not parts[2].startswith("HTTP/1.")
    ):
        raise ValueError("bad request line")
    method, target, version = parts
    url = urllib.parse.urlsplit(target)
    headers: dict[str, str] = {}
    for line in header_lines:
        name, colon, value = line.partition(":")
        if not colon:
            raise ValueError("bad header line")
        key, value = name.strip().lower(), value.strip()
        headers[key] = f"{headers[key]}, {value}" if key in headers else value
    content_length = int(headers.get("content-length", "0"))
    if len(rest) < content_length:
        raise ValueError("body shorter than Content-Length")
    query = urllib.parse.parse_qs(url.query, keep_blank_values=True)
    return HttpRequest(method, url.path, query, version, headers, rest[:content_length])


# <<< Lab 6.1 exercise 1


# >>> Lab 6.1 exercise 2
ALLOWED_METHODS = {"/health": "GET", "/notes": "GET", "/echo": "POST"}


def json_reply(
    status: int, payload: object, extra_headers: Iterable[tuple[str, str]] = ()
) -> bytes:
    """Complete HTTP/1.1 response bytes with a JSON body."""
    body = json.dumps(payload).encode()
    lines = [
        f"HTTP/1.1 {status} {HTTPStatus(status).phrase}",
        "Content-Type: application/json",
        f"Content-Length: {len(body)}",
        "Connection: close",
        *(f"{name}: {value}" for name, value in extra_headers),
    ]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body


def handle_raw_request(raw: bytes) -> bytes:
    """Parse, route and answer one raw HTTP request with a JSON response."""
    try:
        request = parse_http_request(raw)
    except ValueError as error:
        return json_reply(400, {"error": str(error)})
    path = request.path
    if path.startswith("/notes/") and path.count("/") == 2:
        if request.method != "GET":
            return json_reply(405, {"error": "method not allowed"}, [("Allow", "GET")])
        note_id = path.removeprefix("/notes/")
        note = LAB_NOTES.get(int(note_id)) if note_id.isdigit() else None
        if note is None:
            return json_reply(404, {"error": f"note {note_id} not found"})
        return json_reply(200, note)
    allowed = ALLOWED_METHODS.get(path)
    if allowed is None:
        return json_reply(404, {"error": f"no route {request.method} {path}"})
    if request.method != allowed:
        return json_reply(405, {"error": "method not allowed"}, [("Allow", allowed)])
    if path == "/health":
        return json_reply(200, {"status": "ok"})
    if path == "/notes":
        return json_reply(200, [LAB_NOTES[note_id] for note_id in sorted(LAB_NOTES)])
    try:
        return json_reply(200, {"received": json.loads(request.body)})
    except json.JSONDecodeError:
        return json_reply(400, {"error": "invalid JSON"})


# <<< Lab 6.1 exercise 2


# >>> Lab 6.1 exercise 3
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
        started = self.clock()

        def timed_start_response(
            status: str, headers: list[tuple[str, str]], exc_info: object = None
        ) -> object:
            """Add the Server-Timing header and record the duration."""
            duration = self.clock() - started
            self.durations.append(duration)
            timing = ("Server-Timing", f"app;dur={duration * 1000:.1f}")
            return start_response(status, [*headers, timing], exc_info)

        return self.app(environ, timed_start_response)


# <<< Lab 6.1 exercise 3


# >>> Lab 6.1 exercise 4
COUNTDOWN_TICK = 0.0  # seconds between lines; set to 0.5 to watch it under Uvicorn
TEXT_PLAIN = [(b"content-type", b"text/plain; charset=utf-8")]


async def send_text(
    send: Callable[[dict[str, Any]], Awaitable[None]], status: int, body: bytes
) -> None:
    """A complete plain-text response in one body message."""
    await send({"type": "http.response.start", "status": status, "headers": TEXT_PLAIN})
    await send({"type": "http.response.body", "body": body})


async def countdown_app(
    scope: dict[str, Any],
    receive: Callable[[], Awaitable[dict[str, Any]]],
    send: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    """Raw ASGI app: lifespan support and a streaming GET /countdown."""
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
    if scope["type"] != "http":
        return
    if (scope["method"], scope["path"]) != ("GET", "/countdown"):
        await send_text(send, 404, b"not found\n")
        return
    query = urllib.parse.parse_qs(scope["query_string"].decode())
    raw_start = query.get("start", ["3"])[0]
    if not raw_start.isdecimal() or not 1 <= int(raw_start) <= 10:
        await send_text(send, 400, b"start must be an integer from 1 to 10\n")
        return
    await send({"type": "http.response.start", "status": 200, "headers": TEXT_PLAIN})
    lines = [*(f"{number}\n" for number in range(int(raw_start), 0, -1)), "liftoff\n"]
    for line in lines:
        await send({"type": "http.response.body", "body": line.encode(), "more_body": True})
        await asyncio.sleep(COUNTDOWN_TICK)
    await send({"type": "http.response.body", "body": b"", "more_body": False})


# <<< Lab 6.1 exercise 4


class Request:
    """What a handler receives: the scope's data plus the body, read on demand (given)."""

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


# >>> Lab 6.1 exercise 5
type Handler = Callable[..., Awaitable[object]]
type Send = Callable[[dict[str, Any]], Awaitable[None]]


class MicroFramework:
    """A tiny ASGI framework: decorator routing, typed path parameters, JSON responses."""

    def __init__(self) -> None:
        """Start with no routes."""
        self.routes: list[tuple[str, frozenset[str], Handler]] = []

    def route(self, path: str, methods: Iterable[str] = ("GET",)) -> Callable[[Handler], Handler]:
        """Decorator: register handler for path and methods."""

        def register(handler: Handler) -> Handler:
            """Store the route and return the handler unchanged."""
            allowed = frozenset(method.upper() for method in methods)
            self.routes.append((path, allowed, handler))
            return handler

        return register

    @staticmethod
    def match(template: str, path: str, handler: Handler) -> dict[str, object] | None:
        """Path parameters if path fits template (converted by annotation), else None."""
        template_parts, path_parts = template.strip("/").split("/"), path.strip("/").split("/")
        if len(template_parts) != len(path_parts):
            return None
        parameters = inspect.signature(handler).parameters
        path_params: dict[str, object] = {}
        for template_part, path_part in zip(template_parts, path_parts, strict=True):
            if template_part.startswith("{") and template_part.endswith("}"):
                name = template_part[1:-1]
                annotation = parameters[name].annotation if name in parameters else str
                converter = annotation if annotation in (int, float) else str
                try:
                    path_params[name] = converter(path_part)
                except ValueError:
                    return None
            elif template_part != path_part:
                return None
        return path_params

    @staticmethod
    async def send_json(
        send: Send, status: int, payload: object, headers: Iterable[tuple[bytes, bytes]] = ()
    ) -> None:
        """A complete JSON response."""
        body = json.dumps(payload).encode()
        response_headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            *headers,
        ]
        await send({"type": "http.response.start", "status": status, "headers": response_headers})
        await send({"type": "http.response.body", "body": body})

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Send,
    ) -> None:
        """ASGI entry point."""
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                await send({"type": f"{message['type']}.complete"})
                if message["type"] == "lifespan.shutdown":
                    return
        if scope["type"] != "http":
            return
        request = Request(scope, receive)
        allowed: set[str] = set()
        for template, methods, handler in self.routes:
            path_params = self.match(template, request.path, handler)
            if path_params is None:
                continue
            if request.method not in methods:
                allowed |= methods
                continue
            try:
                result = await handler(request, **path_params)
            except Exception:
                await self.send_json(send, 500, {"detail": "Internal Server Error"})
                return
            status, payload = result if isinstance(result, tuple) else (200, result)
            await self.send_json(send, status, payload)
            return
        if allowed:
            allow_header = (b"allow", ", ".join(sorted(allowed)).encode())
            await self.send_json(send, 405, {"detail": "Method Not Allowed"}, [allow_header])
            return
        await self.send_json(send, 404, {"detail": "Not Found"})


# <<< Lab 6.1 exercise 5


# ----- Lab 6.1: checks (the notebook's check cells) -----


def check_exercise_6_1_1() -> None:
    """Exercise 1 checks."""
    sample_get = (
        b"GET /notes/search?tag=work&tag=home&q=green%20tea HTTP/1.1\r\n"
        b"Host: localhost\r\nAccept: application/json\r\nX-Tag: a\r\nx-tag: b\r\n\r\n"
    )
    sample_post = b'POST /echo HTTP/1.1\r\nContent-Length: 7\r\n\r\n{"a":1}EXTRA'

    def parsed_line(raw: bytes) -> tuple[str, str, str]:
        """Method, path and version of a parsed request."""
        request = parse_http_request(raw)
        return request.method, request.path, request.version

    run_checks(
        [
            (
                "method, path, version",
                lambda: parsed_line(sample_get),
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
            (
                "incomplete head",
                lambda: raised_message(
                    lambda: parse_http_request(b"GET / HTTP/1.1\r\nHost: x\r\n")
                ),
                "ValueError: incomplete request",
            ),
            (
                "bad request line",
                lambda: raised_message(lambda: parse_http_request(b"get / HTTP/1.1\r\n\r\n")),
                "ValueError: bad request line",
            ),
            (
                "bad version",
                lambda: raised_message(lambda: parse_http_request(b"GET / SPDY/3\r\n\r\n")),
                "ValueError: bad request line",
            ),
            (
                "bad header line",
                lambda: raised_message(
                    lambda: parse_http_request(b"GET / HTTP/1.1\r\nNoColon\r\n\r\n")
                ),
                "ValueError: bad header line",
            ),
            (
                "short body",
                lambda: raised_message(
                    lambda: parse_http_request(b"POST / HTTP/1.1\r\nContent-Length: 9\r\n\r\nabc")
                ),
                "ValueError: body shorter than Content-Length",
            ),
        ]
    )


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


def check_exercise_6_1_2() -> None:
    """Exercise 2 checks: a real socket server around handle_raw_request."""
    with serve_raw(handle_raw_request) as lab_port:
        answers = {
            path: json_call(lab_port, method, path.split(" ")[0], body)
            for method, path, body in LAB2_REQUESTS
        }
        delete_health = http_call(lab_port, "DELETE", "/health")
        health = http_call(lab_port, "GET", "/health")
    run_checks(
        [
            ("GET /health", lambda: answers["/health"], (200, {"status": "ok"})),
            ("GET /notes sorted", lambda: answers["/notes"], (200, [LAB_NOTES[1], LAB_NOTES[2]])),
            ("GET /notes/2", lambda: answers["/notes/2"], (200, LAB_NOTES[2])),
            (
                "GET /notes/9 -> 404",
                lambda: answers["/notes/9"],
                (404, {"error": "note 9 not found"}),
            ),
            ("GET /notes/abc -> 404", lambda: answers["/notes/abc"][0], 404),
            ("POST /echo", lambda: answers["/echo"], (200, {"received": {"cups": 2}})),
            (
                "POST /echo bad JSON -> 400",
                lambda: answers["/echo bad"],
                (400, {"error": "invalid JSON"}),
            ),
            (
                "unknown route -> 404",
                lambda: answers["/nope"],
                (404, {"error": "no route GET /nope"}),
            ),
        ]
    )
    run_checks(
        [
            (
                "DELETE /health -> 405 + Allow",
                lambda: (delete_health[0], delete_health[1].get("allow")),
                (405, "GET"),
            ),
            ("JSON content type", lambda: health[1].get("content-type"), "application/json"),
            ("Connection: close", lambda: health[1].get("connection"), "close"),
            (
                "Content-Length matches",
                lambda: int(health[1]["content-length"]) == len(health[2]),
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


def hello_app(environ: dict[str, Any], start_response: Callable[..., object]) -> list[bytes]:
    """Stand-in for wsgi_demo.app from Unit 6.1.5."""
    start_response("200 OK", [("Content-Type", "application/json")])
    return [b'{"message": "hello"}']


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


def check_exercise_6_1_3() -> None:
    """Exercise 3 checks."""
    ClosingBody.closed = False
    timed = TimingMiddleware(closing_app, clock=ManualClock(1.0, 1.25))
    timed_result: tuple[str, list[tuple[str, str]], bytes] = ("not run", [], b"")
    try:
        timed_result = timed_call(timed)
    except Exception as error:
        timed_result = ("raised", [], type(error).__name__.encode())
    real_clock_app = TimingMiddleware(hello_app)
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
            (
                "works with the real clock",
                lambda: (
                    re.fullmatch(
                        r"app;dur=\d+\.\d",
                        dict(timed_call(real_clock_app)[1]).get("Server-Timing", ""),
                    )
                    is not None
                ),
                True,
            ),
        ]
    )


async def _check_exercise_6_1_4() -> None:
    """Exercise 4 checks."""

    async def countdown_messages(query: bytes, path: str = "/countdown") -> object:
        """Messages countdown_app sends for one GET (or the error it raised)."""
        try:
            return await call_asgi(countdown_app, http_scope("GET", path, query))
        except Exception as error:
            return f"raised {type(error).__name__}"

    text_plain = [(b"content-type", b"text/plain; charset=utf-8")]
    three: Any = await countdown_messages(b"start=3")
    default: Any = await countdown_messages(b"")
    bad: Any = await countdown_messages(b"start=99")
    not_a_number: Any = await countdown_messages(b"start=ten")
    missing: Any = await countdown_messages(b"", path="/elsewhere")
    lifespan_sent = await call_asgi(
        countdown_app,
        {"type": "lifespan"},
        [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}],
    )
    transport = httpx.ASGITransport(app=countdown_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://lab") as lab_client:
        countdown_text = (await lab_client.get("/countdown", params={"start": 2})).text
    run_checks(
        [
            (
                "start message",
                lambda: three[0],
                {"type": "http.response.start", "status": 200, "headers": text_plain},
            ),
            (
                "one body message per line",
                lambda: [message["body"] for message in three[1:]],
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
                lambda: (bad[0]["status"], bad[1]["body"]),
                (400, b"start must be an integer from 1 to 10\n"),
            ),
            ("not a number -> 400", lambda: not_a_number[0]["status"], 400),
            (
                "unknown path -> 404",
                lambda: (missing[0]["status"], missing[1]["body"]),
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
        """GET one note, or 404."""
        if note_id not in notes:
            return 404, {"detail": f"note {note_id} not found"}
        return notes[note_id]

    @micro.route("/boom")
    async def boom(request: Request) -> object:
        """A handler with a bug: the framework must answer 500."""
        raise RuntimeError("bug")

    return micro


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
        """GET one note, or 404."""
        if note_id not in notes:
            raise HTTPException(status_code=404, detail=f"note {note_id} not found")
        return notes[note_id]

    return api


async def responses_from(build_app: Callable[[], Callable[..., Awaitable[None]]]) -> object:
    """(status, json) for a fixed list of requests to a fresh app."""
    requests_to_send = [
        ("GET", "/notes", None),
        ("GET", "/notes/2", None),
        ("GET", "/notes/99", None),
        ("POST", "/notes", {"title": "Chai"}),
        ("GET", "/notes/3", None),
        ("DELETE", "/notes", None),
        ("GET", "/nope", None),
    ]
    transport = httpx.ASGITransport(app=build_app(), raise_app_exceptions=False)
    answers = []
    async with httpx.AsyncClient(transport=transport, base_url="http://lab") as client:
        for method, path, body in requests_to_send:
            reply = await client.request(method, path, json=body)
            answers.append((reply.status_code, reply.json()))
    return answers


async def _check_exercise_6_1_5() -> None:
    """Exercise 5 checks."""
    fastapi_answers = await responses_from(build_fastapi_notes)
    micro_answers = await responses_from(build_micro_notes)
    transport = httpx.ASGITransport(app=build_micro_notes(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://lab") as client:
        not_allowed = await client.delete("/notes/1")
        crashed = await client.get("/boom")
        not_int = await client.get("/notes/abc")
    run_checks(
        [
            ("same answers as FastAPI for 7 requests", lambda: micro_answers, fastapi_answers),
            ("405 lists allowed methods", lambda: not_allowed.headers.get("allow"), "GET"),
            (
                "handler error -> 500 JSON",
                lambda: (crashed.status_code, crashed.json()),
                (500, {"detail": "Internal Server Error"}),
            ),
            ("non-int path parameter -> 404", lambda: not_int.status_code, 404),
            (
                "JSON content type",
                lambda: not_allowed.headers.get("content-type"),
                "application/json",
            ),
            (
                "route() returns the handler",
                lambda: MicroFramework().route("/x")(seed_notes) is seed_notes,
                True,
            ),
        ]
    )
    methods = [getattr(member, "__func__", member) for member in vars(MicroFramework).values()]
    method_lines = sum(
        len(inspect.getsource(method).splitlines())
        for method in methods
        if inspect.isfunction(method)
    )
    print(f"MicroFramework methods: {method_lines} lines")


def check_lab_6_1() -> None:
    """Run every Lab 6.1 check (each check prints PASS/FAIL)."""
    for title, check in (
        ("exercise 1", check_exercise_6_1_1),
        ("exercise 2", check_exercise_6_1_2),
        ("exercise 3", check_exercise_6_1_3),
        ("exercise 4", lambda: asyncio.run(_check_exercise_6_1_4())),
        ("exercise 5", lambda: asyncio.run(_check_exercise_6_1_5())),
    ):
        print(f"--- {title}")
        check()


# ----- Lab 6.2: reference solutions -----


# >>> Lab 6.2 exercise 1
class NoteCreate(BaseModel):
    """POST/PUT body: title (stripped, 1-100), body (max 1000, default ""), pinned."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: Annotated[str, Field(min_length=1, max_length=100)]
    body: Annotated[str, Field(max_length=1000)] = ""
    pinned: bool = False


class NoteUpdate(BaseModel):
    """PATCH body: the same fields, all optional; unknown keys rejected."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    body: Annotated[str, Field(max_length=1000)] | None = None
    pinned: bool | None = None


class NoteRead(BaseModel):
    """Response: id, title, body, pinned, created_at."""

    id: int
    title: str
    body: str
    pinned: bool
    created_at: datetime


def create_notes_app() -> FastAPI:
    """Notes API v1: a fresh app with its own empty in-memory store."""
    app = FastAPI()
    notes: dict[int, NoteRead] = {}
    counter = {"last_id": 0}

    def find(note_id: int) -> NoteRead:
        """The note with this id, or HTTP 404."""
        if note_id not in notes:
            raise HTTPException(status_code=404, detail=f"note {note_id} not found")
        return notes[note_id]

    @app.post("/notes", status_code=201)
    async def create_note(note: NoteCreate, response: Response) -> NoteRead:
        """POST /notes: 201 and the new note."""
        counter["last_id"] += 1
        created = NoteRead(id=counter["last_id"], created_at=datetime.now(UTC), **note.model_dump())
        notes[created.id] = created
        response.headers["Location"] = f"/notes/{created.id}"
        return created

    @app.get("/notes")
    async def list_notes() -> list[NoteRead]:
        """GET /notes."""
        return [notes[note_id] for note_id in sorted(notes)]

    @app.get("/notes/{note_id}")
    async def get_note(note_id: int) -> NoteRead:
        """GET one note, or 404."""
        return find(note_id)

    @app.put("/notes/{note_id}")
    async def replace_note(note_id: int, note: NoteCreate) -> NoteRead:
        """PUT: replace every client-owned field."""
        notes[note_id] = find(note_id).model_copy(update=note.model_dump())
        return notes[note_id]

    @app.delete("/notes/{note_id}", status_code=204)
    async def delete_note(note_id: int) -> None:
        """DELETE: 204, or 404."""
        find(note_id)
        del notes[note_id]

    return app


# <<< Lab 6.2 exercise 1


# >>> Lab 6.2 exercise 2
class NoteFilters(BaseModel):
    """Query parameters for GET /notes: q, pinned, sort, limit, offset; extras rejected."""

    model_config = ConfigDict(extra="forbid")

    q: Annotated[str | None, Field(max_length=50)] = None
    pinned: bool | None = None
    sort: Literal["id", "-id", "title", "-title"] = "id"
    limit: Annotated[int, Field(ge=1, le=50)] = 10
    offset: Annotated[int, Field(ge=0)] = 0


def filter_notes(notes: list[dict[str, Any]], filters: NoteFilters) -> dict[str, object]:
    """Filter, sort and paginate notes; total counts matches before pagination."""
    needle = filters.q.casefold() if filters.q else None

    def wanted(note: dict[str, Any]) -> bool:
        """True if the note passes the pinned and q filters."""
        if filters.pinned is not None and note["pinned"] != filters.pinned:
            return False
        text = f"{note['title']}\n{note['body']}".casefold()
        return needle is None or needle in text

    field_name = filters.sort.removeprefix("-")
    found = sorted(
        (note for note in notes if wanted(note)),
        key=lambda note: (
            str(note[field_name]).casefold() if field_name == "title" else note[field_name]
        ),
        reverse=filters.sort.startswith("-"),
    )
    page = found[filters.offset : filters.offset + filters.limit]
    return {"items": page, "total": len(found), "limit": filters.limit, "offset": filters.offset}


# <<< Lab 6.2 exercise 2


# >>> Lab 6.2 exercise 3
class UserRegistration(BaseModel):
    """Sign-up form with field rules and cross-field rules (see the exercise text)."""

    model_config = ConfigDict(extra="forbid")

    username: str
    email: EmailStr
    password: Annotated[str, Field(min_length=12)]
    password_confirm: Annotated[str, Field(exclude=True)]
    birth_date: date
    signup_date: date
    accept_terms: bool

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        """Strip and lower-case, then allow 3-20 of a-z, 0-9 and _."""
        normalized = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9_]{3,20}", normalized):
            raise ValueError("username must be 3-20 characters of a-z, 0-9 and _")
        return normalized

    @field_validator("password")
    @classmethod
    def letters_and_digits(cls, value: str) -> str:
        """At least one letter and one digit."""
        if not (re.search(r"[A-Za-z]", value) and re.search(r"\d", value)):
            raise ValueError("password needs at least one letter and one digit")
        return value

    @field_validator("accept_terms")
    @classmethod
    def terms_accepted(cls, value: bool) -> bool:
        """The terms must be accepted."""
        if not value:
            raise ValueError("the terms must be accepted")
        return value

    @model_validator(mode="after")
    def cross_field_rules(self) -> UserRegistration:
        """Passwords match; the user is at least 13 on signup_date."""
        if self.password != self.password_confirm:
            raise ValueError("passwords do not match")
        signup = self.signup_date
        try:
            cutoff = signup.replace(year=signup.year - 13)
        except ValueError:  # signing up on 29 February
            cutoff = signup.replace(year=signup.year - 13, day=28)
        if self.birth_date > cutoff:
            raise ValueError("you must be at least 13 years old to sign up")
        return self


# <<< Lab 6.2 exercise 3


# >>> Lab 6.2 exercise 4
class NotePatch(BaseModel):
    """PATCH body: optional title/body/pinned; explicit null and unknown keys rejected."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    body: Annotated[str, Field(max_length=1000)] | None = None
    pinned: bool | None = None

    @model_validator(mode="after")
    def reject_explicit_null(self) -> NotePatch:
        """None means "not sent"; a null sent by the client is an error."""
        nulled = sorted(name for name in self.model_fields_set if getattr(self, name) is None)
        if nulled:
            raise ValueError(f"fields cannot be null: {', '.join(nulled)}")
        return self


def create_patch_app(seed: dict[int, dict[str, Any]]) -> FastAPI:
    """GET and PATCH /notes/{note_id} over a copy of seed."""
    app = FastAPI()
    notes = {note_id: dict(note) for note_id, note in seed.items()}

    def find(note_id: int) -> dict[str, Any]:
        """The note with this id, or HTTP 404."""
        if note_id not in notes:
            raise HTTPException(status_code=404, detail=f"note {note_id} not found")
        return notes[note_id]

    @app.get("/notes/{note_id}")
    async def get_note(note_id: int) -> dict[str, Any]:
        """GET one note, or 404."""
        return find(note_id)

    @app.patch("/notes/{note_id}")
    async def patch_note(note_id: int, changes: NotePatch) -> dict[str, Any]:
        """PATCH: apply only the fields sent; bump version on a real change."""
        note = find(note_id)
        sent = changes.model_dump(exclude_unset=True)
        if any(note[name] != value for name, value in sent.items()):
            note.update(sent)
            note["version"] += 1
        return note

    return app


# <<< Lab 6.2 exercise 4


# >>> Lab 6.2 exercise 5
async def benchmark_endpoints(
    app: FastAPI, paths: list[str], request_count: int = 8
) -> dict[str, float]:
    """Wall seconds for request_count concurrent GETs of each path, in order."""
    timings: dict[str, float] = {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://bench") as client:
        for path in paths:
            started = time.perf_counter()
            await asyncio.gather(*(client.get(path) for _ in range(request_count)))
            timings[path] = time.perf_counter() - started
    return timings


def diagnose(timings: dict[str, float], delay: float, request_count: int) -> dict[str, str]:
    """ "serialized" if a path took at least 0.75 * delay * request_count, else "concurrent"."""
    threshold = 0.75 * delay * request_count
    return {
        path: "serialized" if seconds >= threshold else "concurrent"
        for path, seconds in timings.items()
    }


# <<< Lab 6.2 exercise 5


# ----- Lab 6.2: checks (the notebook's check cells) -----


def check_exercise_6_2_1() -> None:
    """Exercise 1 checks."""
    results: dict[str, Any] = {}
    with TestClient(create_notes_app()) as client:
        first = client.post("/notes", json={"title": "  Buy tea  ", "pinned": True})
        first_note = {key: value for key, value in first.json().items() if key != "created_at"}
        results["create"] = (first.status_code, first.headers.get("location"), first_note)
        results["created_at"] = type(datetime.fromisoformat(first.json()["created_at"])).__name__
        client.post("/notes", json={"title": "Call Ravi", "body": "about the trip"})
        results["list"] = [note["title"] for note in client.get("/notes").json()]
        results["get"] = client.get("/notes/2").json()["body"]
        results["missing"] = (client.get("/notes/99").status_code, client.get("/notes/99").json())
        results["bad id"] = client.get("/notes/abc").status_code
        invalid_bodies = [
            {"title": "   "},
            {"title": "x" * 101},
            {"title": "ok", "color": "red"},
            {"body": "x"},
        ]
        results["invalid"] = [
            client.post("/notes", json=body).status_code for body in invalid_bodies
        ]
        replaced = client.put("/notes/1", json={"title": "Buy green tea"})
        results["put"] = (replaced.status_code, replaced.json()["title"], replaced.json()["pinned"])
        results["put missing"] = client.put("/notes/99", json={"title": "x"}).status_code
        deleted = client.delete("/notes/1")
        results["delete"] = (
            deleted.status_code,
            deleted.content,
            client.get("/notes/1").status_code,
            client.delete("/notes/1").status_code,
        )
    with TestClient(create_notes_app()) as fresh_client:
        results["fresh store"] = fresh_client.get("/notes").json()
    run_checks(
        [
            (
                "POST: 201, Location, stripped title",
                lambda: results["create"],
                (201, "/notes/1", {"id": 1, "title": "Buy tea", "body": "", "pinned": True}),
            ),
            ("created_at parses as a datetime", lambda: results["created_at"], "datetime"),
            ("GET /notes in id order", lambda: results["list"], ["Buy tea", "Call Ravi"]),
            ("GET /notes/2", lambda: results["get"], "about the trip"),
            (
                "unknown id -> 404 detail",
                lambda: results["missing"],
                (404, {"detail": "note 99 not found"}),
            ),
            ("non-integer id -> 422", lambda: results["bad id"], 422),
            ("invalid bodies -> 422", lambda: results["invalid"], [422, 422, 422, 422]),
            ("PUT replaces every field", lambda: results["put"], (200, "Buy green tea", False)),
            ("PUT unknown id -> 404", lambda: results["put missing"], 404),
            ("DELETE: 204 empty, then 404", lambda: results["delete"], (204, b"", 404, 404)),
            ("each app has its own store", lambda: results["fresh store"], []),
            (
                "NoteUpdate: three optional fields",
                lambda: (
                    NoteUpdate().model_dump(exclude_unset=True),
                    sorted(NoteUpdate.model_fields),
                ),
                ({}, ["body", "pinned", "title"]),
            ),
            (
                "NoteUpdate forbids extras",
                lambda: validation_problems(lambda: NoteUpdate(color="red")),  # type: ignore[call-arg]
                [("color", "extra_forbidden")],
            ),
            (
                "NoteRead fields",
                lambda: sorted(NoteRead.model_fields),
                ["body", "created_at", "id", "pinned", "title"],
            ),
        ]
    )


SAMPLE_NOTES = [
    {"id": 1, "title": "Buy tea", "body": "Assam and Darjeeling", "pinned": True},
    {"id": 2, "title": "call Ravi", "body": "about the trip", "pinned": False},
    {"id": 3, "title": "Book tickets", "body": "Pune to Goa, December", "pinned": True},
    {"id": 4, "title": "Water plants", "body": "", "pinned": False},
    {"id": 5, "title": "Tea tasting notes", "body": "Nilgiri was brighter", "pinned": False},
    {"id": 6, "title": "Pay electricity bill", "body": "due on the 20th", "pinned": True},
    {"id": 7, "title": "Trip budget", "body": "tickets, hotel, tea estates", "pinned": False},
    {"id": 8, "title": "Read FastAPI docs", "body": "dependencies chapter", "pinned": False},
]


def check_exercise_6_2_2() -> None:
    """Exercise 2 checks."""
    filters_app = FastAPI()

    @filters_app.get("/notes")
    async def search_sample_notes(filters: Annotated[NoteFilters, Query()]) -> dict[str, object]:
        """Given endpoint: apply the model and the function to SAMPLE_NOTES."""
        return filter_notes(SAMPLE_NOTES, filters)

    def page_ids(query: str) -> object:
        """(ids on the page, total), or the status code if the request failed."""
        with TestClient(filters_app, raise_server_exceptions=False) as client:
            response = client.get(f"/notes?{query}")
        if response.status_code != 200:
            return response.status_code
        page = response.json()
        return [note["id"] for note in page["items"]], page["total"]

    def page_envelope() -> object:
        """The page JSON with the items blanked out."""
        with TestClient(filters_app) as client:
            return client.get("/notes?limit=2&offset=4").json() | {"items": None}

    run_checks(
        [
            ("defaults: first 8 by id", lambda: page_ids(""), ([1, 2, 3, 4, 5, 6, 7, 8], 8)),
            ("limit and offset", lambda: page_ids("limit=3&offset=3"), ([4, 5, 6], 8)),
            ("q matches title or body, any case", lambda: page_ids("q=TEA"), ([1, 5, 7], 3)),
            ("pinned=true", lambda: page_ids("pinned=true"), ([1, 3, 6], 3)),
            ("sort=-id with limit", lambda: page_ids("sort=-id&limit=2"), ([8, 7], 8)),
            ("sort=title ignores case", lambda: page_ids("sort=title&limit=3"), ([3, 1, 2], 8)),
            ("total counts before paging", lambda: page_ids("q=tea&limit=1&offset=1"), ([5], 3)),
            (
                "page echoes limit/offset",
                page_envelope,
                {"items": None, "total": 8, "limit": 2, "offset": 4},
            ),
            ("limit=0 -> 422", lambda: page_ids("limit=0"), 422),
            ("limit=51 -> 422", lambda: page_ids("limit=51"), 422),
            ("offset=-1 -> 422", lambda: page_ids("offset=-1"), 422),
            ("sort=newest -> 422", lambda: page_ids("sort=newest"), 422),
            ("q longer than 50 -> 422", lambda: page_ids("q=" + "x" * 51), 422),
            ("unknown parameter -> 422", lambda: page_ids("colour=red"), 422),
        ]
    )


VALID_SIGNUP = {
    "username": "  Asha_R ",
    "email": "asha@Example.com",
    "password": "chai4ever-and-more",
    "password_confirm": "chai4ever-and-more",
    "birth_date": "2000-05-17",
    "signup_date": "2026-11-17",
    "accept_terms": True,
}


def signup_error_locations(**changes: object) -> object:
    """Locations of the validation errors for VALID_SIGNUP with changes applied."""
    problems = validation_problems(
        lambda: UserRegistration.model_validate({**VALID_SIGNUP, **changes})
    )
    return problems if isinstance(problems, str) else [location for location, _type in problems]


def signup_messages(**changes: object) -> str:
    """All error messages for VALID_SIGNUP with changes applied, joined."""
    try:
        UserRegistration.model_validate({**VALID_SIGNUP, **changes})
    except ValidationError as error:
        return " | ".join(problem["msg"] for problem in error.errors())
    return "no error"


def check_exercise_6_2_3() -> None:
    """Exercise 3 checks."""
    run_checks(
        [
            (
                "valid registration dumps cleanly",
                lambda: UserRegistration.model_validate(VALID_SIGNUP).model_dump(mode="json"),
                {
                    "username": "asha_r",
                    "email": "asha@example.com",
                    "password": "chai4ever-and-more",
                    "birth_date": "2000-05-17",
                    "signup_date": "2026-11-17",
                    "accept_terms": True,
                },
            ),
            (
                "username with a space",
                lambda: signup_error_locations(username="asha rao"),
                ["username"],
            ),
            ("username too short", lambda: signup_error_locations(username="as"), ["username"]),
            ("bad email", lambda: signup_error_locations(email="asha-at-example"), ["email"]),
            (
                "password without a digit",
                lambda: signup_error_locations(
                    password="only-letters-here", password_confirm="only-letters-here"
                ),
                ["password"],
            ),
            (
                "password too short",
                lambda: signup_error_locations(password="abc123", password_confirm="abc123"),
                ["password"],
            ),
            (
                "passwords differ",
                lambda: (
                    "passwords do not match"
                    in signup_messages(password_confirm="chai4ever-and-less")
                ),
                True,
            ),
            (
                "13th birthday is the cutoff",
                lambda: UserRegistration.model_validate(
                    {**VALID_SIGNUP, "birth_date": "2013-11-17"}
                ).model_dump(mode="json")["birth_date"],
                "2013-11-17",
            ),
            (
                "one day too young",
                lambda: "at least 13" in signup_messages(birth_date="2013-11-18"),
                True,
            ),
            (
                "terms must be accepted",
                lambda: signup_error_locations(accept_terms=False),
                ["accept_terms"],
            ),
            ("unknown key rejected", lambda: signup_error_locations(is_admin=True), ["is_admin"]),
        ]
    )


PATCH_SEED = {1: {"id": 1, "title": "Buy tea", "body": "Assam", "pinned": False, "version": 1}}


def check_exercise_6_2_4() -> None:
    """Exercise 4 checks."""
    results: dict[str, Any] = {}
    with TestClient(create_patch_app(PATCH_SEED)) as client:
        results["pin"] = client.patch("/notes/1", json={"pinned": True}).json()
        results["retitle"] = client.patch("/notes/1", json={"title": "  Buy green tea "}).json()
        results["empty"] = client.patch("/notes/1", json={}).json()["version"]
        results["same value"] = client.patch("/notes/1", json={"pinned": True}).json()["version"]
        bad_bodies = [{"title": None}, {"pinned": None}, {"title": ""}, {"color": "red"}]
        results["errors"] = [client.patch("/notes/1", json=body).status_code for body in bad_bodies]
        results["missing"] = (
            client.patch("/notes/99", json={"pinned": True}).status_code,
            client.get("/notes/99").json(),
        )
        results["get"] = client.get("/notes/1").json()
    retitled = results["retitle"]
    run_checks(
        [
            (
                "only pinned changes, version 2",
                lambda: results["pin"],
                {"id": 1, "title": "Buy tea", "body": "Assam", "pinned": True, "version": 2},
            ),
            (
                "title stripped, version 3",
                lambda: (retitled["title"], retitled["body"], retitled["version"]),
                ("Buy green tea", "Assam", 3),
            ),
            ("{} changes nothing", lambda: results["empty"], 3),
            ("same value changes nothing", lambda: results["same value"], 3),
            (
                "null, empty title, unknown key -> 422",
                lambda: results["errors"],
                [422, 422, 422, 422],
            ),
            (
                "unknown id -> 404",
                lambda: results["missing"],
                (404, {"detail": "note 99 not found"}),
            ),
            ("GET sees the changes", lambda: results["get"]["title"], "Buy green tea"),
            (
                "seed was not modified",
                lambda: (results["get"]["version"], PATCH_SEED[1]["version"]),
                (3, 1),
            ),
        ]
    )


BENCH_DELAY = 0.05


def build_bench_app() -> FastAPI:
    """The given app: three ways to wait BENCH_DELAY seconds."""
    bench_app = FastAPI()

    @bench_app.get("/async-blocking")
    async def bench_async_blocking() -> dict[str, bool]:
        """Blocks the event loop."""
        time.sleep(BENCH_DELAY)
        return {"ok": True}

    @bench_app.get("/sync-blocking")
    def bench_sync_blocking() -> dict[str, bool]:
        """Blocks a thread-pool thread."""
        time.sleep(BENCH_DELAY)
        return {"ok": True}

    @bench_app.get("/async-sleep")
    async def bench_async_sleep() -> dict[str, bool]:
        """Waits without blocking."""
        await asyncio.sleep(BENCH_DELAY)
        return {"ok": True}

    return bench_app


async def _check_exercise_6_2_5() -> None:
    """Exercise 5 checks."""
    bench_paths = ["/async-blocking", "/sync-blocking", "/async-sleep"]
    bench_timings = await benchmark_endpoints(build_bench_app(), bench_paths, request_count=8)
    run_checks(
        [
            ("one timing per path, in order", lambda: list(bench_timings), bench_paths),
            (
                "timings are positive floats",
                lambda: all(
                    isinstance(seconds, float) and seconds > 0 for seconds in bench_timings.values()
                ),
                True,
            ),
            (
                "async-blocking serializes (>= 0.3 s)",
                lambda: bench_timings["/async-blocking"] >= 0.3,
                True,
            ),
            (
                "the others overlap (< 0.2 s)",
                lambda: (
                    bench_timings["/sync-blocking"] < 0.2 and bench_timings["/async-sleep"] < 0.2
                ),
                True,
            ),
            (
                "diagnose the measurements",
                lambda: diagnose(bench_timings, BENCH_DELAY, 8),
                {
                    "/async-blocking": "serialized",
                    "/sync-blocking": "concurrent",
                    "/async-sleep": "concurrent",
                },
            ),
            (
                "diagnose: either side of 0.3 s",
                lambda: diagnose({"/a": 0.31, "/b": 0.29}, 0.05, 8),
                {"/a": "serialized", "/b": "concurrent"},
            ),
        ]
    )
    print({path: f"{seconds:.3f} s" for path, seconds in bench_timings.items()})


def check_lab_6_2() -> None:
    """Run every Lab 6.2 check (each check prints PASS/FAIL)."""
    for title, check in (
        ("exercise 1", check_exercise_6_2_1),
        ("exercise 2", check_exercise_6_2_2),
        ("exercise 3", check_exercise_6_2_3),
        ("exercise 4", check_exercise_6_2_4),
        ("exercise 5", lambda: asyncio.run(_check_exercise_6_2_5())),
    ):
        print(f"--- {title}")
        check()


if __name__ == "__main__":
    selected = set(sys.argv[1:])
    labs = [("Lab 6.1", check_lab_6_1), ("Lab 6.2", check_lab_6_2)]
    for lab_title, check_lab in labs:
        if selected and lab_title not in selected:
            continue
        print(f"===== {lab_title} =====")
        check_lab()
