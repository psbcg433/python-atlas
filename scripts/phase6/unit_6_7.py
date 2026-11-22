"""Unit 6.7 — API Testing and Observability (with Lab 6.7 and Notes API v6)."""

from helpers_module import setup_cells
from nbformat import NotebookNode

from nb_builder import code, md, predict_cells, writefile_cells

UNIT_SETUP_SOURCE = r"""
import asyncio
import atexit
import contextlib
import difflib
import importlib
import importlib.util
import inspect
import io
import itertools
import json
import logging
import math
import os
import random
import re
import secrets
import shutil
import socket
import sqlite3
import statistics
import subprocess
import sys
import textwrap
import threading
import time
import urllib.request
import uuid
import warnings
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import alembic
import arq
import asyncpg
import fakeredis
import fastapi
import httpx
import hypothesis
import jwt
import prometheus_client
import pwdlib
import pydantic
import pydantic_settings
import redis.asyncio as redis_asyncio
import respx
import schemathesis
import sqlalchemy as sa
import starlette
import structlog
import uvicorn
import yaml
from arq.connections import ArqRedis
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, WebSocket, status
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect
from hypothesis import HealthCheck, Verbosity, given
from hypothesis import settings as hypothesis_settings
from opentelemetry import propagate, trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool

warnings.filterwarnings(
    "ignore", message=".*iscoroutinefunction.* is deprecated", category=DeprecationWarning
)
warnings.filterwarnings("ignore", message="Call to deprecated close", category=DeprecationWarning)

"""

POSTGRES_HELPERS_SOURCE = r'''
pg_container: Any = None  # one PostgreSQL testcontainer per unit, started on first use
PG_URL: str | None = None


def stop_shared_postgres() -> None:
    """Stop and remove the unit's PostgreSQL container (also registered with atexit)."""
    global pg_container
    if pg_container is not None:
        with contextlib.suppress(Exception):
            pg_container.stop()
        pg_container = None


def start_shared_postgres() -> str | None:
    """Start the unit's PostgreSQL container once; return its asyncpg URL (None without Docker)."""
    global pg_container
    if not HAS_DOCKER:
        return None
    if pg_container is None:
        from testcontainers.community.postgres import PostgresContainer

        pg_container = PostgresContainer(POSTGRES_IMAGE, driver="asyncpg").start()
        atexit.register(stop_shared_postgres)
    return pg_container.get_connection_url()


print(f"{structlog.__version__=}  {schemathesis.__version__=}")
print(f"{hypothesis.__version__=}  {prometheus_client.__name__=}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 6.7 — API Testing and Observability

            **Objectives**

            - Choose between `TestClient` and `httpx.AsyncClient` + `ASGITransport`, configure
              async tests, and swap dependencies with `dependency_overrides`.
            - Test against a real database: testcontainers, rollback-per-test, factories.
            - Fake external services with `respx` / `MockTransport`; test WebSockets, jobs and
              streams.
            - Find contract bugs with Schemathesis and freeze the public API with an OpenAPI
              snapshot.
            - Explain logs, metrics and traces, SLIs and SLOs, and the RED and USE methods.
            - Write structured JSON logs with structlog, carrying request and trace ids, with
              secrets redacted.
            - Expose Prometheus counters, gauges and histograms, also from several processes.
            - Trace requests with OpenTelemetry auto-instrumentation and send spans to an
              exporter.
            - Track errors with Sentry and design liveness, readiness and startup probes.
            - Move the **Notes API to v6**: a reorganised suite run in CI against service
              containers, JSON logs, metrics, traces, Sentry, probes.

            **JS bridge**

            | JavaScript / TypeScript | Python | The difference that bites |
            | --- | --- | --- |
            | Jest / Vitest + Supertest (`request(app).get(...)`) | pytest + `TestClient` / `httpx.AsyncClient(transport=ASGITransport(app))` | `TestClient` runs the app in another thread and event loop |
            | `jest.mock()` of modules | `app.dependency_overrides[dep] = fake` | overrides replace a dependency, not an import: design for injection |
            | `nock` / MSW | `respx` / `httpx.MockTransport` | intercepts httpx only (not `requests` or `urllib`) |
            | Testcontainers for Node | testcontainers-python | same project, same Ryuk reaper |
            | Dredd / Schemathesis (also for Node) | Schemathesis + Hypothesis | generates cases from the schema and shrinks failures |
            | pino / winston (JSON logs) | structlog (+ stdlib logging) | bind context with `contextvars`, not `req.log` |
            | prom-client | prometheus_client | several Uvicorn workers need multiprocess mode |
            | `@opentelemetry/auto-instrumentations-node` | `opentelemetry-instrumentation-fastapi` | instrument the app object; exporters are configured in code |
            | `@sentry/node` | `sentry-sdk` | `before_send` must scrub secrets |

            Run the setup cells first. Part 1: the imports (structlog, prometheus_client,
            OpenTelemetry, Schemathesis):
            """
        ),
        *setup_cells(
            "6.7",
            UNIT_SETUP_SOURCE,
            """
            Part 2: the shared helpers from [`phase6_helpers.py`](phase6_helpers.py) (server, Notes API, database, Redis and
            worker helpers of Units 6.1–6.6), including `start_shared_postgres()`: one
            PostgreSQL testcontainer for the unit, removed in the *Clean up* cell and by an
            `atexit` hook:
            """,
            folders='*NOTES_FOLDERS, REPO_ROOT / ".github" / "workflows"',
        ),
    ]


def _test_architecture_cells() -> list[NotebookNode]:
    """6.7.1 Test architecture."""
    return [
        md(
            """
            ### 6.7.1 Test architecture

            | | `TestClient` (Starlette, on httpx) | `httpx.AsyncClient(transport=ASGITransport(app))` |
            | --- | --- | --- |
            | Test style | plain `def` tests | `async def` tests (pytest's anyio plugin) |
            | Where the app runs | a **separate thread and event loop** (anyio portal) | the test's own event loop |
            | Lifespan | runs inside `with TestClient(app)` | not run: enter `app.router.lifespan_context(app)` yourself |
            | WebSockets | `client.websocket_connect()` | not supported |
            | Async objects shared with the test (asyncpg connection, task, fake client) | no: they belong to the test's loop | yes |
            | Typical use | most API tests | database-transaction tests, concurrency tests, async fixtures |

            Where does each client run the app? An endpoint reports its thread and event loop:
            """
        ),
        code(
            r'''
            loop_app = FastAPI()


            @loop_app.get("/where")
            async def where() -> dict[str, int]:
                """The thread and event loop running this request."""
                return {"thread": threading.get_ident(), "loop": id(asyncio.get_running_loop())}


            here = {"thread": threading.get_ident(), "loop": id(asyncio.get_running_loop())}
            with TestClient(loop_app) as client:
                via_test_client = client.get("/where").json()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=loop_app), base_url="http://test"
            ) as http:
                via_async_client = (await http.get("/where")).json()
            for label, seen in (("TestClient ", via_test_client), ("AsyncClient", via_async_client)):
                print(
                    f"{label}: same thread as this cell: {seen['thread'] == here['thread']!s:5} "
                    f" same loop: {seen['loop'] == here['loop']}"
                )
            '''
        ),
        md(
            """
            `ASGITransport` does not send lifespan events; tests that need the app's startup
            resources enter `app.router.lifespan_context(app)` (the Notes API's `async_client`
            fixture does):
            """
        ),
        code(
            r'''
            @contextlib.asynccontextmanager
            async def demo_lifespan(app: FastAPI) -> AsyncIterator[None]:
                """Startup and shutdown of a tiny app."""
                app.state.started = True
                yield
                app.state.started = False


            life_app = FastAPI(lifespan=demo_lifespan)


            @life_app.get("/started")
            async def started(request: Request) -> dict[str, bool]:
                """Did the lifespan run?"""
                return {"started": getattr(request.app.state, "started", False)}


            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=life_app), base_url="http://test"
            ) as http:
                print("AsyncClient alone      :", (await http.get("/started")).json())
                async with life_app.router.lifespan_context(life_app):
                    print("inside lifespan_context:", (await http.get("/started")).json())
            '''
        ),
        md(
            """
            **Async test configuration.** Async tests need a plugin that runs them on an event
            loop. anyio ships one (no extra package): mark tests with `pytest.mark.anyio` and
            choose the backend with an `anyio_backend` fixture; async fixtures work the same way.
            (`pytest-asyncio` is the other common choice: `asyncio_mode = "auto"`.) A complete
            async test module, run with pytest:
            """
        ),
        code(
            r'''
            %%writefile _scratch/phase6/test_async_demo.py
            """Async tests with the anyio pytest plugin."""

            from collections.abc import AsyncIterator

            import httpx
            import pytest
            from fastapi import FastAPI

            pytestmark = pytest.mark.anyio
            app = FastAPI()


            @app.get("/ping")
            async def ping() -> dict[str, str]:
                """A route to call."""
                return {"pong": "yes"}


            @pytest.fixture
            def anyio_backend() -> str:
                """Run on asyncio (trio is the other option)."""
                return "asyncio"


            @pytest.fixture
            async def http() -> AsyncIterator[httpx.AsyncClient]:
                """An async client calling the app in the test's loop."""
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    yield client


            async def test_ping(http: httpx.AsyncClient) -> None:
                """Awaited request, plain assert."""
                assert (await http.get("/ping")).json() == {"pong": "yes"}
            '''
        ),
        md("Run it:"),
        code(
            r"""
            async_run = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_async_demo.py"],
                cwd=PHASE6_DIR,
                capture_output=True,
                text=True,
                env=CHILD_ENV,
                timeout=120,
            )
            print(tidy_test_output(async_run.stdout).splitlines()[-1])
            """
        ),
        md(
            """
            **`dependency_overrides`** swaps a dependency for a test: a fixed clock, a fake
            payment client, a session in a rolled-back transaction. The route code is unchanged;
            clear the dict afterwards (a fresh app per test does that for you):
            """
        ),
        code(
            r'''
            def get_exchange_rate() -> float:
                """The real dependency would call a paid API."""
                raise RuntimeError("no network in tests")


            price_app = FastAPI()


            @price_app.get("/price")
            def price(rate: Annotated[float, Depends(get_exchange_rate)]) -> dict[str, float]:
                """100 INR in EUR."""
                return {"eur": round(100 * rate, 2)}


            price_app.dependency_overrides[get_exchange_rate] = lambda: 0.011
            with TestClient(price_app) as client:
                print("with the override   :", client.get("/price").json())
            price_app.dependency_overrides.clear()
            with TestClient(price_app, raise_server_exceptions=False) as client:
                print("without the override:", client.get("/price").status_code)
            '''
        ),
    ]


def _database_test_cells() -> list[NotebookNode]:
    """6.7.2 Database tests."""
    return [
        md(
            """
            ### 6.7.2 Database tests

            | Strategy | Speed | Realism | Notes |
            | --- | --- | --- | --- |
            | SQLite file per test (`create_all`) | fast | dialect differences (no `ILIKE`, no `FOR UPDATE`, no trigram) | the Notes API's default fixtures |
            | **Real PostgreSQL** (testcontainers or CI service) | slower to start, then fast | the production dialect | start once per session |
            | Truncate between tests | medium | real commits | needed when code commits on other connections |
            | **Rollback-per-test** | fastest per test | real database, but one transaction | the app's commits become savepoints |
            | Template database (`CREATE DATABASE ... TEMPLATE`) | fast | full isolation | good for parallel workers |

            **Rollback-per-test**: open a connection, begin a transaction, give the code under
            test a session bound to that connection with
            `join_transaction_mode="create_savepoint"`, and roll back at the end. The code may
            call `commit()`: it only releases a savepoint. Two "tests" on the unit's PostgreSQL
            container:
            """
        ),
        code(
            r'''
            class DemoBase(DeclarativeBase):
                """Tables for the database-test demos."""


            class Ticket(DemoBase):
                """A support ticket."""

                __tablename__ = "demo_tickets"
                id: Mapped[int] = mapped_column(primary_key=True)
                title: Mapped[str] = mapped_column(sa.String(100))


            PG_URL = start_shared_postgres()
            print(
                "PostgreSQL:",
                "testcontainer started" if PG_URL else "SKIP (no Docker): the rollback demo needs PostgreSQL",
            )
            if PG_URL:
                demo_engine = create_async_engine(PG_URL, poolclass=NullPool)
                async with demo_engine.begin() as connection:
                    await connection.run_sync(DemoBase.metadata.drop_all)
                    await connection.run_sync(DemoBase.metadata.create_all)
            '''
        ),
        md("The fixture, as a context manager, and two tests that each insert a row and commit:"),
        code(
            r'''
            @contextlib.asynccontextmanager
            async def rolled_back_session() -> AsyncIterator[AsyncSession]:
                """A session whose commits are savepoints in a transaction that is rolled back."""
                async with demo_engine.connect() as connection:
                    transaction = await connection.begin()
                    session = AsyncSession(bind=connection, join_transaction_mode="create_savepoint")
                    try:
                        yield session
                    finally:
                        await session.close()
                        await transaction.rollback()


            async def ticket_count(source: Any) -> int:
                """Rows in demo_tickets, as seen by an engine or a session."""
                return (await source.execute(sa.select(sa.func.count()).select_from(Ticket))).scalar_one()


            if PG_URL:
                for test_number in (1, 2):
                    async with rolled_back_session() as session:
                        before = await ticket_count(session)
                        session.add(Ticket(title=f"from test {test_number}"))
                        await session.commit()  # the code under test commits
                        inside = await ticket_count(session)
                    async with demo_engine.connect() as connection:
                        after = await ticket_count(connection)
                    print(
                        f"test {test_number}: {before} row(s) at the start, "
                        f"{inside} after its commit, {after} after the rollback"
                    )
            '''
        ),
        md(
            """
            Each test starts from zero although each one committed. The Notes API's
            `test_postgres_rollback.py` does the same for the whole app through `AsyncClient`
            (an asyncpg connection belongs to the event loop that opened it, so `TestClient`,
            with its own loop, cannot share it).

            **Factories** create valid objects with unique defaults, so a test states only what
            it is about. `factory_boy` and `polyfactory` are the libraries; the idea fits in a
            few lines:
            """
        ),
        code(
            r'''
            class TicketFactory:
                """Valid tickets with unique titles; override any field."""

                sequence = itertools.count(1)

                @classmethod
                def build(cls, **overrides: Any) -> Ticket:
                    """A new, unsaved ticket."""
                    return Ticket(**({"title": f"Ticket {next(cls.sequence)}"} | overrides))


            print(
                [TicketFactory.build().title for _ in range(3)],
                TicketFactory.build(title="Printer on fire").title,
            )
            for package in ("factory", "polyfactory"):
                installed = importlib.util.find_spec(package) is not None
                availability = "installed" if installed else "not installed (optional here)"
                print(f"{package}: {availability}")
            '''
        ),
    ]


def _external_service_cells() -> list[NotebookNode]:
    """6.7.3 External services."""
    return [
        md(
            """
            ### 6.7.3 External services

            Tests must not call real third-party services: they are slow, flaky, cost money and
            can have side effects. httpx accepts a **transport**; `httpx.MockTransport(handler)`
            answers every request with a function you write:
            """
        ),
        code(
            r'''
            def fake_weather(request: httpx.Request) -> httpx.Response:
                """A whole weather API in one function."""
                if request.url.path != "/now":
                    return httpx.Response(404)
                return httpx.Response(200, json={"city": request.url.params["q"], "celsius": 21})


            with httpx.Client(
                transport=httpx.MockTransport(fake_weather), base_url="https://weather.example"
            ) as weather:
                print(weather.get("/now", params={"q": "Pune"}).json(), weather.get("/forecast").status_code)
            '''
        ),
        md(
            """
            `respx` patches httpx globally (so code that creates its own client is covered too),
            matches routes, returns sequences of responses and records the calls for assertions.
            Here a retrying caller meets a 503 first:
            """
        ),
        code(
            r'''
            def temperature_with_retry(client: httpx.Client, attempts: int = 3) -> float:
                """Retry on 5xx (the code under test)."""
                for _ in range(attempts):
                    reply = client.get("https://weather.example/now", params={"q": "Pune"})
                    if reply.status_code < 500:
                        return reply.json()["celsius"]
                raise RuntimeError("weather service down")


            with respx.mock(assert_all_called=True) as mock:
                route = mock.get("https://weather.example/now").mock(
                    side_effect=[httpx.Response(503), httpx.Response(200, json={"celsius": 21})]
                )
                with httpx.Client() as client:
                    print("temperature:", temperature_with_retry(client))
                print("calls:", route.call_count, "| last query:", route.calls.last.request.url.query.decode())
            '''
        ),
        md(
            """
            **WebSockets, jobs and streams.** WebSockets go through `TestClient.websocket_connect`;
            an ARQ job is an async function, so call it with a fake `ctx`; a stream is read line
            by line with `client.stream()`:
            """
        ),
        code(
            r'''
            realtime_app = FastAPI()


            @realtime_app.websocket("/ws")
            async def echo_once(websocket: WebSocket) -> None:
                """Echo one message as JSON, then close."""
                await websocket.accept()
                await websocket.send_json({"echo": await websocket.receive_text()})
                await websocket.close()


            @realtime_app.get("/events")
            async def events() -> StreamingResponse:
                """Three SSE events."""

                async def stream() -> AsyncIterator[str]:
                    """The event stream."""
                    for number in range(3):
                        yield f"data: {number}\n\n"

                return StreamingResponse(stream(), media_type="text/event-stream")


            async def send_receipt(ctx: dict[str, Any], order_id: int) -> str:
                """An ARQ task."""
                await ctx["redis"].rpush("receipts", order_id)
                return "sent"
            '''
        ),
        md("The three tests:"),
        code(
            r"""
            with TestClient(realtime_app) as client:
                with client.websocket_connect("/ws") as websocket:
                    websocket.send_text("hello")
                    print("websocket:", websocket.receive_json())
                with client.stream("GET", "/events") as response:
                    print("stream   :", [line for line in response.iter_lines() if line])
            job_ctx = {"redis": fakeredis.FakeAsyncRedis(decode_responses=True), "job_try": 1}
            print(
                "job      :", await send_receipt(job_ctx, 42), await job_ctx["redis"].lrange("receipts", 0, -1)
            )
            """
        ),
    ]


def _contract_cells() -> list[NotebookNode]:
    """6.7.4 Contract and fuzz testing."""
    return [
        md(
            """
            ### 6.7.4 Contract and fuzz testing

            Example-based tests check the cases you thought of. **Schemathesis** reads the
            OpenAPI schema and generates requests from it (Hypothesis does the generating and
            shrinks failures to a minimal example), then checks every response against the
            schema: no 5xx, documented status codes and content types, bodies matching the
            response models, invalid input rejected. An inventory API with two bugs a happy-path
            test would miss:
            """
        ),
        code(
            r'''
            class Item(BaseModel):
                """An item in stock."""

                name: str = Field(min_length=1, max_length=50)
                quantity: int = Field(ge=0, le=1000)


            inventory_app = FastAPI()
            STOCK: dict[int, Item] = {}


            @inventory_app.post("/items", status_code=201, response_model=Item)
            def add_item(item: Item) -> Item:
                """Store an item (bug: crashes for quantity 0)."""
                if 1000 // item.quantity < 1:  # "units per crate": ZeroDivisionError -> 500
                    raise HTTPException(422, "too many units")
                STOCK[len(STOCK) + 1] = item
                return item


            @inventory_app.get("/items/{item_id}", response_model=Item)
            def get_item(item_id: int) -> Item:
                """One item (bug: an unknown id is a KeyError -> 500, not a 404)."""
                return STOCK[item_id]
            '''
        ),
        md(
            "`fuzz(app)` runs Schemathesis over every operation (a fixed seed, so the run is repeatable) and collects the distinct failures:"
        ),
        code(
            r'''
            def failure_titles(error: BaseException) -> set[str]:
                """The titles of Schemathesis failures inside (possibly nested) exception groups."""
                if isinstance(error, BaseExceptionGroup):
                    return set().union(*(failure_titles(inner) for inner in error.exceptions))
                return {getattr(error, "title", type(error).__name__)}


            def fuzz(app: FastAPI, max_examples: int = 30) -> list[str]:
                """Distinct 'METHOD /path: failure' lines found by Schemathesis."""
                schema = schemathesis.openapi.from_dict(app.openapi())
                found: set[str] = set()
                with TestClient(app, raise_server_exceptions=False) as client:
                    for operation in (result.ok() for result in schema.get_all_operations()):

                        @given(case=operation.as_strategy())
                        @hypothesis_settings(
                            max_examples=max_examples,
                            deadline=None,
                            derandomize=True,
                            database=None,
                            suppress_health_check=list(HealthCheck),
                            verbosity=Verbosity.quiet,
                        )
                        def check(case: Any) -> None:
                            """One generated request, validated against the schema."""
                            case.validate_response(
                                client.request(**case.as_transport_kwargs(base_url=str(client.base_url)))
                            )

                        try:
                            check()
                        except (Exception, BaseExceptionGroup) as error:  # FailureGroup is a BaseExceptionGroup
                            found |= {
                                f"{operation.method.upper()} {operation.path}: {title}"
                                for title in failure_titles(error)
                            }
                return sorted(found)


            print(*fuzz(inventory_app), sep="\n")
            '''
        ),
        md(
            """
            (Schemathesis reports failures as a `FailureGroup`, a `BaseExceptionGroup`: a plain
            `except Exception` does not catch it.) Both bugs surface as server errors, with no
            test written by hand for either. The
            Notes API's contract test found five real mismatches this way (see the v6 section):
            undocumented `application/problem+json` errors, nullable PATCH fields the validator
            rejected, `"pinned": 0` accepted as a boolean, `/notes/feed` shadowed by
            `/notes/{note_id}`, and a 500 for ids beyond PostgreSQL's `INTEGER`.

            **OpenAPI snapshot tests** freeze the public contract: the test compares the current
            document with a committed copy, so any change (a renamed field, a tightened limit)
            fails until someone reviews and re-records it. Suppose a teammate lowers the
            quantity limit; the diff is what a reviewer sees:
            """
        ),
        code(
            r"""
            snapshot_text = json.dumps(inventory_app.openapi(), indent=2, sort_keys=True)
            current = json.loads(snapshot_text)
            current["components"]["schemas"]["Item"]["properties"]["quantity"]["maximum"] = 500  # the change
            current_text = json.dumps(current, indent=2, sort_keys=True)
            diff = difflib.unified_diff(
                snapshot_text.splitlines(), current_text.splitlines(), "snapshot", "current", lineterm="", n=2
            )
            print("\n".join(diff))
            print("snapshot test passes:", snapshot_text == current_text)
            """
        ),
    ]


def _observability_cells() -> list[NotebookNode]:
    """6.7.5 Observability fundamentals."""
    return [
        md(
            """
            ### 6.7.5 Observability fundamentals

            Observability is being able to answer new questions about a running system from
            the data it emits. Three kinds of telemetry:

            | Signal | What it is | Good for | Cost |
            | --- | --- | --- | --- |
            | **Logs** | timestamped events (one JSON object per line) | what happened to *this* request | volume: sample or drop debug in production |
            | **Metrics** | numbers aggregated over time (counters, gauges, histograms) | trends, alerts, dashboards | cheap, if label values stay few |
            | **Traces** | a tree of timed spans across services for one request | where the time went | sampling keeps it affordable |

            The request id and the trace id **link** them: from an alert (metric) to the slow
            traces to the log lines of one request.

            **SLI / SLO / error budget.** A *service level indicator* is a measured ratio (good
            events / all events), e.g. "requests answered without 5xx in under 200 ms"; the
            *objective* is its target over a window (99.5 % over 30 days); the *error budget* is
            what the objective allows to go wrong. Measured on a seeded sample of request
            records:
            """
        ),
        code(
            r'''
            rng = random.Random(42)
            REQUESTS = [  # (latency in ms, status) for 10 000 requests
                (rng.lognormvariate(math.log(40), 0.6), 500 if rng.random() < 0.002 else 200)
                for _ in range(10_000)
            ]
            SLO_TARGET, LATENCY_LIMIT_MS = 0.995, 200


            def sli(records: list[tuple[float, int]]) -> float:
                """Fraction of good requests: no server error and fast enough."""
                good = sum(1 for latency, code in records if code < 500 and latency < LATENCY_LIMIT_MS)
                return good / len(records)


            measured = sli(REQUESTS)
            budget = (1 - SLO_TARGET) * len(REQUESTS)  # requests allowed to be bad
            spent = len(REQUESTS) - round(measured * len(REQUESTS))
            print(f"SLI {measured:.4f} vs SLO {SLO_TARGET}: {'met' if measured >= SLO_TARGET else 'MISSED'}")
            print(f"error budget: {budget:.0f} bad requests allowed, {spent} spent ({spent / budget:.0%})")
            print(f"30-day budget at 99.9 %: {30 * 24 * 60 * 0.001:.1f} minutes of full outage")
            '''
        ),
        md(
            """
            Two checklists for what to measure:

            | **RED** (for every service / endpoint) | **USE** (for every resource) |
            | --- | --- |
            | **R**ate: requests per second | **U**tilization: share of time busy (CPU, pool connections in use) |
            | **E**rrors: failed requests per second | **S**aturation: work waiting (queue length, tasks waiting for a connection) |
            | **D**uration: latency distribution (p50, p95, p99) | **E**rrors: resource errors (timeouts, refused connections) |

            RED from the records above, and USE for a pool of 5 database connections with 8
            requests competing for it (a semaphore stands in for the pool):
            """
        ),
        code(
            r'''
            latencies = sorted(latency for latency, _ in REQUESTS)
            percentile = statistics.quantiles(latencies, n=100)
            errors = sum(1 for _, code in REQUESTS if code >= 500)
            print(
                f"RED: rate {len(REQUESTS) / 600:.1f} req/s over 10 min, errors {errors / 600:.3f}/s, "
                f"p50 {percentile[49]:.0f} ms, p95 {percentile[94]:.0f} ms, p99 {percentile[98]:.0f} ms"
            )


            async def use_of_a_pool(pool_size: int = 5, requests: int = 8) -> None:
                """Utilization and saturation of a connection pool under load."""
                pool, in_use, waiting, peak = (
                    asyncio.Semaphore(pool_size),
                    [0],
                    [0],
                    {"in_use": 0, "waiting": 0},
                )

                async def handle() -> None:
                    """One request holding a connection for 50 ms."""
                    waiting[0] += 1
                    peak["waiting"] = max(peak["waiting"], waiting[0] - (pool_size - in_use[0]))
                    async with pool:
                        waiting[0] -= 1
                        in_use[0] += 1
                        peak["in_use"] = max(peak["in_use"], in_use[0])
                        await asyncio.sleep(0.05)
                        in_use[0] -= 1

                await asyncio.gather(*(handle() for _ in range(requests)))
                print(
                    f"USE: utilization {peak['in_use']}/{pool_size} connections, "
                    f"saturation: {peak['waiting']} requests waited, errors: 0"
                )


            await use_of_a_pool()
            '''
        ),
    ]


def _structured_logging_cells() -> list[NotebookNode]:
    """6.7.6 Structured logging."""
    return [
        md(
            """
            ### 6.7.6 Structured logging

            A log line is for machines first: one JSON object with fixed keys, so the log store
            can filter (`status >= 500`), group (`by route`) and join (`request_id`). structlog
            builds each event as a dict and passes it through a chain of **processors**; the
            last one renders it:
            """
        ),
        code(
            r"""
            log_buffer = io.StringIO()
            structlog.configure(
                processors=[
                    structlog.contextvars.merge_contextvars,
                    structlog.processors.add_log_level,
                    structlog.processors.TimeStamper(fmt="iso", utc=True),
                    structlog.processors.JSONRenderer(),
                ],
                logger_factory=structlog.PrintLoggerFactory(file=log_buffer),
                cache_logger_on_first_use=False,
            )
            demo_log = structlog.get_logger()
            demo_log.info("note created", note_id=42, owner_id=7, duration_ms=12.5)
            demo_log.warning("cache miss", key="notes:v5:note:42")
            for line in log_buffer.getvalue().splitlines():
                print(re.sub(r'"timestamp": "[^"]+"', '"timestamp": "<now>"', line))
            """
        ),
        md(
            """
            **Under the hood: a processor is any callable `(logger, method_name, event_dict)`.**
            `structlog.get_config()` returns the chain just configured; `inspect` shows what
            each entry is (a plain function or an instance with `__call__`), its signature and
            where it is defined:
            """
        ),
        code(
            r"""
            chain = structlog.get_config()["processors"]
            for position, processor in enumerate(chain, start=1):
                is_function = inspect.isfunction(processor)
                kind = "function" if is_function else f"{type(processor).__name__} instance"
                source_file = Path(inspect.getfile(processor if is_function else type(processor)))
                where = f"{source_file.parent.name}/{source_file.name}"
                print(f"{position}. {kind:30} {inspect.signature(processor)}  ({where})")
            """
        ),
        md(
            """
            So `log.info("note created", note_id=42)` is a fold over that list: the event dict
            goes through each processor in turn, and the last one turns it into the string the
            logger prints. Running the chain by hand shows each step:
            """
        ),
        code(
            r"""
            event: object = {"event": "note created", "note_id": 42}
            for processor in chain:
                event = processor(None, "info", event)
                name = getattr(processor, "__name__", type(processor).__name__)
                shown = re.sub(r"\d{4}-\d\d-\d\dT[\d:.]+Z", "<now>", repr(event))
                print(f"{name:20} -> {type(event).__name__:4} {shown}")
            """
        ),
        md(
            """
            **Request ids.** `bind_contextvars()` stores values in a `ContextVar`, so every log
            call during the same request (in any function, without passing a logger around)
            gets them; each asyncio task has its own context, so concurrent requests never mix
            their ids. A middleware binds the id and clears it afterwards:
            """
        ),
        code(
            r'''
            correlated_app = FastAPI()


            @correlated_app.middleware("http")
            async def bind_request_id(request: Request, call_next: Callable) -> Response:
                """Bind a request id for every log line of this request."""
                request_id = request.headers.get("X-Request-ID") or secrets.token_hex(8)
                structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
                try:
                    response = await call_next(request)
                finally:
                    structlog.contextvars.clear_contextvars()
                response.headers["X-Request-ID"] = request_id
                return response


            @correlated_app.post("/orders")
            async def place_order() -> dict[str, str]:
                """Two log lines deep inside the request handling."""
                demo_log.info("order validated")
                demo_log.info("order stored", order_id=1001)
                return {"status": "ok"}


            log_buffer.truncate(0)
            log_buffer.seek(0)
            with TestClient(correlated_app) as client:
                client.post("/orders", headers={"X-Request-ID": "req-aaa"})
                client.post("/orders", headers={"X-Request-ID": "req-bbb"})
            print(
                *[
                    {key: entry[key] for key in ("event", "request_id")}
                    for entry in map(json.loads, log_buffer.getvalue().splitlines())
                ],
                sep="\n",
            )
            '''
        ),
        md(
            """
            **Trace ids and redaction** are two more processors: one reads the current
            OpenTelemetry span, the other rewrites sensitive keys and secret-shaped values (the
            Notes API's `core/logging.py` has both, and also routes stdlib logging and Uvicorn
            through the same chain with `structlog.stdlib.ProcessorFormatter`):
            """
        ),
        code(
            r'''
            SENSITIVE = ("password", "token", "secret", "authorization")


            def add_trace_ids(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
                """Copy the active span's ids into the event."""
                span_context = trace.get_current_span().get_span_context()
                if span_context.is_valid:
                    event_dict["trace_id"] = format(span_context.trace_id, "032x")
                return event_dict


            def redact(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
                """Hide values of sensitive keys and anything that looks like a bearer token."""
                return {
                    key: "[REDACTED]"
                    if any(word in key.lower() for word in SENSITIVE)
                    else re.sub(r"(?i)bearer\s+\S+", "Bearer [REDACTED]", value)
                    if isinstance(value, str)
                    else value
                    for key, value in event_dict.items()
                }


            log_buffer.truncate(0)
            log_buffer.seek(0)
            structlog.configure(
                processors=[add_trace_ids, redact, structlog.processors.JSONRenderer()],
                logger_factory=structlog.PrintLoggerFactory(file=log_buffer),
            )
            tracer_for_logs = TracerProvider().get_tracer("demo")
            with tracer_for_logs.start_as_current_span("login"):
                structlog.get_logger().info(
                    "login attempt", email="asha@example.com", password="hunter2", header="Bearer abc.def"
                )
            print(log_buffer.getvalue().strip())
            structlog.reset_defaults()
            '''
        ),
    ]


def _metrics_cells() -> list[NotebookNode]:
    """6.7.7 Metrics."""
    return [
        md(
            """
            ### 6.7.7 Metrics

            | Type | Goes | Example | Query (PromQL) |
            | --- | --- | --- | --- |
            | **Counter** | only up (reset on restart) | `http_requests_total{route, status}` | `rate(http_requests_total[5m])` |
            | **Gauge** | up and down | `requests_in_progress`, `queue_length` | the value itself |
            | **Histogram** | counts per latency bucket, plus sum and count | `request_duration_seconds_bucket{le="0.2"}` | `histogram_quantile(0.95, rate(..._bucket[5m]))` |

            Each distinct label combination is a separate time series, so labels must take few
            values: a route **template** (`/notes/{note_id}`), never the raw path or a user id.
            Metrics in their own registry, and the text Prometheus scrapes:
            """
        ),
        code(
            r"""
            demo_registry = CollectorRegistry()
            requests_total = Counter(
                "demo_requests_total", "Requests.", ["route", "status"], registry=demo_registry
            )
            in_progress = Gauge("demo_requests_in_progress", "Requests being handled.", registry=demo_registry)
            latency = Histogram(
                "demo_request_seconds",
                "Latency.",
                ["route"],
                buckets=(0.05, 0.1, 0.2, 0.5, 1.0),
                registry=demo_registry,
            )

            for seconds in (0.03, 0.07, 0.12, 0.15, 0.4):
                requests_total.labels("/notes/{note_id}", "200").inc()
                latency.labels("/notes/{note_id}").observe(seconds)
            requests_total.labels("/notes/{note_id}", "404").inc()
            in_progress.inc(3)
            in_progress.dec()
            exposition = generate_latest(demo_registry).decode()
            print(
                "\n".join(
                    line
                    for line in exposition.splitlines()
                    if not line.startswith("#") and "_created" not in line
                )
            )
            """
        ),
        md(
            """
            Bucket counts are **cumulative** (`le` = less than or equal). Prometheus estimates
            quantiles from them by linear interpolation inside the bucket that contains the
            quantile: cheap and mergeable across processes, but only as precise as the buckets
            (so put bucket edges around your SLO threshold). The estimate versus the exact
            value for the 10 000 latencies of 6.7.5:
            """
        ),
        code(
            r'''
            def histogram_quantile(quantile: float, buckets: list[tuple[float, int]]) -> float:
                """Prometheus's estimate from cumulative (upper bound, count) buckets."""
                total = buckets[-1][1]
                rank, lower_bound, lower_count = quantile * total, 0.0, 0
                for upper_bound, count in buckets:
                    if count >= rank:
                        return lower_bound + (upper_bound - lower_bound) * (rank - lower_count) / (
                            count - lower_count
                        )
                    lower_bound, lower_count = upper_bound, count
                return buckets[-1][0]


            edges = [10, 25, 50, 100, 150, 200, 300, 500, 1000, 5000]
            cumulative = [(edge, sum(1 for value in latencies if value <= edge)) for edge in edges]
            print(
                f"p95 estimated from buckets: {histogram_quantile(0.95, cumulative):.1f} "
                f"ms, exact: {percentile[94]:.1f} ms"
            )
            '''
        ),
        md(
            """
            **Multiprocess mode.** With `uvicorn --workers 2` each process has its own counters,
            and a scrape reaches only one of them. `prometheus_client`'s multiprocess mode makes
            every process write its values to files in `PROMETHEUS_MULTIPROC_DIR`, and
            `MultiProcessCollector` adds them up at scrape time. A demo app served twice by two
            workers, without and with the directory:
            """
        ),
        code(
            r'''
            %%writefile _scratch/phase6/metrics_demo.py
            """Counting requests across Uvicorn worker processes."""

            import os

            from fastapi import FastAPI, Response
            from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, generate_latest
            from prometheus_client.multiprocess import MultiProcessCollector

            app = FastAPI()
            REGISTRY = CollectorRegistry()
            HITS = Counter("demo_hits_total", "Hits on /hit.", registry=REGISTRY)


            @app.get("/health")
            def health() -> dict[str, int]:
                """Liveness, and which process answered."""
                return {"pid": os.getpid()}


            @app.get("/hit")
            def hit() -> dict[str, int]:
                """Count a hit in this process."""
                HITS.inc()
                return {"pid": os.getpid()}


            @app.get("/metrics")
            def metrics() -> Response:
                """This process's counters, or every process's in multiprocess mode."""
                registry = REGISTRY
                if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
                    registry = CollectorRegistry()
                    MultiProcessCollector(registry)
                return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
            '''
        ),
        md("Forty hits on fresh connections (so both workers get some), then three scrapes:"),
        code(
            r'''
            def scrape_counts(extra_env: dict[str, str]) -> tuple[int, list[float]]:
                """Serve with 2 workers; return how many processes answered and three scraped totals."""
                with uvicorn_server(
                    "metrics_demo:app", extra_args=["--workers", "2"], extra_env=extra_env
                ) as base_url:
                    with httpx.Client(
                        base_url=base_url, trust_env=False, limits=httpx.Limits(max_keepalive_connections=0)
                    ) as client:
                        pids = {client.get("/hit").json()["pid"] for _ in range(40)}
                        totals = []
                        for _ in range(3):
                            line = next(
                                row
                                for row in client.get("/metrics").text.splitlines()
                                if row.startswith("demo_hits_total")
                            )
                            totals.append(float(line.split()[-1]))
                return len(pids), totals


            multiproc_dir = PHASE6_DIR / "prometheus_multiproc"
            shutil.rmtree(multiproc_dir, ignore_errors=True)
            multiproc_dir.mkdir()
            print("one registry per process:", scrape_counts({}))
            print("multiprocess mode       :", scrape_counts({"PROMETHEUS_MULTIPROC_DIR": str(multiproc_dir)}))
            '''
        ),
        md(
            """
            Without the directory each scrape reports one worker's share (and which one is
            random); with it every scrape reports all 40. The directory must be empty when the
            server starts (the Notes API image mounts a fresh `tmpfs` there). Gauges need a
            `multiprocess_mode` (`livesum`, `max`, ...) to say how to combine processes.
            """
        ),
    ]


def _tracing_cells() -> list[NotebookNode]:
    """6.7.8 Tracing."""
    return [
        md(
            """
            ### 6.7.8 Tracing

            A **trace** is one request's journey; it is a tree of **spans** (an operation with
            a start, an end, attributes and a status). OpenTelemetry (OTel) is the vendor-neutral
            standard: the API creates spans, the SDK processes and exports them (to Jaeger,
            Tempo, Honeycomb, Datadog...). Manual spans with an in-memory exporter:
            """
        ),
        code(
            r"""
            span_exporter = InMemorySpanExporter()
            provider = TracerProvider(resource=Resource.create({"service.name": "demo-api"}))
            provider.add_span_processor(SimpleSpanProcessor(span_exporter))
            demo_tracer = provider.get_tracer("demo")

            with demo_tracer.start_as_current_span("GET /notes/{note_id}") as request_span:
                request_span.set_attribute("http.route", "/notes/{note_id}")
                with demo_tracer.start_as_current_span("cache.get") as cache_span:
                    cache_span.set_attribute("cache.hit", False)
                with demo_tracer.start_as_current_span("db.query") as query_span:
                    query_span.add_event("rows fetched", {"rows": 1})

            for finished in span_exporter.get_finished_spans():
                parent = finished.parent.span_id if finished.parent else None
                print(
                    f"{finished.name:22} trace={format(finished.context.trace_id, '032x')[:8]}... "
                    f"parent={'-' if parent is None else format(parent, '016x')[:6]} "
                    f"attrs={dict(finished.attributes)}"
                )
            """
        ),
        md(
            """
            **Auto-instrumentation** creates the server spans for you:
            `FastAPIInstrumentor.instrument_app(app, tracer_provider=...)` wraps the app in
            OpenTelemetry's ASGI middleware (one SERVER span per request, named after the route
            template, plus small spans for sending the response). **Propagation** continues a
            trace across services: the caller injects a W3C `traceparent` header, the callee's
            instrumentation reads it. A frontend calling a backend:
            """
        ),
        code(
            r'''
            span_exporter.clear()
            backend_app, frontend_app = FastAPI(), FastAPI()


            @backend_app.get("/stock/{sku}")
            async def stock(sku: str) -> dict[str, object]:
                """The downstream service."""
                return {"sku": sku, "available": 3}


            @frontend_app.get("/products/{sku}")
            async def product(sku: str) -> dict[str, object]:
                """Call the backend, passing the trace context along."""
                headers: dict[str, str] = {}
                propagate.inject(headers)  # adds traceparent: 00-<trace id>-<span id>-01
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=backend_app), base_url="http://backend"
                ) as backend:
                    return (await backend.get(f"/stock/{sku}", headers=headers)).json() | {
                        "traceparent": headers["traceparent"][:20] + "..."
                    }


            for instrumented in (backend_app, frontend_app):
                FastAPIInstrumentor.instrument_app(instrumented, tracer_provider=provider)
            with TestClient(frontend_app) as client:
                print(client.get("/products/tea-001").json())
            request_spans = [
                span for span in span_exporter.get_finished_spans() if "http send" not in span.name
            ]
            print(
                [
                    (span.name, span.kind.name, format(span.context.trace_id, "032x")[:8])
                    for span in request_spans
                ]
            )
            '''
        ),
        md(
            """
            One trace id for both services: the backend's span is a child of the frontend's. (It
            is `INTERNAL` here because both apps run in one process, where the frontend's span
            is already current; in a separate process the backend's span is a `SERVER` span
            whose parent arrived in the `traceparent` header.)
            **Exporters** send finished spans somewhere. `ConsoleSpanExporter` prints them (for
            debugging); `BatchSpanProcessor` + the **OTLP** exporter is the production setup,
            usually to an OpenTelemetry Collector. One span on the console:
            """
        ),
        code(
            r"""
            console_output = io.StringIO()
            console_provider = TracerProvider(resource=Resource.create({"service.name": "demo-api"}))
            console_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter(out=console_output)))
            with console_provider.get_tracer("demo").start_as_current_span("checkout") as checkout_span:
                checkout_span.set_attribute("order.items", 3)
            printed = json.loads(console_output.getvalue())
            print(
                {key: printed[key] for key in ("name", "kind", "attributes")},
                printed["resource"]["attributes"]["service.name"],
            )
            """
        ),
        md(
            """
            And OTLP for real: a Jaeger container (it accepts OTLP over HTTP on port 4318 and
            has a query API on 16686). The notebook exports a small trace and asks Jaeger for it,
            then removes the container. Without Docker the cell prints a skip message:
            """
        ),
        code(
            r'''
            def jaeger_round_trip() -> None:
                """Export spans over OTLP/HTTP to Jaeger, then read the trace back from its API."""
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                from testcontainers.core.container import DockerContainer

                with DockerContainer("jaegertracing/all-in-one:1.62.0").with_exposed_ports(
                    4318, 16686
                ) as jaeger:
                    host = jaeger.get_container_host_ip()
                    query = f"http://{host}:{jaeger.get_exposed_port(16686)}"
                    for _ in range(60):
                        with contextlib.suppress(httpx.TransportError):
                            if httpx.get(f"{query}/api/services", timeout=1).status_code == 200:
                                break
                        time.sleep(0.5)
                    otlp_provider = TracerProvider(resource=Resource.create({"service.name": "notes-demo"}))
                    exporter = OTLPSpanExporter(
                        endpoint=f"http://{host}:{jaeger.get_exposed_port(4318)}/v1/traces"
                    )
                    otlp_provider.add_span_processor(SimpleSpanProcessor(exporter))
                    with otlp_provider.get_tracer("demo").start_as_current_span("GET /api/v1/notes"):
                        with otlp_provider.get_tracer("demo").start_as_current_span("db.query"):
                            time.sleep(0.01)
                    otlp_provider.shutdown()
                    for _ in range(20):
                        traces = httpx.get(
                            f"{query}/api/traces", params={"service": "notes-demo"}, timeout=2
                        ).json()["data"]
                        if traces:
                            break
                        time.sleep(0.5)
                    print("Jaeger stored:", sorted(span["operationName"] for span in traces[0]["spans"]))


            if HAS_DOCKER:
                jaeger_round_trip()
            else:
                print("SKIP the OTLP export: no Docker for the Jaeger container")
            '''
        ),
    ]


def _error_tracking_cells() -> list[NotebookNode]:
    """6.7.9 Error tracking and health checks."""
    return [
        md(
            """
            ### 6.7.9 Error tracking and health checks

            **Sentry** groups exceptions into issues, with stack traces, request data, release
            and environment, and alerts on new ones. `sentry_sdk.init(dsn=...)` enables the
            FastAPI/Starlette integration automatically. The SDK sends events through a
            *transport*; here a capturing transport keeps them in memory (no network). First a
            `before_send` hook that removes credentials, and an app whose route crashes:
            """
        ),
        code(
            r'''
            def scrub_credentials(sentry_event: Any, _hint: Any) -> Any:
                """before_send: never ship credentials."""
                headers = sentry_event.get("request", {}).get("headers", {})
                for name in list(headers):
                    if name.lower() in ("authorization", "cookie"):
                        headers[name] = "[REDACTED]"
                return sentry_event


            def build_crash_app() -> FastAPI:
                """An app whose only route has a bug."""
                crash_app = FastAPI()

                @crash_app.get("/boom")
                def boom() -> None:
                    """A bug."""
                    raise ValueError("cannot divide the bill by zero people")

                return crash_app
            '''
        ),
        md("The demo: a capturing transport, then one crashing request with a token in it:"),
        code(
            r'''
            def sentry_demo() -> list[dict[str, Any]]:
                """Capture the events of one crashing request; scrub the Authorization header."""
                import sentry_sdk
                from sentry_sdk.transport import Transport

                class CapturingTransport(Transport):
                    """Keep events instead of sending them."""

                    def __init__(self) -> None:
                        """Start empty."""
                        super().__init__()
                        self.events: list[dict[str, Any]] = []

                    def capture_envelope(self, envelope: Any) -> None:
                        """Store each event."""
                        if (captured := envelope.get_event()) is not None:
                            self.events.append(captured)

                transport = CapturingTransport()
                sentry_sdk.init(
                    dsn="https://public@sentry.example/1",
                    transport=transport,
                    before_send=scrub_credentials,
                    environment="demo",
                )
                with TestClient(build_crash_app(), raise_server_exceptions=False) as client:
                    client.get("/boom", headers={"Authorization": "Bearer secret.token.value"})
                sentry_sdk.flush()
                sentry_sdk.init()  # back to a disabled client
                return transport.events
            '''
        ),
        md("What Sentry would have received:"),
        code(
            r"""
            if importlib.util.find_spec("sentry_sdk"):
                for captured in sentry_demo():
                    exception = captured["exception"]["values"][-1]
                    print(
                        exception["type"],
                        "-",
                        exception["value"],
                        "| url:",
                        captured["request"]["url"],
                        "| Authorization:",
                        captured["request"]["headers"].get(
                            "Authorization", captured["request"]["headers"].get("authorization")
                        ),
                    )
            else:
                print("SKIP the Sentry demo: sentry-sdk is not installed")
            """
        ),
        md(
            """
            **Health checks** answer three different questions; mixing them up causes outages
            (a liveness probe that checks the database restarts every API process when the
            database blips):

            | Probe | Question | Checks | On failure the orchestrator | Notes API v6 |
            | --- | --- | --- | --- | --- |
            | **Liveness** | is the process stuck? | nothing external | restarts the container | `/health/live` |
            | **Readiness** | can it serve traffic now? | database, Redis (with timeouts) | stops routing traffic (no restart) | `/health/ready` |
            | **Startup** | has it finished starting? | schema at the right migration, warm-up done | keeps waiting; the other probes wait too | `/health/startup` |

            A tiny app whose dependencies can be switched off:
            """
        ),
        code(
            r'''
            dependency_up = {"database": True, "cache": True, "migrated": False}
            probe_app = FastAPI()


            @probe_app.get("/live")
            def probe_live() -> dict[str, str]:
                """Never touches a dependency."""
                return {"status": "ok"}


            @probe_app.get("/ready")
            def probe_ready(response: Response) -> dict[str, object]:
                """503 with the failing checks named."""
                checks = {name: "ok" if dependency_up[name] else "down" for name in ("database", "cache")}
                if "down" in checks.values():
                    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
                return {"checks": checks}


            @probe_app.get("/startup")
            def probe_startup(response: Response) -> dict[str, bool]:
                """503 until the migrations ran."""
                if not dependency_up["migrated"]:
                    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
                return {"migrated": dependency_up["migrated"]}


            with TestClient(probe_app) as client:
                for change in ({}, {"migrated": True}, {"cache": False}, {"cache": True}):
                    dependency_up.update(change)
                    print(
                        f"{str(change):20} live={client.get('/live').status_code} "
                        f"ready={client.get('/ready').status_code} startup={client.get('/startup').status_code}"
                    )
            '''
        ),
    ]


def _predict_cells() -> list[NotebookNode]:
    """Three predict-the-output questions for Unit 6.7."""
    return [
        md(
            """
            ### Predict the output — Unit 6.7

            Three questions about histograms, context variables and spans. Decide first, then
            run the proof.
            """
        ),
        *predict_cells(
            """
            registry = CollectorRegistry()
            seconds = Histogram("q_seconds", "Q.", buckets=(0.1, 0.5), registry=registry)
            seconds.observe(0.05)
            seconds.observe(0.3)
            exposition = generate_latest(registry).decode().splitlines()
            print([line.split()[-1] for line in exposition if "_bucket" in line])
            """,
            """
            `['1.0', '2.0', '2.0']`. Buckets are cumulative: `le="0.1"` counts the 0.05
            observation, `le="0.5"` counts both, and the automatic `le="+Inf"` bucket always
            equals the total count.
            """,
            r"""
            registry = CollectorRegistry()
            seconds = Histogram("q_seconds", "Q.", buckets=(0.1, 0.5), registry=registry)
            seconds.observe(0.05)
            seconds.observe(0.3)
            exposition = generate_latest(registry).decode().splitlines()
            print([line.split()[-1] for line in exposition if "_bucket" in line])
            """,
        ),
        *predict_cells(
            """
            structlog.contextvars.bind_contextvars(request_id="r-1")
            structlog.contextvars.clear_contextvars()
            structlog.contextvars.bind_contextvars(user="asha")
            print(structlog.contextvars.get_contextvars())
            """,
            """
            `{'user': 'asha'}`. `clear_contextvars()` removes everything bound so far, which is
            why the middleware calls it when a request ends: without it, a value could leak into
            the next request handled in the same context.
            """,
            r"""
            structlog.contextvars.bind_contextvars(request_id="r-1")
            structlog.contextvars.clear_contextvars()
            structlog.contextvars.bind_contextvars(user="asha")
            print(structlog.contextvars.get_contextvars())
            structlog.contextvars.clear_contextvars()
            """,
        ),
        *predict_cells(
            """
            outside = trace.get_current_span().get_span_context().is_valid
            with TracerProvider().get_tracer("q").start_as_current_span("work"):
                inside = trace.get_current_span().get_span_context().is_valid
            print(outside, inside)
            """,
            """
            `False True`. Outside any span the current span is a non-recording placeholder with
            an invalid context (so the log processor adds no trace id); inside
            `start_as_current_span` the new span is current.
            """,
            r"""
            outside = trace.get_current_span().get_span_context().is_valid
            with TracerProvider().get_tracer("q").start_as_current_span("work"):
                inside = trace.get_current_span().get_span_context().is_valid
            print(outside, inside)
            """,
        ),
    ]


LAB67_GIVEN_SOURCE = r'''
class CartLine(BaseModel):
    """One line of a shopping cart."""

    sku: str = Field(pattern=r"^[A-Z]{3}-[0-9]{3}$")
    quantity: int = Field(ge=1, le=99)


class CartSummary(BaseModel):
    """GET /carts/{cart_id}: how many lines."""

    lines: int


def build_buggy_shop() -> FastAPI:
    """A cart API with two contract bugs (exercise 2 finds them)."""
    carts: dict[int, list[CartLine]] = {1: []}
    shop = FastAPI()

    @shop.post("/carts/{cart_id}/lines", status_code=201, response_model=list[CartLine])
    def add_line(cart_id: int, line: CartLine) -> list[CartLine]:
        """Bug 1: an unknown cart is a KeyError (500)."""
        carts[cart_id].append(line)
        return carts[cart_id]

    @shop.get(
        "/carts/{cart_id}",
        responses={200: {"model": CartSummary}, 404: {"description": "No such cart"}},
    )
    def cart_summary(cart_id: int) -> JSONResponse:
        """Bug 2: "lines" is sent as a string, not the documented integer."""
        if cart_id not in carts:
            return JSONResponse({"detail": "no such cart"}, status_code=404)
        return JSONResponse({"lines": str(len(carts[cart_id]))})

    return shop

'''

LAB67_CLOCK_SOURCE = r'''
class LabClock:
    """A clock that only moves when told to (exercise 4)."""

    def __init__(self) -> None:
        """Start at zero."""
        self.now = 0.0

    def __call__(self) -> float:
        """The current time in seconds."""
        return self.now

    def advance(self, seconds: float) -> None:
        """Move forward."""
        self.now += seconds
'''


def _lab_setup_cells() -> list[NotebookNode]:
    """Lab 6.7 introduction and given code."""
    return [
        md(
            """
            ### Lab 6.7

            | Exercise | Syllabus item | You write |
            | --- | --- | --- |
            | 1 | Notes API v6: full test suite in CI with service containers | `build_ci_workflow()` |
            | 2 | A Schemathesis run | `contract_failures(app)`, `build_fixed_shop()` |
            | 3 | Correlated JSON logs | `configure_lab_logging(stream)`, `build_logged_app()` |
            | 4 | Latency histograms | `build_metrics_app(registry, clock)`, `bucket_counts`, `estimate_quantile` |
            | 5 | OpenTelemetry spans | `build_traced_app(provider)`, `outgoing_headers()` |
            | 6 | Health endpoints | `build_probe_app(checks, state)` |

            The *Notes API v6* section after the lab runs the real suite the way CI does. Given:
            a cart API with two contract bugs for exercise 2 (`CartLine`, `CartSummary`,
            `build_buggy_shop()`):
            """
        ),
        code(LAB67_GIVEN_SOURCE),
        md("And `LabClock` for exercise 4, a clock that only moves when told to:"),
        code(LAB67_CLOCK_SOURCE),
    ]


def _lab_exercise_1_cells() -> list[NotebookNode]:
    """Lab 6.7 exercise 1."""
    return [
        md(
            """
            #### Exercise 1 — The test suite in CI with service containers

            Write `build_ci_workflow() -> dict`, a GitHub Actions workflow (as the dict that
            `yaml.safe_dump` turns into the file) that runs the Notes API suite:

            - triggers: `push` and `pull_request`; `defaults.run.working-directory` is
              `projects/notes_api`;
            - one job `test` on an `ubuntu-*` runner with two **service containers**:
              `postgres` (image `postgres:18-alpine`, port `5432:5432`, a `pg_isready` health
              check in `options`, `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` in `env`)
              and `redis` (image `redis:7.4`, port `6379:6379`, a `redis-cli ping` health check);
            - job `env`: `NOTES_TEST_DATABASE_URL` (asyncpg URL to `localhost:5432`) and
              `NOTES_TEST_REDIS_URL` (`redis://localhost:6379/0`);
            - steps: `actions/checkout@...`, `astral-sh/setup-uv@...`, a step running exactly
              `uv sync --frozen`, and a step whose `run` invokes `pytest`.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            def build_ci_workflow() -> dict[str, Any]:
                """A workflow that tests against PostgreSQL and Redis service containers."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 1:"),
        code(
            r'''
            def ci_job() -> dict[str, Any]:
                """The test job of the student's workflow."""
                return build_ci_workflow()["jobs"]["test"]


            def ci_steps() -> list[dict[str, Any]]:
                """Its steps."""
                return ci_job()["steps"]
            '''
        ),
        md("The checks:"),
        code(
            r"""
            run_checks(
                [
                    ("triggers", lambda: {"push", "pull_request"} <= set(build_ci_workflow()["on"]), True),
                    (
                        "working directory",
                        lambda: build_ci_workflow()["defaults"]["run"]["working-directory"],
                        "projects/notes_api",
                    ),
                    ("Linux runner", lambda: ci_job()["runs-on"].startswith("ubuntu"), True),
                    (
                        "postgres service",
                        lambda: (
                            ci_job()["services"]["postgres"]["image"],
                            "pg_isready" in ci_job()["services"]["postgres"]["options"],
                        ),
                        ("postgres:18-alpine", True),
                    ),
                    (
                        "redis service",
                        lambda: (
                            ci_job()["services"]["redis"]["image"],
                            "redis-cli ping" in ci_job()["services"]["redis"]["options"],
                        ),
                        ("redis:7.4", True),
                    ),
                    (
                        "published ports",
                        lambda: (
                            ci_job()["services"]["postgres"]["ports"],
                            ci_job()["services"]["redis"]["ports"],
                        ),
                        (["5432:5432"], ["6379:6379"]),
                    ),
                ]
            )
            """
        ),
        md("More checks:"),
        code(
            r"""
            run_checks(
                [
                    (
                        "database url",
                        lambda: (
                            ci_job()["env"]["NOTES_TEST_DATABASE_URL"].startswith("postgresql+asyncpg://")
                            and "localhost:5432" in ci_job()["env"]["NOTES_TEST_DATABASE_URL"]
                        ),
                        True,
                    ),
                    ("redis url", lambda: ci_job()["env"]["NOTES_TEST_REDIS_URL"], "redis://localhost:6379/0"),
                    (
                        "checkout and uv",
                        lambda: [
                            any(step.get("uses", "").startswith(prefix) for step in ci_steps())
                            for prefix in ("actions/checkout@", "astral-sh/setup-uv@")
                        ],
                        [True, True],
                    ),
                    (
                        "frozen install, then pytest",
                        lambda: (
                            "uv sync --frozen" in [step.get("run") for step in ci_steps()],
                            any("pytest" in step.get("run", "") for step in ci_steps()),
                        ),
                        (True, True),
                    ),
                    (
                        "survives a YAML round trip",
                        lambda: yaml.safe_load(yaml.safe_dump(build_ci_workflow())) == build_ci_workflow(),
                        True,
                    ),
                ]
            )
            """
        ),
    ]


def _lab_exercise_2_cells() -> list[NotebookNode]:
    """Lab 6.7 exercise 2."""
    return [
        md(
            """
            #### Exercise 2 — A Schemathesis run

            - `contract_failures(app, max_examples=25) -> dict[str, set[str]]`: run Schemathesis
              over every operation of `app` (schema from `app.openapi()`, a `TestClient` with
              `raise_server_exceptions=False`, Hypothesis with `derandomize=True`,
              `database=None`, quiet verbosity). Return `{"METHOD /path": {failure titles}}`
              for operations that failed, nothing for those that passed. Remember that
              Schemathesis raises a `BaseExceptionGroup`.
            - `build_fixed_shop() -> FastAPI`: the same two operations as `build_buggy_shop()`
              without the bugs (404 problem for an unknown cart on both routes, documented in
              `responses`; `lines` as an integer). Its run must come back empty.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            def contract_failures(app: FastAPI, max_examples: int = 25) -> dict[str, set[str]]:
                """Failure titles per operation."""
                raise NotImplementedError


            def build_fixed_shop() -> FastAPI:
                """The cart API without its contract bugs."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 2 (each run takes a few seconds):"),
        code(
            r"""
            lab_buggy_failures: dict[str, set[str]] = {}
            lab_fixed_failures: dict[str, set[str]] | str = "not run"
            with contextlib.suppress(Exception):
                lab_buggy_failures = contract_failures(build_buggy_shop())
            with contextlib.suppress(Exception):
                lab_fixed_failures = contract_failures(build_fixed_shop())
            run_checks(
                [
                    (
                        "POST finds the server error",
                        lambda: "Server error" in lab_buggy_failures.get("POST /carts/{cart_id}/lines", set()),
                        True,
                    ),
                    (
                        "GET finds the schema violation",
                        lambda: (
                            "Response violates schema" in lab_buggy_failures.get("GET /carts/{cart_id}", set())
                        ),
                        True,
                    ),
                    (
                        "only the two buggy operations",
                        lambda: sorted(lab_buggy_failures),
                        ["GET /carts/{cart_id}", "POST /carts/{cart_id}/lines"],
                    ),
                    ("the fixed shop passes", lambda: lab_fixed_failures, {}),
                ]
            )
            """
        ),
    ]


def _lab_exercise_3_cells() -> list[NotebookNode]:
    """Lab 6.7 exercise 3."""
    return [
        md(
            """
            #### Exercise 3 — Correlated JSON logs

            - `configure_lab_logging(stream)`: configure structlog to write one JSON object per
              line to `stream`, with `merge_contextvars` and the log level (`"level"`).
            - `build_logged_app() -> FastAPI`: a middleware binds `request_id` (the incoming
              `X-Request-ID`, or a new `uuid.uuid4().hex`), `method` and `path` with
              `bind_contextvars`, logs `"request finished"` with `status` and `duration_ms`,
              returns the id in the `X-Request-ID` response header, and clears the context
              afterwards. `POST /notes` logs `"note created"` with `note_id=1` and returns 201.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            def configure_lab_logging(stream: io.StringIO) -> None:
                """structlog: JSON lines to stream, with context variables and the level."""
                raise NotImplementedError


            def build_logged_app() -> FastAPI:
                """An app whose log lines share the request id."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 3:"),
        code(
            r'''
            def logged_scenario() -> dict[str, Any]:
                """Two requests (one with an id), then a log line outside any request."""
                stream = io.StringIO()
                configure_lab_logging(stream)
                with TestClient(build_logged_app()) as client:
                    first = client.post("/notes", headers={"X-Request-ID": "req-123"})
                    second = client.post("/notes")
                structlog.get_logger().info("after the requests")
                lines = [json.loads(line) for line in stream.getvalue().splitlines()]
                structlog.reset_defaults()
                return {"lines": lines, "first": first, "second": second}


            lab_logged: dict[str, Any] = {}
            with contextlib.suppress(Exception):
                lab_logged = logged_scenario()
            '''
        ),
        md("The checks:"),
        code(
            r"""
            run_checks(
                [
                    (
                        "four request lines, one outside",
                        lambda: [line["event"] for line in lab_logged["lines"]],
                        [
                            "note created",
                            "request finished",
                            "note created",
                            "request finished",
                            "after the requests",
                        ],
                    ),
                    (
                        "the given id on both lines",
                        lambda: [line.get("request_id") for line in lab_logged["lines"][:2]],
                        ["req-123", "req-123"],
                    ),
                    (
                        "a generated id, echoed in the header",
                        lambda: (
                            lab_logged["lines"][2]["request_id"] == lab_logged["second"].headers["x-request-id"]
                            and len(lab_logged["lines"][2]["request_id"]) == 32
                        ),
                        True,
                    ),
                    (
                        "request line fields",
                        lambda: {
                            key: lab_logged["lines"][1][key] for key in ("method", "path", "status", "level")
                        },
                        {"method": "POST", "path": "/notes", "status": 201, "level": "info"},
                    ),
                ]
            )
            """
        ),
        md("More checks:"),
        code(
            r"""
            run_checks(
                [
                    (
                        "duration is a number",
                        lambda: isinstance(lab_logged["lines"][1]["duration_ms"], int | float),
                        True,
                    ),
                    (
                        "context cleared after the request",
                        lambda: "request_id" in lab_logged["lines"][-1],
                        False,
                    ),
                ]
            )
            """
        ),
    ]


def _lab_exercise_4_cells() -> list[NotebookNode]:
    """Lab 6.7 exercise 4."""
    return [
        md(
            """
            #### Exercise 4 — Latency histograms

            - `build_metrics_app(registry, clock) -> FastAPI`: a middleware times each request
              with `clock()` (not `time`), observes the histogram
              `lab_request_duration_seconds` (label `route`, buckets 0.05, 0.1, 0.25, 0.5, 1.0)
              and counts `lab_requests_total` (labels `route`, `status`), both in `registry`.
              The route label is the matched route's `path_format` (`/work/{ms}`), or
              `"unmatched"`. `GET /work/{ms}` calls `clock.advance(ms / 1000)`; `GET /metrics`
              returns `generate_latest(registry)` (and is itself not measured).
            - `bucket_counts(registry, route) -> list[tuple[float, int]]`: the cumulative
              `(upper bound, count)` pairs of that route, `+Inf` included as `math.inf`.
            - `estimate_quantile(quantile, buckets) -> float`: Prometheus's linear
              interpolation (as `histogram_quantile` in 6.7.7).
            """
        ),
        md("Your solution:"),
        code(
            r'''
            def build_metrics_app(registry: CollectorRegistry, clock: LabClock) -> FastAPI:
                """Measure every request with clock into registry."""
                raise NotImplementedError


            def bucket_counts(registry: CollectorRegistry, route: str) -> list[tuple[float, int]]:
                """Cumulative bucket counts of one route."""
                raise NotImplementedError


            def estimate_quantile(quantile: float, buckets: list[tuple[float, int]]) -> float:
                """The quantile estimated from cumulative buckets."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 4:"),
        code(
            r'''
            def histogram_scenario() -> dict[str, Any]:
                """Five requests of known durations, a 404, then the metrics."""
                registry, clock = CollectorRegistry(), LabClock()
                with TestClient(build_metrics_app(registry, clock)) as client:
                    for milliseconds in (30, 80, 120, 300, 700):
                        client.get(f"/work/{milliseconds}")
                    client.get("/nowhere")
                    text = client.get("/metrics").text
                return {"registry": registry, "text": text, "buckets": bucket_counts(registry, "/work/{ms}")}


            lab_histogram: dict[str, Any] = {}
            with contextlib.suppress(Exception):
                lab_histogram = histogram_scenario()
            EXPECTED_BUCKETS = [(0.05, 1), (0.1, 2), (0.25, 3), (0.5, 4), (1.0, 5), (math.inf, 5)]
            run_checks(
                [
                    ("cumulative buckets", lambda: lab_histogram["buckets"], EXPECTED_BUCKETS),
                    (
                        "route template, not the path",
                        lambda: (
                            'route="/work/{ms}"' in lab_histogram["text"]
                            and "/work/30" not in lab_histogram["text"]
                        ),
                        True,
                    ),
                    (
                        "404s are counted as unmatched",
                        lambda: (
                            'lab_requests_total{route="unmatched",status="404"} 1.0' in lab_histogram["text"]
                        ),
                        True,
                    ),
                    ("/metrics is not measured", lambda: 'route="/metrics"' in lab_histogram["text"], False),
                    ("median estimate", lambda: round(estimate_quantile(0.5, EXPECTED_BUCKETS), 4), 0.175),
                    ("p95 estimate", lambda: round(estimate_quantile(0.95, EXPECTED_BUCKETS), 4), 0.875),
                ]
            )
            '''
        ),
    ]


def _lab_exercise_5_cells() -> list[NotebookNode]:
    """Lab 6.7 exercise 5."""
    return [
        md(
            """
            #### Exercise 5 — OpenTelemetry spans

            - `build_traced_app(provider) -> FastAPI` with `GET /notes/{note_id}` (an `int`):
              inside the handler, a child span `"db.load_note"` (from
              `provider.get_tracer("lab")`) with the attribute `note.id`; return
              `{"id": note_id}`. Instrument the app with `FastAPIInstrumentor` and `provider`.
            - `outgoing_headers() -> dict[str, str]`: the headers a call to another service must
              carry to continue the current trace (empty when there is no current span).
            """
        ),
        md("Your solution:"),
        code(
            r'''
            def build_traced_app(provider: TracerProvider) -> FastAPI:
                """An instrumented app with one manual child span."""
                raise NotImplementedError


            def outgoing_headers() -> dict[str, str]:
                """Trace context for an outgoing request."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 5:"),
        code(
            r'''
            INCOMING_TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"


            def tracing_scenario() -> dict[str, Any]:
                """One request with an incoming traceparent; collect the spans."""
                exporter, provider = InMemorySpanExporter(), TracerProvider()
                provider.add_span_processor(SimpleSpanProcessor(exporter))
                with TestClient(build_traced_app(provider)) as client:
                    client.get("/notes/7", headers={"traceparent": f"00-{INCOMING_TRACE}-00f067aa0ba902b7-01"})
                spans = {
                    span.name: span for span in exporter.get_finished_spans() if "http send" not in span.name
                }
                with provider.get_tracer("lab").start_as_current_span("caller") as caller:
                    inside = outgoing_headers().get("traceparent", "")
                    caller_trace = format(caller.get_span_context().trace_id, "032x")
                return {
                    "spans": spans,
                    "inside": inside,
                    "caller_trace": caller_trace,
                    "outside": outgoing_headers(),
                }


            lab_tracing: dict[str, Any] = {}
            with contextlib.suppress(Exception):
                lab_tracing = tracing_scenario()
            '''
        ),
        md("The checks:"),
        code(
            r"""
            run_checks(
                [
                    (
                        "server and child spans",
                        lambda: sorted(lab_tracing["spans"]),
                        ["GET /notes/{note_id}", "db.load_note"],
                    ),
                    (
                        "server span kind",
                        lambda: lab_tracing["spans"]["GET /notes/{note_id}"].kind.name,
                        "SERVER",
                    ),
                    (
                        "child of the server span",
                        lambda: (
                            lab_tracing["spans"]["db.load_note"].parent.span_id
                            == lab_tracing["spans"]["GET /notes/{note_id}"].context.span_id
                        ),
                        True,
                    ),
                    (
                        "note.id attribute",
                        lambda: dict(lab_tracing["spans"]["db.load_note"].attributes),
                        {"note.id": 7},
                    ),
                    (
                        "incoming trace continued",
                        lambda: format(lab_tracing["spans"]["db.load_note"].context.trace_id, "032x"),
                        INCOMING_TRACE,
                    ),
                    (
                        "outgoing traceparent carries the trace",
                        lambda: lab_tracing["inside"].split("-")[1] == lab_tracing["caller_trace"],
                        True,
                    ),
                    ("nothing to propagate outside a span", lambda: lab_tracing["outside"], {}),
                ]
            )
            """
        ),
    ]


def _lab_exercise_6_cells() -> list[NotebookNode]:
    """Lab 6.7 exercise 6."""
    return [
        md(
            """
            #### Exercise 6 — Health endpoints

            `build_probe_app(checks, state) -> FastAPI`, where `checks` maps names to async
            functions that raise when their dependency is unhealthy and `state` is a dict:

            - `GET /health/live`: 200 `{"status": "ok"}`, **without** calling any check;
            - `GET /health/ready`: run every check with a 0.5 s timeout; the body is
              `{"status": "ok" | "unavailable", "checks": {name: result}}` where result is
              `"ok"`, `"timeout"` or `"failed: <ExceptionName>"`; 200 if all are ok, else 503;
            - `GET /health/startup`: 503 `{"started": false}` until `state["started"]` is true,
              then 200 `{"started": true}`.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            def build_probe_app(
                checks: dict[str, Callable[[], Awaitable[None]]], state: dict[str, bool]
            ) -> FastAPI:
                """Liveness, readiness and startup probes."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 6:"),
        code(
            r'''
            def probe_scenario() -> dict[str, Any]:
                """Probe an app whose checks succeed, fail and hang."""
                calls: list[str] = []

                async def database() -> None:
                    """Healthy."""
                    calls.append("database")

                async def redis() -> None:
                    """Refuses connections."""
                    calls.append("redis")
                    raise ConnectionError("refused")

                async def search() -> None:
                    """Hangs."""
                    calls.append("search")
                    await asyncio.sleep(5)

                state = {"started": False}
                results: dict[str, Any] = {}
                with TestClient(build_probe_app({"database": database}, state)) as client:
                    results["live"] = (client.get("/health/live").status_code, list(calls))
                    results["ready ok"] = client.get("/health/ready").json()
                    results["startup before"] = client.get("/health/startup").status_code
                    state["started"] = True
                    results["startup after"] = client.get("/health/startup").json()
                with TestClient(
                    build_probe_app({"database": database, "redis": redis, "search": search}, state)
                ) as client:
                    started = time.perf_counter()
                    ready = client.get("/health/ready")
                    results["ready bad"] = (ready.status_code, ready.json(), time.perf_counter() - started < 2)
                return results


            lab_probes: dict[str, Any] = {}
            with contextlib.suppress(Exception):
                lab_probes = probe_scenario()
            '''
        ),
        md("The checks:"),
        code(
            r"""
            run_checks(
                [
                    ("liveness calls no check", lambda: lab_probes["live"], (200, [])),
                    (
                        "ready when all checks pass",
                        lambda: lab_probes["ready ok"],
                        {"status": "ok", "checks": {"database": "ok"}},
                    ),
                    ("startup 503 before", lambda: lab_probes["startup before"], 503),
                    ("startup 200 after", lambda: lab_probes["startup after"], {"started": True}),
                    (
                        "503 naming each failure, quickly",
                        lambda: lab_probes["ready bad"],
                        (
                            503,
                            {
                                "status": "unavailable",
                                "checks": {
                                    "database": "ok",
                                    "redis": "failed: ConnectionError",
                                    "search": "timeout",
                                },
                            },
                            True,
                        ),
                    ),
                ]
            )
            """
        ),
    ]


def _notes_v6_intro_cells() -> list[NotebookNode]:
    """Notes API v6: introduction and pruning."""
    return [
        md(
            """
            ### Notes API v6 — the project files

            v6 changes how the Notes API is tested and how it reports on itself:

            | v5 (Unit 6.6) | v6 (this unit) |
            | --- | --- |
            | `TestClient` tests only | plus `httpx.AsyncClient` tests (`async_client` fixture, lifespan included) |
            | PostgreSQL tests in their own container per module | one session-scoped database: the CI service container (`NOTES_TEST_DATABASE_URL`) or a testcontainer; **rollback-per-test** with factories |
            | — | **Schemathesis** over every notes operation, and an **OpenAPI snapshot** |
            | — | **CI**: `.github/workflows/notes-api.yml` runs lint and the suite against PostgreSQL and Redis service containers |
            | plain stdlib log lines | **structlog JSON**: request id, trace id, span id; secrets redacted; one access line per request |
            | — | **Prometheus**: RED metrics per route template, cache and write counters, `/metrics` (multiprocess-ready) |
            | — | **OpenTelemetry** tracing (auto-instrumented server spans + a cache span), console/OTLP/in-memory exporters |
            | — | **Sentry** when `NOTES_SENTRY_DSN` is set, with scrubbing |
            | `/health`, `/health/ready` (database) | `/health/live`, `/health/ready` (database + Redis, timeouts), `/health/startup` (migration revision) |
            | contract drift | fixed: problem+json documented, strict request JSON, non-nullable PATCH fields, `{note_id:int}`, id limits, a correct `Allow` header |

            The cells write the 32 files that changed (of 90) plus the workflow; the OpenAPI
            snapshot is recorded by running its test. First, remove files of other versions
            (including the deployment files of Unit 6.8, when you re-run this section later):
            """
        ),
        code(
            r'''
            NOTES_V6_FILES = """
            .env.example README.md alembic.ini alembic/env.py alembic/script.py.mako
            alembic/versions/0001_create_notes.py alembic/versions/0002_tags_many_to_many.py
            alembic/versions/0003_version_and_search.py alembic/versions/0004_users_and_ownership.py
            alembic/versions/0005_refresh_tokens_and_api_keys.py
            alembic/versions/0006_outbox_and_webhooks.py compose.yaml pyproject.toml ruff.toml
            src/notes_api/__init__.py src/notes_api/auth.py src/notes_api/cache.py
            src/notes_api/core/__init__.py src/notes_api/core/config.py src/notes_api/core/errors.py
            src/notes_api/core/lifespan.py src/notes_api/core/logging.py src/notes_api/core/metrics.py
            src/notes_api/core/middleware.py src/notes_api/core/sentry.py src/notes_api/core/tracing.py
            src/notes_api/db.py src/notes_api/dependencies.py src/notes_api/events.py
            src/notes_api/exceptions.py src/notes_api/exports.py src/notes_api/mailer.py
            src/notes_api/main.py src/notes_api/models.py src/notes_api/oauth.py src/notes_api/pagination.py
            src/notes_api/ratelimit.py src/notes_api/repositories.py src/notes_api/routers/__init__.py
            src/notes_api/routers/admin.py src/notes_api/routers/auth.py src/notes_api/routers/exports.py
            src/notes_api/routers/health.py src/notes_api/routers/notes.py src/notes_api/routers/pages.py
            src/notes_api/routers/realtime.py src/notes_api/routers/users.py src/notes_api/schemas.py
            src/notes_api/security.py src/notes_api/services.py src/notes_api/static/style.css
            src/notes_api/templates/_note.html src/notes_api/templates/_notes.html
            src/notes_api/templates/base.html src/notes_api/templates/index.html
            src/notes_api/templates/login.html src/notes_api/worker.py tests/conftest.py tests/factories.py
            tests/helpers.py tests/snapshots/openapi.json tests/test_admin.py tests/test_async.py
            tests/test_auth.py tests/test_background.py tests/test_bola.py tests/test_caching.py
            tests/test_contract.py tests/test_errors.py tests/test_exports.py tests/test_links.py
            tests/test_middleware.py tests/test_migrations.py tests/test_notes.py tests/test_oauth.py
            tests/test_observability.py tests/test_pages.py tests/test_pagination.py tests/test_postgres.py
            tests/test_postgres_rollback.py tests/test_realtime.py tests/test_redis_worker.py
            tests/test_repository.py tests/test_security.py tests/test_settings.py tests/test_worker.py
            src/notes_api/manage.py src/notes_api/netguard.py tests/test_limits.py tests/test_netguard.py
            """.split()
            print("removed:", prune_notes_project(NOTES_V6_FILES))
            V7_ONLY = ["Dockerfile", ".dockerignore", "Procfile", "deploy", "load"]  # outside prune's areas
            for name in V7_ONLY:
                target = NOTES_API_DIR / name
                if target.is_dir():
                    shutil.rmtree(target)
                elif target.exists():
                    target.unlink()
            (NOTES_API_DIR / "tests" / "snapshots").mkdir(parents=True, exist_ok=True)
            print(f"{len(NOTES_V6_FILES)} files in v6")
            '''
        ),
    ]


def _notes_v6_try_cells() -> list[NotebookNode]:
    """Notes API v6: observability in the kernel."""
    return [
        md(
            """
            **Try it in the kernel.** The app writes JSON logs to a buffer here, keeps spans in
            memory (`NOTES_OTEL_EXPORTER=memory`) and counts in its own registry. One request,
            seen three ways: its access log line, its metrics, its span tree, all sharing the
            same ids:
            """
        ),
        code(
            r"""
            notes_main = reload_notes_api()
            NotesSettings = sys.modules["notes_api.core.config"].Settings
            notes_db = sys.modules["notes_api.db"]
            notes_dependencies = sys.modules["notes_api.dependencies"]
            notes_logging = sys.modules["notes_api.core.logging"]

            demo_db = PHASE6_DIR / "notes_v6_demo.db"
            demo_db.unlink(missing_ok=True)
            notes_settings = NotesSettings(
                _env_file=None,
                environment="test",
                database_url=SecretStr(f"sqlite+aiosqlite:///{demo_db}"),
                jwt_secret=SecretStr(secrets.token_urlsafe(32)),
                password_time_cost=1,
                password_memory_kib=64,
                cookie_secure=False,
                otel_exporter="memory",
                check_migrations=False,
            )
            schema_engine = notes_db.create_engine_from_settings(notes_settings)
            async with schema_engine.begin() as connection:
                await connection.run_sync(notes_db.Base.metadata.create_all)
            await schema_engine.dispose()
            notes_app = notes_main.create_app(notes_settings)
            demo_redis = fakeredis.FakeAsyncRedis(decode_responses=True)
            notes_app.dependency_overrides[notes_dependencies.get_redis] = lambda: demo_redis
            notes_app.dependency_overrides[notes_dependencies.get_queue] = lambda: ArqRedis(
                connection_pool=fakeredis.FakeAsyncRedis().connection_pool
            )
            notes_logs = io.StringIO()
            notes_logging.configure_logging("INFO", json_output=True, stream=notes_logs)
            print(
                type(notes_app.state.span_exporter).__name__,
                "| metrics:",
                any(getattr(route, "path", "") == "/metrics" for route in notes_app.routes),
            )
            """
        ),
        md(
            "A logged-in user creates and reads a note; then the log line, the metrics and the spans of that read:"
        ),
        code(
            r"""
            with TestClient(notes_app) as client:
                client.post(
                    "/api/v1/auth/register", json={"email": "obs@example.com", "password": "a-long-passphrase"}
                )
                token = client.post(
                    "/api/v1/auth/token", data={"username": "obs@example.com", "password": "a-long-passphrase"}
                ).json()["access_token"]
                client.headers["Authorization"] = f"Bearer {token}"
                note_id = client.post("/api/v1/notes", json={"title": "Observed"}).json()["id"]
                notes_app.state.span_exporter.clear()
                client.get(f"/api/v1/notes/{note_id}", headers={"X-Request-ID": "req-observed"})
                metrics_text = client.get("/metrics").text
            access = [
                json.loads(line) for line in notes_logs.getvalue().splitlines() if '"req-observed"' in line
            ][-1]
            print({key: access[key] for key in ("event", "method", "path", "status", "request_id", "trace_id")})
            print(
                *[
                    line
                    for line in metrics_text.splitlines()
                    if line.startswith("notes_http_requests_total") and "note_id" in line
                ],
                sep="\n",
            )
            for span in notes_app.state.span_exporter.get_finished_spans():
                if "http send" not in span.name:
                    print(
                        f"  span {span.name:34} trace {format(span.context.trace_id, '032x')[:8]}... "
                        f"{dict(span.attributes).get('cache.hit', '')}"
                    )
            """
        ),
        md(
            """
            The trace id in the log line is the trace of the spans: from a slow-request alert to
            its trace to its log lines is one search each. And the probes:
            """
        ),
        code(
            r"""
            with TestClient(notes_app) as client:
                for probe in ("/health/live", "/health/ready", "/health/startup"):
                    reply = client.get(probe)
                    print(f"{probe:16} {reply.status_code} {reply.json()}")
            """
        ),
    ]


def _notes_v6_run_cells() -> list[NotebookNode]:
    """Notes API v6: snapshot, the suite as in CI, clean up."""
    return [
        md(
            """
            **Record the OpenAPI snapshot.** The first run of the snapshot test with
            `UPDATE_SNAPSHOTS=1` writes `tests/snapshots/openapi.json`; from then on any change to
            the public contract fails the test until it is re-recorded deliberately:
            """
        ),
        code(
            r"""
            snapshot_run = run_in_notes(
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-k",
                "snapshot",
                extra_env={"UPDATE_SNAPSHOTS": "1"},
            )
            print(
                [
                    line
                    for line in tidy_test_output(snapshot_run.stdout).splitlines()
                    if "passed" in line or "failed" in line
                ][-1]
            )
            snapshot_file = NOTES_API_DIR / "tests" / "snapshots" / "openapi.json"
            print(
                snapshot_file.relative_to(REPO_ROOT),
                f"{len(snapshot_file.read_text().splitlines())} lines,",
                len(json.loads(snapshot_file.read_text())["paths"]),
                "paths",
            )
            """
        ),
        md(
            """
            **This version's tests, the way CI runs them.** `uv lock` adds the new packages to
            the project's lock; then the test files v6 adds or changes (`NEW_TESTS`; the full suite runs once, in the Phase 6 Project)
            run with `NOTES_TEST_DATABASE_URL` and
            `NOTES_TEST_REDIS_URL` pointing at this unit's PostgreSQL and Redis containers,
            exactly as the workflow points them at its service containers (so no test starts its
            own container). Without Docker the PostgreSQL and Redis tests skip:
            """
        ),
        code(
            r'''
            async def fresh_database(server_url: str, name: str) -> str:
                """An empty database on the shared server (the demo tables of 6.7.2 stay out of it)."""
                connection = await asyncpg.connect(server_url.replace("postgresql+asyncpg", "postgresql"))
                try:
                    await connection.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
                    await connection.execute(f"CREATE DATABASE {name}")
                finally:
                    await connection.close()
                return server_url.rsplit("/", 1)[0] + f"/{name}"


            NEW_TESTS = __NEW_TESTS__
            REDIS_URL = start_shared_redis()
            ci_env = {}
            if PG_URL and REDIS_URL:
                ci_env = {
                    "NOTES_TEST_DATABASE_URL": await fresh_database(PG_URL, "notes_ci"),
                    "NOTES_TEST_REDIS_URL": REDIS_URL,
                }
            '''
        ),
        md("Next:"),
        code(
            r"""
            if HAS_UV:
                lock_run = run_in_notes("uv", "lock")
                print(lock_summary(lock_run.stderr))
                ci_run = run_in_notes(
                    "uv",
                    "run",
                    "--frozen",
                    "pytest",
                    "-p",
                    "no:cacheprovider",
                    "-rfs",
                    *NEW_TESTS,
                    extra_env=ci_env,
                    timeout=600,
                )
                summary = tidy_test_output(ci_run.stdout).splitlines()
                print(
                    summary[-1],
                    f"(exit code {ci_run.returncode})",
                    "with service URLs" if ci_env else "SKIP: no Docker, no services",
                )
                print(*[line for line in summary if line.startswith(("SKIPPED", "FAILED"))], sep="\n")
            else:
                print("SKIP: the uv command is not on PATH")
            """
        ),
        md(
            """
            GitHub reads the workflow from the repository; the same steps run locally as above.
            The workflow file is valid YAML with the job, services and steps the lab asked for:
            """
        ),
        code(
            r"""
            workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "notes-api.yml").read_text())
            job = workflow["jobs"]["test"]
            print("services:", {name: service["image"] for name, service in job["services"].items()})
            print(
                "steps   :", [step.get("name") or step.get("uses", "").split("@")[0] for step in job["steps"]]
            )
            """
        ),
        md("The project after Unit 6.7 (tool caches removed first):"),
        code(
            r"""
            for cache in (".hypothesis", ".mypy_cache"):  # tool caches, git-ignored
                shutil.rmtree(NOTES_API_DIR / cache, ignore_errors=True)
            print(notes_tree())
            """
        ),
        md(
            """
            **Clean up.** Stop and remove this unit's PostgreSQL and Redis containers (the
            Jaeger container of 6.7.8 was removed by its `with` block), and check `docker ps`:
            """
        ),
        code(
            r"""
            stop_shared_postgres()
            stop_shared_redis()
            if shutil.which("docker"):
                running = subprocess.run(
                    ["docker", "ps", "--format", "{{.Image}}"], capture_output=True, text=True
                ).stdout.split()
                print("containers still running:", running or "none")
            """
        ),
        md(
            """
            What v6 leaves for Unit 6.8: an image to run all this in, a stack with a proxy and TLS,
            a pipeline that builds, scans, pushes and deploys, and a load test.
            """
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 6.7."""
    return [
        md(
            """
            ### Recap — Unit 6.7

            | Concept | One-line takeaway | JS / TS equivalent |
            | --- | --- | --- |
            | TestClient vs AsyncClient | TestClient runs the app in another loop; AsyncClient shares the test's loop (lifespan by hand) | Supertest |
            | Async tests | the anyio plugin: `pytest.mark.anyio` + `anyio_backend` | Jest async tests |
            | `dependency_overrides` | swap a dependency per test; design code for injection | `jest.mock`, NestJS testing module |
            | Database tests | real PostgreSQL once per session; rollback-per-test with `create_savepoint`; factories | Testcontainers, Prisma test DB |
            | External services | `respx` / `MockTransport`; call jobs directly; read streams line by line | `nock`, MSW |
            | Contract testing | Schemathesis generates requests from the schema; the snapshot freezes the contract | Dredd, Schemathesis |
            | Observability | logs, metrics, traces linked by ids; SLIs, SLOs, error budgets; RED and USE | same concepts |
            | Structured logging | structlog processors; `bind_contextvars` per request; redact before rendering | pino, winston |
            | Metrics | counters, gauges, histograms; few label values; multiprocess mode for workers | prom-client |
            | Tracing | OTel spans; auto-instrumentation; `traceparent` propagation; OTLP exporter | OTel JS |
            | Error tracking | Sentry with `before_send` scrubbing | `@sentry/node` |
            | Probes | liveness (nothing external), readiness (dependencies), startup (migrations) | same in Kubernetes |

            **Further reading**

            - [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/),
              [async tests](https://fastapi.tiangolo.com/advanced/async-tests/),
              [testing dependencies](https://fastapi.tiangolo.com/advanced/testing-dependencies/)
            - [SQLAlchemy: joining a session into an external transaction](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#joining-a-session-into-an-external-transaction-such-as-for-test-suites)
            - [respx](https://lundberg.github.io/respx/), [Schemathesis](https://schemathesis.readthedocs.io/),
              [Hypothesis](https://hypothesis.readthedocs.io/), [testcontainers-python](https://testcontainers-python.readthedocs.io/)
            - [structlog](https://www.structlog.org/), [prometheus_client](https://prometheus.github.io/client_python/)
              ([multiprocess mode](https://prometheus.github.io/client_python/multiprocess/)),
              [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/),
              [W3C Trace Context](https://www.w3.org/TR/trace-context/), [Sentry for FastAPI](https://docs.sentry.io/platforms/python/integrations/fastapi/)
            - Google SRE book: [Service Level Objectives](https://sre.google/sre-book/service-level-objectives/),
              [The RED method](https://grafana.com/blog/2018/08/02/the-red-method-how-to-instrument-your-services/),
              [The USE method](https://www.brendangregg.com/usemethod.html)
            - Kubernetes: [liveness, readiness and startup probes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/);
              GitHub Actions: [service containers](https://docs.github.com/en/actions/use-cases-and-examples/using-containerized-services/about-service-containers)
            - Python: [`contextvars`](https://docs.python.org/3/library/contextvars.html),
              [`logging`](https://docs.python.org/3/library/logging.html),
              [`statistics.quantiles`](https://docs.python.org/3/library/statistics.html#statistics.quantiles),
              [PEP 654 (exception groups)](https://peps.python.org/pep-0654/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 6.7, Lab 6.7 and Notes API v6."""
    return [
        *_overview_cells(),
        *_test_architecture_cells(),
        *_database_test_cells(),
        *_external_service_cells(),
        *_contract_cells(),
        *_observability_cells(),
        *_structured_logging_cells(),
        *_metrics_cells(),
        *_tracing_cells(),
        *_error_tracking_cells(),
        *_predict_cells(),
        *_lab_setup_cells(),
        *_lab_exercise_1_cells(),
        *_lab_exercise_2_cells(),
        *_lab_exercise_3_cells(),
        *_lab_exercise_4_cells(),
        *_lab_exercise_5_cells(),
        *_lab_exercise_6_cells(),
        *_notes_v6_intro_cells(),
        *_notes_v6_project_cells(),
        *_notes_v6_observability_cells(),
        *_notes_v6_api_cells(),
        *_notes_v6_test_cells(),
        *_notes_v6_try_cells(),
        *_notes_v6_run_cells(),
        *_recap_cells(),
    ]


def _notes_v6_project_cells() -> list[NotebookNode]:
    """Notes API v6: project metadata, environment template, README, CI workflow."""
    return [
        md(
            """
            **Project metadata.** Version 0.6.0. Runtime: `structlog`, `prometheus-client`,
            `opentelemetry-sdk` and `opentelemetry-instrumentation-fastapi`. Tests:
            `schemathesis` (and `locust`, used in Unit 6.8):
            """
        ),
        *writefile_cells(
            NOTES_V6_PYPROJECT_TOML,
            [
                ("", "Part 1 of `pyproject.toml`: from `[project]`."),
                ("[tool.pytest.ini_options]", "Part 2: from `[tool.pytest.ini_options]`."),
            ],
        ),
        md("`.env.example` gains the observability settings (all optional):"),
        *writefile_cells(
            NOTES_V6_ENV_EXAMPLE,
            [
                (
                    "",
                    "Part 1 of `.env.example`: from `# Copy this file to .env and fill in real values. .env is gi`.",
                ),
                (
                    "# Observability: JSON logs, Prometheus metrics, OpenTelemetry traces, Sentry",
                    "Part 2: Observability: JSON logs, Prometheus metrics, OpenTelemetry traces, Sentry.",
                ),
            ],
        ),
        md("The README: observability, CI, and the new test layout:"),
        *writefile_cells(
            NOTES_V6_README_MD,
            [
                ("", "Part 1 of `README.md`: Notes API."),
                ("## Run", "Part 2: Run."),
                ("## Endpoints", "Part 3: Endpoints."),
                ("## Layout", "Part 4: Layout."),
            ],
        ),
        md(
            """
            **CI** (`.github/workflows/notes-api.yml`, in the repository root, where GitHub
            looks for workflows): lint, then the whole suite against **PostgreSQL and Redis
            service containers**. GitHub starts them next to the job, waits for their health
            checks, and the tests find them through `NOTES_TEST_DATABASE_URL` and
            `NOTES_TEST_REDIS_URL`:
            """
        ),
        *writefile_cells(
            NOTES_V6_GITHUB_WORKFLOWS_NOTES_API_YML,
            [
                (
                    "",
                    "Part 1 of `.github/workflows/notes-api.yml`: from `# CI for the Notes API (projects/notes_api/): lint and the w`.",
                ),
                ("jobs:", "Part 2: `jobs`: `test`."),
                ("    steps:", "Part 3: `steps` under `test`."),
            ],
        ),
    ]


def _notes_v6_observability_cells() -> list[NotebookNode]:
    """Notes API v6: settings, logging, metrics, tracing, Sentry, errors, health, main."""
    return [
        md("Version 0.6.0:"),
        code(NOTES_V6_INIT_PY),
        md(
            "`config.py` adds log level and format, metrics, the OpenTelemetry exporter and endpoint, the Sentry DSN and the migration check:"
        ),
        *writefile_cells(
            NOTES_V6_CORE_CONFIG_PY,
            [
                (
                    "",
                    "Part 1 of `core/config.py`: the module docstring and imports, then `Settings`.",
                ),
                (
                    "    # Authentication: an HS256 secret (required in production; a random one per process otherwise)",
                    "Part 2 (continues `Settings`): more fields.",
                ),
                (
                    "    # Observability (Unit 6.7)",
                    "Part 3 (continues `Settings`): `oauth_enabled()`, `require_real_secrets_in_production()`; then `get_settings()` — The process-wide settings, read from the environment once and then cached.",
                ),
            ],
        ),
        md(
            """
            **`core/logging.py`**: structlog. `configure_logging()` routes structlog **and**
            stdlib logging (Uvicorn included) through one formatter; the processors add the
            request id, the trace and span ids, and redact secrets; `AccessLogMiddleware`
            writes one line per request from inside the request's context:
            """
        ),
        *writefile_cells(
            NOTES_V6_CORE_LOGGING_PY,
            [
                ("", "Part 1 of `core/logging.py`: the module docstring and imports."),
                (
                    "def redact_text(text: str) -> str:",
                    "Part 2: `redact_text()`, `redact_value()`, `RedactingFilter`, `install_redaction()` — Replace secrets in a string (prefixes such as 'Bearer ' or 'password=' are kept).",
                ),
                (
                    "def add_request_context(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:",
                    "Part 3: `add_request_context()`, `redact_event()`, `SHARED_PROCESSORS` — structlog processor: add the request id and the current trace/span ids.",
                ),
                (
                    "def configure_logging(",
                    "Part 4: `configure_logging()` — Route structlog and stdlib logging (Uvicorn included) through one JSON formatter.",
                ),
                (
                    "class AccessLogMiddleware:",
                    "Part 5: `AccessLogMiddleware` — Pure ASGI: one structured log line per request, written inside the request's context.",
                ),
            ],
        ),
        md(
            """
            **`core/metrics.py`** (new): RED metrics per **route template** (never the raw
            path), a gauge of requests in flight, business counters, and `/metrics`, which
            aggregates every worker process in multiprocess mode:
            """
        ),
        *writefile_cells(
            NOTES_V6_CORE_METRICS_PY,
            [
                ("", "Part 1 of `core/metrics.py`: the module docstring and imports."),
                (
                    "HTTP_REQUESTS = Counter(",
                    "Part 2: `HTTP_REQUESTS`, `HTTP_LATENCY`, `HTTP_IN_PROGRESS`.",
                ),
                (
                    "NOTES_WRITTEN = Counter(",
                    "Part 3: `NOTES_WRITTEN`, `CACHE_LOOKUPS`, `EXCLUDED_PATHS`, `route_template()` — The matched route's template (e.g. /api/v1/notes/{note_id}); 'unmatched' for 404s.",
                ),
                (
                    "class MetricsMiddleware:",
                    "Part 4: `MetricsMiddleware` — Pure ASGI: count requests, observe their duration, track requests in flight.",
                ),
                (
                    "def metrics_registry() -> CollectorRegistry:",
                    "Part 5: `metrics_registry()`, `metrics_endpoint()` — This process's registry, or an aggregate of every worker's files in multiprocess mode.",
                ),
            ],
        ),
        md(
            """
            **`core/tracing.py`** (new): one `TracerProvider` per app, FastAPI
            auto-instrumentation, and the exporter chosen by `NOTES_OTEL_EXPORTER`:
            """
        ),
        *writefile_cells(
            NOTES_V6_CORE_TRACING_PY,
            [
                ("", "Part 1 of `core/tracing.py`: the module docstring and imports."),
                (
                    "def make_exporter(settings: Settings) -> SpanExporter | None:",
                    "Part 2: `make_exporter()`, `install_tracing()` — The span exporter the settings ask for (None: tracing off).",
                ),
            ],
        ),
        md(
            "**`core/sentry.py`** (new): Sentry, only with a DSN; `scrub_event` redacts before anything leaves:"
        ),
        *writefile_cells(
            NOTES_V6_CORE_SENTRY_PY,
            [
                (
                    "",
                    "Part 1 of `core/sentry.py`: the module docstring and imports, then `scrub_event()`.",
                ),
                (
                    "def install_sentry(settings: Settings, transport: Any = None) -> bool:",
                    "Part 2: `install_sentry()` — Initialise the Sentry SDK (FastAPI integration auto-enabled); False when disabled.",
                ),
            ],
        ),
        md(
            """
            `core/errors.py`: what Schemathesis found. The OpenAPI document now says what the
            handlers send (`application/problem+json` for every 4xx/5xx, a 400 for malformed
            bodies), and a 405 lists **all** the methods of the path in `Allow`:
            """
        ),
        *writefile_cells(
            NOTES_V6_CORE_ERRORS_PY,
            [
                (
                    "",
                    "Part 1 of `core/errors.py`: the module docstring and imports, then `ProblemDetail`.",
                ),
                (
                    "def problem_response(",
                    "Part 2: `problem_response()` — Build an application/problem+json response; the request id links it to the logs.",
                ),
                (
                    "async def domain_error_handler(request: Request, error: DomainError) -> JSONResponse:",
                    "Part 3: `domain_error_handler()`, `allowed_methods()` — DomainError subclasses → their own status, type and title.",
                ),
                (
                    "async def http_error_handler(request: Request, error: StarletteHTTPException) -> JSONResponse:",
                    "Part 4: `http_error_handler()`, `validation_error_handler()` — HTTPException (ours, and Starlette's 404/405) → Problem Details.",
                ),
                (
                    "async def integrity_error_handler(request: Request, error: IntegrityError) -> JSONResponse:",
                    "Part 5: `integrity_error_handler()`, `unhandled_error_handler()`, `install_error_handlers()` — A constraint the database enforced (unique, foreign key) → 409, without SQL details.",
                ),
                (
                    "def document_problem_responses(app: FastAPI) -> None:",
                    "Part 6: `document_problem_responses()` — Make the OpenAPI document tell the truth: every 4xx/5xx body is application/problem+json.",
                ),
            ],
        ),
        md("The lifespan flushes the tracer on shutdown:"),
        *writefile_cells(
            NOTES_V6_CORE_LIFESPAN_PY,
            [
                ("", "Part 1 of `core/lifespan.py`: the module docstring and imports."),
                (
                    "@asynccontextmanager",
                    "Part 2: `lifespan()` — Open the database pool, Redis (text and queue clients) and an HTTP client; close them.",
                ),
            ],
        ),
        md("`db.py` declares the schema revision this code expects:"),
        *writefile_cells(
            NOTES_V6_DB_PY,
            [
                ("", "Part 1 of `db.py`: the module docstring and imports, then `UTCDateTime`."),
                (
                    "    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:",
                    "Part 2 (continues `UTCDateTime`): `process_bind_param()`, `process_result_value()`; then `Base`, `enable_sqlite_foreign_keys()` — Base class of every model: shared metadata and type mapping.",
                ),
                (
                    "def create_engine_from_settings(settings: Settings) -> AsyncEngine:",
                    "Part 3: `create_engine_from_settings()`, `make_session_factory()` — An async engine: a connection pool for PostgreSQL, foreign keys switched on for SQLite.",
                ),
            ],
        ),
        md(
            """
            **`routers/health.py`**: three probes. Liveness touches nothing; readiness checks the
            database and Redis (each with a timeout); startup checks the migration revision:
            """
        ),
        *writefile_cells(
            NOTES_V6_ROUTERS_HEALTH_PY,
            [
                (
                    "",
                    "Part 1 of `routers/health.py`: the module docstring and imports, then `health()`, `live()`.",
                ),
                (
                    "async def database_revision(request: Request) -> str | None:",
                    "Part 2: `database_revision()`, `report()`, `ready()` — SELECT 1, then the Alembic revision (None when the table does not exist); a failed check reports only `unavailable` (the exception goes to the log, not to whoever calls the probe).",
                ),
                (
                    '@router.get("/health/startup")',
                    "Part 3: `startup()`, `migration_state()` — the schema must be at SCHEMA_REVISION **or newer**: after a rollback the database keeps the newer release's migrations (expand/contract), and the old code must still start.",
                ),
            ],
        ),
        md(
            "`main.py`: logging, Sentry, the metrics and access-log middleware, `/metrics`, and tracing installed last (outermost):"
        ),
        *writefile_cells(
            NOTES_V6_MAIN_PY,
            [
                ("", "Part 1 of `main.py`: the module docstring and imports."),
                (
                    "def operation_id(route: APIRoute) -> str:",
                    "Part 2: `operation_id()`, `install_middleware()`, `install_security()` — Use the function name as the OpenAPI operationId (clean names in generated clients).",
                ),
                (
                    "OPENAPI_TAGS = [",
                    "Part 3: `OPENAPI_TAGS`, `include_routers()` — Health probes and pages at the root; everything else under /api/v1.",
                ),
                (
                    "def create_app(settings: Settings | None = None) -> FastAPI:",
                    "Part 4: `create_app()`, `app` — Build a fully wired app; tests pass their own Settings, servers use the environment.",
                ),
            ],
        ),
    ]


def _notes_v6_api_cells() -> list[NotebookNode]:
    """Notes API v6: contract fixes in schemas and routes, instrumented cache and services."""
    return [
        md(
            """
            `schemas.py`, tightened by the contract tests: strict JSON types in request bodies,
            optional-but-not-nullable PATCH fields (`SkipJsonSchema[None]`), patterns that put
            the title and tag rules into the schema, and limits at the database's `INTEGER`
            range:
            """
        ),
        *writefile_cells(
            NOTES_V6_SCHEMAS_PY,
            [
                (
                    "",
                    "Part 1 of `schemas.py`: the module docstring and imports, then `require_slug()`.",
                ),
                (
                    "def unique_in_order(tags: list[str]) -> list[str]:",
                    "Part 2: `unique_in_order()`, `at_most()`, `Title`, `Body`, `Tag`, ... — Drop repeated tags, keeping the first occurrence.",
                ),
                (
                    "    model_config = ConfigDict(",
                    "Part 3 (continues `NoteCreate`): `drop_duplicate_tags()`; then `NoteUpdate` — Body of PATCH /notes/{note_id}: only the fields being changed.",
                ),
                (
                    "    # Optional but not nullable: SkipJsonSchema keeps None out of the documented schema, which",
                    "Part 4 (continues `NoteUpdate`): `drop_duplicate_tags()`, `reject_explicit_null()`; then `NoteRead` — A note as the API returns it.",
                ),
                (
                    "    id: int",
                    "Part 5 (continues `NoteRead`): `word_count()`; then `NoteFilters`, `FeedParams` — Query parameters of GET /notes: filtering, sorting and pagination.",
                ),
                (
                    "class LinkPreview(BaseModel):",
                    "Part 6: `LinkPreview`, `ImportReport`, `ScopeName`, `UserCreate`, `UserRead` — The title of one link found in a note's body (or why it could not be fetched).",
                ),
                (
                    "    id: int\n    email: str",
                    "Part 7 (continues `UserRead`): more fields; then `TokenPair`, `RefreshRequest`, `ApiKeyCreate`, `ApiKeyRead` — The OAuth 2.0 token response (RFC 6749 section 5.1) plus our refresh token.",
                ),
                (
                    "    id: int\n    name: str",
                    "Part 8 (continues `ApiKeyRead`): `split_scopes()`; then `ApiKeyCreated`, `WebhookSettings` — The response to creating a key: the only time the full key is shown.",
                ),
            ],
        ),
        md(
            "`routers/notes.py`: `{note_id:int}` paths (`/notes/feed` no longer matches an id route), documented 400/401/403/409 responses:"
        ),
        *writefile_cells(
            NOTES_V6_ROUTERS_NOTES_PY,
            [
                (
                    "",
                    "Part 1 of `routers/notes.py`: the module docstring and imports, then `problem()`.",
                ),
                (
                    'NOT_FOUND: dict[int | str, dict[str, Any]] = {404: problem("No note has this id.")}',
                    "Part 2: `NOT_FOUND`, `WRITE_ERRORS`, `AUTH_ERRORS`, `CACHE_CONTROL`, `router`, ... — A strong validator: the version changes on every update.",
                ),
                (
                    '@router.post(\n    "",\n    response_model=NoteRead,',
                    "Part 3: `create_note()`, `list_notes()` — Create a note; the Location header points at it.",
                ),
                (
                    '@router.get(\n    "/feed",',
                    "Part 4: `notes_feed()`, `get_note()` — Newest notes first, with keyset (cursor) pagination.",
                ),
                (
                    '@router.put(\n    "/{note_id:int}",',
                    "Part 5: `replace_note()` — Replace every field of a note (omitted fields get their defaults).",
                ),
                (
                    '@router.patch(\n    "/{note_id:int}",',
                    "Part 6: `update_note()` — change only the fields sent; a stale `version` is a 409. Like every write, it spends the caller's write budget.",
                ),
                (
                    '@router.delete(\n    "/{note_id:int}",',
                    "Part 7: `delete_note()`, `note_links()` — Delete a note; link previews have their own, smaller budget.",
                ),
            ],
        ),
        md(
            "`cache.py`: each lookup is a span (`cache.get_or_load`, attribute `cache.hit`) and a Prometheus count:"
        ),
        *writefile_cells(
            NOTES_V6_CACHE_PY,
            [
                (
                    "",
                    "Part 1 of `cache.py`: the module docstring and imports, then `note_key()`, `NoteCache`.",
                ),
                (
                    "    def __init__(",
                    "Part 2 (continues `NoteCache`): `__init__()`, `ttl()`, `get_or_load()` — Keep the client, the base TTL and the tracer (a no-op one by default).",
                ),
                (
                    "    async def _load(",
                    "Part 3 (continues `NoteCache`): `_load()`, `invalidate()`, `stats()` — A miss: load under a short lock so concurrent misses do not all hit the database.",
                ),
            ],
        ),
        md("`dependencies.py`: the cache gets the app's tracer:"),
        *writefile_cells(
            NOTES_V6_DEPENDENCIES_PY,
            [
                ("", "Part 1 of `dependencies.py`: the module docstring and imports."),
                (
                    "def get_app_settings(connection: HTTPConnection) -> Settings:",
                    "Part 2: `get_app_settings()`, `get_session()`, `SessionDep`, `get_redis()`, `get_clock()`, ... — The settings this app was created with (HTTPConnection: works for WebSockets too).",
                ),
                (
                    "SettingsDep = Annotated[Settings, Depends(get_app_settings)]",
                    "Part 3: `SettingsDep`, `RedisDep`, `ClockDep`, `HttpClientDep`, `get_note_repository()`, ... — The SQL repository on this request's session.",
                ),
                (
                    "AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]",
                    "Part 4: `AuthServiceDep`, `SESSION_COOKIE`, `oauth2_scheme`, `api_key_header`, `get_current_principal()`, ... — Authenticate with a bearer token or an API key, then check the required scopes.",
                ),
                (
                    "async def require_admin(",
                    "Part 5: `require_admin()`, `AdminPrincipal`, `get_note_service()`, `ReaderServiceDep`, `WriterServiceDep`, ... — Role check on top of the scope check (OWASP API5: function-level authorization).",
                ),
                (
                    "def get_login_limiter(redis: RedisDep, settings: SettingsDep) -> FixedWindowRateLimiter:",
                    "Part 6: `get_login_limiter()`, `LoginLimiterDep` — The login/registration rate limiter (shared by every worker through Redis).",
                ),
                (
                    "def per_user_limit(bucket: str, scopes: list[str]) -> Any:",
                    "Part 7: `per_user_limit()` and the route dependencies built with it (OWASP API4). The inner `enforce()` asks for the principal with the route's own scopes: FastAPI caches a dependency per function and scopes, so the limiter adds no second token check.",
                ),
                (
                    "def get_oidc_client(settings: SettingsDep, client: HttpClientDep, redis: RedisDep) -> OidcClient:",
                    "Part 8: `get_oidc_client()`, `OidcClientDep`, `get_cookie_principal()`, `CookiePrincipalDep`, `get_queue()` — The OpenID Connect client (the router checks settings.oauth_enabled first).",
                ),
                (
                    "def get_mailer() -> Mailer:",
                    "Part 9: `get_mailer()`, `get_note_cache()`, `QueueDep`, `MailerDep`, `NoteCacheDep`, ... — Where emails go (tests override it with a fake that records messages).",
                ),
            ],
        ),
        md(
            "`services.py`: note writes are counted; imports validate leniently (CSV values are text):"
        ),
        *writefile_cells(
            NOTES_V6_SERVICES_PY,
            [
                (
                    "",
                    "Part 1 of `services.py`: the module docstring and imports, then `NoteService`.",
                ),
                (
                    "    def __init__(",
                    "Part 2 (continues `NoteService`): `__init__()`, `record()`, `create()`, `load_for_cache()`, ... — Keep the collaborators; every operation is limited to owner_id's notes.",
                ),
                (
                    "    async def search(self, filters: NoteFilters) -> tuple[list[Note], int]:",
                    "Part 3 (continues `NoteService`): `search()`, `feed()`, `replace()`, `update()`, ... — One page of the owner's matching notes and the total.",
                ),
                (
                    "    async def import_notes(self, notes: list[NoteCreate]) -> list[Note]:",
                    "Part 4 (continues `NoteService`): `import_notes()`; then `parse_import()` — Notes from a .json list or a .csv file (title, body, tags separated by ';', pinned).",
                ),
                (
                    "class LinkPreviewer:",
                    "Part 5: `LinkPreviewer` — Fetch the <title> of links in a note, refusing anything that is not a public web URL; the checks now live in `netguard.py`.",
                ),
                (
                    "    async def preview(self, url: str) -> LinkPreview:",
                    "Part 6 (continues `LinkPreviewer`): `preview()`, `previews()` — One link: its status and title, or why it was not fetched (never raises).",
                ),
            ],
        ),
        md("`worker.py`: the worker logs the same JSON as the API:"),
        *writefile_cells(
            NOTES_V6_WORKER_PY,
            [
                ("", "Part 1 of `worker.py`: the module docstring and imports."),
                (
                    "def utc_now() -> datetime:",
                    "Part 2: `utc_now()`, `startup()`, `shutdown()` — Now, in UTC.",
                ),
                (
                    "async def relay_outbox(ctx: dict[str, Any]) -> int:",
                    "Part 3: `relay_outbox()` — Publish unpublished outbox events (Redis pub/sub) and queue their webhooks.",
                ),
                (
                    "async def deliver_webhook(ctx: dict[str, Any], event_id: int) -> str:",
                    "Part 4: `deliver_webhook()` — check the URL again (DNS may have changed since it was saved; a blocked URL is dead-lettered at once), POST one signed event through the public-only client, retry with exponential backoff, dead-letter after the last try.",
                ),
                (
                    "async def export_notes(",
                    "Part 5: `export_notes()` — Build a JSON export of a user's notes in chunks, reporting progress to a Redis Stream.",
                ),
                (
                    "async def purge_expired_tokens(ctx: dict[str, Any]) -> int:",
                    "Part 6: `purge_expired_tokens()`, `WorkerSettings` — Daily: delete refresh tokens that expired more than a day ago (one worker at a time).",
                ),
                (
                    "async def run_worker(",
                    "Part 7: `run_worker()` — Build the arq Worker inside a running event loop and run it (SIGTERM stops it cleanly).",
                ),
            ],
        ),
    ]


def _notes_v6_test_cells() -> list[NotebookNode]:
    """Notes API v6: the reorganised test suite."""
    return [
        md(
            """
            **Tests.** `conftest.py`: an `async_client` fixture (`httpx.AsyncClient` +
            `ASGITransport` with the lifespan), session-scoped `postgres_url` / `redis_url`
            that use the CI services when the environment names them and testcontainers
            otherwise, and no Hypothesis example database:
            """
        ),
        *writefile_cells(
            NOTES_V6_TESTS_CONFTEST_PY,
            [
                ("", "Part 1 of `tests/conftest.py`: the module docstring and imports."),
                (
                    "@pytest.fixture",
                    "Part 2: `anyio_backend()`, `settings()`, `redis_server()` — Run async tests on asyncio (the anyio pytest plugin ships with anyio).",
                ),
                (
                    "@pytest.fixture\ndef fake_redis(redis_server: fakeredis.FakeServer) -> fakeredis.FakeAsyncRedis:",
                    "Part 3: `fake_redis()`, `fake_queue()`, `mailer()`, `app()` — The text client (decoded strings), as the app uses it.",
                ),
                (
                    "@pytest.fixture\ndef anonymous(app: FastAPI) -> Iterator[TestClient]:",
                    "Part 4: `anonymous()`, `client()`, `admin_email()`, `admin_headers()`, `async_client()` — A TestClient without credentials; entering it runs the lifespan.",
                ),
                (
                    "async def async_auth_headers(http: httpx.AsyncClient, email: str) -> dict[str, str]:",
                    "Part 5: `async_auth_headers()`, `postgres_url()` — Register and log in through the async client; return a Bearer header.",
                ),
                (
                    '@pytest.fixture(scope="session")\ndef redis_url() -> Iterator[str]:',
                    "Part 6: `redis_url()` — A real Redis: the CI service, or a testcontainer.",
                ),
            ],
        ),
        md(
            "`helpers.py`: Docker detection and the Alembic configuration, shared by the service fixtures:"
        ),
        *writefile_cells(
            NOTES_V6_TESTS_HELPERS_PY,
            [
                (
                    "",
                    "Part 1 of `tests/helpers.py`: the module docstring and imports, then `create()`, `ids()`.",
                ),
                (
                    "def register(client: TestClient, email: str, password: str = PASSWORD) -> Any:",
                    "Part 2: `register()`, `login()`, `auth_headers()`, `promote()` — POST /auth/register (without the client's default credentials), log in, and promote an account the way an operator does (`notes_api.manage.set_role`).",
                ),
                (
                    "async def fake_resolver(host: str) -> list[str]:",
                    "Part 3: `fake_resolver()` — DNS for tests: IP literals resolve to themselves, a few names to fixed addresses.",
                ),
                (
                    "async def create_tables(settings: Settings) -> None:",
                    "Part 4: `create_tables()`, `FakeMailer`, `PROJECT_DIR`, `POSTGRES_IMAGE`, `REDIS_IMAGE`, ... — CREATE TABLE for every model (fast; the PostgreSQL tests run the Alembic migrations).",
                ),
                (
                    "def postgres_alembic_config(url: str) -> Config:",
                    "Part 5: `postgres_alembic_config()` — alembic.ini pointed at a PostgreSQL URL.",
                ),
            ],
        ),
        md(
            "**`factories.py`** (new): valid users and notes with unique defaults; tests override only what they test:"
        ),
        code(NOTES_V6_TESTS_FACTORIES_PY),
        md(
            "**`test_async.py`** (new): the async client, concurrent requests in one loop, a dependency override:"
        ),
        *writefile_cells(
            NOTES_V6_TESTS_TEST_ASYNC_PY,
            [
                (
                    "",
                    "Part 1 of `tests/test_async.py`: the module docstring and imports, then `test_crud_through_the_async_client()`, `test_concurrent_requests_in_one_loop()`.",
                ),
                (
                    "async def test_dependency_override_freezes_the_clock(",
                    "Part 2: `test_dependency_override_freezes_the_clock()` — dependency_overrides swaps a dependency for the rest of the test.",
                ),
            ],
        ),
        md(
            """
            **`test_postgres_rollback.py`** (new): rollback-per-test. The app's session joins
            an outer transaction with `join_transaction_mode="create_savepoint"`; every test
            starts empty without truncating:
            """
        ),
        *writefile_cells(
            NOTES_V6_TESTS_TEST_POSTGRES_ROLLBACK_PY,
            [
                (
                    "",
                    "Part 1 of `tests/test_postgres_rollback.py`: the module docstring and imports.",
                ),
                (
                    "@pytest.fixture",
                    "Part 2: `db_connection()`, `db_session()` — A connection with an open transaction that is always rolled back.",
                ),
                (
                    "@pytest.fixture\nasync def pg_client(",
                    "Part 3: `pg_client()`, `count_notes()` — A logged-in AsyncClient whose requests use the test's session.",
                ),
                (
                    '@pytest.mark.parametrize("run", [1, 2])',
                    "Part 4: `test_every_test_starts_empty()`, `test_factories_make_valid_rows()` — Both runs see zero notes first, though each one writes three.",
                ),
            ],
        ),
        md(
            """
            **`test_contract.py`** (new): Schemathesis over every notes operation, and the
            OpenAPI snapshot (recorded below with `UPDATE_SNAPSHOTS=1`):
            """
        ),
        *writefile_cells(
            NOTES_V6_TESTS_TEST_CONTRACT_PY,
            [
                (
                    "",
                    "Part 1 of `tests/test_contract.py`: the module docstring and imports, then `api_schema()`.",
                ),
                (
                    "@schema.parametrize()",
                    "Part 2: `test_notes_operations_honour_the_schema()`, `test_openapi_matches_the_snapshot()` — Call the app through the logged-in client; validate status, content type and body.",
                ),
            ],
        ),
        md(
            "**`test_observability.py`** (new): correlated JSON logs, redaction, metrics labels, spans, probes, Sentry:"
        ),
        *writefile_cells(
            NOTES_V6_TESTS_TEST_OBSERVABILITY_PY,
            [
                (
                    "",
                    "Part 1 of `tests/test_observability.py`: the module docstring and imports, then `json_lines()`, `test_access_log_is_json_with_request_and_trace_ids()`.",
                ),
                (
                    "def test_secrets_never_reach_the_logs() -> None:",
                    "Part 2: `test_secrets_never_reach_the_logs()`, `test_metrics_use_route_templates()` — stdlib and structlog records are redacted the same way.",
                ),
                (
                    "def test_spans_for_requests_and_the_cache(client: TestClient, app: FastAPI) -> None:",
                    "Part 3: `test_spans_for_requests_and_the_cache()`, `test_probes()`, `BrokenRedis` — The instrumentation makes a server span; NoteCache adds a child span with cache.hit.",
                ),
                (
                    "def test_readiness_fails_when_redis_is_down(client: TestClient, app: FastAPI) -> None:",
                    "Part 4: `test_readiness_fails_when_redis_is_down()`, `test_startup_waits_for_migrations()` — 503 with the failing check named (only `unavailable`, no exception name); liveness stays 200.",
                ),
                (
                    '@pytest.mark.parametrize(\n    ("revision", "status_code", "migrations"),',
                    "Part 5: `test_startup_accepts_a_newer_schema()`, `test_production_publishes_no_schema()` — a database ahead of the code (a rolled-back release migrated it) is ready, one behind is not; production serves no schema at all.",
                ),
                (
                    '@pytest.mark.skipif(importlib.util.find_spec("sentry_sdk") is None, reason="sentry-sdk missing")',
                    "Part 6: `test_sentry_captures_errors_without_secrets()` — An unhandled error reaches Sentry's transport, with the Authorization header scrubbed.",
                ),
                (
                    "    transport = CapturingTransport()",
                    "Part 7 (continues `test_sentry_captures_errors_without_secrets()`): the rest of it.",
                ),
            ],
        ),
        md("`test_middleware.py`: the new middleware order (tracing wraps the stack):"),
        *writefile_cells(
            NOTES_V6_TESTS_TEST_MIDDLEWARE_PY,
            [
                (
                    "",
                    "Part 1 of `tests/test_middleware.py`: the module docstring and imports, then `test_request_id_is_generated_echoed_or_replaced()`, `test_problem_bodies_carry_the_request_id()`, `test_server_timing_header()`.",
                ),
                (
                    "def test_large_responses_are_gzipped(client: TestClient) -> None:",
                    "Part 2: `test_large_responses_are_gzipped()`, `test_cors_preflight_for_an_allowed_and_a_foreign_origin()`, `test_simple_cors_request_exposes_headers()` — Responses over 1000 bytes are compressed when the client accepts gzip.",
                ),
                (
                    "def test_middleware_order(app: FastAPI) -> None:",
                    "Part 3: `test_middleware_order()`, `test_security_headers()` — Outermost first: request id, access log, metrics, security headers, CORS, GZip, timing.",
                ),
            ],
        ),
        md("`test_notes.py`: the readiness body changed:"),
        *writefile_cells(
            NOTES_V6_TESTS_TEST_NOTES_PY,
            [
                (
                    "",
                    "Part 1 of `tests/test_notes.py`: the module docstring and imports, then `test_health()`, `test_create_returns_201_location_and_normalized_fields()`.",
                ),
                (
                    "@pytest.mark.parametrize(",
                    "Part 2: `test_create_rejects_invalid_input()`, `test_get_one_and_unknown_id()`, `test_list_paginates_and_counts_all_matches()` — Invalid bodies are 422 problems pointing at the bad field.",
                ),
                (
                    "def test_list_filters_by_tag_pinned_and_text(client: TestClient) -> None:",
                    "Part 3: `test_list_filters_by_tag_pinned_and_text()`, `test_list_rejects_bad_parameters()`, `test_put_replaces_every_field()`, `test_patch_changes_only_the_fields_sent()` — tag (all of them), pinned and q filters combine.",
                ),
                (
                    "def test_patch_without_a_change_keeps_updated_at(client: TestClient) -> None:",
                    "Part 4: `test_patch_without_a_change_keeps_updated_at()`, `test_patch_rejects_null_and_unknown_fields()`, `test_delete_then_gone()`, `test_unknown_note_is_404_for_every_method()` — Sending the current values is not a change.",
                ),
                (
                    "def test_openapi_uses_function_names_and_versioned_paths(client: TestClient) -> None:",
                    "Part 5: `test_openapi_uses_function_names_and_versioned_paths()`, `test_patch_with_the_current_version_bumps_it()`, `test_patch_with_a_stale_version_is_a_409_problem()`, `test_tags_are_returned_sorted_and_shared()` — Operation ids are function names; JSON routes live under /api/v1; pages are hidden.",
                ),
                (
                    "def test_search_treats_percent_and_underscore_literally(client: TestClient) -> None:",
                    "Part 6: `test_search_treats_percent_and_underscore_literally()`, `test_readiness_checks_the_database()` — q is escaped for LIKE: '%' only matches a real percent sign.",
                ),
            ],
        ),
        md("`test_migrations.py`: `SCHEMA_REVISION` must be the migration head:"),
        *writefile_cells(
            NOTES_V6_TESTS_TEST_MIGRATIONS_PY,
            [
                (
                    "",
                    "Part 1 of `tests/test_migrations.py`: the module docstring and imports, then `alembic_config()`.",
                ),
                (
                    "def test_upgrade_downgrade_round_trip(tmp_path: Path) -> None:",
                    "Part 2: `test_upgrade_downgrade_round_trip()` — head creates every table; base removes them again.",
                ),
                (
                    "def test_data_migration_moves_tags_and_back(tmp_path: Path) -> None:",
                    "Part 3: `test_data_migration_moves_tags_and_back()` — 0002 turns 'shop,food' text into rows; downgrading writes the text back.",
                ),
                (
                    "def test_existing_notes_get_a_disabled_legacy_owner(tmp_path: Path) -> None:",
                    "Part 4: `test_existing_notes_get_a_disabled_legacy_owner()`, `test_schema_revision_is_the_newest_migration()` — 0004 gives notes written before accounts existed to an owner that cannot log in.",
                ),
            ],
        ),
        md(
            "`test_postgres.py`: the shared database fixture; tests that commit clean up after themselves:"
        ),
        *writefile_cells(
            NOTES_V6_TESTS_TEST_POSTGRES_PY,
            [
                ("", "Part 1 of `tests/test_postgres.py`: the module docstring and imports."),
                (
                    "@pytest.fixture",
                    "Part 2: `empty_url()`, `test_models_match_the_migrations()` — The database with every row removed and ids restarted, before and after the test.",
                ),
                (
                    "def test_api_round_trip_on_postgres(empty_url: str) -> None:",
                    "Part 3: `test_api_round_trip_on_postgres()` — Create, search (ILIKE), feed, PATCH with versions and the 409, on the real database.",
                ),
                (
                    "def test_trigram_index_serves_substring_search(empty_url: str) -> None:",
                    "Part 4: `test_trigram_index_serves_substring_search()` — EXPLAIN shows ILIKE '%tea%' using the GIN trigram index (sequential scans off).",
                ),
                (
                    "def test_concurrent_new_tag_is_absorbed_by_the_savepoint(empty_url: str) -> None:",
                    "Part 5: `test_concurrent_new_tag_is_absorbed_by_the_savepoint()` — Two transactions add one new tag; a SAVEPOINT absorbs the loser's unique violation.",
                ),
                (
                    "    async def race() -> list[list[str]]:",
                    "Part 6 (continues `test_concurrent_new_tag_is_absorbed_by_the_savepoint()`): `race()` — Run the two transactions concurrently and report each note's tags.",
                ),
            ],
        ),
        md("`test_redis_worker.py`: Redis from the shared fixture:"),
        *writefile_cells(
            NOTES_V6_TESTS_TEST_REDIS_WORKER_PY,
            [
                (
                    "",
                    "Part 1 of `tests/test_redis_worker.py`: the module docstring and imports, then `real_settings()`, `burst()`.",
                ),
                (
                    "@respx.mock",
                    "Part 2: `test_write_kick_relay_and_signed_webhook()` — A note change reaches the user's webhook through outbox → kick → relay → job.",
                ),
            ],
        ),
    ]


NOTES_V6_PYPROJECT_TOML = r"""
%%writefile ../projects/notes_api/pyproject.toml
[project]
name = "notes-api"
version = "0.6.0"
description = "The Phase 6 Notes API: a FastAPI service built step by step from Unit 6.2 to 6.8."
readme = "README.md"
requires-python = ">=3.15"
dependencies = [
    "fastapi[standard]>=0.163.1",
    "alembic>=1.20.1",
    "arq>=0.25.0",
    "asyncpg>=0.32.0",
    "pwdlib[argon2]>=0.4.2",
    "pydantic-settings>=2.16.2",
    "pyjwt[crypto]>=2.15.1",
    "redis>=8.1.0",
    "sqlalchemy[asyncio]>=2.1.9",
    "structlog>=26.1.0",
    "prometheus-client>=0.26.0",
    "opentelemetry-sdk>=1.45.2",
    "opentelemetry-instrumentation-fastapi>=0.66b2",
]

[dependency-groups]
dev = [
    "aiosqlite>=0.22.1",
    "fakeredis>=2.40.0",
    "locust>=2.47.0",
    "pytest>=9.2.0",
    "respx>=0.23.1",
    "ruff>=0.17.3",
    "schemathesis>=4.33.4",
    "testcontainers>=4.15.0",
]

[build-system]
requires = ["uv_build>=0.13,<0.14"]
build-backend = "uv_build"


[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
addopts = "-q"
markers = [
    "postgres: needs Docker; runs against PostgreSQL in a testcontainer",
    "redis: needs Docker; runs against Redis and the ARQ worker in a testcontainer",
]
filterwarnings = [
    "ignore::DeprecationWarning:testcontainers.*",
    "ignore:'asyncio.iscoroutinefunction' is deprecated:DeprecationWarning:arq.*",
    "ignore:Call to deprecated close:DeprecationWarning",
]
"""

NOTES_V6_ENV_EXAMPLE = r"""
%%writefile ../projects/notes_api/.env.example
# Copy this file to .env and fill in real values. .env is git-ignored: never commit secrets.
# Every variable starts with NOTES_ (see src/notes_api/core/config.py).
NOTES_ENVIRONMENT=development
NOTES_DEBUG=false
# A JSON list of browser origins allowed by CORS.
NOTES_CORS_ORIGINS=["http://localhost:5173"]
NOTES_MAX_UPLOAD_BYTES=1048576
NOTES_HTTP_TIMEOUT_SECONDS=5
# PostgreSQL and Redis from compose.yaml (docker compose up -d --wait); SQLite also works:
# NOTES_DATABASE_URL=sqlite+aiosqlite:///./notes.db
NOTES_DATABASE_URL=postgresql+asyncpg://notes:notes@localhost:5432/notes
NOTES_DATABASE_ECHO=false
NOTES_REDIS_URL=redis://localhost:6379/0
# Access tokens are signed with this secret (HS256). Required in production, 32+ characters:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"
# Left empty in development, the app makes a random one at startup (tokens die on restart).
NOTES_JWT_SECRET=change-me
NOTES_ACCESS_TOKEN_MINUTES=15
NOTES_REFRESH_TOKEN_DAYS=14
NOTES_LOGIN_RATE_LIMIT=5
NOTES_LOGIN_RATE_WINDOW_SECONDS=60
# Set to false only for plain-HTTP local development (the session cookie needs HTTPS otherwise).
NOTES_COOKIE_SECURE=true
# Optional: sign in with an OpenID Connect provider (all six values, or leave them out).
# NOTES_OAUTH_CLIENT_ID=notes-web
# NOTES_OAUTH_CLIENT_SECRET=change-me
# NOTES_OAUTH_AUTHORIZE_URL=https://id.example/authorize
# NOTES_OAUTH_TOKEN_URL=https://id.example/token
# NOTES_OAUTH_JWKS_URL=https://id.example/.well-known/jwks.json
# NOTES_OAUTH_ISSUER=https://id.example
# Background jobs, real time and caching (the worker: uv run python -m notes_api.worker)
NOTES_WEBHOOK_TIMEOUT_SECONDS=5
NOTES_WEBHOOK_MAX_ATTEMPTS=5
NOTES_CACHE_TTL_SECONDS=60
NOTES_WS_HEARTBEAT_SECONDS=20
NOTES_EXPORT_TTL_SECONDS=3600


# Observability: JSON logs, Prometheus metrics, OpenTelemetry traces, Sentry
NOTES_LOG_LEVEL=INFO
NOTES_LOG_JSON=true
NOTES_METRICS_ENABLED=true
NOTES_OTEL_EXPORTER=none                      # console | otlp | none
# NOTES_OTEL_ENDPOINT=http://localhost:4318/v1/traces
# NOTES_SENTRY_DSN=https://<public key>@<host>/<project>
NOTES_CHECK_MIGRATIONS=true
# With several worker processes, Prometheus multiprocess mode needs an empty directory:
# PROMETHEUS_MULTIPROC_DIR=/tmp/notes-metrics
"""

NOTES_V6_README_MD = r"""
%%writefile ../projects/notes_api/README.md
# Notes API

A FastAPI service for creating, searching and organizing notes. It is built step by step in
Phase 6 of the course (`notebooks/phase6_web_fastapi.ipynb`); the notebook writes these files.


| Version | Unit | Adds |
| --- | --- | --- |
| v1 | 6.2 | CRUD path operations, Pydantic v2 schemas, filtering and pagination, OpenAPI |
| v2 | 6.3 | `create_app()` factory, routers under `/api/v1`, settings, dependency injection, middleware, CORS, Problem Details errors, lifespan HTTP client, uploads, cursor pagination, HTML pages |
| v3 | 6.4 | PostgreSQL with async SQLAlchemy 2.0 (typed models, many-to-many tags), a session per request, Alembic migrations, optimistic locking (409), trigram search, keyset pagination on an index |
| v4 | 6.5 | users (Argon2id), JWT access tokens with scopes and roles, rotating refresh tokens with reuse detection, logout and revocation, owner-only notes, hashed API keys, Redis login rate limiting, cookie login with CSRF for the pages, OpenID Connect login, SSRF-safe link previews, security headers, log redaction |
| v5 | 6.6 | an ARQ worker: transactional outbox relay, signed webhooks with retries and a dead-letter list, exports with SSE progress, scheduled clean-up with locks; a WebSocket feed fanned out through Redis pub/sub; ETags, 304 and Cache-Control; Redis cache-aside with stampede protection and hit-rate stats; a welcome email from BackgroundTasks |
| v6 | 6.7 | the test suite reorganised (async client tests, PostgreSQL rollback-per-test with factories, Schemathesis contract tests, an OpenAPI snapshot) and run in CI against service containers; JSON logs with request and trace ids (structlog), Prometheus metrics on `/metrics`, OpenTelemetry tracing, optional Sentry, liveness / readiness / startup probes |


## Run

```bash
cd projects/notes_api
cp .env.example .env                          # then set NOTES_JWT_SECRET (and the rest) in .env
docker compose up -d --wait                   # PostgreSQL 18 and Redis 7.4 on 127.0.0.1
uv run alembic upgrade head                   # create the tables
uv run uvicorn notes_api.main:app --reload    # http://127.0.0.1:8000/ and /docs
uv run python -m notes_api.worker             # the ARQ worker (second terminal)
uv run pytest                                 # fast tests + PostgreSQL / Redis tests (Docker)
uv run pytest -m "not postgres and not redis" # only the fast tests (SQLite, fakeredis)
UPDATE_SNAPSHOTS=1 uv run pytest -k snapshot  # record a deliberate OpenAPI change
docker compose down                           # add -v to delete the data volume
```

Local plain HTTP: set `NOTES_COOKIE_SECURE=false`, or the browser will not send the session
cookie. Every account starts as an ordinary user; promote one with
`uv run python -m notes_api.manage promote-admin <email>` (a command, never an HTTP request).

Observability: every log line is JSON with `request_id`, `trace_id` and `span_id`
(`NOTES_LOG_JSON=false` for console output); Prometheus scrapes `GET /metrics`;
`NOTES_OTEL_EXPORTER=otlp` sends traces to an OpenTelemetry Collector at `NOTES_OTEL_ENDPOINT`;
`NOTES_SENTRY_DSN` turns on error tracking. Probes: `/health/live`, `/health/ready`
(database and Redis), `/health/startup` (schema at the expected migration).

CI (`.github/workflows/notes-api.yml`) runs the whole suite against PostgreSQL and Redis service
containers: the tests read `NOTES_TEST_DATABASE_URL` and `NOTES_TEST_REDIS_URL`, and start
testcontainers only when those are not set.


## Endpoints

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| `GET` | `/health`, `/health/live` | none | liveness (no dependency calls) |
| `GET` | `/health/ready`, `/health/startup` | none | readiness (database + Redis), startup (migrations at head) |
| `GET` | `/metrics` | none (block it at the proxy) | Prometheus text format |
| `POST` | `/api/v1/auth/register` | none | 201; rate limited; never accepts a role |
| `POST` | `/api/v1/auth/token` | none | OAuth2 password form (`username` = email, optional `scope`); rate limited (429 + `Retry-After`) |
| `POST` | `/api/v1/auth/refresh` | refresh token | rotation: each refresh token works once; reuse revokes the family |
| `POST` | `/api/v1/auth/logout` | refresh token (+ bearer) | revokes the family and denies the access token |
| `GET` | `/api/v1/auth/oauth/login`, `/oauth/callback` | none | OpenID Connect (Authorization Code + PKCE); 404 unless configured |
| `GET/DELETE` | `/api/v1/users/me` | bearer or key | the current user; DELETE removes the account and everything it owns |
| `POST/GET/DELETE` | `/api/v1/users/me/api-keys[/{id}]` | bearer | keys are shown once, stored as SHA-256, limited to scopes |
| `POST/GET` | `/api/v1/notes` | `notes:write` / `notes:read` | only the caller's notes |
| `GET` | `/api/v1/notes/feed` | `notes:read` | keyset pagination |
| `GET/PUT/PATCH/DELETE` | `/api/v1/notes/{note_id}` | `notes:read` / `notes:write` | someone else's note is a 404; PATCH `version` → 409 if stale |
| `GET` | `/api/v1/notes/{note_id}/links` | `notes:read` | link titles; private addresses are never fetched |
| `GET/PUT/DELETE` | `/api/v1/users/me/webhook` | bearer | a public URL; PUT returns the signing secret once |
| `POST` | `/api/v1/exports` | any user | 202 + `Location`; an ARQ job builds the export |
| `GET` | `/api/v1/exports/{id}`, `/download`, `/events` | owner | status, JSON file, `text/event-stream` progress (`Last-Event-ID`) |
| `WS` | `/api/v1/ws` | first message `{"token": ...}` | live note events; server pings; 1008 on bad auth or over 5 sockets per user |
| `POST/GET/DELETE` | `/api/v1/admin/import`, `/export`, `/notes` | admin role + `admin` scope | bulk operations |
| `GET/POST` | `/api/v1/admin/cache-stats`, `/webhooks/dead[/{id}/retry]` | admin | cache hit rate; dead-letter list and replay |
| `GET/POST` | `/login`, `/logout`, `/`, `/notes`, `/notes/{id}/pin` | session cookie + CSRF token | HTML (Jinja2 + HTMX) |

Credentials: `Authorization: Bearer <access token>` or `X-API-Key: nk_...`. Errors are
`application/problem+json` (RFC 9457). Every response carries `X-Request-ID`,
`Server-Timing` and security headers (HSTS, CSP, `X-Content-Type-Options`, `X-Frame-Options`).
`GET /api/v1/notes/{id}` sends `ETag` and `Cache-Control: private, no-cache` and answers
`If-None-Match` with 304. Per-user budgets (429 + `Retry-After`): 120 writes, 10 link-preview
calls and 5 exports a minute (`NOTES_WRITE_RATE_LIMIT` etc.). Webhooks carry `X-Notes-Event-Id` and
`X-Notes-Signature: t=<unix time>,v1=<HMAC-SHA256 of "t.body">`.


## Layout

```text
src/notes_api/
├── main.py           # create_app(): settings, security, handlers, middleware, routers
├── core/             # config, errors, middleware, lifespan, logging (structlog + redaction),
│                     # metrics (Prometheus), tracing (OpenTelemetry), sentry
├── routers/          # health, auth, users, notes, exports, realtime, admin, pages
├── dependencies.py   # principal / scopes / roles, sessions, Redis, services as Annotated aliases
├── auth.py           # AuthService: register, login, rotate, logout, API keys, OIDC accounts
├── oauth.py          # OidcClient: Authorization Code + PKCE, ID-token verification
├── security.py       # Argon2id hasher, TokenService (PyJWT), Principal, scopes
├── ratelimit.py      # FixedWindowRateLimiter on Redis
├── worker.py         # ARQ tasks (relay, webhooks, exports, purge) + run_worker()
├── events.py         # outbox events, Redis channels, webhook signatures
├── cache.py          # NoteCache: cache-aside, TTL jitter, stampede lock, stats
├── exports.py        # export progress in Redis Streams, SSE formatting
├── mailer.py         # Mailer protocol, LogMailer, the welcome email
├── services.py       # NoteService (owner-scoped), parse_import, LinkPreviewer (SSRF-safe)
├── repositories.py   # NoteRepository / SqlNoteRepository, SqlUserRepository
├── models.py         # User, RefreshToken, ApiKey, OutboxEvent, Note, Tag, note_tags
├── db.py             # Base (naming convention), UTCDateTime, engine, session factory
├── exceptions.py     # DomainError and subclasses (no FastAPI)
├── schemas.py        # Pydantic request/response models
├── pagination.py     # Page[T], CursorPage[T], cursors
├── templates/        # Jinja2 templates (login, notes)
└── static/           # CSS
alembic/              # env.py (async) + versions/0001-0006
compose.yaml          # local PostgreSQL and Redis
tests/                # pytest: one app, SQLite file and fakeredis per test; factories.py;
                      # PostgreSQL / Redis tests use CI services or testcontainers;
                      # test_contract.py: Schemathesis + snapshots/openapi.json
```

Dependencies point inwards: routers → services → repositories → models. Nothing in
`services.py`, `auth.py`, `security.py`, `repositories.py`, `models.py`, `db.py` or
`exceptions.py` imports FastAPI; `core/errors.py` maps domain exceptions to HTTP responses.
"""

NOTES_V6_GITHUB_WORKFLOWS_NOTES_API_YML = r"""
%%writefile ../.github/workflows/notes-api.yml
# CI for the Notes API (projects/notes_api/): lint and the whole test suite against real
# PostgreSQL and Redis, started by GitHub Actions as service containers next to the job.
#
# The tests read NOTES_TEST_DATABASE_URL and NOTES_TEST_REDIS_URL; on a laptop, where those
# are not set, the same tests start testcontainers instead. Actions are pinned to full commit
# SHAs (a moved tag cannot change what runs); the comment names the release.
name: notes-api

on:
  push:
    branches: ["**"]
    paths:
      - "projects/notes_api/**"
      - ".github/workflows/notes-api.yml"
  pull_request:
    paths:
      - "projects/notes_api/**"
      - ".github/workflows/notes-api.yml"
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: notes-api-${{ github.ref }}
  cancel-in-progress: true

defaults:
  run:
    working-directory: projects/notes_api


jobs:
  test:
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    services:
      postgres:
        image: postgres:18-alpine
        env:
          POSTGRES_USER: notes
          POSTGRES_PASSWORD: notes # a throwaway CI database, not a secret
          POSTGRES_DB: notes_test
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U notes -d notes_test"
          --health-interval 2s --health-timeout 3s --health-retries 15
      redis:
        image: redis:7.4
        ports: ["6379:6379"]
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 2s --health-timeout 3s --health-retries 15
    env:
      NOTES_TEST_DATABASE_URL: postgresql+asyncpg://notes:notes@localhost:5432/notes_test
      NOTES_TEST_REDIS_URL: redis://localhost:6379/0

    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - uses: astral-sh/setup-uv@37802adc94f370d6bfd71619e3f0bf239e1f3b78 # v7.6.0
        with:
          python-version: "3.15"
          enable-cache: true
          cache-dependency-glob: projects/notes_api/uv.lock
      - name: Install (exactly the locked versions)
        run: uv sync --frozen
      - name: Lint and format
        run: uv run ruff check . && uv run ruff format --check .
      - name: Tests (PostgreSQL and Redis from the service containers)
        run: uv run pytest -p no:cacheprovider -rs --junitxml=test-results.xml
      - name: Keep the test report
        if: always()
        uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2
        with:
          name: notes-api-test-results
          path: projects/notes_api/test-results.xml
"""

NOTES_V6_INIT_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/__init__.py
"""Notes API: a FastAPI service built step by step in Phase 6 of the course."""

__version__ = "0.6.0"
'''

NOTES_V6_CORE_CONFIG_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/core/config.py
"""Application settings: environment variables (prefix NOTES_) and an optional .env file."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_SECRETS = {"", "change-me"}
MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    """Every configurable value of the Notes API, validated once at startup."""

    model_config = SettingsConfigDict(
        env_prefix="NOTES_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Notes API"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    cors_origins: list[str] = ["http://localhost:5173"]
    max_upload_bytes: int = Field(default=1_048_576, gt=0)
    http_timeout_seconds: float = Field(default=5.0, gt=0)
    database_url: SecretStr = SecretStr("postgresql+asyncpg://notes:notes@localhost:5432/notes")
    database_echo: bool = False  # log every SQL statement (development only)
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")

    # Authentication: an HS256 secret (required in production; a random one per process otherwise)
    jwt_secret: SecretStr | None = None
    jwt_issuer: str = "notes-api"
    jwt_audience: str = "notes-api"
    access_token_minutes: int = Field(default=15, ge=1)
    refresh_token_days: int = Field(default=14, ge=1)
    password_time_cost: int = Field(default=3, ge=1)  # Argon2id parameters (tests lower them)
    password_memory_kib: int = Field(default=65_536, ge=32)  # Argon2 needs 8 KiB per lane (4)
    login_rate_limit: int = Field(default=5, ge=1)  # attempts per window, per IP + email
    login_rate_window_seconds: int = Field(default=60, ge=1)
    cookie_secure: bool = True  # session cookie only over HTTPS (False for local HTTP)

    # Third-party login (OpenID Connect, Authorization Code + PKCE); disabled until configured
    oauth_client_id: str | None = None
    oauth_client_secret: SecretStr | None = None
    oauth_authorize_url: str | None = None
    oauth_token_url: str | None = None
    oauth_jwks_url: str | None = None
    oauth_issuer: str | None = None
    oauth_redirect_url: str = "http://localhost:8000/api/v1/auth/oauth/callback"

    # Background work, real time and caching (Unit 6.6)
    webhook_timeout_seconds: float = Field(default=5.0, gt=0)
    webhook_max_attempts: int = Field(default=5, ge=1)  # then the event is dead-lettered
    cache_ttl_seconds: int = Field(default=60, ge=1)
    ws_heartbeat_seconds: float = Field(default=20.0, gt=0)
    ws_connections_per_user: int = Field(default=5, ge=1)  # open sockets per user, all replicas

    # Per-user budgets per window on expensive routes (OWASP API4); a 429 when one is spent
    write_rate_limit: int = Field(default=120, ge=1)  # note, key and webhook writes; admin actions
    link_preview_rate_limit: int = Field(default=10, ge=1)  # each call fetches up to 5 URLs
    export_rate_limit: int = Field(default=5, ge=1)  # POST /exports and GET /admin/export
    user_rate_window_seconds: int = Field(default=60, ge=1)
    export_ttl_seconds: int = Field(default=3600, ge=60)

    # Observability (Unit 6.7)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = True  # one JSON object per line; False: coloured console output
    metrics_enabled: bool = (
        True  # GET /metrics (keep it off the public internet: the proxy blocks it)
    )
    otel_exporter: Literal["none", "console", "otlp", "memory"] = "none"
    otel_endpoint: str = "http://localhost:4318/v1/traces"  # OTLP over HTTP (a collector)
    sentry_dsn: SecretStr | None = None  # error tracking is off unless a DSN is configured
    check_migrations: bool = True  # /health/startup: the database must be at the newest revision

    @property
    def oauth_enabled(self) -> bool:
        """True when every OpenID Connect setting is present."""
        required = (self.oauth_client_id, self.oauth_authorize_url, self.oauth_token_url)
        return all(required) and bool(self.oauth_jwks_url and self.oauth_issuer)

    @model_validator(mode="after")
    def require_real_secrets_in_production(self) -> Settings:
        """Refuse to start in production with a missing or weak JWT secret or insecure cookies."""
        if self.environment != "production":
            return self
        secret = None if self.jwt_secret is None else self.jwt_secret.get_secret_value()
        if secret is None or secret in PLACEHOLDER_SECRETS or len(secret) < MIN_JWT_SECRET_LENGTH:
            raise ValueError(
                f"NOTES_JWT_SECRET must be a random secret of at least {MIN_JWT_SECRET_LENGTH} "
                "characters in production"
            )
        if not self.cookie_secure:
            raise ValueError("NOTES_COOKIE_SECURE must be true in production")
        return self


@lru_cache
def get_settings() -> Settings:
    """The process-wide settings, read from the environment once and then cached."""
    return Settings()
'''

NOTES_V6_CORE_LOGGING_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/core/logging.py
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
'''

NOTES_V6_CORE_METRICS_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/core/metrics.py
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
'''

NOTES_V6_CORE_TRACING_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/core/tracing.py
"""OpenTelemetry tracing: auto-instrumented FastAPI spans plus our own, sent to an exporter.

Each app gets its own TracerProvider (on app.state), instead of the process-global one, so
tests and notebooks can build many apps. NOTES_OTEL_EXPORTER picks where spans go:
"none" (default), "console", "otlp" (an OpenTelemetry Collector, Jaeger, Tempo...) or
"memory" (kept on app.state.span_exporter, for tests).
"""

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Tracer

from notes_api import __version__
from notes_api.core.config import Settings

NOT_TRACED = "health,metrics"  # comma-separated URL patterns the instrumentation skips


def make_exporter(settings: Settings) -> SpanExporter | None:
    """The span exporter the settings ask for (None: tracing off)."""
    if settings.otel_exporter == "console":
        return ConsoleSpanExporter()
    if settings.otel_exporter == "memory":
        return InMemorySpanExporter()
    if settings.otel_exporter == "otlp":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        return OTLPSpanExporter(endpoint=settings.otel_endpoint, timeout=5)
    return None


def install_tracing(app: FastAPI, settings: Settings) -> Tracer:
    """Instrument the app (call it last: the tracing middleware must be the outermost)."""
    resource = Resource.create(
        {
            "service.name": "notes-api",
            "service.version": __version__,
            "deployment.environment": settings.environment,
        }
    )
    provider = TracerProvider(resource=resource)
    exporter = make_exporter(settings)
    if exporter is not None:
        # Batch in production (spans leave in the background); one by one for tests and demos
        batched = settings.otel_exporter == "otlp"
        provider.add_span_processor(
            BatchSpanProcessor(exporter) if batched else SimpleSpanProcessor(exporter)
        )
        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider, excluded_urls=NOT_TRACED)
    app.state.tracer_provider = provider
    app.state.span_exporter = exporter
    return provider.get_tracer("notes_api")
'''

NOTES_V6_CORE_SENTRY_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/core/sentry.py
"""Error tracking with Sentry: off unless NOTES_SENTRY_DSN is set; secrets are scrubbed first."""

import importlib.util
import logging
from typing import Any

from notes_api import __version__
from notes_api.core.config import Settings
from notes_api.core.logging import redact_value

logger = logging.getLogger("notes_api.sentry")


def scrub_event(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any]:
    """before_send hook: redact headers, cookies, bodies and messages before they leave."""
    request = event.get("request", {})
    for part in ("headers", "cookies", "data", "query_string"):
        if isinstance(request.get(part), dict):
            request[part] = {key: redact_value(key, value) for key, value in request[part].items()}
        elif isinstance(request.get(part), str):
            request[part] = redact_value(part, request[part])
    if isinstance(event.get("logentry"), dict):
        event["logentry"] = redact_value("logentry", event["logentry"])
    return event


def install_sentry(settings: Settings, transport: Any = None) -> bool:
    """Initialise the Sentry SDK (FastAPI integration auto-enabled); False when disabled."""
    if settings.sentry_dsn is None:
        return False
    if importlib.util.find_spec("sentry_sdk") is None:
        logger.warning("NOTES_SENTRY_DSN is set but sentry-sdk is not installed")
        return False
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn.get_secret_value(),
        environment=settings.environment,
        release=f"notes-api@{__version__}",
        traces_sample_rate=0.0,  # tracing goes to OpenTelemetry
        before_send=scrub_event,  # the SDK's defaults send no IPs or cookies; this scrubs the rest
        transport=transport,  # tests pass a fake; production sends to the DSN
    )
    return True
'''

NOTES_V6_CORE_ERRORS_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/core/errors.py
"""Domain errors and RFC 9457 Problem Details responses for every error the API returns."""

import re
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from notes_api.core.middleware import REQUEST_ID_HEADER
from notes_api.exceptions import DomainError

PROBLEM_JSON = "application/problem+json"


class ProblemDetail(BaseModel):
    """The RFC 9457 body (used for the OpenAPI docs; responses are built as dicts)."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    request_id: str | None = None
    errors: list[dict[str, Any]] | None = None


def problem_response(
    request: Request,
    status_code: int,
    detail: str | None = None,
    *,
    problem_type: str | None = None,
    title: str | None = None,
    headers: dict[str, str] | None = None,
    **extra: Any,
) -> JSONResponse:
    """Build an application/problem+json response; the request id links it to the logs."""
    request_id = getattr(request.state, "request_id", None)
    body = {
        "type": f"/problems/{problem_type}" if problem_type else "about:blank",
        "title": title or HTTPStatus(status_code).phrase,
        "status": status_code,
        "detail": detail,
        "instance": request.url.path,
        "request_id": request_id,
        **extra,
    }
    all_headers = {**(headers or {}), **({REQUEST_ID_HEADER: request_id} if request_id else {})}
    return JSONResponse(
        {key: value for key, value in body.items() if value is not None},
        status_code=status_code,
        media_type=PROBLEM_JSON,
        headers=all_headers,
    )


async def domain_error_handler(request: Request, error: DomainError) -> JSONResponse:
    """DomainError subclasses → their own status, type and title."""
    return problem_response(
        request,
        error.status_code,
        str(error),
        problem_type=error.problem_type,
        title=error.title,
        headers=error.headers or None,
    )


def allowed_methods(app: FastAPI, path: str) -> list[str]:
    """Every documented method of the paths matching this URL path.

    FastAPI has one route per method, so Starlette's own 405 lists only the first matching
    route's methods; the OpenAPI document knows them all.
    """
    paths = app.openapi().get("paths", {})
    if path in paths:  # a literal path wins over templates (/notes/feed vs /notes/{note_id})
        return sorted(method.upper() for method in paths[path])
    methods: set[str] = set()
    for template, operations in paths.items():
        if re.fullmatch(re.sub(r"\{[^/]+\}", "[^/]+", template), path):
            methods |= {method.upper() for method in operations}
    return sorted(methods)


async def http_error_handler(request: Request, error: StarletteHTTPException) -> JSONResponse:
    """HTTPException (ours, and Starlette's 404/405) → Problem Details."""
    detail = error.detail if isinstance(error.detail, str) else None
    headers = dict(error.headers or {})
    if error.status_code == HTTPStatus.METHOD_NOT_ALLOWED:
        documented = allowed_methods(request.app, request.url.path)
        if documented:
            headers["Allow"] = ", ".join(documented)
    return problem_response(request, error.status_code, detail, headers=headers or None)


async def validation_error_handler(request: Request, error: RequestValidationError) -> JSONResponse:
    """422 with one entry per problem (location, message, type), without echoing input."""
    problems = [
        {"loc": list(problem["loc"]), "msg": problem["msg"], "type": problem["type"]}
        for problem in error.errors()
    ]
    return problem_response(
        request,
        HTTPStatus.UNPROCESSABLE_CONTENT,
        f"{len(problems)} validation error(s)",
        problem_type="validation-error",
        title="Invalid request",
        errors=problems,
    )


async def integrity_error_handler(request: Request, error: IntegrityError) -> JSONResponse:
    """A constraint the database enforced (unique, foreign key) → 409, without SQL details."""
    return problem_response(
        request,
        HTTPStatus.CONFLICT,
        "the change conflicts with existing data",
        problem_type="conflict",
        title="Conflict",
    )


async def unhandled_error_handler(request: Request, error: Exception) -> JSONResponse:
    """Any other exception → a generic 500; details stay in the server log."""
    return problem_response(request, HTTPStatus.INTERNAL_SERVER_ERROR, "unexpected error")


def install_error_handlers(app: FastAPI) -> None:
    """Register every handler on the app."""
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    document_problem_responses(app)


def document_problem_responses(app: FastAPI) -> None:
    """Make the OpenAPI document tell the truth: every 4xx/5xx body is application/problem+json.

    FastAPI documents its 422 as application/json (HTTPValidationError); our handlers send
    RFC 9457 problems instead. Contract tests (Schemathesis) caught the mismatch.
    """
    generate = app.openapi

    def openapi_with_problems() -> dict[str, Any]:
        """Generate once, rewrite the error responses, cache."""
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = generate()
        problem = {"schema": {"$ref": "#/components/schemas/ProblemDetail"}}
        schema.setdefault("components", {}).setdefault("schemas", {})["ProblemDetail"] = (
            ProblemDetail.model_json_schema(ref_template="#/components/schemas/{model}")
        )
        for path_item in schema.get("paths", {}).values():
            for operation in path_item.values():
                responses = operation.setdefault("responses", {})
                if "requestBody" in operation:  # a body that is not valid JSON
                    responses.setdefault("400", {"description": "Malformed request body."})
                for code, response in responses.items():
                    if code[0] in "45":
                        response["content"] = {PROBLEM_JSON: problem}
        for unused in ("HTTPValidationError", "ValidationError"):
            schema["components"]["schemas"].pop(unused, None)
        app.openapi_schema = schema
        return schema

    app.openapi = openapi_with_problems  # type: ignore[method-assign]
'''

NOTES_V6_CORE_LIFESPAN_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/core/lifespan.py
"""Startup and shutdown: create shared resources once and keep them on app.state."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as redis_asyncio
from arq.connections import ArqRedis
from fastapi import FastAPI

from notes_api import __version__
from notes_api.core.config import Settings
from notes_api.db import create_engine_from_settings, make_session_factory
from notes_api.netguard import public_only_client


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the database pool, Redis (text and queue clients) and an HTTP client; close them."""
    settings: Settings = app.state.settings
    engine = create_engine_from_settings(settings)  # connects lazily, on first use
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.redis = redis_asyncio.from_url(  # also lazy: no connection until the first command
        settings.redis_url.get_secret_value(), decode_responses=True
    )
    # The ARQ client (bytes, pickled jobs) for enqueuing background work; lazy as well
    app.state.queue = ArqRedis.from_url(settings.redis_url.get_secret_value())
    try:
        async with (
            httpx.AsyncClient(
                timeout=settings.http_timeout_seconds,
                follow_redirects=False,  # a redirect could lead a fetch somewhere private
                headers={"User-Agent": f"notes-api/{__version__}"},
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            ) as http_client,
            public_only_client(
                settings.http_timeout_seconds, f"notes-api/{__version__}"
            ) as outbound_client,
        ):
            app.state.http_client = http_client  # configured endpoints (the OIDC provider)
            app.state.outbound_client = outbound_client  # user-supplied URLs (link previews)
            yield
    finally:
        await app.state.queue.aclose()
        await app.state.redis.aclose()
        await engine.dispose()  # close every pooled database connection
        app.state.tracer_provider.shutdown()  # flush spans still waiting in the exporter
'''

NOTES_V6_DB_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/db.py
"""Database plumbing: naming conventions, the declarative base, the engine and sessions."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, event
from sqlalchemy.engine import Dialect
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator

from notes_api.core.config import Settings

# Predictable constraint names, so Alembic can find (and drop) them later.
SCHEMA_REVISIONS = ("0001", "0002", "0003", "0004", "0005", "0006")  # this code's migrations
SCHEMA_REVISION = SCHEMA_REVISIONS[-1]  # the revision it expects (/health/startup checks it)

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UTCDateTime(TypeDecorator[datetime]):
    """A timezone-aware timestamp stored in UTC (SQLite's naive values come back as UTC)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        """Refuse naive datetimes; convert aware ones to UTC."""
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime: pass an aware one (UTC)")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        """Attach UTC to naive values (SQLite has no time zone type)."""
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class Base(DeclarativeBase):
    """Base class of every model: shared metadata and type mapping."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {datetime: UTCDateTime}


def enable_sqlite_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
    """SQLite ignores foreign keys (and ON DELETE CASCADE) unless each connection opts in."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_engine_from_settings(settings: Settings) -> AsyncEngine:
    """An async engine: a connection pool for PostgreSQL, foreign keys switched on for SQLite."""
    url = settings.database_url.get_secret_value()
    if url.startswith("sqlite"):
        engine = create_async_engine(url, echo=settings.database_echo)
        event.listen(engine.sync_engine, "connect", enable_sqlite_foreign_keys)
        return engine
    return create_async_engine(
        url,
        echo=settings.database_echo,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,  # replace connections the server closed while idle
    )


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Sessions whose objects stay readable after commit (the response is built after it)."""
    return async_sessionmaker(engine, expire_on_commit=False)
'''

NOTES_V6_ROUTERS_HEALTH_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/routers/health.py
"""Probes for orchestrators (Kubernetes, Compose, load balancers).

- /health and /health/live: liveness. The process answers; no dependency is touched, so a
  database outage never makes the orchestrator restart every API process.
- /health/ready: readiness. The database and Redis answer; until then, send no traffic here.
- /health/startup: startup. The database schema is at the revision this code needs, or newer.

Probe answers are public, so a failed check says only "unavailable"; the reason goes to the log.
"""

import asyncio
import logging

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from notes_api.db import SCHEMA_REVISION, SCHEMA_REVISIONS
from notes_api.dependencies import RedisDep, SettingsDep

router = APIRouter(tags=["health"])
logger = logging.getLogger("notes_api.health")
CHECK_TIMEOUT_SECONDS = 2.0


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe kept from v1 (load balancers often expect /health)."""
    return {"status": "ok"}


@router.get("/health/live")
async def live() -> dict[str, str]:
    """Liveness probe: the process answers (no database or Redis call)."""
    return {"status": "ok"}


async def database_revision(request: Request) -> str | None:
    """SELECT 1, then the Alembic revision (None when the table does not exist)."""
    async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
        async with request.app.state.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            try:
                result = await connection.execute(text("SELECT version_num FROM alembic_version"))
            except Exception:  # no migrations table (a schema made by create_all)
                return None
            return result.scalar_one_or_none()


def report(checks: dict[str, str]) -> JSONResponse:
    """200 when every check says ok, else 503; the body lists each check."""
    healthy = all(value == "ok" for value in checks.values())
    code = status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse({"status": "ok" if healthy else "unavailable", "checks": checks}, code)


@router.get("/health/ready")
async def ready(request: Request, redis: RedisDep) -> JSONResponse:
    """Readiness probe: 503 until the database and Redis both answer."""
    checks = {}
    try:
        await database_revision(request)
        checks["database"] = "ok"
    except Exception:
        logger.warning("readiness: database check failed", exc_info=True)
        checks["database"] = "unavailable"
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
            await redis.ping()
        checks["redis"] = "ok"
    except Exception:
        logger.warning("readiness: redis check failed", exc_info=True)
        checks["redis"] = "unavailable"
    return report(checks)


@router.get("/health/startup")
async def startup(request: Request, settings: SettingsDep) -> JSONResponse:
    """Startup probe: the schema is at SCHEMA_REVISION or newer (when the check is enabled)."""
    try:
        revision = await database_revision(request)
    except Exception:
        logger.warning("startup: database check failed", exc_info=True)
        return report({"database": "unavailable"})
    if not settings.check_migrations:
        return report({"database": "ok", "migrations": "ok"})
    return report({"database": "ok", "migrations": migration_state(revision)})


def migration_state(revision: str | None) -> str:
    """Ok at this code's revision or at one it does not know (a newer release migrated, then
    was rolled back: expand/contract keeps this code working); else what is missing."""
    if revision == SCHEMA_REVISION or (revision is not None and revision not in SCHEMA_REVISIONS):
        return "ok"
    return f"at {revision}, need {SCHEMA_REVISION}"
'''

NOTES_V6_MAIN_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/main.py
"""The Notes API application factory.

create_app() wires settings, password hashing and token secrets, error handlers, middleware,
the lifespan (database, Redis, the ARQ queue, an HTTP client), the routers and observability:
JSON logs with request and trace ids, Prometheus metrics, OpenTelemetry tracing, optional
Sentry. The ARQ worker lives in worker.py. Serve it with `uvicorn notes_api.main:app`.
"""

from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles

from notes_api import __version__
from notes_api.core.config import PLACEHOLDER_SECRETS, Settings, get_settings
from notes_api.core.errors import install_error_handlers
from notes_api.core.lifespan import lifespan
from notes_api.core.logging import AccessLogMiddleware, configure_logging, install_redaction
from notes_api.core.metrics import MetricsMiddleware, metrics_endpoint
from notes_api.core.middleware import (
    REQUEST_ID_HEADER,
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
    TimingMiddleware,
)
from notes_api.core.sentry import install_sentry
from notes_api.core.tracing import install_tracing
from notes_api.routers import admin, auth, exports, health, notes, pages, realtime, users
from notes_api.routers.realtime import ConnectionManager
from notes_api.security import make_password_hasher, new_secret

PACKAGE_DIR = Path(__file__).resolve().parent
API_PREFIX = "/api/v1"


def operation_id(route: APIRoute) -> str:
    """Use the function name as the OpenAPI operationId (clean names in generated clients)."""
    return route.name


def install_middleware(app: FastAPI, settings: Settings) -> None:
    """Add middleware; the last one added is the outermost (it sees the request first)."""
    app.add_middleware(TimingMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER, "Location", "Server-Timing"],
        max_age=600,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(AccessLogMiddleware)  # inside RequestIdMiddleware: logs carry the id
    app.add_middleware(RequestIdMiddleware)


def install_security(app: FastAPI, settings: Settings) -> None:
    """The password hasher, a dummy hash (equal timing for unknown users) and the JWT secret."""
    hasher = make_password_hasher(settings.password_time_cost, settings.password_memory_kib)
    app.state.password_hasher = hasher
    app.state.dummy_hash = hasher.hash(new_secret())
    secret = settings.jwt_secret.get_secret_value() if settings.jwt_secret else ""
    if secret in PLACEHOLDER_SECRETS:  # dev/test only (production refuses to start without one)
        secret = new_secret(32)  # a random secret per process: tokens die on restart
    app.state.jwt_secret = secret
    install_redaction()


OPENAPI_TAGS = [
    {"name": "auth", "description": "Register, log in, refresh and log out."},
    {"name": "users", "description": "The current user and personal API keys."},
    {"name": "notes", "description": "Your notes (scopes notes:read / notes:write)."},
    {"name": "exports", "description": "Background exports with SSE progress."},
    {"name": "realtime", "description": "WebSocket live updates."},
    {"name": "admin", "description": "Bulk operations; admin role and scope."},
    {"name": "health", "description": "Liveness probe for load balancers and tests."},
]


def include_routers(app: FastAPI) -> None:
    """Health probes and pages at the root; everything else under /api/v1."""
    api_router = APIRouter(prefix=API_PREFIX)
    for module in (auth, users, notes, exports, realtime, admin):
        api_router.include_router(module.router)
    app.include_router(health.router)
    app.include_router(api_router)
    app.include_router(pages.router)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a fully wired app; tests pass their own Settings, servers use the environment."""
    settings = settings or get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        summary="Create, search and organize notes.",
        description="Built step by step in Phase 6 of the course. Errors are RFC 9457 problems.",
        debug=settings.debug,
        lifespan=lifespan,
        openapi_url=None if settings.environment == "production" else "/openapi.json",
        docs_url=None if settings.environment == "production" else "/docs",
        redoc_url=None if settings.environment == "production" else "/redoc",
        generate_unique_id_function=operation_id,
        openapi_tags=OPENAPI_TAGS,
    )
    app.state.settings = settings
    app.state.connections = ConnectionManager()
    configure_logging(settings.log_level, settings.log_json)
    install_sentry(settings)
    install_security(app, settings)
    install_error_handlers(app)
    install_middleware(app, settings)
    include_routers(app)
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
    if settings.metrics_enabled:
        app.add_route("/metrics", metrics_endpoint, include_in_schema=False)
    app.state.tracer = install_tracing(app, settings)  # last: its middleware is the outermost
    return app


app = create_app()
'''

NOTES_V6_SCHEMAS_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/schemas.py
"""Request and response schemas for the Notes API (Pydantic v2).

One schema per direction: NoteCreate (POST/PUT body), NoteUpdate (PATCH body, every field
optional), NoteRead (responses, with server-owned fields) and NoteFilters (query parameters).
Page envelopes live in pagination.py, error bodies in core/errors.py.
"""

import re
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    HttpUrl,
    StringConstraints,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic.json_schema import SkipJsonSchema

MAX_TAGS = 10
MAX_DB_INT = 2**31 - 1  # PostgreSQL INTEGER: larger ids, offsets or versions cannot exist


def require_slug(value: str) -> str:
    """Allow lowercase letters, digits and dashes (checked after stripping and lower-casing)."""
    if not re.fullmatch(r"[a-z0-9-]+", value):
        raise ValueError("tags use lowercase letters, digits and dashes")
    return value


def unique_in_order(tags: list[str]) -> list[str]:
    """Drop repeated tags, keeping the first occurrence."""
    return list(dict.fromkeys(tags))


def at_most(limit: int) -> Callable[[object], object]:
    """A before-validator: the raw string (before stripping) obeys the documented maxLength."""

    def check(value: object) -> object:
        """Reject over-long raw strings."""
        if isinstance(value, str) and len(value) > limit:
            raise ValueError(f"at most {limit} characters")
        return value

    return check


# The patterns put the rules into the OpenAPI schema (clients and Schemathesis see them):
# a title has a non-space character; a tag is letters, digits and dashes (stored lower-case).
Title = Annotated[
    str,
    BeforeValidator(at_most(200)),
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200, pattern=r"\S"),
]
Body = Annotated[str, Field(max_length=10_000)]
Tag = Annotated[
    str,
    StringConstraints(to_lower=True, min_length=1, max_length=30, pattern=r"^[A-Za-z0-9-]+$"),
    AfterValidator(require_slug),
]
Tags = Annotated[list[Tag], Field(max_length=MAX_TAGS)]
SortOrder = Literal["created_at", "-created_at", "updated_at", "-updated_at", "title", "-title"]


class NoteCreate(BaseModel):
    """Body of POST /notes and PUT /notes/{note_id}: every field a client may set."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,  # JSON types as documented: "pinned": 0 is not a boolean
        json_schema_extra={
            "examples": [{"title": "Buy tea", "body": "Assam, 500 g", "tags": ["shopping"]}]
        },
    )

    title: Title
    body: Body = ""
    tags: Tags = []
    pinned: bool = False

    @field_validator("tags")
    @classmethod
    def drop_duplicate_tags(cls, tags: list[str]) -> list[str]:
        """Keep each tag once."""
        return unique_in_order(tags)


class NoteUpdate(BaseModel):
    """Body of PATCH /notes/{note_id}: only the fields being changed."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        json_schema_extra={"examples": [{"pinned": True, "version": 1}]},
    )

    # Optional but not nullable: SkipJsonSchema keeps None out of the documented schema, which
    # must match what the validator below accepts (Schemathesis found the mismatch).
    title: Title | SkipJsonSchema[None] = None
    body: Body | SkipJsonSchema[None] = None
    tags: Tags | SkipJsonSchema[None] = None
    pinned: bool | SkipJsonSchema[None] = None
    version: Annotated[
        Annotated[int, Field(ge=1, le=MAX_DB_INT)] | SkipJsonSchema[None],
        Field(description="The version you read; a mismatch is a 409."),
    ] = None

    @field_validator("tags")
    @classmethod
    def drop_duplicate_tags(cls, tags: list[str] | None) -> list[str] | None:
        """Keep each tag once."""
        return None if tags is None else unique_in_order(tags)

    @model_validator(mode="after")
    def reject_explicit_null(self) -> NoteUpdate:
        """None means "not sent"; an explicit null is an error (no field is nullable)."""
        nulled = sorted(name for name in self.model_fields_set if getattr(self, name) is None)
        if nulled:
            raise ValueError(f"fields cannot be null: {', '.join(nulled)}")
        return self


class NoteRead(BaseModel):
    """A note as the API returns it."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    body: str
    tags: list[str]
    pinned: bool
    version: int
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def word_count(self) -> int:
        """Words in the body (derived, never stored)."""
        return len(self.body.split())


class NoteFilters(BaseModel):
    """Query parameters of GET /notes: filtering, sorting and pagination."""

    model_config = ConfigDict(extra="forbid")

    q: Annotated[str | None, Field(max_length=100, description="Text in title or body.")] = None
    tag: Annotated[list[Tag], Field(description="Only notes that have all these tags.")] = []
    pinned: bool | None = None
    sort: SortOrder = "-created_at"
    limit: Annotated[int, Field(ge=1, le=100)] = 20
    offset: Annotated[int, Field(ge=0, le=MAX_DB_INT)] = 0


class FeedParams(BaseModel):
    """Query parameters of GET /notes/feed: keyset (cursor) pagination, newest first."""

    model_config = ConfigDict(extra="forbid")

    cursor: Annotated[str | None, Field(description="next_cursor from the previous page.")] = None
    limit: Annotated[int, Field(ge=1, le=100)] = 20


class LinkPreview(BaseModel):
    """The title of one link found in a note's body (or why it could not be fetched)."""

    url: str
    status_code: int | None = None
    title: str | None = None
    error: str | None = None


class ImportReport(BaseModel):
    """Result of POST /admin/import."""

    filename: str
    imported: int
    ids: list[int]


ScopeName = Literal["notes:read", "notes:write", "admin"]


class UserCreate(BaseModel):
    """Body of POST /auth/register. The role is never accepted from clients (OWASP API3)."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: Annotated[str, Field(min_length=12, max_length=128)]


class UserRead(BaseModel):
    """A user as the API shows it: no password hash, no internal flags."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: str
    created_at: datetime


class TokenPair(BaseModel):
    """The OAuth 2.0 token response (RFC 6749 section 5.1) plus our refresh token."""

    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    scope: str


class RefreshRequest(BaseModel):
    """Body of POST /auth/refresh and /auth/logout."""

    model_config = ConfigDict(extra="forbid")

    refresh_token: Annotated[str, Field(min_length=10, max_length=200)]


class ApiKeyCreate(BaseModel):
    """Body of POST /users/me/api-keys."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    scopes: Annotated[list[ScopeName], Field(min_length=1)] = ["notes:read"]


class ApiKeyRead(BaseModel):
    """An API key without its secret."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    prefix: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None

    @field_validator("scopes", mode="before")
    @classmethod
    def split_scopes(cls, value: object) -> object:
        """The database stores scopes space-separated."""
        return value.split() if isinstance(value, str) else value


class ApiKeyCreated(ApiKeyRead):
    """The response to creating a key: the only time the full key is shown."""

    key: str


class WebhookSettings(BaseModel):
    """Body of PUT /users/me/webhook."""

    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
'''

NOTES_V6_ROUTERS_NOTES_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/routers/notes.py
"""/api/v1/notes: CRUD, search, a keyset feed, link previews; ETags and a Redis cache."""

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Header, Path, Query, Request, Response, status

from notes_api.core.errors import PROBLEM_JSON, ProblemDetail
from notes_api.dependencies import (
    LINK_PREVIEW_LIMIT,
    NOTE_WRITE_LIMIT,
    LinkPreviewerDep,
    NoteCacheDep,
    QueueDep,
    ReaderServiceDep,
    WriterServiceDep,
    kick_relay,
)
from notes_api.exceptions import NoteNotFoundError
from notes_api.models import Note
from notes_api.pagination import CursorPage, Page
from notes_api.schemas import (
    MAX_DB_INT,
    FeedParams,
    LinkPreview,
    NoteCreate,
    NoteFilters,
    NoteRead,
    NoteUpdate,
)

NoteId = Annotated[int, Path(ge=1, le=MAX_DB_INT, description="The note's id.")]


def problem(description: str) -> dict[str, Any]:
    """An OpenAPI response entry for an RFC 9457 problem."""
    return {"model": ProblemDetail, "description": description, "content": {PROBLEM_JSON: {}}}


NOT_FOUND: dict[int | str, dict[str, Any]] = {404: problem("No note has this id.")}
WRITE_ERRORS: dict[int | str, dict[str, Any]] = {
    **NOT_FOUND,
    409: problem("Version conflict: someone changed the note; read it again."),
}
AUTH_ERRORS: dict[int | str, dict[str, Any]] = {
    401: problem("Missing, invalid or expired credentials."),
    403: problem("The token lacks the scope this operation needs."),
}
CACHE_CONTROL = "private, no-cache"  # browsers may keep it, but must revalidate (ETag) first

# Every route needs a user (scopes below). {note_id:int}: "/notes/feed" never matches an id route.
router = APIRouter(prefix="/notes", tags=["notes"], responses=AUTH_ERRORS)


def etag_of(note: dict[str, Any]) -> str:
    """A strong validator: the version changes on every update."""
    return f'"{note["id"]}-{note["version"]}"'


def matches(if_none_match: str | None, etag: str) -> bool:
    """True if the client's If-None-Match lists this ETag (or '*')."""
    if not if_none_match:
        return False
    candidates = {item.strip().removeprefix("W/") for item in if_none_match.split(",")}
    return etag in candidates or "*" in candidates


def after_write(background: BackgroundTasks, queue: Any, cache: Any, note_id: int | None) -> None:
    """After the response (so after the commit): drop the cached copy again, wake the relay."""
    if note_id is not None:
        background.add_task(cache.invalidate, note_id)
    background.add_task(kick_relay, queue)


@router.post(
    "",
    response_model=NoteRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[NOTE_WRITE_LIMIT],
)
async def create_note(
    note: NoteCreate,
    service: WriterServiceDep,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    queue: QueueDep,
    cache: NoteCacheDep,
) -> Note:
    """Create a note; the Location header points at it."""
    created = await service.create(note)
    response.headers["Location"] = request.app.url_path_for("get_note", note_id=str(created.id))
    after_write(background, queue, cache, None)
    return created


@router.get("", response_model=Page[NoteRead])
async def list_notes(
    filters: Annotated[NoteFilters, Query()], service: ReaderServiceDep, response: Response
) -> dict[str, object]:
    """Search, filter, sort and paginate notes (offset pagination)."""
    notes, total = await service.search(filters)
    response.headers["Cache-Control"] = "private, no-store"  # lists change constantly
    return {"items": notes, "total": total, "limit": filters.limit, "offset": filters.offset}


@router.get(
    "/feed",
    response_model=CursorPage[NoteRead],
    responses={400: problem("The cursor is not one this API issued.")},
)
async def notes_feed(
    params: Annotated[FeedParams, Query()], service: ReaderServiceDep
) -> dict[str, object]:
    """Newest notes first, with keyset (cursor) pagination."""
    notes, next_cursor = await service.feed(params.limit, params.cursor)
    return {"items": notes, "limit": params.limit, "next_cursor": next_cursor}


@router.get(
    "/{note_id:int}",
    response_model=NoteRead,
    responses={**NOT_FOUND, 304: {"description": "Not modified (If-None-Match matched)."}},
)
async def get_note(
    note_id: NoteId,
    service: ReaderServiceDep,
    cache: NoteCacheDep,
    response: Response,
    if_none_match: Annotated[str | None, Header()] = None,
) -> Any:
    """Fetch one note through the cache; 304 when the client's copy is current."""
    cached = await cache.get_or_load(note_id, lambda: service.load_for_cache(note_id))
    if cached is None or cached["owner_id"] != service.owner_id:  # authorize after the cache
        raise NoteNotFoundError(note_id)
    note, etag = cached["note"], etag_of(cached["note"])
    headers = {"ETag": etag, "Cache-Control": CACHE_CONTROL}
    if matches(if_none_match, etag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    response.headers.update(headers)
    return note


@router.put(
    "/{note_id:int}",
    response_model=NoteRead,
    responses=WRITE_ERRORS,
    dependencies=[NOTE_WRITE_LIMIT],
)
async def replace_note(
    note_id: NoteId,
    note: NoteCreate,
    service: WriterServiceDep,
    background: BackgroundTasks,
    queue: QueueDep,
    cache: NoteCacheDep,
) -> Note:
    """Replace every field of a note (omitted fields get their defaults)."""
    replaced = await service.replace(note_id, note)  # 404 for someone else's note first
    await cache.invalidate(note_id)  # now (a reader could still re-cache the old row) ...
    after_write(background, queue, cache, note_id)  # ... so once more after the commit
    return replaced


@router.patch(
    "/{note_id:int}",
    response_model=NoteRead,
    responses=WRITE_ERRORS,
    dependencies=[NOTE_WRITE_LIMIT],
)
async def update_note(
    note_id: NoteId,
    changes: NoteUpdate,
    service: WriterServiceDep,
    background: BackgroundTasks,
    queue: QueueDep,
    cache: NoteCacheDep,
) -> Note:
    """Change only the fields sent in the body."""
    updated = await service.update(note_id, changes)
    await cache.invalidate(note_id)
    after_write(background, queue, cache, note_id)
    return updated


@router.delete(
    "/{note_id:int}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=NOT_FOUND,
    dependencies=[NOTE_WRITE_LIMIT],
)
async def delete_note(
    note_id: NoteId,
    service: WriterServiceDep,
    background: BackgroundTasks,
    queue: QueueDep,
    cache: NoteCacheDep,
) -> None:
    """Delete a note."""
    await service.delete(note_id)
    await cache.invalidate(note_id)
    after_write(background, queue, cache, note_id)


@router.get(
    "/{note_id:int}/links",
    response_model=list[LinkPreview],
    responses=NOT_FOUND,
    dependencies=[LINK_PREVIEW_LIMIT],
)
async def note_links(
    note_id: NoteId, service: ReaderServiceDep, previewer: LinkPreviewerDep
) -> list[LinkPreview]:
    """Titles of the links in a note's body, fetched with the shared HTTP client."""
    note = await service.get(note_id)
    return await previewer.previews(note.body)
'''

NOTES_V6_CACHE_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/cache.py
"""Cache-aside for single notes in Redis: TTL with jitter, invalidation, stampede protection.

Each lookup is a span (cache.get_or_load, attribute cache.hit) and a Prometheus count.
"""

import asyncio
import json
import random
from collections.abc import Awaitable, Callable
from typing import Any

from opentelemetry import trace
from redis.asyncio import Redis

from notes_api.core.metrics import CACHE_LOOKUPS

KEY_PREFIX = "notes:v5"  # bump the version when the cached shape changes
STATS_KEY = f"{KEY_PREFIX}:cache-stats"
LOCK_MILLISECONDS = 2000
WAIT_STEPS = 10


def note_key(note_id: int) -> str:
    """notes:v5:note:<id>: namespace, schema version, entity, id."""
    return f"{KEY_PREFIX}:note:{note_id}"


class NoteCache:
    """Read-through helper; the loader returns a JSON-able dict, or None for 'no such note'."""

    def __init__(
        self,
        redis: Redis,
        ttl_seconds: int,
        rng: random.Random | None = None,
        tracer: trace.Tracer | None = None,
    ) -> None:
        """Keep the client, the base TTL and the tracer (a no-op one by default)."""
        self.redis = redis
        self.ttl_seconds = ttl_seconds
        self.rng = rng or random.Random()
        self.tracer = tracer or trace.NoOpTracer()

    def ttl(self) -> int:
        """The base TTL ±10 %, so keys written together do not all expire together."""
        spread = max(1, self.ttl_seconds // 10)
        return self.ttl_seconds + self.rng.randint(-spread, spread)

    async def get_or_load(
        self, note_id: int, loader: Callable[[], Awaitable[dict[str, Any] | None]]
    ) -> dict[str, Any] | None:
        """Cached value, or load it once (one loader per key at a time) and cache it."""
        with self.tracer.start_as_current_span("cache.get_or_load") as span:
            span.set_attribute("note.id", note_id)
            key = note_key(note_id)
            hit = (cached := await self.redis.get(key)) is not None
            span.set_attribute("cache.hit", hit)
            CACHE_LOOKUPS.labels("hit" if hit else "miss").inc()
            await self.redis.hincrby(STATS_KEY, "hits" if hit else "misses", 1)
            if cached is not None:
                return json.loads(cached)
            return await self._load(key, loader)

    async def _load(
        self, key: str, loader: Callable[[], Awaitable[dict[str, Any] | None]]
    ) -> dict[str, Any] | None:
        """A miss: load under a short lock so concurrent misses do not all hit the database."""
        lock = f"{key}:lock"
        if await self.redis.set(lock, "1", nx=True, px=LOCK_MILLISECONDS):
            try:
                value = await loader()
                if value is not None:
                    await self.redis.set(key, json.dumps(value), ex=self.ttl())
                return value
            finally:
                await self.redis.delete(lock)
        for _ in range(WAIT_STEPS):  # someone else is loading: wait briefly for their result
            await asyncio.sleep(LOCK_MILLISECONDS / 1000 / WAIT_STEPS / 4)
            if (cached := await self.redis.get(key)) is not None:
                return json.loads(cached)
        return await loader()  # give up waiting: correctness first

    async def invalidate(self, note_id: int) -> None:
        """Delete the cached copy (called before and again after the database commit)."""
        await self.redis.delete(note_key(note_id))

    async def stats(self) -> dict[str, float]:
        """Hits, misses and the hit rate since the counters were last reset."""
        raw = await self.redis.hgetall(STATS_KEY)
        hits, misses = int(raw.get("hits", 0)), int(raw.get("misses", 0))
        total = hits + misses
        return {
            "hits": hits,
            "misses": misses,
            "hit_rate": round(hits / total, 3) if total else 0.0,
        }
'''

NOTES_V6_DEPENDENCIES_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/dependencies.py
"""Dependencies shared by the routers, as Annotated aliases. A notes request resolves as:

ReaderServiceDep ── Security(get_note_service, ["notes:read"])
                      ├─ get_note_repository ─ get_session
                      ├─ get_clock
                      └─ get_current_principal (receives the accumulated scopes)
get_current_principal ─┬─ OAuth2PasswordBearer (Authorization: Bearer ...)
                       ├─ APIKeyHeader (X-API-Key)
                       └─ get_auth_service ─ get_session, get_redis, app.state
"""

import contextlib
import time
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timedelta
from typing import Annotated, Any

import httpx
from arq.connections import ArqRedis
from fastapi import Depends, Request, Security
from fastapi.requests import HTTPConnection
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer, SecurityScopes
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from notes_api.auth import AuthService
from notes_api.cache import NoteCache
from notes_api.core.config import Settings
from notes_api.exceptions import AuthenticationError, PermissionDeniedError, RateLimitedError
from notes_api.mailer import LogMailer, Mailer
from notes_api.models import utc_now
from notes_api.netguard import Resolver, resolve_host
from notes_api.oauth import OidcClient
from notes_api.ratelimit import FixedWindowRateLimiter
from notes_api.repositories import NoteRepository, SqlNoteRepository, SqlUserRepository
from notes_api.security import ALL_SCOPES, Principal, TokenService
from notes_api.services import LinkPreviewer, NoteService


def get_app_settings(connection: HTTPConnection) -> Settings:
    """The settings this app was created with (HTTPConnection: works for WebSockets too)."""
    return connection.app.state.settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session and one transaction per request: commit on success, roll back on error."""
    async with request.app.state.session_factory() as session, session.begin():
        yield session


# scope="function": commit before the response is sent, so a failed commit is a 500/409,
# never a 200 for data that was not saved (the default scope would commit after sending).
SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]


def get_redis(connection: HTTPConnection) -> Redis:
    """The Redis client the lifespan created (tests override this with fakeredis)."""
    return connection.app.state.redis


def get_clock() -> Callable[[], datetime]:
    """The clock for timestamps (tests override it with dependency_overrides)."""
    return utc_now


def get_http_client(request: Request) -> httpx.AsyncClient:
    """The pooled HTTP client the lifespan created."""
    return request.app.state.http_client


def get_resolver() -> Resolver:
    """DNS resolution for link previews (tests override it: no real DNS in tests)."""
    return resolve_host


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
RedisDep = Annotated[Redis, Depends(get_redis)]
ClockDep = Annotated[Callable[[], datetime], Depends(get_clock)]
HttpClientDep = Annotated[httpx.AsyncClient, Depends(get_http_client)]


def get_note_repository(session: SessionDep) -> NoteRepository:
    """The SQL repository on this request's session."""
    return SqlNoteRepository(session)


RepositoryDep = Annotated[NoteRepository, Depends(get_note_repository)]


def get_auth_service(
    request: Request, session: SessionDep, redis: RedisDep, settings: SettingsDep, clock: ClockDep
) -> AuthService:
    """An AuthService on this request's session, with the app-wide hasher and secret."""
    tokens = TokenService(
        request.app.state.jwt_secret,
        settings.jwt_issuer,
        settings.jwt_audience,
        timedelta(minutes=settings.access_token_minutes),
        clock,
    )
    return AuthService(
        SqlUserRepository(session),
        tokens,
        request.app.state.password_hasher,
        request.app.state.dummy_hash,
        redis,
        request.app.state.session_factory,
        timedelta(days=settings.refresh_token_days),
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


SESSION_COOKIE = "notes_session"
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/token", scopes=ALL_SCOPES, auto_error=False
)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_current_principal(
    security_scopes: SecurityScopes,
    auth: AuthServiceDep,
    token: Annotated[str | None, Depends(oauth2_scheme)],
    api_key: Annotated[str | None, Depends(api_key_header)],
) -> Principal:
    """Authenticate with a bearer token or an API key, then check the required scopes."""
    if token:
        principal = await auth.principal_from_access_token(token)
    elif api_key:
        principal = await auth.principal_from_api_key(api_key)
    else:
        raise AuthenticationError("not authenticated", security_scopes.scopes)
    missing = set(security_scopes.scopes) - principal.scopes
    if missing:
        raise PermissionDeniedError(f"missing scope(s): {' '.join(sorted(missing))}")
    return principal


CurrentPrincipal = Annotated[Principal, Security(get_current_principal)]


async def require_admin(
    principal: Annotated[Principal, Security(get_current_principal, scopes=["admin"])],
) -> Principal:
    """Role check on top of the scope check (OWASP API5: function-level authorization)."""
    if principal.role != "admin":
        raise PermissionDeniedError("admin role required")
    return principal


AdminPrincipal = Annotated[Principal, Depends(require_admin)]


def get_note_service(
    repository: RepositoryDep, clock: ClockDep, principal: CurrentPrincipal
) -> NoteService:
    """A NoteService limited to the caller's notes; route scopes flow down to the principal."""
    return NoteService(repository, clock, principal.user_id)


ReaderServiceDep = Annotated[NoteService, Security(get_note_service, scopes=["notes:read"])]
WriterServiceDep = Annotated[NoteService, Security(get_note_service, scopes=["notes:write"])]


def get_link_previewer(
    request: Request, resolver: Annotated[Resolver, Depends(get_resolver)]
) -> LinkPreviewer:
    """A LinkPreviewer on the public-only client (it refuses private addresses on connect)."""
    return LinkPreviewer(request.app.state.outbound_client, resolver)


LinkPreviewerDep = Annotated[LinkPreviewer, Depends(get_link_previewer)]


def get_login_limiter(redis: RedisDep, settings: SettingsDep) -> FixedWindowRateLimiter:
    """The login/registration rate limiter (shared by every worker through Redis)."""
    return FixedWindowRateLimiter(
        redis, settings.login_rate_limit, settings.login_rate_window_seconds, "login"
    )


LoginLimiterDep = Annotated[FixedWindowRateLimiter, Depends(get_login_limiter)]


def per_user_limit(bucket: str, scopes: list[str]) -> Any:
    """A route dependency that spends one unit of the caller's budget for `bucket` (OWASP
    API4). `scopes` repeats the route's scopes: FastAPI caches a dependency per (function,
    scopes), so the principal is still resolved once per request."""

    async def enforce(
        principal: Annotated[Principal, Security(get_current_principal, scopes=scopes)],
        redis: RedisDep,
        settings: SettingsDep,
    ) -> None:
        """429 with Retry-After once this user's budget for the window is spent."""
        limit = getattr(settings, f"{bucket}_rate_limit")
        window = settings.user_rate_window_seconds
        limiter = FixedWindowRateLimiter(redis, limit, window, f"user-{bucket}")
        result = await limiter.hit(str(principal.user_id))
        if not result.allowed:
            raise RateLimitedError(result.retry_after)

    return Depends(enforce)


NOTE_WRITE_LIMIT = per_user_limit("write", ["notes:write"])  # POST/PUT/PATCH/DELETE notes
LINK_PREVIEW_LIMIT = per_user_limit("link_preview", ["notes:read"])  # up to 5 fetches each
ACCOUNT_WRITE_LIMIT = per_user_limit("write", [])  # /users/me: keys, webhook, account
ADMIN_WRITE_LIMIT = per_user_limit("write", ["admin"])  # imports, wipes, retries
EXPORT_LIMIT = per_user_limit("export", [])  # POST /exports (a worker job each)
ADMIN_EXPORT_LIMIT = per_user_limit("export", ["admin"])  # GET /admin/export (every note)


def get_oidc_client(settings: SettingsDep, client: HttpClientDep, redis: RedisDep) -> OidcClient:
    """The OpenID Connect client (the router checks settings.oauth_enabled first)."""
    return OidcClient(settings, client, redis)


OidcClientDep = Annotated[OidcClient, Depends(get_oidc_client)]


async def get_cookie_principal(request: Request, auth: AuthServiceDep) -> Principal | None:
    """The user of an HTML page, from the HttpOnly session cookie (None if absent or invalid)."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        return await auth.principal_from_access_token(token)
    except AuthenticationError:
        return None


CookiePrincipalDep = Annotated[Principal | None, Depends(get_cookie_principal)]


def get_queue(request: Request) -> ArqRedis:
    """The ARQ client for enqueuing jobs (tests override it with one on fakeredis)."""
    return request.app.state.queue


def get_mailer() -> Mailer:
    """Where emails go (tests override it with a fake that records messages)."""
    return LogMailer()


def get_note_cache(request: Request, redis: RedisDep, settings: SettingsDep) -> NoteCache:
    """Cache-aside for single notes, traced with the app's tracer."""
    return NoteCache(redis, settings.cache_ttl_seconds, tracer=request.app.state.tracer)


QueueDep = Annotated[ArqRedis, Depends(get_queue)]
MailerDep = Annotated[Mailer, Depends(get_mailer)]
NoteCacheDep = Annotated[NoteCache, Depends(get_note_cache)]


async def kick_relay(queue: ArqRedis) -> None:
    """Background task after a write: wake the outbox relay now instead of at the next cron
    tick. Best effort: if Redis is down, the cron job publishes the events later."""
    with contextlib.suppress(Exception):
        await queue.enqueue_job("relay_outbox", _job_id=f"relay-kick:{int(time.time())}")
'''

NOTES_V6_SERVICES_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/services.py
"""Business logic: what the API does, independent of HTTP and of how notes are stored."""

import asyncio
import csv
import io
import json
import re
from collections.abc import Callable
from datetime import datetime
from http import HTTPStatus
from typing import Any

import httpx
from pydantic import TypeAdapter, ValidationError

from notes_api.core.metrics import NOTES_WRITTEN
from notes_api.events import new_event
from notes_api.exceptions import NoteNotFoundError, UploadRejectedError, VersionConflictError
from notes_api.models import Note
from notes_api.netguard import BLOCKED, Resolver, check_public_url, resolve_host
from notes_api.pagination import decode_cursor, encode_cursor
from notes_api.repositories import NoteRepository
from notes_api.schemas import LinkPreview, NoteCreate, NoteFilters, NoteRead, NoteUpdate

URL_PATTERN = re.compile(r"https?://[^\s<>\"')]+")
TITLE_PATTERN = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
MAX_LINKS = 5
MAX_PREVIEW_BYTES = 64 * 1024
IMPORT_ADAPTER = TypeAdapter(list[NoteCreate])


class NoteService:
    """Use cases for one user's notes; repository, clock and owner are injected."""

    def __init__(
        self, repository: NoteRepository, clock: Callable[[], datetime], owner_id: int
    ) -> None:
        """Keep the collaborators; every operation is limited to owner_id's notes."""
        self.repository = repository
        self.clock = clock
        self.owner_id = owner_id

    async def record(self, event_type: str, note: Note) -> None:
        """Write an outbox event in the same transaction as the change it describes."""
        data = {"note_id": note.id, "title": note.title, "version": note.version}
        await self.repository.add_event(new_event(self.owner_id, event_type, data))
        NOTES_WRITTEN.labels(event_type.removeprefix("note.")).inc()

    async def create(self, data: NoteCreate) -> Note:
        """Store a new note for the owner, stamped with the current time."""
        note = await self.repository.add(data, self.clock(), self.owner_id)
        await self.record("note.created", note)
        return note

    async def load_for_cache(self, note_id: int) -> dict[str, Any] | None:
        """The cacheable form of any note (owner included): the caller checks the owner."""
        note = await self.repository.get(note_id)
        if note is None:
            return None
        return {
            "owner_id": note.owner_id,
            "note": NoteRead.model_validate(note).model_dump(mode="json"),
        }

    async def get(self, note_id: int) -> Note:
        """The owner's note, or NoteNotFoundError: someone else's note is 'not found' too,
        so ids cannot be probed (404, not 403)."""
        note = await self.repository.get(note_id)
        if note is None or note.owner_id != self.owner_id:
            raise NoteNotFoundError(note_id)
        return note

    async def search(self, filters: NoteFilters) -> tuple[list[Note], int]:
        """One page of the owner's matching notes and the total."""
        return await self.repository.search(filters, self.owner_id)

    async def feed(self, limit: int, cursor: str | None) -> tuple[list[Note], str | None]:
        """A keyset page, newest first, and the cursor of the next page (None at the end)."""
        after = decode_cursor(cursor) if cursor else None
        notes = await self.repository.feed(limit + 1, after, self.owner_id)  # one extra
        page = notes[:limit]
        has_more = len(notes) > limit
        next_cursor = encode_cursor((page[-1].created_at, page[-1].id)) if has_more else None
        return page, next_cursor

    async def replace(self, note_id: int, data: NoteCreate) -> Note:
        """PUT: every client-owned field gets the new value (or its default)."""
        note = await self.get(note_id)
        note = await self.repository.update(note, data.model_dump(), self.clock())
        await self.record("note.updated", note)
        return note

    async def update(self, note_id: int, changes: NoteUpdate) -> Note:
        """PATCH: check the expected version, apply the fields sent, move updated_at on change."""
        note = await self.get(note_id)
        if changes.version is not None and changes.version != note.version:
            raise VersionConflictError(note_id, expected=changes.version, actual=note.version)
        sent = changes.model_dump(exclude_unset=True, exclude={"version"})
        if all(getattr(note, name) == value for name, value in sent.items()):
            return note
        note = await self.repository.update(note, sent, self.clock())
        await self.record("note.updated", note)
        return note

    async def delete(self, note_id: int) -> None:
        """Delete a note, or NoteNotFoundError."""
        note = await self.get(note_id)
        await self.record("note.deleted", note)
        await self.repository.delete(note)

    async def import_notes(self, notes: list[NoteCreate]) -> list[Note]:
        """Create every note of an import, in file order."""
        return [await self.create(note) for note in notes]


def parse_import(filename: str, content: bytes) -> list[NoteCreate]:
    """Notes from a .json list or a .csv file (title, body, tags separated by ';', pinned)."""
    try:
        text = content.decode("utf-8-sig")
        if filename.endswith(".json"):
            return IMPORT_ADAPTER.validate_python(json.loads(text), strict=False)
        rows = [
            {**row, "tags": [tag for tag in (row.get("tags") or "").split(";") if tag]}
            for row in csv.DictReader(io.StringIO(text))
        ]
        return IMPORT_ADAPTER.validate_python(rows, strict=False)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
        reason = f"{type(error).__name__}: {str(error).splitlines()[0]}"
        raise UploadRejectedError(reason, HTTPStatus.UNPROCESSABLE_CONTENT) from error


class LinkPreviewer:
    """Fetch the <title> of links in a note, refusing anything that is not a public web URL.

    Server-side request forgery (OWASP API7): a note body is user input, so a link could point
    at 127.0.0.1, the cloud metadata service (169.254.169.254) or a private network.
    check_url() gives an early, readable answer; the client (netguard.public_only_client)
    enforces the rule where it matters, when it connects. Redirects are not followed (a public
    URL could redirect to a private one); at most MAX_PREVIEW_BYTES of a page are read.
    """

    def __init__(self, client: httpx.AsyncClient, resolver: Resolver = resolve_host) -> None:
        """Use the lifespan's public-only client and an injectable DNS resolver."""
        self.client = client
        self.resolver = resolver

    async def check_url(self, url: str) -> str | None:
        """None if the URL may be fetched, else the reason it may not."""
        return await check_public_url(url, self.resolver)

    async def preview(self, url: str) -> LinkPreview:
        """One link: its status and title, or why it was not fetched (never raises)."""
        if reason := await self.check_url(url):
            return LinkPreview(url=url, error=reason)
        try:
            async with self.client.stream("GET", url, follow_redirects=False) as response:
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= MAX_PREVIEW_BYTES:
                        break
        except httpx.HTTPError as error:  # BLOCKED: the DNS answer changed after check_url()
            reason = BLOCKED if str(error).startswith(BLOCKED) else type(error).__name__
            return LinkPreview(url=url, error=reason)
        if response.is_redirect:
            return LinkPreview(
                url=url, status_code=response.status_code, error="redirect not followed"
            )
        text = b"".join(chunks)[:MAX_PREVIEW_BYTES].decode(response.encoding or "utf-8", "replace")
        match = TITLE_PATTERN.search(text)
        title = " ".join(match[1].split()) if match else None
        return LinkPreview(url=url, status_code=response.status_code, title=title)

    async def previews(self, body: str) -> list[LinkPreview]:
        """The first MAX_LINKS distinct links of a body, fetched concurrently."""
        urls = list(dict.fromkeys(URL_PATTERN.findall(body)))[:MAX_LINKS]
        return list(await asyncio.gather(*(self.preview(url) for url in urls)))
'''

NOTES_V6_WORKER_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/worker.py
"""The ARQ worker (python -m notes_api.worker): relay, webhooks, exports, clean-up."""

import asyncio
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import httpx
import redis.asyncio as redis_asyncio
from arq import Retry, cron
from arq.connections import RedisSettings
from arq.worker import Worker
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from notes_api import __version__
from notes_api.core.config import Settings, get_settings
from notes_api.core.logging import configure_logging
from notes_api.db import create_engine_from_settings, make_session_factory
from notes_api.events import (
    EVENT_ID_HEADER,
    SIGNATURE_HEADER,
    event_message,
    sign_webhook,
    user_channel,
)
from notes_api.exports import add_progress, owner_key, result_key
from notes_api.models import Note, OutboxEvent, RefreshToken, User
from notes_api.netguard import BLOCKED, Resolver, check_public_url, public_only_client, resolve_host
from notes_api.schemas import NoteRead

RELAY_BATCH = 100
EXPORT_CHUNK = 25
DEAD_LETTERS = "webhooks:dead"


def utc_now() -> datetime:
    """Now, in UTC."""
    return datetime.now(UTC)


async def startup(ctx: dict[str, Any]) -> None:
    """Open what the tasks share (once per worker process)."""
    settings: Settings = ctx.get("settings") or get_settings()
    ctx["settings"] = settings
    ctx["engine"] = create_engine_from_settings(settings)
    ctx["session_factory"] = make_session_factory(ctx["engine"])
    ctx["text_redis"] = redis_asyncio.from_url(
        settings.redis_url.get_secret_value(), decode_responses=True
    )
    ctx.setdefault("resolver", resolve_host)  # tests pass a fake DNS
    ctx["http"] = public_only_client(  # connects only to the public address it checked
        settings.webhook_timeout_seconds,
        f"notes-api-webhooks/{__version__}",
        resolver=ctx["resolver"],
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    """Close everything startup opened."""
    await ctx["http"].aclose()
    await ctx["text_redis"].aclose()
    await ctx["engine"].dispose()


async def relay_outbox(ctx: dict[str, Any]) -> int:
    """Publish unpublished outbox events (Redis pub/sub) and queue their webhooks.

    A Redis lock keeps two relays (cron + a kick, or two workers) from overlapping; on
    PostgreSQL the SELECT ... FOR UPDATE SKIP LOCKED would also let several relays share work.
    """
    redis = ctx["text_redis"]
    if not await redis.set("lock:relay-outbox", "1", nx=True, ex=30):
        return 0
    try:
        async with ctx["session_factory"]() as session, session.begin():
            statement = (
                select(OutboxEvent, User.webhook_url)
                .join(User, User.id == OutboxEvent.user_id)
                .where(OutboxEvent.published_at.is_(None))
                .order_by(OutboxEvent.id)
                .limit(RELAY_BATCH)
                .with_for_update(skip_locked=True, of=OutboxEvent)
            )
            rows = (await session.execute(statement)).all()
            for event, webhook_url in rows:
                await redis.publish(user_channel(event.user_id), json.dumps(event_message(event)))
                if webhook_url:
                    event.webhook_status = "pending"
                    await ctx["redis"].enqueue_job(
                        "deliver_webhook", event.id, _job_id=f"webhook:{event.id}"
                    )
                event.published_at = utc_now()
        return len(rows)
    finally:
        await redis.delete("lock:relay-outbox")


async def deliver_webhook(ctx: dict[str, Any], event_id: int) -> str:
    """POST one signed event; retry with backoff; dead-letter after the last try. The URL is
    checked again first: DNS may have changed since it was saved."""
    settings: Settings = ctx["settings"]
    async with ctx["session_factory"]() as session, session.begin():
        event = await session.get(OutboxEvent, event_id)
        user = await session.get(User, event.user_id) if event else None
        if event is None or user is None or not user.webhook_url or not user.webhook_secret:
            return "skipped"
        if event.webhook_status == "delivered":
            return "already delivered"  # a duplicate job: at-least-once delivery
        body = json.dumps(event_message(event), separators=(",", ":")).encode()
        headers = {
            "Content-Type": "application/json",
            EVENT_ID_HEADER: str(event.id),  # receivers deduplicate on this id
            SIGNATURE_HEADER: sign_webhook(user.webhook_secret, int(time.time()), body),
        }
        event.webhook_attempts += 1
        if blocked := await check_public_url(user.webhook_url, ctx["resolver"]):
            event.webhook_status, event.last_error = "dead", blocked  # no retry; an admin can
            await ctx["text_redis"].lpush(DEAD_LETTERS, str(event.id))
            return "blocked"
        try:
            response = await ctx["http"].post(user.webhook_url, content=body, headers=headers)
            error = None if response.is_success else f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:  # BLOCKED: the DNS answer changed since the check
            error = BLOCKED if str(exc).startswith(BLOCKED) else type(exc).__name__
        if error is None:
            event.webhook_status, event.last_error = "delivered", None
            return "delivered"
        event.last_error = error
        if ctx.get("job_try", 1) >= settings.webhook_max_attempts:
            event.webhook_status = "dead"
            await ctx["text_redis"].lpush(DEAD_LETTERS, str(event.id))
            return "dead"
    raise Retry(defer=2 ** ctx.get("job_try", 1))  # 2, 4, 8 ... seconds (after the commit)


async def export_notes(
    ctx: dict[str, Any], export_id: str, user_id: int, delay: float = 0.0
) -> int:
    """Build a JSON export of a user's notes in chunks, reporting progress to a Redis Stream."""
    redis, ttl = ctx["text_redis"], ctx["settings"].export_ttl_seconds
    if await redis.get(owner_key(export_id)) != str(user_id):
        return 0
    async with ctx["session_factory"]() as session:
        statement = (
            select(Note).options(selectinload(Note.tag_objects)).where(Note.owner_id == user_id)
        )
        notes = list(await session.scalars(statement.order_by(Note.id)))
    total, exported = len(notes), []
    await add_progress(redis, export_id, ttl, status="running", done=0, total=total)
    for start in range(0, total, EXPORT_CHUNK):
        chunk = notes[start : start + EXPORT_CHUNK]
        exported += [NoteRead.model_validate(note).model_dump(mode="json") for note in chunk]
        if delay:
            await asyncio.sleep(delay)  # demos slow the export down to watch the progress
        await add_progress(redis, export_id, ttl, status="running", done=len(exported), total=total)
    await redis.set(result_key(export_id), json.dumps(exported), ex=ttl)
    await add_progress(redis, export_id, ttl, status="done", done=total, total=total)
    return total


async def purge_expired_tokens(ctx: dict[str, Any]) -> int:
    """Daily: delete refresh tokens that expired more than a day ago (one worker at a time)."""
    redis = ctx["text_redis"]
    if not await redis.set("lock:purge-tokens", "1", nx=True, ex=600):
        return 0
    try:
        cutoff = utc_now() - timedelta(days=1)
        async with ctx["session_factory"]() as session, session.begin():
            result = await session.execute(
                delete(RefreshToken).where(RefreshToken.expires_at < cutoff)
            )
        return result.rowcount
    finally:
        await redis.delete("lock:purge-tokens")


class WorkerSettings:
    """What `arq notes_api.worker.WorkerSettings` runs."""

    functions: ClassVar[list[Any]] = [
        relay_outbox,
        deliver_webhook,
        export_notes,
        purge_expired_tokens,
    ]
    cron_jobs: ClassVar[list[Any]] = [
        cron(relay_outbox, second={0, 10, 20, 30, 40, 50}, unique=True),  # safety net for kicks
        cron(purge_expired_tokens, hour={3}, minute={0}, unique=True),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url.get_secret_value())
    max_tries = get_settings().webhook_max_attempts
    job_timeout = 60
    keep_result = 300


async def run_worker(
    burst: bool = False, settings: Settings | None = None, resolver: Resolver | None = None
) -> None:
    """Build the arq Worker inside a running event loop and run it (SIGTERM stops it cleanly).

    `arq notes_api.worker.WorkerSettings` is the usual command, but arq 0.25's CLI calls
    asyncio.get_event_loop() outside a running loop, which raises on Python 3.14+.
    """
    log_settings = settings or get_settings()
    configure_logging(log_settings.log_level, log_settings.log_json)  # the same JSON as the API
    worker = Worker(
        functions=WorkerSettings.functions,
        cron_jobs=WorkerSettings.cron_jobs,
        redis_settings=(
            RedisSettings.from_dsn(settings.redis_url.get_secret_value())
            if settings
            else WorkerSettings.redis_settings
        ),
        on_startup=startup,
        on_shutdown=shutdown,
        ctx={"settings": settings, "resolver": resolver or resolve_host} if settings else {},
        burst=burst,
        poll_delay=0.1,
        max_tries=WorkerSettings.max_tries if settings is None else settings.webhook_max_attempts,
        job_timeout=WorkerSettings.job_timeout,
        keep_result=WorkerSettings.keep_result,
    )
    try:
        await worker.main()
    finally:
        await worker.close()


if __name__ == "__main__":
    asyncio.run(run_worker(burst="--burst" in sys.argv))
'''

NOTES_V6_TESTS_CONFTEST_PY = r'''
%%writefile ../projects/notes_api/tests/conftest.py
"""Shared fixtures: an app per test (SQLite file, fakeredis), clients, PostgreSQL and Redis."""

import asyncio
import os
import secrets
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import fakeredis
import httpx
import pytest
from alembic import command
from arq.connections import ArqRedis
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import settings as hypothesis_settings
from pydantic import SecretStr

from helpers import (
    ADMIN_EMAIL,
    PASSWORD,
    POSTGRES_IMAGE,
    REDIS_IMAGE,
    USER_EMAIL,
    FakeMailer,
    auth_headers,
    create_tables,
    docker_available,
    fake_resolver,
    postgres_alembic_config,
    promote,
)
from notes_api.core.config import Settings
from notes_api.dependencies import get_mailer, get_queue, get_redis, get_resolver
from notes_api.main import create_app

# No example database for Hypothesis (Schemathesis uses it): every run tries the same cases.
hypothesis_settings.register_profile("notes", database=None)
hypothesis_settings.load_profile("notes")


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests on asyncio (the anyio pytest plugin ships with anyio)."""
    return "asyncio"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Test settings: a fresh SQLite file, a generated JWT secret, cheap Argon2 parameters."""
    return Settings(
        _env_file=None,
        environment="test",
        cors_origins=["http://localhost:5173"],
        max_upload_bytes=2048,
        database_url=SecretStr(f"sqlite+aiosqlite:///{tmp_path / 'notes.db'}"),
        jwt_secret=SecretStr(secrets.token_urlsafe(32)),
        password_time_cost=1,
        password_memory_kib=64,
        login_rate_limit=10,
        write_rate_limit=10_000,  # tests make many requests per user; test_limits.py checks
        link_preview_rate_limit=10_000,  # the per-user budgets with small values
        export_rate_limit=10_000,
        cookie_secure=False,  # TestClient talks plain HTTP
        check_migrations=False,  # the test schema comes from create_all, not Alembic
        otel_exporter="memory",  # spans are kept on app.state.span_exporter
    )


@pytest.fixture
def redis_server() -> fakeredis.FakeServer:
    """One in-memory Redis server per test, shared by the text and the queue clients."""
    return fakeredis.FakeServer()


@pytest.fixture
def fake_redis(redis_server: fakeredis.FakeServer) -> fakeredis.FakeAsyncRedis:
    """The text client (decoded strings), as the app uses it."""
    return fakeredis.FakeAsyncRedis(server=redis_server, decode_responses=True)


@pytest.fixture
def fake_queue(redis_server: fakeredis.FakeServer) -> ArqRedis:
    """An ARQ client on the same fake server (bytes, pickled jobs)."""
    return ArqRedis(connection_pool=fakeredis.FakeAsyncRedis(server=redis_server).connection_pool)


@pytest.fixture
def mailer() -> FakeMailer:
    """Records emails instead of sending them."""
    return FakeMailer()


@pytest.fixture
def app(
    settings: Settings,
    fake_redis: fakeredis.FakeAsyncRedis,
    fake_queue: ArqRedis,
    mailer: FakeMailer,
) -> FastAPI:
    """A fresh app on an empty database, with fake Redis, queue, mailer and DNS."""
    asyncio.run(create_tables(settings))
    application = create_app(settings)
    application.dependency_overrides[get_redis] = lambda: fake_redis
    application.dependency_overrides[get_queue] = lambda: fake_queue
    application.dependency_overrides[get_mailer] = lambda: mailer
    application.dependency_overrides[get_resolver] = lambda: fake_resolver
    return application


@pytest.fixture
def anonymous(app: FastAPI) -> Iterator[TestClient]:
    """A TestClient without credentials; entering it runs the lifespan."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def client(anonymous: TestClient) -> TestClient:
    """The same client, logged in as an ordinary user (Authorization header on every call)."""
    anonymous.headers.update(auth_headers(anonymous, USER_EMAIL))
    return anonymous


@pytest.fixture
def admin_email(anonymous: TestClient) -> str:
    """Register ADMIN_EMAIL as an ordinary user, then promote it the way an operator does."""
    promote(anonymous, ADMIN_EMAIL)
    return ADMIN_EMAIL


@pytest.fixture
def admin_headers(anonymous: TestClient, admin_email: str) -> dict[str, str]:
    """Bearer headers of the promoted admin (logged in after the promotion)."""
    return auth_headers(anonymous, admin_email)


@pytest.fixture
async def async_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """httpx.AsyncClient calling the app in this event loop (ASGITransport), with its lifespan."""
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            http.headers.update(await async_auth_headers(http, USER_EMAIL))
            yield http


async def async_auth_headers(http: httpx.AsyncClient, email: str) -> dict[str, str]:
    """Register and log in through the async client; return a Bearer header."""
    await http.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    form = {"username": email, "password": PASSWORD}
    token = (await http.post("/api/v1/auth/token", data=form)).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """A PostgreSQL database migrated to head: the CI service, or a testcontainer."""
    if url := os.environ.get("NOTES_TEST_DATABASE_URL"):
        command.upgrade(postgres_alembic_config(url), "head")
        yield url
        return
    if not docker_available():
        pytest.skip("no NOTES_TEST_DATABASE_URL and Docker is not available")
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as container:
        url = container.get_connection_url()
        command.upgrade(postgres_alembic_config(url), "head")
        yield url


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    """A real Redis: the CI service, or a testcontainer."""
    if url := os.environ.get("NOTES_TEST_REDIS_URL"):
        yield url
        return
    if not docker_available():
        pytest.skip("no NOTES_TEST_REDIS_URL and Docker is not available")
    from testcontainers.community.redis import RedisContainer

    with RedisContainer(REDIS_IMAGE) as container:
        host, port = container.get_container_host_ip(), container.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"
'''

NOTES_V6_TESTS_HELPERS_PY = r'''
%%writefile ../projects/notes_api/tests/helpers.py
"""Small helpers shared by the test modules."""

import ipaddress
from pathlib import Path
from typing import Any

from alembic.config import Config
from fastapi.testclient import TestClient

from notes_api.core.config import Settings
from notes_api.db import Base, create_engine_from_settings
from notes_api.manage import set_role

USER_EMAIL = "user@example.com"
ADMIN_EMAIL = "admin@example.com"  # promoted by the admin_email fixture
PASSWORD = "correct horse battery staple"
ANONYMOUS = {"Authorization": ""}  # overrides the client's default header
FAKE_DNS = {
    "docs.example": ["93.184.216.34"],
    "slow.example": ["93.184.216.35"],
    "intranet.example": ["10.0.0.7"],
    "metadata.example": ["169.254.169.254"],
    "mixed.example": ["93.184.216.36", "127.0.0.1"],
    "hooks.example": ["93.184.216.37"],
}


def create(client: TestClient, **fields: Any) -> dict[str, Any]:
    """POST a note (title defaults to "Buy tea") and return the created note."""
    response = client.post("/api/v1/notes", json={"title": "Buy tea", **fields})
    assert response.status_code == 201, response.text
    return response.json()


def ids(response: Any) -> list[int]:
    """Ids of the notes on a page."""
    assert response.status_code == 200, response.text
    return [note["id"] for note in response.json()["items"]]


def register(client: TestClient, email: str, password: str = PASSWORD) -> Any:
    """POST /auth/register (without the client's default credentials)."""
    body = {"email": email, "password": password}
    return client.post("/api/v1/auth/register", json=body, headers=ANONYMOUS)


def login(client: TestClient, email: str, password: str = PASSWORD, scope: str = "") -> Any:
    """POST /auth/token with the OAuth2 password form."""
    form = {"username": email, "password": password, "scope": scope}
    return client.post("/api/v1/auth/token", data=form, headers=ANONYMOUS)


def auth_headers(client: TestClient, email: str, scope: str = "") -> dict[str, str]:
    """Register (if needed) and log in; return a Bearer header."""
    register(client, email)
    response = login(client, email, scope=scope)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def promote(client: TestClient, email: str) -> None:
    """Register `email` (if needed) as an ordinary user, then make it an admin the way an
    operator does (notes_api.manage.set_role); tokens issued afterwards carry the admin scope."""
    register(client, email)
    session_factory = client.app.state.session_factory  # type: ignore[attr-defined]
    assert client.portal.call(set_role, session_factory, email, "admin")


async def fake_resolver(host: str) -> list[str]:
    """DNS for tests: IP literals resolve to themselves, a few names to fixed addresses."""
    try:
        return [str(ipaddress.ip_address(host))]
    except ValueError:
        pass
    if host not in FAKE_DNS:
        raise OSError(f"cannot resolve {host}")
    return FAKE_DNS[host]


async def create_tables(settings: Settings) -> None:
    """CREATE TABLE for every model (fast; the PostgreSQL tests run the Alembic migrations)."""
    engine = create_engine_from_settings(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


class FakeMailer:
    """A Mailer that keeps the messages."""

    def __init__(self) -> None:
        """Start with an empty outbox."""
        self.sent: list[tuple[str, str]] = []

    async def send(self, to: str, subject: str, body: str) -> None:
        """Record one message."""
        self.sent.append((to, subject))


PROJECT_DIR = Path(__file__).resolve().parent.parent
POSTGRES_IMAGE = "postgres:18-alpine"
REDIS_IMAGE = "redis:7.4"


def docker_available() -> bool:
    """True if a Docker daemon answers (the PostgreSQL / Redis tests need one, or CI services)."""
    try:
        import docker

        docker.from_env().ping()
    except Exception:
        return False
    return True


def postgres_alembic_config(url: str) -> Config:
    """alembic.ini pointed at a PostgreSQL URL."""
    config = Config(PROJECT_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    config.attributes["configure_logger"] = False
    return config
'''

NOTES_V6_TESTS_FACTORIES_PY = r'''
%%writefile ../projects/notes_api/tests/factories.py
"""Test data factories: valid objects with sensible defaults, overridable per test.

Like factory_boy or polyfactory, but small: each call makes a new row with unique values (a
sequence number), so tests state only the fields they care about.
"""

import itertools
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from notes_api.models import Note, User
from notes_api.repositories import SqlNoteRepository, SqlUserRepository
from notes_api.schemas import NoteCreate

SEQUENCE = itertools.count(1)
NOW = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)


async def make_user(session: AsyncSession, **overrides: Any) -> User:
    """A user (no password: tests that log in use the HTTP API instead)."""
    number = next(SEQUENCE)
    fields = {"email": f"user{number}@example.com", "password_hash": None, "role": "user"}
    fields |= overrides
    return await SqlUserRepository(session).add_user(
        fields["email"], fields["password_hash"], fields["role"]
    )


async def make_note(session: AsyncSession, owner: User | None = None, **overrides: Any) -> Note:
    """A note owned by owner (a new user if none is given)."""
    owner = owner or await make_user(session)
    number = next(SEQUENCE)
    fields: dict[str, Any] = {"title": f"Note {number}", "body": "", "tags": [], "pinned": False}
    fields |= overrides
    return await SqlNoteRepository(session).add(NoteCreate(**fields), NOW, owner.id)
'''

NOTES_V6_TESTS_TEST_ASYNC_PY = r'''
%%writefile ../projects/notes_api/tests/test_async.py
"""httpx.AsyncClient + ASGITransport: the app runs in the test's own event loop.

TestClient runs the app in a separate thread with its own loop: convenient for synchronous
tests, but async resources created by the test (an asyncpg connection, a task) cannot be
shared with the app. AsyncClient calls the ASGI app directly from the test's loop.
"""

import asyncio
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI

from notes_api.dependencies import get_clock

pytestmark = pytest.mark.anyio
NOTES = "/api/v1/notes"


async def test_crud_through_the_async_client(async_client: httpx.AsyncClient) -> None:
    """The same API, awaited."""
    created = (await async_client.post(NOTES, json={"title": "Async tea"})).json()
    fetched = await async_client.get(f"{NOTES}/{created['id']}")
    assert fetched.status_code == 200 and fetched.json()["title"] == "Async tea"
    assert (await async_client.get(NOTES)).json()["total"] == 1


async def test_concurrent_requests_in_one_loop(async_client: httpx.AsyncClient) -> None:
    """asyncio.gather sends ten requests at once; every note gets its own id."""
    responses = await asyncio.gather(
        *(async_client.post(NOTES, json={"title": f"Note {number}"}) for number in range(10))
    )
    assert {response.status_code for response in responses} == {201}
    assert len({response.json()["id"] for response in responses}) == 10


async def test_dependency_override_freezes_the_clock(
    app: FastAPI, async_client: httpx.AsyncClient
) -> None:
    """dependency_overrides swaps a dependency for the rest of the test."""
    frozen = datetime(2026, 11, 18, 9, 30, tzinfo=UTC)
    app.dependency_overrides[get_clock] = lambda: lambda: frozen
    created = (await async_client.post(NOTES, json={"title": "Frozen"})).json()
    assert created["created_at"] == "2026-11-18T09:30:00Z"
'''

NOTES_V6_TESTS_TEST_POSTGRES_ROLLBACK_PY = r'''
%%writefile ../projects/notes_api/tests/test_postgres_rollback.py
"""Rollback-per-test on PostgreSQL: one outer transaction per test, rolled back at the end.

The app's session joins the test's connection with join_transaction_mode="create_savepoint":
the app's commits become SAVEPOINT releases inside the outer transaction, so each test sees
an empty database without truncating or re-migrating. AsyncClient keeps app and test on one
event loop (an asyncpg connection belongs to the loop that opened it).
"""

from collections.abc import AsyncIterator

import fakeredis
import httpx
import pytest
import sqlalchemy as sa
from arq.connections import ArqRedis
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from conftest import async_auth_headers
from factories import make_note, make_user
from helpers import USER_EMAIL, FakeMailer, fake_resolver
from notes_api.core.config import Settings
from notes_api.dependencies import get_mailer, get_queue, get_redis, get_resolver, get_session
from notes_api.main import create_app

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
async def db_connection(postgres_url: str) -> AsyncIterator[AsyncConnection]:
    """A connection with an open transaction that is always rolled back."""
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()
    await engine.dispose()


@pytest.fixture
async def db_session(db_connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    """A session whose commits are savepoints inside the test's transaction."""
    session = AsyncSession(
        bind=db_connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    try:
        yield session
    finally:
        await session.close()


@pytest.fixture
async def pg_client(
    settings: Settings,
    postgres_url: str,
    db_session: AsyncSession,
    fake_redis: fakeredis.FakeAsyncRedis,
    fake_queue: ArqRedis,
    mailer: FakeMailer,
) -> AsyncIterator[httpx.AsyncClient]:
    """A logged-in AsyncClient whose requests use the test's session."""
    app: FastAPI = create_app(settings.model_copy(update={"database_url": SecretStr(postgres_url)}))

    async def session_in_test_transaction() -> AsyncIterator[AsyncSession]:
        """Each request: a savepoint in the test transaction (nested if one is already open)."""
        nested = db_session.in_transaction()
        async with db_session.begin_nested() if nested else db_session.begin():
            yield db_session

    app.dependency_overrides[get_session] = session_in_test_transaction
    app.dependency_overrides[get_redis] = lambda: fake_redis
    app.dependency_overrides[get_queue] = lambda: fake_queue
    app.dependency_overrides[get_mailer] = lambda: mailer
    app.dependency_overrides[get_resolver] = lambda: fake_resolver
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            http.headers.update(await async_auth_headers(http, USER_EMAIL))
            yield http


async def count_notes(connection: AsyncConnection | AsyncSession) -> int:
    """Rows in notes, as the test's transaction sees them."""
    return (await connection.execute(sa.text("SELECT count(*) FROM notes"))).scalar_one()


@pytest.mark.parametrize("run", [1, 2])
async def test_every_test_starts_empty(
    pg_client: httpx.AsyncClient, db_session: AsyncSession, run: int
) -> None:
    """Both runs see zero notes first, though each one writes three."""
    assert await count_notes(db_session) == 0
    for number in range(3):
        response = await pg_client.post("/api/v1/notes", json={"title": f"Run {run} #{number}"})
        assert response.status_code == 201
    assert await count_notes(db_session) == 3


async def test_factories_make_valid_rows(db_session: AsyncSession) -> None:
    """Factories fill in unique, valid defaults; tests override only what matters."""
    owner = await make_user(db_session)
    pinned = await make_note(db_session, owner, pinned=True, tags=["work"])
    other = await make_note(db_session)
    assert pinned.owner_id == owner.id and pinned.tags == ["work"] and pinned.pinned
    assert other.owner_id != owner.id and other.title != pinned.title
    assert await count_notes(db_session) == 2
'''

NOTES_V6_TESTS_TEST_CONTRACT_PY = r'''
%%writefile ../projects/notes_api/tests/test_contract.py
"""Contract tests: Schemathesis fuzzes the documented notes operations; the OpenAPI is snapshotted.

Schemathesis generates requests from the OpenAPI schema (valid and invalid ones) and checks
every response: no 5xx, documented status codes and content types, bodies matching the
response schemas. The snapshot test fails whenever the public API changes, so a change is
always deliberate: review the diff, then record it with UPDATE_SNAPSHOTS=1.
"""

import json
import os
from pathlib import Path

import pytest
import schemathesis
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import HealthCheck
from hypothesis import settings as hypothesis_settings

SNAPSHOT = Path(__file__).parent / "snapshots" / "openapi.json"


@pytest.fixture
def api_schema(app: FastAPI) -> schemathesis.BaseSchema:
    """The app's own OpenAPI document (the filter is applied to the lazy schema below)."""
    return schemathesis.openapi.from_dict(app.openapi())


schema = schemathesis.pytest.from_fixture("api_schema").include(path_regex=r"^/api/v1/notes")


@schema.parametrize()
@hypothesis_settings(
    max_examples=12,
    deadline=None,
    derandomize=True,  # the same examples on every run (and in CI)
    suppress_health_check=list(HealthCheck),
)
def test_notes_operations_honour_the_schema(case: schemathesis.Case, client: TestClient) -> None:
    """Call the app through the logged-in client; validate status, content type and body.

    Two checks are switched off, for reasons the schema cannot express:
    - ignored_auth (resend without credentials, expect 401): this client always sends
      credentials; test_security.py covers authentication.
    - positive_data_acceptance (schema-valid requests must succeed): opaque cursors, ids of
      notes that do not exist and version preconditions make valid requests fail legitimately.
    """
    kwargs = case.as_transport_kwargs(base_url=str(client.base_url), headers=dict(client.headers))
    if not kwargs.get("cookies"):
        kwargs.pop("cookies", None)  # per-request cookies are deprecated in the test client
    if isinstance(kwargs.get("data"), bytes | str):
        kwargs["content"] = kwargs.pop("data")  # httpx: raw bodies go in content=
    response = client.request(**kwargs)
    excluded = [schemathesis.checks.ignored_auth, schemathesis.checks.positive_data_acceptance]
    case.validate_response(response, excluded_checks=excluded)


def test_openapi_matches_the_snapshot(app: FastAPI) -> None:
    """The public contract changes only on purpose."""
    current = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    if os.environ.get("UPDATE_SNAPSHOTS"):
        SNAPSHOT.write_text(current, encoding="utf-8")
    assert SNAPSHOT.exists(), "no snapshot yet: run UPDATE_SNAPSHOTS=1 uv run pytest -k snapshot"
    recorded = SNAPSHOT.read_text(encoding="utf-8")
    assert recorded == current, (
        "the OpenAPI changed: review it, then re-run with UPDATE_SNAPSHOTS=1"
    )
'''

NOTES_V6_TESTS_TEST_OBSERVABILITY_PY = r'''
%%writefile ../projects/notes_api/tests/test_observability.py
"""Observability: correlated JSON logs, Prometheus metrics, OpenTelemetry spans, probes, Sentry."""

import importlib.util
import io
import json
import logging
import sqlite3
from typing import Any

import pytest
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from helpers import create
from notes_api.core.logging import configure_logging
from notes_api.dependencies import get_redis
from notes_api.main import create_app


def json_lines(buffer: io.StringIO) -> list[dict[str, Any]]:
    """The log output, one dict per line."""
    return [json.loads(line) for line in buffer.getvalue().splitlines() if line.startswith("{")]


def test_access_log_is_json_with_request_and_trace_ids(client: TestClient, app: FastAPI) -> None:
    """One line per request; its trace id is the server span's trace id."""
    buffer = io.StringIO()
    configure_logging("INFO", json_output=True, stream=buffer)
    client.get("/api/v1/notes", headers={"X-Request-ID": "req-123"})
    access = [line for line in json_lines(buffer) if line["event"] == "request"][-1]
    assert (access["request_id"], access["status"], access["method"]) == ("req-123", 200, "GET")
    assert access["level"] == "info" and access["timestamp"].endswith("Z")
    spans = app.state.span_exporter.get_finished_spans()
    server_trace_ids = {format(span.context.trace_id, "032x") for span in spans}
    assert access["trace_id"] in server_trace_ids


def test_secrets_never_reach_the_logs() -> None:
    """stdlib and structlog records are redacted the same way."""
    buffer = io.StringIO()
    configure_logging("INFO", json_output=True, stream=buffer)
    logging.getLogger("notes_api.test").warning("retry with password=%s", "hunter2")
    structlog.get_logger("notes_api.test").info("key used", api_key="nk_" + "x" * 24)
    first, second = json_lines(buffer)[-2:]
    assert first["event"] == "retry with password=[REDACTED]"
    assert second["api_key"] == "[REDACTED]"


def test_metrics_use_route_templates(client: TestClient) -> None:
    """Counters and histograms are labelled by route template, never by raw path."""
    note_id = create(client, title="Metric me")["id"]
    client.get(f"/api/v1/notes/{note_id}")
    client.get("/api/v1/notes/987654")
    client.get("/no/such/page")
    text = client.get("/metrics").text
    route = 'route="/api/v1/notes/{note_id}"'
    assert f'notes_http_requests_total{{method="GET",{route},status="200"}}' in text
    assert f'{route},status="404"' in text
    assert 'route="unmatched"' in text
    assert f'notes_http_request_duration_seconds_bucket{{le="0.2",method="GET",{route}}}' in text
    assert 'notes_writes_total{operation="created"}' in text
    assert 'notes_cache_lookups_total{result="miss"}' in text
    assert f'/api/v1/notes/{note_id}"' not in text


def test_spans_for_requests_and_the_cache(client: TestClient, app: FastAPI) -> None:
    """The instrumentation makes a server span; NoteCache adds a child span with cache.hit."""
    note_id = create(client, title="Trace me")["id"]
    app.state.span_exporter.clear()
    client.get(f"/api/v1/notes/{note_id}")
    client.get(f"/api/v1/notes/{note_id}")
    spans = app.state.span_exporter.get_finished_spans()
    cache_spans = [span for span in spans if span.name == "cache.get_or_load"]
    assert [span.attributes["cache.hit"] for span in cache_spans] == [False, True]
    server = [span for span in spans if span.kind.name == "SERVER"]
    assert len(server) == 2
    assert server[0].attributes["http.status_code"] == 200
    assert server[0].attributes["http.route"].startswith("/api/v1/notes/{note_id")
    assert cache_spans[0].parent.span_id == server[0].context.span_id


def test_probes(client: TestClient, app: FastAPI, settings: Any) -> None:
    """Liveness never touches dependencies; readiness and startup report each check."""
    assert client.get("/health/live").json() == {"status": "ok"}
    ready = client.get("/health/ready")
    assert ready.json()["checks"] == {"database": "ok", "redis": "ok"}
    assert client.get("/health/startup").status_code == 200  # check_migrations=False in tests


class BrokenRedis:
    """A Redis client whose server is gone."""

    async def ping(self) -> bool:
        """Fail like a refused connection."""
        raise ConnectionError("connection refused")


def test_readiness_fails_when_redis_is_down(client: TestClient, app: FastAPI) -> None:
    """503 with the failing check named; liveness stays 200."""
    app.dependency_overrides[get_redis] = BrokenRedis
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["redis"] == "unavailable"  # no exception name in public
    assert client.get("/health/live").status_code == 200


def test_startup_waits_for_migrations(settings: Any, app: FastAPI) -> None:
    """With the check on, a schema made by create_all (no alembic_version) is not ready."""
    app.state.settings = settings.model_copy(update={"check_migrations": True})
    with TestClient(app) as anonymous:
        response = anonymous.get("/health/startup")
    assert response.status_code == 503
    assert response.json()["checks"]["migrations"] == "at None, need 0006"


@pytest.mark.parametrize(
    ("revision", "status_code", "migrations"),
    [("0007", 200, "ok"), ("0005", 503, "at 0005, need 0006")],
)
def test_startup_accepts_a_newer_schema(
    settings: Any, app: FastAPI, revision: str, status_code: int, migrations: str
) -> None:
    """Ahead of the code (a rolled-back release migrated it): ready. Behind: not ready."""
    database = settings.database_url.get_secret_value().removeprefix("sqlite+aiosqlite:///")
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
    app.state.settings = settings.model_copy(update={"check_migrations": True})
    with TestClient(app) as anonymous:
        response = anonymous.get("/health/startup")
    checks = response.json()["checks"]
    assert (response.status_code, checks["migrations"]) == (status_code, migrations)


def test_production_publishes_no_schema(settings: Any) -> None:
    """No /openapi.json, /docs or /redoc in production (OWASP API9: keep the inventory private)."""
    production = settings.model_copy(update={"environment": "production"})
    with TestClient(create_app(production)) as anonymous:
        codes = [anonymous.get(path).status_code for path in ("/openapi.json", "/docs", "/redoc")]
    assert codes == [404, 404, 404]


@pytest.mark.skipif(importlib.util.find_spec("sentry_sdk") is None, reason="sentry-sdk missing")
def test_sentry_captures_errors_without_secrets(settings: Any) -> None:
    """An unhandled error reaches Sentry's transport, with the Authorization header scrubbed."""
    import sentry_sdk
    from sentry_sdk.transport import Transport

    from notes_api.core.sentry import install_sentry

    class CapturingTransport(Transport):
        """Keeps envelopes instead of sending them."""

        def __init__(self) -> None:
            """Start empty."""
            super().__init__()
            self.events: list[dict[str, Any]] = []

        def capture_envelope(self, envelope: Any) -> None:
            """Store the event of each envelope."""
            if (event := envelope.get_event()) is not None:
                self.events.append(event)

    transport = CapturingTransport()
    dsn = SecretStr("https://public@sentry.example/1")
    sentry_settings = settings.model_copy(update={"sentry_dsn": dsn})
    try:
        assert install_sentry(sentry_settings, transport=transport)
        sentry_sdk.capture_exception(RuntimeError("boom"))
        sentry_sdk.flush()
        assert transport.events and transport.events[0]["exception"]["values"][0]["type"] == (
            "RuntimeError"
        )
        scrubbed = {"request": {"headers": {"Authorization": "Bearer abc.def.ghi", "X": "1"}}}
        from notes_api.core.sentry import scrub_event

        assert scrub_event(scrubbed, {})["request"]["headers"] == {
            "Authorization": "[REDACTED]",
            "X": "1",
        }
    finally:
        sentry_sdk.init()  # no DSN: back to a disabled client
'''

NOTES_V6_TESTS_TEST_MIDDLEWARE_PY = r'''
%%writefile ../projects/notes_api/tests/test_middleware.py
"""Request ids, Server-Timing, GZip, CORS and the order of the middleware stack."""

import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from helpers import create
from notes_api.core.middleware import RequestIdMiddleware, TimingMiddleware


def test_request_id_is_generated_echoed_or_replaced(client: TestClient) -> None:
    """No header → a new hex id; a safe header is reused; an unsafe one is replaced."""
    generated = client.get("/health").headers["x-request-id"]
    assert re.fullmatch(r"[0-9a-f]{32}", generated)
    assert (
        client.get("/health", headers={"X-Request-ID": "abc-123"}).headers["x-request-id"]
        == "abc-123"
    )
    replaced = client.get("/health", headers={"X-Request-ID": "bad id\twith spaces"}).headers[
        "x-request-id"
    ]
    assert re.fullmatch(r"[0-9a-f]{32}", replaced)


def test_problem_bodies_carry_the_request_id(client: TestClient) -> None:
    """The id in the error body matches the header, so a client can quote it in a report."""
    response = client.get("/api/v1/notes/99", headers={"X-Request-ID": "trace-42"})
    assert response.json()["request_id"] == response.headers["x-request-id"] == "trace-42"


def test_server_timing_header(client: TestClient) -> None:
    """Every response says how long the app took, in milliseconds."""
    assert re.fullmatch(r"app;dur=\d+\.\d", client.get("/health").headers["server-timing"])


def test_large_responses_are_gzipped(client: TestClient) -> None:
    """Responses over 1000 bytes are compressed when the client accepts gzip."""
    for number in range(10):
        create(client, title=f"Note {number}", body="lorem ipsum " * 20)
    big = client.get("/api/v1/notes", headers={"Accept-Encoding": "gzip"})
    small = client.get("/health", headers={"Accept-Encoding": "gzip"})
    assert big.headers["content-encoding"] == "gzip"
    assert "content-encoding" not in small.headers


def test_cors_preflight_for_an_allowed_and_a_foreign_origin(client: TestClient) -> None:
    """The configured origin may send X-API-Key; other origins get no CORS headers."""
    preflight = {
        "Access-Control-Request-Method": "PATCH",
        "Access-Control-Request-Headers": "x-api-key",
    }
    allowed = client.options(
        "/api/v1/notes/1", headers={"Origin": "http://localhost:5173", **preflight}
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "PATCH" in allowed.headers["access-control-allow-methods"]
    foreign = client.options(
        "/api/v1/notes/1", headers={"Origin": "https://evil.example", **preflight}
    )
    assert foreign.status_code == 400
    assert "access-control-allow-origin" not in foreign.headers


def test_simple_cors_request_exposes_headers(client: TestClient) -> None:
    """A cross-origin GET may read X-Request-ID because the app exposes it."""
    response = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert "X-Request-ID" in response.headers["access-control-expose-headers"]


def test_middleware_order(app: FastAPI) -> None:
    """Outermost first: request id, access log, metrics, security headers, CORS, GZip, timing.

    OpenTelemetry wraps the whole stack (it patches build_middleware_stack), outside all of them.
    """
    assert app._is_instrumented_by_opentelemetry  # noqa: SLF001
    names = [middleware.cls.__name__ for middleware in app.user_middleware]
    assert names == [
        "RequestIdMiddleware",
        "AccessLogMiddleware",
        "MetricsMiddleware",
        "SecurityHeadersMiddleware",
        "CORSMiddleware",
        "GZipMiddleware",
        "TimingMiddleware",
    ]
    assert {RequestIdMiddleware, TimingMiddleware} <= {
        middleware.cls for middleware in app.user_middleware
    }


def test_security_headers(client: TestClient) -> None:
    """HSTS, nosniff, frame denial and a CSP on API responses; the docs get their own CSP."""
    headers = client.get("/health").headers
    assert headers["strict-transport-security"].startswith("max-age=31536000")
    assert (headers["x-content-type-options"], headers["x-frame-options"]) == ("nosniff", "DENY")
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert "cdn.jsdelivr.net" in client.get("/docs").headers["content-security-policy"]
'''

NOTES_V6_TESTS_TEST_NOTES_PY = r'''
%%writefile ../projects/notes_api/tests/test_notes.py
"""Behaviour of the /api/v1/notes endpoints."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from helpers import create, ids

NOTES = "/api/v1/notes"


def test_health(client: TestClient) -> None:
    """GET /health answers ok."""
    assert client.get("/health").json() == {"status": "ok"}


def test_create_returns_201_location_and_normalized_fields(client: TestClient) -> None:
    """POST returns 201, a Location header and cleaned-up fields."""
    response = client.post(
        NOTES, json={"title": "  Buy tea  ", "body": "Assam, 500 g", "tags": ["Shop", "shop"]}
    )
    assert response.status_code == 201
    assert response.headers["location"] == "/api/v1/notes/1"
    note = response.json()
    assert {key: note[key] for key in ("id", "title", "tags", "pinned", "word_count")} == {
        "id": 1,
        "title": "Buy tea",
        "tags": ["shop"],
        "pinned": False,
        "word_count": 3,
    }
    assert note["created_at"] == note["updated_at"]


@pytest.mark.parametrize(
    ("body", "location"),
    [
        ({}, ["body", "title"]),
        ({"title": "   "}, ["body", "title"]),
        ({"title": "x", "color": "red"}, ["body", "color"]),
        ({"title": "x", "tags": ["two words"]}, ["body", "tags", 0]),
        ({"title": "x", "tags": [f"tag-{number}" for number in range(11)]}, ["body", "tags"]),
    ],
)
def test_create_rejects_invalid_input(
    client: TestClient, body: dict[str, Any], location: list[Any]
) -> None:
    """Invalid bodies are 422 problems pointing at the bad field."""
    response = client.post(NOTES, json=body)
    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"] == location


def test_get_one_and_unknown_id(client: TestClient) -> None:
    """GET returns the note; an unknown id is a 404 problem."""
    create(client)
    assert client.get(f"{NOTES}/1").json()["title"] == "Buy tea"
    missing = client.get(f"{NOTES}/99")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "note 99 not found"


def test_list_paginates_and_counts_all_matches(client: TestClient) -> None:
    """limit/offset select a page; total counts every match."""
    for number in range(5):
        create(client, title=f"Note {number}")
    page = client.get(NOTES, params={"limit": 2, "offset": 2, "sort": "created_at"}).json()
    assert [note["title"] for note in page["items"]] == ["Note 2", "Note 3"]
    assert (page["total"], page["limit"], page["offset"]) == (5, 2, 2)


def test_list_filters_by_tag_pinned_and_text(client: TestClient) -> None:
    """tag (all of them), pinned and q filters combine."""
    create(client, title="Tea", tags=["shop", "food"], pinned=True)
    create(client, title="Rice", tags=["shop"], body="basmati")
    create(client, title="Call Ravi", tags=["home"])
    assert ids(client.get(NOTES, params={"tag": ["shop", "food"]})) == [1]
    assert ids(client.get(NOTES, params={"pinned": False, "sort": "title"})) == [3, 2]
    assert ids(client.get(NOTES, params={"q": "BASMATI"})) == [2]


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "sort=size", "color=red"])
def test_list_rejects_bad_parameters(client: TestClient, query: str) -> None:
    """Out-of-range, unknown or extra query parameters are 422 problems."""
    assert client.get(f"{NOTES}?{query}").status_code == 422


def test_put_replaces_every_field(client: TestClient) -> None:
    """PUT resets omitted fields to their defaults."""
    create(client, body="old body", tags=["shop"], pinned=True)
    replaced = client.put(f"{NOTES}/1", json={"title": "New title"}).json()
    assert (replaced["title"], replaced["body"], replaced["tags"], replaced["pinned"]) == (
        "New title",
        "",
        [],
        False,
    )


def test_patch_changes_only_the_fields_sent(client: TestClient) -> None:
    """PATCH keeps the other fields and moves updated_at."""
    created = create(client, body="Assam", tags=["shop"])
    patched = client.patch(f"{NOTES}/1", json={"pinned": True}).json()
    assert (patched["pinned"], patched["body"], patched["tags"]) == (True, "Assam", ["shop"])
    assert patched["updated_at"] > created["updated_at"]


def test_patch_without_a_change_keeps_updated_at(client: TestClient) -> None:
    """Sending the current values is not a change."""
    created = create(client, pinned=True)
    patched = client.patch(f"{NOTES}/1", json={"pinned": True}).json()
    assert patched["updated_at"] == created["updated_at"]


@pytest.mark.parametrize("body", [{"title": None}, {"pinned": None}, {"color": "red"}])
def test_patch_rejects_null_and_unknown_fields(client: TestClient, body: dict[str, Any]) -> None:
    """Explicit null and unknown fields are 422 problems."""
    create(client)
    assert client.patch(f"{NOTES}/1", json=body).status_code == 422


def test_delete_then_gone(client: TestClient) -> None:
    """DELETE returns 204 with no body; the note is gone afterwards."""
    create(client)
    response = client.delete(f"{NOTES}/1")
    assert (response.status_code, response.content) == (204, b"")
    assert client.get(f"{NOTES}/1").status_code == 404


@pytest.mark.parametrize("method", ["GET", "PUT", "PATCH", "DELETE"])
def test_unknown_note_is_404_for_every_method(client: TestClient, method: str) -> None:
    """Every operation on a missing note is a 404 problem."""
    response = client.request(method, f"{NOTES}/7", json={"title": "x"})
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"


def test_openapi_uses_function_names_and_versioned_paths(client: TestClient) -> None:
    """Operation ids are function names; JSON routes live under /api/v1; pages are hidden."""
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    assert paths[NOTES]["post"]["operationId"] == "create_note"
    assert paths[f"{NOTES}/feed"]["get"]["operationId"] == "notes_feed"
    assert "/" not in paths
    assert "Page_NoteRead_" in schema["components"]["schemas"]


def test_patch_with_the_current_version_bumps_it(client: TestClient) -> None:
    """Sending the version you read succeeds and increments it."""
    assert create(client)["version"] == 1
    patched = client.patch(f"{NOTES}/1", json={"pinned": True, "version": 1}).json()
    assert patched["version"] == 2


def test_patch_with_a_stale_version_is_a_409_problem(client: TestClient) -> None:
    """Optimistic locking: an old version means someone else changed the note first."""
    create(client)
    client.patch(f"{NOTES}/1", json={"title": "Changed elsewhere"})
    stale = client.patch(f"{NOTES}/1", json={"pinned": True, "version": 1})
    assert stale.status_code == 409
    assert stale.json()["type"] == "/problems/version-conflict"
    assert stale.json()["detail"] == "note 1 is at version 2, not 1; read it again"
    assert client.get(f"{NOTES}/1").json()["pinned"] is False


def test_tags_are_returned_sorted_and_shared(client: TestClient) -> None:
    """Tags come back in name order; the same name is one row shared by many notes."""
    assert create(client, tags=["work", "Home"])["tags"] == ["home", "work"]
    create(client, title="Second", tags=["home"])
    assert ids(client.get(NOTES, params={"tag": "home", "sort": "created_at"})) == [1, 2]


def test_search_treats_percent_and_underscore_literally(client: TestClient) -> None:
    """q is escaped for LIKE: '%' only matches a real percent sign."""
    create(client, title="100% done")
    create(client, title="Plain")
    assert ids(client.get(NOTES, params={"q": "%"})) == [1]
    assert ids(client.get(NOTES, params={"q": "_"})) == []


def test_readiness_checks_the_database(client: TestClient) -> None:
    """/health/ready runs SELECT 1 and pings Redis."""
    expected = {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}
    assert client.get("/health/ready").json() == expected
'''

NOTES_V6_TESTS_TEST_MIGRATIONS_PY = r'''
%%writefile ../projects/notes_api/tests/test_migrations.py
"""The Alembic migrations run up and down on SQLite, and 0002 copies the tag data."""

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

PROJECT_DIR = Path(__file__).resolve().parent.parent


def alembic_config(database_file: Path) -> Config:
    """alembic.ini with the URL of a test database."""
    config = Config(PROJECT_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_file}")
    config.attributes["configure_logger"] = False
    return config


def test_upgrade_downgrade_round_trip(tmp_path: Path) -> None:
    """head creates every table; base removes them again."""
    database_file = tmp_path / "migrations.db"
    config = alembic_config(database_file)
    command.upgrade(config, "head")
    engine = sa.create_engine(f"sqlite:///{database_file}")
    assert set(sa.inspect(engine).get_table_names()) == {
        "alembic_version",
        "notes",
        "tags",
        "note_tags",
        "users",
        "refresh_tokens",
        "api_keys",
        "outbox_events",
    }
    command.downgrade(config, "base")
    assert sa.inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()


def test_data_migration_moves_tags_and_back(tmp_path: Path) -> None:
    """0002 turns 'shop,food' text into rows; downgrading writes the text back."""
    database_file = tmp_path / "data.db"
    config = alembic_config(database_file)
    command.upgrade(config, "0001")
    engine = sa.create_engine(f"sqlite:///{database_file}")
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO notes (title, tags) VALUES ('Tea', 'shop,food')"))
        connection.execute(sa.text("INSERT INTO notes (title, tags) VALUES ('Rice', 'shop')"))
    command.upgrade(config, "0002")
    with engine.connect() as connection:
        links = connection.execute(
            sa.text(
                "SELECT notes.title, tags.name FROM note_tags JOIN notes ON notes.id = note_id"
                " JOIN tags ON tags.id = tag_id ORDER BY notes.title, tags.name"
            )
        ).all()
    assert [tuple(row) for row in links] == [("Rice", "shop"), ("Tea", "food"), ("Tea", "shop")]
    command.downgrade(config, "0001")
    with engine.connect() as connection:
        rows = connection.execute(sa.text("SELECT title, tags FROM notes ORDER BY id")).all()
    assert [tuple(row) for row in rows] == [("Tea", "food,shop"), ("Rice", "shop")]
    engine.dispose()


def test_existing_notes_get_a_disabled_legacy_owner(tmp_path: Path) -> None:
    """0004 gives notes written before accounts existed to an owner that cannot log in."""
    database_file = tmp_path / "owners.db"
    config = alembic_config(database_file)
    command.upgrade(config, "0003")
    engine = sa.create_engine(f"sqlite:///{database_file}")
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO notes (title) VALUES ('Old note')"))
    command.upgrade(config, "head")
    with engine.connect() as connection:
        owner = connection.execute(
            sa.text(
                "SELECT users.email, users.is_active, users.password_hash FROM notes"
                " JOIN users ON users.id = notes.owner_id"
            )
        ).one()
    assert tuple(owner) == ("legacy-owner@notes.invalid", 0, None)
    engine.dispose()


def test_schema_revision_is_the_newest_migration() -> None:
    """The revision /health/startup expects is the head of the migration history."""
    from alembic.script import ScriptDirectory

    from notes_api.db import SCHEMA_REVISION, SCHEMA_REVISIONS

    script = ScriptDirectory.from_config(alembic_config(PROJECT_DIR / "unused.db"))
    chain = tuple(revision.revision for revision in script.walk_revisions())[::-1]
    assert (script.get_current_head(), chain) == (SCHEMA_REVISION, SCHEMA_REVISIONS)
'''

NOTES_V6_TESTS_TEST_POSTGRES_PY = r'''
%%writefile ../projects/notes_api/tests/test_postgres.py
"""The same app on PostgreSQL in Docker: migrations, drift check, trigram search, races.

Uses the CI service (NOTES_TEST_DATABASE_URL) or a testcontainer; skipped without either.
Run only these: `uv run pytest -m postgres`; skip them: `uv run pytest -m "not postgres"`.
"""

import asyncio
import secrets
from collections.abc import Iterator
from datetime import UTC, datetime

import fakeredis
import pytest
import sqlalchemy as sa
from alembic import command
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from helpers import USER_EMAIL, auth_headers, postgres_alembic_config
from notes_api.core.config import Settings
from notes_api.dependencies import get_redis
from notes_api.main import create_app
from notes_api.repositories import SqlNoteRepository, SqlUserRepository
from notes_api.schemas import NoteCreate

pytestmark = pytest.mark.postgres


@pytest.fixture
def empty_url(postgres_url: str) -> Iterator[str]:
    """The database with every row removed and ids restarted, before and after the test.

    The database is shared with test_postgres_rollback.py (session-scoped), so these
    committing tests clean up after themselves.
    """

    async def truncate() -> None:
        """TRUNCATE all tables."""
        engine = create_async_engine(postgres_url)
        async with engine.begin() as connection:
            await connection.execute(
                sa.text("TRUNCATE notes, tags, users RESTART IDENTITY CASCADE")
            )
        await engine.dispose()

    asyncio.run(truncate())
    yield postgres_url
    asyncio.run(truncate())


def test_models_match_the_migrations(postgres_url: str) -> None:
    """alembic check: autogenerate finds no difference between the models and the schema."""
    command.check(postgres_alembic_config(postgres_url))


def test_api_round_trip_on_postgres(empty_url: str) -> None:
    """Create, search (ILIKE), feed, PATCH with versions and the 409, on the real database."""
    settings = Settings(
        _env_file=None,
        environment="test",
        jwt_secret=SecretStr(secrets.token_urlsafe(32)),
        password_time_cost=1,
        password_memory_kib=64,
        database_url=SecretStr(empty_url),
    )
    app = create_app(settings)
    app.dependency_overrides[get_redis] = lambda: fakeredis.FakeAsyncRedis(decode_responses=True)
    with TestClient(app) as client:
        client.headers.update(auth_headers(client, USER_EMAIL))
        for title in ("Buy Tea", "Steep the tea", "Call Ravi"):
            assert (
                client.post("/api/v1/notes", json={"title": title, "tags": ["x"]}).status_code
                == 201
            )
        found = client.get("/api/v1/notes", params={"q": "TEA", "sort": "title"}).json()
        assert [note["title"] for note in found["items"]] == ["Buy Tea", "Steep the tea"]
        feed = client.get("/api/v1/notes/feed", params={"limit": 2}).json()
        assert [note["id"] for note in feed["items"]] == [3, 2] and feed["next_cursor"]
        assert (
            client.patch("/api/v1/notes/1", json={"pinned": True, "version": 1}).json()["version"]
            == 2
        )
        assert (
            client.patch("/api/v1/notes/1", json={"pinned": False, "version": 1}).status_code == 409
        )
        assert client.get("/health/ready").json()["checks"]["database"] == "ok"


def test_trigram_index_serves_substring_search(empty_url: str) -> None:
    """EXPLAIN shows ILIKE '%tea%' using the GIN trigram index (sequential scans off)."""

    async def plan() -> str:
        """The query plan of a title search."""
        async_engine = create_async_engine(empty_url)
        async with async_engine.begin() as connection:
            await connection.execute(sa.text("SET LOCAL enable_seqscan = off"))
            rows = await connection.execute(
                sa.text("EXPLAIN SELECT id FROM notes WHERE title ILIKE '%tea%'")
            )
            text = "\n".join(row[0] for row in rows)
        await async_engine.dispose()
        return text

    assert "ix_notes_title_trgm" in asyncio.run(plan())


def test_concurrent_new_tag_is_absorbed_by_the_savepoint(empty_url: str) -> None:
    """Two transactions add one new tag; a SAVEPOINT absorbs the loser's unique violation."""
    now = datetime(2026, 11, 17, tzinfo=UTC)

    async def race() -> list[list[str]]:
        """Run the two transactions concurrently and report each note's tags."""
        engine = create_async_engine(empty_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        first_flushed = asyncio.Event()
        async with factory() as session, session.begin():
            owner = await SqlUserRepository(session).add_user("racer@example.com", None, "user")

        async def first() -> list[str]:
            """Insert the tag, hold the transaction open for a moment, then commit."""
            async with factory() as session, session.begin():
                note = await SqlNoteRepository(session).add(
                    NoteCreate(title="A", tags=["race"]), now, owner.id
                )
                first_flushed.set()
                await asyncio.sleep(0.3)  # the second transaction blocks on the unique index
                return list(note.tags)

        async def second(session_factory: async_sessionmaker[AsyncSession]) -> list[str]:
            """Insert the same tag while the first transaction still holds it."""
            await first_flushed.wait()
            async with session_factory() as session, session.begin():
                note = await SqlNoteRepository(session).add(
                    NoteCreate(title="B", tags=["race"]), now, owner.id
                )
                return list(note.tags)

        results = await asyncio.gather(first(), second(factory))
        async with engine.connect() as connection:
            tag_count = await connection.scalar(sa.text("SELECT count(*) FROM tags"))
        await engine.dispose()
        assert tag_count == 1
        return list(results)

    assert asyncio.run(race()) == [["race"], ["race"]]
'''

NOTES_V6_TESTS_TEST_REDIS_WORKER_PY = r'''
%%writefile ../projects/notes_api/tests/test_redis_worker.py
"""End to end on a real Redis (testcontainer) with the real ARQ worker in burst mode.

Skipped without Docker. Run only these: `uv run pytest -m redis`.
"""

import asyncio

import pytest
import respx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from helpers import USER_EMAIL, FakeMailer, auth_headers, create, create_tables, fake_resolver
from notes_api.core.config import Settings
from notes_api.dependencies import get_mailer, get_resolver
from notes_api.events import SIGNATURE_HEADER, verify_webhook
from notes_api.main import create_app
from notes_api.worker import run_worker

pytestmark = pytest.mark.redis
HOOK = "https://hooks.example/notes"


@pytest.fixture
def real_settings(settings: Settings, redis_url: str) -> Settings:
    """The test settings, but with the real Redis."""
    return settings.model_copy(update={"redis_url": SecretStr(redis_url)})


def burst(settings: Settings) -> None:
    """Process every queued job (and the jobs they queue), then stop."""
    asyncio.run(run_worker(burst=True, settings=settings, resolver=fake_resolver))


@respx.mock
def test_write_kick_relay_and_signed_webhook(real_settings: Settings) -> None:
    """A note change reaches the user's webhook through outbox → kick → relay → job."""
    receiver = respx.post(HOOK).respond(204)
    asyncio.run(create_tables(real_settings))
    app = create_app(real_settings)
    app.dependency_overrides[get_resolver] = lambda: fake_resolver
    app.dependency_overrides[get_mailer] = FakeMailer
    with TestClient(app) as client:
        client.headers.update(auth_headers(client, USER_EMAIL))
        secret = client.put("/api/v1/users/me/webhook", json={"url": HOOK}).json()["secret"]
        create(client, title="Real Redis")
        burst(real_settings)
        request = receiver.calls.last.request
        timestamp = int(request.headers[SIGNATURE_HEADER].split(",")[0][2:])
        assert verify_webhook(secret, request.headers[SIGNATURE_HEADER], request.content, timestamp)
        assert b'"type":"note.created"' in request.content

        export = client.post("/api/v1/exports").json()
        burst(real_settings)
        events = client.get(export["events_url"]).text
        assert '"status":"done","done":1,"total":1' in events
'''
