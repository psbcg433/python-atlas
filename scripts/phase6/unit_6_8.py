"""Unit 6.8 — Deployment and Operations (with Lab 6.8 and Notes API v7)."""

from helpers_module import setup_cells
from nbformat import NotebookNode

from nb_builder import code, md, predict_cells, writefile_cells

UNIT_FOLDERS = """
*NOTES_FOLDERS,
NOTES_API_DIR / "deploy" / "k8s",
NOTES_API_DIR / "deploy" / "systemd",
NOTES_API_DIR / "deploy" / "cloudrun",
NOTES_API_DIR / "load",
REPO_ROOT / ".github" / "workflows",
PHASE6_DIR / "deploy_demo",
"""  # the arguments of enter_phase6() in Unit 6.8 and the project

UNIT_SETUP_SOURCE = r"""
import asyncio
import atexit
import contextlib
import csv
import dataclasses
import graphlib
import hashlib
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
import signal
import socket
import sqlite3
import subprocess
import sys
import textwrap
import threading
import time
import urllib.request
import warnings
from collections import Counter as TallyCounter
from collections.abc import AsyncIterator, Callable, Iterable, Iterator
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
import redis as redis_sync
import redis.asyncio as redis_asyncio
import respx
import schemathesis
import sqlalchemy as sa
import starlette
import structlog
import uvicorn
import yaml
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import event

warnings.filterwarnings(
    "ignore", message=".*iscoroutinefunction.* is deprecated", category=DeprecationWarning
)
warnings.filterwarnings("ignore", message="Call to deprecated close", category=DeprecationWarning)

"""

DOCKER_HELPERS_SOURCE = r'''
DEMO_DIR = PHASE6_DIR / "deploy_demo"  # images and stacks of this unit are built from here
DEMO_DIR.mkdir(exist_ok=True)


def docker(*arguments: str, cwd: Path = DEMO_DIR, timeout: float = 600, check: bool = True) -> str:
    """Run a docker command; return its output (raise with the output if it fails and check)."""
    run = subprocess.run(
        ["docker", *arguments],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**CHILD_ENV, "DOCKER_BUILDKIT": "1"},
    )
    output = (run.stdout + run.stderr).strip()
    if check and run.returncode != 0:
        raise RuntimeError(f"docker {' '.join(arguments[:3])} failed:\n{output[-1500:]}")
    return output


def image_size_mb(image: str) -> float:
    """The image's size in MB."""
    return int(docker("image", "inspect", image, "--format", "{{.Size}}")) / 1_000_000


docker_version = docker("version", "--format", "{{.Server.Version}}") if HAS_DOCKER else "-"
print(f"{HAS_DOCKER=}  {HAS_OPENSSL=}  docker: {docker_version}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 6.8 — Deployment and Operations

            **Objectives**

            - Choose a process model (Uvicorn workers or Gunicorn with Uvicorn workers), size it,
              and keep `database pool × processes` under the database's limit.
            - Write a multi-stage Dockerfile with uv, a non-root user and a small image.
            - Run a Compose stack: API, worker, PostgreSQL, Redis, a migrations job, a proxy.
            - Configure by environment (12-factor) and keep secrets out of images and git.
            - Put Caddy, Nginx or Traefik in front: TLS, proxy headers, WebSocket proxying.
            - Build a CI/CD pipeline: lint, type-check, test, build, scan, push, deploy.
            - Run migrations as one-off jobs and change schemas with expand/contract.
            - Compare deployment targets: VM, PaaS, Cloud Run / ECS, Kubernetes.
            - Deploy without downtime: graceful shutdown, rolling / blue-green / canary releases,
              stateless scaling, PgBouncer, CDNs.
            - Load-test with Locust, plan capacity, and walk a production checklist.
            - Move the **Notes API to v7**: a production image, the full stack behind TLS, a
              CI/CD pipeline, deployment manifests, a graceful-shutdown test and a load test.

            **JS bridge**

            | JavaScript / TypeScript | Python | The difference that bites |
            | --- | --- | --- |
            | `node server.js` (one process per core with `cluster` / PM2) | `uvicorn --workers N`, or Gunicorn managing Uvicorn workers | one event loop per process; the GIL makes threads no substitute for processes |
            | `node:22-alpine` + `npm ci` | `python:3.15-slim` + `uv sync --frozen` in a build stage | wheels for musl (Alpine) are rarer: slim (glibc) is the safe default |
            | `.env` + `dotenv` | pydantic-settings (environment, `.env`, secret files) | settings are validated at startup, not read ad hoc |
            | Nginx / Caddy in front of Express | the same proxies in front of Uvicorn | Uvicorn must be told to trust proxy headers (`--proxy-headers`, `FORWARDED_ALLOW_IPS`) |
            | GitHub Actions with `setup-node` | GitHub Actions with `setup-uv` | the same pipeline shape |
            | Prisma `migrate deploy` in a release step | `alembic upgrade head` as a one-off job | migrations must be backward compatible while old pods run |
            | `server.close()` on SIGTERM | Uvicorn's graceful shutdown (`--timeout-graceful-shutdown`) | the container's PID 1 must receive the signal |
            | k6 / Artillery | Locust (Python user classes) | the load generator is Python code too |

            Run the setup cells first. Part 1: the imports:
            """
        ),
        *setup_cells(
            "6.8",
            UNIT_SETUP_SOURCE,
            """
            Part 2: the shared helpers from [`phase6_helpers.py`](phase6_helpers.py) (server,
            Notes API, database, Redis, worker and PostgreSQL helpers of Units 6.1–6.7),
            including this unit's `docker(*arguments)` (run the Docker CLI, raise with its output
            on failure), `image_size_mb()` and `DEMO_DIR`, the folder the demo images and stacks
            are built from. Everything that needs Docker prints a skip message without it:
            """,
            folders=UNIT_FOLDERS,
        ),
        *writefile_cells(
            r'''
            %%writefile _scratch/phase6/deploy_demo/app.py
            """The deployment demo app (served by Uvicorn, inside or outside a container)."""

            import asyncio
            import os
            import socket
            import sys
            import tracemalloc

            if os.environ.get("TRACE_MEMORY"):  # started first, so importing FastAPI is measured
                tracemalloc.start()

            import redis.asyncio as redis_asyncio
            from fastapi import FastAPI, Request, WebSocket

            app = FastAPI()
            COUNTS = {"hits": 0}  # in memory: one copy per process
            REDIS = redis_asyncio.from_url(os.environ["REDIS_URL"]) if os.environ.get("REDIS_URL") else None


            @app.get("/health")
            def health() -> dict[str, str]:
                """Liveness."""
                return {"status": "ok"}


            @app.get("/version")
            def version() -> dict[str, object]:
                """The release this process runs (APP_VERSION), for the blue-green demo."""
                return {"version": os.environ.get("APP_VERSION", "dev"), "pid": os.getpid()}


            @app.get("/whoami")
            def whoami(request: Request) -> dict[str, object]:
                """Which process answered, and the client and scheme as this app sees them."""
                forwarded = {key: value for key, value in request.headers.items() if key.startswith("x-forwarded")}
                return {"pid": os.getpid(), "host": socket.gethostname(),
                        "client": request.client.host if request.client else None,
                        "scheme": request.url.scheme, "forwarded": forwarded}


            @app.get("/slow")
            async def slow(seconds: float = 1.0) -> dict[str, float | int]:
                """A request that takes a while (and which process served it)."""
                await asyncio.sleep(seconds)
                return {"slept": seconds, "pid": os.getpid()}


            @app.post("/count")
            async def count() -> dict[str, int]:
                """Increment the in-memory counter and, if configured, the shared one."""
                COUNTS["hits"] += 1
                shared = await REDIS.incr("demo:hits") if REDIS else -1
                return {"in_memory": COUNTS["hits"], "shared": shared}


            @app.websocket("/ws")
            async def echo(websocket: WebSocket) -> None:
                """Echo one message."""
                await websocket.accept()
                await websocket.send_text("echo: " + await websocket.receive_text())
                await websocket.close()


            @app.get("/memory")
            async def memory(hold: float = 0.0) -> dict[str, object]:
                """This process's Python allocations (tracemalloc) and peak resident memory."""
                await asyncio.sleep(hold)  # lets concurrent requests reach different workers
                traced, peak = tracemalloc.get_traced_memory() if tracemalloc.is_tracing() else (0, 0)
                try:
                    import resource  # Unix only

                    max_rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # KiB on Linux
                except ImportError:
                    max_rss_kib = -1
                return {"pid": os.getpid(), "traced_kib": traced // 1024, "peak_kib": peak // 1024,
                        "max_rss_kib": max_rss_kib, "modules": len(sys.modules)}
            ''',
            [
                (
                    "",
                    """
                    The demo app for this unit's sections, in parts. Part 1: imports and state.
                    With `TRACE_MEMORY` set, `tracemalloc` starts **before** FastAPI is
                    imported, so the memory demo in 6.8.1 sees what the import costs each
                    process. `COUNTS` lives in the process; `REDIS` is shared when `REDIS_URL`
                    is set:
                    """,
                ),
                (
                    '@app.get("/health")',
                    """
                    Part 2: the health check, `/version` (the release named by `APP_VERSION`,
                    for the blue-green demo in 6.8.9), and `/whoami`, which reports the process
                    (process and host name) that answered and the client address and scheme
                    **as this app sees them** (a proxy changes both; 6.8.5):
                    """,
                ),
                (
                    '@app.get("/slow")',
                    """
                    Part 3: a slow route for the worker and shutdown demos, and two counters (in
                    memory, and in Redis when configured) for the scaling demo in 6.8.9:
                    """,
                ),
                ('@app.websocket("/ws")', "Part 4: a WebSocket echo, for proxying in 6.8.5:"),
                (
                    '@app.get("/memory")',
                    """
                    Part 5: `/memory`, the process's own view of its memory: Python allocations
                    traced since start-up and the peak resident set size (`ru_maxrss`):
                    """,
                ),
            ],
        ),
        md("Its pinned requirements (the same versions as the course environment):"),
        code(
            r"""
            %%writefile _scratch/phase6/deploy_demo/requirements.txt
            fastapi==0.163.1
            uvicorn==0.54.0
            websockets==17.4
            redis==8.1.0
            """
        ),
    ]


def _process_model_cells() -> list[NotebookNode]:
    """6.8.1 Process model."""
    return [
        md(
            """
            ### 6.8.1 Process model

            One Uvicorn process runs one event loop on one core; the GIL means threads do not
            add CPU parallelism for Python code (free-threaded builds aside). To use a machine,
            run **several processes**:

            | Option | What manages the processes | Notes |
            | --- | --- | --- |
            | `uvicorn --workers N` | Uvicorn's own supervisor (restarts dead workers) | simplest; reads `WEB_CONCURRENCY`; the Notes API image uses it |
            | `gunicorn -k uvicorn_worker.UvicornWorker -w N` | Gunicorn (mature process manager: timeouts, `max_requests`, graceful reloads) | the classic choice on VMs |
            | **one process per container**, N containers | the orchestrator (Kubernetes, ECS, Compose `--scale`) | preferred on Kubernetes: scaling, health and restarts per pod |

            **Sizing.** For async, I/O-bound APIs start with one process per CPU core and measure;
            CPU-heavy endpoints need more processes or a worker queue; memory per process (models,
            caches) can be the real limit. Three workers share one listening socket and the
            kernel hands each new connection to a waiting worker, so concurrent requests are
            spread over the processes (an idle server may keep serving from one):
            """
        ),
        code(
            r'''
            def busy_requests(base_url: str, count: int = 30) -> TallyCounter:
                """count concurrent 0.3 s requests; which process served each."""
                results: list[int] = []
                threads = [
                    threading.Thread(
                        target=lambda: results.append(
                            httpx.get(f"{base_url}/slow?seconds=0.3", timeout=10).json()["pid"]
                        )
                    )
                    for _ in range(count)
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
                return TallyCounter(results)


            with uvicorn_server("app:app", app_dir=DEMO_DIR, extra_args=["--workers", "3"]) as base_url:
                time.sleep(1.5)  # /health answered as soon as the first worker was up
                answered_by = busy_requests(base_url)
            print(f"{len(answered_by)} processes served 30 concurrent requests: {sorted(answered_by.values())}")
            print(f"this machine has {os.cpu_count()} logical CPUs")
            '''
        ),
        md(
            """
            **Under the hood: every worker is a whole interpreter.** `--workers 3` starts three
            separate processes, and each one imports Python, FastAPI, Pydantic and your app for
            itself. The `/memory` route asks each worker (with `TRACE_MEMORY=1`) how much memory
            `tracemalloc` saw it allocate since start-up and its peak resident set size. Twelve
            overlapping requests reach different workers:
            """
        ),
        code(
            r'''
            def memory_by_worker(base_url: str, requests: int = 12) -> dict[int, dict[str, int]]:
                """GET /memory concurrently (each holds 0.3 s); one answer per worker pid."""
                answers: list[dict[str, int]] = []

                def ask() -> None:
                    answers.append(httpx.get(f"{base_url}/memory?hold=0.3", timeout=10).json())

                threads = [threading.Thread(target=ask) for _ in range(requests)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
                return {answer["pid"]: answer for answer in answers}


            with uvicorn_server(
                "app:app", app_dir=DEMO_DIR, extra_args=["--workers", "3"], extra_env={"TRACE_MEMORY": "1"}
            ) as base_url:
                time.sleep(1.5)  # let all three workers finish importing
                workers = memory_by_worker(base_url)
            for pid, answer in sorted(workers.items()):
                traced, peak, rss = (answer[key] / 1024 for key in ("traced_kib", "peak_kib", "max_rss_kib"))
                print(
                    f"worker {pid}: tracemalloc {traced:5.1f} MiB (peak {peak:5.1f}), "
                    f"max RSS {rss:5.1f} MiB, {answer['modules']} modules"
                )
            total_rss = sum(answer["max_rss_kib"] for answer in workers.values()) / 1024
            print(f"{len(workers)} workers answered; together about {total_rss:.0f} MiB resident")
            '''
        ),
        md(
            """
            Each worker carries the same tens of MiB of modules and objects: memory grows with
            `workers × replicas`, which is why memory, not CPU, often decides how many processes
            fit on a machine. Pages loaded from the same files are shared by the operating
            system, so RSS figures overlap (the sum overstates the real total a little); Python
            objects are not shared, because reference counting writes to them. Gunicorn's
            `--preload` imports the app once before forking to share more pages; it helps less
            in Python than in C programs for the same reason.
            """
        ),
        md(
            """
            Gunicorn is not a course dependency; the cell checks for it and shows its
            configuration:
            """
        ),
        code(
            r'''
            GUNICORN_CONF = """
            # gunicorn.conf.py: gunicorn -c gunicorn.conf.py notes_api.main:app
            import multiprocessing
            bind = "0.0.0.0:8000"
            workers = multiprocessing.cpu_count()
            worker_class = "uvicorn_worker.UvicornWorker"
            graceful_timeout = 20       # like uvicorn --timeout-graceful-shutdown
            max_requests = 10_000       # recycle workers (slow memory leaks)
            max_requests_jitter = 1_000
            forwarded_allow_ips = "*"   # behind a proxy only
            """
            installed = all(importlib.util.find_spec(name) for name in ("gunicorn", "uvicorn_worker"))
            print(
                "gunicorn + uvicorn-worker:",
                "installed" if installed else "SKIP (not installed; Uvicorn's --workers is used instead)",
            )
            print(textwrap.dedent(GUNICORN_CONF).strip())
            '''
        ),
        md(
            """
            **Database connections.** Every process has its own SQLAlchemy pool, so the total is
            `replicas × processes × (pool_size + max_overflow)` (plus the workers, the migration
            job and your own `psql`). PostgreSQL's `max_connections` (100 by default) caps it; each
            connection costs memory on the server. The budget of a few layouts, against the
            unit's PostgreSQL container:
            """
        ),
        code(
            r'''
            def connection_budget(
                replicas: int, processes: int, pool_size: int = 5, max_overflow: int = 10
            ) -> int:
                """The most connections the API can open."""
                return replicas * processes * (pool_size + max_overflow)


            async def server_max_connections() -> int:
                """SHOW max_connections on the unit's PostgreSQL (the default without Docker)."""
                url = start_shared_postgres()
                if url is None:
                    return 100
                connection = await asyncpg.connect(url.replace("postgresql+asyncpg", "postgresql"))
                try:
                    return int(await connection.fetchval("SHOW max_connections"))
                finally:
                    await connection.close()


            limit = await server_max_connections()
            for replicas, processes, pool, overflow in [
                (1, 2, 5, 10),
                (3, 2, 5, 10),
                (6, 4, 5, 10),
                (6, 4, 2, 3),
            ]:
                needed = connection_budget(replicas, processes, pool, overflow)
                verdict = (
                    "fits (under 80 %)" if needed <= limit * 0.8 else "over 80 %: shrink pools or add PgBouncer"
                )
                print(
                    f"{replicas} replicas x {processes} processes x "
                    f"({pool}+{overflow}) = {needed:4} of {limit}: {verdict}"
                )
            '''
        ),
    ]


def _container_cells() -> list[NotebookNode]:
    """6.8.2 Containers."""
    return [
        md(
            """
            ### 6.8.2 Containers

            | Practice | Why |
            | --- | --- |
            | **multi-stage** build: compile/install in one stage, copy only results to the runtime stage | no compilers, caches or build tools in production |
            | dependencies before code (`COPY uv.lock` → install → `COPY src`) | layer caching: a code change does not reinstall packages |
            | `.dockerignore` (or an allow-list) | small context; no `.venv`, `.git` or secrets in the image |
            | `python:3.X-slim` (glibc) | small, and every wheel works (Alpine's musl often means compiling) |
            | a **non-root** user, read-only filesystem at run time | a compromised process can do less |
            | exec-form `CMD ["uvicorn", ...]` | Uvicorn is PID 1 and receives SIGTERM (a shell in between does not forward it) |
            | pinned versions, `HEALTHCHECK` | reproducible builds; the platform knows when the app is up |

            Two images of the demo app. The naive one copies everything, installs with pip, runs
            as root and starts through a shell:
            """
        ),
        code(
            r"""
            %%writefile _scratch/phase6/deploy_demo/Dockerfile.naive
            FROM python:3.15-slim
            WORKDIR /app
            COPY . .
            RUN pip install -r requirements.txt
            CMD uvicorn app:app --host 0.0.0.0 --port 8000
            """
        ),
        md(
            """
            The optimized one installs into a virtual environment in a build stage (uv, with a
            cache mount), copies only that environment and the app into a clean runtime stage,
            and runs as an unprivileged user with an exec-form command:
            """
        ),
        code(
            r"""
            %%writefile _scratch/phase6/deploy_demo/Dockerfile
            FROM ghcr.io/astral-sh/uv:0.13.5 AS uv

            FROM python:3.15-slim AS build
            COPY --from=uv /uv /usr/local/bin/uv
            ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
            COPY requirements.txt /tmp/requirements.txt
            RUN --mount=type=cache,target=/root/.cache/uv \
                uv venv /venv && uv pip install --python /venv/bin/python -r /tmp/requirements.txt

            FROM python:3.15-slim AS runtime
            RUN useradd --system --uid 10001 --no-create-home app
            COPY --from=build /venv /venv
            COPY --chown=app app.py /app/app.py
            WORKDIR /app
            ENV PATH="/venv/bin:$PATH" PYTHONUNBUFFERED=1
            USER app
            HEALTHCHECK --interval=5s --timeout=2s CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health')"]
            CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
            """
        ),
        md(
            "Build both (the first build downloads the base images and packages; later builds are cached):"
        ),
        code(
            r'''
            def build_demo_images() -> None:
                """Build both images and compare them."""
                for tag, dockerfile in (
                    ("deploy-demo:naive", "Dockerfile.naive"),
                    ("deploy-demo:optimized", "Dockerfile"),
                ):
                    started = time.perf_counter()
                    docker("build", "--quiet", "--file", dockerfile, "--tag", tag, ".")
                    user = docker("run", "--rm", "--entrypoint", "id", tag, "-un")
                    print(
                        f"{tag:22} {image_size_mb(tag):6.0f} MB, user {user:5}, "
                        f"built in {time.perf_counter() - started:4.1f} s"
                    )


            if HAS_DOCKER:
                (DEMO_DIR / "scratch-notes.txt").write_text("local notes that should not be in an image\n")
                build_demo_images()
            else:
                print("SKIP the image builds: Docker is not available")
            '''
        ),
        md(
            """
            The naive image also contains pip's download cache and every file in the folder (the
            stray `scratch-notes.txt` included). **Layer caching**: change only the code and
            rebuild; the dependency layer is reused:
            """
        ),
        code(
            r"""
            if HAS_DOCKER:
                app_file = DEMO_DIR / "app.py"
                original = app_file.read_text()
                app_file.write_text(original + "\n# a code change\n")
                started = time.perf_counter()
                build_log = docker("build", "--progress=plain", "--tag", "deploy-demo:optimized", ".")
                app_file.write_text(original)
                docker("build", "--quiet", "--tag", "deploy-demo:optimized", ".")
                cached_steps = len(re.findall(r"CACHED", build_log))
                print(
                    f"rebuild after a code change: {time.perf_counter() - started:.1f} "
                    f"s, {cached_steps} steps from cache"
                )
                print(
                    "in the naive image:",
                    docker("run", "--rm", "--entrypoint", "ls", "deploy-demo:naive", "/app").split(),
                )
            """
        ),
        md(
            """
            **PID 1 and signals.** `docker stop` sends SIGTERM, waits (here 3 s), then SIGKILL.
            With the shell-form `CMD`, `/bin/sh` is PID 1 and does not pass SIGTERM on, so the app
            is killed after the timeout; with the exec form Uvicorn gets the signal and shuts down
            cleanly at once:
            """
        ),
        code(
            r'''
            def stop_time(image: str) -> float:
                """Seconds docker stop needs for a running container of image."""
                container = docker("run", "--detach", image)
                time.sleep(2)  # let Uvicorn start
                started = time.perf_counter()
                docker("stop", "--time", "3", container)
                elapsed = time.perf_counter() - started
                docker("rm", container)
                return elapsed


            if HAS_DOCKER:
                for image in ("deploy-demo:naive", "deploy-demo:optimized"):
                    print(f"{image:22} stopped in {stop_time(image):.1f} s")
            '''
        ),
    ]


def _compose_cells() -> list[NotebookNode]:
    """6.8.3 Docker Compose stacks."""
    return [
        md(
            """
            ### 6.8.3 Docker Compose stacks

            Compose describes a whole stack in one file. The parts that matter for an API:

            | Feature | Use |
            | --- | --- |
            | `depends_on: {db: {condition: service_healthy}}` | start the API only after the database answers its health check |
            | `condition: service_completed_successfully` | wait for a **one-off job** (migrations) to exit 0 |
            | `healthcheck` | `docker compose up --wait` returns when everything is healthy |
            | YAML anchors (`x-app: &app`, `<<: *app`) | share settings between api, worker and migrate |
            | `expose` vs `ports` | reachable inside the network vs published on the host |
            | volumes, `secrets`, `read_only`, `tmpfs` | data that survives, secrets as files, an immutable container |

            A small stack: the demo app twice behind nothing yet, Redis, and an `init` job the
            apps wait for:
            """
        ),
        code(
            r"""
            %%writefile _scratch/phase6/deploy_demo/compose.yaml
            # The deployment demo stack: docker compose -p deploy-demo up -d --wait
            x-app: &app
              image: deploy-demo:optimized
              environment:
                REDIS_URL: redis://redis:6379/0
              depends_on:
                redis: { condition: service_healthy }
                init: { condition: service_completed_successfully }

            services:
              redis:
                image: redis:7.4
                healthcheck: { test: ["CMD", "redis-cli", "ping"], interval: 2s, timeout: 3s, retries: 15 }

              init: # a one-off job, like a migration
                image: redis:7.4
                command: ["redis-cli", "-h", "redis", "set", "demo:hits", "0"]
                depends_on:
                  redis: { condition: service_healthy }

              app:
                <<: *app
                environment: { REDIS_URL: "redis://redis:6379/0", FORWARDED_ALLOW_IPS: "*" }

              app_untrusting: # the same app, but it does not trust proxy headers
                <<: *app

              proxy:
                image: caddy:2
                ports: ["127.0.0.1:${DEMO_HTTPS_PORT:-58444}:443"]
                volumes: ["./Caddyfile:/etc/caddy/Caddyfile:ro"]
                depends_on:
                  app: { condition: service_healthy }
                  app_untrusting: { condition: service_healthy }
            """
        ),
        md(
            """
            The proxy and its Caddyfile belong to 6.8.5; Compose needs the file to exist. One
            route forwards to each app:
            """
        ),
        code(
            r"""
            %%writefile _scratch/phase6/deploy_demo/Caddyfile
            localhost {
                handle_path /trusting/* {
                    reverse_proxy app:8000
                }
                handle_path /untrusting/* {
                    reverse_proxy app_untrusting:8000
                }
            }
            """
        ),
        md(
            """
            Up, with `--wait` (it returns when every health check passes and the job has
            finished), then the state of each service. An `atexit` hook takes the stack down
            when the kernel stops, so a cell that fails before the *take it down* cell in 6.8.5
            cannot leave containers and ports behind:
            """
        ),
        code(
            r'''
            DEMO_STACK = ["compose", "-p", "deploy-demo"]


            def remove_demo_stack() -> None:
                """compose down -v for the demo stack (also the exit hook, if a later cell fails)."""
                docker(*DEMO_STACK, "down", "-v", "--remove-orphans", check=False)


            if HAS_DOCKER:
                atexit.register(remove_demo_stack)  # registered before up: a failed up is cleaned too
                started = time.perf_counter()
                docker(*DEMO_STACK, "up", "-d", "--wait")
                print(f"stack up and healthy in {time.perf_counter() - started:.1f} s")
                for line in docker(
                    *DEMO_STACK, "ps", "-a", "--format", "{{.Service}} {{.State}} {{.Health}} {{.ExitCode}}"
                ).splitlines():
                    print("  ", line)
            else:
                print("SKIP the Compose demo: Docker is not available")
            '''
        ),
    ]


def _config_cells() -> list[NotebookNode]:
    """6.8.4 Configuration and secrets."""
    return [
        md(
            """
            ### 6.8.4 Configuration and secrets

            The **twelve-factor app** rules, and where the Notes API follows them:

            | Factor | Rule | Notes API v7 |
            | --- | --- | --- |
            | Codebase | one repo, many deploys | one image, promoted from CI to every environment |
            | Dependencies | declared and isolated | `uv.lock`, `uv sync --frozen` in the image |
            | **Config** | in the environment | `NOTES_*` variables, validated by pydantic-settings |
            | Backing services | attached resources (URLs) | `NOTES_DATABASE_URL`, `NOTES_REDIS_URL` |
            | Build, release, run | strictly separate stages | build the image once; release = image + config; run |
            | Processes | stateless, share nothing | sessions, rate limits, caches in Redis; files in object storage |
            | Port binding | the app exports HTTP itself | Uvicorn on port 8000 |
            | Concurrency | scale out with processes | `WEB_CONCURRENCY`, replicas |
            | Disposability | fast start, graceful stop | lifespan, `--timeout-graceful-shutdown` |
            | Dev/prod parity | the same backing services everywhere | Compose runs PostgreSQL and Redis locally |
            | Logs | event streams to stdout | structlog JSON to stdout |
            | Admin processes | one-off tasks in the same image | `alembic upgrade head` as the `migrate` job |

            **Secrets** never go into the image, the repository or a log. Platforms inject them as
            environment variables or, better, as files (Docker/Compose secrets, Kubernetes
            Secrets, mounted at `/run/secrets`), which do not show up in `docker inspect` or child
            process environments. pydantic-settings reads both; the order of precedence, shown
            with a throwaway settings class:
            """
        ),
        code(
            r'''
            class DemoSettings(BaseSettings):
                """Three settings from four possible sources."""

                model_config = SettingsConfigDict(env_prefix="DEMO_", env_file=PHASE6_DIR / "demo.env")
                api_key: SecretStr = SecretStr("default-key")
                region: str = "default-region"
                workers: int = 1


            secrets_dir = PHASE6_DIR / "demo_secrets"
            secrets_dir.mkdir(exist_ok=True)
            (secrets_dir / "demo_api_key").write_text("key-from-a-secret-file")
            (secrets_dir / "demo_region").write_text("region-from-a-secret-file")
            (PHASE6_DIR / "demo.env").write_text("DEMO_REGION=region-from-dotenv\nDEMO_WORKERS=2\n")
            with temporary_env(DEMO_WORKERS="4"):
                loaded = DemoSettings(_secrets_dir=secrets_dir)
            print(f"api_key: {loaded.api_key.get_secret_value()!r:28} (secret file beats the default)")
            print(f"region : {loaded.region!r:28} (.env beats the secret file)")
            print(f"workers: {loaded.workers!r:28} (an environment variable beats .env)")
            print("repr hides secrets:", loaded)
            '''
        ),
    ]


def _proxy_cells() -> list[NotebookNode]:
    """6.8.5 Reverse proxy and TLS."""
    return [
        md(
            """
            ### 6.8.5 Reverse proxy and TLS

            A reverse proxy terminates TLS, serves or caches static files, limits request sizes,
            balances replicas and hides internal routes. The usual three:

            | | Caddy | Nginx | Traefik |
            | --- | --- | --- | --- |
            | TLS certificates | **automatic** (Let's Encrypt; a local CA for `localhost`) | external (certbot, a secret store) | automatic (ACME) |
            | Configuration | a short `Caddyfile` | `nginx.conf` (explicit, very flexible) | labels on containers / Kubernetes CRDs |
            | WebSockets | work by default | need `Upgrade` / `Connection` headers and long timeouts | work by default |
            | Good for | small stacks, quick HTTPS | high traffic, fine control, caching | dynamic container platforms |

            **Proxy headers.** Behind a proxy the app sees the proxy's address and plain HTTP. The
            proxy adds `X-Forwarded-For` (the client) and `X-Forwarded-Proto` (https); Uvicorn
            applies them with `--proxy-headers`, but **only for proxies it trusts**
            (`FORWARDED_ALLOW_IPS`), since anyone can send those headers. Both demo apps sit
            behind the same Caddy; only `app` trusts it:
            """
        ),
        code(
            r'''
            def through_proxy(path: str) -> dict[str, Any]:
                """GET through Caddy's HTTPS port (its local CA is not in our trust store)."""
                port = os.environ.get("DEMO_HTTPS_PORT", "58444")
                with httpx.Client(
                    base_url=f"https://localhost:{port}", verify=False, trust_env=False
                ) as client:
                    return client.get(path).json()


            if HAS_DOCKER:
                for route in ("/trusting/whoami", "/untrusting/whoami"):
                    seen = through_proxy(route)
                    print(
                        f"{route:20} scheme={seen['scheme']:5} client={seen['client']:12} "
                        f"X-Forwarded-For={seen['forwarded'].get('x-forwarded-for')}"
                    )
            '''
        ),
        md(
            """
            Only the trusting app knows the request came over HTTPS (so redirects and `url_for`
            produce `https://` links) and from which client (so rate limits apply per user, not
            to the proxy). WebSockets pass through Caddy unchanged:
            """
        ),
        code(
            r'''
            def websocket_through_proxy() -> str:
                """One message over wss:// through Caddy."""
                import ssl

                from websockets.sync.client import connect

                insecure = ssl.create_default_context()
                insecure.check_hostname, insecure.verify_mode = False, ssl.CERT_NONE
                port = os.environ.get("DEMO_HTTPS_PORT", "58444")
                with connect(f"wss://localhost:{port}/trusting/ws", ssl=insecure) as socket_connection:
                    socket_connection.send("hello through TLS")
                    return socket_connection.recv(timeout=5)


            if HAS_DOCKER:
                print(websocket_through_proxy())
            '''
        ),
        md(
            """
            **Nginx** needs the certificate files and explicit WebSocket and streaming settings
            (the Notes API ships `deploy/nginx.conf`). `nginx -t` validates a configuration; here
            with a self-signed certificate made by `openssl` for the test:
            """
        ),
        code(
            r'''
            NGINX_CONF = """
            events {}
            http {
                map $http_upgrade $connection_upgrade { default upgrade; "" close; }
                server {
                    listen 443 ssl;
                    ssl_certificate /etc/nginx/tls/cert.pem;
                    ssl_certificate_key /etc/nginx/tls/key.pem;
                    location / {
                        proxy_pass http://app:8000;
                        proxy_http_version 1.1;
                        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
                        proxy_set_header X-Forwarded-Proto $scheme;
                        proxy_set_header Upgrade $http_upgrade;
                        proxy_set_header Connection $connection_upgrade;
                        proxy_buffering off;
                    }
                }
            }
            """
            tls_dir = DEMO_DIR / "tls"
            tls_dir.mkdir(exist_ok=True)
            (DEMO_DIR / "nginx.conf").write_text(textwrap.dedent(NGINX_CONF))
            print("nginx.conf:", len(textwrap.dedent(NGINX_CONF).strip().splitlines()), "lines")
            '''
        ),
        md(
            "A self-signed certificate for it, then `nginx -t` in the official image checks the config:"
        ),
        code(
            r"""
            if HAS_DOCKER and HAS_OPENSSL:
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
                        "-subj",
                        "/CN=localhost",
                        "-keyout",
                        str(tls_dir / "key.pem"),
                        "-out",
                        str(tls_dir / "cert.pem"),
                    ],
                    capture_output=True,
                    check=True,
                )
                (tls_dir / "key.pem").chmod(0o644)
                print(
                    docker(
                        "run",
                        "--rm",
                        "--add-host",
                        "app:127.0.0.1",
                        "-v",
                        f"{DEMO_DIR / 'nginx.conf'}:/etc/nginx/nginx.conf:ro",
                        "-v",
                        f"{tls_dir}:/etc/nginx/tls:ro",
                        "nginx:1.27-alpine",
                        "nginx",
                        "-t",
                    ).splitlines()[-1]
                )
            else:
                print("SKIP nginx -t: needs Docker and openssl")
            """
        ),
        md(
            """
            **Traefik** is configured by the platform instead: in Compose, labels on the service
            (`traefik.http.routers.api.rule=Host(\\`notes.example\\`)`,
            `traefik.http.routers.api.tls.certresolver=letsencrypt`,
            `traefik.http.services.api.loadbalancer.server.port=8000`) and Traefik discovers the
            containers through the Docker API; in Kubernetes, `IngressRoute` resources. Its
            **file provider** takes the same model as YAML, which makes the parts visible: a
            *static* configuration (entry points, providers) and a *dynamic* one (routers that
            match requests, services that balance them over servers, with health checks). Both,
            built as data:
            """
        ),
        code(
            r"""
            TRAEFIK_IMAGE = "traefik:v3"
            TRAEFIK_DIR = DEMO_DIR / "traefik"
            TRAEFIK_DIR.mkdir(exist_ok=True)
            traefik_static = {
                "entryPoints": {"web": {"address": ":80"}},
                "providers": {"file": {"filename": "/etc/traefik/dynamic.yml"}},
                "log": {"level": "ERROR"},
            }
            traefik_dynamic = {
                "http": {
                    "routers": {"demo": {"rule": "PathPrefix(`/`)", "entryPoints": ["web"], "service": "demo"}},
                    "services": {
                        "demo": {
                            "loadBalancer": {
                                "servers": [{"url": "http://app:8000"}, {"url": "http://app_untrusting:8000"}],
                                "healthCheck": {"path": "/health", "interval": "2s", "timeout": "1s"},
                            }
                        }
                    },
                }
            }
            (TRAEFIK_DIR / "traefik.yml").write_text(yaml.safe_dump(traefik_static, sort_keys=False))
            (TRAEFIK_DIR / "dynamic.yml").write_text(yaml.safe_dump(traefik_dynamic, sort_keys=False))
            print((TRAEFIK_DIR / "dynamic.yml").read_text())
            """
        ),
        md(
            """
            With Docker, Traefik runs for a moment on the demo stack's network (the first run
            pulls `traefik:v3`; no Docker or no network prints SKIP). Four requests are balanced
            round-robin over the two apps, and the proxy-header lesson repeats: only `app`
            trusts the proxy, so only it reports the real client from `X-Forwarded-For`:
            """
        ),
        code(
            r'''
            def through_traefik(requests: int = 4) -> list[dict[str, Any]]:
                """Start Traefik on the demo network, send some requests, always remove it."""
                name, port = "deploy-demo-traefik", free_port()
                docker("rm", "-f", name, check=False)
                docker(
                    *["run", "-d", "--name", name, "--network", "deploy-demo_default"],
                    *["-p", f"127.0.0.1:{port}:80", "-v", f"{TRAEFIK_DIR}:/etc/traefik:ro"],
                    TRAEFIK_IMAGE,
                )
                try:
                    base_url = f"http://127.0.0.1:{port}"
                    with httpx.Client(base_url=base_url, trust_env=False, timeout=3) as client:
                        deadline = time.monotonic() + 30
                        while True:  # wait until both servers passed a health check
                            with contextlib.suppress(httpx.HTTPError):
                                if len({client.get("/whoami").json()["host"] for _ in range(4)}) == 2:
                                    break
                            if time.monotonic() > deadline:
                                raise TimeoutError("Traefik did not route to both apps within 30 s")
                            time.sleep(0.5)
                        return [client.get("/whoami").json() for _ in range(requests)]
                finally:
                    docker("rm", "-f", name, check=False)


            if HAS_DOCKER:
                try:
                    for seen in through_traefik():
                        print(
                            f"host={seen['host'][:12]}  client={seen['client']:12} "
                            f"X-Forwarded-For={seen['forwarded'].get('x-forwarded-for')}"
                        )
                except (RuntimeError, TimeoutError) as error:
                    print(f"SKIP Traefik: {str(error).splitlines()[-1][:150]}")
            else:
                print("SKIP Traefik: Docker is not available")
            '''
        ),
        md(
            """
            Two container host names alternate: Traefik balanced per request. The Notes API
            uses Caddy (`deploy/Caddyfile`); Nginx and Traefik are the alternatives above.

            The demo stack has served its purpose; take it down (`-v` also removes its volumes)
            and cancel its exit hook:
            """
        ),
        code(
            r"""
            if HAS_DOCKER:
                remove_demo_stack()
                atexit.unregister(remove_demo_stack)
                print("demo stack removed; containers left:", docker(*DEMO_STACK, "ps", "-aq") or "none")
            """
        ),
    ]


def _cicd_cells() -> list[NotebookNode]:
    """6.8.6 CI/CD."""
    return [
        md(
            """
            ### 6.8.6 CI/CD

            Continuous integration checks every change; continuous delivery turns a green commit
            into a deployable artifact, and deployment ships it. The stages of the Notes API
            pipeline, and the GitHub Actions features behind them:

            | Stage | Does | GitHub Actions |
            | --- | --- | --- |
            | lint | `ruff check`, `ruff format --check` | a job; `setup-uv` with a cache keyed on `uv.lock` |
            | type-check | `mypy` | a parallel job |
            | test | pytest against PostgreSQL and Redis | **service containers** with health checks |
            | build | the image, plus a smoke test | `needs: [lint, types, test]`; the image travels as an **artifact** |
            | scan | Trivy (OS packages, wheels), `pip-audit` (locked deps) | fail on fixable HIGH/CRITICAL |
            | push | to a registry (GHCR) | `permissions: packages: write`, `GITHUB_TOKEN`; only `main` and release tags |
            | deploy | migrate, then roll out | an **environment** with required reviewers and its own secrets |

            Also: actions pinned to commit SHAs, `concurrency` to cancel superseded runs, path
            filters, and no long-lived cloud keys (OIDC federation where the target supports it).
            Jobs form a graph; `graphlib.TopologicalSorter` (standard library) computes an order
            and the jobs that can run side by side:
            """
        ),
        code(
            r"""
            PIPELINE_NEEDS = {
                "lint": [],
                "types": [],
                "test": [],
                "build": ["lint", "types", "test"],
                "scan": ["build"],
                "push": ["scan"],
                "deploy": ["push"],
            }
            sorter = graphlib.TopologicalSorter(PIPELINE_NEEDS)
            sorter.prepare()
            wave = 1
            while sorter.is_active():
                ready = sorted(sorter.get_ready())
                print(f"wave {wave}: {ready}")
                sorter.done(*ready)
                wave += 1
            print(
                "act (runs workflows locally in Docker):",
                "installed" if shutil.which("act") else "not installed (optional)",
            )
            """
        ),
        md(
            """
            GitHub runs the workflow; the steps themselves are ordinary commands, so the Notes API
            section runs the lint, type-check, test, build and smoke-test steps locally too. A
            cycle in `needs` is a configuration error the sorter reports:
            """
        ),
        code(
            r"""
            print(
                raised_message(
                    lambda: list(
                        graphlib.TopologicalSorter({"build": ["test"], "test": ["build"]}).static_order()
                    )
                )
            )
            """
        ),
        md(
            """
            **The scan stage, locally.** CI scans every image with Trivy (the Notes API
            workflow runs `aquasec/trivy:0.58.1` and fails on fixable HIGH/CRITICAL findings).
            The first scan downloads Trivy and its vulnerability database (a few hundred MB), so
            this cell runs only when Trivy is already here (the `trivy` CLI or the image) or
            when you set `RUN_TRIVY=1` before starting Jupyter; otherwise it prints SKIP. It
            scans the optimized demo image from 6.8.2:
            """
        ),
        code(
            r'''
            TRIVY_IMAGE = "aquasec/trivy:0.58.1"  # the version the Notes API workflow uses


            def trivy_command() -> list[str] | None:
                """The Trivy CLI, the Trivy container (present, or RUN_TRIVY=1), or None."""
                if shutil.which("trivy"):
                    return ["trivy"]
                if not HAS_DOCKER:
                    return None
                if docker("image", "ls", "-q", TRIVY_IMAGE) or os.environ.get("RUN_TRIVY") == "1":
                    mounts = ["-v", "/var/run/docker.sock:/var/run/docker.sock"]  # reads local images
                    mounts += ["-v", "trivy-cache:/root/.cache"]  # the database, kept between runs
                    return ["docker", "run", "--rm", *mounts, TRIVY_IMAGE]
                return None


            def trivy_summary(image: str, command: list[str]) -> str:
                """Fixable HIGH/CRITICAL findings in image, counted by severity, plus the first few."""
                options = ["--quiet", "--scanners", "vuln", "--severity", "HIGH,CRITICAL", "--ignore-unfixed"]
                scan = subprocess.run(
                    [*command, "image", *options, "--format", "json", image],
                    capture_output=True,
                    text=True,
                    timeout=600,
                )
                if scan.returncode != 0:
                    return f"SKIP Trivy: {(scan.stderr.strip().splitlines() or ['failed'])[-1][:150]}"
                findings = [
                    finding
                    for result in json.loads(scan.stdout).get("Results", [])
                    for finding in result.get("Vulnerabilities") or []
                ]
                counts = TallyCounter(finding["Severity"] for finding in findings)
                lines = [f"{image}: {dict(counts) or 'no fixable HIGH/CRITICAL findings'}"]
                for item in findings[:5]:
                    package = f"{item['PkgName']} {item['InstalledVersion']} -> {item['FixedVersion']}"
                    lines.append(f"  {item['VulnerabilityID']:20} {package}")
                return "\n".join(lines)


            trivy = trivy_command()
            if trivy is None:
                print("SKIP Trivy: not installed and RUN_TRIVY is not 1 (CI scans every image)")
            elif not docker("image", "ls", "-q", "deploy-demo:optimized"):
                print("SKIP Trivy: the 6.8.2 image deploy-demo:optimized was not built")
            else:
                print(trivy_summary("deploy-demo:optimized", trivy))
            '''
        ),
    ]


def _migration_cells() -> list[NotebookNode]:
    """6.8.7 Migrations on deploy."""
    return [
        md(
            """
            ### 6.8.7 Migrations on deploy

            | Where migrations run | Risk |
            | --- | --- |
            | in the app's startup | N replicas race to migrate; a slow migration blocks every start |
            | **one-off job** before the rollout (Compose `migrate`, a Kubernetes `Job`, a PaaS `release` phase) | the standard: one runner, the deploy stops if it fails |
            | an init container per pod | still N runners; needs a lock (Alembic in a PostgreSQL advisory lock) |

            During a rolling deploy **old and new code run at the same time** against the same
            schema, so every migration must work with both. Breaking changes are split
            (**expand / contract**): add the new shape, write both, backfill, switch reads, and
            remove the old shape only once no old code runs. Renaming `full_name` into
            `first_name` + `last_name`: v1 reads `full_name`; v2 also writes the new columns; v3
            reads only the new ones. Both readers are checked after every step:
            """
        ),
        code(
            r'''
            schema_db = sqlite3.connect(":memory:")
            schema_db.execute("CREATE TABLE people (id INTEGER PRIMARY KEY, full_name TEXT)")
            schema_db.execute("INSERT INTO people (full_name) VALUES ('Asha Rao'), ('Ravi Kumar')")


            def old_code_reads() -> list[str]:
                """v1 of the app: reads full_name."""
                return [row[0] for row in schema_db.execute("SELECT full_name FROM people ORDER BY id")]


            def new_code_reads() -> list[str]:
                """v3 of the app: reads only the split columns (deployed after the backfill)."""
                rows = schema_db.execute("SELECT first_name, last_name FROM people ORDER BY id")
                return [f"{first} {last}" for first, last in rows]


            def new_code_inserts(first: str, last: str) -> None:
                """v2 writes both shapes (and still reads full_name, like v1)."""
                schema_db.execute(
                    "INSERT INTO people (first_name, last_name, full_name) VALUES (?, ?, ?)",
                    (first, last, f"{first} {last}"),
                )
            '''
        ),
        md("The steps of the deploy, and what each version of the code sees:"),
        code(
            r'''
            def report(step: str) -> None:
                """Run both versions of the code against the current schema."""
                outcomes = []
                for name, reader in (("v1/v2", old_code_reads), ("v3", new_code_reads)):
                    try:
                        outcomes.append(f"{name}: {reader()}")
                    except sqlite3.OperationalError as error:
                        outcomes.append(f"{name}: BROKEN ({error})")
                print(f"{step:42} {' | '.join(outcomes)}")


            schema_db.execute("ALTER TABLE people ADD COLUMN first_name TEXT")
            schema_db.execute("ALTER TABLE people ADD COLUMN last_name TEXT")
            report("1 expand: nullable columns added")
            new_code_inserts("Meera", "Iyer")
            report("2 deploy v2: writes both shapes")
            schema_db.execute(
                "UPDATE people SET first_name = substr(full_name, 1, instr(full_name, ' ') - 1), "
                "last_name = substr(full_name, instr(full_name, ' ') + 1) WHERE first_name IS NULL"
            )
            report("3 backfill old rows")
            schema_db.execute("ALTER TABLE people DROP COLUMN full_name")
            report("4 contract (only after v1 is gone everywhere)")
            '''
        ),
        md(
            """
            Reading the new columns before the backfill gives `None None` for old rows, so v3
            (which reads them) ships only after step 3; the contract step breaks only v1, which
            is why it ships last, in a later release.
            Alembic expresses each step as its own revision; the Notes API's `0004` migration used
            the same pattern (nullable `owner_id`, backfill, then `NOT NULL`).
            """
        ),
    ]


def _targets_cells() -> list[NotebookNode]:
    """6.8.8 Deployment targets."""
    return [
        md(
            """
            ### 6.8.8 Deployment targets

            | Target | You manage | Scaling | The worker | Good for |
            | --- | --- | --- | --- | --- |
            | **VM** (systemd + Caddy/Nginx, or Compose) | OS, patches, process manager, TLS | bigger machine, or more VMs behind a load balancer | another systemd unit / Compose service | small teams, predictable load, lowest cost |
            | **PaaS** (Heroku, Render, Fly.io, Railway) | the app; a `Procfile` (`web`, `worker`, `release`) | a slider / autoscaling | a `worker` process type | getting started fast |
            | **Cloud Run / App Runner** (serverless containers) | the image and settings | per request, to zero | separately (CPU only during requests) | spiky HTTP traffic |
            | **ECS / Fargate** | task definitions, services, load balancer | service autoscaling | its own ECS service | AWS shops |
            | **Kubernetes** | manifests or Helm charts (and possibly the cluster) | HorizontalPodAutoscaler | its own Deployment | many services, platform teams |

            Kubernetes basics in one object: a **Deployment** keeps N **Pods** (containers) running
            from a template, replaces them gradually on change (rolling update), restarts them per
            the probes; a **Service** gives them one address; **ConfigMaps** and **Secrets** hold
            configuration; a **Job** runs to completion (migrations). A minimal Deployment, built
            as data:
            """
        ),
        code(
            r'''
            def deployment(name: str, image: str, replicas: int, port: int) -> dict[str, Any]:
                """A minimal Kubernetes Deployment with probes and resources."""
                probe = lambda path: {"httpGet": {"path": path, "port": port}, "periodSeconds": 5}  # noqa: E731
                container = {
                    "name": name,
                    "image": image,
                    "ports": [{"containerPort": port}],
                    "readinessProbe": probe("/health/ready"),
                    "livenessProbe": probe("/health/live"),
                    "resources": {
                        "requests": {"cpu": "250m", "memory": "256Mi"},
                        "limits": {"memory": "512Mi"},
                    },
                }
                return {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "metadata": {"name": name},
                    "spec": {
                        "replicas": replicas,
                        "selector": {"matchLabels": {"app": name}},
                        "template": {
                            "metadata": {"labels": {"app": name}},
                            "spec": {"containers": [container]},
                        },
                    },
                }


            manifest = yaml.safe_dump(
                deployment("notes-api", "ghcr.io/example/notes-api:0.7.0", 3, 8000), sort_keys=False
            )
            print(manifest)
            '''
        ),
        md(
            """
            With `kubectl` and a cluster context, a client-side dry run validates the manifest
            (even `--dry-run=client` asks the API server which resource types exist):
            """
        ),
        code(
            r"""
            kubectl = shutil.which("kubectl")
            has_cluster = (
                kubectl is not None
                and subprocess.run([kubectl, "config", "current-context"], capture_output=True).returncode == 0
            )
            if has_cluster:
                dry_run = subprocess.run(
                    [kubectl, "apply", "--dry-run=client", "-f", "-"],
                    input=manifest,
                    capture_output=True,
                    text=True,
                )
                print((dry_run.stdout or dry_run.stderr).strip())
            else:
                reason = "no cluster context configured" if kubectl else "kubectl not installed"
                print(f"SKIP kubectl dry run: {reason}; the Notes API's manifests are checked by its tests")
            """
        ),
        md(
            """
            **Where the other targets appear.** The Notes API v7 files at the end of this unit
            write one configuration per target: Kubernetes manifests (`deploy/k8s/`), a
            hardened **systemd** unit for a plain VM (`deploy/systemd/notes-api.service`) and a
            **Cloud Run** service (`deploy/cloudrun/service.yaml`, a Knative manifest). **ECS /
            Fargate** takes the same facts (image, command, port, environment, secrets, health
            check, CPU and memory) in a task definition, as the Cloud Run file's header comment
            notes. The **VM with Compose** path is the one the Phase 6 Project deploys for
            real.
            """
        ),
    ]


def _zero_downtime_cells() -> list[NotebookNode]:
    """6.8.9 Zero downtime and scaling."""
    return [
        md(
            """
            ### 6.8.9 Zero downtime and scaling

            **Graceful shutdown.** To stop a container the platform sends SIGTERM, waits a grace
            period, then SIGKILL. Uvicorn on SIGTERM stops accepting connections, lets requests in
            flight finish (up to `--timeout-graceful-shutdown`), runs the lifespan shutdown (close
            pools, flush spans) and exits. A request that started before the signal still
            completes:
            """
        ),
        code(
            r'''
            def graceful_shutdown_demo() -> dict[str, object]:
                """Start Uvicorn, begin a 1.5 s request, send SIGTERM, see what happens.

                The finally block kills the server if anything fails before it has exited.
                """
                port = free_port()
                server = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "app:app",
                        "--port",
                        str(port),
                        "--timeout-graceful-shutdown",
                        "10",
                        "--log-level",
                        "warning",
                    ],
                    cwd=DEMO_DIR,
                    env=CHILD_ENV,
                )
                base_url = f"http://127.0.0.1:{port}"
                try:
                    wait_for_health(base_url + "/health", server, 15)
                    results: dict[str, object] = {}
                    request = threading.Thread(
                        target=lambda: results.update(
                            reply=httpx.get(base_url + "/slow?seconds=1.5", timeout=10).json()
                        )
                    )
                    request.start()
                    time.sleep(0.4)
                    server.send_signal(signal.SIGTERM)
                    started = time.perf_counter()
                    request.join()
                    results["exit status"] = server.wait(timeout=15)
                    results["stopped after"] = f"{time.perf_counter() - started:.1f} s"
                    results["new connections"] = raised_error_name(
                        lambda: httpx.get(base_url + "/health", timeout=1)
                    )
                    return results
                finally:
                    if server.poll() is None:  # only when something above failed
                        server.kill()
                        server.wait()
            '''
        ),
        md("Run it:"),
        code(
            r"""
            print(graceful_shutdown_demo())
            """
        ),
        md(
            """
            The request in flight finished; new connections are refused; the exit status is
            "terminated by SIGTERM" (-15), which Uvicorn re-raises after a clean shutdown. In
            Kubernetes a `preStop` pause gives the load balancer a moment to stop routing to the
            pod before the signal arrives.

            **Release strategies**

            | Strategy | How | Rollback | Cost |
            | --- | --- | --- | --- |
            | **Rolling** | replace replicas a few at a time (`maxUnavailable: 0`, `maxSurge: 1`) | roll forward again, or `kubectl rollout undo` | none extra; both versions serve for a while |
            | **Blue-green** | start the full new version beside the old, switch traffic at once | switch back | double capacity during the switch |
            | **Canary** | send a small share (1 %, 5 %, 25 %...) to the new version, watch its error rate and latency | route the share back to 0 | needs traffic splitting and good metrics |

            **Blue-green in miniature.** Two complete releases run side by side: *blue* (live)
            and *green* (new). Green is started and health-checked **before** it gets any
            traffic; the switch is one assignment, and blue keeps running, so rolling back is
            the same assignment the other way. Here the "load balancer" is a variable that a
            traffic thread reads on every request; in production it is the proxy's upstream (a
            Caddy or Nginx reload, a Kubernetes Service selector, a load-balancer target group;
            the project's `rollout.sh` pins Caddy's upstreams the same way):
            """
        ),
        code(
            r'''
            @dataclasses.dataclass
            class BlueGreenSwitch:
                """Which colour is live: the only thing a blue-green release changes."""

                upstreams: dict[str, str]
                live: str

                def url(self) -> str:
                    """The base URL of the live colour."""
                    return self.upstreams[self.live]


            def send_traffic(switch: BlueGreenSwitch, stop: threading.Event, replies: list[str]) -> None:
                """GET /version through the switch until stop is set; record versions or "error"."""
                with httpx.Client(timeout=5, trust_env=False) as client:
                    while not stop.is_set():
                        try:
                            replies.append(client.get(switch.url() + "/version").json()["version"])
                        except httpx.HTTPError:
                            replies.append("error")


            def run_lengths(replies: list[str]) -> str:
                """Compress the replies: [a, a, b, b, b, a] -> "a x2 -> b x3 -> a x1"."""
                groups = [(name, len(list(run))) for name, run in itertools.groupby(replies)]
                return " -> ".join(f"{name} x{count}" for name, count in groups)
            '''
        ),
        md(
            """
            The release: blue serves alone, green starts beside it, traffic flips to green,
            then (as if green had a problem) flips back. Requests keep flowing the whole time:
            """
        ),
        code(
            r'''
            def blue_green_release() -> list[str]:
                """Serve from blue, switch to green, roll back to blue; return every reply."""
                replies: list[str] = []
                stop = threading.Event()
                with uvicorn_server("app:app", app_dir=DEMO_DIR, extra_env={"APP_VERSION": "blue-v1"}) as blue:
                    switch = BlueGreenSwitch({"blue": blue}, live="blue")
                    sender = threading.Thread(target=send_traffic, args=(switch, stop, replies))
                    sender.start()
                    try:
                        with uvicorn_server(
                            "app:app", app_dir=DEMO_DIR, extra_env={"APP_VERSION": "green-v2"}
                        ) as green:  # started and healthy before it is live
                            switch.upstreams["green"] = green
                            switch.live = "green"  # the release
                            time.sleep(0.5)
                            switch.live = "blue"  # the rollback: blue never stopped
                            time.sleep(0.3)
                    finally:
                        stop.set()
                        sender.join()
                return replies


            release_replies = blue_green_release()
            print(run_lengths(release_replies))
            print(f"{len(release_replies)} requests, {release_replies.count('error')} failed")
            '''
        ),
        md(
            """
            Every request was answered by exactly one complete release, none failed, and the
            rollback took no restart. The cost is visible too: during the switch both releases
            run, so the platform needs room for two full copies, and both share one database,
            so the schema must suit both (expand/contract, 6.8.7).

            A canary step in miniature: 5 % of 20 000 simulated requests go to the new version,
            which has a bug; comparing error rates decides whether to continue:
            """
        ),
        code(
            r'''
            def canary_step(share: float, new_error_rate: float, requests: int = 20_000, seed: int = 42) -> str:
                """Route a share of traffic to the canary; promote or roll back by error rate."""
                rng = random.Random(seed)
                served = {"stable": [0, 0], "canary": [0, 0]}  # [requests, errors]
                for _ in range(requests):
                    version = "canary" if rng.random() < share else "stable"
                    error_rate = new_error_rate if version == "canary" else 0.001
                    served[version][0] += 1
                    served[version][1] += rng.random() < error_rate
                rates = {version: errors / max(count, 1) for version, (count, errors) in served.items()}
                verdict = "ROLL BACK" if rates["canary"] > 2 * rates["stable"] + 0.002 else "promote"
                return (
                    f"canary got {served['canary'][0]} requests, "
                    f"error rate {rates['canary']:.2%} vs {rates['stable']:.2%}: {verdict}"
                )


            print("healthy canary:", canary_step(0.05, new_error_rate=0.001))
            print("buggy canary  :", canary_step(0.05, new_error_rate=0.03))
            '''
        ),
        md(
            """
            **Stateless scaling.** Any replica must be able to answer any request, so state lives
            outside the process (database, Redis). Two demo app processes behind a round-robin
            client: the in-memory counter disagrees depending on who answers; the Redis counter is
            right everywhere:
            """
        ),
        code(
            r'''
            def two_replicas_counting(redis_url: str) -> None:
                """Alternate 10 POST /count between two processes sharing one Redis."""
                env = {"REDIS_URL": redis_url}
                with (
                    uvicorn_server("app:app", app_dir=DEMO_DIR, extra_env=env) as first,
                    uvicorn_server("app:app", app_dir=DEMO_DIR, extra_env=env) as second,
                ):
                    redis_sync.Redis.from_url(redis_url).set("demo:hits", 0)
                    answers = [
                        httpx.post(f"{[first, second][number % 2]}/count", timeout=5).json()
                        for number in range(10)
                    ]
                print("in memory:", [answer["in_memory"] for answer in answers])
                print("in Redis :", [answer["shared"] for answer in answers])


            REDIS_URL = start_shared_redis()
            if REDIS_URL:
                two_replicas_counting(REDIS_URL)
            else:
                print("SKIP: two processes need a real Redis (Docker) to share a counter")
            '''
        ),
        md(
            """
            **PgBouncer** sits between many app processes and PostgreSQL and multiplexes their
            connections onto a few server connections (transaction pooling: a server connection
            is lent for one transaction). 24 processes × 15 pooled connections = 360 client
            connections can share 20 server connections. The catch: session state does not
            survive between transactions, so asyncpg's prepared-statement cache must be off
            (`NOTES_DATABASE_PGBOUNCER=true` in v7 sets `statement_cache_size=0` and unique
            statement names; PgBouncer 1.21+ can also track prepared statements itself).

            **CDNs** cache static files (and cacheable API responses) close to users. The trick for
            static assets is a **content hash in the file name**: the file can be cached "forever"
            (`immutable`), and a new version gets a new name, so no cache ever serves a stale
            stylesheet:
            """
        ),
        code(
            r'''
            def fingerprint(path: Path) -> str:
                """style.css -> style.<8 hex of SHA-256>.css"""
                digest = hashlib.sha256(path.read_bytes()).hexdigest()[:8]
                return f"{path.stem}.{digest}{path.suffix}"


            def cache_header(file_name: str) -> str:
                """Fingerprinted assets never change; others must be revalidated."""
                fingerprinted = re.search(r"\.[0-9a-f]{8}\.", file_name) is not None
                return (
                    "public, max-age=31536000, immutable"
                    if fingerprinted
                    else "public, max-age=0, must-revalidate"
                )


            stylesheet = DEMO_DIR / "style.css"
            stylesheet.write_text("body { font-family: sans-serif; }\n")
            first_name = fingerprint(stylesheet)
            stylesheet.write_text("body { font-family: serif; }\n")
            print(
                first_name,
                "->",
                fingerprint(stylesheet),
                "|",
                cache_header(first_name),
                "|",
                cache_header("index.html"),
            )
            '''
        ),
    ]


def _load_test_cells() -> list[NotebookNode]:
    """6.8.10 Load testing and readiness."""
    return [
        md(
            """
            ### 6.8.10 Load testing and readiness

            Load tests answer: how much traffic does one replica take at our latency target, and
            what breaks first? **Locust** describes users as Python classes (`HttpUser`, `@task`
            weights, `wait_time`), runs them on gevent, and reports percentiles; `--headless` with
            `--csv` makes it scriptable. A locustfile for the demo app:
            """
        ),
        code(
            r'''
            %%writefile _scratch/phase6/deploy_demo/locustfile.py
            """Demo load: mostly fast reads, some slow requests."""

            from locust import HttpUser, between, task


            class DemoUser(HttpUser):
                """One simulated client."""

                wait_time = between(0.01, 0.05)

                @task(9)
                def whoami(self) -> None:
                    """A fast request."""
                    self.client.get("/whoami")

                @task(1)
                def slow(self) -> None:
                    """A deliberately slow request (50 ms)."""
                    self.client.get("/slow?seconds=0.05", name="/slow")
            '''
        ),
        md(
            "Ten seconds, 20 users, against the app under Uvicorn with two workers; then the numbers from the CSV report:"
        ),
        code(
            r'''
            def locust_summary(csv_prefix: Path) -> dict[str, float]:
                """The Aggregated row of Locust's stats CSV."""
                with open(f"{csv_prefix}_stats.csv", newline="") as stats_file:
                    total = next(row for row in csv.DictReader(stats_file) if row["Name"] == "Aggregated")
                return {
                    "requests": int(total["Request Count"]),
                    "failures": int(total["Failure Count"]),
                    "rps": round(float(total["Requests/s"]), 1),
                    "p50_ms": float(total["50%"]),
                    "p95_ms": float(total["95%"]),
                }


            csv_prefix = DEMO_DIR / "locust_demo"
            '''
        ),
        md("The run: Uvicorn with two workers, then Locust headless with 20 users for 5 s:"),
        code(
            r"""
            with uvicorn_server("app:app", app_dir=DEMO_DIR, extra_args=["--workers", "2"]) as base_url:
                load_run = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "locust",
                        "-f",
                        "locustfile.py",
                        "--host",
                        base_url,
                        "--headless",
                        "-u",
                        "20",
                        "-r",
                        "10",
                        "-t",
                        "5s",
                        "--only-summary",
                        "--csv",
                        str(csv_prefix),
                    ],
                    cwd=DEMO_DIR,
                    capture_output=True,
                    text=True,
                    env=CHILD_ENV,
                    timeout=120,
                )
            summary = locust_summary(csv_prefix)
            print(summary, "| exit code", load_run.returncode)
            """
        ),
        md(
            """
            **Capacity planning** starts from **Little's law**: requests in the system =
            throughput × time in the system. With a measured p95 and per-replica throughput you
            can estimate replicas for a target load, with headroom for spikes and for losing a
            replica during a deploy:
            """
        ),
        code(
            r'''
            def replicas_needed(
                peak_rps: float, rps_per_replica: float, headroom: float = 0.5, spare: int = 1
            ) -> int:
                """Replicas for a peak with headroom, plus spares for deploys and failures."""
                return math.ceil(peak_rps * (1 + headroom) / rps_per_replica) + spare


            in_flight = summary["rps"] * summary["p50_ms"] / 1000
            print(
                f"Little's law: {summary['rps']} req/s x {summary['p50_ms']} "
                f"ms = {in_flight:.2f} requests in flight on average"
            )
            print(
                f"a peak of 2 000 req/s at {summary['rps']} req/s per replica "
                f"-> {replicas_needed(2000, summary['rps'])} replicas"
            )
            '''
        ),
        md(
            """
            **Production checklist** (the Notes API v7 answers in the right column):

            | Area | Check | Notes API v7 |
            | --- | --- | --- |
            | Security | secrets from the platform, never in images or git; non-root; TLS; headers | `/run/secrets`, uid 10001, Caddy, `SecurityHeadersMiddleware` |
            | Config | validated at startup; production refuses unsafe settings | pydantic-settings validators |
            | Reliability | probes; graceful shutdown; retries with backoff; idempotent jobs | `/health/*`, `--timeout-graceful-shutdown`, ARQ retries |
            | Data | migrations as a job, backward compatible; backups and a tested restore | `migrate` service / Job; (backups: platform) |
            | Observability | JSON logs, metrics, traces, error tracking, alerts on SLOs | structlog, Prometheus, OTel, Sentry |
            | Capacity | load-tested; pools sized; autoscaling limits | Locust gate, `connection_budget`, HPA |
            | Delivery | CI on every change; scanned images; reviewed production deploys | the workflow's scan job and `production` environment |
            | Operations | runbooks; on-call; dependency updates | (team process) |
            """
        ),
    ]


def _predict_cells() -> list[NotebookNode]:
    """Three predict-the-output questions for Unit 6.8."""
    return [
        md(
            """
            ### Predict the output — Unit 6.8

            Three questions about pools, job graphs and caching. Decide first, then run the proof.
            """
        ),
        *predict_cells(
            """
            print(connection_budget(replicas=4, processes=3, pool_size=5, max_overflow=10))
            """,
            """
            `180`. Every process has its own pool of up to 5 + 10 connections, and there are
            4 × 3 = 12 processes: 12 × 15 = 180, more than PostgreSQL's default
            `max_connections` of 100.
            """,
            r"""
            print(connection_budget(replicas=4, processes=3, pool_size=5, max_overflow=10))
            """,
        ),
        *predict_cells(
            """
            pipeline_graph = {"deploy": ["push"], "push": ["build"], "build": []}
            print(list(graphlib.TopologicalSorter(pipeline_graph).static_order()))
            """,
            """
            `['build', 'push', 'deploy']`. The mapping says what each node depends on
            (`deploy` needs `push`), and `static_order()` lists every node after its dependencies.
            """,
            r"""
            pipeline_graph = {"deploy": ["push"], "push": ["build"], "build": []}
            print(list(graphlib.TopologicalSorter(pipeline_graph).static_order()))
            """,
        ),
        *predict_cells(
            """
            print(cache_header("app.3f9a1c2b.js"), "|", cache_header("app.js"))
            """,
            """
            `public, max-age=31536000, immutable | public, max-age=0, must-revalidate`. Only the
            fingerprinted name can be cached for a year: its content can never change under that
            name.
            """,
            r"""
            print(cache_header("app.3f9a1c2b.js"), "|", cache_header("app.js"))
            """,
        ),
    ]


LAB68_GIVEN_SOURCE = r'''
LAB_APP_DIR = PHASE6_DIR / "lab68_app"
shutil.rmtree(LAB_APP_DIR, ignore_errors=True)  # start clean: no files left by an earlier run
LAB_APP_DIR.mkdir()
(LAB_APP_DIR / "app.py").write_text(
    textwrap.dedent("""
    \"\"\"The Lab 6.8 app.\"\"\"

    import asyncio

    from fastapi import FastAPI

    app = FastAPI()


    @app.get("/health")
    def health() -> dict[str, str]:
        \"\"\"Liveness.\"\"\"
        return {"status": "ok"}


    @app.get("/slow")
    async def slow(seconds: float = 1.0) -> dict[str, float]:
        \"\"\"A request that takes a while.\"\"\"
        await asyncio.sleep(seconds)
        return {"slept": seconds}
""")
)
print("app.py:", len((LAB_APP_DIR / "app.py").read_text().strip().splitlines()), "lines")
'''

LAB68_FILES_SOURCE = r'''
(LAB_APP_DIR / "requirements.txt").write_text("fastapi==0.163.1\nuvicorn==0.54.0\n")
(LAB_APP_DIR / "notes.txt").write_text("a local file that must not end up in the image\n")
(LAB_APP_DIR / "locustfile.py").write_text(
    textwrap.dedent("""
    \"\"\"Lab load: health checks and short requests.\"\"\"

    from locust import HttpUser, between, task


    class LabUser(HttpUser):
        \"\"\"One simulated client.\"\"\"

        wait_time = between(0.01, 0.05)

        @task(4)
        def health(self) -> None:
            \"\"\"Cheap.\"\"\"
            self.client.get("/health")

        @task(1)
        def short(self) -> None:
            \"\"\"20 ms.\"\"\"
            self.client.get("/slow?seconds=0.02", name="/slow")
""")
)
print(sorted(path.name for path in LAB_APP_DIR.iterdir()))
'''

LAB68_CSV_SOURCE = r"""
SAMPLE_LOCUST_CSV = (
    "Type,Name,Request Count,Failure Count,Median Response Time,Average Response Time,"
    "Min Response Time,Max Response Time,Average Content Size,Requests/s,Failures/s,"
    "50%,66%,75%,80%,90%,95%,98%,99%,99.9%,99.99%,100%\n"
    "GET,/health,800,0,3,3.4,1,40,15,80.0,0.0,3,4,4,5,6,8,12,20,35,40,40\n"
    "GET,/slow,200,2,24,26.1,21,310,30,20.0,0.2,24,25,26,27,30,45,120,250,310,310,310\n"
    ",Aggregated,1000,2,4,7.9,1,310,18,100.0,0.2,4,5,6,8,24,27,40,120,310,310,310\n"
)
print(SAMPLE_LOCUST_CSV.splitlines()[-1])
"""


def _lab_setup_cells() -> list[NotebookNode]:
    """Lab 6.8 introduction and given code."""
    return [
        md(
            """
            ### Lab 6.8

            | Exercise | Syllabus item | You write |
            | --- | --- | --- |
            | 1 | An optimized multi-stage Dockerfile | `write_dockerfile(app_dir)` |
            | 2 | A Compose stack with health checks | `build_compose(image)` |
            | 3 | A TLS reverse-proxy config | `write_caddyfile(site, upstream)` |
            | 4 | A CI/CD pipeline | `build_pipeline()`, `job_waves(pipeline)` |
            | 5 | A graceful-shutdown test | `graceful_shutdown_result(port)` |
            | 6 | A Locust report at p95 < 200 ms | `load_report(csv_prefix)`, `run_load_test(base_url, csv_prefix)` |

            The *Notes API v7* section after the lab applies all of it to the real project.
            Given: a tiny app in `LAB_APP_DIR`, starting with `app.py` (`/health` and `/slow`):
            """
        ),
        code(LAB68_GIVEN_SOURCE),
        md("Next to it: `requirements.txt`, a stray `notes.txt`, and a `locustfile.py`:"),
        code(LAB68_FILES_SOURCE),
        md("And `SAMPLE_LOCUST_CSV`, a stats file as Locust writes it:"),
        code(LAB68_CSV_SOURCE),
    ]


def _lab_exercise_1_cells() -> list[NotebookNode]:
    """Lab 6.8 exercise 1."""
    return [
        md(
            """
            #### Exercise 1 — An optimized multi-stage Dockerfile

            `write_dockerfile(app_dir) -> Path` writes `app_dir / "Dockerfile"` and
            `app_dir / ".dockerignore"` and returns the Dockerfile's path. Requirements:

            - at least two stages (`FROM ... AS build`, then a runtime stage); dependencies
              installed into a virtual environment in the build stage (with uv or pip), and only
              that environment plus `app.py` copied into the runtime stage;
            - the runtime runs as a non-root user (`USER` with a name or a non-zero uid);
            - a `HEALTHCHECK` against `/health`, and an **exec-form** `CMD` (a JSON array) running
              `uvicorn app:app --host 0.0.0.0 --port 8000`;
            - `.dockerignore` keeps `notes.txt` (and everything else not needed) out of the context.

            With Docker, the checks also build it, look inside, and time `docker stop`.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            def write_dockerfile(app_dir: Path) -> Path:
                """Write an optimized Dockerfile and .dockerignore for the lab app."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 1. The static checks, then (with Docker) a build and a run:"),
        code(
            r'''
            def dockerfile_text() -> str:
                """The student's Dockerfile."""
                return write_dockerfile(LAB_APP_DIR).read_text()


            def built_image_facts() -> dict[str, object]:
                """Write the Dockerfile, build, then inspect the image and a running container."""
                write_dockerfile(LAB_APP_DIR)
                docker("build", "--quiet", "--tag", "lab68:latest", ".", cwd=LAB_APP_DIR)
                files = docker(
                    "run", "--rm", "--entrypoint", "ls", "lab68:latest", "-a", "/app", check=False
                ).split()
                uid = docker("run", "--rm", "--entrypoint", "id", "lab68:latest", "-u")
                container = docker("run", "--detach", "lab68:latest")
                time.sleep(2)
                started = time.perf_counter()
                docker("stop", "--time", "5", container)
                stop_seconds = time.perf_counter() - started
                docker("rm", container)
                return {"notes.txt in image": "notes.txt" in files, "uid": uid, "stops fast": stop_seconds < 3}
            '''
        ),
        md("The checks:"),
        code(
            r"""
            image_checks = [
                ("two or more stages", lambda: len(re.findall(r"^FROM ", dockerfile_text(), re.M)) >= 2, True),
                (
                    "non-root user",
                    lambda: re.findall(r"^USER\s+(\S+)", dockerfile_text(), re.M)[-1] not in ("root", "0"),
                    True,
                ),
                (
                    "health check",
                    lambda: "HEALTHCHECK" in dockerfile_text() and "/health" in dockerfile_text(),
                    True,
                ),
                (
                    "exec-form CMD with uvicorn",
                    lambda: re.search(r'^CMD \[.*"uvicorn".*\]', dockerfile_text(), re.M) is not None,
                    True,
                ),
                (
                    "no COPY of the whole folder",
                    lambda: re.search(r"^COPY \. ", dockerfile_text(), re.M) is None,
                    True,
                ),
                ("a .dockerignore", lambda: (LAB_APP_DIR / ".dockerignore").exists(), True),
            ]
            if HAS_DOCKER:
                lab_image: dict[str, object] = {}
                try:
                    lab_image = built_image_facts()
                except (RuntimeError, subprocess.SubprocessError) as error:  # the checks below then fail
                    print(f"build or run failed: {type(error).__name__}: {str(error)[-400:]}")
                image_checks += [
                    ("notes.txt stayed out", lambda: lab_image["notes.txt in image"], False),
                    ("runs with a non-zero uid", lambda: lab_image["uid"] != "0", True),
                    ("SIGTERM reaches uvicorn (stops in < 3 s)", lambda: lab_image["stops fast"], True),
                ]
            else:
                print("SKIP the build checks: no Docker")
            run_checks(image_checks)
            """
        ),
    ]


def _lab_exercise_2_cells() -> list[NotebookNode]:
    """Lab 6.8 exercise 2."""
    return [
        md(
            """
            #### Exercise 2 — A Compose stack with health checks

            `build_compose(image) -> dict`, the content of a `compose.yaml` with four services:

            - `redis` (`redis:7.4`) with a `redis-cli ping` health check;
            - `init`: a one-off job (any command, `restart: "no"`) that waits for Redis to be
              healthy;
            - `api` (`image`): waits for `redis` **healthy** and `init` **completed successfully**,
              has a health check, `expose`s 8000 (no `ports`), `read_only: true`;
            - `proxy` (`caddy:2`): the only service with `ports` (bound to `127.0.0.1`), waits for
              `api` healthy.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            def build_compose(image: str) -> dict[str, Any]:
                """A Compose stack: redis, a one-off init job, the api, a proxy."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 2. The helpers:"),
        code(
            r'''
            def compose_services() -> dict[str, Any]:
                """The student's services."""
                return build_compose("lab68:latest")["services"]


            def compose_config_is_valid() -> bool:
                """docker compose config accepts the file."""
                compose_file = LAB_APP_DIR / "compose.lab.yaml"
                compose_file.write_text(yaml.safe_dump(build_compose("lab68:latest")))
                docker("compose", "-f", compose_file.name, "config", "--quiet", cwd=LAB_APP_DIR)
                return True
            '''
        ),
        md("The checks: services and start-up order:"),
        code(
            r"""
            stack_checks = [
                ("four services", lambda: sorted(compose_services()), ["api", "init", "proxy", "redis"]),
                (
                    "redis health check",
                    lambda: "redis-cli" in str(compose_services()["redis"]["healthcheck"]["test"]),
                    True,
                ),
                (
                    "init waits for healthy redis",
                    lambda: compose_services()["init"]["depends_on"]["redis"]["condition"],
                    "service_healthy",
                ),
                (
                    "api waits for init to finish",
                    lambda: compose_services()["api"]["depends_on"]["init"]["condition"],
                    "service_completed_successfully",
                ),
            ]
            """
        ),
        md("Then the API's hardening and the proxy; the Compose check needs Docker:"),
        code(
            r"""
            stack_checks += [
                (
                    "api has a health check, no ports, read-only",
                    lambda: (
                        "healthcheck" in compose_services()["api"],
                        "ports" in compose_services()["api"],
                        compose_services()["api"]["read_only"],
                    ),
                    (True, False, True),
                ),
                (
                    "only the proxy publishes, on 127.0.0.1",
                    lambda: (
                        [name for name, service in compose_services().items() if "ports" in service]
                        == ["proxy"]
                        and all(
                            str(port).startswith("127.0.0.1:") for port in compose_services()["proxy"]["ports"]
                        )
                    ),
                    True,
                ),
                (
                    "proxy waits for a healthy api",
                    lambda: compose_services()["proxy"]["depends_on"]["api"]["condition"],
                    "service_healthy",
                ),
            ]
            if HAS_DOCKER:
                stack_checks.append(("docker compose config accepts it", compose_config_is_valid, True))
            run_checks(stack_checks)
            """
        ),
    ]


def _lab_exercise_3_cells() -> list[NotebookNode]:
    """Lab 6.8 exercise 3."""
    return [
        md(
            """
            #### Exercise 3 — A TLS reverse-proxy config

            `write_caddyfile(site, upstream) -> str` returns a Caddyfile for `site` (Caddy
            obtains the certificate) that:

            - proxies everything to `upstream` (e.g. `api:8000`) with `reverse_proxy`;
            - answers **404** for `/metrics` (a named matcher and `respond`);
            - adds `Strict-Transport-Security: max-age=31536000` with `header`;
            - compresses (`encode`) and logs as JSON to stdout (a `log` block).

            With Docker, `caddy validate` checks it.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            def write_caddyfile(site: str, upstream: str) -> str:
                """A Caddyfile for site, proxying to upstream."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 3:"),
        code(
            r'''
            def caddy_validates(text: str) -> str:
                """caddy validate's verdict (its log lines go to stderr, interleaved)."""
                path = LAB_APP_DIR / "Caddyfile"
                path.write_text(text)
                output = docker(
                    "run",
                    "--rm",
                    "-v",
                    f"{path}:/etc/caddy/Caddyfile:ro",
                    "caddy:2",
                    "caddy",
                    "validate",
                    "--config",
                    "/etc/caddy/Caddyfile",
                    "--adapter",
                    "caddyfile",
                    check=False,
                )
                return "Valid configuration" if "Valid configuration" in output else output.splitlines()[-1]


            def caddyfile() -> str:
                """The student's config for the checks."""
                return write_caddyfile("notes.example.com", "api:8000")
            '''
        ),
        md("The checks:"),
        code(
            r"""
            proxy_checks = [
                (
                    "site block",
                    lambda: re.search(r"^notes\.example\.com\s*\{", caddyfile(), re.M) is not None,
                    True,
                ),
                ("reverse_proxy to the upstream", lambda: "reverse_proxy api:8000" in caddyfile(), True),
                (
                    "/metrics answered with 404",
                    lambda: (
                        "/metrics" in caddyfile()
                        and re.search(r"respond\s+@\w+\s+404", caddyfile()) is not None
                    ),
                    True,
                ),
                (
                    "HSTS header",
                    lambda: (
                        re.search(r'header\s+Strict-Transport-Security\s+"?max-age=31536000', caddyfile())
                        is not None
                    ),
                    True,
                ),
                (
                    "compression and JSON logs",
                    lambda: ("encode" in caddyfile(), "format json" in caddyfile()),
                    (True, True),
                ),
            ]
            if HAS_DOCKER:
                proxy_checks.append(
                    ("caddy validate", lambda: caddy_validates(caddyfile()), "Valid configuration")
                )
            run_checks(proxy_checks)
            """
        ),
    ]


def _lab_exercise_4_cells() -> list[NotebookNode]:
    """Lab 6.8 exercise 4."""
    return [
        md(
            """
            #### Exercise 4 — A CI/CD pipeline

            - `build_pipeline() -> dict`: a GitHub Actions workflow with the jobs `lint`, `test`,
              `build`, `scan`, `push` and `deploy`. `build` needs `lint` and `test`; `scan` needs
              `build`; `push` needs `scan` and runs only on the main branch (its `if` mentions
              `refs/heads/main`); `deploy` needs `push` and uses the environment `production`.
              `test` has a `postgres` service container. Every job runs on `ubuntu-24.04` and has
              at least one step.
            - `job_waves(pipeline) -> list[list[str]]`: the jobs grouped into waves that can run in
              parallel (each wave sorted), using `graphlib.TopologicalSorter`; `needs` may be a
              string or a list.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            def build_pipeline() -> dict[str, Any]:
                """lint, test, build, scan, push, deploy."""
                raise NotImplementedError


            def job_waves(pipeline: dict[str, Any]) -> list[list[str]]:
                """Jobs grouped by when they can start."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 4:"),
        code(
            r'''
            def pipeline_jobs() -> dict[str, Any]:
                """The student's jobs."""
                return build_pipeline()["jobs"]
            '''
        ),
        md("The checks:"),
        code(
            r"""
            run_checks(
                [
                    (
                        "six jobs",
                        lambda: sorted(pipeline_jobs()),
                        ["build", "deploy", "lint", "push", "scan", "test"],
                    ),
                    (
                        "waves",
                        lambda: job_waves(build_pipeline()),
                        [["lint", "test"], ["build"], ["scan"], ["push"], ["deploy"]],
                    ),
                    ("push only from main", lambda: "refs/heads/main" in pipeline_jobs()["push"]["if"], True),
                    (
                        "deploy through production",
                        lambda: str(pipeline_jobs()["deploy"]["environment"]).count("production") >= 1,
                        True,
                    ),
                    ("tests get PostgreSQL", lambda: "postgres" in pipeline_jobs()["test"]["services"], True),
                    (
                        "every job has steps",
                        lambda: all(
                            job["steps"] and job["runs-on"] == "ubuntu-24.04"
                            for job in pipeline_jobs().values()
                        ),
                        True,
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
                        "waves of another graph",
                        lambda: job_waves(
                            {
                                "jobs": {
                                    "a": {},
                                    "b": {"needs": "a"},
                                    "c": {"needs": ["a"]},
                                    "d": {"needs": ["b", "c"]},
                                }
                            }
                        ),
                        [["a"], ["b", "c"], ["d"]],
                    ),
                ]
            )
            """
        ),
    ]


def _lab_exercise_5_cells() -> list[NotebookNode]:
    """Lab 6.8 exercise 5."""
    return [
        md(
            """
            #### Exercise 5 — A graceful-shutdown test

            `graceful_shutdown_result(port) -> dict` starts the lab app with Uvicorn in a
            subprocess (`cwd=LAB_APP_DIR`, `--port port`, `--timeout-graceful-shutdown 10`), waits
            until `/health` answers, starts `GET /slow?seconds=1.0` in a thread, sends SIGTERM
            after 0.3 s, waits for the request and the process, then tries one more request.
            Return `{"status": <slow request status>, "body": <its JSON>, "exit_status": <return
            code>, "refused_after": <True if the last request could not connect>}`. Always stop the
            process, even when something fails.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            def graceful_shutdown_result(port: int) -> dict[str, object]:
                """SIGTERM during a request: what does the client see?"""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 5:"),
        code(
            r"""
            lab_shutdown: dict[str, object] = {}
            with contextlib.suppress(Exception):
                lab_shutdown = graceful_shutdown_result(free_port())
            run_checks(
                [
                    ("the request in flight succeeds", lambda: lab_shutdown["status"], 200),
                    ("with its full body", lambda: lab_shutdown["body"], {"slept": 1.0}),
                    (
                        "a clean exit (0, or SIGTERM re-raised)",
                        lambda: lab_shutdown["exit_status"] in (0, -signal.SIGTERM),
                        True,
                    ),
                    ("new connections refused afterwards", lambda: lab_shutdown["refused_after"], True),
                ]
            )
            """
        ),
    ]


def _lab_exercise_6_cells() -> list[NotebookNode]:
    """Lab 6.8 exercise 6."""
    return [
        md(
            """
            #### Exercise 6 — A Locust report at p95 < 200 ms

            - `load_report(csv_prefix) -> dict`: read `<csv_prefix>_stats.csv` and return the
              `Aggregated` row as `{"requests": int, "failures": int, "rps": float, "p95_ms":
              float, "passed": bool}`, where `passed` means p95 < 200 ms **and** a failure ratio
              below 1 %.
            - `run_load_test(base_url, csv_prefix) -> int`: run Locust headless with
              `LAB_APP_DIR / "locustfile.py"` against `base_url` (10 users, spawn rate 10, 8
              seconds, `--csv csv_prefix`); return Locust's exit code.

            The checks parse `SAMPLE_LOCUST_CSV`, then load-test the lab app under Uvicorn.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            def load_report(csv_prefix: Path) -> dict[str, object]:
                """The Aggregated row of a Locust stats CSV, with a pass/fail verdict."""
                raise NotImplementedError


            def run_load_test(base_url: str, csv_prefix: Path) -> int:
                """Run Locust headless; return its exit code."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 6:"),
        code(
            r"""
            sample_prefix = LAB_APP_DIR / "sample"
            Path(f"{sample_prefix}_stats.csv").write_text(SAMPLE_LOCUST_CSV)
            live_prefix = LAB_APP_DIR / "live"
            lab_load: dict[str, object] = {}
            with contextlib.suppress(Exception):
                with uvicorn_server("app:app", app_dir=LAB_APP_DIR) as lab_url:
                    lab_load = {"exit": run_load_test(lab_url, live_prefix), "report": load_report(live_prefix)}
            run_checks(
                [
                    (
                        "sample report",
                        lambda: load_report(sample_prefix),
                        {"requests": 1000, "failures": 2, "rps": 100.0, "p95_ms": 27.0, "passed": True},
                    ),
                    (
                        "the sample p95 is under the limit",
                        lambda: load_report(sample_prefix)["p95_ms"] < 200,
                        True,
                    ),
                    ("live run: exit code 0", lambda: lab_load["exit"], 0),
                    (
                        "live run: requests and no failures",
                        lambda: lab_load["report"]["requests"] > 100 and lab_load["report"]["failures"] == 0,
                        True,
                    ),
                    ("live run: p95 under 200 ms", lambda: lab_load["report"]["passed"], True),
                ]
            )
            """
        ),
    ]


def _notes_v7_intro_cells() -> list[NotebookNode]:
    """Notes API v7: introduction and pruning."""
    return [
        md(
            """
            ### Notes API v7 — the project files

            v7 is the Notes API ready to deploy:

            | v6 (Unit 6.7) | v7 (this unit) |
            | --- | --- |
            | run with `uv run uvicorn` | a **multi-stage image** (uv build stage, non-root runtime, health check, graceful shutdown) |
            | Compose for PostgreSQL and Redis | the **whole stack**: `db`, `redis`, a `migrate` job, `api`, `worker`, `proxy` (Caddy, TLS); read-only containers, a file secret |
            | — | `deploy/`: Caddyfile, Nginx alternative, Kubernetes manifests (probes, rolling update, migrate Job, autoscaler), systemd unit, Cloud Run service; a `Procfile` |
            | secrets only from the environment | also from `/run/secrets` files; a PgBouncer mode for the engine |
            | — | `python -m notes_api.worker --check` (container health check) |
            | CI: lint and tests | **CI/CD**: lint, types (mypy), tests, build + smoke test, scan (Trivy, pip-audit), push to GHCR, deploy |
            | — | `load/locustfile.py` (p95 < 200 ms gate), `test_shutdown.py`, `test_deploy.py` |

            The cells write the 25 files that change or are new (of 106) plus the workflow, and
            re-record the OpenAPI snapshot (the version changed). First, remove files of other
            versions:
            """
        ),
        code(
            r'''
            NOTES_V7_FILES = """
            .dockerignore .env.example Dockerfile Procfile README.md alembic.ini alembic/env.py
            alembic/script.py.mako alembic/versions/0001_create_notes.py
            alembic/versions/0002_tags_many_to_many.py alembic/versions/0003_version_and_search.py
            alembic/versions/0004_users_and_ownership.py
            alembic/versions/0005_refresh_tokens_and_api_keys.py
            alembic/versions/0006_outbox_and_webhooks.py compose.yaml deploy/Caddyfile
            deploy/cloudrun/service.yaml deploy/k8s/api-deployment.yaml deploy/k8s/api-service.yaml
            deploy/k8s/config.yaml deploy/k8s/migrate-job.yaml deploy/k8s/worker.yaml deploy/nginx.conf
            deploy/systemd/notes-api.service load/locustfile.py pyproject.toml ruff.toml
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
            tests/helpers.py tests/slow_app.py tests/snapshots/openapi.json tests/test_admin.py
            tests/test_async.py tests/test_auth.py tests/test_background.py tests/test_bola.py
            tests/test_caching.py tests/test_contract.py tests/test_deploy.py tests/test_errors.py
            tests/test_exports.py tests/test_links.py tests/test_middleware.py tests/test_migrations.py
            tests/test_notes.py tests/test_oauth.py tests/test_observability.py tests/test_pages.py
            tests/test_pagination.py tests/test_postgres.py tests/test_postgres_rollback.py
            tests/test_realtime.py tests/test_redis_worker.py tests/test_repository.py
            tests/test_security.py tests/test_settings.py tests/test_shutdown.py tests/test_worker.py
            src/notes_api/manage.py src/notes_api/netguard.py tests/test_limits.py tests/test_netguard.py
            """.split()
            print("removed:", prune_notes_project(NOTES_V7_FILES))
            print(f"{len(NOTES_V7_FILES)} files in v7")
            '''
        ),
    ]


def _notes_v7_build_cells() -> list[NotebookNode]:
    """Notes API v7: build the image, record the snapshot."""
    return [
        md(
            """
            **Re-record the OpenAPI snapshot** (only `info.version` changed; the test would fail
            until the change is recorded, which is the point):
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
            """
        ),
        md(
            """
            **Build the image** from `projects/notes_api/` (the build context is what
            `.dockerignore` allows: `pyproject.toml`, `uv.lock`, `README.md`, `src/`, the
            migrations). The lock must match `pyproject.toml` first; then the image, its size, its
            user, its largest layers:
            """
        ),
        code(
            r"""
            if HAS_UV:
                print(lock_summary(run_in_notes("uv", "lock").stderr))
            if HAS_DOCKER:
                started = time.perf_counter()
                docker("build", "--quiet", "--tag", "notes-api:latest", ".", cwd=NOTES_API_DIR)
                print(
                    f"notes-api:latest {image_size_mb('notes-api:latest'):.0f} "
                    f"MB, built in {time.perf_counter() - started:.1f} s"
                )
                print("runs as:", docker("run", "--rm", "--entrypoint", "id", "notes-api:latest"))
                print(
                    "version:",
                    docker(
                        "run",
                        "--rm",
                        "--entrypoint",
                        "python",
                        "notes-api:latest",
                        "-c",
                        "import notes_api; print(notes_api.__version__)",
                    ),
                )
                layers = [
                    line.split("\t", 1)
                    for line in docker(
                        "history", "notes-api:latest", "--format", "{{.Size}}\t{{.CreatedBy}}"
                    ).splitlines()
                ]
                print("layers with content (newest first):")
                print(*[f"  {size:>8}  {created[:70]}" for size, created in layers if size != "0B"], sep="\n")
            else:
                print("SKIP the image build: Docker is not available")
            """
        ),
    ]


def _notes_v7_stack_cells() -> list[NotebookNode]:
    """Notes API v7: the full stack behind TLS."""
    return [
        md(
            """
            **The stack.** The JWT secret is a file in `.secrets/` (git-ignored, readable by the
            container user), generated now. Non-default host ports keep the demo clear of
            anything else on this machine:
            """
        ),
        code(
            r'''
            secret_file = NOTES_API_DIR / ".secrets" / "notes_jwt_secret"
            secret_file.parent.mkdir(exist_ok=True)
            secret_file.unlink(missing_ok=True)  # read-only from an earlier run
            secret_file.write_text(secrets.token_urlsafe(32))
            secret_file.chmod(0o444)
            ignored = (
                subprocess.run(["git", "check-ignore", "-q", str(secret_file)], cwd=REPO_ROOT).returncode == 0
            )
            print(f"secret written ({secret_file.stat().st_size} bytes), ignored by git: {ignored}")
            STACK_ENV = {
                "POSTGRES_PORT": "55432",
                "REDIS_PORT": "56379",
                "HTTPS_PORT": "58443",
                "HTTP_PORT": "58080",
            }


            def notes_stack(*arguments: str, timeout: float = 600) -> str:
                """docker compose for the Notes API stack (project notes-v7)."""
                run = subprocess.run(
                    ["docker", "compose", "-p", "notes-v7", *arguments],
                    cwd=NOTES_API_DIR,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env={**CHILD_ENV, **STACK_ENV},
                )
                if run.returncode != 0:
                    raise RuntimeError((run.stdout + run.stderr)[-2000:])
                return (run.stdout + run.stderr).strip()


            def remove_notes_stack() -> None:
                """compose down -v for the v7 stack; never raises (it is also the exit hook)."""
                with contextlib.suppress(RuntimeError, subprocess.TimeoutExpired):
                    notes_stack("down", "-v", "--remove-orphans")
            '''
        ),
        md(
            """
            Up with `--wait`: PostgreSQL and Redis become healthy, `migrate` runs and exits 0,
            then `api` and `worker` start and pass their health checks, then Caddy. The exit
            hook is registered first, so even a failed `up` or a failing cell below cannot leave
            the stack (and its ports 58080, 58443, 55432, 56379) running after the kernel stops:
            """
        ),
        code(
            r"""
            if HAS_DOCKER:
                atexit.register(remove_notes_stack)
                started = time.perf_counter()
                notes_stack("up", "-d", "--wait")
                print(f"stack up and healthy in {time.perf_counter() - started:.1f} s")
                for line in notes_stack(
                    "ps", "-a", "--format", "{{.Service}} {{.State}} {{.Health}} {{.ExitCode}}"
                ).splitlines():
                    print("  ", line)
            else:
                print("SKIP the stack: Docker is not available")
            """
        ),
        md(
            """
            Through Caddy (its local CA is not trusted by this client, hence `verify=False`):
            readiness, the hidden `/metrics`, the HTTP → HTTPS redirect, and the headers:
            """
        ),
        code(
            r"""
            NOTES_HTTPS = f"https://localhost:{STACK_ENV['HTTPS_PORT']}"
            if HAS_DOCKER:
                with httpx.Client(base_url=NOTES_HTTPS, verify=False, trust_env=False) as client:
                    print("ready   :", client.get("/health/ready").json())
                    print("/metrics:", client.get("/metrics").status_code)
                    headers = client.get("/health/live").headers
                    print(
                        "headers :",
                        {
                            name: headers[name][:28]
                            for name in ("strict-transport-security", "x-request-id", "alt-svc")
                            if name in headers
                        },
                    )
                redirect = httpx.get(f"http://localhost:{STACK_ENV['HTTP_PORT']}/health/live", trust_env=False)
                print("http    :", redirect.status_code, "->", redirect.headers["location"])
            """
        ),
        md(
            """
            A user registers, opens a WebSocket over `wss://`, creates a note over HTTPS, and the
            **worker container** pushes the event back through Redis, the API container and
            Caddy:
            """
        ),
        code(
            r'''
            def stack_round_trip() -> None:
                """Register, connect a WebSocket, write, receive the worker's push."""
                import ssl

                from websockets.sync.client import connect

                insecure = ssl.create_default_context()
                insecure.check_hostname, insecure.verify_mode = False, ssl.CERT_NONE
                with httpx.Client(base_url=NOTES_HTTPS, verify=False, trust_env=False, timeout=20) as client:
                    client.post(
                        "/api/v1/auth/register",
                        json={"email": "ops@example.com", "password": "a-long-passphrase"},
                    )
                    token = client.post(
                        "/api/v1/auth/token",
                        data={"username": "ops@example.com", "password": "a-long-passphrase"},
                    ).json()["access_token"]
                    with connect(
                        NOTES_HTTPS.replace("https", "wss") + "/api/v1/ws", ssl=insecure
                    ) as socket_connection:
                        socket_connection.send(json.dumps({"token": token}))
                        print("socket:", json.loads(socket_connection.recv(timeout=10))["type"])
                        created = client.post(
                            "/api/v1/notes",
                            json={"title": "Deployed"},
                            headers={"Authorization": f"Bearer {token}"},
                        )
                        print("created:", created.status_code, created.headers["location"])
                        print("pushed by the worker:", json.loads(socket_connection.recv(timeout=20))["type"])


            if HAS_DOCKER:
                stack_round_trip()
            '''
        ),
        md(
            """
            **Stateless scaling**: two API replicas; Caddy discovers both through Docker's DNS
            and alternates between them (counted from each container's access log):
            """
        ),
        code(
            r"""
            if HAS_DOCKER:
                notes_stack("up", "-d", "--wait", "--scale", "api=2")
                time.sleep(6)  # Caddy refreshes its upstream list every 5 s
                with httpx.Client(base_url=NOTES_HTTPS, verify=False, trust_env=False) as client:
                    for _ in range(20):
                        client.get("/api/v1/notes")
                for container in notes_stack("ps", "-q", "api").split():
                    name = docker("inspect", "--format", "{{.Name}}", container).lstrip("/")
                    served = docker("logs", container).count('"path": "/api/v1/notes"')
                    print(f"{name}: {served} requests")
            """
        ),
        md(
            """
            **Load test** through the proxy, with the locustfile's p95 < 200 ms gate deciding the
            exit code:
            """
        ),
        code(
            r"""
            if HAS_DOCKER:
                locust_prefix = PHASE6_DIR / "notes_v7_locust"
                load_run = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "locust",
                        "-f",
                        str(NOTES_API_DIR / "load" / "locustfile.py"),
                        "--host",
                        NOTES_HTTPS,
                        "--headless",
                        "-u",
                        "20",
                        "-r",
                        "10",
                        "-t",
                        "8s",
                        "--only-summary",
                        "--csv",
                        str(locust_prefix),
                    ],
                    capture_output=True,
                    text=True,
                    env=CHILD_ENV,
                    timeout=180,
                )
                with open(f"{locust_prefix}_stats.csv", newline="") as stats_file:
                    rows = {row["Name"]: row for row in csv.DictReader(stats_file)}
                for name in ("/api/v1/notes", "/api/v1/notes/{id}", "Aggregated"):
                    print(
                        f"{name:20} {rows[name]['Request Count']:>6} requests, "
                        f"{rows[name]['Failure Count']} failures, p95 {rows[name]['95%']} ms"
                    )
                print("exit code (0 = within the SLO):", load_run.returncode)
            """
        ),
        md(
            "Take the stack down (`-v`: the database and Caddy volumes go too) and cancel its exit hook:"
        ),
        code(
            r"""
            if HAS_DOCKER:
                remove_notes_stack()
                atexit.unregister(remove_notes_stack)
                print("stack removed; containers left:", notes_stack("ps", "-aq") or "none")
            """
        ),
    ]


def _notes_v7_ci_cells() -> list[NotebookNode]:
    """Notes API v7: the pipeline's checks, locally; clean up."""
    return [
        md(
            """
            **The pipeline's checks, locally**: the `lint` and `types` jobs, then the `test` job
            the CI way (service URLs pointing at this unit's PostgreSQL and Redis containers, a
            fresh database) for the test files v7 adds, the graceful-shutdown and deployment
            tests (the full suite runs once, in the Phase 6 Project):
            """
        ),
        code(
            r"""
            if HAS_UV:
                for label, command in (
                    ("lint ", ["uv", "run", "--frozen", "ruff", "check", "."]),
                    ("format", ["uv", "run", "--frozen", "ruff", "format", "--check", "."]),
                    ("types", ["uv", "run", "--frozen", "mypy"]),
                ):
                    step = run_in_notes(*command)
                    verdict = (step.stdout.strip().splitlines() or ["(no output)"])[-1]
                    print(f"{label}: exit {step.returncode} | {verdict}")
            """
        ),
        md("And the tests:"),
        code(
            r'''
            async def fresh_database(server_url: str, name: str) -> str:
                """An empty database on the shared server."""
                connection = await asyncpg.connect(server_url.replace("postgresql+asyncpg", "postgresql"))
                try:
                    await connection.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
                    await connection.execute(f"CREATE DATABASE {name}")
                finally:
                    await connection.close()
                return server_url.rsplit("/", 1)[0] + f"/{name}"


            NEW_TESTS = __NEW_TESTS__
            PG_URL, REDIS_URL = start_shared_postgres(), start_shared_redis()
            ci_env = {}
            if PG_URL and REDIS_URL:
                ci_env = {
                    "NOTES_TEST_DATABASE_URL": await fresh_database(PG_URL, "notes_ci"),
                    "NOTES_TEST_REDIS_URL": REDIS_URL,
                }
            if HAS_UV:
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
                    "with service URLs" if ci_env else "without Docker services",
                )
                print(*[line for line in summary if line.startswith(("SKIPPED", "FAILED"))], sep="\n")
            '''
        ),
        md(
            """
            The rest of the pipeline (scan, push, deploy) needs the registry, Trivy's database and
            a server: it runs on GitHub. The workflow's job graph:
            """
        ),
        code(
            r"""
            workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "notes-api.yml").read_text())
            needs = {
                name: [job["needs"]] if isinstance(job.get("needs"), str) else job.get("needs", [])
                for name, job in workflow["jobs"].items()
            }
            print(
                " -> ".join(
                    " + ".join(sorted(wave))
                    for wave in [[name for name in needs if not needs[name]]]
                    + [[name] for name in ("build", "scan", "push", "deploy")]
                )
            )
            print(
                "deploy environment:",
                workflow["jobs"]["deploy"]["environment"]["name"],
                "| push runs on:",
                workflow["jobs"]["push"]["if"][:60],
            )
            """
        ),
        md(
            "The project after Unit 6.8 (tool caches and the local secret removed from the listing):"
        ),
        code(
            r"""
            for cache in (".hypothesis", ".mypy_cache"):
                shutil.rmtree(NOTES_API_DIR / cache, ignore_errors=True)
            print(
                "\n".join(
                    line
                    for line in notes_tree().splitlines()
                    if ".secrets" not in line and "notes_jwt_secret" not in line
                )
            )
            """
        ),
        md(
            """
            **Clean up.** Stop the unit's PostgreSQL and Redis containers and confirm that no
            container started by this notebook is running (the images stay cached for the next
            run):
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
            That completes the Notes API's journey through Phase 6: from an in-memory CRUD app
            (v1) to a secured, observable, containerised service with background work, real-time
            updates, a pipeline and deployment manifests (v7). The *Phase 6 Project* takes it to
            production.
            """
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 6.8."""
    return [
        md(
            """
            ### Recap — Unit 6.8

            | Concept | One-line takeaway | JS / TS equivalent |
            | --- | --- | --- |
            | Process model | one event loop per process; `--workers` or Gunicorn, or one process per container | PM2 / cluster |
            | Pool budget | replicas × processes × (pool + overflow) < `max_connections` (or PgBouncer) | same for `pg` pools |
            | Containers | multi-stage, dependencies before code, slim base, non-root, exec-form `CMD` | multi-stage `node` images |
            | Compose | health checks, `service_completed_successfully` jobs, anchors, `--wait` | same |
            | Config and secrets | 12-factor; validated settings; secrets as files, never in images | `dotenv`, platform secrets |
            | Reverse proxy | TLS, proxy headers (trusted proxies only), WebSockets, hidden internal routes | same proxies |
            | CI/CD | lint, types, tests with services, build, scan, push, reviewed deploy | GitHub Actions for Node |
            | Migrations | a one-off job before rollout; expand → migrate → contract | Prisma `migrate deploy` |
            | Targets | VM, PaaS, Cloud Run / ECS, Kubernetes: trade control for convenience | same platforms |
            | Zero downtime | graceful shutdown, rolling / blue-green / canary, stateless replicas | same |
            | PgBouncer / CDN | multiplex connections; fingerprinted static files cached forever | same |
            | Load testing | Locust users in Python; p95 gates; Little's law for capacity | k6, Artillery |

            **Further reading**

            - [FastAPI in containers](https://fastapi.tiangolo.com/deployment/docker/),
              [Uvicorn deployment](https://www.uvicorn.org/deployment/),
              [uv in Docker](https://docs.astral.sh/uv/guides/integration/docker/)
            - [Dockerfile best practices](https://docs.docker.com/build/building/best-practices/),
              [Compose file reference](https://docs.docker.com/reference/compose-file/),
              [The Twelve-Factor App](https://12factor.net/)
            - [Caddy reverse_proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy),
              [Nginx WebSocket proxying](https://nginx.org/en/docs/http/websocket.html),
              [Traefik Docker provider](https://doc.traefik.io/traefik/providers/docker/)
            - [GitHub Actions: workflow syntax](https://docs.github.com/en/actions/writing-workflows/workflow-syntax-for-github-actions),
              [Trivy](https://trivy.dev/), [pip-audit](https://github.com/pypa/pip-audit)
            - [Kubernetes Deployments](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/),
              [Pod lifecycle and termination](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#pod-termination),
              [Cloud Run](https://cloud.google.com/run/docs), [PgBouncer](https://www.pgbouncer.org/features.html)
            - [Locust](https://docs.locust.io/), [Little's law](https://en.wikipedia.org/wiki/Little%27s_law)
            - Python: [`graphlib`](https://docs.python.org/3/library/graphlib.html),
              [`signal`](https://docs.python.org/3/library/signal.html),
              [`subprocess`](https://docs.python.org/3/library/subprocess.html),
              [PEP 703 (free-threaded CPython)](https://peps.python.org/pep-0703/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 6.8, Lab 6.8 and Notes API v7."""
    return [
        *_overview_cells(),
        *_process_model_cells(),
        *_container_cells(),
        *_compose_cells(),
        *_config_cells(),
        *_proxy_cells(),
        *_cicd_cells(),
        *_migration_cells(),
        *_targets_cells(),
        *_zero_downtime_cells(),
        *_load_test_cells(),
        *_predict_cells(),
        *_lab_setup_cells(),
        *_lab_exercise_1_cells(),
        *_lab_exercise_2_cells(),
        *_lab_exercise_3_cells(),
        *_lab_exercise_4_cells(),
        *_lab_exercise_5_cells(),
        *_lab_exercise_6_cells(),
        *_notes_v7_intro_cells(),
        *_notes_v7_image_cells(),
        *_notes_v7_targets_cells(),
        *_notes_v7_code_cells(),
        *_notes_v7_test_cells(),
        *_notes_v7_build_cells(),
        *_notes_v7_stack_cells(),
        *_notes_v7_ci_cells(),
        *_recap_cells(),
    ]


def _notes_v7_image_cells() -> list[NotebookNode]:
    """Notes API v7: version, project metadata, the image, the Compose stack, the proxy."""
    return [
        md("Version 0.7.0:"),
        code(NOTES_V7_INIT_PY),
        md(
            "**Project metadata.** Version 0.7.0, `mypy` joins the dev tools, and the mypy configuration lists the modules with known typing debt (CI checks everything else):"
        ),
        *writefile_cells(
            NOTES_V7_PYPROJECT_TOML,
            [
                ("", "Part 1 of `pyproject.toml`: from `[project]`."),
                ("[tool.pytest.ini_options]", "Part 2: from `[tool.pytest.ini_options]`."),
            ],
        ),
        md(
            """
            **`Dockerfile`**: three stages. `uv` is copied from its official image; the
            `build` stage installs the locked dependencies first (a cached layer until
            `uv.lock` changes), then the project as a regular package; `runtime` gets only
            the virtual environment and the migrations, a non-root user, a health check, and
            Uvicorn with graceful shutdown:
            """
        ),
        *writefile_cells(
            NOTES_V7_DOCKERFILE,
            [
                ("", "Part 1 of `Dockerfile`: from `# syntax=docker/dockerfile:1`."),
                (
                    "FROM python:${PYTHON_VERSION}-slim AS runtime",
                    "Part 2: from `FROM python:${PYTHON_VERSION}-slim AS runtime`.",
                ),
            ],
        ),
        md(
            "**`.dockerignore`**: an allow-list, so the build context holds only what the image needs (no `.venv`, `.env`, `.secrets` or `.git`):"
        ),
        code(NOTES_V7_DOCKERIGNORE),
        md(
            """
            **`compose.yaml`**: the whole stack. A YAML anchor shares the app settings; `migrate`
            is a one-off job the API and worker wait for (`service_completed_successfully`);
            every service has a health check; only the proxy publishes ports; the app
            containers are read-only, drop all capabilities, and read the JWT secret from a
            file:
            """
        ),
        *writefile_cells(
            NOTES_V7_COMPOSE_YAML,
            [
                (
                    "",
                    "Part 1 of `compose.yaml`: from `# The Notes API stack. Local development needs only the back`.",
                ),
                ("  redis:", "Part 2: `redis`, `api`, `worker` under `services`."),
                ("  proxy:", "Part 3: `proxy` under `services`; then `secrets`, `volumes`."),
            ],
        ),
        md(
            """
            **`deploy/Caddyfile`**: automatic HTTPS, `X-Forwarded-*` headers, WebSockets,
            `/metrics` hidden from the outside, and every `api` container found through
            Docker's DNS (`dynamic a`), so `--scale api=3` needs no configuration change:
            """
        ),
        code(NOTES_V7_DEPLOY_CADDYFILE),
        md(
            "**`deploy/nginx.conf`**: the same with Nginx, where WebSockets and SSE need explicit headers and buffering settings:"
        ),
        *writefile_cells(
            NOTES_V7_DEPLOY_NGINX_CONF,
            [
                (
                    "",
                    "Part 1 of `deploy/nginx.conf`: from `# The same reverse proxy with Nginx (an alternative to deplo`.",
                ),
                ("        location / {", "Part 2: from `location / {`."),
            ],
        ),
        md(
            "**`Procfile`** for Heroku-style platforms: `web`, `worker`, and a `release` phase for migrations:"
        ),
        code(NOTES_V7_PROCFILE),
    ]


def _notes_v7_targets_cells() -> list[NotebookNode]:
    """Notes API v7: Kubernetes, systemd and Cloud Run targets."""
    return [
        md(
            "**Kubernetes.** `config.yaml`: settings in a ConfigMap; the Secret is created out of band, never committed:"
        ),
        code(NOTES_V7_DEPLOY_K8S_CONFIG_YAML),
        md(
            """
            `api-deployment.yaml`: the three probes mapped to the three health endpoints, a
            rolling update that never drops below the wanted replicas, a grace period longer
            than Uvicorn's, a `preStop` pause so traffic stops before SIGTERM, and a locked-down
            container:
            """
        ),
        code(NOTES_V7_DEPLOY_K8S_API_DEPLOYMENT_YAML),
        md("`api-service.yaml`: a Service and a CPU-based HorizontalPodAutoscaler:"),
        code(NOTES_V7_DEPLOY_K8S_API_SERVICE_YAML),
        md("`worker.yaml`: the worker, with the `--check` command as its liveness probe:"),
        code(NOTES_V7_DEPLOY_K8S_WORKER_YAML),
        md("`migrate-job.yaml`: migrations as a Job the pipeline runs before rolling out:"),
        code(NOTES_V7_DEPLOY_K8S_MIGRATE_JOB_YAML),
        md("**A plain VM**: a hardened systemd unit:"),
        code(NOTES_V7_DEPLOY_SYSTEMD_NOTES_API_SERVICE),
        md("**Cloud Run** (Knative service; ECS is the AWS equivalent):"),
        code(NOTES_V7_DEPLOY_CLOUDRUN_SERVICE_YAML),
    ]


def _notes_v7_code_cells() -> list[NotebookNode]:
    """Notes API v7: secrets, PgBouncer, the worker health check, typing fixes, CI/CD, README."""
    return [
        md(
            "`config.py`: `get_settings()` also reads secret files from `/run/secrets` (environment variables still win), and a `database_pgbouncer` switch:"
        ),
        *writefile_cells(
            NOTES_V7_CORE_CONFIG_PY,
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
                    "Part 3 (continues `Settings`): `oauth_enabled()`, `require_real_secrets_in_production()` — True when every OpenID Connect setting is present.",
                ),
                (
                    '    @model_validator(mode="after")\n    def add_redis_password(self) -> Settings:',
                    "Part 4 (continues `Settings`): `add_redis_password()`; then `SECRETS_DIR` — production Redis requires a password (`requirepass`); it comes from the secret file `notes_redis_password` and is added to `redis_url`, which therefore never holds a secret.",
                ),
                (
                    "@lru_cache",
                    "Part 5: `get_settings()` — The process-wide settings, read once and cached (12-factor: config from the environment).",
                ),
            ],
        ),
        md(
            "`db.py`: behind PgBouncer in transaction mode, asyncpg must not cache prepared statements:"
        ),
        *writefile_cells(
            NOTES_V7_DB_PY,
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
            "`worker.py`: `python -m notes_api.worker --check` for container health checks (arq's health key, refreshed every 30 s):"
        ),
        *writefile_cells(
            NOTES_V7_WORKER_PY,
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
                    "Part 7: `run_worker()`, `HEALTH_CHECK_KEY`, `HEALTH_CHECK_SECONDS` — Build the arq Worker inside a running event loop and run it (SIGTERM stops it cleanly).",
                ),
                (
                    "async def worker_is_healthy(settings: Settings) -> bool:",
                    "Part 8: `worker_is_healthy()` — True if some worker refreshed its health key recently (it expires after ~31 s).",
                ),
            ],
        ),
        md("`schemas.py` and `core/sentry.py`: small typing fixes so `mypy` passes in CI:"),
        *writefile_cells(
            NOTES_V7_SCHEMAS_PY,
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
        md("`core/sentry.py` with Sentry's own event types:"),
        *writefile_cells(
            NOTES_V7_CORE_SENTRY_PY,
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
            **CI/CD** (`.github/workflows/notes-api.yml`): lint, types and tests in parallel;
            then build and smoke-test the image, scan it (Trivy) and the locked dependencies
            (pip-audit), push to GHCR for `main` and release tags, and deploy release tags
            through the `production` environment: migrations first, then the containers:
            """
        ),
        *writefile_cells(
            NOTES_V7_GITHUB_WORKFLOWS_NOTES_API_YML,
            [
                (
                    "",
                    "Part 1 of `.github/workflows/notes-api.yml`: from `# CI/CD for the Notes API (projects/notes_api/).`.",
                ),
                ("jobs:", "Part 2: `jobs`: `lint`, `types`."),
                ("  test:", "Part 3: `test` under `jobs`."),
                ("  build:", "Part 4: `build`, `scan` under `jobs`."),
                ("  push:\n    needs: scan", "Part 5: `push`, `deploy` under `jobs`."),
            ],
        ),
        md("The README: deployment commands and the new layout:"),
        *writefile_cells(
            NOTES_V7_README_MD,
            [
                ("", "Part 1 of `README.md`: Notes API."),
                ("## Run", "Part 2: Run."),
                ("## Deploy", "Part 3: Deploy."),
                ("## Endpoints", "Part 4: Endpoints."),
                ("## Layout", "Part 5: Layout."),
                ("## Dependency rule", "Part 6: Dependency rule."),
            ],
        ),
    ]


def _notes_v7_test_cells() -> list[NotebookNode]:
    """Notes API v7: load test and new tests."""
    return [
        md(
            """
            **`load/locustfile.py`**: one shared account, a read-heavy mix, and a quitting hook
            that turns the 200 ms p95 target into the exit code:
            """
        ),
        *writefile_cells(
            NOTES_V7_LOAD_LOCUSTFILE_PY,
            [
                ("", "Part 1 of `load/locustfile.py`: the module docstring and imports."),
                (
                    "@events.test_start.add_listener",
                    "Part 2: `create_account()`, `NotesUser` — Register one user and log in once, before any simulated user starts.",
                ),
                (
                    "    @task(3)",
                    "Part 3 (continues `NotesUser`): `read_note()`, `create_note()`, `feed()`; then `enforce_slo()` — Fail the run (exit code 1) when the latency or error budget is blown.",
                ),
            ],
        ),
        md("**Tests.** `slow_app.py`: the API plus a slow route, only for the shutdown test:"),
        code(NOTES_V7_TESTS_SLOW_APP_PY),
        md("**`test_shutdown.py`**: SIGTERM during a request; the request still succeeds:"),
        *writefile_cells(
            NOTES_V7_TESTS_TEST_SHUTDOWN_PY,
            [
                (
                    "",
                    "Part 1 of `tests/test_shutdown.py`: the module docstring and imports, then `free_port()`.",
                ),
                (
                    "def wait_until_live(base_url: str, process: subprocess.Popen[bytes]) -> None:",
                    "Part 2: `wait_until_live()` — Poll /health/live until the server answers (or fail with its output).",
                ),
                (
                    "def start_slow_server(database_path: Path) -> tuple[subprocess.Popen[bytes], str]:",
                    "Part 3: `start_slow_server()` — Start Uvicorn with slow_app on a free port; return the process and its base URL.",
                ),
                (
                    "def test_sigterm_lets_requests_in_flight_finish(tmp_path: Path) -> None:",
                    "Part 4: `test_sigterm_lets_requests_in_flight_finish()` — A 1.5 s request started before SIGTERM still gets its 200; then the process exits.",
                ),
            ],
        ),
        md("**`test_deploy.py`**: the deployment files and settings, checked statically:"),
        *writefile_cells(
            NOTES_V7_TESTS_TEST_DEPLOY_PY,
            [
                (
                    "",
                    "Part 1 of `tests/test_deploy.py`: the module docstring and imports, then `load_yaml()`, `test_dockerfile_is_multi_stage_and_unprivileged()`.",
                ),
                (
                    "def test_compose_stack_order_and_health() -> None:",
                    "Part 2: `test_compose_stack_order_and_health()`, `test_compose_secret_comes_from_an_ignored_file()`, `test_kubernetes_api_probes_and_rollout()` — Migrations run before api/worker; backing services and the worker have health checks.",
                ),
                (
                    "def test_proxy_blocks_metrics_and_procfile_has_three_processes() -> None:",
                    "Part 3: `test_proxy_blocks_metrics_and_procfile_has_three_processes()`, `test_secrets_are_read_from_files()`, `test_redis_password_file_goes_into_the_url()` — Caddy hides /metrics; the PaaS Procfile declares web, worker and release.",
                ),
                (
                    "def test_pgbouncer_mode_disables_statement_caches(monkeypatch: pytest.MonkeyPatch) -> None:",
                    "Part 4: `test_pgbouncer_mode_disables_statement_caches()` — Behind PgBouncer in transaction mode, asyncpg must not cache prepared statements.",
                ),
                (
                    "async def test_worker_health_check(monkeypatch: pytest.MonkeyPatch) -> None:",
                    "Part 5: `test_worker_health_check()`, `_noop()` — --check passes while a worker keeps its health key fresh, fails when it is gone.",
                ),
            ],
        ),
    ]


NOTES_V7_INIT_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/__init__.py
"""Notes API: a FastAPI service built step by step in Phase 6 of the course."""

__version__ = "0.7.0"
'''

NOTES_V7_PYPROJECT_TOML = r"""
%%writefile ../projects/notes_api/pyproject.toml
[project]
name = "notes-api"
version = "0.7.0"
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
    "mypy>=2.4.1",
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


[tool.mypy]
python_version = "3.15"
files = ["src/notes_api"]
warn_unused_ignores = true
warn_redundant_casts = true

# Typing debt: these modules have known errors (SQLAlchemy result types, Starlette's handler
# signature, Redis response unions). CI type-checks everything else; remove a module from the
# list once it passes, never add one.
[[tool.mypy.overrides]]
module = [
    "notes_api.core.errors",
    "notes_api.exports",
    "notes_api.repositories",
    "notes_api.routers.exports",
    "notes_api.routers.pages",
]
ignore_errors = true
"""

NOTES_V7_DOCKERFILE = r"""
%%writefile ../projects/notes_api/Dockerfile
# syntax=docker/dockerfile:1
# The Notes API image (API and worker). Stage "build" installs the locked dependencies with uv
# into /app/.venv; stage "runtime" copies only that environment and the migrations, and runs
# as an unprivileged user. Build: docker build -t notes-api .
ARG PYTHON_VERSION=3.15

FROM ghcr.io/astral-sh/uv:0.13.5 AS uv


FROM python:${PYTHON_VERSION}-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
# 1. Dependencies only: this layer is reused until uv.lock or pyproject.toml change.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project
# 2. The project itself, installed as a regular package (no link back to /app/src).
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable


FROM python:${PYTHON_VERSION}-slim AS runtime
# Debian security fixes published after the base image was built (CI fails on fixable
# HIGH/CRITICAL findings), and no pip: the app runs from /app/.venv and installs nothing,
# while the base image's pip vendors its own urllib3, msgpack and setuptools copies.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade --yes \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall --yes --root-user-action=ignore pip
RUN groupadd --system --gid 10001 notes \
    && useradd --system --uid 10001 --gid notes --no-create-home --shell /usr/sbin/nologin notes \
    && install -d -o notes -g notes /tmp/prometheus
WORKDIR /app
COPY --from=build --chown=notes:notes /app/.venv /app/.venv
COPY --chown=notes:notes alembic.ini ./
COPY --chown=notes:notes alembic ./alembic
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WEB_CONCURRENCY=2 \
    PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus \
    NOTES_ENVIRONMENT=production
USER notes
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health/live', timeout=2)"]
# Uvicorn reads WEB_CONCURRENCY (worker processes) and FORWARDED_ALLOW_IPS (trusted proxies).
CMD ["uvicorn", "notes_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--timeout-graceful-shutdown", "20"]
"""

NOTES_V7_DOCKERIGNORE = r"""
%%writefile ../projects/notes_api/.dockerignore
# Only what the image needs goes into the build context: smaller, faster, no secrets.
**
!pyproject.toml
!uv.lock
!README.md
!src/
!alembic.ini
!alembic/
**/__pycache__
**/*.pyc
"""

NOTES_V7_COMPOSE_YAML = r"""
%%writefile ../projects/notes_api/compose.yaml
# The Notes API stack. Local development needs only the backing services:
#     docker compose up -d --wait db redis       (then run the API and worker with uv)
# The whole stack, built from the Dockerfile, behind Caddy with TLS:
#     mkdir -p .secrets && openssl rand -base64 32 > .secrets/notes_jwt_secret   (git-ignored)
#     chmod 444 .secrets/notes_jwt_secret        (the container user, uid 10001, must read it)
#     docker compose up -d --build --wait
#     open https://localhost:8443                (stop: docker compose down; add -v for data)
name: notes

x-app: &app # shared by api, worker and migrate (YAML anchor)
  build: .
  image: ${NOTES_IMAGE:-notes-api}:${TAG:-latest} # CI deploys ghcr.io/<owner>/notes-api:<version>
  environment:
    NOTES_DATABASE_URL: postgresql+asyncpg://notes:${POSTGRES_PASSWORD:-notes}@db:5432/notes
    NOTES_REDIS_URL: redis://redis:6379/0
    NOTES_ENVIRONMENT: production
    FORWARDED_ALLOW_IPS: "*" # only Caddy can reach the app on this network
  secrets: [notes_jwt_secret] # a file in /run/secrets, read by get_settings()
  read_only: true # nothing in the image can be modified at run time ...
  tmpfs: ["/tmp:mode=1777", "/tmp/prometheus:mode=1777"] # ... except scratch space
  security_opt: ["no-new-privileges:true"]
  cap_drop: [ALL]
  restart: unless-stopped

services:
  db:
    image: postgres:18-alpine
    environment:
      POSTGRES_USER: notes
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-notes} # local default; set it for real use
      POSTGRES_DB: notes
    ports: ["127.0.0.1:${POSTGRES_PORT:-5432}:5432"]
    volumes: ["notes-db:/var/lib/postgresql"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U notes -d notes"]
      interval: 2s
      timeout: 3s
      retries: 15

  redis:
    image: redis:7.4
    ports: ["127.0.0.1:${REDIS_PORT:-6379}:6379"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 2s
      timeout: 3s
      retries: 15

  migrate: # a one-off job: run the migrations, exit; api and worker wait for it
    <<: *app
    command: ["alembic", "upgrade", "head"]
    restart: "no"
    depends_on:
      db: { condition: service_healthy }

  api:
    <<: *app
    expose: ["8000"] # reachable from the proxy, not from the host
    depends_on:
      migrate: { condition: service_completed_successfully }
      redis: { condition: service_healthy }

  worker:
    <<: *app
    command: ["python", "-m", "notes_api.worker"]
    healthcheck:
      test: ["CMD", "python", "-m", "notes_api.worker", "--check"]
      interval: 10s
      timeout: 5s
      start_period: 15s
      retries: 3
    depends_on:
      migrate: { condition: service_completed_successfully }
      redis: { condition: service_healthy }

  proxy:
    image: caddy:2
    ports: ["127.0.0.1:${HTTPS_PORT:-8443}:443", "127.0.0.1:${HTTP_PORT:-8080}:80"]
    volumes: ["./deploy/Caddyfile:/etc/caddy/Caddyfile:ro", "caddy-data:/data"]
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://127.0.0.1:2019/config/"]
      interval: 5s
      timeout: 3s
      retries: 10
    depends_on:
      api: { condition: service_healthy }

secrets:
  notes_jwt_secret:
    file: ./.secrets/notes_jwt_secret # never committed (.gitignore), mounted read-only

volumes:
  notes-db:
  caddy-data:
"""

NOTES_V7_DEPLOY_CADDYFILE = r"""
%%writefile ../projects/notes_api/deploy/Caddyfile
# Caddy in front of the Notes API. Automatic HTTPS: a public domain gets a Let's Encrypt
# certificate, "localhost" one from Caddy's internal CA. HTTP is redirected to HTTPS, the
# X-Forwarded-* headers are set, and WebSocket upgrades pass through without extra settings.
{
	admin localhost:2019
}

{$NOTES_SITE:localhost} {
	encode zstd gzip
	header -Server
	header /static/* Cache-Control "public, max-age=86400" # a CDN can cache these too

	@internal path /metrics /metrics/*
	respond @internal 404 # Prometheus scrapes the app directly, inside the network

	reverse_proxy {
		dynamic a api 8000 { # every "api" container: docker compose up --scale api=3
			refresh 5s
		}
		lb_policy round_robin
		health_uri /health/ready # stop sending traffic to a replica that is not ready
		health_interval 5s
	}

	log {
		output stdout
		format json
	}
}
"""

NOTES_V7_DEPLOY_NGINX_CONF = r"""
%%writefile ../projects/notes_api/deploy/nginx.conf
# The same reverse proxy with Nginx (an alternative to deploy/Caddyfile). Certificates come
# from elsewhere (certbot, a secret store); Nginx does not obtain them itself.
events {}

http {
    upstream notes_api {
        server api:8000;
        keepalive 32;
    }

    map $http_upgrade $connection_upgrade { # WebSockets need these two headers forwarded
        default upgrade;
        ""      close;
    }

    server {
        listen 80;
        return 301 https://$host$request_uri;
    }

    server {
        listen 443 ssl;
        http2 on;
        ssl_certificate     /etc/nginx/tls/fullchain.pem;
        ssl_certificate_key /etc/nginx/tls/privkey.pem;
        ssl_protocols       TLSv1.2 TLSv1.3;
        add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

        location = /metrics { return 404; }

        location / {
            proxy_pass http://notes_api;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            proxy_read_timeout 3600s; # long-lived WebSockets and SSE streams
            proxy_buffering off;      # SSE events must not wait in a buffer
        }
    }
}
"""

NOTES_V7_PROCFILE = r"""
%%writefile ../projects/notes_api/Procfile
web: uvicorn notes_api.main:app --host 0.0.0.0 --port $PORT --proxy-headers --timeout-graceful-shutdown 20
worker: python -m notes_api.worker
release: alembic upgrade head
"""

NOTES_V7_DEPLOY_K8S_CONFIG_YAML = r"""
%%writefile ../projects/notes_api/deploy/k8s/config.yaml
# Configuration for the Kubernetes deployment. Plain settings live in a ConfigMap; secrets are
# created out of band, never committed, e.g.:
#   kubectl create secret generic notes-secrets \
#     --from-literal=NOTES_JWT_SECRET="$(openssl rand -base64 32)" \
#     --from-literal=NOTES_DATABASE_URL='postgresql+asyncpg://notes:<password>@<host>:5432/notes'
apiVersion: v1
kind: ConfigMap
metadata:
  name: notes-config
data:
  NOTES_ENVIRONMENT: production
  NOTES_REDIS_URL: redis://redis:6379/0
  NOTES_LOG_LEVEL: INFO
  NOTES_OTEL_EXPORTER: otlp
  NOTES_OTEL_ENDPOINT: http://otel-collector:4318/v1/traces
  FORWARDED_ALLOW_IPS: "*" # only the ingress controller reaches the pods
"""

NOTES_V7_DEPLOY_K8S_API_DEPLOYMENT_YAML = r"""
%%writefile ../projects/notes_api/deploy/k8s/api-deployment.yaml
# The API: stateless replicas, replaced one at a time, never fewer ready pods than wanted.
apiVersion: apps/v1
kind: Deployment
metadata:
  name: notes-api
spec:
  replicas: 3
  selector: { matchLabels: { app: notes-api } }
  strategy: { type: RollingUpdate, rollingUpdate: { maxSurge: 1, maxUnavailable: 0 } }
  template:
    metadata: { labels: { app: notes-api } }
    spec:
      terminationGracePeriodSeconds: 30 # longer than uvicorn --timeout-graceful-shutdown 20
      securityContext: { runAsNonRoot: true, runAsUser: 10001 }
      containers:
        - name: api
          image: ghcr.io/example/notes-api:0.7.0 # CI pushes ghcr.io/<owner>/notes-api:<tag>
          ports: [{ containerPort: 8000 }]
          envFrom: [{ configMapRef: { name: notes-config } }, { secretRef: { name: notes-secrets } }]
          env: [{ name: WEB_CONCURRENCY, value: "1" }] # one process per pod; scale with pods
          resources: { requests: { cpu: 250m, memory: 256Mi }, limits: { memory: 512Mi } }
          startupProbe: # migrations done? until then the other probes wait
            httpGet: { path: /health/startup, port: 8000 }
            periodSeconds: 2
            failureThreshold: 60
          readinessProbe: # database and Redis reachable? if not, no traffic (not restarted)
            httpGet: { path: /health/ready, port: 8000 }
            periodSeconds: 5
          livenessProbe: # process stuck? restart it (no dependency checks here)
            httpGet: { path: /health/live, port: 8000 }
            periodSeconds: 10
          lifecycle: { preStop: { sleep: { seconds: 5 } } } # endpoints update before SIGTERM
          securityContext:
            { readOnlyRootFilesystem: true, allowPrivilegeEscalation: false, capabilities: { drop: [ALL] } }
          volumeMounts: [{ name: tmp, mountPath: /tmp }, { name: metrics, mountPath: /tmp/prometheus }]
      volumes: [{ name: tmp, emptyDir: {} }, { name: metrics, emptyDir: {} }]
"""

NOTES_V7_DEPLOY_K8S_API_SERVICE_YAML = r"""
%%writefile ../projects/notes_api/deploy/k8s/api-service.yaml
# A stable address for the API pods, and horizontal autoscaling on CPU (stateless scaling).
apiVersion: v1
kind: Service
metadata:
  name: notes-api
spec:
  selector: { app: notes-api }
  ports: [{ port: 80, targetPort: 8000 }]
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: notes-api
spec:
  scaleTargetRef: { apiVersion: apps/v1, kind: Deployment, name: notes-api }
  minReplicas: 3
  maxReplicas: 12 # x pool size must stay below the database's max_connections (or PgBouncer)
  metrics:
    - type: Resource
      resource: { name: cpu, target: { type: Utilization, averageUtilization: 70 } }
"""

NOTES_V7_DEPLOY_K8S_WORKER_YAML = r"""
%%writefile ../projects/notes_api/deploy/k8s/worker.yaml
# The ARQ worker: no Service (it serves nothing); liveness from its Redis health key.
apiVersion: apps/v1
kind: Deployment
metadata:
  name: notes-worker
spec:
  replicas: 2
  selector: { matchLabels: { app: notes-worker } }
  template:
    metadata: { labels: { app: notes-worker } }
    spec:
      terminationGracePeriodSeconds: 60 # a job in progress may finish
      securityContext: { runAsNonRoot: true, runAsUser: 10001 }
      containers:
        - name: worker
          image: ghcr.io/example/notes-api:0.7.0
          command: ["python", "-m", "notes_api.worker"]
          envFrom: [{ configMapRef: { name: notes-config } }, { secretRef: { name: notes-secrets } }]
          resources: { requests: { cpu: 100m, memory: 256Mi }, limits: { memory: 512Mi } }
          livenessProbe:
            exec: { command: ["python", "-m", "notes_api.worker", "--check"] }
            periodSeconds: 30
            initialDelaySeconds: 20
          securityContext: { readOnlyRootFilesystem: true, allowPrivilegeEscalation: false }
          volumeMounts: [{ name: tmp, mountPath: /tmp }, { name: metrics, mountPath: /tmp/prometheus }]
      volumes: [{ name: tmp, emptyDir: {} }, { name: metrics, emptyDir: {} }]
"""

NOTES_V7_DEPLOY_K8S_MIGRATE_JOB_YAML = r"""
%%writefile ../projects/notes_api/deploy/k8s/migrate-job.yaml
# Migrations as a one-off Job, run by the pipeline before the new Deployment rolls out
# (kubectl apply -f migrate-job.yaml && kubectl wait --for=condition=complete job/notes-migrate).
# Migrations must be backward compatible (expand/contract): old pods keep running meanwhile.
apiVersion: batch/v1
kind: Job
metadata:
  name: notes-migrate
spec:
  backoffLimit: 1
  ttlSecondsAfterFinished: 3600
  template:
    spec:
      restartPolicy: Never
      securityContext: { runAsNonRoot: true, runAsUser: 10001 }
      containers:
        - name: migrate
          image: ghcr.io/example/notes-api:0.7.0
          command: ["alembic", "upgrade", "head"]
          envFrom: [{ configMapRef: { name: notes-config } }, { secretRef: { name: notes-secrets } }]
"""

NOTES_V7_DEPLOY_SYSTEMD_NOTES_API_SERVICE = r"""
%%writefile ../projects/notes_api/deploy/systemd/notes-api.service
# A plain VM: systemd runs Uvicorn behind Caddy or Nginx on the same host.
# Install the project into /opt/notes-api (uv sync --frozen --no-dev), put settings in
# /etc/notes-api/env (mode 600), then: systemctl enable --now notes-api
[Unit]
Description=Notes API (Uvicorn)
After=network-online.target
Wants=network-online.target

[Service]
User=notes
Group=notes
WorkingDirectory=/opt/notes-api
EnvironmentFile=/etc/notes-api/env
ExecStartPre=/opt/notes-api/.venv/bin/alembic upgrade head
ExecStart=/opt/notes-api/.venv/bin/uvicorn notes_api.main:app --host 127.0.0.1 --port 8000 \
    --workers 4 --proxy-headers --timeout-graceful-shutdown 20
KillSignal=SIGTERM
TimeoutStopSec=30
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
"""

NOTES_V7_DEPLOY_CLOUDRUN_SERVICE_YAML = r"""
%%writefile ../projects/notes_api/deploy/cloudrun/service.yaml
# Google Cloud Run (Knative): gcloud run services replace deploy/cloudrun/service.yaml
# Cloud Run scales containers on requests (to zero when idle), so the ARQ worker runs elsewhere
# (a VM, a Kubernetes Deployment, or Cloud Run with CPU always allocated). AWS ECS/Fargate is
# similar: a task definition with the same image, health check and secrets from Secrets Manager.
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: notes-api
spec:
  template:
    metadata:
      annotations:
        autoscaling.knative.dev/minScale: "1" # no cold start for the first request
        autoscaling.knative.dev/maxScale: "10"
    spec:
      containerConcurrency: 80
      timeoutSeconds: 300
      containers:
        - image: europe-docker.pkg.dev/example/notes/notes-api:0.7.0
          ports: [{ containerPort: 8000 }]
          env:
            - { name: WEB_CONCURRENCY, value: "1" }
            - name: NOTES_JWT_SECRET
              valueFrom: { secretKeyRef: { name: notes-jwt-secret, key: latest } }
            - name: NOTES_DATABASE_URL
              valueFrom: { secretKeyRef: { name: notes-database-url, key: latest } }
          startupProbe: { httpGet: { path: /health/startup }, periodSeconds: 2, failureThreshold: 30 }
          livenessProbe: { httpGet: { path: /health/live }, periodSeconds: 10 }
"""

NOTES_V7_CORE_CONFIG_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/core/config.py
"""Application settings: environment variables (prefix NOTES_) and an optional .env file."""

import urllib.parse
from functools import lru_cache
from pathlib import Path
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
    database_pgbouncer: bool = False  # behind PgBouncer (transaction pooling): no statement cache
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")
    redis_password: SecretStr | None = None  # production: the secret file notes_redis_password

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

    @model_validator(mode="after")
    def add_redis_password(self) -> Settings:
        """Put redis_password into redis_url (redis://:<password>@host) unless it has one, so
        the URL in compose.yaml stays free of secrets and the password lives in a file."""
        url = urllib.parse.urlsplit(self.redis_url.get_secret_value())
        if self.redis_password is None or url.password:
            return self
        password = urllib.parse.quote(self.redis_password.get_secret_value(), safe="")
        host = f"{url.hostname}:{url.port}" if url.port else str(url.hostname)
        netloc = f"{url.username or ''}:{password}@{host}"
        self.redis_url = SecretStr(url._replace(netloc=netloc).geturl())
        return self


SECRETS_DIR = Path("/run/secrets")  # where Docker, Compose and Kubernetes mount secret files


@lru_cache
def get_settings() -> Settings:
    """The process-wide settings, read once and cached (12-factor: config from the environment).

    Order of precedence: environment variables, then .env, then secret files in /run/secrets
    (a file named notes_jwt_secret holds NOTES_JWT_SECRET), then the defaults.
    """
    if SECRETS_DIR.is_dir():
        return Settings(_secrets_dir=SECRETS_DIR)  # type: ignore[call-arg]  # a pydantic-settings init option
    return Settings()
'''

NOTES_V7_DB_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/db.py
"""Database plumbing: naming conventions, the declarative base, the engine and sessions."""

import uuid
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
    connect_args = {}
    if settings.database_pgbouncer:
        # PgBouncer in transaction mode hands each transaction to any server connection, so
        # prepared statements cached on one connection do not exist on the next one.
        connect_args = {
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4()}__",
        }
    return create_async_engine(
        url,
        echo=settings.database_echo,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,  # replace connections the server closed while idle
        connect_args=connect_args,
    )


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Sessions whose objects stay readable after commit (the response is built after it)."""
    return async_sessionmaker(engine, expire_on_commit=False)
'''

NOTES_V7_WORKER_PY = r'''
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
        health_check_interval=HEALTH_CHECK_SECONDS,  # arq's default is an hour
        max_tries=WorkerSettings.max_tries if settings is None else settings.webhook_max_attempts,
        job_timeout=WorkerSettings.job_timeout,
        keep_result=WorkerSettings.keep_result,
    )
    try:
        await worker.main()
    finally:
        await worker.close()


HEALTH_CHECK_KEY = "arq:queue:health-check"  # arq refreshes it every health_check_interval
HEALTH_CHECK_SECONDS = 30


async def worker_is_healthy(settings: Settings) -> bool:
    """True if some worker refreshed its health key recently (it expires after ~31 s)."""
    redis = redis_asyncio.from_url(settings.redis_url.get_secret_value())
    try:
        return bool(await redis.exists(HEALTH_CHECK_KEY))
    except OSError, redis_asyncio.RedisError:
        return False
    finally:
        await redis.aclose()


if __name__ == "__main__":
    if "--check" in sys.argv:  # container health check: exit 0 = healthy
        sys.exit(0 if asyncio.run(worker_is_healthy(get_settings())) else 1)
    asyncio.run(run_worker(burst="--burst" in sys.argv))
'''

NOTES_V7_SCHEMAS_PY = r'''
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

    @computed_field  # type: ignore[prop-decorator]  # mypy does not model this pydantic idiom
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

NOTES_V7_CORE_SENTRY_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/core/sentry.py
"""Error tracking with Sentry: off unless NOTES_SENTRY_DSN is set; secrets are scrubbed first."""

import importlib.util
import logging
from typing import TYPE_CHECKING, Any

from notes_api import __version__
from notes_api.core.config import Settings
from notes_api.core.logging import redact_value

if TYPE_CHECKING:
    from sentry_sdk.types import Event, Hint

logger = logging.getLogger("notes_api.sentry")


def scrub_event(event: Event, _hint: Hint) -> Event | None:
    """before_send hook: redact headers, cookies, bodies and messages before they leave."""
    request: dict[str, Any] = event.get("request", {})
    for part in ("headers", "cookies", "data", "query_string"):
        if isinstance(request.get(part), dict):
            request[part] = {key: redact_value(key, value) for key, value in request[part].items()}
        elif isinstance(request.get(part), str):
            request[part] = redact_value(part, request[part])
    if isinstance(event.get("logentry"), dict):
        event["logentry"] = redact_value("logentry", event["logentry"])  # type: ignore[typeddict-item]
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

NOTES_V7_GITHUB_WORKFLOWS_NOTES_API_YML = r"""
%%writefile ../.github/workflows/notes-api.yml
# CI/CD for the Notes API (projects/notes_api/).
#
#   lint ─┐
#   types ├─> build image (+ smoke test) ─> scan ─> push to GHCR ─> deploy (tags only)
#   test ─┘   (test: PostgreSQL and Redis as service containers)
#
# Pushes go to ghcr.io/<owner>/notes-api for the main branch and for tags notes-api-v*; only a
# tag deploys, through the "production" environment (configure required reviewers there).
# Actions are pinned to commit SHAs; the comment names the release.
name: notes-api

on:
  push:
    branches: ["**"]
    tags: ["notes-api-v*"]
    paths: ["projects/notes_api/**", ".github/workflows/notes-api.yml"]
  pull_request:
    paths: ["projects/notes_api/**", ".github/workflows/notes-api.yml"]
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: notes-api-${{ github.ref }}
  cancel-in-progress: ${{ !startsWith(github.ref, 'refs/tags/') }}

env:
  IMAGE: ghcr.io/${{ github.repository_owner }}/notes-api

defaults:
  run:
    working-directory: projects/notes_api


jobs:
  lint:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - uses: astral-sh/setup-uv@37802adc94f370d6bfd71619e3f0bf239e1f3b78 # v7.6.0
        with: { python-version: "3.15", enable-cache: true, cache-dependency-glob: projects/notes_api/uv.lock }
      - run: uv sync --frozen
      - run: uv run ruff check . && uv run ruff format --check .

  types:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - uses: astral-sh/setup-uv@37802adc94f370d6bfd71619e3f0bf239e1f3b78 # v7.6.0
        with: { python-version: "3.15", enable-cache: true, cache-dependency-glob: projects/notes_api/uv.lock }
      - run: uv sync --frozen
      - run: uv run mypy # files and the typing-debt list are in pyproject.toml

  test:
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    services:
      postgres:
        image: postgres:18-alpine
        env: { POSTGRES_USER: notes, POSTGRES_PASSWORD: notes, POSTGRES_DB: notes_test } # CI only
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U notes -d notes_test"
          --health-interval 2s --health-timeout 3s --health-retries 15
      redis:
        image: redis:7.4
        ports: ["6379:6379"]
        options: --health-cmd "redis-cli ping" --health-interval 2s --health-timeout 3s --health-retries 15
    env:
      NOTES_TEST_DATABASE_URL: postgresql+asyncpg://notes:notes@localhost:5432/notes_test
      NOTES_TEST_REDIS_URL: redis://localhost:6379/0
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - uses: astral-sh/setup-uv@37802adc94f370d6bfd71619e3f0bf239e1f3b78 # v7.6.0
        with: { python-version: "3.15", enable-cache: true, cache-dependency-glob: projects/notes_api/uv.lock }
      - run: uv sync --frozen
      - run: uv run pytest -p no:cacheprovider -rs --junitxml=test-results.xml
      - if: always()
        uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2
        with: { name: notes-api-test-results, path: projects/notes_api/test-results.xml }

  build:
    needs: [lint, types, test]
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - name: Build the image
        run: docker build --tag "$IMAGE:$GITHUB_SHA" .
      - name: Report the image size
        run: docker image inspect "$IMAGE:$GITHUB_SHA" --format 'size={{.Size}}' >> "$GITHUB_STEP_SUMMARY"
      - name: Smoke test (the container starts and answers its liveness probe)
        # The image has only the production driver (asyncpg; aiosqlite is a dev dependency).
        # Nothing listens on port 9: the engine connects lazily and /health/live touches no
        # dependency, so this checks that the app imports, configures and starts.
        run: |
          docker run --detach --name smoke --publish 8000:8000 \
            --env NOTES_ENVIRONMENT=test --env NOTES_CHECK_MIGRATIONS=false \
            --env NOTES_DATABASE_URL=postgresql+asyncpg://smoke:smoke@127.0.0.1:9/smoke "$IMAGE:$GITHUB_SHA"
          for attempt in $(seq 30); do curl --fail --silent localhost:8000/health/live && exit 0; sleep 1; done
          docker logs smoke; exit 1
      - run: docker save "$IMAGE:$GITHUB_SHA" | gzip > image.tar.gz
      - uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2
        with: { name: notes-api-image, path: projects/notes_api/image.tar.gz, retention-days: 3 }

  scan:
    needs: build
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - uses: actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333 # v8.0.2
        with: { name: notes-api-image, path: projects/notes_api }
      - run: gunzip -c image.tar.gz | docker load
      - name: Vulnerabilities in the image (OS packages and Python wheels)
        run: |
          docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:0.58.1 \
            image --exit-code 1 --severity CRITICAL,HIGH --ignore-unfixed "$IMAGE:$GITHUB_SHA"
      - uses: astral-sh/setup-uv@37802adc94f370d6bfd71619e3f0bf239e1f3b78 # v7.6.0
        with: { python-version: "3.15" } # never the runner's system Python
      - name: Known vulnerabilities in the locked dependencies
        # Only the third-party pins (no line for the project itself), audited as listed:
        # pip-audit installs nothing, so no Python version can reject a package.
        run: |
          uv export --frozen --no-dev --no-hashes --no-emit-project > requirements.txt
          uvx pip-audit --disable-pip --no-deps -r requirements.txt

  push:
    needs: scan
    if: github.event_name == 'push' && (github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/tags/notes-api-v'))
    runs-on: ubuntu-24.04
    permissions: { contents: read, packages: write }
    steps:
      - uses: actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333 # v8.0.2
        with: { name: notes-api-image, path: projects/notes_api }
      - run: gunzip -c image.tar.gz | docker load
      - name: Push the commit tag, plus the version tag (tags) or latest (main)
        env: { GH_TOKEN: "${{ secrets.GITHUB_TOKEN }}" }
        run: |
          echo "$GH_TOKEN" | docker login ghcr.io --username "$GITHUB_ACTOR" --password-stdin
          extra="latest"
          if [[ "$GITHUB_REF" == refs/tags/* ]]; then extra="${GITHUB_REF_NAME#notes-api-v}"; fi
          docker tag "$IMAGE:$GITHUB_SHA" "$IMAGE:$extra"
          docker push "$IMAGE:$GITHUB_SHA" && docker push "$IMAGE:$extra"

  deploy:
    needs: push
    if: startsWith(github.ref, 'refs/tags/notes-api-v')
    runs-on: ubuntu-24.04
    environment: { name: production, url: "https://${{ vars.NOTES_HOST }}" }
    steps:
      - name: Migrate, then replace the containers one service at a time
        env: { SSH_KEY: "${{ secrets.DEPLOY_SSH_KEY }}", HOST: "${{ vars.NOTES_HOST }}" }
        run: |
          install -m 600 /dev/null ~/.ssh_key && printf '%s\n' "$SSH_KEY" > ~/.ssh_key
          ssh -i ~/.ssh_key -o StrictHostKeyChecking=accept-new "deploy@$HOST" \
            "cd /srv/notes && export TAG=${GITHUB_REF_NAME#notes-api-v} && docker compose pull \
             && docker compose run --rm migrate && docker compose up -d --no-deps --wait api worker"
"""

NOTES_V7_README_MD = r"""
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
| v7 | 6.8 | a multi-stage uv Dockerfile (non-root, read-only), a Compose stack (db, redis, migrate job, api, worker, Caddy with TLS), an Nginx alternative, Kubernetes / systemd / Procfile / Cloud Run targets, Docker secrets, PgBouncer mode, a worker health check, a CI/CD pipeline (lint, types, test, build, scan, push, deploy), a graceful-shutdown test and a Locust load test with a p95 gate |


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


## Deploy

```bash
mkdir -p .secrets && openssl rand -base64 32 > .secrets/notes_jwt_secret && chmod 444 .secrets/notes_jwt_secret
docker compose up -d --build --wait           # db, redis, migrate (one-off), api, worker, proxy
curl -k https://localhost:8443/health/ready   # Caddy terminates TLS (its local CA for localhost)
docker compose up -d --wait --scale api=3     # stateless API: Caddy balances the replicas
uv run locust -f load/locustfile.py --host https://localhost:8443 --headless -u 20 -r 10 -t 30s
docker compose down                           # -v also deletes the database volume
```

The image (`Dockerfile`) runs Uvicorn with `WEB_CONCURRENCY` worker processes, trusts proxy
headers, and shuts down gracefully (20 s) on SIGTERM. `deploy/` holds the Caddyfile, an Nginx
equivalent, Kubernetes manifests (probes, rolling updates, a migrate Job, an autoscaler), a
systemd unit and a Cloud Run service; `Procfile` covers Heroku-style platforms. CI/CD:
`.github/workflows/notes-api.yml`.


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
compose.yaml          # the stack: db, redis, migrate, api, worker, proxy (Caddy)
Dockerfile            # multi-stage uv build, non-root runtime; .dockerignore
deploy/               # Caddyfile, nginx.conf, k8s/, systemd/, cloudrun/
load/locustfile.py    # load test with a p95 < 200 ms gate
Procfile              # web / worker / release for a PaaS
tests/                # pytest: one app, SQLite file and fakeredis per test; factories.py;
                      # PostgreSQL / Redis tests use CI services or testcontainers;
                      # test_contract.py: Schemathesis + snapshots/openapi.json
```


## Dependency rule

Dependencies point inwards: routers → services → repositories → models. Nothing in
`services.py`, `auth.py`, `security.py`, `repositories.py`, `models.py`, `db.py` or
`exceptions.py` imports FastAPI; `core/errors.py` maps domain exceptions to HTTP responses.
"""

NOTES_V7_LOAD_LOCUSTFILE_PY = r'''
%%writefile ../projects/notes_api/load/locustfile.py
"""Load test for the Notes API (Locust).

    uv run locust -f load/locustfile.py --host http://127.0.0.1:8000 --headless -u 20 -r 10 -t 30s

One account is created when the test starts (registration is rate-limited per address, as it
should be) and every simulated user shares its token. Users mostly read (list, one note, the
feed) and sometimes write. The run exits with code 1 when the 95th percentile is above
P95_LIMIT_MS or more than MAX_FAILURE_RATIO of the requests fail: a pass/fail gate for CI.
"""

import random
import secrets
from typing import Any

import requests
from locust import HttpUser, between, events, task

P95_LIMIT_MS = 200
MAX_FAILURE_RATIO = 0.01
SHARED: dict[str, str] = {}


@events.test_start.add_listener
def create_account(environment: Any, **_kwargs: Any) -> None:
    """Register one user and log in once, before any simulated user starts."""
    email, password = f"load-{secrets.token_hex(4)}@example.com", secrets.token_urlsafe(16)
    host = environment.host
    requests.post(
        f"{host}/api/v1/auth/register",
        json={"email": email, "password": password},
        verify=False,
        timeout=10,
    )
    reply = requests.post(
        f"{host}/api/v1/auth/token",
        data={"username": email, "password": password},
        verify=False,
        timeout=10,
    )
    SHARED["authorization"] = f"Bearer {reply.json()['access_token']}"


class NotesUser(HttpUser):
    """A user who reads a lot and writes a little."""

    wait_time = between(0.05, 0.2)

    def on_start(self) -> None:
        """Use the shared token; accept the proxy's local certificate."""
        self.client.headers["Authorization"] = SHARED["authorization"]
        self.client.verify = False  # Caddy's internal CA in the local stack
        self.note_ids: list[int] = []

    @task(5)
    def list_notes(self) -> None:
        """The most common request."""
        self.client.get("/api/v1/notes?limit=20", name="/api/v1/notes")

    @task(3)
    def read_note(self) -> None:
        """One note (cache and ETag path)."""
        if self.note_ids:
            note_id = random.choice(self.note_ids)
            self.client.get(f"/api/v1/notes/{note_id}", name="/api/v1/notes/{id}")

    @task(1)
    def create_note(self) -> None:
        """A write: database transaction, outbox row, cache invalidation."""
        reply = self.client.post("/api/v1/notes", json={"title": f"Load {secrets.token_hex(3)}"})
        if reply.status_code == 201:
            self.note_ids.append(reply.json()["id"])

    @task(1)
    def feed(self) -> None:
        """Keyset pagination."""
        self.client.get("/api/v1/notes/feed?limit=10", name="/api/v1/notes/feed")


@events.quitting.add_listener
def enforce_slo(environment: Any, **_kwargs: Any) -> None:
    """Fail the run (exit code 1) when the latency or error budget is blown."""
    total = environment.stats.total
    p95 = total.get_response_time_percentile(0.95) or 0
    if total.fail_ratio > MAX_FAILURE_RATIO or p95 > P95_LIMIT_MS:
        environment.process_exit_code = 1
'''

NOTES_V7_TESTS_SLOW_APP_PY = r'''
%%writefile ../projects/notes_api/tests/slow_app.py
"""The Notes API plus one slow route, for the graceful-shutdown test (never deployed)."""

import asyncio

from notes_api.main import create_app

app = create_app()


@app.get("/test/slow")
async def slow(seconds: float = 1.0) -> dict[str, float]:
    """A request that is still running when the server is told to stop."""
    await asyncio.sleep(seconds)
    return {"slept": seconds}
'''

NOTES_V7_TESTS_TEST_SHUTDOWN_PY = r'''
%%writefile ../projects/notes_api/tests/test_shutdown.py
"""Graceful shutdown: on SIGTERM Uvicorn stops accepting, finishes requests in flight, exits.

Orchestrators (Compose, Kubernetes, ECS) stop a container with SIGTERM, wait a grace period,
then SIGKILL. A rolling deploy only loses no requests if the process uses that grace period.
"""

import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

TESTS_DIR = Path(__file__).resolve().parent
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")


def free_port() -> int:
    """A TCP port nobody listens on right now."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def wait_until_live(base_url: str, process: subprocess.Popen[bytes]) -> None:
    """Poll /health/live until the server answers (or fail with its output)."""
    for _ in range(100):
        if process.poll() is not None:
            pytest.fail(
                f"server exited: {process.stdout.read().decode() if process.stdout else ''}"
            )
        try:
            if httpx.get(f"{base_url}/health/live", timeout=0.5).status_code == 200:
                return
        except httpx.TransportError:
            time.sleep(0.1)
    pytest.fail("server did not start")


def start_slow_server(database_path: Path) -> tuple[subprocess.Popen[bytes], str]:
    """Start Uvicorn with slow_app on a free port; return the process and its base URL."""
    port = free_port()
    env = {
        **os.environ,
        "NOTES_ENVIRONMENT": "test",
        "NOTES_DATABASE_URL": f"sqlite+aiosqlite:///{database_path}",
        "NOTES_LOG_JSON": "false",
        "NOTES_CHECK_MIGRATIONS": "false",
    }
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "slow_app:app",
        "--app-dir",
        str(TESTS_DIR),
        "--port",
        str(port),
        "--timeout-graceful-shutdown",
        "10",
        "--log-level",
        "warning",
    ]
    server = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return server, f"http://127.0.0.1:{port}"


def test_sigterm_lets_requests_in_flight_finish(tmp_path: Path) -> None:
    """A 1.5 s request started before SIGTERM still gets its 200; then the process exits.

    After a clean shutdown Uvicorn re-raises the signal it caught, so the exit status is
    "terminated by SIGTERM" (-15), the conventional result; 0 is accepted too.
    """
    server, base_url = start_slow_server(tmp_path / "shutdown.db")
    try:
        wait_until_live(base_url, server)
        results: dict[str, httpx.Response] = {}
        request = threading.Thread(
            target=lambda: results.update(
                slow=httpx.get(f"{base_url}/test/slow?seconds=1.5", timeout=10)
            )
        )
        request.start()
        time.sleep(0.4)  # the request is now in flight
        server.send_signal(signal.SIGTERM)
        request.join(timeout=10)
        exit_status = server.wait(timeout=10)
    finally:
        if server.poll() is None:
            server.kill()
    assert results["slow"].status_code == 200
    assert results["slow"].json() == {"slept": 1.5}
    assert exit_status in (0, -signal.SIGTERM)
    with pytest.raises(httpx.ConnectError):  # nothing listens any more
        httpx.get(f"{base_url}/health/live", timeout=1)
'''

NOTES_V7_TESTS_TEST_DEPLOY_PY = r'''
%%writefile ../projects/notes_api/tests/test_deploy.py
"""Deployment files and settings: checked statically, since CI has no cluster to deploy to."""

import re
from pathlib import Path
from typing import Any

import fakeredis
import pytest
import yaml
from pydantic import SecretStr

from helpers import PROJECT_DIR
from notes_api import db, worker
from notes_api.core.config import Settings

pytestmark = pytest.mark.anyio


def load_yaml(relative: str) -> list[dict[str, Any]]:
    """Every document of a YAML file in the project."""
    return list(yaml.safe_load_all((PROJECT_DIR / relative).read_text(encoding="utf-8")))


def test_dockerfile_is_multi_stage_and_unprivileged() -> None:
    """Build and runtime stages; the final user is not root; a health check is declared."""
    dockerfile = (PROJECT_DIR / "Dockerfile").read_text(encoding="utf-8")
    assert len(re.findall(r"^FROM ", dockerfile, re.M)) >= 3
    assert re.findall(r"^USER (\S+)", dockerfile, re.M)[-1] not in ("root", "0")
    assert "HEALTHCHECK" in dockerfile and "--no-dev" in dockerfile


def test_compose_stack_order_and_health() -> None:
    """Migrations run before api/worker; backing services and the worker have health checks."""
    services = load_yaml("compose.yaml")[0]["services"]
    assert set(services) == {"db", "redis", "migrate", "api", "worker", "proxy"}
    for name in ("api", "worker"):
        depends = services[name]["depends_on"]
        assert depends["migrate"]["condition"] == "service_completed_successfully"
    for name in ("db", "redis", "worker", "proxy"):
        assert "healthcheck" in services[name]
    assert "ports" not in services["api"]  # only the proxy is published
    assert services["api"]["read_only"] is True and services["api"]["cap_drop"] == ["ALL"]


def test_compose_secret_comes_from_an_ignored_file() -> None:
    """The JWT secret is a file under .secrets/, which git ignores."""
    secrets = load_yaml("compose.yaml")[0]["secrets"]
    assert secrets["notes_jwt_secret"]["file"].startswith("./.secrets/")


def test_kubernetes_api_probes_and_rollout() -> None:
    """Three probes, no unavailable pods during a rollout, enough time to shut down."""
    deployment = load_yaml("deploy/k8s/api-deployment.yaml")[0]
    spec = deployment["spec"]["template"]["spec"]
    container = spec["containers"][0]
    probes = {key for key in container if key.endswith("Probe")}
    assert probes == {"startupProbe", "readinessProbe", "livenessProbe"}
    assert container["readinessProbe"]["httpGet"]["path"] == "/health/ready"
    assert deployment["spec"]["strategy"]["rollingUpdate"]["maxUnavailable"] == 0
    assert spec["terminationGracePeriodSeconds"] > 20 and spec["securityContext"]["runAsNonRoot"]
    kinds = [doc["kind"] for doc in load_yaml("deploy/k8s/api-service.yaml")]
    assert kinds == ["Service", "HorizontalPodAutoscaler"]


def test_proxy_blocks_metrics_and_procfile_has_three_processes() -> None:
    """Caddy hides /metrics; the PaaS Procfile declares web, worker and release."""
    caddyfile = (PROJECT_DIR / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    assert "respond @internal 404" in caddyfile and "reverse_proxy" in caddyfile
    procfile = (PROJECT_DIR / "Procfile").read_text(encoding="utf-8").splitlines()
    assert [line.split(":")[0] for line in procfile] == ["web", "worker", "release"]


def test_secrets_are_read_from_files(tmp_path: Path) -> None:
    """Docker/Kubernetes secret files fill settings (a file per variable, name case-insensitive)."""
    (tmp_path / "notes_jwt_secret").write_text("from-a-secret-file-" + "x" * 20, encoding="utf-8")
    settings = Settings(_env_file=None, _secrets_dir=tmp_path)
    assert settings.jwt_secret is not None
    assert settings.jwt_secret.get_secret_value().startswith("from-a-secret-file-")


def test_redis_password_file_goes_into_the_url(tmp_path: Path) -> None:
    """notes_redis_password (a secret file) completes NOTES_REDIS_URL; a URL with one wins."""
    (tmp_path / "notes_redis_password").write_text("s3cret/+", encoding="utf-8")
    url = SecretStr("redis://redis:6379/0")
    settings = Settings(_env_file=None, _secrets_dir=tmp_path, redis_url=url)
    assert settings.redis_url.get_secret_value() == "redis://:s3cret%2F%2B@redis:6379/0"
    explicit = SecretStr("redis://:other@redis:6379/0")
    settings = Settings(_env_file=None, _secrets_dir=tmp_path, redis_url=explicit)
    assert settings.redis_url.get_secret_value() == "redis://:other@redis:6379/0"


def test_pgbouncer_mode_disables_statement_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Behind PgBouncer in transaction mode, asyncpg must not cache prepared statements."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(db, "create_async_engine", lambda url, **kwargs: captured.update(kwargs))
    url = SecretStr("postgresql+asyncpg://notes:notes@pgbouncer:6432/notes")
    db.create_engine_from_settings(
        Settings(_env_file=None, database_url=url, database_pgbouncer=True)
    )
    assert captured["connect_args"]["statement_cache_size"] == 0
    assert captured["connect_args"]["prepared_statement_cache_size"] == 0


async def test_worker_health_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """--check passes while a worker keeps its health key fresh, fails when it is gone."""
    fake = fakeredis.FakeAsyncRedis()
    monkeypatch.setattr(worker.redis_asyncio, "from_url", lambda *_args, **_kwargs: fake)
    monkeypatch.setattr(fake, "aclose", lambda: _noop())
    settings = Settings(_env_file=None)
    assert await worker.worker_is_healthy(settings) is False
    await fake.set(worker.HEALTH_CHECK_KEY, "j_complete=3", px=31_000)
    assert await worker.worker_is_healthy(settings) is True


async def _noop() -> None:
    """Keep the fake client open between the two checks."""
'''
