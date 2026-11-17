"""Pure ASGI middleware: request ids (kept in a ContextVar) and Server-Timing headers."""

import re
import time
import uuid
from collections.abc import Callable
from contextvars import ContextVar

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestIdMiddleware:
    """Reuse a safe incoming X-Request-ID or make one; expose it to code, logs and the client."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the next ASGI app."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Set the id for this request, add it to the response headers, then reset it."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = Headers(scope=scope).get(REQUEST_ID_HEADER, "")
        request_id = incoming if VALID_REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id  # request.state.request_id
        token = request_id_var.set(request_id)

        async def send_with_id(message: Message) -> None:
            """Add the header to the response start message."""
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_var.reset(token)


class TimingMiddleware:
    """Add Server-Timing: app;dur=<ms>, measured until the response starts."""

    def __init__(self, app: ASGIApp, clock: Callable[[], float] = time.perf_counter) -> None:
        """Wrap the next ASGI app; clock is injectable for tests."""
        self.app = app
        self.clock = clock

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Time the inner app and report it in a header (milliseconds, one decimal)."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = self.clock()

        async def send_with_timing(message: Message) -> None:
            """Add the header to the response start message."""
            if message["type"] == "http.response.start":
                elapsed_ms = (self.clock() - started) * 1000
                MutableHeaders(scope=message).append("Server-Timing", f"app;dur={elapsed_ms:.1f}")
            await send(message)

        await self.app(scope, receive, send_with_timing)
