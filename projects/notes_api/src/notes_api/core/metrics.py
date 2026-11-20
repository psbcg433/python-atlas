"""Prometheus metrics: RED (rate, errors, duration) per route, plus a few business counters.

The metrics live in their own registry (not prometheus_client's global one), so re-importing
this module (tests, notebooks) never registers a metric twice. With several worker processes
(`uvicorn --workers N`), set PROMETHEUS_MULTIPROC_DIR to an empty directory: every process
then writes its values to files there and GET /metrics aggregates them (multiprocess mode).
"""

import os
import time

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client.multiprocess import MultiProcessCollector
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REGISTRY = CollectorRegistry(auto_describe=True)
# Latency buckets in seconds: dense around the 200 ms target of the load test
LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 1.0, 2.5, 5.0)


HTTP_REQUESTS = Counter(
    "notes_http_requests_total",
    "HTTP requests handled, by method, route template and status code.",
    ["method", "route", "status"],
    registry=REGISTRY,
)
HTTP_LATENCY = Histogram(
    "notes_http_request_duration_seconds",
    "Time from receiving the request to sending the last body chunk.",
    ["method", "route"],
    buckets=LATENCY_BUCKETS,
    registry=REGISTRY,
)


HTTP_IN_PROGRESS = Gauge(
    "notes_http_requests_in_progress",
    "Requests being handled right now.",
    ["method"],
    multiprocess_mode="livesum",  # summed over the live worker processes
    registry=REGISTRY,
)


NOTES_WRITTEN = Counter(
    "notes_writes_total",
    "Notes created, updated or deleted.",
    ["operation"],
    registry=REGISTRY,
)
CACHE_LOOKUPS = Counter(
    "notes_cache_lookups_total",
    "Note cache lookups, by result.",
    ["result"],
    registry=REGISTRY,
)


EXCLUDED_PATHS = ("/metrics", "/health")  # probes and scrapes would drown the real traffic


def route_template(scope: Scope) -> str:
    """The matched route's template (e.g. /api/v1/notes/{note_id}); 'unmatched' for 404s.

    Labels must have few distinct values: raw paths (/notes/1, /notes/2, ...) would create a
    time series per note id.
    """
    route = scope.get("route")
    if route is None or not hasattr(route, "path_format"):
        return "unmatched"
    params = {name: str(value) for name, value in scope.get("path_params", {}).items()}
    try:
        rendered = route.path_format.format(**params)
    except KeyError, IndexError, ValueError:
        return route.path_format
    path = scope.get("path", "")
    prefix = path[: len(path) - len(rendered)] if path.endswith(rendered) else ""
    return prefix + route.path_format  # path_format drops converters: {note_id}, not {note_id:int}


class MetricsMiddleware:
    """Pure ASGI: count requests, observe their duration, track requests in flight."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the next ASGI app."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Measure one HTTP request (WebSockets and lifespan pass through)."""
        if scope["type"] != "http" or scope["path"].startswith(EXCLUDED_PATHS):
            await self.app(scope, receive, send)
            return
        method, started, status_code = scope["method"], time.perf_counter(), 500

        async def send_and_record(message: Message) -> None:
            """Remember the status code from the response start."""
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        HTTP_IN_PROGRESS.labels(method).inc()
        try:
            await self.app(scope, receive, send_and_record)
        finally:
            HTTP_IN_PROGRESS.labels(method).dec()
            route = route_template(scope)
            HTTP_REQUESTS.labels(method, route, str(status_code)).inc()
            HTTP_LATENCY.labels(method, route).observe(time.perf_counter() - started)


def metrics_registry() -> CollectorRegistry:
    """This process's registry, or an aggregate of every worker's files in multiprocess mode."""
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        aggregate = CollectorRegistry()
        MultiProcessCollector(aggregate)
        return aggregate
    return REGISTRY


async def metrics_endpoint(request: Request) -> Response:
    """GET /metrics in the Prometheus text exposition format."""
    return Response(generate_latest(metrics_registry()), media_type=CONTENT_TYPE_LATEST)
