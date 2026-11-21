"""Unit 6.6 — Background Jobs, Real-Time and Caching (with Lab 6.6 and Notes API v5)."""

from helpers_module import setup_cells
from nbformat import NotebookNode

from nb_builder import code, md, predict_cells, writefile_cells

UNIT_SETUP_SOURCE = r"""
import asyncio
import atexit
import base64
import contextlib
import dataclasses
import email.utils
import hashlib
import hmac
import importlib
import importlib.util
import inspect
import json
import logging
import os
import random
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import textwrap
import time
import urllib.request
import uuid
import warnings
from collections import defaultdict
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
import jwt
import pwdlib
import pydantic
import pydantic_settings
import redis.asyncio as redis_asyncio
import respx
import sqlalchemy as sa
import starlette
import uvicorn
from arq import Retry, cron
from arq.connections import ArqRedis, RedisSettings, create_pool
from arq.cron import next_cron
from arq.worker import Worker
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
    WebSocket,
    status,
)
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pydantic import BaseModel, SecretStr
from sqlalchemy import event

# arq 0.25 calls asyncio.iscoroutinefunction (deprecated in 3.14) and redis' deprecated close()
warnings.filterwarnings(
    "ignore", message=".*iscoroutinefunction.* is deprecated", category=DeprecationWarning
)
warnings.filterwarnings("ignore", message="Call to deprecated close", category=DeprecationWarning)

"""

WORKER_HELPERS_SOURCE = r'''
@contextlib.contextmanager
def worker_process(
    command: list[str],
    ready: Callable[[], bool],
    *,
    extra_env: dict[str, str] | None = None,
    cwd: Path = PHASE6_DIR,
    timeout: float = 20.0,
) -> Iterator[subprocess.Popen]:
    """Start a background worker process, wait until ready() is true, always stop it afterwards."""
    log_path = PHASE6_DIR / f"worker_{secrets.token_hex(3)}.log"
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            command,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=cwd,
            env={**CHILD_ENV, **(extra_env or {})},
        )
    try:
        deadline = time.monotonic() + timeout
        while not ready():
            if process.poll() is not None or time.monotonic() > deadline:
                print(log_path.read_text(encoding="utf-8")[-2000:])
                raise RuntimeError(f"worker did not become ready (exit code {process.poll()})")
            time.sleep(0.1)
        yield process
    finally:
        process.terminate()  # SIGTERM: arq finishes the running job, then exits
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        log_path.unlink(missing_ok=True)


def redis_key_exists(url: str, key: str) -> bool:
    """Synchronous check used as a readiness probe (a fresh client each time)."""
    import redis

    client = redis.Redis.from_url(url)
    try:
        return bool(client.exists(key))
    finally:
        client.close()


def format_sse(
    data: object, *, event_name: str | None = None, event_id: str | int | None = None
) -> str:
    """One Server-Sent Events message: optional id and event lines, JSON data, a blank line."""
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    if event_name is not None:
        lines.append(f"event: {event_name}")
    lines.append(f"data: {json.dumps(data)}")
    return "\n".join(lines) + "\n\n"


print(f"{arq.VERSION=}  {fakeredis.__version__=}  {respx.__version__=}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 6.6 — Background Jobs, Real-Time and Caching

            **Objectives**

            - Use `BackgroundTasks` for small after-the-response work, and know its limits.
            - Explain the broker/worker architecture and compare Celery, ARQ, Dramatiq and
              Taskiq; run a real ARQ worker against Redis.
            - Make background work reliable: idempotency, retries with backoff, dead-letter
              queues, the transactional outbox, scheduled jobs and distributed locks.
            - Push live updates with WebSockets: the handshake, `@app.websocket`, connection
              managers, authentication, heartbeats and fan-out through Redis.
            - Stream with Server-Sent Events: the event-stream format, `StreamingResponse`,
              `Last-Event-ID`, `EventSource`; choose between SSE, WebSockets and polling; stream
              LLM-style tokens.
            - Cache over HTTP with `Cache-Control`, `ETag` and 304 responses.
            - Cache in Redis: cache-aside, TTLs, key design, invalidation, stampede protection.
            - Choose between Redis pub/sub and Streams; send signed webhooks.
            - Move the **Notes API to v5**: an ARQ worker, a transactional outbox with signed
              webhooks, WebSocket live updates, SSE export progress, ETags and a Redis cache.

            **JS bridge**

            | JavaScript / TypeScript | Python | The difference that bites |
            | --- | --- | --- |
            | `res.on("finish", ...)` / `setImmediate` after `res.send()` | `BackgroundTasks` | runs in the same process after the response; lost if the process dies |
            | BullMQ (Redis queues, workers, repeatable jobs) | ARQ (asyncio, Redis), Celery, Dramatiq, Taskiq | ARQ's job ids give enqueue-once semantics; retries are explicit (`Retry`) |
            | Socket.IO | FastAPI/Starlette WebSockets (+ Redis pub/sub for fan-out) | plain WebSocket protocol: no rooms, acks or auto-reconnect unless you build them |
            | `EventSource` / `res.write("data: ...\\n\\n")` | `StreamingResponse(media_type="text/event-stream")` | same wire format; the browser side is identical |
            | `etag` / `fresh` in Express | an `ETag` header + `If-None-Match` check (by hand or middleware) | FastAPI does not add ETags for you |
            | `ioredis` caching, `node-cache` | `redis.asyncio`, in-process `functools.lru_cache` / `cachetools` | a per-process cache is not shared between Uvicorn workers |
            | Stripe-style webhook signatures (`stripe.webhooks.constructEvent`) | HMAC-SHA256 over `timestamp.body` with `hmac.compare_digest` | same scheme, same replay window |

            Run the setup cells first. Part 1: the imports (arq, Redis, fakeredis, respx):
            """
        ),
        *setup_cells(
            "6.6",
            UNIT_SETUP_SOURCE,
            """
            Part 2: the shared helpers from [`phase6_helpers.py`](phase6_helpers.py) (server, Notes API, database and Redis
            helpers of Units 6.1–6.5), including this unit's `worker_process(command, ready)`
            (starts a worker in a background process, waits until `ready()` is true, **always**
            stops it), `redis_key_exists()` and `format_sse()`. Docker is used for a real Redis
            (one container for the unit, started in 6.6.2 and removed in the *Clean up* cell);
            without it the demos fall back to fakeredis and the worker demos print skip
            messages:
            """,
            folders="*NOTES_FOLDERS",
        ),
    ]


def _background_tasks_cells() -> list[NotebookNode]:
    """6.6.1 BackgroundTasks."""
    return [
        md(
            """
            ### 6.6.1 `BackgroundTasks`

            A handler that declares a `BackgroundTasks` parameter can queue functions that run
            **after the response has been sent**, in the same process (`async def` tasks on the
            event loop, `def` tasks in the thread pool). Typical uses: a welcome e-mail, a cache
            invalidation, an audit record. The order of events, made visible with a tiny ASGI
            wrapper that notes when the last body chunk leaves:
            """
        ),
        code(
            r'''
            EVENTS: list[str] = []
            ordering_app = FastAPI()


            def record_task(name: str) -> None:
                """A background task."""
                EVENTS.append(f"task {name}")


            @ordering_app.post("/signup")
            def signup(background: BackgroundTasks) -> dict[str, bool]:
                """Queue two tasks; they run after the response, in order."""
                background.add_task(record_task, "welcome-email")
                background.add_task(record_task, "audit-log")
                EVENTS.append("handler returns")
                return {"ok": True}


            class ResponseSentMarker:
                """Pure ASGI wrapper: note the moment the final response chunk is sent."""

                def __init__(self, app: Any) -> None:
                    """Wrap the app."""
                    self.app = app

                async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
                    """Forward everything; log the last body message."""

                    async def marking_send(message: dict) -> None:
                        """Send, then record the end of the response."""
                        await send(message)
                        if message["type"] == "http.response.body" and not message.get("more_body"):
                            EVENTS.append("response sent")

                    await self.app(scope, receive, marking_send)


            with TestClient(ResponseSentMarker(ordering_app)) as client:
                client.post("/signup")
            print(EVENTS)
            '''
        ),
        md(
            """
            Under the hood, `BackgroundTasks` is a list of `BackgroundTask` objects (function +
            arguments) that Starlette runs, in order, after sending the response. `vars()` shows
            what each one stores, and `inspect` shows that `async def` tasks are awaited while
            plain functions go to the thread pool:
            """
        ),
        code(
            r'''
            async def async_job(note_id: int) -> None:
                """An async background task."""


            queued = BackgroundTasks()
            queued.add_task(record_task, "welcome-email")
            queued.add_task(async_job, 42)
            for task in queued.tasks:
                details = {key: value for key, value in vars(task).items() if key != "func"}
                is_coroutine = inspect.iscoroutinefunction(task.func)
                print(f"{task.func.__name__:12} coroutine={is_coroutine!s:5} {details}")
            '''
        ),
        md(
            """
            Under a real server the client gets its answer **before** the task finishes. The
            demo app sleeps 1 s in a background task and writes a file; the client's request
            returns at once, and the file appears a second later:
            """
        ),
        code(
            r'''
            %%writefile _scratch/phase6/background_demo.py
            # A slow background task under Uvicorn: the response does not wait for it.
            import asyncio
            from pathlib import Path

            from fastapi import BackgroundTasks, FastAPI

            app = FastAPI()
            MARKER = Path(__file__).with_name("background_done.txt")


            @app.get("/health")
            def health() -> dict[str, str]:
                """Liveness probe for the server helper."""
                return {"status": "ok"}


            async def slow_email(address: str) -> None:
                """Pretend to talk to an SMTP server, then leave a marker file."""
                await asyncio.sleep(1.0)  # pretend to talk to an SMTP server
                MARKER.write_text(f"sent to {address}")


            @app.post("/signup")
            async def signup(background: BackgroundTasks) -> dict[str, str]:
                """Answer at once; the e-mail is sent after the response."""
                MARKER.unlink(missing_ok=True)
                background.add_task(slow_email, "asha@example.com")
                return {"status": "registered"}
            '''
        ),
        md("Time the request, then wait for the task:"),
        code(
            r"""
            with uvicorn_server("background_demo:app") as base_url:
                with httpx.Client(base_url=base_url, trust_env=False) as client:
                    with Timer("signup", report=None) as request_timer:
                        reply = client.post("/signup")
                    marker = PHASE6_DIR / "background_done.txt"
                    print(
                        f"response {reply.json()} after {request_timer.elapsed_seconds:.2f} s"
                        f"; file exists: {marker.exists()}"
                    )
                    time.sleep(1.3)
                    print("1.3 s later the file exists:", marker.exists(), "->", marker.read_text())
            """
        ),
        md(
            """
            **Limits.** `BackgroundTasks` is a convenience, not a job system:

            | Limit | Consequence | Use instead |
            | --- | --- | --- |
            | runs in the web process | a deploy, crash or OOM kill loses queued tasks | a task queue (6.6.2) |
            | no retries | a failing SMTP call is just a log line | retries with backoff (6.6.3) |
            | the client already got 2xx | an error cannot change the response | do critical work before responding |
            | competes with requests | CPU-heavy tasks slow every request (and the GIL) | a separate worker process |
            | request-scoped dependencies are closed | the request's DB session is gone (`scope="function"` closes it before the response) | open a new session in the task |

            A failing task, seen from the client:
            """
        ),
        code(
            r'''
            failing_app = FastAPI()


            def flaky_email(address: str) -> None:
                """A task that crashes after the response."""
                raise ConnectionError(f"SMTP server unreachable for {address}")


            @failing_app.post("/signup")
            def failing_signup(background: BackgroundTasks) -> dict[str, str]:
                """Respond 200, then fail in the background."""
                background.add_task(flaky_email, "asha@example.com")
                return {"status": "registered"}


            with TestClient(failing_app, raise_server_exceptions=False) as client:
                reply = client.post("/signup")
                print("client saw:", reply.status_code, reply.json(), "- and nobody will retry the e-mail")
            '''
        ),
        md(
            """
            And the closed dependency: a yield-dependency with `scope="function"` finishes
            before the response is sent, so by the time the task runs its resource is closed
            (the Notes API's `kick_relay` task therefore gets only the queue client, never the
            request's session):
            """
        ),
        code(
            r'''
            class FakeSession:
                """Stands in for a database session."""

                def __init__(self) -> None:
                    """Open."""
                    self.closed = False


            def get_fake_session() -> Iterator[FakeSession]:
                """Yield a session and close it afterwards."""
                session = FakeSession()
                yield session
                session.closed = True


            session_app = FastAPI()
            SEEN_BY_TASK: list[bool] = []


            @session_app.post("/work")
            def work(
                background: BackgroundTasks,
                session: Annotated[FakeSession, Depends(get_fake_session, scope="function")],
            ) -> dict[str, bool]:
                """Hand the request's session to a task (a mistake)."""
                background.add_task(lambda: SEEN_BY_TASK.append(session.closed))
                return {"closed during handler": session.closed}


            with TestClient(session_app) as client:
                print(client.post("/work").json(), "| closed when the task ran:", SEEN_BY_TASK)
            '''
        ),
    ]


def _queue_cells() -> list[NotebookNode]:
    """6.6.2 Task queues."""
    return [
        md(
            """
            ### 6.6.2 Task queues

            A task queue moves work out of the web process. The API (the **producer**) writes a
            job description to a **broker**; separate **worker** processes take jobs, run them
            and may store results:

            ```mermaid
            flowchart LR
                api1[API process] -- enqueue --> broker[(Broker: Redis / RabbitMQ)]
                api2[API process] -- enqueue --> broker
                broker -- dequeue --> w1[Worker 1]
                broker -- dequeue --> w2[Worker 2]
                w1 -- result / retry --> broker
                cron[Scheduler / cron] -- enqueue --> broker
            ```

            <details><summary>ASCII version</summary>

            ```text
            [API] --enqueue--> (broker) --dequeue--> [worker 1]
            [API] --enqueue-->    |     --dequeue--> [worker 2]
                                  '<-- results, retries, scheduled jobs
            ```

            </details>

            Workers can be scaled, restarted and deployed independently, and a job survives a
            crash of the web process. Most brokers deliver **at least once**: a job can run
            twice (a worker dies after doing the work but before acknowledging it), so tasks
            must be **idempotent** (6.6.3).

            | Library | Broker | Model | Strengths | Watch out |
            | --- | --- | --- | --- | --- |
            | **Celery** | RabbitMQ, Redis, SQS | sync (processes/threads; async support limited) | mature, huge ecosystem: canvas (chains, groups), beat scheduler, Flower | heavy configuration; asyncio is not native |
            | **ARQ** | Redis | **asyncio** | tiny, async-native, job ids, deferred jobs, cron, retries; used by the Notes API | Redis only; small feature set; 0.25's CLI does not start on Python 3.14+ (see below) |
            | **Dramatiq** | RabbitMQ, Redis | sync (threads) | simple, reliable defaults (retries, time limits), middleware | asyncio support via an extra actor type |
            | **Taskiq** | Redis, RabbitMQ, NATS, Kafka | **asyncio** | async-native, FastAPI-style dependencies, many brokers | younger project |
            | RQ | Redis | sync (fork per job) | very simple | no Windows, no asyncio |
            | *BullMQ (Node)* | Redis | async | repeatable jobs, flows, priorities | — |

            Celery, Dramatiq and Taskiq are not course dependencies; each cell checks and shows
            the equivalent of the ARQ task below:
            """
        ),
        code(
            r"""
            EQUIVALENTS = {
                "celery": (
                    "@celery_app.task(bind=True, max_retries=5)\ndef send_welcome(self, email): ...\n"
                    'send_welcome.delay("asha@example.com")'
                ),
                "dramatiq": (
                    "@dramatiq.actor(max_retries=5)\ndef send_welcome(email): ...\n"
                    'send_welcome.send("asha@example.com")'
                ),
                "taskiq": (
                    "@broker.task\nasync def send_welcome(email: str) -> None: ...\n"
                    'await send_welcome.kiq("asha@example.com")'
                ),
            }
            for package, snippet in EQUIVALENTS.items():
                status_text = (
                    "installed"
                    if importlib.util.find_spec(package)
                    else "SKIP: not installed (not a course dependency)"
                )
                print(f"--- {package}: {status_text}\n{snippet}")
            """
        ),
        md(
            """
            **ARQ for real.** This unit's Redis container starts now (fakeredis cannot run an
            ARQ worker: the worker uses Redis commands such as `INFO` that fakeredis does not
            implement). The worker module defines tasks as `async def task(ctx, ...)`; `ctx`
            holds the Redis pool, the `job_id` and the try number. A `WorkerSettings` class
            lists functions, cron jobs and startup/shutdown hooks:
            """
        ),
        code(
            r"""
            REDIS_URL = start_shared_redis()
            print(
                "Redis:",
                "testcontainer" if REDIS_URL else "SKIP (no Docker): fakeredis only, worker demos skipped",
            )
            """
        ),
        md(
            """
            The demo worker module. arq 0.25's own command (`arq module.WorkerSettings`) calls
            `asyncio.get_event_loop()` outside a running loop, which raises `RuntimeError` on
            Python 3.14+ (*Changed in 3.14*: it no longer creates a loop implicitly), so
            the module starts the worker itself inside `asyncio.run` (the Notes API's worker
            does the same in `run_worker()`):
            """
        ),
        *writefile_cells(
            ARQ_DEMO_TASKS_SOURCE,
            [
                ("", "Part 1: the tasks (`ctx` first, then the job's own arguments):"),
                (
                    "async def startup(",
                    "Part 2: a startup hook (it tells the notebook the worker is ready), the settings and the entry point:",
                ),
            ],
        ),
        md(
            """
            Start the worker in a background process (it is stopped when the `with` block
            ends, even on errors), enqueue jobs from the notebook with `create_pool`, and wait
            for their results:
            """
        ),
        code(
            r'''
            async def arq_round_trip() -> None:
                """Enqueue three jobs on the real Redis and await their results."""
                pool = await create_pool(RedisSettings.from_dsn(REDIS_URL))
                await pool.delete("demo:worker-ready", "demo:dead-letters")
                ready = lambda: redis_key_exists(REDIS_URL, "demo:worker-ready")  # noqa: E731
                with worker_process(
                    [sys.executable, "-m", "arq_demo_tasks"], ready, extra_env={"REDIS_URL": REDIS_URL}
                ):
                    jobs = [
                        await pool.enqueue_job("send_welcome", email)
                        for email in ("asha@example.com", "ravi@example.com")
                    ]
                    deferred = await pool.enqueue_job("send_welcome", "later@example.com", _defer_by=0.5)
                    print("queued now:", len(await pool.queued_jobs()), "| status:", await jobs[0].status())
                    for job in [*jobs, deferred]:
                        print(await job.result(timeout=10))
                    print("status after:", await jobs[0].status(), "| info:", (await jobs[0].info()).function)
                await pool.aclose()


            if REDIS_URL:
                await arq_round_trip()
            else:
                print("SKIP the ARQ worker demo: no Docker, so no real Redis")
            '''
        ),
        md(
            """
            `enqueue_job` returns a `Job` handle; `status()` goes `queued` → `in_progress` →
            `complete`; `result()` waits for the worker. The deferred job waited 0.5 s in a
            sorted set before a worker could take it.
            """
        ),
    ]


def _reliability_cells() -> list[NotebookNode]:
    """6.6.3 Reliability."""
    return [
        md(
            """
            ### 6.6.3 Reliability

            | Technique | Problem it solves | In the Notes API v5 |
            | --- | --- | --- |
            | **Idempotency** | the same job (or HTTP request) arrives twice | webhook jobs enqueued with `_job_id=webhook:<event id>`; welcome e-mails keyed by user |
            | **Retries with backoff** | transient failures (timeouts, 503s) | `deliver_webhook` raises `Retry(defer=2 ** job_try)` |
            | **Dead-letter queue** | a job that will never succeed must not retry forever or vanish | after `webhook_max_attempts` the event goes to `webhooks:dead`, visible to admins, retryable |
            | **Transactional outbox** | "save to the DB **and** publish an event" cannot be atomic across two systems | `outbox_events` rows written in the note's transaction, published by the relay |
            | **Scheduled jobs** | periodic work | arq `cron`: relay every 10 s, token purge at 03:00 |
            | **Locks** | two workers running the same singleton job | the relay takes `lock:relay-outbox` with `SET NX EX` |

            **Idempotency with a key.** Remember that a piece of work was done, atomically,
            *before* doing it: `SET key value NX EX ttl` succeeds only for the first caller.
            The same pattern implements HTTP `Idempotency-Key` headers:
            """
        ),
        code(
            r'''
            async def charge_once(
                redis_client: Any, idempotency_key: str, ledger: list[str], amount: int
            ) -> str:
                """Run the side effect only for the first delivery of this key."""
                first = await redis_client.set(f"idempotency:{idempotency_key}", "done", nx=True, ex=86_400)
                if not first:
                    return "duplicate ignored"
                ledger.append(f"charged {amount}")
                return "charged"


            async def idempotency_demo() -> None:
                """Deliver the same job three times."""
                redis_client = make_redis(REDIS_URL)
                await redis_client.delete("idempotency:order-1042")
                ledger: list[str] = []
                print([await charge_once(redis_client, "order-1042", ledger, 499) for _ in range(3)], ledger)
                await redis_client.aclose()


            await idempotency_demo()
            '''
        ),
        md(
            """
            ARQ builds this in for enqueueing: a job with an explicit `_job_id` is enqueued only
            if no job with that id is queued, running or has a stored result (fakeredis is
            enough to show it, since no worker is involved):
            """
        ),
        code(
            r'''
            async def job_id_demo() -> None:
                """Enqueue the same job id twice."""
                pool = ArqRedis(connection_pool=fakeredis.FakeAsyncRedis().connection_pool)
                first = await pool.enqueue_job("deliver_webhook", 42, _job_id="webhook:42")
                second = await pool.enqueue_job("deliver_webhook", 42, _job_id="webhook:42")
                print(
                    f"first: {first.job_id if first else None}   second: {second}"
                    f"   queued: {len(await pool.queued_jobs())}"
                )
                await pool.aclose()


            await job_id_demo()
            '''
        ),
        md(
            """
            **Retries and a dead-letter list** with the real worker. `flaky_report` raises
            `Retry` twice (with exponential backoff) and succeeds on the third try;
            `always_fails` gives up on its last try and parks the payload in a dead-letter
            list instead of disappearing:
            """
        ),
        code(
            r'''
            async def retry_demo() -> None:
                """Two jobs that need retries; inspect results and the dead letters."""
                pool = await create_pool(RedisSettings.from_dsn(REDIS_URL))
                await pool.delete("demo:worker-ready", "demo:dead-letters")
                ready = lambda: redis_key_exists(REDIS_URL, "demo:worker-ready")  # noqa: E731
                with worker_process(
                    [sys.executable, "-m", "arq_demo_tasks"], ready, extra_env={"REDIS_URL": REDIS_URL}
                ):
                    flaky = await pool.enqueue_job("flaky_report", "november")
                    doomed = await pool.enqueue_job("always_fails", "event-7")
                    print(await flaky.result(timeout=15))
                    await doomed.result(timeout=15)
                    print("dead letters:", await pool.lrange("demo:dead-letters", 0, -1))
                await pool.aclose()


            if REDIS_URL:
                await retry_demo()
            else:
                print("SKIP the retry demo: no Docker, so no real Redis")
            '''
        ),
        md(
            """
            **The transactional outbox.** "Commit the order, then publish `order.placed`" has a
            gap: a crash between the two loses the event; publishing first and failing the
            commit announces an order that does not exist. The outbox closes the gap: the event
            is a **row written in the same transaction** as the order, and a separate relay
            publishes rows and marks them published (at least once, so consumers dedupe by
            event id):
            """
        ),
        code(
            r'''
            outbox_db = sqlite3.connect(":memory:", isolation_level=None)
            outbox_db.executescript("""
                CREATE TABLE orders (id INTEGER PRIMARY KEY, item TEXT NOT NULL);
                CREATE TABLE outbox (id INTEGER PRIMARY KEY, event TEXT NOT NULL, published INTEGER DEFAULT 0);
            """)


            def place_order_with_event(item: str, crash_after_insert: bool = False) -> None:
                """Order and event in one transaction: both or neither."""
                outbox_db.execute("BEGIN")
                try:
                    order_id = outbox_db.execute("INSERT INTO orders (item) VALUES (?)", (item,)).lastrowid
                    if crash_after_insert:
                        raise RuntimeError("process killed mid-transaction")
                    outbox_db.execute(
                        "INSERT INTO outbox (event) VALUES (?)",
                        (json.dumps({"type": "order.placed", "order": order_id}),),
                    )
                    outbox_db.execute("COMMIT")
                except RuntimeError:
                    outbox_db.execute("ROLLBACK")


            place_order_with_event("tea")
            place_order_with_event("rice", crash_after_insert=True)
            print("orders:", outbox_db.execute("SELECT item FROM orders").fetchall())
            print("outbox:", outbox_db.execute("SELECT event, published FROM outbox").fetchall())
            relayed = [
                json.loads(row[1])
                for row in outbox_db.execute("SELECT id, event FROM outbox WHERE published = 0")
            ]
            outbox_db.execute("UPDATE outbox SET published = 1 WHERE published = 0")
            print("relay published:", relayed)
            '''
        ),
        md(
            """
            Lab 6.6 exercise 6 builds the relay properly (ordering, partial failures). The Notes
            API's `relay_outbox` also uses `SELECT ... FOR UPDATE SKIP LOCKED` on PostgreSQL so
            two relays never publish the same row concurrently.

            **Scheduled jobs.** ARQ's `cron(task, minute=..., hour=...)` runs a task on a
            schedule inside the worker (the Notes API: `cron(relay_outbox, second={0, 10, ...})`
            and `cron(purge_expired_tokens, hour=3, minute=0)`). `arq.cron.next_cron` computes
            the next run:
            """
        ),
        code(
            r'''
            moment = datetime(2026, 11, 18, 2, 59, 30)  # a fixed "now", so the output is stable
            nightly = next_cron(moment, hour=3, minute=0, second=0, microsecond=0)
            every_ten = [next_cron(moment, second={0, 10, 20, 30, 40, 50}, microsecond=0)]
            every_ten.append(next_cron(every_ten[-1], second={0, 10, 20, 30, 40, 50}, microsecond=0))
            print("purge job next runs at:", nightly)
            print("relay job next runs at:", [str(run.time()) for run in every_ten])


            async def purge_demo(ctx: dict[str, Any]) -> None:
                """A scheduled task (it would delete expired rows)."""


            nightly_job = cron(purge_demo, hour=3, minute=0, second=0)
            print("cron job:", nightly_job.name, "| hour:", nightly_job.hour, "minute:", nightly_job.minute)
            '''
        ),
        md(
            """
            With several worker processes, every one of them runs each cron job, so a job that
            must run **once** needs a **lock**. `SET key token NX EX ttl` acquires it; release
            must delete the key **only if it still holds our token** (the lock may have expired
            and been taken by someone else). `WATCH`/`MULTI` makes the check-and-delete atomic
            (redis-py's `Lock` class does the same with a Lua script):
            """
        ),
        code(
            r'''
            async def acquire_lock(redis_client: Any, name: str, ttl: int) -> str | None:
                """A random token if we got the lock, else None."""
                token = secrets.token_hex(8)
                return token if await redis_client.set(f"lock:{name}", token, nx=True, ex=ttl) else None


            async def release_lock(redis_client: Any, name: str, token: str) -> bool:
                """Delete the lock only if it is still ours (WATCH makes it atomic)."""
                async with redis_client.pipeline(transaction=True) as pipe:
                    await pipe.watch(f"lock:{name}")
                    if await pipe.get(f"lock:{name}") != token:
                        await pipe.unwatch()
                        return False
                    pipe.multi()
                    pipe.delete(f"lock:{name}")
                    await pipe.execute()
                    return True


            async def lock_demo() -> None:
                """Two workers race for the relay lock."""
                redis_client = make_redis(REDIS_URL)
                await redis_client.delete("lock:relay")
                worker_one = await acquire_lock(redis_client, "relay", ttl=30)
                worker_two = await acquire_lock(redis_client, "relay", ttl=30)
                print(f"worker 1 got it: {worker_one is not None}; worker 2 got it: {worker_two is not None}")
                print(
                    "worker 2 releases (not its lock):",
                    await release_lock(redis_client, "relay", "forged-token"),
                )
                print("worker 1 releases:", await release_lock(redis_client, "relay", worker_one))
                await redis_client.aclose()


            await lock_demo()
            '''
        ),
    ]


def _websocket_cells() -> list[NotebookNode]:
    """6.6.4 WebSockets."""
    return [
        md(
            """
            ### 6.6.4 WebSockets

            A WebSocket (RFC 6455) is a full-duplex connection that starts as an HTTP/1.1
            request with `Upgrade: websocket`. The server answers **101 Switching Protocols**
            and from then on both sides send framed messages (text, binary, ping/pong, close)
            over the same TCP connection.

            | Step | Client sends | Server answers |
            | --- | --- | --- |
            | 1 | `GET /ws HTTP/1.1`, `Upgrade: websocket`, `Connection: Upgrade`, `Sec-WebSocket-Key: <random base64>`, `Sec-WebSocket-Version: 13` | — |
            | 2 | — | `101 Switching Protocols`, `Sec-WebSocket-Accept: base64(SHA-1(key + GUID))` |
            | 3 | frames ↔ frames | close frame with a code (1000 normal, 1008 policy violation, 1011 server error) |

            The accept value proves the server understood the WebSocket handshake. With the key
            from RFC 6455 section 1.3:
            """
        ),
        code(
            r'''
            WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


            def websocket_accept(key: str) -> str:
                """The Sec-WebSocket-Accept value for a Sec-WebSocket-Key."""
                return base64.b64encode(hashlib.sha1((key + WEBSOCKET_GUID).encode()).digest()).decode()


            print(
                websocket_accept("dGhlIHNhbXBsZSBub25jZQ=="),
                websocket_accept("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=",
            )
            '''
        ),
        md(
            """
            A demo app for this section and the next, served by Uvicorn later: a WebSocket echo
            route and an SSE route (6.6.5). In FastAPI a WebSocket route is
            `@app.websocket(path)`; the handler `accept()`s, then `receive_*` / `send_*`
            until the client disconnects (`WebSocketDisconnect`):
            """
        ),
        *writefile_cells(
            REALTIME_DEMO_SOURCE,
            [
                ("", "Part 1: the app and the WebSocket echo route:"),
                ('@app.get("/events")', "Part 2: the SSE route (resuming after `Last-Event-ID`):"),
            ],
        ),
        md(
            "The raw handshake against the served app, with a plain socket (no WebSocket library), to see the 101 response:"
        ),
        code(
            r'''
            def raw_websocket_handshake(base_url: str) -> str:
                """Send the upgrade request by hand; return the response head."""
                host, port = base_url.removeprefix("http://").split(":")
                key = base64.b64encode(secrets.token_bytes(16)).decode()
                request = (
                    f"GET /ws/echo HTTP/1.1\r\nHost: {host}:{port}\r\n"
                    f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                    f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
                )
                with socket.create_connection((host, int(port)), timeout=5) as connection:
                    connection.sendall(request.encode())
                    head = connection.recv(4096).decode("latin-1").split("\r\n\r\n")[0]
                accepted = websocket_accept(key) in head
                return (
                    re.sub(r"(?i)(sec-websocket-accept: )\S+", r"\1<derived from our key>", head)
                    + f"\naccept matches: {accepted}"
                )


            with uvicorn_server("realtime_demo:app") as base_url:
                print(mask_dates(raw_websocket_handshake(base_url)))
            '''
        ),
        md(
            """
            In tests (and here) `TestClient.websocket_connect()` talks to the app in-process.
            A **connection manager** keeps the open sockets per room so a message can be
            broadcast; it is the core of a chat or a live dashboard:
            """
        ),
        code(
            r'''
            class RoomManager:
                """Open sockets grouped by room."""

                def __init__(self) -> None:
                    """No rooms yet."""
                    self.rooms: dict[str, set[WebSocket]] = defaultdict(set)

                async def join(self, room: str, websocket: WebSocket) -> None:
                    """Accept and remember a socket."""
                    await websocket.accept()
                    self.rooms[room].add(websocket)

                def leave(self, room: str, websocket: WebSocket) -> None:
                    """Forget a socket."""
                    self.rooms[room].discard(websocket)

                async def broadcast(self, room: str, message: dict[str, object]) -> None:
                    """Send to every socket in the room."""
                    for websocket in list(self.rooms[room]):
                        await websocket.send_json(message)


            chat_app = FastAPI()
            chat_rooms = RoomManager()


            @chat_app.websocket("/ws/rooms/{room}")
            async def chat(websocket: WebSocket, room: str, name: str) -> None:
                """Broadcast every message to the room."""
                await chat_rooms.join(room, websocket)
                try:
                    while True:
                        await chat_rooms.broadcast(room, {"from": name, "text": await websocket.receive_text()})
                except WebSocketDisconnect:
                    chat_rooms.leave(room, websocket)
            '''
        ),
        md("Two clients in one room:"),
        code(
            r"""
            with TestClient(chat_app) as client:
                with (
                    client.websocket_connect("/ws/rooms/tea?name=asha") as asha,
                    client.websocket_connect("/ws/rooms/tea?name=ravi") as ravi,
                ):
                    asha.send_text("kettle is on")
                    print("ravi got:", ravi.receive_json())
                    print("asha got:", asha.receive_json())
            print("sockets left in the room:", len(chat_rooms.rooms["tea"]))
            """
        ),
        md(
            """
            **Authentication.** Browsers cannot set an `Authorization` header on a WebSocket.
            Options: a cookie (sent with the upgrade request; then check the `Origin` header
            against CSRF-style attacks), a token in the query string (it ends up in access
            logs), or, as in the Notes API, the **first message carries the token** and the
            server closes with code **1008** if it is missing or invalid:
            """
        ),
        code(
            r'''
            WS_SECRET = secrets.token_urlsafe(32)
            auth_ws_app = FastAPI()


            @auth_ws_app.websocket("/ws")
            async def authenticated_feed(websocket: WebSocket) -> None:
                """First message must be {"token": ...}; otherwise close with 1008."""
                await websocket.accept()
                try:
                    first = await asyncio.wait_for(websocket.receive_json(), timeout=5)
                    claims = jwt.decode(first.get("token", ""), WS_SECRET, algorithms=["HS256"])
                except TimeoutError, jwt.InvalidTokenError, ValueError, AttributeError:
                    await websocket.close(
                        code=status.WS_1008_POLICY_VIOLATION, reason="authentication required"
                    )
                    return
                await websocket.send_json({"ready": True, "user": claims["sub"]})


            with TestClient(auth_ws_app) as client:
                with client.websocket_connect("/ws") as websocket:
                    websocket.send_json({"token": jwt.encode({"sub": "asha"}, WS_SECRET, algorithm="HS256")})
                    print("valid token :", websocket.receive_json())
                with client.websocket_connect("/ws") as websocket:
                    websocket.send_json({"token": "forged"})
                    try:
                        websocket.receive_json()
                    except WebSocketDisconnect as closed:
                        print("forged token: closed with", closed.code, closed.reason)
            '''
        ),
        md(
            """
            **Heartbeats.** A connection can die silently (a laptop sleeps, a proxy drops idle
            connections after 60 s). Sending a small message periodically keeps proxies happy
            and detects dead peers. Uvicorn already sends protocol-level pings
            (`--ws-ping-interval`); an application-level `{"type": "ping"}` also reaches
            browser code, which cannot see protocol pings. Here the interval is 0.1 s:
            """
        ),
        code(
            r'''
            heartbeat_app = FastAPI()


            @heartbeat_app.websocket("/ws")
            async def heartbeat_feed(websocket: WebSocket) -> None:
                """Ping when the client has been quiet for 0.1 s; answer pings with pongs."""
                await websocket.accept()
                try:
                    while True:
                        try:
                            message = await asyncio.wait_for(websocket.receive_json(), timeout=0.1)
                        except TimeoutError:
                            await websocket.send_json({"type": "ping", "at": round(time.time(), 1)})
                            continue
                        if message.get("type") == "ping":
                            await websocket.send_json({"type": "pong"})
                except WebSocketDisconnect:
                    pass


            with TestClient(heartbeat_app) as client, client.websocket_connect("/ws") as websocket:
                print([websocket.receive_json()["type"] for _ in range(2)])
                websocket.send_json({"type": "ping"})
                print(websocket.receive_json())
            '''
        ),
        md(
            """
            **Fan-out through Redis.** With several API processes, a client's socket lives in
            one process while the event may happen in another. Each process subscribes to Redis
            pub/sub and forwards what arrives to its own sockets. Two app instances (two
            "processes") share one Redis; a message posted to instance B reaches a socket on
            instance A:
            """
        ),
        code(
            r'''
            SHARED_FAKE_SERVER = fakeredis.FakeServer()  # used only without Docker


            @contextlib.asynccontextmanager
            async def redis_lifespan(app: FastAPI) -> AsyncIterator[None]:
                """One Redis client per process (the real Redis, or a fake shared by both apps)."""
                app.state.redis = (
                    make_redis(REDIS_URL)
                    if REDIS_URL
                    else fakeredis.FakeAsyncRedis(server=SHARED_FAKE_SERVER, decode_responses=True)
                )
                yield
                await app.state.redis.aclose()
            '''
        ),
        md(
            "`build_fanout_app()`: an API instance: WebSocket subscribers and an HTTP publisher, joined by Redis:"
        ),
        code(
            r'''
            def build_fanout_app(name: str) -> FastAPI:
                """An API instance: WebSocket subscribers and an HTTP publisher, joined by Redis."""
                fanout_app = FastAPI(lifespan=redis_lifespan)

                @fanout_app.post("/rooms/{room}/messages")
                async def publish(room: str, body: dict[str, str]) -> dict[str, int]:
                    """Publish to every process; returns how many subscribers got it."""
                    return {
                        "receivers": await fanout_app.state.redis.publish(
                            f"room:{room}", json.dumps(body | {"via": name})
                        )
                    }

                @fanout_app.websocket("/ws/{room}")
                async def subscribe(websocket: WebSocket, room: str) -> None:
                    """Forward the room's Redis messages to this socket until it closes."""
                    await websocket.accept()
                    pubsub = fanout_app.state.redis.pubsub()
                    await pubsub.subscribe(f"room:{room}")
                    await websocket.send_json({"ready": name})
                    forwarder = asyncio.create_task(forward_messages(pubsub, websocket))
                    try:
                        while True:
                            await websocket.receive_text()
                    except WebSocketDisconnect:
                        pass
                    finally:
                        forwarder.cancel()
                        await pubsub.aclose()

                return fanout_app
            '''
        ),
        md("`forward_messages` copies pub/sub messages to the socket:"),
        code(
            r'''
            async def forward_messages(pubsub: Any, websocket: WebSocket) -> None:
                """Copy every pub/sub message to the socket."""
                while True:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if message is not None:
                        await websocket.send_text(message["data"])


            instance_a, instance_b = build_fanout_app("A"), build_fanout_app("B")
            with TestClient(instance_a) as client_a, TestClient(instance_b) as client_b:
                with client_a.websocket_connect("/ws/tea") as websocket:
                    print("subscribed on:", websocket.receive_json())
                    print(
                        "published on B:",
                        client_b.post("/rooms/tea/messages", json={"text": "kettle is on"}).json(),
                    )
                    print("socket on A got:", websocket.receive_json())
            '''
        ),
        md(
            """
            The JS side: Node 24 has the browser `WebSocket` class built in, so the same client
            code a browser would run talks to the Uvicorn-served echo route:
            """
        ),
        code(
            r'''
            NODE_WS_CLIENT = """
            const socket = new WebSocket(process.argv[1]);
            socket.addEventListener("open", () => socket.send("hello from Node"));
            socket.addEventListener("message", (event) => { console.log(event.data); socket.close(); });
            """

            if HAS_NODE:
                with uvicorn_server("realtime_demo:app") as base_url:
                    ws_url = base_url.replace("http://", "ws://") + "/ws/echo"
                    node_run = subprocess.run(
                        ["node", "-e", textwrap.dedent(NODE_WS_CLIENT), ws_url],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    print(node_run.stdout.strip() or node_run.stderr.strip()[-300:])
            else:
                print("SKIP the Node WebSocket client: node is not installed")
            '''
        ),
    ]


ARQ_DEMO_TASKS_SOURCE = r'''
%%writefile _scratch/phase6/arq_demo_tasks.py
# ARQ demo worker: run with `python -m arq_demo_tasks` (REDIS_URL in the environment).
import asyncio
import os
from typing import Any, ClassVar

from arq import Retry
from arq.connections import RedisSettings
from arq.worker import Worker


async def send_welcome(ctx: dict[str, Any], email: str) -> str:
    """Pretend to send an e-mail; return a receipt."""
    await asyncio.sleep(0.05)  # pretend to call an e-mail API
    return f"welcome e-mail to {email} (job {ctx['job_id'][:8]}, try {ctx['job_try']})"


async def flaky_report(ctx: dict[str, Any], name: str) -> str:
    """Fail twice with backoff, then succeed."""
    if ctx["job_try"] < 3:  # fail twice, then succeed
        raise Retry(defer=0.2 * 2 ** ctx["job_try"])  # exponential backoff
    return f"report {name} built on try {ctx['job_try']}"


async def always_fails(ctx: dict[str, Any], payload: str) -> None:
    """Never succeeds: dead-letter the payload on the third try."""
    if ctx["job_try"] >= 3:  # the last allowed try: park it in a dead-letter list
        await ctx["redis"].rpush("demo:dead-letters", f"{payload} (tries: {ctx['job_try']})")
        return
    raise Retry(defer=0.1)


async def startup(ctx: dict[str, Any]) -> None:
    """Tell the notebook the worker is ready."""
    await ctx["redis"].set("demo:worker-ready", "1", ex=60)


class WorkerSettings:
    """What `arq arq_demo_tasks.WorkerSettings` would read."""

    functions: ClassVar = [send_welcome, flaky_report, always_fails]
    on_startup = startup
    max_tries = 5
    poll_delay = 0.05


async def main() -> None:
    """Create the worker inside a running loop (works on Python 3.14+) and run it."""
    worker = Worker(
        functions=WorkerSettings.functions,
        on_startup=WorkerSettings.on_startup,
        max_tries=WorkerSettings.max_tries,
        poll_delay=WorkerSettings.poll_delay,
        redis_settings=RedisSettings.from_dsn(os.environ["REDIS_URL"]),
    )
    await worker.async_run()


if __name__ == "__main__":
    asyncio.run(main())
'''


REALTIME_DEMO_SOURCE = r'''
%%writefile _scratch/phase6/realtime_demo.py
# WebSocket echo and an SSE counter, for the Node clients in 6.6.4 and 6.6.5.
import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import FastAPI, Header, WebSocket
from fastapi.responses import StreamingResponse
from fastapi.websockets import WebSocketDisconnect

app = FastAPI()


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe for the server helper."""
    return {"status": "ok"}


@app.websocket("/ws/echo")
async def echo(websocket: WebSocket) -> None:
    """Echo every text message until the client leaves."""
    await websocket.accept()
    try:
        while True:
            text = await websocket.receive_text()
            await websocket.send_text(f"echo: {text}")
    except WebSocketDisconnect:
        pass


@app.get("/events")
async def events(last_event_id: str | None = Header(default=None)) -> StreamingResponse:
    """Three numbered events, continuing after Last-Event-ID."""
    start = int(last_event_id or 0) + 1

    async def stream() -> AsyncIterator[str]:
        """The event stream: a retry hint, then the events."""
        yield "retry: 500\n\n"
        for number in range(start, start + 3):
            await asyncio.sleep(0.05)
            yield f"id: {number}\nevent: tick\ndata: {json.dumps({'n': number})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
'''


def _sse_cells() -> list[NotebookNode]:
    """6.6.5 Server-Sent Events."""
    return [
        md(
            """
            ### 6.6.5 Server-Sent Events

            SSE is a one-way stream from server to client over a normal HTTP response with
            `Content-Type: text/event-stream`. The body is UTF-8 text: each event is a few
            `field: value` lines followed by a **blank line**:

            | Field | Meaning |
            | --- | --- |
            | `data:` | the payload (several `data:` lines are joined with `\\n`) |
            | `event:` | an event name (the browser dispatches it to `addEventListener(name)`; default `message`) |
            | `id:` | the event id; the browser remembers it and sends `Last-Event-ID` when it reconnects |
            | `retry:` | reconnection delay in milliseconds |
            | `: text` | a comment (often sent as a keep-alive) |

            `format_sse()` (from the setup cell) produces exactly that:
            """
        ),
        code(
            r"""
            print(repr(format_sse({"done": 3, "total": 10}, event_name="progress", event_id=3)))
            print(format_sse("plain text", event_id="2026-11-18-0001"), end="")
            print(repr(": keep-alive\n\n"))
            """
        ),
        md(
            """
            In FastAPI, a `StreamingResponse` over an async generator sends each yielded string
            as soon as it is produced. Resuming is the server's job: read `Last-Event-ID` and
            continue after it. Send `Cache-Control: no-cache` (and `X-Accel-Buffering: no` for
            nginx) so nothing buffers the stream:
            """
        ),
        code(
            r'''
            sse_app = FastAPI()
            JOB_STEPS = ["queued", "reading notes", "writing JSON", "compressing", "done"]


            @sse_app.get("/jobs/{job_id}/events")
            async def job_events(
                job_id: str, last_event_id: Annotated[str | None, Header()] = None
            ) -> StreamingResponse:
                """Progress events for a job, resuming after Last-Event-ID."""
                start = int(last_event_id) + 1 if last_event_id else 0

                async def stream() -> AsyncIterator[str]:
                    """One event per step."""
                    yield "retry: 1000\n\n"
                    for index in range(start, len(JOB_STEPS)):
                        await asyncio.sleep(0.01)
                        name = "done" if JOB_STEPS[index] == "done" else "progress"
                        yield format_sse(
                            {"job": job_id, "step": JOB_STEPS[index]}, event_name=name, event_id=index
                        )

                headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
                return StreamingResponse(stream(), media_type="text/event-stream", headers=headers)


            def read_events(
                client: TestClient, path: str, last_event_id: str | None = None
            ) -> list[tuple[str, str]]:
                """(id, data) of every event in a finite stream."""
                headers = {"Last-Event-ID": last_event_id} if last_event_id else {}
                events, current_id = [], None
                with client.stream("GET", path, headers=headers) as response:
                    for line in response.iter_lines():
                        if line.startswith("id: "):
                            current_id = line[4:]
                        elif line.startswith("data: "):
                            events.append((current_id, json.loads(line[6:])["step"]))
                return events
            '''
        ),
        md("Read the whole stream, then reconnect as a browser would after event 2:"),
        code(
            r"""
            with TestClient(sse_app) as client:
                print("first connection:", read_events(client, "/jobs/42/events"))
                print("resume after 2  :", read_events(client, "/jobs/42/events", last_event_id="2"))
                print("content type    :", client.get("/jobs/42/events").headers["content-type"])
            """
        ),
        md(
            """
            **`EventSource`** is the browser API: `new EventSource(url)` opens the stream,
            dispatches `message` / named events, and **reconnects automatically** with
            `Last-Event-ID`. Node 24 ships it behind `--experimental-eventsource`; here it reads
            three events from the Uvicorn-served demo app:
            """
        ),
        code(
            r'''
            NODE_SSE_CLIENT = """
            const source = new EventSource(process.argv[1]);
            let count = 0;
            source.addEventListener("tick", (event) => {
              console.log(`tick id=${event.lastEventId} data=${event.data}`);
              if (++count === 3) source.close();
            });
            """

            if HAS_NODE:
                with uvicorn_server("realtime_demo:app") as base_url:
                    node_run = subprocess.run(
                        [
                            "node",
                            "--experimental-eventsource",
                            "--no-warnings",
                            "-e",
                            textwrap.dedent(NODE_SSE_CLIENT),
                            base_url + "/events",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    print(node_run.stdout.strip() or node_run.stderr.strip()[-300:])
            else:
                print("SKIP the Node EventSource client: node is not installed")
            '''
        ),
        md(
            """
            **SSE vs WebSockets vs polling**

            | | Polling (`GET` every n s) | Long polling | **SSE** | **WebSockets** |
            | --- | --- | --- | --- | --- |
            | Direction | client asks | client asks, server answers when ready | server → client | both ways |
            | Protocol | plain HTTP | plain HTTP | plain HTTP (works with HTTP/2 multiplexing, proxies, auth headers via fetch) | upgrade to a new protocol |
            | Reconnect / resume | n/a | manual | **built in** (`Last-Event-ID`) | manual |
            | Data | any | any | UTF-8 text | text or binary |
            | Latency / cost | up to n s, many empty requests | low, one request per event | low, one connection | lowest, one connection |
            | Good for | rare changes, simple clients | legacy fallback | progress bars, notifications, feeds, **LLM token streams** | chat, collaboration, games |

            **LLM token streaming** is the most common SSE use today: the model produces tokens
            one by one, and users see the answer grow instead of waiting for all of it. A fake
            "model" that yields tokens with small delays, streamed as SSE and assembled by the
            client; the time to the first token is what users feel:
            """
        ),
        code(
            r'''
            async def fake_model(prompt: str) -> AsyncIterator[str]:
                """Yield an answer token by token, like a language model API."""
                for token in f"Here is a short answer about {prompt}: tea is steeped, not boiled.".split(" "):
                    await asyncio.sleep(0.02)
                    yield token + " "


            llm_app = FastAPI()


            @llm_app.get("/chat")
            async def chat_stream(prompt: str) -> StreamingResponse:
                """Stream the model's tokens as SSE, then a done event."""

                async def stream() -> AsyncIterator[str]:
                    """Token events, then one final event."""
                    async for token in fake_model(prompt):
                        yield format_sse({"token": token})
                    yield format_sse({"finish_reason": "stop"}, event_name="done")

                return StreamingResponse(stream(), media_type="text/event-stream")


            async def consume_tokens(base_url: str) -> None:
                """Assemble the answer; measure time to first token vs total."""
                async with httpx.AsyncClient(base_url=base_url, trust_env=False) as client:
                    started, first_token_at, answer = time.perf_counter(), None, []
                    async with client.stream("GET", "/chat", params={"prompt": "tea"}) as response:
                        async for line in response.aiter_lines():
                            if line.startswith("data: ") and "token" in line:
                                first_token_at = first_token_at or time.perf_counter() - started
                                answer.append(json.loads(line[6:])["token"])
                    total = time.perf_counter() - started
                print("".join(answer).strip())
                print(
                    f"first token after {first_token_at * 1000:.0f} ms, full answer after {total * 1000:.0f} ms"
                )


            '''
        ),
        md(
            """
            Streaming must be tested through a real server: `httpx.ASGITransport` and
            `TestClient` collect the whole body before returning it, so every token would seem
            to arrive at the end. `serve_in_kernel()` runs Uvicorn **inside the notebook's event
            loop** for an app defined in the notebook, and always shuts it down:
            """
        ),
        code(
            r'''
            @contextlib.asynccontextmanager
            async def serve_in_kernel(app: FastAPI) -> AsyncIterator[str]:
                """Serve app with Uvicorn as a task in this event loop; yield its URL; always stop it."""
                port = free_port()
                server = uvicorn.Server(
                    uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off")
                )
                serving = asyncio.create_task(server.serve())
                try:
                    while not server.started:
                        if serving.done():
                            serving.result()  # re-raise a startup error
                        await asyncio.sleep(0.01)
                    yield f"http://127.0.0.1:{port}"
                finally:
                    server.should_exit = True
                    await serving


            async with serve_in_kernel(llm_app) as llm_url:
                await consume_tokens(llm_url)
            '''
        ),
    ]


def _http_cache_cells() -> list[NotebookNode]:
    """6.6.6 HTTP caching."""
    return [
        md(
            """
            ### 6.6.6 HTTP caching

            Browsers, CDNs and proxies cache responses according to the `Cache-Control` header:

            | Directive | Meaning |
            | --- | --- |
            | `max-age=N` | fresh for N seconds: reuse without asking |
            | `s-maxage=N` | the same, for shared caches (CDNs) only |
            | `no-cache` | may store, but must **revalidate** with the server before each use |
            | `no-store` | never store (sensitive or ever-changing data) |
            | `private` / `public` | only the user's browser may store it / shared caches may too |
            | `must-revalidate` | once stale, never serve without revalidating |
            | `immutable` | will never change (fingerprinted assets: `app.3f9a.js`) |
            | `stale-while-revalidate=N` | serve stale for N s while refreshing in the background |
            | `Vary: Authorization` | keep separate copies per value of that request header |

            **Validators** make revalidation cheap. The server sends `ETag: "<version>"` (or
            `Last-Modified`); the client later sends `If-None-Match: "<version>"` (or
            `If-Modified-Since`); if nothing changed the server answers **304 Not Modified**
            with no body. Strong ETags (`"abc"`) mean byte-identical; weak ones (`W/"abc"`)
            mean semantically equivalent. An endpoint with both validators:
            """
        ),
        code(
            r'''
            ARTICLES = {
                1: {
                    "title": "Steeping tea",
                    "body": "Three minutes.",
                    "updated": datetime(2026, 11, 18, 9, 0, tzinfo=UTC),
                }
            }
            cache_app = FastAPI()


            def article_etag(article: dict[str, object]) -> str:
                """A strong validator: a hash of the representation."""
                digest = hashlib.sha256(json.dumps(article, default=str, sort_keys=True).encode()).hexdigest()
                return f'"{digest[:16]}"'
            '''
        ),
        md("`read_article()`: 200 with validators, or 304 when the client's copy is current:"),
        code(
            r'''
            @cache_app.get("/articles/{article_id}")
            def read_article(
                article_id: int,
                if_none_match: Annotated[str | None, Header()] = None,
                if_modified_since: Annotated[str | None, Header()] = None,
            ) -> Response:
                """200 with validators, or 304 when the client's copy is current."""
                article = ARTICLES[article_id]
                headers = {
                    "ETag": article_etag(article),
                    "Last-Modified": email.utils.format_datetime(article["updated"], usegmt=True),
                    "Cache-Control": "public, max-age=60, must-revalidate",
                }
                etags = {
                    tag.strip().removeprefix("W/") for tag in (if_none_match or "").split(",") if tag.strip()
                }
                if headers["ETag"] in etags or "*" in etags:
                    return Response(status_code=304, headers=headers)
                if (
                    if_none_match is None
                    and if_modified_since
                    and email.utils.parsedate_to_datetime(if_modified_since) >= article["updated"]
                ):
                    return Response(status_code=304, headers=headers)
                return Response(
                    json.dumps(article, default=str), media_type="application/json", headers=headers
                )
            '''
        ),
        md("A first request, two kinds of revalidation, then a change:"),
        code(
            r"""
            with TestClient(cache_app) as client:
                first = client.get("/articles/1")
                show_response(first, "etag", "last-modified", "cache-control")
                etag, modified = first.headers["etag"], first.headers["last-modified"]
                print(
                    "If-None-Match      :",
                    client.get("/articles/1", headers={"If-None-Match": etag}).status_code,
                )
                print(
                    "weak If-None-Match :",
                    client.get("/articles/1", headers={"If-None-Match": f"W/{etag}"}).status_code,
                )
                print(
                    "If-Modified-Since  :",
                    client.get("/articles/1", headers={"If-Modified-Since": modified}).status_code,
                )
                ARTICLES[1] |= {"body": "Four minutes.", "updated": datetime(2026, 11, 18, 10, 0, tzinfo=UTC)}
                changed = client.get("/articles/1", headers={"If-None-Match": etag})
                print(
                    "after an update    :",
                    changed.status_code,
                    len(changed.content),
                    "bytes, new ETag:",
                    changed.headers["etag"] != etag,
                )
            """
        ),
        md(
            """
            What a browser does with these headers, as a tiny client-side cache: within
            `max-age` it does not even send a request; afterwards it revalidates with
            `If-None-Match` and reuses its copy on 304:
            """
        ),
        code(
            r'''
            class BrowserCache:
                """A minimal private cache honouring max-age and ETag revalidation."""

                def __init__(self, client: TestClient, clock: Callable[[], float]) -> None:
                    """Wrap a client; time comes from clock."""
                    self.client, self.clock = client, clock
                    self.entries: dict[str, tuple[float, str, bytes]] = {}  # url -> (expires, etag, body)

                def get(self, url: str) -> str:
                    """Return how the response was obtained."""
                    entry = self.entries.get(url)
                    if entry and self.clock() < entry[0]:
                        return "fresh: served from cache, no request"
                    headers = {"If-None-Match": entry[1]} if entry else {}
                    response = self.client.get(url, headers=headers)
                    max_age = int(
                        re.search(r"max-age=(\d+)", response.headers.get("cache-control", "max-age=0"))[1]
                    )
                    body = entry[2] if response.status_code == 304 else response.content
                    self.entries[url] = (self.clock() + max_age, response.headers["etag"], body)
                    outcome = "revalidated, reused copy" if response.status_code == 304 else "downloaded"
                    return f"{response.status_code}: {outcome}"


            fake_now = [0.0]
            with TestClient(cache_app) as client:
                browser = BrowserCache(client, lambda: fake_now[0])
                for moment in (0, 30, 61, 90):
                    fake_now[0] = moment
                    print(f"t={moment:3}s  {browser.get('/articles/1')}")
            '''
        ),
        md(
            """
            Personal API data (like a user's notes) should be `private` (never in a CDN), and
            `no-cache` with an ETag gives correctness plus cheap 304s: that is what the Notes
            API v5 sends for `GET /notes/{id}`; lists change too often and get `no-store`.
            """
        ),
    ]


def _redis_cache_cells() -> list[NotebookNode]:
    """6.6.7 Application caching with Redis."""
    return [
        md(
            """
            ### 6.6.7 Application caching with Redis

            | Pattern | Read | Write | Notes |
            | --- | --- | --- | --- |
            | **Cache-aside** (lazy) | app checks the cache; on a miss loads from the DB and stores | app writes the DB, then deletes the key | the default; only requested data is cached (Notes API v5) |
            | Read-through | the cache library loads on a miss | — | same idea, inside a library |
            | Write-through | — | write cache and DB together | cache always warm; slower writes |
            | Write-behind | — | write the cache, flush to the DB later | fast writes; risk of loss |

            **Key design**: `<app>:<version>:<entity>:<id>[:<variant>]`, e.g.
            `notes:v5:note:42`. A version segment lets you invalidate a whole family by bumping
            it; never put secrets or unbounded user input in keys. **TTLs** bound staleness
            and memory; add **jitter** so keys written together do not expire together.

            Cache-aside on the real Redis (fakeredis without Docker), with a slow "database"
            and hit/miss counters:
            """
        ),
        code(
            r'''
            DATABASE_ROWS = {note_id: {"id": note_id, "title": f"Note {note_id}"} for note_id in range(1, 21)}
            DATABASE_CALLS: list[int] = []


            async def load_note(note_id: int) -> dict[str, object] | None:
                """The slow source of truth (20 ms per query)."""
                await asyncio.sleep(0.02)
                DATABASE_CALLS.append(note_id)
                return DATABASE_ROWS.get(note_id)


            def note_cache_key(note_id: int, version: str = "v1") -> str:
                """Namespaced, versioned key."""
                return f"demo:{version}:note:{note_id}"


            async def cached_note(redis_client: Any, note_id: int, ttl: int = 60) -> dict[str, object] | None:
                """Cache-aside read with hit/miss counters and TTL jitter."""
                cached = await redis_client.get(note_cache_key(note_id))
                if cached is not None:
                    await redis_client.hincrby("demo:cache-stats", "hits", 1)
                    return json.loads(cached)
                await redis_client.hincrby("demo:cache-stats", "misses", 1)
                note = await load_note(note_id)
                jittered_ttl = int(ttl * random.uniform(0.9, 1.1))
                await redis_client.set(note_cache_key(note_id), json.dumps(note), ex=jittered_ttl)
                return note
            '''
        ),
        md(
            "Time a miss and a hit, then replay a skewed workload (most reads hit a few hot notes) and compute the hit rate:"
        ),
        code(
            r'''
            async def cache_aside_demo() -> None:
                """Miss vs hit latency, then a measured hit rate."""
                redis_client = make_redis(REDIS_URL)
                await redis_client.delete(*[key async for key in redis_client.scan_iter("demo:*")] or ["none"])
                DATABASE_CALLS.clear()
                for label in ("miss", "hit "):
                    started = time.perf_counter()
                    await cached_note(redis_client, 7)
                    print(f"{label}: {(time.perf_counter() - started) * 1000:6.2f} ms")
                rng = random.Random(42)
                workload = [
                    rng.choice([1, 2, 3]) if rng.random() < 0.8 else rng.randint(4, 20) for _ in range(200)
                ]
                for note_id in workload:
                    await cached_note(redis_client, note_id)
                stats = {
                    key: int(value) for key, value in (await redis_client.hgetall("demo:cache-stats")).items()
                }
                print(
                    stats,
                    f"hit rate {stats['hits'] / (stats['hits'] + stats['misses']):.0%}"
                    f", database queries: {len(DATABASE_CALLS)}",
                )
                print("TTL of one key (60 s ± 10 %):", await redis_client.ttl(note_cache_key(7)))
                await redis_client.aclose()


            await cache_aside_demo()
            '''
        ),
        md(
            """
            **Invalidation.** After a write, delete the key (the next read reloads). Forgetting
            it serves stale data until the TTL expires. Bumping the version segment invalidates
            *everything* at once (old keys are simply never read again and expire):
            """
        ),
        code(
            r'''
            async def invalidation_demo() -> None:
                """Stale read without invalidation; fresh read with it; namespace bump."""
                redis_client = make_redis(REDIS_URL)
                await cached_note(redis_client, 5)  # warm the cache
                DATABASE_ROWS[5]["title"] = "Renamed note"
                print("without invalidation:", (await cached_note(redis_client, 5))["title"])
                await redis_client.delete(note_cache_key(5))  # what the write path must do
                print("after DEL           :", (await cached_note(redis_client, 5))["title"])
                print("v2 namespace hit?   :", await redis_client.exists(note_cache_key(5, "v2")) == 1)
                await redis_client.aclose()


            await invalidation_demo()
            '''
        ),
        md(
            """
            **Stampede protection.** When a hot key expires, every concurrent request misses at
            once and hammers the database (a *thundering herd*). With a short per-key lock,
            only the first request loads; the others wait briefly and read what it stored.
            Twenty concurrent requests for a cold key, without and with the lock (the client's
            connection pool is opened first: otherwise setting up twenty TCP connections takes
            longer than the 20 ms query, and the requests would not really overlap):
            """
        ),
        code(
            r'''
            async def guarded_note(redis_client: Any, note_id: int) -> dict[str, object] | None:
                """Cache-aside where only one caller per key loads; the rest poll the cache."""
                key = note_cache_key(note_id)
                for _ in range(50):
                    cached = await redis_client.get(key)
                    if cached is not None:
                        return json.loads(cached)
                    if await redis_client.set(f"{key}:lock", "1", nx=True, ex=5):
                        note = await load_note(note_id)
                        await redis_client.set(key, json.dumps(note), ex=60)
                        await redis_client.delete(f"{key}:lock")
                        return note
                    await asyncio.sleep(0.01)  # someone else is loading
                return await load_note(note_id)  # give up waiting: load ourselves


            async def stampede_demo() -> None:
                """Count database queries for 20 simultaneous cold reads."""
                redis_client = make_redis(REDIS_URL)
                await asyncio.gather(
                    *(redis_client.ping() for _ in range(20))
                )  # open 20 pooled connections first
                for reader, label in ((cached_note, "no lock  "), (guarded_note, "with lock")):
                    await redis_client.delete(note_cache_key(9))
                    DATABASE_CALLS.clear()
                    await asyncio.gather(*(reader(redis_client, 9) for _ in range(20)))
                    print(f"{label}: {len(DATABASE_CALLS)} database queries for 20 requests")
                await redis_client.aclose()


            await stampede_demo()
            '''
        ),
        md(
            """
            Other defences: TTL jitter (above), refreshing hot keys **before** they expire
            ("probabilistic early expiration"), and serving a stale copy while one request
            refreshes. The Notes API's `NoteCache.get_or_load` uses the lock + jitter
            combination, and Lab 6.6 exercise 4 measures a hit rate like the one above.
            """
        ),
    ]


def _messaging_cells() -> list[NotebookNode]:
    """6.6.8 Messaging."""
    return [
        md(
            """
            ### 6.6.8 Messaging

            | | Redis **pub/sub** | Redis **Streams** |
            | --- | --- | --- |
            | Storage | none: a message goes to whoever is subscribed **right now** | an append-only log with ids (`1731916800000-0`) |
            | Delivery | at most once; offline subscribers miss it | replay from any id; consumer groups track progress |
            | Consumers | every subscriber gets every message (fan-out) | groups share the work; each entry to one consumer, acknowledged with `XACK` |
            | Failure handling | none | pending entries list (`XPENDING`), claim stuck entries (`XAUTOCLAIM`) |
            | Notes API v5 | live WebSocket fan-out (a missed event is fine: the client refetches) | export progress (SSE clients resume with `Last-Event-ID`) |

            Pub/sub forgets: a message published before the subscription is lost:
            """
        ),
        code(
            r'''
            async def pubsub_demo() -> None:
                """Publish before and after subscribing."""
                redis_client = make_redis(REDIS_URL)
                print(
                    "receivers before subscribing:",
                    await redis_client.publish("demo:news", "nobody hears this"),
                )
                pubsub = redis_client.pubsub()
                await pubsub.subscribe("demo:news")
                await pubsub.get_message(timeout=1.0)  # the subscribe confirmation
                print("receivers after subscribing :", await redis_client.publish("demo:news", "kettle is on"))
                message = None
                while message is None:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                print("received:", message["data"])
                await pubsub.aclose()
                await redis_client.aclose()


            await pubsub_demo()
            '''
        ),
        md(
            """
            Streams remember. `XADD` appends, `XRANGE`/`XREAD` read from an id, and a consumer
            group hands each entry to one consumer, which acknowledges it; an entry read but
            never acknowledged (the consumer crashed) stays **pending** and can be claimed by
            another consumer:
            """
        ),
        code(
            r'''
            async def streams_demo() -> None:
                """Append, read, consume in a group, crash, claim."""
                redis_client = make_redis(REDIS_URL)
                await redis_client.delete("demo:orders")
                for item in ("tea", "rice", "milk"):
                    await redis_client.xadd("demo:orders", {"item": item})
                entries = await redis_client.xrange("demo:orders")
                print("XRANGE:", [fields["item"] for _, fields in entries])
                print(
                    "XREAD after the first id:",
                    [
                        fields["item"]
                        for _, fields in (await redis_client.xread({"demo:orders": entries[0][0]}))[0][1]
                    ],
                )
                await redis_client.xgroup_create("demo:orders", "billing", id="0")
                batch = await redis_client.xreadgroup("billing", "worker-1", {"demo:orders": ">"}, count=2)
                first_id = batch[0][1][0][0]
                await redis_client.xack(
                    "demo:orders", "billing", first_id
                )  # worker-1 crashes before acking the second
                print(
                    "pending after a crash:", (await redis_client.xpending("demo:orders", "billing"))["pending"]
                )
                claimed = await redis_client.xautoclaim("demo:orders", "billing", "worker-2", min_idle_time=0)
                print("worker-2 claimed:", [fields["item"] for _, fields in claimed[1]])
                await redis_client.aclose()


            await streams_demo()
            '''
        ),
        md(
            """
            **Outgoing signed webhooks.** A webhook is an HTTP `POST` your system sends to a
            URL a customer registered when something happens. The receiver must be able to
            check that the request really came from you and is not a replay. The usual scheme
            (Stripe, GitHub, the Notes API): HMAC-SHA256 over `timestamp.body` with a secret
            shared at registration, sent as `X-Notes-Signature: t=<unix time>,v1=<hex>`; the
            receiver recomputes it with `hmac.compare_digest` and rejects old timestamps:
            """
        ),
        code(
            r'''
            def sign_payload(secret: str, body: bytes, timestamp: int) -> str:
                """The signature header value."""
                digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
                return f"t={timestamp},v1={digest}"


            def verify_payload(secret: str, body: bytes, header: str, now: float, tolerance: int = 300) -> bool:
                """Receiver side: right signature and a recent timestamp."""
                parts = dict(item.split("=", 1) for item in header.split(","))
                timestamp = int(parts.get("t", "0"))
                expected = sign_payload(secret, body, timestamp).split("v1=")[1]
                return abs(now - timestamp) <= tolerance and hmac.compare_digest(expected, parts.get("v1", ""))


            webhook_secret = "whsec_" + secrets.token_hex(16)
            event_body = json.dumps({"id": "evt_1", "type": "note.created", "note_id": 42}).encode()
            signed_at = int(time.time())
            signature = sign_payload(webhook_secret, event_body, signed_at)
            print("valid   :", verify_payload(webhook_secret, event_body, signature, now=time.time()))
            print(
                "tampered:",
                verify_payload(webhook_secret, event_body.replace(b"42", b"43"), signature, now=time.time()),
            )
            print("replayed:", verify_payload(webhook_secret, event_body, signature, now=signed_at + 3600))
            '''
        ),
        md(
            """
            Delivery to a receiver (mocked with respx: no real endpoint is contacted). The
            sender uses a timeout, does not follow redirects, sends an event id so the receiver
            can dedupe (deliveries are at least once), and treats non-2xx as a failure to retry:
            """
        ),
        code(
            r'''
            async def deliver(http: httpx.AsyncClient, url: str, body: bytes) -> int:
                """POST one signed event; return the receiver's status."""
                headers = {
                    "Content-Type": "application/json",
                    "X-Notes-Event-Id": "evt_1",
                    "X-Notes-Signature": sign_payload(webhook_secret, body, int(time.time())),
                }
                reply = await http.post(url, content=body, headers=headers, timeout=5.0, follow_redirects=False)
                return reply.status_code


            def receiver(request: httpx.Request) -> httpx.Response:
                """The customer's endpoint: verify, then accept."""
                valid = verify_payload(
                    webhook_secret, request.content, request.headers["X-Notes-Signature"], now=time.time()
                )
                return httpx.Response(204 if valid else 400)


            async def webhook_demo() -> None:
                """One good delivery and one with a broken signature."""
                with respx.mock() as mock:
                    mock.post("https://hooks.customer.example/notes").mock(side_effect=receiver)
                    async with httpx.AsyncClient() as http:
                        print(
                            "delivered:",
                            await deliver(http, "https://hooks.customer.example/notes", event_body),
                        )
                        good_signature = sign_payload(webhook_secret, event_body, int(time.time()))
                        reply = await http.post(
                            "https://hooks.customer.example/notes",
                            content=event_body + b" ",
                            headers={"X-Notes-Signature": good_signature},
                        )
                        print("body changed in transit:", reply.status_code)


            await webhook_demo()
            '''
        ),
    ]


def _predict_cells() -> list[NotebookNode]:
    """Three predict-the-output questions for Unit 6.6."""
    return [
        md(
            """
            ### Predict the output — Unit 6.6

            Three questions about background tasks, SSE and Redis. Decide first, then run the
            proof.
            """
        ),
        *predict_cells(
            """
            EVENTS.clear()
            with TestClient(ResponseSentMarker(ordering_app)) as client:
                print(client.post("/signup").json(), len(EVENTS))
            print(EVENTS[-1])
            """,
            """
            `{'ok': True} 4` then `task audit-log`. `TestClient` returns only after the whole
            ASGI call, including the background tasks, has finished, so all four events are
            recorded by the time `post()` returns; the last one is the second task. (A real
            client would get the response before the tasks run, as the Uvicorn demo showed.)
            """,
            r"""
            EVENTS.clear()
            with TestClient(ResponseSentMarker(ordering_app)) as client:
                print(client.post("/signup").json(), len(EVENTS))
            print(EVENTS[-1])
            """,
        ),
        *predict_cells(
            """
            print(repr(format_sse({"n": 1}, event_name="tick", event_id=7)))
            """,
            """
            `'id: 7\\nevent: tick\\ndata: {"n": 1}\\n\\n'`. One `field: value` line each, and
            the event ends with an empty line (two newlines in a row); without the blank line
            the browser keeps waiting for the rest of the event.
            """,
            r"""
            print(repr(format_sse({"n": 1}, event_name="tick", event_id=7)))
            """,
        ),
        *predict_cells(
            """
            redis_client = fakeredis.FakeAsyncRedis(decode_responses=True)
            print(
                await redis_client.set("lock:x", "a", nx=True, ex=5),
                await redis_client.set("lock:x", "b", nx=True, ex=5),
                await redis_client.get("lock:x"),
            )
            """,
            """
            `True None a`. `SET ... NX` only writes when the key does not exist: the first call
            returns `True`, the second returns `None` (not `False`) and leaves the value alone.
            That single atomic command is the basis of locks and idempotency keys.
            """,
            r"""
            redis_client = fakeredis.FakeAsyncRedis(decode_responses=True)
            print(
                await redis_client.set("lock:x", "a", nx=True, ex=5),
                await redis_client.set("lock:x", "b", nx=True, ex=5),
                await redis_client.get("lock:x"),
            )
            """,
        ),
    ]


LAB66_GIVEN_SOURCE = r'''
def fake_queue() -> ArqRedis:
    """An ARQ client on an in-memory Redis (enough to enqueue and inspect jobs)."""
    return ArqRedis(connection_pool=fakeredis.FakeAsyncRedis().connection_pool)


def fresh_outbox_db() -> sqlite3.Connection:
    """An in-memory database with orders and an outbox (autocommit: use BEGIN/COMMIT yourself)."""
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.executescript("""
        CREATE TABLE orders (id INTEGER PRIMARY KEY, item TEXT NOT NULL, quantity INTEGER NOT NULL);
        CREATE TABLE outbox (
            id INTEGER PRIMARY KEY,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            published_at TEXT
        );
    """)
    return db


def parse_sse(text: str) -> list[dict[str, object]]:
    """Split an event stream into events: {"id", "event", "data"} (data parsed as JSON)."""
    events = []
    for block in text.strip().split("\n\n"):
        fields = dict(
            line.split(": ", 1)
            for line in block.splitlines()
            if ": " in line and not line.startswith(":")
        )
        if "data" in fields:
            events.append(
                {
                    "id": fields.get("id"),
                    "event": fields.get("event", "message"),
                    "data": json.loads(fields["data"]),
                }
            )
    return events
'''


def _lab_setup_cells() -> list[NotebookNode]:
    """Lab 6.6 introduction and given code."""
    return [
        md(
            """
            ### Lab 6.6

            | Exercise | Syllabus item | You write |
            | --- | --- | --- |
            | 1 | Notes API v5 — ARQ notification jobs | `send_note_notification`, `queue_note_notification` |
            | 2 | WebSocket live updates | `build_live_app()` |
            | 3 | SSE export progress | `export_progress`, `build_export_app()` |
            | 4 | Redis caching with a measured hit rate | `CachedLoader` |
            | 5 | ETags and 304 responses | `build_etag_app()` |
            | 6 | An outbox relay worker | `place_order`, `relay_outbox` |

            The *Notes API v5* section after the lab puts the same pieces into the project.
            Given: `fake_queue()` (an ARQ client on fakeredis), `fresh_outbox_db()` for
            exercise 6, and `parse_sse(text)` to read event streams in the checks:
            """
        ),
        code(LAB66_GIVEN_SOURCE),
    ]


def _lab_exercise_1_cells() -> list[NotebookNode]:
    """Lab 6.6 exercise 1."""
    return [
        md(
            """
            #### Exercise 1 — ARQ notification jobs

            When a note is created, the Notes API should tell the owner by e-mail, in a worker,
            exactly once.

            - `async send_note_notification(ctx, note_id, title, recipient) -> str`, an ARQ
              task. `ctx["redis"]` is the worker's Redis client. Mark the note as notified with
              an atomic `SET notified:<note_id> 1 NX EX 86400`; if it was already marked,
              return `"duplicate"`. Otherwise `RPUSH` the text
              `"<recipient>: new note '<title>'"` to the list `lab66:sent` and return `"sent"`.
            - `async queue_note_notification(pool, note_id, title, recipient) -> str | None`:
              enqueue `send_note_notification` with the job id `notify:<note_id>`; return the
              job id, or `None` when ARQ refused a duplicate.

            The checks call the task directly with a fake `ctx`, and, when Docker is available,
            run it in a **real ARQ worker** (burst mode, in this kernel) against the unit's
            Redis.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            async def send_note_notification(
                ctx: dict[str, Any], note_id: int, title: str, recipient: str
            ) -> str:
                """Send the notification once per note."""
                raise NotImplementedError


            async def queue_note_notification(
                pool: ArqRedis, note_id: int, title: str, recipient: str
            ) -> str | None:
                """Enqueue the notification job (once per note)."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 1. The scenario on fakeredis (enqueue twice, run the task twice):"),
        code(
            r'''
            async def notification_scenario() -> dict[str, object]:
                """Enqueue twice, inspect the queue, run the task twice with a fake ctx."""
                pool = fake_queue()
                job_ids = [await queue_note_notification(pool, 7, "Tea", "asha@example.com") for _ in range(2)]
                queued = [(job.function, job.args) for job in await pool.queued_jobs()]
                ctx = {"redis": pool, "job_id": "notify:7", "job_try": 1}
                runs = [await send_note_notification(ctx, 7, "Tea", "asha@example.com") for _ in range(2)]
                sent = [item.decode() for item in await pool.lrange("lab66:sent", 0, -1)]
                return {
                    "job ids": job_ids,
                    "queued": queued,
                    "runs": runs,
                    "sent": sent,
                    "ttl": await pool.ttl("notified:7"),
                }
            '''
        ),
        md(
            "`real_worker_scenario()`: enqueue on the real Redis and let a burst-mode worker run the job:"
        ),
        code(
            r'''
            async def real_worker_scenario() -> object:
                """Enqueue on the real Redis and let a burst-mode worker run the job."""
                pool = await create_pool(RedisSettings.from_dsn(REDIS_URL))
                await pool.delete(
                    "lab66:sent",
                    "notified:8",
                    *[f"arq:{kind}:notify:8" for kind in ("job", "result", "retry", "in-progress")],
                )
                await pool.zrem("arq:queue", "notify:8")  # leftovers of an earlier run of this cell
                job_id = await queue_note_notification(pool, 8, "Rice", "ravi@example.com")
                worker = Worker(
                    functions=[send_note_notification],
                    redis_pool=pool,
                    burst=True,
                    poll_delay=0.05,
                    handle_signals=False,
                )
                await worker.async_run()
                result = (
                    job_id,
                    worker.jobs_complete,
                    [item.decode() for item in await pool.lrange("lab66:sent", 0, -1)],
                )
                await worker.close()
                return result


            lab_notify_results: dict[str, object] = {}
            lab_worker_result: object = "not run"
            with contextlib.suppress(Exception):
                lab_notify_results = await notification_scenario()
            if REDIS_URL:
                try:
                    lab_worker_result = await real_worker_scenario()
                except Exception as error:  # a check cell must never stop Run All
                    lab_worker_result = f"raised {type(error).__name__}: {error}"
            '''
        ),
        md("The checks (the real-worker check is added only when Docker is available):"),
        code(
            r"""
            notify_checks = [
                ("enqueued once", lambda: lab_notify_results["job ids"], ["notify:7", None]),
                (
                    "the queued job",
                    lambda: lab_notify_results["queued"],
                    [("send_note_notification", (7, "Tea", "asha@example.com"))],
                ),
                (
                    "task runs once, then sees a duplicate",
                    lambda: lab_notify_results["runs"],
                    ["sent", "duplicate"],
                ),
                ("one message", lambda: lab_notify_results["sent"], ["asha@example.com: new note 'Tea'"]),
                ("the marker expires within a day", lambda: 0 < lab_notify_results["ttl"] <= 86_400, True),
            ]
            if REDIS_URL:
                notify_checks.append(
                    (
                        "a real ARQ worker runs it",
                        lambda: lab_worker_result,
                        ("notify:8", 1, ["ravi@example.com: new note 'Rice'"]),
                    )
                )
            else:
                print("SKIP the real-worker check: no Docker")
            run_checks(notify_checks)
            """
        ),
    ]


def _lab_exercise_2_cells() -> list[NotebookNode]:
    """Lab 6.6 exercise 2."""
    return [
        md(
            """
            #### Exercise 2 — WebSocket live updates

            Write `build_live_app() -> FastAPI` (each call has its own state) with a WebSocket
            route `/ws/{room}`:

            1. Accept. The first message must be JSON `{"name": "<non-empty>"}`; otherwise close
               with code **1008**.
            2. Broadcast `{"event": "joined", "name": name}` to everyone in the room (the
               newcomer included).
            3. Each further message `{"text": "..."}` is broadcast as
               `{"event": "message", "name": name, "text": text}` to everyone in the room.
            4. On disconnect, remove the socket and broadcast `{"event": "left", "name": name}`
               to the others. Rooms never see each other's messages.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            def build_live_app() -> FastAPI:
                """Rooms of WebSocket clients with join, message and leave events."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 2. `live_scenario()` drives three clients in two rooms:"),
        code(
            r'''
            def live_scenario() -> dict[str, object]:
                """Join, talk, isolate rooms, leave."""
                results: dict[str, object] = {}
                with TestClient(build_live_app()) as client:
                    with client.websocket_connect("/ws/tea") as asha:
                        asha.send_json({"name": "asha"})
                        results["asha joined"] = asha.receive_json()
                        with (
                            client.websocket_connect("/ws/tea") as ravi,
                            client.websocket_connect("/ws/rice") as zoe,
                        ):
                            ravi.send_json({"name": "ravi"})
                            results["join seen by both"] = [asha.receive_json(), ravi.receive_json()]
                            zoe.send_json({"name": "zoe"})
                            zoe.receive_json()
                            asha.send_json({"text": "kettle is on"})
                            results["message seen by both"] = [asha.receive_json(), ravi.receive_json()]
                            zoe.send_json({"text": "rice is ready"})
                            results["other room"] = zoe.receive_json()  # her own message, nothing from "tea"
                        results["leave"] = asha.receive_json()
                    with client.websocket_connect("/ws/tea") as nameless:
                        nameless.send_json({"text": "no name"})
                        try:
                            nameless.receive_json()
                            results["no name"] = "not closed"
                        except WebSocketDisconnect as closed:
                            results["no name"] = closed.code
                return results
            '''
        ),
        md("The checks:"),
        code(
            r"""
            lab_live_results: dict[str, object] = {}
            with contextlib.suppress(Exception):
                lab_live_results = live_scenario()
            run_checks(
                [
                    (
                        "joined (to the newcomer)",
                        lambda: lab_live_results["asha joined"],
                        {"event": "joined", "name": "asha"},
                    ),
                    (
                        "joined (to everyone)",
                        lambda: lab_live_results["join seen by both"],
                        [{"event": "joined", "name": "ravi"}] * 2,
                    ),
                    (
                        "broadcast",
                        lambda: lab_live_results["message seen by both"],
                        [{"event": "message", "name": "asha", "text": "kettle is on"}] * 2,
                    ),
                    (
                        "rooms are separate",
                        lambda: lab_live_results["other room"],
                        {"event": "message", "name": "zoe", "text": "rice is ready"},
                    ),
                    (
                        "leaving is announced",
                        lambda: lab_live_results["leave"],
                        {"event": "left", "name": "ravi"},
                    ),
                    ("no name: closed with 1008", lambda: lab_live_results["no name"], 1008),
                ]
            )
            """
        ),
    ]


def _lab_exercise_3_cells() -> list[NotebookNode]:
    """Lab 6.6 exercise 3."""
    return [
        md(
            """
            #### Exercise 3 — SSE export progress

            - `async export_progress(total, after)` yields, for each `n` from `after + 1` to
              `total`, the event `id: <n>`, `event: progress`,
              `data: {"done": <n>, "total": <total>}`, then a final event without an id:
              `event: done`, `data: {"total": <total>}`. Every event ends with a blank line
              (`format_sse` from the setup cell does the formatting).
            - `build_export_app()` with `GET /exports/{total}/events`: a `StreamingResponse`
              of `export_progress` with media type `text/event-stream` and
              `Cache-Control: no-cache`, resuming after the `Last-Event-ID` request header
              (default 0).
            """
        ),
        md("Your solution:"),
        code(
            r'''
            async def export_progress(total: int, after: int) -> AsyncIterator[str]:
                """Progress events after the given id, then a done event."""
                raise NotImplementedError
                yield ""  # makes this stub an async generator


            def build_export_app() -> FastAPI:
                """GET /exports/{total}/events as Server-Sent Events."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 3:"),
        code(
            r'''
            def export_events(
                total: int, last_event_id: str | None = None
            ) -> tuple[str, str, list[dict[str, object]]]:
                """Content type, cache header and parsed events of one stream."""
                headers = {"Last-Event-ID": last_event_id} if last_event_id else {}
                with TestClient(build_export_app()) as client:
                    response = client.get(f"/exports/{total}/events", headers=headers)
                    return (
                        response.headers["content-type"].split(";")[0],
                        response.headers.get("cache-control"),
                        parse_sse(response.text),
                    )


            async def raw_progress() -> str:
                """The generator's exact text for total=2, after=1."""
                return "".join([chunk async for chunk in export_progress(2, 1)])


            lab_raw_progress = "not run"
            with contextlib.suppress(Exception):
                lab_raw_progress = await raw_progress()
            '''
        ),
        md("The checks:"),
        code(
            r"""
            run_checks(
                [
                    (
                        "exact event text",
                        lambda: lab_raw_progress,
                        'id: 2\nevent: progress\ndata: {"done": 2, "total": 2}\n\n'
                        'event: done\ndata: {"total": 2}\n\n',
                    ),
                    (
                        "content type and cache header",
                        lambda: export_events(3)[:2],
                        ("text/event-stream", "no-cache"),
                    ),
                    (
                        "all events",
                        lambda: [(event["id"], event["event"], event["data"]) for event in export_events(3)[2]],
                        [
                            ("1", "progress", {"done": 1, "total": 3}),
                            ("2", "progress", {"done": 2, "total": 3}),
                            ("3", "progress", {"done": 3, "total": 3}),
                            (None, "done", {"total": 3}),
                        ],
                    ),
                    (
                        "resume after Last-Event-ID 2",
                        lambda: [event["id"] for event in export_events(4, "2")[2]],
                        ["3", "4", None],
                    ),
                    (
                        "resume at the end",
                        lambda: [event["event"] for event in export_events(4, "4")[2]],
                        ["done"],
                    ),
                ]
            )
            """
        ),
    ]


def _lab_exercise_4_cells() -> list[NotebookNode]:
    """Lab 6.6 exercise 4."""
    return [
        md(
            """
            #### Exercise 4 — Redis caching with a measured hit rate

            `CachedLoader(redis, loader, ttl, namespace)` puts cache-aside in front of an async
            `loader(key)`:

            - `async get(key)`: read `"<namespace>:<key>"` (JSON). On a hit, increment the field
              `hits` of the hash `"<namespace>:stats"`; on a miss, increment `misses`, call the
              loader, store the JSON value with `ex=ttl`, and return it.
            - `async invalidate(key)`: delete the cached value.
            - `async stats() -> dict`: `{"hits": int, "misses": int, "hit_rate": float}` with
              the rate rounded to 2 decimals (0.0 when nothing was read).
            """
        ),
        md("Your solution:"),
        code(
            r'''
            class CachedLoader:
                """Cache-aside with hit/miss counters in Redis."""

                def __init__(
                    self,
                    redis_client: Any,
                    loader: Callable[[str], Awaitable[object]],
                    ttl: int,
                    namespace: str,
                ) -> None:
                    """Keep the collaborators."""
                    raise NotImplementedError

                async def get(self, key: str) -> object:
                    """The cached value, loading it on a miss."""
                    raise NotImplementedError

                async def invalidate(self, key: str) -> None:
                    """Forget one key."""
                    raise NotImplementedError

                async def stats(self) -> dict[str, object]:
                    """Hits, misses and the hit rate."""
                    raise NotImplementedError
            '''
        ),
        md("Check exercise 4. The scenario (awaited here):"),
        code(
            r'''
            async def caching_scenario() -> dict[str, object]:
                """Ten reads of four keys, an invalidation, a second namespace."""
                redis_client = fakeredis.FakeAsyncRedis(decode_responses=True)
                loads: list[str] = []

                async def loader(key: str) -> dict[str, str]:
                    """The slow source, counting calls."""
                    loads.append(key)
                    return {"key": key, "value": key.upper()}

                cache = CachedLoader(redis_client, loader, ttl=30, namespace="lab66:notes")
                values = [await cache.get(key) for key in ["a", "b", "a", "c", "a", "b", "d", "a", "b", "c"]]
                results = {
                    "values": values[:2],
                    "loads": list(loads),
                    "stats": await cache.stats(),
                    "ttl": await redis_client.ttl("lab66:notes:a"),
                    "stored": await redis_client.get("lab66:notes:a"),
                }
                await cache.invalidate("a")
                await cache.get("a")
                results["after invalidate"] = (len(loads), (await cache.stats())["misses"])
                other = CachedLoader(redis_client, loader, ttl=30, namespace="lab66:other")
                results["other namespace"] = await other.stats()
                return results


            lab_cache_results: dict[str, object] = {}
            with contextlib.suppress(Exception):
                lab_cache_results = await caching_scenario()
            '''
        ),
        md("The checks:"),
        code(
            r"""
            run_checks(
                [
                    (
                        "values come back",
                        lambda: lab_cache_results["values"],
                        [{"key": "a", "value": "A"}, {"key": "b", "value": "B"}],
                    ),
                    ("the loader runs once per key", lambda: lab_cache_results["loads"], ["a", "b", "c", "d"]),
                    (
                        "measured hit rate",
                        lambda: lab_cache_results["stats"],
                        {"hits": 6, "misses": 4, "hit_rate": 0.6},
                    ),
                    (
                        "stored as JSON",
                        lambda: json.loads(lab_cache_results["stored"]),
                        {"key": "a", "value": "A"},
                    ),
                    ("with the TTL", lambda: 0 < lab_cache_results["ttl"] <= 30, True),
                    ("invalidate forces a reload", lambda: lab_cache_results["after invalidate"], (5, 5)),
                    (
                        "namespaces keep separate stats",
                        lambda: lab_cache_results["other namespace"],
                        {"hits": 0, "misses": 0, "hit_rate": 0.0},
                    ),
                ]
            )
            """
        ),
    ]


def _lab_exercise_5_cells() -> list[NotebookNode]:
    """Lab 6.6 exercise 5."""
    return [
        md(
            """
            #### Exercise 5 — ETags and 304 responses

            `build_etag_app()` (its own state, seeded with item 1 `{"id": 1, "name": "tea",
            "version": 1}`):

            - `GET /items/{item_id}`: 404 if missing; else the item with
              `ETag: "<id>-<version>"` and `Cache-Control: private, no-cache`. If
              `If-None-Match` matches (a comma-separated list; `W/` prefixes ignored; `*`
              matches anything) → **304** with the `ETag` header and an empty body.
            - `PUT /items/{item_id}` with JSON `{"name": ...}`: optimistic concurrency with
              `If-Match`. Missing → **428** Precondition Required; not the current ETag →
              **412** Precondition Failed; otherwise bump the version, save the name, return
              the item with its new `ETag`.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            def build_etag_app() -> FastAPI:
                """Items with ETags, 304 revalidation and If-Match updates."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 5:"),
        code(
            r'''
            def etag_scenario() -> dict[str, object]:
                """Revalidate, update with and without the right precondition."""
                with TestClient(build_etag_app()) as client:
                    first = client.get("/items/1")
                    etag = first.headers.get("etag")
                    not_modified = client.get("/items/1", headers={"If-None-Match": f'"0-0", W/{etag}'})
                    return {
                        "first": (first.status_code, etag, first.headers.get("cache-control"), first.json()),
                        "304": (
                            not_modified.status_code,
                            not_modified.headers.get("etag"),
                            not_modified.content,
                        ),
                        "star": client.get("/items/1", headers={"If-None-Match": "*"}).status_code,
                        "no If-Match": client.put("/items/1", json={"name": "chai"}).status_code,
                        "stale If-Match": client.put(
                            "/items/1", json={"name": "chai"}, headers={"If-Match": '"1-0"'}
                        ).status_code,
                        "update": (lambda reply: (reply.status_code, reply.headers.get("etag"), reply.json()))(
                            client.put("/items/1", json={"name": "chai"}, headers={"If-Match": etag})
                        ),
                        "old ETag now": client.get("/items/1", headers={"If-None-Match": etag}).status_code,
                        "missing": client.get("/items/99").status_code,
                    }


            lab_etag_results: dict[str, object] = {}
            with contextlib.suppress(Exception):
                lab_etag_results = etag_scenario()
            '''
        ),
        md("The checks:"),
        code(
            r"""
            run_checks(
                [
                    (
                        "200 with validators",
                        lambda: lab_etag_results["first"],
                        (200, '"1-1"', "private, no-cache", {"id": 1, "name": "tea", "version": 1}),
                    ),
                    ("304 from a list with a weak tag", lambda: lab_etag_results["304"], (304, '"1-1"', b"")),
                    ("* matches", lambda: lab_etag_results["star"], 304),
                    ("PUT without If-Match: 428", lambda: lab_etag_results["no If-Match"], 428),
                    ("PUT with a stale ETag: 412", lambda: lab_etag_results["stale If-Match"], 412),
                    (
                        "PUT with the current ETag",
                        lambda: lab_etag_results["update"],
                        (200, '"1-2"', {"id": 1, "name": "chai", "version": 2}),
                    ),
                    ("the old ETag no longer matches", lambda: lab_etag_results["old ETag now"], 200),
                    ("unknown item: 404", lambda: lab_etag_results["missing"], 404),
                ]
            )
            """
        ),
    ]


def _lab_exercise_6_cells() -> list[NotebookNode]:
    """Lab 6.6 exercise 6."""
    return [
        md(
            """
            #### Exercise 6 — An outbox relay worker

            With a database from `fresh_outbox_db()`:

            - `place_order(db, item, quantity) -> int`: in **one transaction** (`BEGIN` …
              `COMMIT`, `ROLLBACK` and re-raise on any error), insert the order and an outbox
              row with `event_type = "order.placed"` and the JSON payload
              `{"order_id": <id>, "item": ..., "quantity": ...}`. A quantity below 1 raises
              `ValueError` **inside** the transaction, so nothing is written. Return the order
              id.
            - `relay_outbox(db, publish, batch_size=100) -> int`: take up to `batch_size`
              unpublished rows (`published_at IS NULL`) in id order; for each, call
              `publish({"id": <outbox id>, "type": <event_type>, **payload})`, then set its
              `published_at`. If `publish` raises, stop: that row stays unpublished. Return how
              many were published.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            def place_order(db: sqlite3.Connection, item: str, quantity: int) -> int:
                """Write the order and its event atomically."""
                raise NotImplementedError


            def relay_outbox(
                db: sqlite3.Connection, publish: Callable[[dict[str, object]], None], batch_size: int = 100
            ) -> int:
                """Publish unpublished events in order; stop at the first failure."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 6:"),
        code(
            r'''
            def outbox_scenario() -> dict[str, object]:
                """Orders, a failed one, relays with a flaky and a working publisher."""
                db = fresh_outbox_db()
                place_order(db, "tea", 2)
                place_order(db, "rice", 1)
                bad = raised_error_name(lambda: place_order(db, "milk", 0))
                rows = (
                    db.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
                    db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0],
                )
                place_order(db, "milk", 3)
                delivered: list[dict[str, object]] = []

                def flaky_publish(event: dict[str, object]) -> None:
                    """Fail on the second event."""
                    if len(delivered) == 1:
                        raise ConnectionError("broker down")
                    delivered.append(event)

                first_run = relay_outbox(db, flaky_publish)
                second_run = relay_outbox(db, delivered.append, batch_size=1)
                third_run = relay_outbox(db, delivered.append)
                return {
                    "bad order": bad,
                    "rows after bad order": rows,
                    "runs": [first_run, second_run, third_run, relay_outbox(db, delivered.append)],
                    "delivered": delivered,
                }
            '''
        ),
        md("The checks:"),
        code(
            r"""
            lab_outbox_results: dict[str, object] = {}
            with contextlib.suppress(Exception):
                lab_outbox_results = outbox_scenario()
            run_checks(
                [
                    ("quantity 0 is a ValueError", lambda: lab_outbox_results["bad order"], "ValueError"),
                    ("... and wrote nothing", lambda: lab_outbox_results["rows after bad order"], (2, 2)),
                    (
                        "relay counts: flaky, batch of 1, rest, nothing left",
                        lambda: lab_outbox_results["runs"],
                        [1, 1, 1, 0],
                    ),
                    (
                        "events in order, none twice",
                        lambda: [(event["id"], event["item"]) for event in lab_outbox_results["delivered"]],
                        [(1, "tea"), (2, "rice"), (3, "milk")],
                    ),
                    (
                        "event shape",
                        lambda: lab_outbox_results["delivered"][0],
                        {"id": 1, "type": "order.placed", "order_id": 1, "item": "tea", "quantity": 2},
                    ),
                ]
            )
            """
        ),
    ]


def _notes_v5_intro_cells() -> list[NotebookNode]:
    """Notes API v5: introduction and pruning."""
    return [
        md(
            """
            ### Notes API v5 — the project files

            v5 moves slow and outward-facing work out of the request, pushes changes to
            clients, and caches reads:

            | v4 (Unit 6.5) | v5 (this unit) |
            | --- | --- |
            | registration only stores the user | the welcome e-mail goes out in a `BackgroundTasks` task, after the response |
            | nothing happens after a write | every create/update/delete writes an **outbox event** in the same transaction (`outbox_events`, migration `0006`) |
            | — | an **ARQ worker** (`python -m notes_api.worker`): `relay_outbox` (cron every 10 s and kicked after each write, Redis lock, `SKIP LOCKED`), `deliver_webhook` (signed, retried with backoff, dead-lettered), `export_notes`, nightly `purge_expired_tokens` |
            | — | per-user **webhooks** (`/users/me/webhook`; SSRF-checked URL, `whsec_` secret shown once), admin dead-letter list and retry |
            | clients poll | **`WS /api/v1/ws`**: first-message token auth (close 1008), events fanned out through Redis pub/sub, heartbeats |
            | — | **`POST /api/v1/exports`** → 202 + `Location`; progress as **SSE** from a Redis Stream (resumable with `Last-Event-ID`); download |
            | every `GET` hits the database | `GET /notes/{id}`: Redis **cache-aside** (versioned keys, TTL jitter, stampede lock, hit/miss stats), strong **ETag**, **304**, `Cache-Control: private, no-cache`; lists `no-store` |

            The cells write the 34 files that change or are new (of 77). First, remove files of
            other versions (nothing after a full run):
            """
        ),
        code(
            r'''
            NOTES_V5_FILES = """
            .env.example README.md alembic.ini alembic/env.py alembic/script.py.mako
            alembic/versions/0001_create_notes.py alembic/versions/0002_tags_many_to_many.py
            alembic/versions/0003_version_and_search.py alembic/versions/0004_users_and_ownership.py
            alembic/versions/0005_refresh_tokens_and_api_keys.py
            alembic/versions/0006_outbox_and_webhooks.py compose.yaml pyproject.toml ruff.toml
            src/notes_api/__init__.py src/notes_api/auth.py src/notes_api/cache.py
            src/notes_api/core/__init__.py src/notes_api/core/config.py src/notes_api/core/errors.py
            src/notes_api/core/lifespan.py src/notes_api/core/logging.py src/notes_api/core/middleware.py
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
            src/notes_api/templates/login.html src/notes_api/worker.py tests/conftest.py tests/helpers.py
            tests/test_admin.py tests/test_auth.py tests/test_background.py tests/test_bola.py
            tests/test_caching.py tests/test_errors.py tests/test_exports.py tests/test_links.py
            tests/test_middleware.py tests/test_migrations.py tests/test_notes.py tests/test_oauth.py
            tests/test_pages.py tests/test_pagination.py tests/test_postgres.py tests/test_realtime.py
            tests/test_redis_worker.py tests/test_repository.py tests/test_security.py
            tests/test_settings.py tests/test_worker.py
            """.split()
            print("removed:", prune_notes_project(NOTES_V5_FILES))
            print(f"{len(NOTES_V5_FILES)} files in v5")
            '''
        ),
    ]


def _notes_v5_try_cells() -> list[NotebookNode]:
    """Notes API v5: try it in the kernel."""
    return [
        md(
            """
            **Try it in the kernel.** As in the test suite, one `FakeServer` backs both Redis
            clients (the text client for cache, pub/sub and streams, and the `ArqRedis` queue),
            so the notebook can see the jobs the API enqueues and run worker tasks itself with a
            context like the one `startup()` builds:
            """
        ),
        code(
            r"""
            notes_main = reload_notes_api()
            notes_worker = importlib.import_module("notes_api.worker")
            NotesSettings = sys.modules["notes_api.core.config"].Settings
            notes_db = sys.modules["notes_api.db"]
            notes_dependencies = sys.modules["notes_api.dependencies"]

            demo_db = PHASE6_DIR / "notes_v5_demo.db"
            demo_db.unlink(missing_ok=True)
            notes_settings = NotesSettings(
                _env_file=None,
                environment="test",
                database_url=SecretStr(f"sqlite+aiosqlite:///{demo_db}"),
                jwt_secret=SecretStr(secrets.token_urlsafe(32)),
                password_time_cost=1,
                password_memory_kib=64,
                cookie_secure=False,
                admin_emails=["admin@example.com"],
            )
            schema_engine = notes_db.create_engine_from_settings(notes_settings)
            async with schema_engine.begin() as connection:
                await connection.run_sync(notes_db.Base.metadata.create_all)
            await schema_engine.dispose()

            fake_server = fakeredis.FakeServer()
            text_redis = fakeredis.FakeAsyncRedis(server=fake_server, decode_responses=True)
            demo_queue = ArqRedis(connection_pool=fakeredis.FakeAsyncRedis(server=fake_server).connection_pool)
            notes_app = notes_main.create_app(notes_settings)
            notes_app.dependency_overrides[notes_dependencies.get_redis] = lambda: text_redis
            notes_app.dependency_overrides[notes_dependencies.get_queue] = lambda: demo_queue
            logging.getLogger("notes_api").handlers[:] = [logging.StreamHandler(sys.stdout)]
            print(
                sorted(
                    route.path
                    for route in notes_app.routes
                    if "exports" in getattr(route, "path", "") or "ws" in getattr(route, "path", "")
                )
            )
            """
        ),
        md(
            """
            ETags and the cache: the first `GET` is a cache miss, the revalidation is a 304 with
            an empty body, a `PATCH` changes the version (so the old ETag no longer matches),
            and the admin endpoint shows the counters. Every write also left an outbox row and
            queued a `relay_outbox` kick:
            """
        ),
        code(
            r'''
            def v5_login(client: TestClient, email: str) -> dict[str, str]:
                """Register (ignoring 409) and log in; return a bearer header."""
                client.post("/api/v1/auth/register", json={"email": email, "password": "a-long-passphrase"})
                tokens = client.post(
                    "/api/v1/auth/token", data={"username": email, "password": "a-long-passphrase"}
                ).json()
                return {"Authorization": f"Bearer {tokens['access_token']}"}


            with TestClient(notes_app) as client:
                as_admin = v5_login(client, "admin@example.com")
                created = client.post("/api/v1/notes", json={"title": "Cached note"}, headers=as_admin).json()
                note_url = f"/api/v1/notes/{created['id']}"
                first = client.get(note_url, headers=as_admin)
                show_response(first, "etag", "cache-control")
                again = client.get(note_url, headers=as_admin | {"If-None-Match": first.headers["etag"]})
                print("revalidated:", again.status_code, f"{len(again.content)} bytes")
                client.patch(note_url, json={"pinned": True}, headers=as_admin)
                print(
                    "old ETag after PATCH:",
                    client.get(
                        note_url, headers=as_admin | {"If-None-Match": first.headers["etag"]}
                    ).status_code,
                )
                print("cache stats:", client.get("/api/v1/admin/cache-stats", headers=as_admin).json())
                print(
                    "queued jobs:", sorted({job.function for job in client.portal.call(demo_queue.queued_jobs)})
                )
            with sqlite3.connect(demo_db) as database:
                print(
                    "outbox:",
                    database.execute("SELECT id, event_type, published_at FROM outbox_events").fetchall(),
                )
            '''
        ),
        md(
            """
            **Live updates.** Open the WebSocket, send the token as the first message, create a
            note, and run the worker's `relay_outbox` task: it publishes each event on its
            owner's Redis channel, and the socket receives it:
            """
        ),
        code(
            r'''
            def worker_context() -> dict[str, Any]:
                """What WorkerSettings.on_startup builds, on the demo database and fake Redis."""
                engine = notes_db.create_engine_from_settings(notes_settings)
                return {
                    "settings": notes_settings,
                    "session_factory": notes_db.make_session_factory(engine),
                    "text_redis": text_redis,
                    "redis": demo_queue,
                }


            with TestClient(notes_app) as client:
                as_asha = v5_login(client, "asha@example.com")
                token = as_asha["Authorization"].removeprefix("Bearer ")
                with client.websocket_connect("/api/v1/ws") as websocket:
                    websocket.send_json({"token": token})
                    print("socket:", websocket.receive_json())
                    client.post("/api/v1/notes", json={"title": "Live note"}, headers=as_asha)
                    print(
                        "relay published:",
                        client.portal.call(notes_worker.relay_outbox, worker_context()),
                        "events",
                    )
                    pushed = websocket.receive_json()
                    print("pushed:", pushed["type"], pushed["data"])
            '''
        ),
        md(
            """
            **An export with SSE progress.** `POST /exports` answers 202 at once and queues the
            job; here the notebook runs the worker task, then reads the event stream (which
            ends when the export is done) and the download:
            """
        ),
        code(
            r"""
            with TestClient(notes_app) as client:
                as_asha = v5_login(client, "asha@example.com")
                for number in range(3):
                    client.post("/api/v1/notes", json={"title": f"Export me {number}"}, headers=as_asha)
                started = client.post("/api/v1/exports", headers=as_asha)
                print(
                    started.status_code,
                    "Location:",
                    started.headers["location"].replace(started.json()["id"], "<id>"),
                )
                user_id = client.get("/api/v1/users/me", headers=as_asha).json()["id"]
                client.portal.call(notes_worker.export_notes, worker_context(), started.json()["id"], user_id)
                stream_text = client.get(started.json()["events_url"], headers=as_asha).text
                print(
                    [
                        line.removeprefix("data: ")
                        for line in stream_text.splitlines()
                        if line.startswith("data: ")
                    ]
                )
                download = client.get(f"{started.headers['location']}/download", headers=as_asha)
                print(
                    "download:",
                    download.headers["content-disposition"].split(";")[0],
                    "with",
                    len(download.json()),
                    "notes",
                )
            """
        ),
    ]


def _notes_v5_run_cells() -> list[NotebookNode]:
    """Notes API v5: migration, the real API + worker, the suite, clean up."""
    return [
        md(
            """
            **Migrate** a fresh SQLite file to `head` (migration `0006` adds the outbox):
            """
        ),
        code(
            r'''
            live_db = PHASE6_DIR / "notes_v5_live.db"
            live_db.unlink(missing_ok=True)
            NOTES_DB_ENV = {"NOTES_DATABASE_URL": f"sqlite+aiosqlite:///{live_db}"}


            def notes_alembic(*arguments: str) -> str:
                """Run alembic in projects/notes_api against NOTES_DB_ENV; return its log lines."""
                run = run_in_notes(sys.executable, "-m", "alembic", *arguments, extra_env=NOTES_DB_ENV)
                lines = [
                    re.sub(r"^INFO  \[alembic\.\S+\] ", "", line)
                    for line in (run.stdout + run.stderr).splitlines()
                ]
                noise = ("Context impl", "Will assume", "setting up autogenerate plugin")
                return (
                    "\n".join(line for line in lines if line and not line.startswith(noise))
                    or f"exit code {run.returncode}"
                )


            print(notes_alembic("upgrade", "head").splitlines()[-1])
            print("current:", notes_alembic("current"))
            '''
        ),
        md(
            """
            **The real thing**: the API under Uvicorn **and** the ARQ worker, each in its own
            background process, sharing the unit's Redis container and the migrated database.
            The notebook opens a WebSocket to the API and creates a note over HTTP; the API
            commits the note and its outbox row, kicks the relay; the **worker** publishes the
            event on Redis; the **API process** forwards it to the socket. Then an export runs in
            the worker while the notebook follows its SSE progress. Both processes are stopped
            when the cell ends. Without Docker the cell prints a skip message:
            """
        ),
        code(
            r'''
            def live_v5_demo(base_url: str) -> None:
                """WebSocket push from the worker, then an export followed over SSE."""
                from websockets.sync.client import connect

                with httpx.Client(base_url=base_url, trust_env=False, timeout=30) as http:
                    http.post(
                        "/api/v1/auth/register",
                        json={"email": "live@example.com", "password": "a-long-passphrase"},
                    )
                    token = http.post(
                        "/api/v1/auth/token",
                        data={"username": "live@example.com", "password": "a-long-passphrase"},
                    ).json()["access_token"]
                    bearer = {"Authorization": f"Bearer {token}"}
                    with connect(base_url.replace("http://", "ws://") + "/api/v1/ws") as socket:
                        socket.send(json.dumps({"token": token}))
                        print("socket:", json.loads(socket.recv(timeout=10))["type"])
                        http.post("/api/v1/notes", json={"title": "Written over HTTP"}, headers=bearer)
                        pushed = json.loads(socket.recv(timeout=20))
                        print("pushed by the worker via Redis:", pushed["type"], pushed["data"].get("title"))
                    started = http.post("/api/v1/exports", headers=bearer).json()
                    with http.stream("GET", started["events_url"], headers=bearer) as stream:
                        progress = [
                            json.loads(line[6:])["status"]
                            for line in stream.iter_lines()
                            if line.startswith("data: ")
                        ]
                    print("export progress over SSE:", progress)
                    print(
                        "download:",
                        len(http.get(started["status_url"] + "/download", headers=bearer).json()),
                        "note(s)",
                    )
            '''
        ),
        md("Then run it:"),
        code(
            r"""
            if REDIS_URL:
                live_env = {
                    **NOTES_DB_ENV,
                    "NOTES_REDIS_URL": REDIS_URL,
                    "NOTES_JWT_SECRET": secrets.token_urlsafe(32),
                }
                worker_env = {**live_env, "PYTHONPATH": str(NOTES_SRC)}
                redis_asyncio_client = make_redis(REDIS_URL)
                await redis_asyncio_client.delete("arq:queue:health-check")
                await redis_asyncio_client.aclose()
                worker_ready = lambda: redis_key_exists(REDIS_URL, "arq:queue:health-check")  # noqa: E731
                with worker_process(
                    [sys.executable, "-m", "notes_api.worker"],
                    worker_ready,
                    extra_env=worker_env,
                    cwd=NOTES_API_DIR,
                ):
                    with uvicorn_server(
                        "notes_api.main:app", app_dir=NOTES_SRC, extra_env=live_env
                    ) as base_url:
                        live_v5_demo(base_url)
            else:
                print("SKIP the live API + worker demo: no Docker, so no real Redis")
            """
        ),
        md(
            """
            **Run this version's tests.** `NEW_TESTS` lists the test files v5 adds or changes
            (the full suite runs once, in the Phase 6 Project). With the kernel's environment, the fast ones among them (no
            PostgreSQL, no real Redis):
            """
        ),
        code(
            r"""
            NEW_TESTS = __NEW_TESTS__
            pytest_run = run_in_notes(
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-m",
                "not postgres and not redis",
                *NEW_TESTS,
            )
            print(tidy_test_output(pytest_run.stdout + pytest_run.stderr).splitlines()[-1])
            print(f"{pytest_run.returncode=}")
            """
        ),
        md(
            """
            And as its own uv project: `uv lock` adds `arq`, then `uv run --frozen pytest` runs
            all of `NEW_TESTS`, including `test_redis_worker.py`, which starts (and removes) its
            own Redis container and runs the real ARQ worker in burst mode:
            """
        ),
        code(
            r"""
            if HAS_UV:
                lock_run = run_in_notes("uv", "lock")
                print(lock_summary(lock_run.stderr))
                if lock_run.returncode == 0:
                    uv_command = ["uv", "run", "--frozen", "pytest", "-p", "no:cacheprovider", "-rs"]
                    uv_pytest = run_in_notes(*uv_command, *NEW_TESTS, timeout=600)
                    summary = tidy_test_output(uv_pytest.stdout).splitlines()
                    print(summary[-1], f"(exit code {uv_pytest.returncode})")
                    print(*[line for line in summary if line.startswith("SKIPPED")], sep="\n")
                else:
                    print("SKIP uv run pytest: uv lock failed (offline with an empty cache?)")
            else:
                print("SKIP: the uv command is not on PATH")
            """
        ),
        md("The project after Unit 6.6:"),
        code(
            r"""
            print(notes_tree())
            """
        ),
        md(
            """
            **Clean up.** Stop and remove the unit's Redis container, then confirm that no
            container started by this notebook is left (`docker ps`):
            """
        ),
        code(
            r"""
            container_id = shared_redis_id()  # None when the unit started no container
            if container_id is not None:
                stop_shared_redis()
                still_there = subprocess.run(
                    ["docker", "ps", "-aq", "--filter", f"id={container_id}"], capture_output=True, text=True
                ).stdout.strip()
                print(f"Redis container stopped and removed: {not still_there}")
            else:
                print("no container to stop")
            if shutil.which("docker"):
                running = subprocess.run(
                    ["docker", "ps", "--format", "{{.Image}}"], capture_output=True, text=True
                ).stdout.split()
                print("containers still running:", running or "none")
            """
        ),
        md(
            """
            What v5 leaves for later: structured logs, metrics, traces and a richer test suite
            (Unit 6.7); a container image with the API and the worker as separate services,
            migrations at deploy time and production settings (6.8).
            """
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 6.6."""
    return [
        md(
            """
            ### Recap — Unit 6.6

            | Concept | One-line takeaway | JS / TS equivalent |
            | --- | --- | --- |
            | `BackgroundTasks` | after the response, same process: fine for small, losable work | `res.on("finish")`, `setImmediate` |
            | Task queues | producer → broker → workers; at-least-once delivery | BullMQ |
            | ARQ | asyncio + Redis; `enqueue_job`, `_job_id`, `_defer_by`, `Retry`, `cron` | BullMQ jobs, repeatable jobs |
            | Celery / Dramatiq / Taskiq | mature sync / simple sync / async-native alternatives | Bee-Queue, Agenda |
            | Idempotency | `SET key NX` before side effects; job ids; event ids for consumers | idempotency keys |
            | Retries and DLQ | exponential backoff with a cap; park what never succeeds | BullMQ `attempts` + failed set |
            | Transactional outbox | the event is a row in the same transaction; a relay publishes it | same pattern |
            | Scheduled jobs and locks | cron in the worker; `SET NX EX` + token-checked release | `node-cron` + Redlock |
            | WebSockets | 101 upgrade, `@app.websocket`, connection manager, first-message auth, heartbeats | `ws`, Socket.IO |
            | Redis fan-out | each process subscribes and forwards to its own sockets | Socket.IO Redis adapter |
            | SSE | `text/event-stream`, `id`/`event`/`data`, `Last-Event-ID` resume | `EventSource` |
            | SSE vs WS vs polling | one-way updates → SSE; two-way → WS; rare changes → polling | same trade-offs |
            | HTTP caching | `Cache-Control`, `ETag`, `If-None-Match` → 304 | `etag`, `fresh` |
            | Redis caching | cache-aside, versioned keys, TTL + jitter, invalidate on write, stampede lock | `ioredis` + custom code |
            | Pub/sub vs Streams | fire-and-forget fan-out vs a durable log with consumer groups | Redis in Node is the same |
            | Signed webhooks | HMAC over `timestamp.body`, constant-time check, replay window | `stripe.webhooks.constructEvent` |

            **Further reading**

            - FastAPI: [Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/),
              [WebSockets](https://fastapi.tiangolo.com/advanced/websockets/),
              [Custom responses / StreamingResponse](https://fastapi.tiangolo.com/advanced/custom-response/)
            - [ARQ](https://arq-docs.helpmanual.io/), [Celery](https://docs.celeryq.dev/),
              [Dramatiq](https://dramatiq.io/), [Taskiq](https://taskiq-python.github.io/)
            - Redis: [pub/sub](https://redis.io/docs/latest/develop/interact/pubsub/),
              [Streams](https://redis.io/docs/latest/develop/data-types/streams/),
              [distributed locks](https://redis.io/docs/latest/develop/use/patterns/distributed-locks/),
              [client-side caching patterns](https://redis.io/docs/latest/develop/use/client-side-caching/)
            - RFCs and specs: [6455 WebSocket](https://www.rfc-editor.org/rfc/rfc6455),
              [HTML Server-Sent Events](https://html.spec.whatwg.org/multipage/server-sent-events.html),
              [9111 HTTP Caching](https://www.rfc-editor.org/rfc/rfc9111),
              [9110 conditional requests](https://www.rfc-editor.org/rfc/rfc9110#name-conditional-requests)
            - [MDN: Cache-Control](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Cache-Control),
              [ETag](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/ETag),
              [EventSource](https://developer.mozilla.org/en-US/docs/Web/API/EventSource)
            - [Transactional outbox pattern](https://microservices.io/patterns/data/transactional-outbox.html),
              [Stripe webhook signatures](https://docs.stripe.com/webhooks#verify-events)
            - Python: [`asyncio` tasks](https://docs.python.org/3/library/asyncio-task.html),
              [`hmac`](https://docs.python.org/3/library/hmac.html),
              [`email.utils` (HTTP dates)](https://docs.python.org/3/library/email.utils.html),
              [PEP 525 (async generators)](https://peps.python.org/pep-0525/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 6.6, Lab 6.6 and Notes API v5."""
    return [
        *_overview_cells(),
        *_background_tasks_cells(),
        *_queue_cells(),
        *_reliability_cells(),
        *_websocket_cells(),
        *_sse_cells(),
        *_http_cache_cells(),
        *_redis_cache_cells(),
        *_messaging_cells(),
        *_predict_cells(),
        *_lab_setup_cells(),
        *_lab_exercise_1_cells(),
        *_lab_exercise_2_cells(),
        *_lab_exercise_3_cells(),
        *_lab_exercise_4_cells(),
        *_lab_exercise_5_cells(),
        *_lab_exercise_6_cells(),
        *_notes_v5_intro_cells(),
        *_notes_v5_project_cells(),
        *_notes_v5_data_cells(),
        *_notes_v5_background_cells(),
        *_notes_v5_router_cells(),
        *_notes_v5_test_cells(),
        *_notes_v5_try_cells(),
        *_notes_v5_run_cells(),
        *_recap_cells(),
    ]


def _notes_v5_project_cells() -> list[NotebookNode]:
    """Notes API v5: project metadata, environment template, README."""
    return [
        md(
            """
            **Project metadata.** Version 0.5.0 and one new runtime package, `arq`. A `redis`
            test marker selects the end-to-end test that runs the real worker against a
            Redis testcontainer; two warning filters silence deprecation warnings that arq
            0.25 triggers on Python 3.15 (see the worker below):
            """
        ),
        *writefile_cells(
            NOTES_V5_PYPROJECT_TOML,
            [
                ("", "Part 1 of `pyproject.toml`: from `[project]`."),
                ("[tool.pytest.ini_options]", "Part 2: from `[tool.pytest.ini_options]`."),
            ],
        ),
        md("`.env.example` gains the background-work, caching and real-time settings:"),
        code(NOTES_V5_ENV_EXAMPLE),
        md(
            "The README: how to run the worker, the new endpoints, caching behaviour and the layout:"
        ),
        *writefile_cells(
            NOTES_V5_README_MD,
            [
                ("", "Part 1 of `README.md`: Notes API."),
                ("## Endpoints", "Part 2: Endpoints."),
                ("## Layout", "Part 3: Layout."),
            ],
        ),
    ]


def _notes_v5_data_cells() -> list[NotebookNode]:
    """Notes API v5: settings, exceptions, lifespan, models, migration 0006, schemas, repositories, services."""
    return [
        md("Version 0.5.0:"),
        code(NOTES_V5_INIT_PY),
        md(
            "`config.py` adds webhook timeouts and attempts, the cache TTL, the WebSocket heartbeat and how long exports are kept:"
        ),
        *writefile_cells(
            NOTES_V5_CORE_CONFIG_PY,
            [
                (
                    "",
                    "Part 1 of `core/config.py`: the module docstring and imports, then `Settings`.",
                ),
                ('    app_name: str = "Notes API"', "Part 2 (continues `Settings`): more fields."),
                (
                    "    @property",
                    "Part 3 (continues `Settings`): `oauth_enabled()`, `require_real_secrets_in_production()`; then `get_settings()` — The process-wide settings, read from the environment once and then cached.",
                ),
            ],
        ),
        md("`exceptions.py` adds `ExportNotFoundError` (404) and `InvalidWebhookError` (422):"),
        *writefile_cells(
            NOTES_V5_EXCEPTIONS_PY,
            [
                (
                    "",
                    "Part 1 of `exceptions.py`: the module docstring and imports, then `DomainError`, `NoteNotFoundError`, `VersionConflictError`.",
                ),
                (
                    "    def __init__(\n        self, note_id: int, expected: int | None = None, actual: int | None = None",
                    "Part 2 (continues `VersionConflictError`): `__init__()`; then `InvalidCursorError`, `UploadRejectedError`, `AuthenticationError` — A pagination cursor that this API did not issue.",
                ),
                (
                    "    def __init__(self, detail: str, scopes: list[str] | None = None) -> None:",
                    "Part 3 (continues `AuthenticationError`): `__init__()`; then `PermissionDeniedError`, `EmailTakenError`, `RateLimitedError` — Authenticated, but not allowed to do this (403).",
                ),
                (
                    "    def __init__(self, retry_after: int) -> None:",
                    "Part 4 (continues `RateLimitedError`): `__init__()`; then `ApiKeyNotFoundError`, `ExportNotFoundError`, `InvalidWebhookError` — The caller has no API key with this id (someone else's key is 'not found' too).",
                ),
                (
                    "    status_code = HTTPStatus.UNPROCESSABLE_CONTENT",
                    "Part 5 (continues `InvalidWebhookError`): more fields.",
                ),
            ],
        ),
        md(
            """
            The lifespan opens a second Redis client: an `ArqRedis` for enqueuing jobs
            (bytes, pickled job payloads) next to the text client (`decode_responses=True`)
            used for caching, rate limits and pub/sub:
            """
        ),
        *writefile_cells(
            NOTES_V5_CORE_LIFESPAN_PY,
            [
                ("", "Part 1 of `core/lifespan.py`: the module docstring and imports."),
                (
                    "@asynccontextmanager",
                    "Part 2: `lifespan()` — Open the database pool, Redis (text and queue clients) and an HTTP client; close them.",
                ),
            ],
        ),
        md(
            """
            **Models.** `User` gains `webhook_url` and `webhook_secret` (kept in clear: the
            worker needs it to sign; it is shown to its owner once). `OutboxEvent` is the
            **transactional outbox**: a row written in the same transaction as the note
            change, published later by the relay, with webhook delivery status, attempts and
            the last error:
            """
        ),
        *writefile_cells(
            NOTES_V5_MODELS_PY,
            [
                (
                    "",
                    "Part 1 of `models.py`: the module docstring and imports, then `utc_now()`, `TimestampMixin`, `User`.",
                ),
                (
                    "    id: Mapped[int] = mapped_column(primary_key=True)",
                    "Part 2 (continues `User`): `__repr__()`; then `RefreshToken`, `ApiKey` — One opaque refresh token (only its SHA-256 is stored); a family shares one login.",
                ),
                (
                    '    id: Mapped[int] = mapped_column(primary_key=True)\n    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)',
                    "Part 3 (continues `ApiKey`): more fields; then `OutboxEvent`, `Tag` — A domain event written in the same transaction as the change (transactional outbox).",
                ),
                (
                    "    id: Mapped[int] = mapped_column(primary_key=True)\n    name: Mapped[str] = mapped_column(String(30), unique=True)",
                    "Part 4 (continues `Tag`): more fields; then `Note` — A note; tags is a list of names backed by the many-to-many tag_objects relationship.",
                ),
                (
                    '    def __repr__(self) -> str:\n        """Short form for logs and notebooks."""',
                    "Part 5 (continues `Note`): `__repr__()` — Short form for logs and notebooks.",
                ),
            ],
        ),
        md(
            "**Migration 0006**: the `outbox_events` table (indexed on `published_at, id` for the relay) and the two webhook columns:"
        ),
        *writefile_cells(
            NOTES_V5_ALEMBIC_VERSIONS_0006_OUTBOX_AND_WEBHOOKS_PY,
            [
                (
                    "",
                    "Part 1 of `alembic/versions/0006_outbox_and_webhooks.py`: the module docstring and imports.",
                ),
                (
                    "def upgrade() -> None:",
                    "Part 2: `upgrade()` — Two nullable user columns and the outbox table.",
                ),
                (
                    "def downgrade() -> None:",
                    "Part 3: `downgrade()` — Drop the outbox and the webhook columns.",
                ),
            ],
        ),
        md("`schemas.py` adds `WebhookSettings` (an `HttpUrl`):"),
        *writefile_cells(
            NOTES_V5_SCHEMAS_PY,
            [
                (
                    "",
                    "Part 1 of `schemas.py`: the module docstring and imports, then `require_slug()`, `unique_in_order()`.",
                ),
                (
                    "Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]",
                    "Part 2: `Title`, `Body`, `Tag`, `Tags`, `SortOrder`, ... — Body of POST /notes and PUT /notes/{note_id}: every field a client may set.",
                ),
                (
                    '    model_config = ConfigDict(\n        extra="forbid", json_schema_extra={"examples": [{"pinned": True, "version": 1}]}',
                    "Part 3 (continues `NoteUpdate`): `drop_duplicate_tags()`, `reject_explicit_null()`; then `NoteRead` — A note as the API returns it.",
                ),
                (
                    "    id: int",
                    "Part 4 (continues `NoteRead`): `word_count()`; then `NoteFilters`, `FeedParams` — Query parameters of GET /notes: filtering, sorting and pagination.",
                ),
                (
                    "class LinkPreview(BaseModel):",
                    "Part 5: `LinkPreview`, `ImportReport`, `ScopeName`, `UserCreate`, `UserRead` — The title of one link found in a note's body (or why it could not be fetched).",
                ),
                (
                    "    id: int\n    email: str",
                    "Part 6 (continues `UserRead`): more fields; then `TokenPair`, `RefreshRequest`, `ApiKeyCreate`, `ApiKeyRead` — The OAuth 2.0 token response (RFC 6749 section 5.1) plus our refresh token.",
                ),
                (
                    "    id: int\n    name: str",
                    "Part 7 (continues `ApiKeyRead`): `split_scopes()`; then `ApiKeyCreated`, `WebhookSettings` — The response to creating a key: the only time the full key is shown.",
                ),
            ],
        ),
        md("`repositories.py` adds `add_event` to the protocol and the SQL repository:"),
        *writefile_cells(
            NOTES_V5_REPOSITORIES_PY,
            [
                (
                    "",
                    "Part 1 of `repositories.py`: the module docstring and imports, then `NoteRepository`.",
                ),
                (
                    "    async def feed(self, limit: int, after: CursorKey | None, owner_id: int) -> list[Note]:",
                    "Part 2 (continues `NoteRepository`): `feed()`, `update()`, `delete()`, `delete_all()`, ...; then `SqlNoteRepository` — NoteRepository on an AsyncSession: SQL filters, sorts and pages; tags always eager.",
                ),
                (
                    "    async def _tags(self, names: list[str]) -> list[Tag]:",
                    "Part 3 (continues `SqlNoteRepository`): `_tags()`, `_flush()`, `add()` — Tag rows for these names (sorted), creating missing ones; a savepoint absorbs a race.",
                ),
                (
                    '    async def get(self, note_id: int) -> Note | None:\n        """One note with its tags."""',
                    "Part 4 (continues `SqlNoteRepository`): `get()`, `search()`, `feed()` — One note with its tags.",
                ),
                (
                    '    async def update(self, note: Note, changes: dict[str, Any], now: datetime) -> Note:\n        """Change attributes; the flush sends UPDATE ... WHERE id = ? AND version = ?."""',
                    "Part 5 (continues `SqlNoteRepository`): `update()`, `delete()`, `delete_all()`, `add_event()`; then `UserRepository` — What the auth service needs from storage.",
                ),
                (
                    "    async def user_by_id(self, user_id: int) -> User | None:",
                    "Part 6 (continues `UserRepository`): `user_by_id()`, `user_by_email()`; then `SqlUserRepository` — Users, refresh tokens and API keys on the request's session.",
                ),
                (
                    "    async def add_refresh_token(self, token: RefreshToken) -> None:",
                    "Part 7 (continues `SqlUserRepository`): `add_refresh_token()`, `refresh_token_by_hash()`, `revoke_family()`, `add_api_key()`, ... — Store a refresh token row.",
                ),
            ],
        ),
        md(
            """
            `services.py`: `NoteService` records an outbox event on create, update and
            delete (same session, same transaction as the change) and `load_for_cache`
            returns the plain-JSON form the cache stores (with the owner, so authorization
            can still be checked on a cache hit):
            """
        ),
        *writefile_cells(
            NOTES_V5_SERVICES_PY,
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
                    "Part 4 (continues `NoteService`): `import_notes()`; then `parse_import()`, `resolve_host()`, `is_public_address()` — Notes from a .json list or a .csv file (title, body, tags separated by ';', pinned).",
                ),
                (
                    "class LinkPreviewer:",
                    "Part 5: `LinkPreviewer` — Fetch the <title> of links in a note, refusing anything that is not a public web URL.",
                ),
                (
                    "    async def preview(self, url: str) -> LinkPreview:",
                    "Part 6 (continues `LinkPreviewer`): `preview()`, `previews()` — One link: its status and title, or why it was not fetched (never raises).",
                ),
            ],
        ),
    ]


def _notes_v5_background_cells() -> list[NotebookNode]:
    """Notes API v5: events, mail, cache, exports, the worker, dependencies."""
    return [
        md(
            """
            **`events.py`** (new): outbox rows, the per-user Redis channel name, and webhook
            signatures in the `t=<unix time>,v1=<HMAC-SHA256>` format; `verify_webhook`
            is what a receiver runs (constant-time comparison, five-minute tolerance against
            replays):
            """
        ),
        *writefile_cells(
            NOTES_V5_EVENTS_PY,
            [
                (
                    "",
                    "Part 1 of `events.py`: the module docstring and imports, then `user_channel()`, `new_event()`, `event_message()`.",
                ),
                (
                    "def sign_webhook(secret: str, timestamp: int, body: bytes) -> str:",
                    "Part 2: `sign_webhook()`, `verify_webhook()` — 't=<unix time>,v1=<hex HMAC-SHA256 of \"t.body\">' (the scheme Stripe popularised).",
                ),
            ],
        ),
        md(
            "**`mailer.py`** (new): a `Mailer` protocol and a `LogMailer` (no SMTP in the course; tests use a fake):"
        ),
        code(NOTES_V5_MAILER_PY),
        md(
            """
            **`cache.py`** (new): cache-aside for single notes. Versioned keys
            (`notes:v5:note:{id}`), a TTL with ±10 % jitter so keys do not expire together,
            a per-key lock against stampedes (one loader, the others wait for its value),
            invalidation, and hit/miss counters in a Redis hash:
            """
        ),
        *writefile_cells(
            NOTES_V5_CACHE_PY,
            [
                (
                    "",
                    "Part 1 of `cache.py`: the module docstring and imports, then `note_key()`, `NoteCache`.",
                ),
                (
                    "    async def get_or_load(",
                    "Part 2 (continues `NoteCache`): `get_or_load()`, `invalidate()`, `stats()` — Cached value, or load it once (one loader per key at a time) and cache it.",
                ),
            ],
        ),
        md(
            """
            **`exports.py`** (new): export state in Redis. Progress events go to a **Redis
            Stream** per export; their stream ids become SSE `id:` fields, so a client that
            reconnects with `Last-Event-ID` resumes exactly where it stopped:
            """
        ),
        *writefile_cells(
            NOTES_V5_EXPORTS_PY,
            [
                (
                    "",
                    "Part 1 of `exports.py`: the module docstring and imports, then `owner_key()`, `events_key()`, `result_key()`, `add_progress()`.",
                ),
                (
                    "def format_sse(event_id: str, event: str, data: dict[str, object]) -> str:",
                    "Part 2: `format_sse()`, `progress_events()` — One text/event-stream message: id, event and data lines, then a blank line.",
                ),
            ],
        ),
        md(
            """
            **`worker.py`** (new): the ARQ worker. `relay_outbox` (cron every 10 s, and
            kicked after each write) takes a Redis lock, reads unpublished events with
            `FOR UPDATE SKIP LOCKED`, publishes them on the user's channel and enqueues one
            webhook job per event with `_job_id=webhook:<event id>` (enqueued at most once).
            `deliver_webhook` signs and posts, retries with exponential backoff
            (`Retry(defer=...)`) and dead-letters after the last attempt. `export_notes`
            reports progress; `purge_expired_tokens` runs nightly. `run_worker()` replaces
            the `arq` command, which does not start on Python 3.15:
            """
        ),
        *writefile_cells(
            NOTES_V5_WORKER_PY,
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
                    "Part 4: `deliver_webhook()` — POST one signed event; retry with exponential backoff; dead-letter after the last try.",
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
                    "async def run_worker(burst: bool = False, settings: Settings | None = None) -> None:",
                    "Part 7: `run_worker()` — Build the arq Worker inside a running event loop and run it (SIGTERM stops it cleanly).",
                ),
            ],
        ),
        md(
            """
            `dependencies.py`: settings and Redis now come from `HTTPConnection` (so
            WebSocket routes can use them), plus the queue, the mailer, the note cache and
            `kick_relay` (a best-effort background task):
            """
        ),
        *writefile_cells(
            NOTES_V5_DEPENDENCIES_PY,
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
                    "Part 6: `get_login_limiter()`, `LoginLimiterDep`, `get_oidc_client()`, `OidcClientDep`, `get_cookie_principal()`, ... — The login/registration rate limiter (shared by every worker through Redis).",
                ),
                (
                    "def get_mailer() -> Mailer:",
                    "Part 7: `get_mailer()`, `get_note_cache()`, `QueueDep`, `MailerDep`, `NoteCacheDep`, ... — Where emails go (tests override it with a fake that records messages).",
                ),
            ],
        ),
    ]


def _notes_v5_router_cells() -> list[NotebookNode]:
    """Notes API v5: routers and the app factory."""
    return [
        md(
            "`routers/auth.py`: registration sends the welcome e-mail in a `BackgroundTasks` task, after the response:"
        ),
        *writefile_cells(
            NOTES_V5_ROUTERS_AUTH_PY,
            [
                (
                    "",
                    "Part 1 of `routers/auth.py`: the module docstring and imports, then `client_ip()`, `enforce_limit()`.",
                ),
                (
                    '@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)',
                    "Part 2: `register()`, `login()`, `refresh()` — Create an account (rate limited); the welcome email goes out after the response.",
                ),
                (
                    '@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)',
                    "Part 3: `logout()`, `oauth_login()`, `oauth_callback()` — Revoke the refresh-token family; also deny the access token sent, if any.",
                ),
            ],
        ),
        md(
            "`routers/users.py`: webhook settings (`GET/PUT/DELETE /users/me/webhook`); the URL passes the same SSRF check as link previews, and the signing secret is shown once:"
        ),
        *writefile_cells(
            NOTES_V5_ROUTERS_USERS_PY,
            [
                (
                    "",
                    "Part 1 of `routers/users.py`: the module docstring and imports, then `me()`, `create_api_key()`.",
                ),
                (
                    '@router.get("/me/api-keys", response_model=list[ApiKeyRead])',
                    "Part 2: `list_api_keys()`, `revoke_api_key()`, `get_webhook()` — The caller's keys, without their secrets.",
                ),
                (
                    '@router.put("/me/webhook")',
                    "Part 3: `set_webhook()`, `delete_webhook()` — Register a public HTTPS/HTTP URL; returns a new signing secret, once.",
                ),
            ],
        ),
        md(
            """
            **`routers/notes.py`**: `GET /notes/{id}` goes through the cache, sends a strong
            `ETag` (`"<id>-<version>"`) with `Cache-Control: private, no-cache`, and answers
            **304** to a matching `If-None-Match`; authorization is checked *after* the cache
            lookup, so a cached note is never served to someone else. Writes invalidate the
            cache immediately and once more after the commit (a background task), then kick
            the relay; lists are `no-store`:
            """
        ),
        *writefile_cells(
            NOTES_V5_ROUTERS_NOTES_PY,
            [
                (
                    "",
                    "Part 1 of `routers/notes.py`: the module docstring and imports, then `etag_of()`.",
                ),
                (
                    "def matches(if_none_match: str | None, etag: str) -> bool:",
                    "Part 2: `matches()`, `after_write()`, `create_note()` — True if the client's If-None-Match lists this ETag (or '*').",
                ),
                (
                    '@router.get("", response_model=Page[NoteRead])',
                    "Part 3: `list_notes()`, `notes_feed()` — Search, filter, sort and paginate notes (offset pagination).",
                ),
                (
                    '@router.get(\n    "/{note_id}",',
                    "Part 4: `get_note()` — Fetch one note through the cache; 304 when the client's copy is current.",
                ),
                (
                    '@router.put("/{note_id}", response_model=NoteRead, responses=NOT_FOUND)',
                    "Part 5: `replace_note()`, `update_note()` — Replace every field of a note (omitted fields get their defaults).",
                ),
                (
                    '@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND)',
                    "Part 6: `delete_note()`, `note_links()` — Delete a note.",
                ),
            ],
        ),
        md(
            "`routers/admin.py`: cache statistics, the webhook dead-letter list and a retry endpoint:"
        ),
        *writefile_cells(
            NOTES_V5_ROUTERS_ADMIN_PY,
            [
                ("", "Part 1 of `routers/admin.py`: the module docstring and imports."),
                (
                    "async def read_upload(upload: UploadFile, max_bytes: int) -> bytes:",
                    "Part 2: `read_upload()`, `import_notes()`, `export_notes()` — The file's bytes after checking its extension, content type and size.",
                ),
                (
                    '@router.delete("/notes")',
                    "Part 3: `delete_all_notes()`, `cache_stats()`, `dead_webhooks()` — Remove every note of every user.",
                ),
                (
                    '@router.post("/webhooks/dead/{event_id}/retry", status_code=status.HTTP_202_ACCEPTED)',
                    "Part 4: `retry_dead_webhook()` — Send a dead-lettered event again (after the receiver was fixed).",
                ),
            ],
        ),
        md(
            """
            **`routers/exports.py`** (new): `POST /exports` answers **202 Accepted** with a
            `Location`, the job runs in the worker; `GET /exports/{id}` is the status,
            `/download` the result, and `/events` streams progress as **Server-Sent Events**
            (resuming from `Last-Event-ID`):
            """
        ),
        *writefile_cells(
            NOTES_V5_ROUTERS_EXPORTS_PY,
            [
                (
                    "",
                    "Part 1 of `routers/exports.py`: the module docstring and imports, then `check_owner()`.",
                ),
                (
                    '@router.post("", status_code=status.HTTP_202_ACCEPTED)',
                    "Part 2: `start_export()`, `export_status()` — Queue an export of all the caller's notes; 202 Accepted with where to look.",
                ),
                (
                    '@router.get("/{export_id}/download")',
                    "Part 3: `download_export()`, `export_events()` — The finished export as a JSON file (404 until it is ready).",
                ),
            ],
        ),
        md(
            """
            **`routers/realtime.py`** (new): `WS /api/v1/ws`. The browser cannot set an
            `Authorization` header on a WebSocket, so the first message must be
            `{"token": "<access token>"}` (close code 1008 otherwise). Events arrive through
            Redis pub/sub, so every API process can push to its own sockets; the server pings
            every `ws_heartbeat_seconds`:
            """
        ),
        *writefile_cells(
            NOTES_V5_ROUTERS_REALTIME_PY,
            [
                (
                    "",
                    "Part 1 of `routers/realtime.py`: the module docstring and imports, then `ConnectionManager`.",
                ),
                (
                    "    def remove(self, user_id: int, websocket: WebSocket) -> None:",
                    "Part 2 (continues `ConnectionManager`): `remove()`, `count()`; then `authenticate()`, `forward_events()` — Check the access token sent as the first message, with a short-lived DB session.",
                ),
                (
                    "async def read_client(websocket: WebSocket) -> None:",
                    "Part 3: `read_client()` — Client → server: answer pings; any other message is ignored. Ends on disconnect.",
                ),
                (
                    '@router.websocket("/ws")',
                    'Part 4: `live_updates()` — Accept, authenticate with the first message ({"token": ...}), then stream events.',
                ),
            ],
        ),
        md(
            "`main.py`: the exports and realtime routers, and a `ConnectionManager` on `app.state`:"
        ),
        *writefile_cells(
            NOTES_V5_MAIN_PY,
            [
                ("", "Part 1 of `main.py`: the module docstring and imports."),
                (
                    "def operation_id(route: APIRoute) -> str:",
                    "Part 2: `operation_id()`, `install_middleware()`, `install_security()` — Use the function name as the OpenAPI operationId (clean names in generated clients).",
                ),
                ("OPENAPI_TAGS = [", "Part 3: `OPENAPI_TAGS`."),
                (
                    "def create_app(settings: Settings | None = None) -> FastAPI:",
                    "Part 4: `create_app()`, `app` — Build a fully wired app; tests pass their own Settings, servers use the environment.",
                ),
            ],
        ),
    ]


def _notes_v5_test_cells() -> list[NotebookNode]:
    """Notes API v5: the test suite."""
    return [
        md(
            """
            **Tests.** `conftest.py`: one `FakeServer` shared by the text client and an
            `ArqRedis` on fakeredis, so tests can enqueue jobs and inspect the queue; a
            `FakeMailer` records e-mails:
            """
        ),
        *writefile_cells(
            NOTES_V5_TESTS_CONFTEST_PY,
            [
                (
                    "",
                    "Part 1 of `tests/conftest.py`: the module docstring and imports, then `anyio_backend()`.",
                ),
                (
                    "@pytest.fixture\ndef settings(tmp_path: Path) -> Settings:",
                    "Part 2: `settings()`, `redis_server()`, `fake_redis()`, `fake_queue()` — Test settings: a fresh SQLite file, a generated JWT secret, cheap Argon2 parameters.",
                ),
                (
                    "@pytest.fixture\ndef mailer() -> FakeMailer:",
                    "Part 3: `mailer()`, `app()`, `anonymous()`, `client()` — Records emails instead of sending them.",
                ),
                (
                    "@pytest.fixture\ndef admin_headers(anonymous: TestClient) -> dict[str, str]:",
                    "Part 4: `admin_headers()` — Bearer headers of an admin (admin@example.com is in admin_emails).",
                ),
            ],
        ),
        md(
            "`helpers.py`: the fake mailer and a DNS entry for the webhook receiver `hooks.example`:"
        ),
        *writefile_cells(
            NOTES_V5_TESTS_HELPERS_PY,
            [
                (
                    "",
                    "Part 1 of `tests/helpers.py`: the module docstring and imports, then `create()`, `ids()`.",
                ),
                (
                    "def register(client: TestClient, email: str, password: str = PASSWORD) -> Any:",
                    "Part 2: `register()`, `login()`, `auth_headers()`, `fake_resolver()` — POST /auth/register (without the client's default credentials).",
                ),
                (
                    "async def create_tables(settings: Settings) -> None:",
                    "Part 3: `create_tables()`, `FakeMailer` — CREATE TABLE for every model (fast; the PostgreSQL tests run the Alembic migrations).",
                ),
            ],
        ),
        md(
            "**`test_background.py`** (new): background tasks after the response, and webhook signature checks:"
        ),
        code(NOTES_V5_TESTS_TEST_BACKGROUND_PY),
        md(
            """
            **`test_worker.py`** (new): the ARQ tasks called directly with a fake context:
            outbox rows only for committed writes, the relay publishing and enqueuing once,
            signed delivery, retries with backoff then a dead letter, the relay lock and the
            nightly purge:
            """
        ),
        *writefile_cells(
            NOTES_V5_TESTS_TEST_WORKER_PY,
            [
                ("", "Part 1 of `tests/test_worker.py`: the module docstring and imports."),
                (
                    "@pytest.fixture",
                    "Part 2: `ctx()`, `run()`, `with_webhook()` — What WorkerSettings.on_startup builds, but on the test database and fake Redis.",
                ),
                (
                    "async def events(ctx: dict[str, Any]) -> list[OutboxEvent]:",
                    "Part 3: `events()`, `test_writes_create_outbox_events()`, `test_a_failed_write_leaves_no_event()` — Every outbox row.",
                ),
                (
                    "@respx.mock",
                    "Part 4: `test_relay_publishes_and_queues_webhooks()` — Each event goes to the user's Redis channel once; webhook jobs are queued by event id.",
                ),
                (
                    "@respx.mock\ndef test_webhook_is_signed_and_delivered_once(client: TestClient, ctx: dict[str, Any]) -> None:",
                    "Part 5: `test_webhook_is_signed_and_delivered_once()` — The receiver can verify the signature; a duplicate job does not send twice.",
                ),
                (
                    "@respx.mock\ndef test_failing_webhook_retries_then_dead_letters(",
                    "Part 6: `test_failing_webhook_retries_then_dead_letters()` — Failures raise Retry with growing delays; the last try marks the event dead.",
                ),
                (
                    "def test_relay_lock_prevents_overlap(",
                    "Part 7: `test_relay_lock_prevents_overlap()`, `test_purge_expired_tokens()`, `test_webhook_url_must_be_public()` — While another relay holds the lock, a second one does nothing.",
                ),
            ],
        ),
        md("**`test_realtime.py`** (new): WebSocket authentication, Redis fan-out, heartbeats:"),
        *writefile_cells(
            NOTES_V5_TESTS_TEST_REALTIME_PY,
            [
                (
                    "",
                    "Part 1 of `tests/test_realtime.py`: the module docstring and imports, then `token_of()`, `test_socket_needs_a_valid_token()`.",
                ),
                (
                    "def test_events_published_in_redis_reach_the_socket(",
                    "Part 2: `test_events_published_in_redis_reach_the_socket()`, `test_heartbeat_pings()` — Whatever process publishes on the user's channel, the socket forwards it.",
                ),
            ],
        ),
        md("**`test_exports.py`** (new): the export job, SSE progress with resume, and ownership:"),
        *writefile_cells(
            NOTES_V5_TESTS_TEST_EXPORTS_PY,
            [
                (
                    "",
                    "Part 1 of `tests/test_exports.py`: the module docstring and imports, then `started()`.",
                ),
                (
                    "def run_job(",
                    "Part 2: `run_job()`, `sse_messages()` — What the worker would do with the queued job.",
                ),
                (
                    "def test_export_job_is_queued(",
                    "Part 3: `test_export_job_is_queued()` — The API only records the request and queues the work.",
                ),
                (
                    "def test_progress_streams_as_sse_and_resumes(",
                    "Part 4: `test_progress_streams_as_sse_and_resumes()`, `test_other_users_cannot_see_an_export()` — Every progress event arrives once with an id; Last-Event-ID resumes after it.",
                ),
            ],
        ),
        md(
            "**`test_caching.py`** (new): ETag/304, cache hits and misses, authorization on cache hits, the stampede lock:"
        ),
        *writefile_cells(
            NOTES_V5_TESTS_TEST_CACHING_PY,
            [
                (
                    "",
                    "Part 1 of `tests/test_caching.py`: the module docstring and imports, then `test_etag_and_304()`.",
                ),
                (
                    "def test_cache_hits_misses_and_invalidation(",
                    "Part 2: `test_cache_hits_misses_and_invalidation()`, `test_cached_notes_are_still_authorized()`, `test_lists_are_not_stored()` — The first read misses, later reads hit; an update invalidates the cached copy.",
                ),
                (
                    "def test_stampede_lock_loads_once(client: TestClient, fake_redis: fakeredis.FakeAsyncRedis) -> None:",
                    "Part 3: `test_stampede_lock_loads_once()` — Ten concurrent misses on one key run the loader once; the rest wait for its result.",
                ),
            ],
        ),
        md("`test_migrations.py`: the outbox table exists after `upgrade head`:"),
        *writefile_cells(
            NOTES_V5_TESTS_TEST_MIGRATIONS_PY,
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
                    "Part 4: `test_existing_notes_get_a_disabled_legacy_owner()` — 0004 gives notes written before accounts existed to an owner that cannot log in.",
                ),
            ],
        ),
        md(
            """
            **`test_redis_worker.py`** (new, marker `redis`): the whole path on a **real
            Redis** in a testcontainer and the **real ARQ worker** in burst mode: a write
            kicks the relay, the relay queues the webhook, the worker signs and delivers it
            to a respx-mocked receiver:
            """
        ),
        *writefile_cells(
            NOTES_V5_TESTS_TEST_REDIS_WORKER_PY,
            [
                (
                    "",
                    "Part 1 of `tests/test_redis_worker.py`: the module docstring and imports, then `redis_url()`.",
                ),
                (
                    "@pytest.fixture\ndef real_settings(settings: Settings, redis_url: str) -> Settings:",
                    "Part 2: `real_settings()`, `burst()`, `test_write_kick_relay_and_signed_webhook()` — The test settings, but with the real Redis.",
                ),
            ],
        ),
    ]


NOTES_V5_PYPROJECT_TOML = r"""
%%writefile ../projects/notes_api/pyproject.toml
[project]
name = "notes-api"
version = "0.5.0"
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
]

[dependency-groups]
dev = [
    "aiosqlite>=0.22.1",
    "fakeredis>=2.40.0",
    "pytest>=9.2.0",
    "respx>=0.23.1",
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

NOTES_V5_ENV_EXAMPLE = r"""
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
# Accounts registered with these addresses become admins (JSON list).
NOTES_ADMIN_EMAILS=[]
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
"""

NOTES_V5_README_MD = r"""
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
docker compose down                           # add -v to delete the data volume
```

Local plain HTTP: set `NOTES_COOKIE_SECURE=false`, or the browser will not send the session
cookie. Register `NOTES_ADMIN_EMAILS` addresses to get admin accounts.


## Endpoints

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| `GET` | `/health`, `/health/ready` | none | liveness; readiness runs `SELECT 1` |
| `POST` | `/api/v1/auth/register` | none | 201; rate limited; never accepts a role |
| `POST` | `/api/v1/auth/token` | none | OAuth2 password form (`username` = email, optional `scope`); rate limited (429 + `Retry-After`) |
| `POST` | `/api/v1/auth/refresh` | refresh token | rotation: each refresh token works once; reuse revokes the family |
| `POST` | `/api/v1/auth/logout` | refresh token (+ bearer) | revokes the family and denies the access token |
| `GET` | `/api/v1/auth/oauth/login`, `/oauth/callback` | none | OpenID Connect (Authorization Code + PKCE); 404 unless configured |
| `GET` | `/api/v1/users/me` | bearer or key | the current user |
| `POST/GET/DELETE` | `/api/v1/users/me/api-keys[/{id}]` | bearer | keys are shown once, stored as SHA-256, limited to scopes |
| `POST/GET` | `/api/v1/notes` | `notes:write` / `notes:read` | only the caller's notes |
| `GET` | `/api/v1/notes/feed` | `notes:read` | keyset pagination |
| `GET/PUT/PATCH/DELETE` | `/api/v1/notes/{note_id}` | `notes:read` / `notes:write` | someone else's note is a 404; PATCH `version` → 409 if stale |
| `GET` | `/api/v1/notes/{note_id}/links` | `notes:read` | link titles; private addresses are never fetched |
| `GET/PUT/DELETE` | `/api/v1/users/me/webhook` | bearer | a public URL; PUT returns the signing secret once |
| `POST` | `/api/v1/exports` | any user | 202 + `Location`; an ARQ job builds the export |
| `GET` | `/api/v1/exports/{id}`, `/download`, `/events` | owner | status, JSON file, `text/event-stream` progress (`Last-Event-ID`) |
| `WS` | `/api/v1/ws` | first message `{"token": ...}` | live note events; server pings; 1008 on bad auth |
| `POST/GET/DELETE` | `/api/v1/admin/import`, `/export`, `/notes` | admin role + `admin` scope | bulk operations |
| `GET/POST` | `/api/v1/admin/cache-stats`, `/webhooks/dead[/{id}/retry]` | admin | cache hit rate; dead-letter list and replay |
| `GET/POST` | `/login`, `/logout`, `/`, `/notes`, `/notes/{id}/pin` | session cookie + CSRF token | HTML (Jinja2 + HTMX) |

Credentials: `Authorization: Bearer <access token>` or `X-API-Key: nk_...`. Errors are
`application/problem+json` (RFC 9457). Every response carries `X-Request-ID`,
`Server-Timing` and security headers (HSTS, CSP, `X-Content-Type-Options`, `X-Frame-Options`).
`GET /api/v1/notes/{id}` sends `ETag` and `Cache-Control: private, no-cache` and answers
`If-None-Match` with 304. Webhooks carry `X-Notes-Event-Id` and
`X-Notes-Signature: t=<unix time>,v1=<HMAC-SHA256 of "t.body">`.


## Layout

```text
src/notes_api/
├── main.py           # create_app(): settings, security, handlers, middleware, routers
├── core/             # config.py, errors.py, middleware.py, lifespan.py, logging.py (redaction)
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
tests/                # pytest: one app, SQLite file and fakeredis per test;
                      # test_postgres.py / test_redis_worker.py use testcontainers
```

Dependencies point inwards: routers → services → repositories → models. Nothing in
`services.py`, `auth.py`, `security.py`, `repositories.py`, `models.py`, `db.py` or
`exceptions.py` imports FastAPI; `core/errors.py` maps domain exceptions to HTTP responses.
"""

NOTES_V5_INIT_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/__init__.py
"""Notes API: a FastAPI service built step by step in Phase 6 of the course."""

__version__ = "0.5.0"
'''

NOTES_V5_CORE_CONFIG_PY = r'''
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
    admin_emails: list[str] = []  # these addresses get the admin role when they register
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
    export_ttl_seconds: int = Field(default=3600, ge=60)

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

NOTES_V5_EXCEPTIONS_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/exceptions.py
"""Domain exceptions: plain Python, no FastAPI (core/errors.py maps them to HTTP)."""

from http import HTTPStatus


class DomainError(Exception):
    """A business rule failed. Subclasses choose the status, a problem type and a title."""

    status_code: int = HTTPStatus.BAD_REQUEST
    problem_type: str = "domain-error"
    title: str = "Request breaks a business rule"
    headers: dict[str, str] = {}


class NoteNotFoundError(DomainError, LookupError):
    """No note has the requested id."""

    status_code = HTTPStatus.NOT_FOUND
    problem_type = "note-not-found"
    title = "Note not found"

    def __init__(self, note_id: int) -> None:
        """Remember the id; the message becomes the problem's detail."""
        super().__init__(f"note {note_id} not found")
        self.note_id = note_id


class VersionConflictError(DomainError):
    """Optimistic locking: the note changed since the client (or this request) read it."""

    status_code = HTTPStatus.CONFLICT
    problem_type = "version-conflict"
    title = "Version conflict"

    def __init__(
        self, note_id: int, expected: int | None = None, actual: int | None = None
    ) -> None:
        """Explain which versions clashed when they are known."""
        if expected is None or actual is None:
            message = f"note {note_id} was changed by another request; read it again"
        else:
            message = f"note {note_id} is at version {actual}, not {expected}; read it again"
        super().__init__(message)
        self.note_id = note_id


class InvalidCursorError(DomainError, ValueError):
    """A pagination cursor that this API did not issue."""

    problem_type = "invalid-cursor"
    title = "Invalid cursor"


class UploadRejectedError(DomainError):
    """An uploaded file was too large, of the wrong type, or unreadable."""

    problem_type = "upload-rejected"
    title = "Upload rejected"

    def __init__(self, detail: str, status_code: int) -> None:
        """Keep the reason and the status (413, 415 or 422)."""
        super().__init__(detail)
        self.status_code = status_code


class AuthenticationError(DomainError):
    """Missing, invalid, expired or revoked credentials (401)."""

    status_code = HTTPStatus.UNAUTHORIZED
    problem_type = "not-authenticated"
    title = "Authentication required"

    def __init__(self, detail: str, scopes: list[str] | None = None) -> None:
        """Keep the reason; the WWW-Authenticate header tells clients how to authenticate."""
        super().__init__(detail)
        challenge = "Bearer"
        if scopes:
            challenge += f' scope="{" ".join(scopes)}"'
        self.headers = {"WWW-Authenticate": challenge}


class PermissionDeniedError(DomainError):
    """Authenticated, but not allowed to do this (403)."""

    status_code = HTTPStatus.FORBIDDEN
    problem_type = "forbidden"
    title = "Not allowed"


class EmailTakenError(DomainError):
    """Registration with an email that already has an account (409)."""

    status_code = HTTPStatus.CONFLICT
    problem_type = "email-taken"
    title = "Email already registered"


class RateLimitedError(DomainError):
    """Too many attempts; Retry-After says when to try again (429)."""

    status_code = HTTPStatus.TOO_MANY_REQUESTS
    problem_type = "rate-limited"
    title = "Too many requests"

    def __init__(self, retry_after: int) -> None:
        """Remember how many seconds the client must wait."""
        super().__init__(f"too many attempts; retry in {retry_after} s")
        self.retry_after = retry_after
        self.headers = {"Retry-After": str(retry_after)}


class ApiKeyNotFoundError(DomainError, LookupError):
    """The caller has no API key with this id (someone else's key is 'not found' too)."""

    status_code = HTTPStatus.NOT_FOUND
    problem_type = "api-key-not-found"
    title = "API key not found"

    def __init__(self, key_id: int) -> None:
        """Remember the id."""
        super().__init__(f"API key {key_id} not found")
        self.key_id = key_id


class ExportNotFoundError(DomainError, LookupError):
    """No export with this id for the caller (or it expired)."""

    status_code = HTTPStatus.NOT_FOUND
    problem_type = "export-not-found"
    title = "Export not found"

    def __init__(self, export_id: str) -> None:
        """Remember the id."""
        super().__init__(f"export {export_id} not found")
        self.export_id = export_id


class InvalidWebhookError(DomainError, ValueError):
    """A webhook URL the server will not call (not public http(s))."""

    status_code = HTTPStatus.UNPROCESSABLE_CONTENT
    problem_type = "invalid-webhook"
    title = "Webhook URL refused"
'''

NOTES_V5_CORE_LIFESPAN_PY = r'''
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
        async with httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            follow_redirects=False,  # a redirect could lead a server-side fetch somewhere private
            headers={"User-Agent": f"notes-api/{__version__}"},
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        ) as http_client:
            app.state.http_client = http_client
            yield
    finally:
        await app.state.queue.aclose()
        await app.state.redis.aclose()
        await engine.dispose()  # close every pooled database connection
'''

NOTES_V5_MODELS_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/models.py
"""SQLAlchemy 2.0 typed models: users, their notes and tags, refresh tokens and API keys."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, ForeignKey, Index, String, Table, Text, false, func, text, true
from sqlalchemy.ext.associationproxy import AssociationProxy, association_proxy
from sqlalchemy.orm import Mapped, mapped_column, relationship

from notes_api.db import Base


def utc_now() -> datetime:
    """The current time in UTC (the default clock)."""
    return datetime.now(UTC)


class TimestampMixin:
    """created_at / updated_at for any model (the service sets them; the server has defaults)."""

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


note_tags = Table(
    "note_tags",
    Base.metadata,
    Column("note_id", ForeignKey("notes.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class User(TimestampMixin, Base):
    """An account. password_hash is None for users who only sign in with a third party."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), server_default="user")
    is_active: Mapped[bool] = mapped_column(server_default=true())
    oidc_subject: Mapped[str | None] = mapped_column(String(255), unique=True)  # "issuer|sub"
    webhook_url: Mapped[str | None] = mapped_column(String(500))
    webhook_secret: Mapped[str | None] = mapped_column(String(64))  # needed to sign: not hashed

    def __repr__(self) -> str:
        """Never show the hash."""
        return f"User(id={self.id!r}, email={self.email!r}, role={self.role!r})"


class RefreshToken(Base):
    """One opaque refresh token (only its SHA-256 is stored); a family shares one login."""

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    scopes: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]  # set when it was exchanged (rotation)
    revoked_at: Mapped[datetime | None]  # set at logout or when reuse was detected


class ApiKey(TimestampMixin, Base):
    """A personal API key: shown once, stored as a SHA-256, limited to some scopes."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    prefix: Mapped[str] = mapped_column(String(16))  # shown in lists, so users can tell keys apart
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[str] = mapped_column(String(200))
    last_used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]


class OutboxEvent(Base):
    """A domain event written in the same transaction as the change (transactional outbox).

    The relay worker publishes it (Redis pub/sub) and hands webhooks to the queue; webhook
    attempts are counted here, and an event that keeps failing ends up 'dead'.
    """

    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_events_published_at_id", "published_at", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[str] = mapped_column(Text)  # JSON
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    published_at: Mapped[datetime | None]  # set by the relay
    webhook_status: Mapped[str] = mapped_column(String(20), server_default="none")
    webhook_attempts: Mapped[int] = mapped_column(server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)


class Tag(Base):
    """A tag name, stored once and shared by many notes."""

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(30), unique=True)


class Note(TimestampMixin, Base):
    """A note; tags is a list of names backed by the many-to-many tag_objects relationship."""

    __tablename__ = "notes"
    __table_args__ = (
        Index("ix_notes_created_at_id", "created_at", "id"),  # keyset pagination
        Index(  # trigram indexes make ILIKE '%text%' searches fast on PostgreSQL
            "ix_notes_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index(
            "ix_notes_body_trgm",
            "body",
            postgresql_using="gin",
            postgresql_ops={"body": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, server_default="")
    pinned: Mapped[bool] = mapped_column(server_default=false())
    version: Mapped[int] = mapped_column(server_default=text("1"))
    tag_objects: Mapped[list[Tag]] = relationship(
        secondary=note_tags, order_by=Tag.name, lazy="raise"
    )
    tags: AssociationProxy[list[str]] = association_proxy("tag_objects", "name")

    __mapper_args__: dict[str, Any] = {"version_id_col": version}  # UPDATE ... WHERE version = ?

    def __repr__(self) -> str:
        """Short form for logs and notebooks."""
        return f"Note(id={self.id!r}, title={self.title!r}, version={self.version!r})"
'''

NOTES_V5_ALEMBIC_VERSIONS_0006_OUTBOX_AND_WEBHOOKS_PY = r'''
%%writefile ../projects/notes_api/alembic/versions/0006_outbox_and_webhooks.py
"""Add the transactional outbox and per-user webhook settings.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Two nullable user columns and the outbox table."""
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("webhook_url", sa.String(length=500), nullable=True))
        batch.add_column(sa.Column("webhook_secret", sa.String(length=64), nullable=True))
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("webhook_status", sa.String(length=20), server_default="none", nullable=False),
        sa.Column("webhook_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_outbox_events_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_events")),
    )
    op.create_index(op.f("ix_outbox_events_user_id"), "outbox_events", ["user_id"])
    op.create_index("ix_outbox_events_published_at_id", "outbox_events", ["published_at", "id"])


def downgrade() -> None:
    """Drop the outbox and the webhook columns."""
    op.drop_index("ix_outbox_events_published_at_id", table_name="outbox_events")
    op.drop_index(op.f("ix_outbox_events_user_id"), table_name="outbox_events")
    op.drop_table("outbox_events")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("webhook_secret")
        batch.drop_column("webhook_url")
'''

NOTES_V5_SCHEMAS_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/schemas.py
"""Request and response schemas for the Notes API (Pydantic v2).

One schema per direction: NoteCreate (POST/PUT body), NoteUpdate (PATCH body, every field
optional), NoteRead (responses, with server-owned fields) and NoteFilters (query parameters).
Page envelopes live in pagination.py, error bodies in core/errors.py.
"""

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    HttpUrl,
    StringConstraints,
    computed_field,
    field_validator,
    model_validator,
)

MAX_TAGS = 10


def require_slug(value: str) -> str:
    """Allow lowercase letters, digits and dashes (checked after stripping and lower-casing)."""
    if not re.fullmatch(r"[a-z0-9-]+", value):
        raise ValueError("tags use lowercase letters, digits and dashes")
    return value


def unique_in_order(tags: list[str]) -> list[str]:
    """Drop repeated tags, keeping the first occurrence."""
    return list(dict.fromkeys(tags))


Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Body = Annotated[str, Field(max_length=10_000)]
Tag = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True, min_length=1, max_length=30),
    AfterValidator(require_slug),
]
Tags = Annotated[list[Tag], Field(max_length=MAX_TAGS)]
SortOrder = Literal["created_at", "-created_at", "updated_at", "-updated_at", "title", "-title"]


class NoteCreate(BaseModel):
    """Body of POST /notes and PUT /notes/{note_id}: every field a client may set."""

    model_config = ConfigDict(
        extra="forbid",
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
        extra="forbid", json_schema_extra={"examples": [{"pinned": True, "version": 1}]}
    )

    title: Title | None = None
    body: Body | None = None
    tags: Tags | None = None
    pinned: bool | None = None
    version: Annotated[
        int | None, Field(ge=1, description="The version you read; a mismatch is a 409.")
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
    offset: Annotated[int, Field(ge=0)] = 0


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

NOTES_V5_REPOSITORIES_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/repositories.py
"""Storage behind Protocols: services depend on NoteRepository / UserRepository, not on SQL.

Unit 6.3 shipped an in-memory note repository; Unit 6.4 replaced it with SqlNoteRepository;
Unit 6.5 scopes notes to their owner and adds SqlUserRepository (users, refresh tokens, keys).
"""

from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import Select, delete, func, or_, select, tuple_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.exc import StaleDataError

from notes_api.exceptions import VersionConflictError
from notes_api.models import ApiKey, Note, OutboxEvent, RefreshToken, Tag, User
from notes_api.pagination import CursorKey
from notes_api.schemas import NoteCreate, NoteFilters


class NoteRepository(Protocol):
    """What the service needs from storage."""

    async def add(self, data: NoteCreate, now: datetime, owner_id: int) -> Note:
        """Store a new note for owner_id and return it with its id."""
        ...

    async def get(self, note_id: int) -> Note | None:
        """The note with this id, or None."""
        ...

    async def search(self, filters: NoteFilters, owner_id: int | None) -> tuple[list[Note], int]:
        """One page of matching notes (of owner_id, or everyone's when None) and the total."""
        ...

    async def feed(self, limit: int, after: CursorKey | None, owner_id: int) -> list[Note]:
        """Up to limit of owner_id's notes, newest first, strictly older than the key after."""
        ...

    async def update(self, note: Note, changes: dict[str, Any], now: datetime) -> Note:
        """Apply field changes (tags as a list of names), stamp updated_at, return the note."""
        ...

    async def delete(self, note: Note) -> None:
        """Remove a note returned by this repository."""
        ...

    async def delete_all(self) -> int:
        """Remove every note; return how many there were."""
        ...

    async def add_event(self, event: OutboxEvent) -> None:
        """Store an outbox event in the current transaction."""
        ...


class SqlNoteRepository:
    """NoteRepository on an AsyncSession: SQL filters, sorts and pages; tags always eager."""

    def __init__(self, session: AsyncSession) -> None:
        """Work inside the request's session (and so its transaction)."""
        self.session = session

    @staticmethod
    def _select() -> Select[tuple[Note]]:
        """SELECT notes plus one extra query for all their tags (no N+1, no lazy loads)."""
        return select(Note).options(selectinload(Note.tag_objects))

    async def _tags(self, names: list[str]) -> list[Tag]:
        """Tag rows for these names (sorted), creating missing ones; a savepoint absorbs a race."""
        if not names:
            return []
        found = await self.session.scalars(select(Tag).where(Tag.name.in_(names)))
        by_name = {tag.name: tag for tag in found}
        for name in names:
            if name in by_name:
                continue
            try:
                async with self.session.begin_nested():  # SAVEPOINT
                    tag = Tag(name=name)
                    self.session.add(tag)
                by_name[name] = tag
            except IntegrityError:  # another transaction inserted it first: use theirs
                by_name[name] = await self.session.scalar(select(Tag).where(Tag.name == name))
        return sorted((by_name[name] for name in names), key=lambda tag: tag.name)

    async def _flush(self, note: Note) -> None:
        """Send pending changes; a version mismatch becomes a domain conflict."""
        note_id = note.id  # read it now: after a failed flush the session needs a rollback
        try:
            await self.session.flush()
        except StaleDataError as error:
            raise VersionConflictError(note_id) from error

    async def add(self, data: NoteCreate, now: datetime, owner_id: int) -> Note:
        """INSERT the note and its tag links; flush so the id is known."""
        fields = data.model_dump(exclude={"tags"})
        note = Note(**fields, owner_id=owner_id, created_at=now, updated_at=now)
        note.tag_objects = await self._tags(data.tags)
        self.session.add(note)
        await self.session.flush()
        return note

    async def get(self, note_id: int) -> Note | None:
        """One note with its tags."""
        return await self.session.scalar(self._select().where(Note.id == note_id))

    async def search(self, filters: NoteFilters, owner_id: int | None) -> tuple[list[Note], int]:
        """WHERE for the filters, COUNT for the total, ORDER BY + LIMIT/OFFSET for the page."""
        conditions = [Note.tag_objects.any(Tag.name == name) for name in filters.tag]
        if owner_id is not None:
            conditions.append(Note.owner_id == owner_id)
        if filters.pinned is not None:
            conditions.append(Note.pinned == filters.pinned)
        if filters.q:
            conditions.append(
                or_(
                    Note.title.icontains(filters.q, autoescape=True),
                    Note.body.icontains(filters.q, autoescape=True),
                )
            )
        total = await self.session.scalar(select(func.count(Note.id)).where(*conditions))
        field_name = filters.sort.removeprefix("-")
        column = func.lower(Note.title) if field_name == "title" else getattr(Note, field_name)
        if filters.sort.startswith("-"):
            order = [column.desc(), Note.id.desc()]
        else:
            order = [column.asc(), Note.id.asc()]
        page = self._select().where(*conditions).order_by(*order)
        notes = await self.session.scalars(page.offset(filters.offset).limit(filters.limit))
        return list(notes), total or 0

    async def feed(self, limit: int, after: CursorKey | None, owner_id: int) -> list[Note]:
        """Keyset page: WHERE (created_at, id) < (:created_at, :id) on an index, no OFFSET."""
        statement = self._select().where(Note.owner_id == owner_id)
        statement = statement.order_by(Note.created_at.desc(), Note.id.desc())
        if after is not None:
            statement = statement.where(tuple_(Note.created_at, Note.id) < tuple_(*after))
        return list(await self.session.scalars(statement.limit(limit)))

    async def update(self, note: Note, changes: dict[str, Any], now: datetime) -> Note:
        """Change attributes; the flush sends UPDATE ... WHERE id = ? AND version = ?."""
        changes = dict(changes)
        tag_names = changes.pop("tags", None)
        for name, value in changes.items():
            setattr(note, name, value)
        if tag_names is not None:
            note.tag_objects = await self._tags(tag_names)
        note.updated_at = now
        await self._flush(note)
        return note

    async def delete(self, note: Note) -> None:
        """DELETE the note (its tag links go by ON DELETE CASCADE)."""
        await self.session.delete(note)
        await self._flush(note)

    async def delete_all(self) -> int:
        """Bulk DELETE statements: every note, then every tag."""
        result = await self.session.execute(delete(Note))
        await self.session.execute(delete(Tag))
        return result.rowcount

    async def add_event(self, event: OutboxEvent) -> None:
        """Same session, same transaction: the event exists if and only if the change does."""
        self.session.add(event)
        await self.session.flush()


class UserRepository(Protocol):
    """What the auth service needs from storage."""

    async def add_user(self, email: str, password_hash: str | None, role: str) -> User:
        """Store a new user (IntegrityError if the email exists)."""
        ...

    async def user_by_id(self, user_id: int) -> User | None:
        """The user, or None."""
        ...

    async def user_by_email(self, email: str) -> User | None:
        """The user with this email (case-insensitive), or None."""
        ...


class SqlUserRepository:
    """Users, refresh tokens and API keys on the request's session."""

    def __init__(self, session: AsyncSession) -> None:
        """Work inside the request's session."""
        self.session = session

    async def add_user(
        self, email: str, password_hash: str | None, role: str, oidc_subject: str | None = None
    ) -> User:
        """INSERT a user; a duplicate email raises IntegrityError at the flush."""
        user = User(email=email.lower(), password_hash=password_hash, role=role)
        user.oidc_subject = oidc_subject
        self.session.add(user)
        await self.session.flush()
        return user

    async def user_by_id(self, user_id: int) -> User | None:
        """Primary-key lookup (identity map first)."""
        return await self.session.get(User, user_id)

    async def user_by_email(self, email: str) -> User | None:
        """Emails are stored lower-cased."""
        return await self.session.scalar(select(User).where(User.email == email.lower()))

    async def user_by_oidc_subject(self, subject: str) -> User | None:
        """The user linked to a third-party identity."""
        return await self.session.scalar(select(User).where(User.oidc_subject == subject))

    async def add_refresh_token(self, token: RefreshToken) -> None:
        """Store a refresh token row."""
        self.session.add(token)
        await self.session.flush()

    async def refresh_token_by_hash(self, token_hash: str) -> RefreshToken | None:
        """Look a refresh token up by its SHA-256."""
        return await self.session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )

    async def revoke_family(self, family_id: str, now: datetime) -> int:
        """Revoke every token of one login; returns how many were still active."""
        result = await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        return result.rowcount

    async def add_api_key(self, key: ApiKey) -> ApiKey:
        """Store an API key row."""
        self.session.add(key)
        await self.session.flush()
        return key

    async def api_key_by_hash(self, key_hash: str) -> ApiKey | None:
        """An active (not revoked) key by its SHA-256."""
        return await self.session.scalar(
            select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
        )

    async def api_keys_of(self, user_id: int) -> list[ApiKey]:
        """A user's keys, newest first (revoked ones included)."""
        statement = select(ApiKey).where(ApiKey.user_id == user_id).order_by(ApiKey.id.desc())
        return list(await self.session.scalars(statement))
'''

NOTES_V5_SERVICES_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/services.py
"""Business logic: what the API does, independent of HTTP and of how notes are stored."""

import asyncio
import csv
import io
import ipaddress
import json
import re
import socket
import urllib.parse
from collections.abc import Awaitable, Callable
from datetime import datetime
from http import HTTPStatus
from typing import Any

import httpx
from pydantic import TypeAdapter, ValidationError

from notes_api.events import new_event
from notes_api.exceptions import NoteNotFoundError, UploadRejectedError, VersionConflictError
from notes_api.models import Note
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
            return IMPORT_ADAPTER.validate_python(json.loads(text))
        rows = [
            {**row, "tags": [tag for tag in (row.get("tags") or "").split(";") if tag]}
            for row in csv.DictReader(io.StringIO(text))
        ]
        return IMPORT_ADAPTER.validate_python(rows)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
        reason = f"{type(error).__name__}: {str(error).splitlines()[0]}"
        raise UploadRejectedError(reason, HTTPStatus.UNPROCESSABLE_CONTENT) from error


type Resolver = Callable[[str], Awaitable[list[str]]]


async def resolve_host(host: str) -> list[str]:
    """Every IP address a host name resolves to (getaddrinfo runs in a worker thread)."""
    infos = await asyncio.to_thread(socket.getaddrinfo, host, None, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def is_public_address(address: str) -> bool:
    """False for loopback, private, link-local, reserved, multicast and unspecified addresses."""
    ip = ipaddress.ip_address(address)
    return ip.is_global and not ip.is_multicast


class LinkPreviewer:
    """Fetch the <title> of links in a note, refusing anything that is not a public web URL.

    Server-side request forgery (OWASP API7): a note body is user input, so a link could point
    at 127.0.0.1, the cloud metadata service (169.254.169.254) or a private network. Each host
    is resolved first and every address must be public; redirects are not followed (a public
    URL could redirect to a private one); at most MAX_PREVIEW_BYTES of a page are read.
    """

    def __init__(self, client: httpx.AsyncClient, resolver: Resolver = resolve_host) -> None:
        """Use the pooled client created by the lifespan and an injectable DNS resolver."""
        self.client = client
        self.resolver = resolver

    async def check_url(self, url: str) -> str | None:
        """None if the URL may be fetched, else the reason it may not."""
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return "only public http(s) URLs are fetched"
        try:
            addresses = await self.resolver(parsed.hostname)
        except OSError:
            return "host does not resolve"
        if not addresses or not all(is_public_address(address) for address in addresses):
            return "blocked: not a public address"
        return None

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
        except httpx.HTTPError as error:
            return LinkPreview(url=url, error=type(error).__name__)
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

NOTES_V5_EVENTS_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/events.py
"""Domain events: outbox rows, Redis channels and signed webhooks. No FastAPI here."""

import hashlib
import hmac
import json
from datetime import datetime

from notes_api.models import OutboxEvent

SIGNATURE_HEADER = "X-Notes-Signature"
EVENT_ID_HEADER = "X-Notes-Event-Id"
SIGNATURE_TOLERANCE_SECONDS = 300


def user_channel(user_id: int) -> str:
    """The Redis pub/sub channel that carries one user's live events."""
    return f"notes:user:{user_id}"


def new_event(user_id: int, event_type: str, data: dict[str, object]) -> OutboxEvent:
    """An outbox row; the caller adds it to the same session (same transaction) as the change."""
    return OutboxEvent(user_id=user_id, event_type=event_type, payload=json.dumps(data))


def event_message(event: OutboxEvent) -> dict[str, object]:
    """The JSON body used for WebSocket messages and webhooks."""
    created = event.created_at.isoformat() if isinstance(event.created_at, datetime) else None
    return {
        "id": event.id,
        "type": event.event_type,
        "created_at": created,
        "data": json.loads(event.payload),
    }


def sign_webhook(secret: str, timestamp: int, body: bytes) -> str:
    """'t=<unix time>,v1=<hex HMAC-SHA256 of "t.body">' (the scheme Stripe popularised)."""
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"t={timestamp},v1={mac.hexdigest()}"


def verify_webhook(secret: str, header: str, body: bytes, now: int) -> bool:
    """What a receiver does: recompute, compare in constant time, reject old timestamps."""
    try:
        parts = dict(item.split("=", 1) for item in header.split(","))
        timestamp = int(parts["t"])
    except KeyError, ValueError:
        return False
    if abs(now - timestamp) > SIGNATURE_TOLERANCE_SECONDS:  # replayed long after sending
        return False
    expected = sign_webhook(secret, timestamp, body).split("v1=", 1)[1]
    return hmac.compare_digest(expected, parts.get("v1", ""))
'''

NOTES_V5_MAILER_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/mailer.py
"""Outgoing email behind a Protocol; the default mailer only logs (no SMTP in the course)."""

import logging
from typing import Protocol

logger = logging.getLogger("notes_api.mailer")


class Mailer(Protocol):
    """Anything that can send a message."""

    async def send(self, to: str, subject: str, body: str) -> None:
        """Deliver one email."""
        ...


class LogMailer:
    """Writes emails to the log (production would use an email API, called from a worker)."""

    async def send(self, to: str, subject: str, body: str) -> None:
        """Log instead of sending."""
        logger.info("email to=%s subject=%s", to, subject)


async def send_welcome_email(mailer: Mailer, email: str) -> None:
    """The BackgroundTasks job run after registration: failures must not break signup."""
    try:
        await mailer.send(email, "Welcome to Notes", "Your account is ready.")
    except Exception:  # a background task has nobody to report to: log and move on
        logger.exception("welcome email to %s failed", email)
'''

NOTES_V5_CACHE_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/cache.py
"""Cache-aside for single notes in Redis: TTL with jitter, invalidation, stampede protection."""

import asyncio
import json
import random
from collections.abc import Awaitable, Callable
from typing import Any

from redis.asyncio import Redis

KEY_PREFIX = "notes:v5"  # bump the version when the cached shape changes
STATS_KEY = f"{KEY_PREFIX}:cache-stats"
LOCK_MILLISECONDS = 2000
WAIT_STEPS = 10


def note_key(note_id: int) -> str:
    """notes:v5:note:<id>: namespace, schema version, entity, id."""
    return f"{KEY_PREFIX}:note:{note_id}"


class NoteCache:
    """Read-through helper; the loader returns a JSON-able dict, or None for 'no such note'."""

    def __init__(self, redis: Redis, ttl_seconds: int, rng: random.Random | None = None) -> None:
        """Keep the client and the base TTL."""
        self.redis = redis
        self.ttl_seconds = ttl_seconds
        self.rng = rng or random.Random()

    def ttl(self) -> int:
        """The base TTL ±10 %, so keys written together do not all expire together."""
        spread = max(1, self.ttl_seconds // 10)
        return self.ttl_seconds + self.rng.randint(-spread, spread)

    async def get_or_load(
        self, note_id: int, loader: Callable[[], Awaitable[dict[str, Any] | None]]
    ) -> dict[str, Any] | None:
        """Cached value, or load it once (one loader per key at a time) and cache it."""
        key = note_key(note_id)
        if (cached := await self.redis.get(key)) is not None:
            await self.redis.hincrby(STATS_KEY, "hits", 1)
            return json.loads(cached)
        await self.redis.hincrby(STATS_KEY, "misses", 1)
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

NOTES_V5_EXPORTS_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/exports.py
"""Note exports: state and progress in Redis (a Stream per export), read back as SSE."""

import json
from collections.abc import AsyncIterator

from redis.asyncio import Redis

FINAL_STATUSES = {"done", "failed"}
HEARTBEAT_MILLISECONDS = 15_000


def owner_key(export_id: str) -> str:
    """Who may see this export."""
    return f"export:{export_id}:owner"


def events_key(export_id: str) -> str:
    """The Redis Stream of progress events."""
    return f"export:{export_id}:events"


def result_key(export_id: str) -> str:
    """The finished JSON document."""
    return f"export:{export_id}:result"


async def add_progress(redis: Redis, export_id: str, ttl: int, **fields: object) -> str:
    """Append one event (XADD) and keep the stream alive for ttl seconds; returns its id."""
    entry_id = await redis.xadd(
        events_key(export_id), {key: str(value) for key, value in fields.items()}
    )
    await redis.expire(events_key(export_id), ttl)
    return entry_id if isinstance(entry_id, str) else entry_id.decode()


def format_sse(event_id: str, event: str, data: dict[str, object]) -> str:
    """One text/event-stream message: id, event and data lines, then a blank line."""
    return f"id: {event_id}\nevent: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


async def progress_events(redis: Redis, export_id: str, last_event_id: str) -> AsyncIterator[str]:
    """SSE messages after last_event_id until the export finishes; a comment line as heartbeat.

    Stream ids are the SSE ids, so a reconnecting EventSource (Last-Event-ID) resumes exactly.
    """
    cursor = last_event_id or "0-0"
    while True:
        batches = await redis.xread(
            {events_key(export_id): cursor}, block=HEARTBEAT_MILLISECONDS, count=100
        )
        if not batches:
            yield ": keep-alive\n\n"  # comments keep proxies from closing an idle connection
            continue
        for entry_id, fields in batches[0][1]:
            cursor = entry_id
            data = {
                key: (int(value) if value.isdigit() else value) for key, value in fields.items()
            }
            yield format_sse(entry_id, "progress", data)
            if fields.get("status") in FINAL_STATUSES:
                return
'''

NOTES_V5_WORKER_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/worker.py
"""The ARQ worker: outbox relay, signed webhooks, exports, clean-up (python -m notes_api.worker).

Queues deliver *at least once*, so every task is idempotent or guarded.
"""

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
    ctx["http"] = httpx.AsyncClient(
        timeout=settings.webhook_timeout_seconds,
        follow_redirects=False,
        headers={"User-Agent": f"notes-api-webhooks/{__version__}"},
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
    """POST one signed event; retry with exponential backoff; dead-letter after the last try."""
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
        try:
            response = await ctx["http"].post(user.webhook_url, content=body, headers=headers)
            error = None if response.is_success else f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            error = type(exc).__name__
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


async def run_worker(burst: bool = False, settings: Settings | None = None) -> None:
    """Build the arq Worker inside a running event loop and run it (SIGTERM stops it cleanly).

    `arq notes_api.worker.WorkerSettings` is the usual command, but arq 0.25's CLI calls
    asyncio.get_event_loop() outside a running loop, which raises on Python 3.14+.
    """
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
        ctx={"settings": settings} if settings else {},
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

NOTES_V5_DEPENDENCIES_PY = r'''
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
from typing import Annotated

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
from notes_api.exceptions import AuthenticationError, PermissionDeniedError
from notes_api.mailer import LogMailer, Mailer
from notes_api.models import utc_now
from notes_api.oauth import OidcClient
from notes_api.ratelimit import FixedWindowRateLimiter
from notes_api.repositories import NoteRepository, SqlNoteRepository, SqlUserRepository
from notes_api.security import ALL_SCOPES, Principal, TokenService
from notes_api.services import LinkPreviewer, NoteService, Resolver, resolve_host


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
        settings.admin_emails,
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
    client: HttpClientDep, resolver: Annotated[Resolver, Depends(get_resolver)]
) -> LinkPreviewer:
    """A LinkPreviewer on the shared HTTP client, with SSRF checks."""
    return LinkPreviewer(client, resolver)


LinkPreviewerDep = Annotated[LinkPreviewer, Depends(get_link_previewer)]


def get_login_limiter(redis: RedisDep, settings: SettingsDep) -> FixedWindowRateLimiter:
    """The login/registration rate limiter (shared by every worker through Redis)."""
    return FixedWindowRateLimiter(
        redis, settings.login_rate_limit, settings.login_rate_window_seconds, "login"
    )


LoginLimiterDep = Annotated[FixedWindowRateLimiter, Depends(get_login_limiter)]


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


def get_note_cache(redis: RedisDep, settings: SettingsDep) -> NoteCache:
    """Cache-aside for single notes."""
    return NoteCache(redis, settings.cache_ttl_seconds)


QueueDep = Annotated[ArqRedis, Depends(get_queue)]
MailerDep = Annotated[Mailer, Depends(get_mailer)]
NoteCacheDep = Annotated[NoteCache, Depends(get_note_cache)]


async def kick_relay(queue: ArqRedis) -> None:
    """Background task after a write: wake the outbox relay now instead of at the next cron
    tick. Best effort: if Redis is down, the cron job publishes the events later."""
    with contextlib.suppress(Exception):
        await queue.enqueue_job("relay_outbox", _job_id=f"relay-kick:{int(time.time())}")
'''

NOTES_V5_ROUTERS_AUTH_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/routers/auth.py
"""/api/v1/auth: register, log in (OAuth2 password form), refresh, log out, OpenID Connect."""

import contextlib
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm

from notes_api.dependencies import (
    AuthServiceDep,
    LoginLimiterDep,
    MailerDep,
    OidcClientDep,
    SettingsDep,
    oauth2_scheme,
)
from notes_api.exceptions import AuthenticationError, RateLimitedError
from notes_api.mailer import send_welcome_email
from notes_api.models import User
from notes_api.ratelimit import FixedWindowRateLimiter
from notes_api.schemas import RefreshRequest, TokenPair, UserCreate, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


def client_ip(request: Request) -> str:
    """The peer address (behind a proxy, configure Uvicorn's --forwarded-allow-ips)."""
    return request.client.host if request.client else "unknown"


async def enforce_limit(limiter: FixedWindowRateLimiter, key: str) -> None:
    """Count one attempt; 429 with Retry-After once the window's budget is spent."""
    result = await limiter.hit(key)
    if not result.allowed:
        raise RateLimitedError(result.retry_after)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(
    data: UserCreate,
    request: Request,
    auth: AuthServiceDep,
    limiter: LoginLimiterDep,
    background: BackgroundTasks,
    mailer: MailerDep,
) -> User:
    """Create an account (rate limited); the welcome email goes out after the response."""
    await enforce_limit(limiter, f"register:{client_ip(request)}")
    user = await auth.register(data)
    background.add_task(send_welcome_email, mailer, user.email)
    return user


@router.post("/token", response_model=TokenPair)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    request: Request,
    auth: AuthServiceDep,
    limiter: LoginLimiterDep,
) -> TokenPair:
    """OAuth2 password grant: username = email; optional space-separated scope."""
    await enforce_limit(limiter, f"{client_ip(request)}:{form.username.lower()}")
    user = await auth.authenticate(form.username, form.password)
    return await auth.issue_tokens(user, auth.grant_scopes(user.role, form.scopes))


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, auth: AuthServiceDep) -> TokenPair:
    """Exchange a refresh token for a new pair (the old refresh token stops working)."""
    return await auth.refresh(body.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: RefreshRequest,
    auth: AuthServiceDep,
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> None:
    """Revoke the refresh-token family; also deny the access token sent, if any."""
    principal = None
    if token:
        with contextlib.suppress(AuthenticationError):
            principal = await auth.principal_from_access_token(token)
    await auth.logout(body.refresh_token, principal)


@router.get("/oauth/login", response_class=RedirectResponse, status_code=status.HTTP_302_FOUND)
async def oauth_login(settings: SettingsDep, oidc: OidcClientDep) -> RedirectResponse:
    """Start an OpenID Connect login: redirect to the provider (PKCE, state, nonce)."""
    if not settings.oauth_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "third-party login is not configured")
    return RedirectResponse(await oidc.authorization_url(), status_code=status.HTTP_302_FOUND)


@router.get("/oauth/callback", response_model=TokenPair)
async def oauth_callback(
    code: str, state: str, settings: SettingsDep, oidc: OidcClientDep, auth: AuthServiceDep
) -> TokenPair:
    """Finish the login: verify state, exchange the code, verify the ID token, issue tokens."""
    if not settings.oauth_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "third-party login is not configured")
    claims = await oidc.finish(code, state)
    return await auth.oidc_login(claims)
'''

NOTES_V5_ROUTERS_USERS_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/routers/users.py
"""/api/v1/users/me: the current user and their API keys."""

from typing import Annotated

from fastapi import APIRouter, Path, status

from notes_api.dependencies import AuthServiceDep, CurrentPrincipal, LinkPreviewerDep
from notes_api.exceptions import AuthenticationError, InvalidWebhookError, PermissionDeniedError
from notes_api.models import ApiKey, User
from notes_api.schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyRead, UserRead, WebhookSettings
from notes_api.security import new_secret

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
async def me(principal: CurrentPrincipal, auth: AuthServiceDep) -> User:
    """Who am I?"""
    user = await auth.users.user_by_id(principal.user_id)
    if user is None:
        raise AuthenticationError("account disabled")
    return user


@router.post("/me/api-keys", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    data: ApiKeyCreate, principal: CurrentPrincipal, auth: AuthServiceDep
) -> dict[str, object]:
    """Create a key; its full value appears in this response only."""
    if principal.method != "token":
        raise PermissionDeniedError("API keys cannot create API keys; log in first")
    key, raw_key = await auth.create_api_key(principal, data)
    return {**ApiKeyRead.model_validate(key).model_dump(), "key": raw_key}


@router.get("/me/api-keys", response_model=list[ApiKeyRead])
async def list_api_keys(principal: CurrentPrincipal, auth: AuthServiceDep) -> list[ApiKey]:
    """The caller's keys, without their secrets."""
    return await auth.users.api_keys_of(principal.user_id)


@router.delete("/me/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: Annotated[int, Path(ge=1)], principal: CurrentPrincipal, auth: AuthServiceDep
) -> None:
    """Revoke one of the caller's keys."""
    await auth.revoke_api_key(principal, key_id)


@router.get("/me/webhook")
async def get_webhook(principal: CurrentPrincipal, auth: AuthServiceDep) -> dict[str, str | None]:
    """Where note events are POSTed (the secret is never shown again)."""
    user = await auth.users.user_by_id(principal.user_id)
    return {"url": user.webhook_url if user else None}


@router.put("/me/webhook")
async def set_webhook(
    body: WebhookSettings,
    principal: CurrentPrincipal,
    auth: AuthServiceDep,
    previewer: LinkPreviewerDep,
) -> dict[str, str]:
    """Register a public HTTPS/HTTP URL; returns a new signing secret, once."""
    if reason := await previewer.check_url(str(body.url)):  # same SSRF rules as link previews
        raise InvalidWebhookError(f"{body.url}: {reason}")
    user = await auth.users.user_by_id(principal.user_id)
    if user is None:
        raise AuthenticationError("account disabled")
    user.webhook_url, user.webhook_secret = str(body.url), f"whsec_{new_secret(24)}"
    return {"url": user.webhook_url, "secret": user.webhook_secret}


@router.delete("/me/webhook", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(principal: CurrentPrincipal, auth: AuthServiceDep) -> None:
    """Stop sending webhooks."""
    user = await auth.users.user_by_id(principal.user_id)
    if user is not None:
        user.webhook_url = user.webhook_secret = None
'''

NOTES_V5_ROUTERS_NOTES_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/routers/notes.py
"""/api/v1/notes: CRUD, search, a keyset feed, link previews; ETags and a Redis cache."""

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Header, Path, Query, Request, Response, status

from notes_api.core.errors import PROBLEM_JSON, ProblemDetail
from notes_api.dependencies import (
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
from notes_api.schemas import FeedParams, LinkPreview, NoteCreate, NoteFilters, NoteRead, NoteUpdate

NoteId = Annotated[int, Path(ge=1, description="The note's id.")]
NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {
        "model": ProblemDetail,
        "description": "No note has this id.",
        "content": {PROBLEM_JSON: {}},
    }
}
CACHE_CONTROL = "private, no-cache"  # browsers may keep it, but must revalidate (ETag) first

router = APIRouter(prefix="/notes", tags=["notes"])  # every route needs a user (scopes below)


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


@router.post("", response_model=NoteRead, status_code=status.HTTP_201_CREATED)
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


@router.get("/feed", response_model=CursorPage[NoteRead])
async def notes_feed(
    params: Annotated[FeedParams, Query()], service: ReaderServiceDep
) -> dict[str, object]:
    """Newest notes first, with keyset (cursor) pagination."""
    notes, next_cursor = await service.feed(params.limit, params.cursor)
    return {"items": notes, "limit": params.limit, "next_cursor": next_cursor}


@router.get(
    "/{note_id}",
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


@router.put("/{note_id}", response_model=NoteRead, responses=NOT_FOUND)
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


@router.patch("/{note_id}", response_model=NoteRead, responses=NOT_FOUND)
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


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND)
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


@router.get("/{note_id}/links", response_model=list[LinkPreview], responses=NOT_FOUND)
async def note_links(
    note_id: NoteId, service: ReaderServiceDep, previewer: LinkPreviewerDep
) -> list[LinkPreview]:
    """Titles of the links in a note's body, fetched with the shared HTTP client."""
    note = await service.get(note_id)
    return await previewer.previews(note.body)
'''

NOTES_V5_ROUTERS_ADMIN_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/routers/admin.py
"""/api/v1/admin: bulk import (file upload), export and wipe. Admin role + admin scope."""

import time
from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy import select

from notes_api.dependencies import (
    NoteCacheDep,
    QueueDep,
    RepositoryDep,
    SessionDep,
    SettingsDep,
    WriterServiceDep,
    require_admin,
)
from notes_api.exceptions import UploadRejectedError
from notes_api.models import OutboxEvent
from notes_api.schemas import ImportReport, NoteFilters, NoteRead
from notes_api.services import parse_import

ALLOWED_UPLOADS = {".json": {"application/json"}, ".csv": {"text/csv", "application/vnd.ms-excel"}}

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


async def read_upload(upload: UploadFile, max_bytes: int) -> bytes:
    """The file's bytes after checking its extension, content type and size."""
    filename = upload.filename or ""
    extension = filename[filename.rfind(".") :].lower() if "." in filename else ""
    content_type = (upload.content_type or "").split(";")[0].strip()
    if content_type not in ALLOWED_UPLOADS.get(extension, set()):
        detail = f"expected a .json or .csv file, got {filename!r} ({content_type or 'no type'})"
        raise UploadRejectedError(detail, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
    content = await upload.read(max_bytes + 1)  # one byte more tells us it is too large
    if len(content) > max_bytes:
        raise UploadRejectedError(
            f"file is larger than {max_bytes} bytes", HTTPStatus.CONTENT_TOO_LARGE
        )
    return content


@router.post("/import", response_model=ImportReport, status_code=status.HTTP_201_CREATED)
async def import_notes(
    file: UploadFile, service: WriterServiceDep, settings: SettingsDep
) -> ImportReport:
    """Create notes (owned by the admin) from an uploaded .json list or .csv file."""
    content = await read_upload(file, settings.max_upload_bytes)
    notes = parse_import(file.filename or "", content)
    created = await service.import_notes(notes)
    ids = [note.id for note in created]
    return ImportReport(filename=file.filename or "", imported=len(created), ids=ids)


@router.get("/export")
async def export_notes(repository: RepositoryDep) -> JSONResponse:
    """Every user's notes as a downloadable JSON file."""
    notes, _total = await repository.search(NoteFilters(limit=100, sort="created_at"), None)
    payload = [NoteRead.model_validate(note).model_dump(mode="json") for note in notes]
    headers = {"Content-Disposition": 'attachment; filename="notes.json"'}
    return JSONResponse(payload, headers=headers)


@router.delete("/notes")
async def delete_all_notes(repository: RepositoryDep) -> dict[str, int]:
    """Remove every note of every user."""
    return {"deleted": await repository.delete_all()}


@router.get("/cache-stats")
async def cache_stats(cache: NoteCacheDep) -> dict[str, float]:
    """Note-cache hits, misses and hit rate."""
    return await cache.stats()


@router.get("/webhooks/dead")
async def dead_webhooks(session: SessionDep) -> list[dict[str, object]]:
    """The dead-letter list: events whose webhook failed on every attempt."""
    statement = (
        select(OutboxEvent).where(OutboxEvent.webhook_status == "dead").order_by(OutboxEvent.id)
    )
    events = await session.scalars(statement)
    return [
        {
            "id": event.id,
            "type": event.event_type,
            "attempts": event.webhook_attempts,
            "error": event.last_error,
        }
        for event in events
    ]


@router.post("/webhooks/dead/{event_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_dead_webhook(
    event_id: int, session: SessionDep, queue: QueueDep
) -> dict[str, object]:
    """Send a dead-lettered event again (after the receiver was fixed)."""
    event = await session.get(OutboxEvent, event_id)
    if event is None or event.webhook_status != "dead":
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no dead webhook for event {event_id}")
    event.webhook_status, event.webhook_attempts = "pending", 0
    await queue.enqueue_job(
        "deliver_webhook", event_id, _job_id=f"webhook:{event_id}:retry:{time.time_ns()}"
    )
    return {"id": event_id, "status": "pending"}
'''

NOTES_V5_ROUTERS_EXPORTS_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/routers/exports.py
"""/api/v1/exports: start an export job (202), follow its progress with Server-Sent Events."""

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse

from notes_api.dependencies import CurrentPrincipal, QueueDep, RedisDep, SettingsDep
from notes_api.exceptions import ExportNotFoundError
from notes_api.exports import add_progress, events_key, owner_key, progress_events, result_key

router = APIRouter(prefix="/exports", tags=["exports"])


async def check_owner(redis: RedisDep, export_id: str, user_id: int) -> None:
    """Someone else's (or an unknown) export is 'not found'."""
    if await redis.get(owner_key(export_id)) != str(user_id):
        raise ExportNotFoundError(export_id)


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def start_export(
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
    redis: RedisDep,
    queue: QueueDep,
    settings: SettingsDep,
) -> dict[str, str]:
    """Queue an export of all the caller's notes; 202 Accepted with where to look."""
    export_id = uuid.uuid4().hex
    ttl = settings.export_ttl_seconds
    await redis.set(owner_key(export_id), str(principal.user_id), ex=ttl)
    await add_progress(redis, export_id, ttl, status="queued", done=0, total=0)
    await queue.enqueue_job(
        "export_notes", export_id, principal.user_id, _job_id=f"export:{export_id}"
    )
    status_url = request.app.url_path_for("export_status", export_id=export_id)
    response.headers["Location"] = status_url
    return {"id": export_id, "status_url": status_url, "events_url": f"{status_url}/events"}


@router.get("/{export_id}")
async def export_status(
    export_id: str, principal: CurrentPrincipal, redis: RedisDep
) -> dict[str, object]:
    """The latest progress event (polling is the fallback for clients without SSE)."""
    await check_owner(redis, export_id, principal.user_id)
    latest = await redis.xrevrange(events_key(export_id), count=1)
    fields = latest[0][1] if latest else {"status": "unknown"}
    return {
        "id": export_id,
        **{key: int(value) if value.isdigit() else value for key, value in fields.items()},
    }


@router.get("/{export_id}/download")
async def download_export(
    export_id: str, principal: CurrentPrincipal, redis: RedisDep
) -> JSONResponse:
    """The finished export as a JSON file (404 until it is ready)."""
    await check_owner(redis, export_id, principal.user_id)
    result = await redis.get(result_key(export_id))
    if result is None:
        raise ExportNotFoundError(export_id)
    headers = {"Content-Disposition": f'attachment; filename="notes-{export_id}.json"'}
    return JSONResponse(json.loads(result), headers=headers)


@router.get("/{export_id}/events", response_class=StreamingResponse)
async def export_events(
    export_id: str,
    principal: CurrentPrincipal,
    redis: RedisDep,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    """text/event-stream of progress; a reconnecting EventSource resumes after Last-Event-ID."""
    await check_owner(redis, export_id, principal.user_id)
    return StreamingResponse(
        progress_events(redis, export_id, last_event_id or "0-0"),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},  # no proxy buffering
    )
'''

NOTES_V5_ROUTERS_REALTIME_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/routers/realtime.py
"""/api/v1/ws: live note events over a WebSocket, fanned out through Redis pub/sub."""

import asyncio
import contextlib
import json
import time
from collections import defaultdict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.asyncio.client import PubSub

from notes_api.dependencies import RedisDep, SettingsDep, get_auth_service, get_clock
from notes_api.events import user_channel
from notes_api.exceptions import AuthenticationError
from notes_api.security import Principal

AUTH_TIMEOUT_SECONDS = 5.0
POLICY_VIOLATION = 1008  # WebSocket close code for "you are not allowed here"

router = APIRouter(tags=["realtime"])


class ConnectionManager:
    """The sockets open in this process, per user. Other processes' sockets are reached
    through Redis: every process subscribes to the channels of its own connected users."""

    def __init__(self) -> None:
        """Start with no connections."""
        self.active: defaultdict[int, set[WebSocket]] = defaultdict(set)

    def add(self, user_id: int, websocket: WebSocket) -> None:
        """Remember a connection."""
        self.active[user_id].add(websocket)

    def remove(self, user_id: int, websocket: WebSocket) -> None:
        """Forget a connection."""
        self.active[user_id].discard(websocket)
        if not self.active[user_id]:
            del self.active[user_id]

    def count(self) -> int:
        """Open connections in this process."""
        return sum(len(sockets) for sockets in self.active.values())


async def authenticate(
    websocket: WebSocket, token: str, redis: RedisDep, settings: SettingsDep
) -> Principal:
    """Check the access token sent as the first message, with a short-lived DB session."""
    async with websocket.app.state.session_factory() as session:
        auth = get_auth_service(websocket, session, redis, settings, get_clock())  # type: ignore[arg-type]
        return await auth.principal_from_access_token(token)


async def forward_events(websocket: WebSocket, pubsub: PubSub, heartbeat_seconds: float) -> None:
    """Redis → client, plus a ping every heartbeat_seconds (dead connections show up fast)."""
    last_ping = time.monotonic()
    while True:
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.2)
        if message is not None:
            await websocket.send_text(message["data"])
        if time.monotonic() - last_ping >= heartbeat_seconds:
            await websocket.send_json({"type": "ping"})
            last_ping = time.monotonic()


async def read_client(websocket: WebSocket) -> None:
    """Client → server: answer pings; any other message is ignored. Ends on disconnect."""
    while True:
        message = await websocket.receive_json()
        if message.get("type") == "ping":
            await websocket.send_json({"type": "pong"})


@router.websocket("/ws")
async def live_updates(websocket: WebSocket, redis: RedisDep, settings: SettingsDep) -> None:
    """Accept, authenticate with the first message ({"token": ...}), then stream events."""
    await websocket.accept()
    try:
        first = await asyncio.wait_for(websocket.receive_json(), timeout=AUTH_TIMEOUT_SECONDS)
        principal = await authenticate(websocket, str(first.get("token", "")), redis, settings)
    except TimeoutError, AuthenticationError, json.JSONDecodeError, AttributeError:
        await websocket.close(code=POLICY_VIOLATION, reason="authentication required")
        return
    except WebSocketDisconnect:
        return
    manager: ConnectionManager = websocket.app.state.connections
    manager.add(principal.user_id, websocket)
    pubsub = redis.pubsub()
    await pubsub.subscribe(user_channel(principal.user_id))
    await websocket.send_json({"type": "ready", "user_id": principal.user_id})
    tasks = [
        asyncio.create_task(forward_events(websocket, pubsub, settings.ws_heartbeat_seconds)),
        asyncio.create_task(read_client(websocket)),
    ]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)  # the client left
    finally:
        for task in tasks:
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
            await asyncio.gather(*tasks)
        manager.remove(principal.user_id, websocket)
        await pubsub.unsubscribe()
        await pubsub.aclose()
'''

NOTES_V5_MAIN_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/main.py
"""The Notes API application factory.

Unit 6.6 version: create_app() wires settings, password hashing and token secrets, error
handlers, middleware, log redaction, the lifespan (database, Redis, the ARQ queue, an HTTP
client) and the routers: authentication, notes (cached, with ETags), exports (SSE) and a
WebSocket feed. The ARQ worker lives in worker.py. Later units add observability (6.7) and
deployment (6.8).

Serve it with `uvicorn notes_api.main:app` (module-level app) or
`uvicorn --factory notes_api.main:create_app` (a fresh app per process).
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
from notes_api.core.logging import install_redaction
from notes_api.core.middleware import (
    REQUEST_ID_HEADER,
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
    TimingMiddleware,
)
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
        docs_url=None if settings.environment == "production" else "/docs",
        redoc_url=None if settings.environment == "production" else "/redoc",
        generate_unique_id_function=operation_id,
        openapi_tags=OPENAPI_TAGS,
    )
    app.state.settings = settings
    app.state.connections = ConnectionManager()
    install_security(app, settings)
    install_error_handlers(app)
    install_middleware(app, settings)
    api_router = APIRouter(prefix=API_PREFIX)
    api_router.include_router(auth.router)
    api_router.include_router(users.router)
    api_router.include_router(notes.router)
    api_router.include_router(exports.router)
    api_router.include_router(realtime.router)
    api_router.include_router(admin.router)
    app.include_router(health.router)
    app.include_router(api_router)
    app.include_router(pages.router)
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
    return app


app = create_app()
'''

NOTES_V5_TESTS_CONFTEST_PY = r'''
%%writefile ../projects/notes_api/tests/conftest.py
"""Shared fixtures: each test gets its own app, SQLite file and fake Redis, and a logged-in user."""

import asyncio
import secrets
from collections.abc import Iterator
from pathlib import Path

import fakeredis
import pytest
from arq.connections import ArqRedis
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from helpers import USER_EMAIL, FakeMailer, auth_headers, create_tables, fake_resolver
from notes_api.core.config import Settings
from notes_api.dependencies import get_mailer, get_queue, get_redis, get_resolver
from notes_api.main import create_app


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
        admin_emails=["admin@example.com"],
        login_rate_limit=10,
        cookie_secure=False,  # TestClient talks plain HTTP
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
def admin_headers(anonymous: TestClient) -> dict[str, str]:
    """Bearer headers of an admin (admin@example.com is in admin_emails)."""
    return auth_headers(anonymous, "admin@example.com")
'''

NOTES_V5_TESTS_HELPERS_PY = r'''
%%writefile ../projects/notes_api/tests/helpers.py
"""Small helpers shared by the test modules."""

import ipaddress
from typing import Any

from fastapi.testclient import TestClient

from notes_api.core.config import Settings
from notes_api.db import Base, create_engine_from_settings

USER_EMAIL = "user@example.com"
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
'''

NOTES_V5_TESTS_TEST_BACKGROUND_PY = r'''
%%writefile ../projects/notes_api/tests/test_background.py
"""BackgroundTasks after the response: the welcome email and the relay kick."""

from arq.connections import ArqRedis
from fastapi.testclient import TestClient

from helpers import FakeMailer, create, register
from notes_api.events import sign_webhook, verify_webhook


def test_welcome_email_is_sent_after_registration(
    anonymous: TestClient, mailer: FakeMailer
) -> None:
    """The response does not wait for the email; TestClient runs background tasks first."""
    assert register(anonymous, "new@example.com").status_code == 201
    assert mailer.sent == [("new@example.com", "Welcome to Notes")]


def test_writes_kick_the_relay(client: TestClient, fake_queue: ArqRedis) -> None:
    """After a write, a relay job is queued so events go out without waiting for the cron."""
    create(client)
    jobs = client.portal.call(fake_queue.queued_jobs)
    assert "relay_outbox" in {job.function for job in jobs}


def test_webhook_signatures_are_checked_with_a_time_window() -> None:
    """Wrong secret, changed body or an old timestamp fail verification."""
    header = sign_webhook("whsec_test", 1_000, b'{"id":1}')
    assert verify_webhook("whsec_test", header, b'{"id":1}', now=1_010)
    assert not verify_webhook("whsec_other", header, b'{"id":1}', now=1_010)
    assert not verify_webhook("whsec_test", header, b'{"id":2}', now=1_010)
    assert not verify_webhook("whsec_test", header, b'{"id":1}', now=2_000)
    assert not verify_webhook("whsec_test", "garbage", b"", now=0)
'''

NOTES_V5_TESTS_TEST_WORKER_PY = r'''
%%writefile ../projects/notes_api/tests/test_worker.py
"""ARQ tasks, called directly: relay, signed webhooks with retries and dead letters, locks."""

import json
from collections.abc import Callable
from typing import Any

import fakeredis
import httpx
import pytest
import respx
from arq import Retry
from arq.connections import ArqRedis
from fastapi.testclient import TestClient

from helpers import create
from notes_api.core.config import Settings
from notes_api.db import create_engine_from_settings, make_session_factory
from notes_api.events import SIGNATURE_HEADER, user_channel, verify_webhook
from notes_api.models import OutboxEvent
from notes_api.worker import DEAD_LETTERS, deliver_webhook, purge_expired_tokens, relay_outbox

HOOK = "https://hooks.example/notes"


@pytest.fixture
def ctx(
    client: TestClient,
    settings: Settings,
    fake_redis: fakeredis.FakeAsyncRedis,
    fake_queue: ArqRedis,
) -> dict[str, Any]:
    """What WorkerSettings.on_startup builds, but on the test database and fake Redis."""
    engine = create_engine_from_settings(settings)
    return {
        "settings": settings,
        "session_factory": make_session_factory(engine),
        "text_redis": fake_redis,
        "redis": fake_queue,
        "http": httpx.AsyncClient(timeout=1),
        "job_try": 1,
    }


def run(client: TestClient, task: Callable[..., Any], *args: Any) -> Any:
    """Run an async task on the app's event loop (where the fake Redis lives)."""
    return client.portal.call(task, *args)


def with_webhook(client: TestClient) -> str:
    """Register the test receiver; return the signing secret."""
    response = client.put("/api/v1/users/me/webhook", json={"url": HOOK})
    assert response.status_code == 200, response.text
    return response.json()["secret"]


async def events(ctx: dict[str, Any]) -> list[OutboxEvent]:
    """Every outbox row."""
    from sqlalchemy import select

    async with ctx["session_factory"]() as session:
        return list(await session.scalars(select(OutboxEvent).order_by(OutboxEvent.id)))


def test_writes_create_outbox_events(client: TestClient, ctx: dict[str, Any]) -> None:
    """Create, update and delete each leave one event, in the same transaction as the change."""
    note = create(client, title="Tea")
    client.patch(f"/api/v1/notes/{note['id']}", json={"pinned": True})
    client.delete(f"/api/v1/notes/{note['id']}")
    rows = run(client, events, ctx)
    assert [row.event_type for row in rows] == ["note.created", "note.updated", "note.deleted"]
    assert json.loads(rows[0].payload) == {"note_id": 1, "title": "Tea", "version": 1}


def test_a_failed_write_leaves_no_event(client: TestClient, ctx: dict[str, Any]) -> None:
    """A rolled-back request (409) writes no event: change and event share one transaction."""
    note = create(client)
    client.patch(f"/api/v1/notes/{note['id']}", json={"title": "x"})
    assert (
        client.patch(f"/api/v1/notes/{note['id']}", json={"title": "y", "version": 1}).status_code
        == 409
    )
    assert [row.event_type for row in run(client, events, ctx)] == ["note.created", "note.updated"]


@respx.mock
def test_relay_publishes_and_queues_webhooks(
    client: TestClient, ctx: dict[str, Any], fake_redis: fakeredis.FakeAsyncRedis
) -> None:
    """Each event goes to the user's Redis channel once; webhook jobs are queued by event id."""
    with_webhook(client)
    create(client, title="Tea")

    async def relay_and_listen() -> tuple[int, int, list[str]]:
        """Subscribe, relay twice, collect the published messages."""
        pubsub = fake_redis.pubsub()
        await pubsub.subscribe(user_channel(1))
        first, second = await relay_outbox(ctx), await relay_outbox(ctx)
        messages = []
        for _ in range(5):  # the subscribe confirmation also comes back as None: poll a few times
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.05)
            if message is not None:
                messages.append(message["data"])
        await pubsub.aclose()
        return first, second, messages

    first, second, messages = run(client, relay_and_listen)
    assert (first, second) == (1, 0)  # published once; the second run finds nothing new
    assert json.loads(messages[0])["type"] == "note.created"
    queued = run(client, ctx["redis"].queued_jobs)
    assert [(job.function, job.args) for job in queued if job.function == "deliver_webhook"] == [
        ("deliver_webhook", (1,))
    ]
    assert run(client, ctx["redis"].exists, "arq:job:webhook:1") == 1  # the job id is the event id


@respx.mock
def test_webhook_is_signed_and_delivered_once(client: TestClient, ctx: dict[str, Any]) -> None:
    """The receiver can verify the signature; a duplicate job does not send twice."""
    secret = with_webhook(client)
    create(client, title="Tea")
    route = respx.post(HOOK).respond(204)
    assert run(client, deliver_webhook, ctx, 1) == "delivered"
    request = route.calls.last.request
    assert verify_webhook(
        secret,
        request.headers[SIGNATURE_HEADER],
        request.content,
        now=int(request.headers[SIGNATURE_HEADER].split(",")[0][2:]),
    )
    assert run(client, deliver_webhook, ctx, 1) == "already delivered" and route.call_count == 1


@respx.mock
def test_failing_webhook_retries_then_dead_letters(
    client: TestClient,
    ctx: dict[str, Any],
    fake_redis: fakeredis.FakeAsyncRedis,
    admin_headers: dict[str, str],
) -> None:
    """Failures raise Retry with growing delays; the last try marks the event dead."""
    with_webhook(client)
    create(client)
    respx.post(HOOK).respond(500)
    delays = []
    for attempt in range(1, ctx["settings"].webhook_max_attempts):
        ctx["job_try"] = attempt
        with pytest.raises(Retry) as retry:
            run(client, deliver_webhook, ctx, 1)
        delays.append(retry.value.defer_score)
    ctx["job_try"] = ctx["settings"].webhook_max_attempts
    assert run(client, deliver_webhook, ctx, 1) == "dead"
    assert delays == [2000, 4000, 8000, 16000]  # milliseconds
    assert run(client, fake_redis.lrange, DEAD_LETTERS, 0, -1) == ["1"]
    dead = client.get("/api/v1/admin/webhooks/dead", headers=admin_headers).json()
    assert dead == [{"id": 1, "type": "note.created", "attempts": 5, "error": "HTTP 500"}]
    assert (
        client.post("/api/v1/admin/webhooks/dead/1/retry", headers=admin_headers).status_code == 202
    )


def test_relay_lock_prevents_overlap(
    client: TestClient, ctx: dict[str, Any], fake_redis: fakeredis.FakeAsyncRedis
) -> None:
    """While another relay holds the lock, a second one does nothing."""
    create(client)
    run(client, fake_redis.set, "lock:relay-outbox", "1")
    assert run(client, relay_outbox, ctx) == 0
    run(client, fake_redis.delete, "lock:relay-outbox")
    assert run(client, relay_outbox, ctx) == 1


def test_purge_expired_tokens(client: TestClient, ctx: dict[str, Any]) -> None:
    """The daily job runs once per lock and deletes nothing that is still valid."""
    assert run(client, purge_expired_tokens, ctx) == 0


def test_webhook_url_must_be_public(client: TestClient) -> None:
    """Webhooks get the same SSRF rules as link previews."""
    response = client.put("/api/v1/users/me/webhook", json={"url": "http://intranet.example/hook"})
    assert (response.status_code, response.json()["type"]) == (422, "/problems/invalid-webhook")
'''

NOTES_V5_TESTS_TEST_REALTIME_PY = r'''
%%writefile ../projects/notes_api/tests/test_realtime.py
"""WebSocket live updates: first-message authentication, Redis fan-out, heartbeats."""

import json

import fakeredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

from notes_api.events import user_channel


def token_of(client: TestClient) -> str:
    """The logged-in client's access token."""
    return client.headers["authorization"].removeprefix("Bearer ")


def test_socket_needs_a_valid_token(client: TestClient) -> None:
    """A wrong first message closes the socket with 1008 (policy violation)."""
    with client.websocket_connect("/api/v1/ws") as websocket:
        websocket.send_json({"token": "not-a-token"})
        with pytest.raises(WebSocketDisconnect) as closed:
            websocket.receive_json()
    assert closed.value.code == 1008


def test_events_published_in_redis_reach_the_socket(
    client: TestClient, fake_redis: fakeredis.FakeAsyncRedis, app: FastAPI
) -> None:
    """Whatever process publishes on the user's channel, the socket forwards it."""
    with client.websocket_connect("/api/v1/ws") as websocket:
        websocket.send_json({"token": token_of(client)})
        assert websocket.receive_json() == {"type": "ready", "user_id": 1}
        assert app.state.connections.count() == 1
        event = {"id": 7, "type": "note.updated", "data": {"note_id": 3}}
        client.portal.call(fake_redis.publish, user_channel(1), json.dumps(event))
        client.portal.call(fake_redis.publish, user_channel(2), json.dumps({"id": 8}))  # not ours
        assert websocket.receive_json() == event
        websocket.send_json({"type": "ping"})
        assert websocket.receive_json() == {"type": "pong"}
    assert app.state.connections.count() == 0


def test_heartbeat_pings(client: TestClient, app: FastAPI) -> None:
    """The server pings idle clients every ws_heartbeat_seconds."""
    app.state.settings.ws_heartbeat_seconds = 0.1
    with client.websocket_connect("/api/v1/ws") as websocket:
        websocket.send_json({"token": token_of(client)})
        websocket.receive_json()
        assert websocket.receive_json() == {"type": "ping"}
'''

NOTES_V5_TESTS_TEST_EXPORTS_PY = r'''
%%writefile ../projects/notes_api/tests/test_exports.py
"""Exports: 202 + a queued job, progress in a Redis Stream, Server-Sent Events, download."""

from typing import Any

import fakeredis
import pytest
from arq.connections import ArqRedis
from fastapi.testclient import TestClient

from helpers import auth_headers, create
from notes_api.core.config import Settings
from notes_api.db import create_engine_from_settings, make_session_factory
from notes_api.worker import export_notes


@pytest.fixture
def started(client: TestClient) -> dict[str, str]:
    """Three notes, then POST /exports."""
    for number in range(3):
        create(client, title=f"Note {number}")
    response = client.post("/api/v1/exports")
    assert (
        response.status_code == 202
        and response.headers["location"] == response.json()["status_url"]
    )
    return response.json()


def run_job(
    client: TestClient, settings: Settings, fake_redis: fakeredis.FakeAsyncRedis, export_id: str
) -> int:
    """What the worker would do with the queued job."""
    ctx: dict[str, Any] = {
        "settings": settings,
        "session_factory": make_session_factory(create_engine_from_settings(settings)),
        "text_redis": fake_redis,
    }
    return client.portal.call(export_notes, ctx, export_id, 1)


def sse_messages(text: str) -> list[dict[str, str]]:
    """Parse text/event-stream into dicts of fields."""
    messages = []
    for block in text.strip().split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if not line.startswith(":")
        )
        messages.append(fields)
    return messages


def test_export_job_is_queued(
    client: TestClient, started: dict[str, str], fake_queue: ArqRedis
) -> None:
    """The API only records the request and queues the work."""
    jobs = client.portal.call(fake_queue.queued_jobs)
    assert [(job.function, job.args) for job in jobs if job.function == "export_notes"] == [
        ("export_notes", (started["id"], 1))
    ]
    assert client.get(started["status_url"]).json() == {
        "id": started["id"],
        "status": "queued",
        "done": 0,
        "total": 0,
    }


def test_progress_streams_as_sse_and_resumes(
    client: TestClient,
    started: dict[str, str],
    settings: Settings,
    fake_redis: fakeredis.FakeAsyncRedis,
) -> None:
    """Every progress event arrives once with an id; Last-Event-ID resumes after it."""
    assert run_job(client, settings, fake_redis, started["id"]) == 3
    response = client.get(started["events_url"])
    assert response.headers["content-type"].startswith("text/event-stream")
    messages = sse_messages(response.text)
    statuses = [message["data"] for message in messages]
    assert [message["event"] for message in messages] == ["progress"] * 4
    assert (
        statuses[0] == '{"status":"queued","done":0,"total":0}'
        and statuses[-1] == '{"status":"done","done":3,"total":3}'
    )
    resumed = client.get(started["events_url"], headers={"Last-Event-ID": messages[1]["id"]})
    assert [message["id"] for message in sse_messages(resumed.text)] == [
        message["id"] for message in messages[2:]
    ]
    assert [note["title"] for note in client.get(f"{started['status_url']}/download").json()] == [
        "Note 0",
        "Note 1",
        "Note 2",
    ]


def test_other_users_cannot_see_an_export(client: TestClient, started: dict[str, str]) -> None:
    """Status, events and download are 404 for anyone else."""
    intruder = auth_headers(client, "intruder@example.com")
    for suffix in ("", "/events", "/download"):
        assert client.get(f"{started['status_url']}{suffix}", headers=intruder).status_code == 404
'''

NOTES_V5_TESTS_TEST_CACHING_PY = r'''
%%writefile ../projects/notes_api/tests/test_caching.py
"""HTTP caching (ETag, 304, Cache-Control) and the Redis cache-aside for single notes."""

import fakeredis
from fastapi.testclient import TestClient

from helpers import auth_headers, create
from notes_api.cache import NoteCache, note_key


def test_etag_and_304(client: TestClient) -> None:
    """A matching If-None-Match gets an empty 304; an update changes the ETag."""
    note = create(client)
    first = client.get(f"/api/v1/notes/{note['id']}")
    etag = first.headers["etag"]
    assert (etag, first.headers["cache-control"]) == ('"1-1"', "private, no-cache")
    not_modified = client.get(f"/api/v1/notes/{note['id']}", headers={"If-None-Match": etag})
    assert (not_modified.status_code, not_modified.content, not_modified.headers["etag"]) == (
        304,
        b"",
        etag,
    )
    client.patch(f"/api/v1/notes/{note['id']}", json={"pinned": True})
    changed = client.get(f"/api/v1/notes/{note['id']}", headers={"If-None-Match": etag})
    assert (changed.status_code, changed.headers["etag"]) == (200, '"1-2"')


def test_cache_hits_misses_and_invalidation(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    """The first read misses, later reads hit; an update invalidates the cached copy."""
    note = create(client, title="Old")
    for _ in range(4):
        client.get(f"/api/v1/notes/{note['id']}")
    client.patch(f"/api/v1/notes/{note['id']}", json={"title": "New"})
    assert client.get(f"/api/v1/notes/{note['id']}").json()["title"] == "New"
    assert client.get("/api/v1/admin/cache-stats", headers=admin_headers).json() == {
        "hits": 3,
        "misses": 2,
        "hit_rate": 0.6,
    }


def test_cached_notes_are_still_authorized(client: TestClient) -> None:
    """A cached note is not served to another user (authorization happens after the cache)."""
    note = create(client, title="Private")
    client.get(f"/api/v1/notes/{note['id']}")  # now cached
    intruder = auth_headers(client, "intruder@example.com")
    assert client.get(f"/api/v1/notes/{note['id']}", headers=intruder).status_code == 404


def test_lists_are_not_stored(client: TestClient) -> None:
    """Lists change with every write: no-store."""
    assert client.get("/api/v1/notes").headers["cache-control"] == "private, no-store"


def test_stampede_lock_loads_once(client: TestClient, fake_redis: fakeredis.FakeAsyncRedis) -> None:
    """Ten concurrent misses on one key run the loader once; the rest wait for its result."""
    import asyncio

    cache = NoteCache(fake_redis, ttl_seconds=60)
    loads = []

    async def slow_loader() -> dict[str, object]:
        """Count calls; take a while."""
        loads.append(1)
        await asyncio.sleep(0.05)
        return {"owner_id": 1, "note": {"id": 99, "version": 1}}

    async def ten_readers() -> list[object]:
        """Concurrent cache misses."""
        return await asyncio.gather(*(cache.get_or_load(99, slow_loader) for _ in range(10)))

    results = client.portal.call(ten_readers)
    assert len(loads) == 1 and all(result == results[0] for result in results)
    ttl = client.portal.call(fake_redis.ttl, note_key(99))
    assert 54 <= ttl <= 66  # 60 s ± 10 % jitter
'''

NOTES_V5_TESTS_TEST_MIGRATIONS_PY = r'''
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
'''

NOTES_V5_TESTS_TEST_REDIS_WORKER_PY = r'''
%%writefile ../projects/notes_api/tests/test_redis_worker.py
"""End to end on a real Redis (testcontainer) with the real ARQ worker in burst mode.

Skipped without Docker. Run only these: `uv run pytest -m redis`.
"""

import asyncio
from collections.abc import Iterator

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
from test_postgres import docker_available

pytestmark = pytest.mark.redis
REDIS_IMAGE = "redis:7.4"
HOOK = "https://hooks.example/notes"


@pytest.fixture(scope="module")
def redis_url() -> Iterator[str]:
    """One Redis container for this module (removed afterwards)."""
    if not docker_available():
        pytest.skip("Docker is not available")
    from testcontainers.community.redis import RedisContainer

    with RedisContainer(REDIS_IMAGE) as container:
        host, port = container.get_container_host_ip(), container.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"


@pytest.fixture
def real_settings(settings: Settings, redis_url: str) -> Settings:
    """The test settings, but with the real Redis."""
    return settings.model_copy(update={"redis_url": SecretStr(redis_url)})


def burst(settings: Settings) -> None:
    """Process every queued job (and the jobs they queue), then stop."""
    asyncio.run(run_worker(burst=True, settings=settings))


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
