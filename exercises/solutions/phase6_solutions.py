"""Reference solutions for Phase 6 labs.

Run from the repository root:

    uv run python exercises/solutions/phase6_solutions.py            # every lab
    uv run python exercises/solutions/phase6_solutions.py "Lab 6.3"  # one lab

Each check_lab_6_N() repeats the notebook's check cells, so the notebook and this file test the
same things. Each solution sits between ``# >>> Lab 6.N exercise K`` and ``# <<<`` markers, so a
harness can paste it into the notebook's stub cell. Every server in these checks runs on
127.0.0.1 (a socket server thread, or an ASGI app called in-process); nothing touches the network.
"""

import asyncio
import base64
import binascii
import contextlib
import contextvars
import dataclasses
import http.client
import inspect
import json
import os
import random
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import uuid
import wsgiref.util
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from http import HTTPStatus
from pathlib import Path
from typing import Annotated, Any, Literal
from wsgiref.validate import validator

import fastapi
import httpx
import sqlalchemy as sa
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Response, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from fastapi.testclient import TestClient
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import (
    Column,
    ForeignKey,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    event,
    func,
    insert,
    select,
    text,
    tuple_,
    update,
)
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects import sqlite
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    raiseload,
    relationship,
    selectinload,
    sessionmaker,
)
from sqlalchemy.orm.exc import StaleDataError
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope  # Send: the Lab 6.1 alias below

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


# ----- Lab 6.3: helpers and the given code from the lab setup cells -----


def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"


@contextlib.contextmanager
def temporary_env(**variables: str) -> Iterator[None]:
    """Set environment variables inside a with block and restore the old values afterwards."""
    saved = {name: os.environ.get(name) for name in variables}
    os.environ.update(variables)
    try:
        yield
    finally:
        for name, old_value in saved.items():
            if old_value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old_value


class LabNoteIn(BaseModel):
    """Body of POST /api/v1/notes in the lab app."""

    title: str = Field(min_length=1, max_length=100)


class LabNoteStore:
    """In-memory notes: ids from 1; newest() lists the latest first."""

    def __init__(self) -> None:
        """Start empty."""
        self.notes: list[dict[str, object]] = []

    def add(self, title: str) -> dict[str, object]:
        """Store a note and return it."""
        note = {"id": len(self.notes) + 1, "title": title}
        self.notes.append(note)
        return note

    def newest(self, limit: int) -> list[dict[str, object]]:
        """At most limit notes, newest first."""
        return list(reversed(self.notes))[:limit]


lab_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "lab_request_id", default=None
)


class LoanError(Exception):
    """Base of the library's domain errors."""

    status_code = 400
    problem_type = "loan-error"
    title = "Loan rule violated"


class BookNotFoundError(LoanError, LookupError):
    """No book with this id."""

    status_code, problem_type, title = 404, "book-not-found", "Book not found"


class BookAlreadyLoanedError(LoanError):
    """Somebody else has the book."""

    status_code, problem_type, title = 409, "book-already-loaned", "Book already on loan"


class Member(BaseModel):
    """Body of POST /members."""

    name: str = Field(min_length=1)
    age: int = Field(ge=0)


def build_library_app() -> FastAPI:
    """Routes that raise a domain error, an HTTPException and validation errors."""
    app = FastAPI()

    @app.get("/books/{book_id}")
    async def get_book(book_id: int) -> dict[str, object]:
        """Only book 1 exists."""
        if book_id != 1:
            raise BookNotFoundError(f"book {book_id} not found")
        return {"id": 1, "title": "Dune"}

    @app.post("/loans/{book_id}")
    async def loan_book(book_id: int) -> None:
        """Every book is already on loan."""
        raise BookAlreadyLoanedError(f"book {book_id} is already on loan")

    @app.post("/members")
    async def add_member(member: Member) -> Member:
        """Validated body."""
        return member

    @app.get("/teapot")
    async def teapot() -> None:
        """An HTTPException with a header."""
        raise HTTPException(418, "I refuse to brew coffee", headers={"X-Teapot": "yes"})

    return app


# ----- Lab 6.3: reference solutions -----


# >>> Lab 6.3 exercise 1
class LabSettings(BaseSettings):
    """Settings for the lab Notes API."""

    model_config = SettingsConfigDict(env_prefix="LAB_NOTES_", extra="ignore")

    app_name: str = "Lab Notes"
    api_key: SecretStr
    page_size: int = Field(default=20, ge=1, le=100)
    cors_origins: list[str] = []


@lru_cache
def get_lab_settings() -> LabSettings:
    """The settings, read once per process."""
    return LabSettings()  # api_key comes from the environment


def get_lab_store(request: fastapi.Request) -> LabNoteStore:
    """The store the lifespan created."""
    return request.app.state.store


@contextlib.asynccontextmanager
async def lab_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """A fresh store for each app."""
    app.state.store = LabNoteStore()
    yield


def create_lab_app(settings: LabSettings) -> FastAPI:
    """A layered app with its own store."""
    app = FastAPI(title=settings.app_name, lifespan=lab_lifespan)
    app.state.settings = settings
    router = APIRouter(prefix="/api/v1/notes", tags=["notes"])
    store_dependency = Depends(get_lab_store)

    @router.post("", status_code=status.HTTP_201_CREATED)
    async def create_note(
        note: LabNoteIn, store: LabNoteStore = store_dependency
    ) -> dict[str, object]:
        """Store a note."""
        return store.add(note.title)

    @router.get("")
    async def list_notes(store: LabNoteStore = store_dependency) -> list[dict[str, object]]:
        """The newest notes, at most page_size of them."""
        return store.newest(settings.page_size)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok"}

    app.include_router(router)
    return app


# <<< Lab 6.3 exercise 1


# >>> Lab 6.3 exercise 2
def build_admin_app(api_key: str) -> FastAPI:
    """Public /health plus an /admin router guarded by an X-API-Key dependency."""
    header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)

    def require_admin_key(supplied: Annotated[str | None, Depends(header_scheme)]) -> None:
        """401 without a key, 403 with a wrong one."""
        if supplied is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing API key")
        if not secrets.compare_digest(supplied.encode(), api_key.encode()):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid API key")

    app = FastAPI()
    admin_router = APIRouter(
        prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_key)]
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Open to everybody."""
        return {"status": "ok"}

    @admin_router.get("/stats")
    async def stats() -> dict[str, int]:
        """Guarded by the router dependency."""
        return {"notes": 0}

    @admin_router.delete("/cache")
    async def clear_cache() -> dict[str, bool]:
        """Guarded by the router dependency."""
        return {"cleared": True}

    app.include_router(admin_router)
    return app


# <<< Lab 6.3 exercise 2


# >>> Lab 6.3 exercise 3
LAB_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9-]{1,64}")


class LabRequestIdMiddleware:
    """Pure ASGI request-id middleware."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the next app."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Choose the id, expose it in the context variable and the response header."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = Headers(scope=scope).get("x-request-id", "")
        current = incoming if LAB_VALID_REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
        token = lab_request_id.set(current)

        async def send_with_id(message: Message) -> None:
            """Add the header to the response start message."""
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Request-ID"] = current
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            lab_request_id.reset(token)


class LabTimingMiddleware:
    """Pure ASGI Server-Timing middleware."""

    def __init__(self, app: ASGIApp, clock: Callable[[], float] = time.perf_counter) -> None:
        """Wrap the next app; clock is injectable."""
        self.app = app
        self.clock = clock

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Measure from the request to the response start."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = self.clock()

        async def send_with_timing(message: Message) -> None:
            """Add Server-Timing to the response start message."""
            if message["type"] == "http.response.start":
                elapsed_ms = (self.clock() - started) * 1000
                MutableHeaders(scope=message)["Server-Timing"] = f"app;dur={elapsed_ms:.1f}"
            await send(message)

        await self.app(scope, receive, send_with_timing)


# <<< Lab 6.3 exercise 3


# >>> Lab 6.3 exercise 4
def install_problem_handlers(app: FastAPI) -> None:
    """Register Problem Details handlers on app."""

    def problem(
        request: fastapi.Request,
        status_code: int,
        title: str,
        detail: str,
        problem_type: str = "about:blank",
        headers: dict[str, str] | None = None,
        **extra: object,
    ) -> JSONResponse:
        """An application/problem+json response."""
        body = {
            "type": problem_type,
            "title": title,
            "status": status_code,
            "detail": detail,
            "instance": request.url.path,
            **extra,
        }
        return JSONResponse(
            body, status_code=status_code, headers=headers, media_type="application/problem+json"
        )

    async def loan_error(request: fastapi.Request, error: LoanError) -> JSONResponse:
        """Domain errors carry their own status, type and title."""
        problem_type = f"/problems/{error.problem_type}"
        return problem(request, error.status_code, error.title, str(error), problem_type)

    async def http_error(request: fastapi.Request, error: StarletteHTTPException) -> JSONResponse:
        """HTTPException: the standard phrase as the title; keep the headers."""
        title = HTTPStatus(error.status_code).phrase
        return problem(request, error.status_code, title, str(error.detail), headers=error.headers)

    async def validation_error(
        request: fastapi.Request, error: RequestValidationError
    ) -> JSONResponse:
        """422 with the list of problems, without the input."""
        problems = [
            {"loc": list(item["loc"]), "msg": item["msg"], "type": item["type"]}
            for item in error.errors()
        ]
        detail = f"{len(problems)} validation error(s)"
        return problem(
            request, 422, "Invalid request", detail, "/problems/validation-error", errors=problems
        )

    app.add_exception_handler(LoanError, loan_error)
    app.add_exception_handler(StarletteHTTPException, http_error)
    app.add_exception_handler(RequestValidationError, validation_error)


# <<< Lab 6.3 exercise 4


# >>> Lab 6.3 exercise 5
def build_weather_app(transport: httpx.AsyncBaseTransport) -> FastAPI:
    """An app whose lifespan owns one upstream HTTP client."""

    @contextlib.asynccontextmanager
    async def weather_lifespan(app: FastAPI) -> AsyncIterator[None]:
        """One client for the app's whole life, closed on shutdown."""
        async with httpx.AsyncClient(
            base_url="https://weather.example", transport=transport, timeout=2.0
        ) as client:
            app.state.weather_client = client
            yield

    app = FastAPI(lifespan=weather_lifespan)

    @app.get("/forecast/{city}")
    async def forecast(city: str, request: fastapi.Request) -> dict[str, object]:
        """Translate the upstream forecast and its failures."""
        client: httpx.AsyncClient = request.app.state.weather_client
        try:
            upstream = await client.get("/v1/forecast", params={"city": city})
        except httpx.TimeoutException as error:
            raise HTTPException(
                status.HTTP_504_GATEWAY_TIMEOUT, "weather service timed out"
            ) from error
        if upstream.status_code == 404:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown city {city}")
        if upstream.status_code >= 500:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "weather service failed")
        data = upstream.json()
        return {"city": data["city"], "temperature": data["temp_c"], "summary": data["summary"]}

    return app


# <<< Lab 6.3 exercise 5


# >>> Lab 6.3 exercise 6
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"


def build_avatar_app(max_bytes: int) -> FastAPI:
    """POST /avatars with size and content checks."""
    app = FastAPI()

    @app.post("/avatars", status_code=status.HTTP_201_CREATED)
    async def upload_avatar(file: UploadFile) -> dict[str, object]:
        """Accept a small PNG or JPEG, judged by its first bytes."""
        content = await file.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE, f"avatar larger than {max_bytes} bytes"
            )
        if content.startswith(PNG_SIGNATURE):
            kind = "png"
        elif content.startswith(JPEG_SIGNATURE):
            kind = "jpeg"
        else:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "only PNG or JPEG images")
        return {"filename": file.filename, "kind": kind, "bytes": len(content)}

    return app


def encode_event_cursor(at: str, event_id: int) -> str:
    """Opaque cursor for the key (at, event_id)."""
    raw = json.dumps([at, event_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_event_cursor(cursor: str) -> tuple[str, int]:
    """The key inside a cursor, or ValueError."""
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        at, event_id = json.loads(raw)
    except (binascii.Error, ValueError, TypeError) as error:
        raise ValueError(f"invalid cursor {cursor!r}") from error
    if not isinstance(at, str) or not isinstance(event_id, int):
        raise ValueError(f"invalid cursor {cursor!r}")
    return at, event_id


def build_events_app(events: list[dict[str, object]]) -> FastAPI:
    """GET /events with keyset pagination, newest first."""
    app = FastAPI()

    @app.get("/events")
    async def list_events(
        limit: Annotated[int, Query(ge=1, le=50)] = 10, cursor: str | None = None
    ) -> dict[str, object]:
        """Events strictly older than the cursor's (at, id) key."""
        try:
            after = decode_event_cursor(cursor) if cursor else None
        except ValueError as error:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid cursor") from error
        ordered = sorted(
            events, key=lambda event: (str(event["at"]), int(event["id"])), reverse=True
        )
        older = [
            event
            for event in ordered
            if after is None or (str(event["at"]), int(event["id"])) < after
        ]
        page = older[:limit]
        more = len(older) > limit
        next_cursor = (
            encode_event_cursor(str(page[-1]["at"]), int(page[-1]["id"])) if more else None
        )
        return {"items": page, "next_cursor": next_cursor}

    return app


# <<< Lab 6.3 exercise 6


# ----- Lab 6.3: the notebook's check cells -----


def lab_settings_from_env(**variables: str) -> tuple[object, ...]:
    """(app_name, page_size, cors_origins) of LabSettings built from these variables."""
    with temporary_env(**variables):
        settings = LabSettings(_env_file=None)
    return settings.app_name, settings.page_size, settings.cors_origins


def lab_app_scenario(page_size: int) -> dict[str, object]:
    """Two apps from one factory; three notes created in the first."""
    settings = LabSettings(_env_file=None, api_key="lab-secret-123", page_size=page_size)
    first_app, second_app = create_lab_app(settings), create_lab_app(settings)
    with TestClient(first_app) as first, TestClient(second_app) as second:
        created = [
            first.post("/api/v1/notes", json={"title": f"Note {number}"}) for number in range(3)
        ]
        return {
            "statuses": [response.status_code for response in created],
            "first": [note["title"] for note in first.get("/api/v1/notes").json()],
            "second": second.get("/api/v1/notes").json(),
            "unprefixed": first.get("/notes").status_code,
            "health": first.get("/health").json(),
            "empty title": first.post("/api/v1/notes", json={"title": ""}).status_code,
            "tags": first_app.openapi()["paths"]["/api/v1/notes"]["post"]["tags"],
            "title": first_app.title,
        }


def lab_override_titles() -> list[object]:
    """Titles listed when get_lab_store is overridden with a prepared store."""
    prepared = LabNoteStore()
    prepared.add("from the override")
    app = create_lab_app(LabSettings(_env_file=None, api_key="k"))
    app.dependency_overrides[get_lab_store] = lambda: prepared
    with TestClient(app) as client:
        return [note["title"] for note in client.get("/api/v1/notes").json()]


def cached_settings_are_shared() -> bool:
    """get_lab_settings returns the same object twice."""
    with temporary_env(LAB_NOTES_API_KEY="cached-key"):
        get_lab_settings.cache_clear()
        shared = get_lab_settings() is get_lab_settings()
    get_lab_settings.cache_clear()
    return shared


def check_exercise_6_3_1() -> None:
    """Exercise 1 checks."""
    env = {
        "LAB_NOTES_API_KEY": "k",
        "LAB_NOTES_PAGE_SIZE": "5",
        "LAB_NOTES_CORS_ORIGINS": '["http://localhost:5173"]',
    }
    run_checks(
        [
            (
                "env variables are parsed",
                lambda: lab_settings_from_env(**env),
                ("Lab Notes", 5, ["http://localhost:5173"]),
            ),
            (
                "api_key is required",
                lambda: raised_error_name(lambda: LabSettings(_env_file=None)),
                "ValidationError",
            ),
            (
                "page_size 0 is rejected",
                lambda: raised_error_name(
                    lambda: LabSettings(_env_file=None, api_key="k", page_size=0)
                ),
                "ValidationError",
            ),
            (
                "the key is hidden in repr",
                lambda: (
                    "lab-secret-123" in repr(LabSettings(_env_file=None, api_key="lab-secret-123"))
                ),
                False,
            ),
            ("get_lab_settings is cached", cached_settings_are_shared, True),
            ("POST returns 201", lambda: lab_app_scenario(20)["statuses"], [201, 201, 201]),
            (
                "GET lists newest first",
                lambda: lab_app_scenario(20)["first"],
                ["Note 2", "Note 1", "Note 0"],
            ),
            (
                "page_size limits the list",
                lambda: lab_app_scenario(2)["first"],
                ["Note 2", "Note 1"],
            ),
            ("each app has its own store", lambda: lab_app_scenario(20)["second"], []),
            ("routes live under /api/v1/notes", lambda: lab_app_scenario(20)["unprefixed"], 404),
            ("health route", lambda: lab_app_scenario(20)["health"], {"status": "ok"}),
            ("the body is validated", lambda: lab_app_scenario(20)["empty title"], 422),
            (
                "router tag and app title",
                lambda: (lab_app_scenario(20)["tags"], lab_app_scenario(20)["title"]),
                (["notes"], "Lab Notes"),
            ),
            ("get_lab_store can be overridden", lab_override_titles, ["from the override"]),
        ]
    )


def admin_statuses(headers: dict[str, str]) -> list[object]:
    """Status and body of each route when called with these headers."""
    with TestClient(build_admin_app("s3cret-admin-key")) as client:
        calls = [
            client.get("/health", headers=headers),
            client.get("/admin/stats", headers=headers),
            client.delete("/admin/cache", headers=headers),
        ]
        return [(response.status_code, response.json()) for response in calls]


def admin_security() -> tuple[object, ...]:
    """The security schemes and which operations require one."""
    schema = build_admin_app("k").openapi()
    schemes = schema["components"]["securitySchemes"]
    return (
        [(scheme["type"], scheme["in"], scheme["name"]) for scheme in schemes.values()],
        "security" in schema["paths"]["/admin/stats"]["get"],
        "security" in schema["paths"]["/health"]["get"],
    )


def check_exercise_6_3_2() -> None:
    """Exercise 2 checks."""
    missing = (401, {"detail": "missing API key"})
    invalid = (403, {"detail": "invalid API key"})
    healthy = (200, {"status": "ok"})
    run_checks(
        [
            ("no key", lambda: admin_statuses({}), [healthy, missing, missing]),
            (
                "wrong key",
                lambda: admin_statuses({"X-API-Key": "guess"}),
                [healthy, invalid, invalid],
            ),
            (
                "right key",
                lambda: admin_statuses({"X-API-Key": "s3cret-admin-key"}),
                [healthy, (200, {"notes": 0}), (200, {"cleared": True})],
            ),
            (
                "OpenAPI: an apiKey header scheme on admin routes only",
                admin_security,
                ([("apiKey", "header", "X-API-Key")], True, False),
            ),
        ]
    )


def lab_middleware_app(clock: Callable[[], float]) -> FastAPI:
    """An app using both middlewares; the endpoint reports the id it sees."""
    app = FastAPI()
    app.add_middleware(LabTimingMiddleware, clock=clock)
    app.add_middleware(LabRequestIdMiddleware)

    @app.get("/whoami")
    async def whoami() -> dict[str, object]:
        """Report the context variable."""
        return {"seen": lab_request_id.get()}

    return app


def lab_middleware_call(
    headers: dict[str, str], clock: Callable[[], float] = time.perf_counter
) -> dict[str, object]:
    """Response header, the id the endpoint saw, and Server-Timing."""
    with TestClient(lab_middleware_app(clock)) as client:
        response = client.get("/whoami", headers=headers)
    return {
        "header": response.headers.get("x-request-id"),
        "seen": response.json().get("seen"),
        "timing": response.headers.get("server-timing"),
    }


async def lab_reset_probe() -> object:
    """The variable after a call in this task (ASGITransport runs the app here)."""
    try:
        transport = httpx.ASGITransport(app=lab_middleware_app(time.perf_counter))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/whoami", headers={"X-Request-ID": "x-1"})
    except Exception as error:  # a check must never stop the run
        return f"raised {type(error).__name__}"
    return lab_request_id.get()


def check_exercise_6_3_3() -> None:
    """Exercise 3 checks."""
    reset_probe = asyncio.run(lab_reset_probe())
    run_checks(
        [
            (
                "a new id is 32 hex digits",
                lambda: bool(
                    re.fullmatch(r"[0-9a-f]{32}", str(lab_middleware_call({})["header"] or ""))
                ),
                True,
            ),
            (
                "the endpoint sees the same id",
                lambda: (lambda result: result["seen"] == result["header"])(
                    lab_middleware_call({})
                ),
                True,
            ),
            (
                "a valid incoming id is kept",
                lambda: lab_middleware_call({"X-Request-ID": "order-42"})["header"],
                "order-42",
            ),
            (
                "an invalid incoming id is replaced",
                lambda: (
                    lab_middleware_call({"X-Request-ID": "bad id;drop"})["header"] != "bad id;drop"
                ),
                True,
            ),
            (
                "Server-Timing from the clock",
                lambda: lab_middleware_call({}, ManualClock(10.0, 10.0123))["timing"],
                "app;dur=12.3",
            ),
            ("the variable is reset afterwards", lambda: reset_probe, None),
            (
                "pure ASGI classes that work",
                lambda: (
                    not issubclass(LabRequestIdMiddleware, BaseHTTPMiddleware)
                    and not issubclass(LabTimingMiddleware, BaseHTTPMiddleware)
                    and lab_middleware_call({})["timing"] is not None
                ),
                True,
            ),
        ]
    )


def library_problem(method: str, path: str, **request_options: Any) -> tuple[object, ...]:
    """Status, content type and body for one request to the library app."""
    app = build_library_app()
    install_problem_handlers(app)
    with TestClient(app) as client:
        response = client.request(method, path, **request_options)
    return response.status_code, response.headers["content-type"], response.json()


def teapot_header() -> object:
    """The X-Teapot header of the 418 response (handlers must keep it)."""
    app = build_library_app()
    install_problem_handlers(app)
    with TestClient(app) as client:
        return client.get("/teapot").headers.get("x-teapot")


def check_exercise_6_3_4() -> None:
    """Exercise 4 checks."""
    problem_json = "application/problem+json"
    validation_body = {
        "type": "/problems/validation-error",
        "title": "Invalid request",
        "status": 422,
        "detail": "2 validation error(s)",
        "instance": "/members",
        "errors": [
            {
                "loc": ["body", "name"],
                "msg": "String should have at least 1 character",
                "type": "string_too_short",
            },
            {
                "loc": ["body", "age"],
                "msg": "Input should be greater than or equal to 0",
                "type": "greater_than_equal",
            },
        ],
    }
    run_checks(
        [
            (
                "domain 404",
                lambda: library_problem("GET", "/books/7"),
                (
                    404,
                    problem_json,
                    {
                        "type": "/problems/book-not-found",
                        "title": "Book not found",
                        "status": 404,
                        "detail": "book 7 not found",
                        "instance": "/books/7",
                    },
                ),
            ),
            (
                "domain 409",
                lambda: library_problem("POST", "/loans/1")[2]["type"],
                "/problems/book-already-loaned",
            ),
            ("HTTPException keeps its headers", teapot_header, "yes"),
            (
                "HTTPException body",
                lambda: library_problem("GET", "/teapot"),
                (
                    418,
                    problem_json,
                    {
                        "type": "about:blank",
                        "title": "I'm a Teapot",
                        "status": 418,
                        "detail": "I refuse to brew coffee",
                        "instance": "/teapot",
                    },
                ),
            ),
            ("unknown route", lambda: library_problem("GET", "/nowhere")[:2], (404, problem_json)),
            (
                "wrong method",
                lambda: library_problem("DELETE", "/books/1")[2]["title"],
                "Method Not Allowed",
            ),
            (
                "validation problem",
                lambda: library_problem("POST", "/members", json={"name": "", "age": -1})[2],
                validation_body,
            ),
            (
                "a valid request still works",
                lambda: library_problem("POST", "/members", json={"name": "Ravi", "age": 30})[2],
                {"name": "Ravi", "age": 30},
            ),
        ]
    )


def fake_weather_upstream() -> tuple[httpx.MockTransport, list[str]]:
    """A mock upstream and the list of URLs it received."""
    received: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        """Answer by city name."""
        received.append(str(request.url))
        city = request.url.params.get("city", "")
        if city == "slow":
            raise httpx.ReadTimeout("upstream too slow", request=request)
        if city == "crash":
            return httpx.Response(503)
        if city != "pune":
            return httpx.Response(404)
        return httpx.Response(200, json={"city": "Pune", "temp_c": 31.5, "summary": "sunny"})

    return httpx.MockTransport(handle), received


def weather_scenario() -> dict[str, object]:
    """Call every route variant; record what happened to the client."""
    transport, received = fake_weather_upstream()
    app = build_weather_app(transport)
    with TestClient(app) as client:
        first_client = app.state.weather_client
        results = {}
        for city in ("pune", "atlantis", "crash", "slow"):
            response = client.get(f"/forecast/{city}")
            results[city] = (response.status_code, response.json())
        same_client = app.state.weather_client is first_client
    return {
        "results": results,
        "received": received[0],
        "same client": same_client,
        "closed after shutdown": first_client.is_closed,
        "base url": str(first_client.base_url),
    }


def check_exercise_6_3_5() -> None:
    """Exercise 5 checks."""
    run_checks(
        [
            (
                "forecast is mapped",
                lambda: weather_scenario()["results"]["pune"],
                (200, {"city": "Pune", "temperature": 31.5, "summary": "sunny"}),
            ),
            (
                "upstream URL",
                lambda: weather_scenario()["received"],
                "https://weather.example/v1/forecast?city=pune",
            ),
            (
                "upstream 404",
                lambda: weather_scenario()["results"]["atlantis"],
                (404, {"detail": "unknown city atlantis"}),
            ),
            (
                "upstream 5xx → 502",
                lambda: weather_scenario()["results"]["crash"],
                (502, {"detail": "weather service failed"}),
            ),
            (
                "timeout → 504",
                lambda: weather_scenario()["results"]["slow"],
                (504, {"detail": "weather service timed out"}),
            ),
            ("one client for all requests", lambda: weather_scenario()["same client"], True),
            ("closed on shutdown", lambda: weather_scenario()["closed after shutdown"], True),
            ("base URL", lambda: weather_scenario()["base url"], "https://weather.example"),
        ]
    )


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 20


def avatar_upload(name: str, content: bytes, claimed_type: str) -> tuple[int, Any]:
    """Status and body for one upload to an app with a 100-byte limit."""
    with TestClient(build_avatar_app(100)) as client:
        response = client.post("/avatars", files={"file": (name, content, claimed_type)})
    return response.status_code, response.json()


def lab_events() -> list[dict[str, object]]:
    """Seven events; two share a timestamp (the id breaks the tie)."""
    times = ["09:00", "09:05", "09:05", "09:10", "09:20", "09:30", "09:40"]
    return [
        {"id": number, "at": f"2026-11-17T{clock}:00Z", "name": f"event {number}"}
        for number, clock in enumerate(times, start=1)
    ]


def walk_events(limit: int, add_between: bool = False) -> list[list[object]]:
    """Follow next_cursor to the end; optionally add a newer event after page one."""
    events = lab_events()
    pages: list[list[object]] = []
    params: dict[str, object] = {"limit": limit}
    with TestClient(build_events_app(events)) as client:
        while True:
            page = client.get("/events", params=params).json()
            pages.append([event["id"] for event in page["items"]])
            if add_between and len(pages) == 1:
                events.append({"id": 99, "at": "2026-11-17T10:00:00Z", "name": "late"})
            if page["next_cursor"] is None:
                return pages
            params = {"limit": limit, "cursor": page["next_cursor"]}


def bad_cursor_response() -> tuple[int, object]:
    """Status and body for a cursor the app never issued."""
    with TestClient(build_events_app(lab_events())) as client:
        response = client.get("/events", params={"cursor": "definitely-not-a-cursor"})
    return response.status_code, response.json()


def check_exercise_6_3_6() -> None:
    """Exercise 6 checks."""
    sample_cursor = encode_event_cursor("2026-11-17T09:05:00Z", 3)
    run_checks(
        [
            (
                "PNG accepted",
                lambda: avatar_upload("me.png", PNG_BYTES, "image/png"),
                (201, {"filename": "me.png", "kind": "png", "bytes": 28}),
            ),
            (
                "JPEG accepted whatever the header says",
                lambda: avatar_upload("me.bin", JPEG_BYTES, "application/octet-stream")[1]["kind"],
                "jpeg",
            ),
            (
                "GIF refused despite image/png",
                lambda: avatar_upload("me.png", b"GIF89a" + b"\x00" * 20, "image/png"),
                (415, {"detail": "only PNG or JPEG images"}),
            ),
            (
                "too large",
                lambda: avatar_upload("big.png", PNG_BYTES * 10, "image/png"),
                (413, {"detail": "avatar larger than 100 bytes"}),
            ),
            (
                "cursor round trip",
                lambda: decode_event_cursor(sample_cursor),
                ("2026-11-17T09:05:00Z", 3),
            ),
            ("cursor is opaque", lambda: "2026" in sample_cursor or "=" in sample_cursor, False),
            (
                "garbage cursor → ValueError",
                lambda: raised_error_name(lambda: decode_event_cursor("%%%")),
                "ValueError",
            ),
            ("pages of 3, newest first", lambda: walk_events(3), [[7, 6, 5], [4, 3, 2], [1]]),
            (
                "limit = number of events gives one page",
                lambda: walk_events(7),
                [[7, 6, 5, 4, 3, 2, 1]],
            ),
            (
                "a new event does not shift later pages",
                lambda: walk_events(3, add_between=True),
                [[7, 6, 5], [4, 3, 2], [1]],
            ),
            ("bad cursor → 400", bad_cursor_response, (400, {"detail": "invalid cursor"})),
        ]
    )


def check_lab_6_3() -> None:
    """Run every Lab 6.3 check (each check prints PASS/FAIL)."""
    for title, check in (
        ("exercise 1", check_exercise_6_3_1),
        ("exercise 2", check_exercise_6_3_2),
        ("exercise 3", check_exercise_6_3_3),
        ("exercise 4", check_exercise_6_3_4),
        ("exercise 5", check_exercise_6_3_5),
        ("exercise 6", check_exercise_6_3_6),
    ):
        print(f"--- {title}")
        check()


# ----- Lab 6.4: the given code from the lab setup cells -----

PHASE6_DIR = Path(
    tempfile.mkdtemp(prefix="phase6_lab64_")
)  # the notebook uses notebooks/_scratch/phase6
CHILD_ENV = {**os.environ, "PYTHON_COLORS": "0", "NO_COLOR": "1"}
PG_URL: str | None = (
    None  # the notebook passes its PostgreSQL container here; this script uses SQLite
)


class QBase(DeclarativeBase):
    """Base for the given notes schema of exercises 2-3."""


q_note_tags = Table(
    "q_note_tags",
    QBase.metadata,
    Column("note_id", ForeignKey("q_notes.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("q_tags.id", ondelete="CASCADE"), primary_key=True),
)


class QTag(QBase):
    """A tag."""

    __tablename__ = "q_tags"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(30), unique=True)
    notes: Mapped[list[QNote]] = relationship(secondary=q_note_tags, back_populates="tags")


class QNote(QBase):
    """A note (tags load lazily, the default)."""

    __tablename__ = "q_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    pinned: Mapped[bool] = mapped_column(default=False)
    created_on: Mapped[date]
    tags: Mapped[list[QTag]] = relationship(
        secondary=q_note_tags, back_populates="notes", order_by=QTag.name
    )


Q_SEED = [
    ("Buy tea", True, ["shop", "food"]),
    ("Call Ravi", False, ["home"]),
    ("Draft: plan", False, ["work"]),
    ("Pay rent", True, ["home", "bills"]),
    ("Fix bug", False, ["work"]),
    ("Read book", False, []),
    ("Draft: email", False, []),
]


def fresh_q_engine() -> sa.Engine:
    """A new SQLite file with the seven seeded notes (note n was created on 2026-11-0n)."""
    path = PHASE6_DIR / "lab_queries.db"
    path.unlink(missing_ok=True)
    engine = create_engine(f"sqlite:///{path}")
    event.listen(
        engine,
        "connect",
        lambda dbapi_connection, _: dbapi_connection.execute("PRAGMA foreign_keys=ON"),
    )
    QBase.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        tags = {name: QTag(name=name) for name in ("bills", "food", "home", "shop", "work")}
        for day, (title, pinned, names) in enumerate(Q_SEED, start=1):
            session.add(
                QNote(
                    title=title,
                    pinned=pinned,
                    created_on=date(2026, 11, day),
                    tags=[tags[name] for name in names],
                )
            )
    return engine


def titles_with_tags_slow(session: Session) -> list[tuple[str, list[str]]]:
    """Every note's title and tag names: the N+1 way (one query per note for its tags)."""
    notes = session.scalars(select(QNote).order_by(QNote.id))
    return [(note.title, [tag.name for tag in note.tags]) for note in notes]


class DocBase(DeclarativeBase):
    """Base for exercise 5."""


class LabDocument(DocBase):
    """A document with optimistic locking."""

    __tablename__ = "lab_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    content: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column()
    __mapper_args__ = {"version_id_col": version}


class DocumentConflictError(Exception):
    """Somebody changed the document since it was read."""


def fresh_documents() -> sessionmaker[Session]:
    """A session factory on a new database holding document 1 ("first draft", version 1)."""
    path = PHASE6_DIR / "lab_documents.db"
    path.unlink(missing_ok=True)
    engine = create_engine(
        f"sqlite:///{path}", connect_args={"check_same_thread": False}
    )  # def routes run in worker threads
    DocBase.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(LabDocument(id=1, content="first draft"))
    return factory


class ItemBase(DeclarativeBase):
    """Base for exercise 6."""


class LabItem(ItemBase):
    """A searchable, pageable item."""

    __tablename__ = "lab_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime]


ITEM_WORDS = [
    "river",
    "Rice",
    "ridge",
    "Ring",
    "robot",
    "Ruby",
    "rust",
    "Rain",
    "atlas",
    "Basil",
    "cedar",
    "Delta",
]


def fresh_items_engine() -> sa.Engine:
    """3000 items with mixed-case titles; every three share a timestamp (the id breaks ties)."""
    path = PHASE6_DIR / "lab_items.db"
    path.unlink(missing_ok=True)
    engine = create_engine(f"sqlite:///{path}")
    ItemBase.metadata.create_all(engine)
    rng = random.Random(42)
    start = datetime(2026, 1, 1)
    rows = [
        {
            "title": f"{rng.choice(ITEM_WORDS)} {rng.choice(ITEM_WORDS).lower()} {number}",
            "created_at": start + timedelta(minutes=number // 3),
        }
        for number in range(3000)
    ]
    with engine.begin() as connection:
        connection.execute(insert(LabItem), rows)
    return engine


LAB_ALEMBIC = PHASE6_DIR / "lab_alembic"
LAB_ALEMBIC_DB = LAB_ALEMBIC / "links.db"


def write_lab_alembic_project() -> None:
    """The lab's Alembic project: a sync env.py with batch mode, no models."""
    (LAB_ALEMBIC / "migrations" / "versions").mkdir(parents=True, exist_ok=True)
    (LAB_ALEMBIC / "alembic.ini").write_text(
        f"[alembic]\nscript_location = migrations\nsqlalchemy.url = sqlite:///{LAB_ALEMBIC_DB}\n",
        encoding="utf-8",
    )
    (LAB_ALEMBIC / "migrations" / "env.py").write_text(
        "from alembic import context\nfrom sqlalchemy import create_engine\n\n"
        "engine = create_engine(context.config.get_main_option('sqlalchemy.url'))\n"
        "with engine.connect() as connection:\n"
        "    context.configure(connection=connection, target_metadata=None, render_as_batch=True)\n"
        "    with context.begin_transaction():\n"
        "        context.run_migrations()\n",
        encoding="utf-8",
    )
    (LAB_ALEMBIC / "migrations" / "script.py.mako").write_text(
        '"""${message}"""\n', encoding="utf-8"
    )


def reset_lab_alembic() -> Path:
    """Delete the database and every migration file; return the versions folder."""
    write_lab_alembic_project()
    LAB_ALEMBIC_DB.unlink(missing_ok=True)
    versions = LAB_ALEMBIC / "migrations" / "versions"
    for migration in versions.glob("*.py"):
        migration.unlink()
    shutil.rmtree(versions / "__pycache__", ignore_errors=True)
    return versions


def lab_alembic(*arguments: str) -> str:
    """Run alembic in the lab project; return the output, raise if it failed."""
    run = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=LAB_ALEMBIC,
        capture_output=True,
        text=True,
        env=CHILD_ENV,
        timeout=120,
    )
    if run.returncode != 0:
        raise RuntimeError(
            f"alembic {' '.join(arguments)} failed: {run.stderr.strip().splitlines()[-1:]}"
        )
    return run.stdout + run.stderr


# ----- Lab 6.4: reference solutions -----

# >>> Lab 6.4 exercise 1
LAB_NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class LabBase(DeclarativeBase):
    """Base with a naming convention."""

    metadata = MetaData(naming_convention=LAB_NAMING)


lab_note_tags = Table(
    "lab_note_tags",
    LabBase.metadata,
    Column("note_id", ForeignKey("lab_notes.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("lab_tags.id", ondelete="CASCADE"), primary_key=True),
)


class LabTag(LabBase):
    """A tag name, stored once."""

    __tablename__ = "lab_tags"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(30), unique=True)


class LabNote(LabBase):
    """A note with many-to-many tags."""

    __tablename__ = "lab_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    pinned: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    tags: Mapped[list[LabTag]] = relationship(secondary=lab_note_tags, order_by=LabTag.name)


def add_lab_note(session: Session, title: str, tag_names: list[str]) -> LabNote:
    """Create a note, reusing tags that already exist."""
    found = {
        tag.name: tag for tag in session.scalars(select(LabTag).where(LabTag.name.in_(tag_names)))
    }
    note = LabNote(title=title, tags=[found.get(name) or LabTag(name=name) for name in tag_names])
    session.add(note)
    session.flush()
    return note


# <<< Lab 6.4 exercise 1


# >>> Lab 6.4 exercise 2
def build_eight_queries() -> dict[str, sa.Executable]:
    """The eight statements, by key."""
    note_count = func.count(QNote.id)
    newest = (
        select(q_note_tags.c.tag_id, func.max(QNote.created_on).label("newest_on"))
        .join(QNote, QNote.id == q_note_tags.c.note_id)
        .group_by(q_note_tags.c.tag_id)
        .subquery()
    )
    return {
        "pinned_titles": select(QNote.title).where(QNote.pinned).order_by(QNote.title),
        "tagged_work": select(QNote.title)
        .join(QNote.tags)
        .where(QTag.name == "work")
        .order_by(QNote.id),
        "count_per_tag": (
            select(QTag.name, note_count)
            .join(QTag.notes)
            .group_by(QTag.id)
            .order_by(note_count.desc(), QTag.name)
        ),
        "popular_tags": (
            select(QTag.name)
            .join(QTag.notes)
            .group_by(QTag.id)
            .having(note_count >= 2)
            .order_by(QTag.name)
        ),
        "untagged": select(QNote.title).where(~QNote.tags.any()).order_by(QNote.id),
        "latest_per_tag": (
            select(QTag.name, QNote.title)
            .join(newest, newest.c.tag_id == QTag.id)
            .join(QTag.notes)
            .where(QNote.created_on == newest.c.newest_on)
            .order_by(QTag.name)
        ),
        "unpin_old": update(QNote)
        .where(QNote.pinned, QNote.created_on < date(2026, 11, 3))
        .values(pinned=False),
        "delete_drafts": delete(QNote).where(QNote.title.startswith("Draft:")),
    }


# <<< Lab 6.4 exercise 2


# >>> Lab 6.4 exercise 3
def count_statements(engine: sa.Engine, action: Callable[[Session], object]) -> tuple[int, object]:
    """Statements sent while action(session) runs, and its result."""
    statements: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *rest: Any) -> None:
        """before_cursor_execute listener."""
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        with Session(engine) as session:
            result = action(session)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return len(statements), result


def titles_with_tags_fast(session: Session) -> list[tuple[str, list[str]]]:
    """Same as titles_with_tags_slow, in two statements."""
    notes = session.scalars(select(QNote).options(selectinload(QNote.tags)).order_by(QNote.id))
    return [(note.title, [tag.name for tag in note.tags]) for note in notes]


def strict_note(session: Session, note_id: int) -> QNote:
    """One note whose relationships refuse to lazy-load."""
    return session.scalars(select(QNote).options(raiseload("*")).where(QNote.id == note_id)).one()


# <<< Lab 6.4 exercise 3


# >>> Lab 6.4 exercise 4
LAB_MIGRATION_HEADER = (
    "import sqlalchemy as sa\nfrom alembic import op\n\n"
    'revision = "{revision}"\ndown_revision = {previous}\nbranch_labels = None\ndepends_on = None\n'
)

LAB_MIGRATIONS = {
    "0001_create_links.py": (
        "0001",
        None,
        '''
def upgrade() -> None:
    """Create links."""
    op.create_table(
        "links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("title", sa.String(200), nullable=True),
    )


def downgrade() -> None:
    """Drop links."""
    op.drop_table("links")
''',
    ),
    "0002_clicks_and_unique_url.py": (
        "0002",
        "0001",
        '''
def upgrade() -> None:
    """Add clicks and a unique URL constraint."""
    with op.batch_alter_table("links") as batch:
        batch.add_column(sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"))
        batch.create_unique_constraint("uq_links_url", ["url"])


def downgrade() -> None:
    """Remove both."""
    with op.batch_alter_table("links") as batch:
        batch.drop_constraint("uq_links_url", type_="unique")
        batch.drop_column("clicks")
''',
    ),
    "0003_fill_titles.py": (
        "0003",
        "0002",
        '''
links = sa.table("links", sa.column("url", sa.String()), sa.column("title", sa.String()))


def upgrade() -> None:
    """Data migration: missing titles become the URL; then titles are required."""
    op.execute(links.update().where(links.c.title.is_(None)).values(title=links.c.url))
    with op.batch_alter_table("links") as batch:
        batch.alter_column("title", existing_type=sa.String(200), nullable=False)


def downgrade() -> None:
    """Titles become optional again (the copied URLs stay)."""
    with op.batch_alter_table("links") as batch:
        batch.alter_column("title", existing_type=sa.String(200), nullable=True)
''',
    ),
}


def write_lab_migrations(versions_dir: Path) -> None:
    """Write 0001_create_links.py, 0002_clicks_and_unique_url.py, 0003_fill_titles.py."""
    for filename, (revision, previous, body) in LAB_MIGRATIONS.items():
        header = LAB_MIGRATION_HEADER.format(revision=revision, previous=repr(previous))
        source = f'"""{filename[5:-3].replace("_", " ")}"""\n\n{header}\n{body}'
        (versions_dir / filename).write_text(source, encoding="utf-8")


# <<< Lab 6.4 exercise 4


# >>> Lab 6.4 exercise 5
def update_document(
    session: Session, document_id: int, content: str, expected_version: int
) -> LabDocument:
    """Change a document if it is still at expected_version."""
    document = session.get(LabDocument, document_id)
    if document is None:
        raise LookupError(f"document {document_id} not found")
    if document.version != expected_version:
        raise DocumentConflictError(f"document {document_id} is at version {document.version}")
    document.content = content
    try:
        session.flush()
    except StaleDataError as error:
        raise DocumentConflictError(f"document {document_id} changed meanwhile") from error
    return document


class DocumentPatch(BaseModel):
    """Body of PATCH /documents/{document_id}."""

    content: str
    version: int


def build_documents_app(session_factory: sessionmaker[Session]) -> FastAPI:
    """GET and PATCH /documents/{document_id} with 404 and 409 answers."""
    app = FastAPI()

    def get_document_session() -> Iterator[Session]:
        """One transaction per request."""
        with session_factory() as session, session.begin():
            yield session

    session_dependency = Depends(get_document_session, scope="function")  # commit before responding

    def as_dict(document: LabDocument) -> dict[str, object]:
        """The response body."""
        return {"id": document.id, "content": document.content, "version": document.version}

    @app.exception_handler(DocumentConflictError)
    async def conflict(request: fastapi.Request, error: DocumentConflictError) -> JSONResponse:
        """Optimistic-locking conflict → 409."""
        return JSONResponse({"detail": "version conflict"}, status_code=status.HTTP_409_CONFLICT)

    @app.get("/documents/{document_id}")
    def read_document(document_id: int, session: Session = session_dependency) -> dict[str, object]:
        """One document, or 404."""
        document = session.get(LabDocument, document_id)
        if document is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
        return as_dict(document)

    @app.patch("/documents/{document_id}")
    def patch_document(
        document_id: int, patch: DocumentPatch, session: Session = session_dependency
    ) -> dict[str, object]:
        """Update if the client's version is current."""
        try:
            document = update_document(session, document_id, patch.content, patch.version)
        except LookupError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found") from error
        return as_dict(document)

    return app


# <<< Lab 6.4 exercise 5


# >>> Lab 6.4 exercise 6
def create_lab_indexes(engine: sa.Engine) -> None:
    """An expression index for prefix search and a composite index for keyset paging."""
    with engine.begin() as connection:
        connection.execute(
            text("CREATE INDEX ix_lab_items_title_lower ON lab_items (lower(title))")
        )
        connection.execute(
            text("CREATE INDEX ix_lab_items_created_at_id ON lab_items (created_at, id)")
        )


def search_prefix(session: Session, prefix: str, limit: int = 20) -> list[str]:
    """Case-insensitive prefix search as a range on lower(title)."""
    low = prefix.lower()
    high = low[:-1] + chr(ord(low[-1]) + 1)
    lowered = func.lower(LabItem.title)
    statement = (
        select(LabItem.title)
        .where(lowered >= low, lowered < high)
        .order_by(lowered, LabItem.id)
        .limit(limit)
    )
    return list(session.scalars(statement))


def keyset_items(session: Session, after: tuple[datetime, int] | None, limit: int) -> list[LabItem]:
    """Newest first; strictly before after when given."""
    statement = select(LabItem).order_by(LabItem.created_at.desc(), LabItem.id.desc()).limit(limit)
    if after is not None:
        statement = statement.where(tuple_(LabItem.created_at, LabItem.id) < tuple_(*after))
    return list(session.scalars(statement))


# <<< Lab 6.4 exercise 6


# ----- Lab 6.4: the notebook's check cells -----


def lab_schema() -> dict[str, object]:
    """Tables, nullability, the association primary key and constraint names on SQLite."""
    engine = create_engine("sqlite://")
    LabBase.metadata.create_all(engine)
    inspector = sa_inspect(engine)
    return {
        "tables": sorted(inspector.get_table_names()),
        "note columns": {
            column["name"]: column["nullable"] for column in inspector.get_columns("lab_notes")
        },
        "link key": inspector.get_pk_constraint("lab_note_tags")["constrained_columns"],
        "unique": [
            constraint["name"] for constraint in inspector.get_unique_constraints("lab_tags")
        ],
    }


def lab_sqlite_engine() -> sa.Engine:
    """An in-memory SQLite database with the lab tables and foreign keys on."""
    engine = create_engine("sqlite://")
    event.listen(
        engine,
        "connect",
        lambda dbapi_connection, _: dbapi_connection.execute("PRAGMA foreign_keys=ON"),
    )
    LabBase.metadata.create_all(engine)
    return engine


def lab_tag_scenario(bind: Any) -> dict[str, object]:
    """Two notes sharing a tag, then deleting one note (bind: Engine or Connection)."""
    with Session(bind) as session:
        add_lab_note(session, "Buy tea", ["shop", "food"])
        add_lab_note(session, "Rice", ["shop"])
        session.expire_all()  # read back from the database, so order_by applies
        note = session.scalars(select(LabNote).where(LabNote.title == "Buy tea")).one()
        result: dict[str, object] = {
            "tags": session.scalar(select(func.count()).select_from(LabTag)),
            "names": [tag.name for tag in note.tags],
            "body": note.body,
            "pinned": note.pinned,
            "has created_at": note.created_at is not None,
        }
        session.delete(note)
        session.flush()
        result["links after delete"] = session.scalar(
            select(func.count()).select_from(lab_note_tags)
        )
        return result


async def lab_scenario_on_postgres() -> object:
    """The same scenario through an async engine (SQLite here: no container in this script)."""
    try:
        engine = create_async_engine(PG_URL or "sqlite+aiosqlite://")
        async with engine.begin() as connection:
            await connection.run_sync(LabBase.metadata.drop_all)
            await connection.run_sync(LabBase.metadata.create_all)
            result = await connection.run_sync(lab_tag_scenario)
            await connection.run_sync(LabBase.metadata.drop_all)
        await engine.dispose()
        return result
    except Exception as error:  # a check must never stop the run
        return f"raised {type(error).__name__}: {error}"


def check_exercise_6_4_1() -> None:
    """Exercise 1 checks."""
    expected = {
        "tags": 2,
        "names": ["food", "shop"],
        "body": "",
        "pinned": False,
        "has created_at": True,
        "links after delete": 1,
    }
    postgres_result = asyncio.run(lab_scenario_on_postgres())
    run_checks(
        [
            (
                "three tables",
                lambda: lab_schema()["tables"],
                ["lab_note_tags", "lab_notes", "lab_tags"],
            ),
            (
                "every note column is NOT NULL",
                lambda: lab_schema()["note columns"],
                {"id": False, "title": False, "body": False, "pinned": False, "created_at": False},
            ),
            (
                "composite key on the association table",
                lambda: lab_schema()["link key"],
                ["note_id", "tag_id"],
            ),
            ("named unique constraint", lambda: lab_schema()["unique"], ["uq_lab_tags_name"]),
            (
                "created_at is timezone-aware",
                lambda: LabNote.__table__.c.created_at.type.timezone,
                True,
            ),
            (
                "tags are shared; defaults; cascade (SQLite)",
                lambda: lab_tag_scenario(lab_sqlite_engine()),
                expected,
            ),
            ("the same on PostgreSQL", lambda: postgres_result, expected),
        ]
    )


def run_lab_query(key: str) -> object:
    """Run one statement on fresh data: rows for SELECT, (rowcount, pinned titles) for DML."""
    statement = build_eight_queries()[key]
    engine = fresh_q_engine()
    try:
        with Session(engine) as session, session.begin():
            result = session.execute(statement)
            if not statement.is_select:  # UPDATE / DELETE
                pinned = session.scalars(
                    select(QNote.title).where(QNote.pinned).order_by(QNote.title)
                ).all()
                return result.rowcount, pinned
            rows = [tuple(row) for row in result.all()]
    finally:
        engine.dispose()
    return [row[0] for row in rows] if rows and len(rows[0]) == 1 else rows


def check_exercise_6_4_2() -> None:
    """Exercise 2 checks, then the SQL."""
    run_checks(
        [
            ("pinned_titles", lambda: run_lab_query("pinned_titles"), ["Buy tea", "Pay rent"]),
            ("tagged_work", lambda: run_lab_query("tagged_work"), ["Draft: plan", "Fix bug"]),
            (
                "count_per_tag",
                lambda: run_lab_query("count_per_tag"),
                [("home", 2), ("work", 2), ("bills", 1), ("food", 1), ("shop", 1)],
            ),
            ("popular_tags", lambda: run_lab_query("popular_tags"), ["home", "work"]),
            ("untagged", lambda: run_lab_query("untagged"), ["Read book", "Draft: email"]),
            (
                "latest_per_tag",
                lambda: run_lab_query("latest_per_tag"),
                [
                    ("bills", "Pay rent"),
                    ("food", "Buy tea"),
                    ("home", "Pay rent"),
                    ("shop", "Buy tea"),
                    ("work", "Fix bug"),
                ],
            ),
            ("unpin_old", lambda: run_lab_query("unpin_old"), (1, ["Pay rent"])),
            ("delete_drafts", lambda: run_lab_query("delete_drafts")[0], 2),
        ]
    )
    for key, statement in build_eight_queries().items():
        print(f"-- {key}\n{statement.compile(dialect=sqlite.dialect())}")


def strict_tags_error() -> str:
    """What touching the tags of a strict note raises."""
    engine = fresh_q_engine()
    with Session(engine) as session:
        note = strict_note(session, 1)
        return raised_error_name(lambda: note.tags)


def listeners_left_behind() -> int:
    """Listeners count_statements added and did not remove."""
    engine = fresh_q_engine()
    before = len(engine.dispatch.before_cursor_execute)
    count_statements(engine, lambda session: session.get(QNote, 1))
    return len(engine.dispatch.before_cursor_execute) - before


def check_exercise_6_4_3() -> None:
    """Exercise 3 checks."""
    q_engine = fresh_q_engine()
    run_checks(
        [
            (
                "counting: get() twice is one statement",
                lambda: count_statements(
                    q_engine, lambda session: (session.get(QNote, 1), session.get(QNote, 1))
                )[0],
                1,
            ),
            (
                "the slow version is 1 + 7 statements",
                lambda: count_statements(q_engine, titles_with_tags_slow)[0],
                8,
            ),
            (
                "the fast version is at most 2",
                lambda: count_statements(q_engine, titles_with_tags_fast)[0] <= 2,
                True,
            ),
            (
                "same result",
                lambda: (
                    count_statements(q_engine, titles_with_tags_fast)[1]
                    == count_statements(q_engine, titles_with_tags_slow)[1]
                ),
                True,
            ),
            ("the listener is removed afterwards", listeners_left_behind, 0),
            ("raiseload makes lazy loads fail", strict_tags_error, "InvalidRequestError"),
        ]
    )


def lab_migration_run() -> dict[str, object]:
    """Write the migrations, walk them up and down, and record what happened."""
    write_lab_migrations(reset_lab_alembic())
    report: dict[str, object] = {"chain": re.findall(r"(\S+) -> (\w+)", lab_alembic("history"))}
    lab_alembic("upgrade", "0002")
    engine = create_engine(f"sqlite:///{LAB_ALEMBIC_DB}")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO links (url) VALUES ('https://a.example')"))
    report["at 0002"] = {
        column["name"]: column["nullable"] for column in sa_inspect(engine).get_columns("links")
    }
    lab_alembic("upgrade", "head")
    with engine.connect() as connection:
        report["rows"] = [
            tuple(row) for row in connection.execute(text("SELECT url, title, clicks FROM links"))
        ]
    report["title nullable at head"] = {
        column["name"]: column["nullable"] for column in sa_inspect(engine).get_columns("links")
    }["title"]
    with engine.connect() as connection:
        report["duplicate url"] = raised_error_name(
            lambda: connection.execute(
                text("INSERT INTO links (url, title) VALUES ('https://a.example', 'again')")
            )
        )
    lab_alembic("downgrade", "base")
    report["tables after downgrade"] = sa_inspect(engine).get_table_names()
    engine.dispose()
    return report


def check_exercise_6_4_4() -> None:
    """Exercise 4 checks."""
    run_checks(
        [
            (
                "three revisions in a chain",
                lambda: lab_migration_run()["chain"],
                [("0002", "0003"), ("0001", "0002"), ("<base>", "0001")],
            ),
            (
                "schema at 0002",
                lambda: lab_migration_run()["at 0002"],
                {"id": False, "url": False, "title": True, "clicks": False},
            ),
            (
                "data migration filled the title",
                lambda: lab_migration_run()["rows"],
                [("https://a.example", "https://a.example", 0)],
            ),
            (
                "title is NOT NULL at head",
                lambda: lab_migration_run()["title nullable at head"],
                False,
            ),
            ("url is unique", lambda: lab_migration_run()["duplicate url"], "IntegrityError"),
            (
                "downgrade base removes the table",
                lambda: lab_migration_run()["tables after downgrade"],
                ["alembic_version"],
            ),
        ]
    )


def documents_scenario() -> list[tuple[int, object]]:
    """PATCH with the right version, again with the old one, then GET; plus a 404."""
    with TestClient(build_documents_app(fresh_documents())) as client:
        calls = [
            client.patch("/documents/1", json={"content": "second draft", "version": 1}),
            client.patch("/documents/1", json={"content": "lost edit", "version": 1}),
            client.get("/documents/1"),
            client.patch("/documents/9", json={"content": "x", "version": 1}),
        ]
        return [(response.status_code, response.json()) for response in calls]


def documents_race() -> str:
    """Two sessions read version 1; the first commits; the second's flush must fail."""
    factory = fresh_documents()
    with factory() as first, factory() as second:
        second.get(LabDocument, 1)  # second has read version 1 too
        update_document(first, 1, "first wins", 1)
        first.commit()
        return raised_error_name(lambda: update_document(second, 1, "second loses", 1))


def check_exercise_6_4_5() -> None:
    """Exercise 5 checks."""
    current = (200, {"id": 1, "content": "second draft", "version": 2})
    run_checks(
        [
            ("PATCH with the current version", lambda: documents_scenario()[0], current),
            (
                "PATCH with a stale version → 409",
                lambda: documents_scenario()[1],
                (409, {"detail": "version conflict"}),
            ),
            ("the stale edit was not saved", lambda: documents_scenario()[2], current),
            (
                "unknown document → 404",
                lambda: documents_scenario()[3],
                (404, {"detail": "document not found"}),
            ),
            (
                "wrong expected version",
                lambda: raised_error_name(lambda: update_document(fresh_documents()(), 1, "x", 7)),
                "DocumentConflictError",
            ),
            ("a concurrent commit is caught at flush", documents_race, "DocumentConflictError"),
        ]
    )


def last_query_plan(engine: sa.Engine, action: Callable[[Session], object]) -> str:
    """EXPLAIN QUERY PLAN of the last SELECT that action(session) sent."""
    sent: list[tuple[str, Any]] = []

    def remember(conn: Any, cursor: Any, statement: str, parameters: Any, *rest: Any) -> None:
        """Keep each statement with its parameters."""
        sent.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", remember)
    try:
        with Session(engine) as session:
            action(session)
    finally:
        event.remove(engine, "before_cursor_execute", remember)
    statement, parameters = [
        item for item in sent if item[0].lstrip().upper().startswith("SELECT")
    ][-1]
    with engine.connect() as connection:
        return " | ".join(
            row[-1]
            for row in connection.exec_driver_sql("EXPLAIN QUERY PLAN " + statement, parameters)
        )


def indexed_items() -> tuple[sa.Engine, list[tuple[int, str, datetime]]]:
    """A fresh engine with the indexes, and every row for brute-force answers."""
    engine = fresh_items_engine()
    create_lab_indexes(engine)
    with engine.connect() as connection:
        rows = [
            tuple(row)
            for row in connection.execute(select(LabItem.id, LabItem.title, LabItem.created_at))
        ]
    return engine, rows  # type: ignore[return-value]


def walk_items(engine: sa.Engine, page_size: int) -> list[int]:
    """Ids of every item, page by page through keyset_items."""
    ids: list[int] = []
    after = None
    with Session(engine) as session:
        while page := keyset_items(session, after, page_size):
            ids += [item.id for item in page]
            after = (page[-1].created_at, page[-1].id)
    return ids


def expected_prefix(rows: list[tuple[int, str, datetime]], prefix: str, limit: int) -> list[str]:
    """The right answer, computed in Python."""
    matching = sorted(
        (title.lower(), item_id, title)
        for item_id, title, _ in rows
        if title.lower().startswith(prefix.lower())
    )
    return [title for _, _, title in matching[:limit]]


def expected_order(rows: list[tuple[int, str, datetime]]) -> list[int]:
    """Every id, newest first by (created_at, id)."""
    return [
        item_id for item_id, _, _ in sorted(rows, key=lambda row: (row[2], row[0]), reverse=True)
    ]


def prefix_search_is_right(prefix: str, limit: int) -> bool:
    """search_prefix agrees with Python on a fresh, indexed database."""
    engine, rows = indexed_items()
    with Session(engine) as session:
        return search_prefix(session, prefix, limit) == expected_prefix(rows, prefix, limit)


def keyset_walk_is_right() -> bool:
    """Walking keyset pages visits every id once, newest first."""
    engine, rows = indexed_items()
    return walk_items(engine, 700) == expected_order(rows)


def check_exercise_6_4_6() -> None:
    """Exercise 6 checks."""
    run_checks(
        [
            ("prefix search matches Python", lambda: prefix_search_is_right("Ri", 15), True),
            ("case does not matter", lambda: prefix_search_is_right("rUbY", 50), True),
            (
                "the search uses the expression index",
                lambda: (
                    "USING INDEX ix_lab_items_title_lower"
                    in last_query_plan(
                        indexed_items()[0], lambda session: search_prefix(session, "ri", 5)
                    )
                ),
                True,
            ),
            ("keyset pages cover every item in order", keyset_walk_is_right, True),
            (
                "the page query uses the composite index",
                lambda: (
                    "ix_lab_items_created_at_id"
                    in last_query_plan(
                        indexed_items()[0],
                        lambda session: keyset_items(
                            session, (datetime(2026, 1, 1, 8, 0), 1500), 10
                        ),
                    )
                ),
                True,
            ),
        ]
    )


def check_lab_6_4() -> None:
    """Run every Lab 6.4 check (each check prints PASS/FAIL)."""
    for title, check in (
        ("exercise 1", check_exercise_6_4_1),
        ("exercise 2", check_exercise_6_4_2),
        ("exercise 3", check_exercise_6_4_3),
        ("exercise 4", check_exercise_6_4_4),
        ("exercise 5", check_exercise_6_4_5),
        ("exercise 6", check_exercise_6_4_6),
    ):
        print(f"--- {title}")
        check()


if __name__ == "__main__":
    selected = set(sys.argv[1:])
    labs = [
        ("Lab 6.1", check_lab_6_1),
        ("Lab 6.2", check_lab_6_2),
        ("Lab 6.3", check_lab_6_3),
        ("Lab 6.4", check_lab_6_4),
    ]
    for lab_title, check_lab in labs:
        if selected and lab_title not in selected:
            continue
        print(f"===== {lab_title} =====")
        check_lab()
