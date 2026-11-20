"""Structured JSON logs (structlog) with request/trace ids, and redaction of secrets.

Every log line, from our code (structlog or stdlib logging) and from Uvicorn, goes through the
same processors and comes out as one JSON object: timestamp, level, logger, event, plus the
request id and the OpenTelemetry trace/span ids when there is a request or span in progress.
Secrets never reach the output (OWASP API8, and plain good sense).
"""

import logging
import re
import sys
import time
from typing import Any, TextIO

import structlog
from opentelemetry import trace
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from notes_api.core.middleware import request_id_var

SENSITIVE_KEYS = ("password", "token", "secret", "authorization", "api_key", "cookie")
REDACTED = "[REDACTED]"
PATTERNS = [
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),  # Authorization header values
    re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*"),  # anything shaped like a JWT
    re.compile(r"\bnk_[A-Za-z0-9_-]{16,}"),  # our API keys
    re.compile(  # key=value pairs (but leave "Bearer ..." to the first pattern)
        rf"(?i)\b((?:{'|'.join(SENSITIVE_KEYS)})\w*\s*[=:]\s*)(?!bearer\b|\[REDACTED\])[^\s,;&]+"
    ),
]


def redact_text(text: str) -> str:
    """Replace secrets in a string (prefixes such as 'Bearer ' or 'password=' are kept)."""
    for pattern in PATTERNS:
        replacement = rf"\g<1>{REDACTED}" if pattern.groups else REDACTED
        text = pattern.sub(replacement, text)
    return text


def redact_value(key: str, value: object) -> object:
    """Redact a mapping value whose key looks sensitive; recurse into nested mappings."""
    if isinstance(value, dict):
        return {inner: redact_value(inner, item) for inner, item in value.items()}
    if any(word in key.lower() for word in SENSITIVE_KEYS):
        return REDACTED
    return redact_text(value) if isinstance(value, str) else value


class RedactingFilter(logging.Filter):
    """Rewrite each record's message and arguments before any handler formats it."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact in place; never drop the record."""
        if isinstance(record.args, dict):
            record.args = {key: redact_value(key, value) for key, value in record.args.items()}
        message = record.getMessage() if record.args else str(record.msg)
        record.msg, record.args = redact_text(message), None
        return True


def install_redaction(logger_names: tuple[str, ...] = ("notes_api", "uvicorn.access")) -> None:
    """Attach the filter to the app's loggers (idempotent)."""
    for name in logger_names:
        logger = logging.getLogger(name)
        if not any(isinstance(existing, RedactingFilter) for existing in logger.filters):
            logger.addFilter(RedactingFilter())


def add_request_context(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """structlog processor: add the request id and the current trace/span ids."""
    request_id = request_id_var.get()
    if request_id is not None:
        event_dict.setdefault("request_id", request_id)
    span_context = trace.get_current_span().get_span_context()
    if span_context.is_valid:
        event_dict["trace_id"] = format(span_context.trace_id, "032x")
        event_dict["span_id"] = format(span_context.span_id, "016x")
    return event_dict


def redact_event(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """structlog processor: redact sensitive keys and secret-looking values."""
    return {key: redact_value(key, value) for key, value in event_dict.items()}


SHARED_PROCESSORS: list[Any] = [
    structlog.contextvars.merge_contextvars,  # values bound with bind_contextvars()
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
    add_request_context,
    structlog.processors.format_exc_info,
    redact_event,
]


def configure_logging(
    level: str = "INFO", json_output: bool = True, stream: TextIO | None = None
) -> None:
    """Route structlog and stdlib logging (Uvicorn included) through one JSON formatter."""
    renderer = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[*SHARED_PROCESSORS, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=SHARED_PROCESSORS,  # stdlib records get the same treatment
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.set_name("notes_api_json")
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers[:] = [
        existing for existing in root.handlers if existing.get_name() != "notes_api_json"
    ] + [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers.clear()  # let them propagate to our handler
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)  # AccessLogMiddleware logs
    for noisy in ("httpx", "httpcore", "httpx2"):  # one line per outgoing request is too much
        logging.getLogger(noisy).setLevel(logging.WARNING)


class AccessLogMiddleware:
    """Pure ASGI: one structured log line per request, written inside the request's context."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the next ASGI app."""
        self.app = app
        self.logger = structlog.get_logger("notes_api.access")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Log method, path, status and duration when the response is complete."""
        if scope["type"] != "http" or scope["path"].startswith(("/health", "/metrics")):
            await self.app(scope, receive, send)
            return
        started, status_code = time.perf_counter(), 500

        async def send_and_record(message: Message) -> None:
            """Remember the status code."""
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_and_record)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            log = self.logger.warning if status_code >= 500 else self.logger.info
            log(
                "request",
                method=scope["method"],
                path=scope["path"],
                status=status_code,
                duration_ms=duration_ms,
            )
