"""Phase 6 Project — Notes API in Production (notebook section).

The production files are real files in ``scripts/phase6/project_files/`` (so shellcheck,
actionlint and ruff can check them on their own); this module turns each one into explained
``%%writefile`` cells at build time. Running the section writes them into
``projects/notes_api/`` and ``.github/workflows/``, ships release 1.0.0 (with a worker fix the
rehearsal found), rehearses the production stack on this machine (zero-downtime rollouts,
rollback, backups, monitoring, a Locust run that fills LOAD_TEST.md) and ends with 20
predict-the-output questions covering Phase 6. DEPLOY.md and LOAD_TEST.md are committed
documents; the notebook reads DEPLOY.md and fills LOAD_TEST.md's local results.
"""

from pathlib import Path

from helpers_module import setup_cells
from nbformat import NotebookNode
from unit_6_8 import UNIT_FOLDERS, UNIT_SETUP_SOURCE

from nb_builder import code, md, predict_cells, writefile_cells

PROJECT_FILES = Path(__file__).resolve().parent / "project_files"
# Unit 6.8's setup, minus the imports nothing in the project uses (ruff would flag them: the
# project's re-import shadows the earlier one). Each line must exist in Unit 6.8's source.
UNUSED_SETUP_IMPORTS = {
    "import asyncio": "",
    "import csv": "",
    "import dataclasses": "",
    "import graphlib": "",
    "import hashlib": "",
    "import inspect": "",
    "import io": "",
    "import itertools": "",
    "import math": "",
    "import random": "",
    "import signal": "",
    "import sqlite3": "",
    "import textwrap": "",
    "import redis as redis_sync": "",
    "from pydantic import SecretStr": "",
    "from pydantic_settings import BaseSettings, SettingsConfigDict": "",
    "from collections.abc import AsyncIterator, Callable, Iterable, Iterator": (
        "from collections.abc import Callable, Iterable, Iterator"
    ),
    "from fastapi import FastAPI, Request, Response": "from fastapi import FastAPI",
}


def project_unit_setup_source() -> str:
    """Unit 6.8's setup cell with the unused imports removed."""
    lines = UNIT_SETUP_SOURCE.split("\n")
    missing = set(UNUSED_SETUP_IMPORTS) - set(lines)
    if missing:
        raise ValueError(f"Unit 6.8's setup changed; not found: {sorted(missing)}")
    kept = [UNUSED_SETUP_IMPORTS.get(line, line) for line in lines]
    return "\n".join(
        line for line, original in zip(kept, lines, strict=True) if line or not original
    )


NOTES_TARGET = "../projects/notes_api"
WORKFLOWS_TARGET = "../.github/workflows"


def file_cells(source: str, target: str, parts: list[tuple[str, str]]) -> list[NotebookNode]:
    """Explained %%writefile cells for one file of project_files/ (target relative to notebooks/)."""
    text = (PROJECT_FILES / source).read_text()
    return writefile_cells(f"%%writefile {target}\n{text}", parts)


def notes_file_cells(relative: str, parts: list[tuple[str, str]]) -> list[NotebookNode]:
    """file_cells for a file of the Notes API project."""
    return file_cells(f"notes_api/{relative}", f"{NOTES_TARGET}/{relative}", parts)


PROJECT_SETUP_SOURCE = r'''
import difflib

from IPython.display import Markdown, display

PRODUCTION_DIR = NOTES_API_DIR / "deploy" / "production"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
for folder in (PRODUCTION_DIR / "grafana", NOTES_API_DIR / "load", NOTES_API_DIR / "tests"):
    folder.mkdir(parents=True, exist_ok=True)  # %%writefile does not create folders


def run_tool(
    image: str,
    *arguments: str,
    mount: Path,
    mount_at: str = "/work",
    entrypoint: str | None = None,
    environment: dict[str, str] | None = None,
) -> tuple[int, str]:
    """Run a checker from its pinned Docker image, `mount` read-only at `mount_at`."""
    command = ["docker", "run", "--rm", "-v", f"{mount}:{mount_at}:ro", "-w", mount_at]
    command += [f"--env={key}={value}" for key, value in (environment or {}).items()]
    if entrypoint:
        command += ["--entrypoint", entrypoint]
    run = subprocess.run([*command, image, *arguments], capture_output=True, text=True, timeout=300)
    return run.returncode, (run.stdout + run.stderr).strip()


print(f"{HAS_DOCKER=}  {HAS_UV=}")
print("production files go to", PRODUCTION_DIR.relative_to(REPO_ROOT))
'''


def _overview_cells() -> list[NotebookNode]:
    """Project opener: goal, requirements, decisions, setup."""
    return [
        md(
            """
            ## Phase 6 Project — Notes API in Production

            **Goal:** the Notes API built across Units 6.2–6.8, deployed to a real host with
            HTTPS, CI/CD, migrations, monitoring and a written load-test report.

            The notebook prepares and rehearses everything that can be done without an account
            or a credit card. The steps that need you (creating the server, the secrets, the
            first push) are in **`projects/notes_api/DEPLOY.md`**, a numbered, copy-pasteable
            runbook.

            **Requirements and where each one is met**

            | # | Requirement (from the project brief) | Where | Evidence in this notebook |
            | --- | --- | --- | --- |
            | R1 | the Notes API of Units 6.2–6.8 | Step 2: release 1.0.0 | the image CI builds is the image that runs |
            | R2 | deployed to a real host | Steps 3, 6, `DEPLOY.md` | a production Compose override, server bootstrap, deploy scripts |
            | R3 | HTTPS | Step 4 | Caddy + Let's Encrypt; the rehearsal checks the redirect, HSTS and the certificate |
            | R4 | CI/CD | Step 8 | deploy job after lint, types, tests, build and scan, on `main` only; smoke test with automatic rollback |
            | R5 | migrations | Steps 6–7 | a one-off migration container on every deploy, after a backup, before new code takes traffic |
            | R6 | monitoring | Step 5 | health checks, JSON logs with rotation, Prometheus + alert rules, a Grafana dashboard, an uptime workflow |
            | R7 | a written load-test report | Steps 9 and 11, `LOAD_TEST.md` | a Locust run against the rehearsal stack fills the report's local section |

            **Decisions**

            | Question | Choice | Why |
            | --- | --- | --- |
            | Host | a small **Hetzner Cloud** server (2 vCPU, 4 GB) with Docker Compose | reuses the Unit 6.8 stack (Compose, Caddy); cheapest; every operational step is visible in the repository instead of hidden in a platform |
            | Deploy trigger | **every push to `main`**, after all checks pass | continuous deployment; the `production` environment can add a manual approval |
            | Hostname | a free **sslip.io** name (`203-0-113-10.sslip.io`) | resolves to the IP written in it; no account; Let's Encrypt issues certificates for it |
            | Monitoring | **Prometheus + Grafana on the server**, reached through an SSH tunnel; a scheduled **GitHub Actions** uptime check | no extra accounts; GitHub e-mails you when the check fails |

            **If you have deployed Node apps before**

            | Node world | This project | The difference that bites |
            | --- | --- | --- |
            | PM2 cluster on a VPS | Uvicorn worker processes in containers, two replicas | the database pool is per process: replicas × processes × pool must fit |
            | Heroku release phase (`prisma migrate deploy`) | `rollout.sh` runs `alembic upgrade head` in a one-off container | old code keeps serving during the migration: expand/contract |
            | Nginx + certbot cron | Caddy's automatic HTTPS | port 80 must stay open for the HTTP challenge and the redirect |
            | `pm2 reload` (zero-downtime) | start new replicas, pin the proxy to them, stop the old ones | the proxy must stop sending requests *before* SIGTERM |
            | an uptime SaaS | a scheduled GitHub Actions job | scheduled runs can start late and pause after 60 inactive days |

            **Deployment status:** prepared and rehearsed here; *waiting for the user steps* in
            `DEPLOY.md`. After the first deploy, the live load test fills the second results
            section of `LOAD_TEST.md`.

            Run the setup cells first. Part 1: the imports (Unit 6.8's, minus the ones the
            project does not use):
            """
        ),
        *setup_cells(
            "project",
            project_unit_setup_source(),
            """
            Part 2: every helper of Units 6.1–6.8 from [`phase6_helpers.py`](phase6_helpers.py):
            servers, the Notes API, databases, Redis, workers, PostgreSQL and Docker (everything
            that needs Docker prints a skip message without it):
            """,
            folders=UNIT_FOLDERS,
        ),
        md(
            """
            Part 3: the project's own setup: the folders the `%%writefile` cells need, and
            `run_tool()`, which runs a checker (Caddy, promtool, shellcheck, actionlint) from its
            pinned Docker image so nothing has to be installed on this machine:
            """
        ),
        code(PROJECT_SETUP_SOURCE),
    ]


ARCHITECTURE_MERMAID = """
```mermaid
flowchart LR
    client([Browser or API client]) -- "HTTPS :443 (HTTP :80 redirects)" --> caddy
    subgraph server["Hetzner Cloud server: Ubuntu, Docker Compose, /srv/notes"]
        caddy["proxy: Caddy 2.10<br/>TLS, HSTS, load balancing"]
        api1["api replica 1<br/>Uvicorn x 2 processes"]
        api2["api replica 2<br/>Uvicorn x 2 processes"]
        worker["worker: ARQ"]
        db[("db: PostgreSQL 18")]
        redis[("redis: Redis 7.4")]
        prom["prometheus"]
        graf["grafana"]
        caddy --> api1 & api2
        api1 & api2 --> db & redis
        worker --> db & redis
        prom -- "scrape /metrics" --> api1 & api2
        graf --> prom
    end
    gha["GitHub Actions"] -- "docker push" --> ghcr[("GHCR")]
    gha -- "SSH: rsync, rollout.sh" --> server
    ghcr -- "docker pull" --> server
    uptime["uptime workflow, every 15 min"] -- "HTTPS" --> caddy
    you([You]) -- "SSH tunnel :3000 :9090" --> graf
```
"""

ARCHITECTURE_ASCII = """
<details><summary>ASCII version</summary>

```text
  browser / API client --+   HTTPS :443 (HTTP :80 answers 308 to HTTPS)
  uptime workflow -------+
                         v
+- Hetzner Cloud server (Docker Compose, /srv/notes) ------------------------------+
| proxy: Caddy (TLS, HSTS, load balancing)                                         |
|      |                  |                                                        |
|      v                  v                                                        |
| api replica 1      api replica 2       worker (ARQ)                              |
| (Uvicorn x 2)      (Uvicorn x 2)            |                                    |
|      |                  |                   |                                    |
|      v                  v                   v                                    |
| db: PostgreSQL 18 and redis: Redis 7.4 (used by the api replicas and the worker) |
|                                                                                  |
| prometheus: scrapes /metrics of every api replica, inside the network            |
| grafana: reads prometheus; both on 127.0.0.1 only (SSH tunnel)                   |
+----------------------------------------------------------------------------------+
      ^ docker pull                         ^ SSH: rsync + rollout.sh <sha>
  GHCR (images) <-- docker push -- GitHub Actions: lint, types, test, build, scan, push, deploy
```

</details>
"""


def _architecture_cells() -> list[NotebookNode]:
    """Step 1: the production architecture."""
    return [
        md(
            """
            ### Step 1 — The production architecture

            One server runs the whole stack with Docker Compose. Only Caddy is reachable from
            the internet; everything else talks over Compose's private network. Images are
            built once by CI, pushed to the GitHub Container Registry (GHCR), and pulled by the
            server, so the code that passed the tests is byte for byte the code that runs.
            """
        ),
        md(ARCHITECTURE_MERMAID + ARCHITECTURE_ASCII),
        md(
            """
            **The services**

            | Service | Image | Reachable from | State | Health check |
            | --- | --- | --- | --- | --- |
            | `proxy` | `caddy:2.10` | the internet: 80/tcp, 443/tcp, 443/udp | certificates (`caddy-data` volume) | Caddy's admin endpoint |
            | `api` × 2 | `ghcr.io/<owner>/notes-api:<commit sha>` | the proxy and Prometheus | none (stateless) | `/health/live` (Dockerfile) |
            | `worker` | the same image | — (it only connects out) | none | `python -m notes_api.worker --check` |
            | `migrate` | the same image | — | runs `alembic upgrade head`, exits | exit code 0 |
            | `db` | `postgres:18-alpine` | the private network only | `notes-db` volume | `pg_isready` |
            | `redis` | `redis:7.4` | the private network only | `redis-data` volume (append-only file) | `redis-cli ping` |
            | `prometheus` | `prom/prometheus:v3.5.0` | 127.0.0.1:9090 (SSH tunnel) | 15 days of metrics | `/-/ready` |
            | `grafana` | `grafana/grafana-oss:12.1.0` | 127.0.0.1:3000 (SSH tunnel) | `grafana-data` volume | `/api/health` |

            **A request's path:** the client resolves `203-0-113-10.sslip.io` to the server,
            Caddy terminates TLS, picks an API replica (round robin), and forwards the request
            with `X-Forwarded-*` headers; Uvicorn trusts them (`FORWARDED_ALLOW_IPS`), so the
            app sees the client's address and `https`. The response goes back the same way;
            Caddy adds HSTS and compresses it.

            **Sizing.** 2 replicas × 2 Uvicorn processes = 4 event loops on 2 vCPUs. Each
            process keeps up to 5 + 5 database connections, so normal operation needs 40, a
            rollout (old and new replicas side by side) 80, plus the worker's 10: PostgreSQL is
            started with `max_connections=150`. Unit 6.8's defaults (5 + 10 per process) would
            have needed 120 during a rollout, above PostgreSQL's default of 100 (Question 20).
            """
        ),
    ]


WORKER_PATCH_SOURCE = r'''
WORKER_PATH = NOTES_SRC / "notes_api" / "worker.py"
STOPPED_NEVER = """    try:
        await worker.main()
    finally:
        await worker.close()
"""
STOPPED_ON_SIGTERM = """    try:
        await worker.async_run()  # sets worker.main_task: the task arq's SIGTERM handler cancels
    except asyncio.CancelledError:
        current_task = asyncio.current_task()
        if current_task is not None and current_task.cancelling():
            raise  # run_worker itself was cancelled (not a signal): let that propagate
    finally:
        await worker.close()
"""
worker_source = WORKER_PATH.read_text()
if STOPPED_NEVER in worker_source:
    WORKER_PATH.write_text(worker_source.replace(STOPPED_NEVER, STOPPED_ON_SIGTERM))
patch = difflib.unified_diff(
    worker_source.splitlines(keepends=True),
    WORKER_PATH.read_text().splitlines(keepends=True),
    "worker.py (v7)",
    "worker.py (1.0.0)",
    n=1,
)
print("".join(patch) or "worker.py is already patched")
'''


def _release_cells() -> list[NotebookNode]:
    """Step 2: version 1.0.0 and the worker fix."""
    return [
        md(
            """
            ### Step 2 — Release 1.0.0, and a bug the rehearsal found

            The production release is **1.0.0**: the same code as v7 plus one fix. Version
            numbers live in `pyproject.toml` (packaging) and `notes_api.__version__` (shown in
            the OpenAPI document):
            """
        ),
        code(
            r"""
            for relative, version_line in (
                ("pyproject.toml", 'version = "{}"'),
                ("src/notes_api/__init__.py", '__version__ = "{}"'),
            ):
                path = NOTES_API_DIR / relative
                text = path.read_text()
                path.write_text(text.replace(version_line.format("0.7.0"), version_line.format("1.0.0")))
                print(f"{relative}: {version_line.format('1.0.0')}")
            if HAS_UV:
                print(lock_summary(run_in_notes("uv", "lock").stderr))
            """
        ),
        md(
            """
            **The bug.** An earlier rehearsal of the deploy (Step 11 below) timed each step,
            and replacing the worker took about 38 seconds. Its container exited with code
            **137** (killed by SIGKILL), and its log said *shutdown on SIGTERM* — and then the
            worker went on processing cron jobs. What happened:

            1. `docker stop` sends SIGTERM to the container's PID 1, the worker's Python
               process, and waits `stop_grace_period` (30 s) before sending SIGKILL.
            2. arq installs a SIGTERM handler. The handler logs the message and cancels
               `worker.main_task`, the task it expects to be running the worker.
            3. `run_worker()` (written in Unit 6.6 because arq 0.25's CLI fails on Python 3.14+)
               awaits `worker.main()` directly, so `main_task` is `None` and nothing is
               cancelled. The worker keeps running until the SIGKILL, which can interrupt a job
               halfway (arq retries it later, but a webhook could be sent twice).

            The fix is `worker.async_run()`, which creates `main_task` before awaiting it. The
            `CancelledError` that the signal then causes is the normal way out; only a
            cancellation of `run_worker` *itself* (`Task.cancelling()`, *new in 3.11*) is
            re-raised. A regression test (`test_worker_stops_cleanly_on_sigterm`, Step 10) starts
            the real worker, sends SIGTERM and expects exit code 0 within 10 s; it times out on
            the v7 code.

            > **Note:** the API never had this problem: Uvicorn installs its own SIGTERM
            > handler and shuts down gracefully. PID 1 in a container ignores signals it has no
            > handler for, so any long-running Python process you containerize needs one.

            The patch (the cell is safe to re-run):
            """
        ),
        code(WORKER_PATCH_SOURCE),
        md(
            """
            The OpenAPI snapshot test records `info.version`, so it must be re-recorded for
            1.0.0 (the test fails until the change is recorded, which is the point):
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
            snapshot = json.loads((NOTES_API_DIR / "tests" / "snapshots" / "openapi.json").read_text())
            print("snapshot version:", snapshot["info"]["version"])
            """
        ),
    ]


def _compose_cells() -> list[NotebookNode]:
    """Step 3: the production Compose override."""
    return [
        md(
            """
            ### Step 3 — The production Compose override

            `compose.yaml` (Unit 6.8) describes the stack for a laptop: it builds the image,
            publishes PostgreSQL and Redis on localhost, and serves `localhost` with Caddy's
            internal CA. Production needs different values for the same services, so a second
            file is **merged over it**: `docker compose -f compose.yaml -f compose.prod.yaml`.
            Merge rules worth knowing:

            | Field kind | Merge behaviour | Used here |
            | --- | --- | --- |
            | scalars (`image`, `command`) | the later file wins | `image: ${NOTES_IMAGE}:${TAG}` |
            | mappings (`environment`, `logging`) | merged key by key | the database URL, pool sizes |
            | `volumes` | merged by container path | the production Caddyfile replaces the local one |
            | other sequences (`ports`) | **appended** | `!override` replaces them, `!reset []` empties them (Compose 2.24.4+) |
            | `build` | merged | `!reset null` removes it: production never builds |

            Part by part. The header, a logging anchor every service uses (JSON lines on disk,
            rotated at 5 × 10 MB, so logs can never fill the disk) and the environment shared by
            the three app services. `${VAR:?message}` makes Compose stop with that message when a
            variable is missing, instead of starting with an empty password:
            """
        ),
        *notes_file_cells(
            "compose.prod.yaml",
            [
                ("", ""),
                (
                    "services:",
                    """
                    The backing services: no host ports at all (`!reset []`); PostgreSQL gets a
                    higher connection limit and the production password; Redis keeps an
                    append-only file on a volume, so queued jobs survive a restart:
                    """,
                ),
                (
                    "  migrate:",
                    """
                    The app services run the image CI pushed (`NOTES_IMAGE` and `TAG` come
                    from `state/release.env`, written by `rollout.sh`). The API runs two
                    replicas of two Uvicorn processes each, and gets 30 s to stop gracefully:
                    """,
                ),
                ("  worker:", "The worker, with the same image, environment and grace period:"),
                (
                    "  proxy:",
                    """
                    Caddy is the only public service. `!override` replaces Unit 6.8's
                    `127.0.0.1:8443` mapping instead of adding to it; the production Caddyfile
                    is mounted at the same path as the local one, so it replaces it:
                    """,
                ),
                (
                    "  prometheus:",
                    """
                    Monitoring, bound to the server's localhost only (reach it through an SSH
                    tunnel). Grafana's data source and dashboard are provisioned from files, so
                    a fresh server needs no clicking:
                    """,
                ),
                ("  grafana:", "Grafana, provisioned from files, on 127.0.0.1:3000:"),
                ("volumes:", "The named volumes added by this file:"),
            ],
        )[1:],
        md(
            """
            The template for the server's secrets file, `/srv/notes/.env` (committed; the real
            file never is). Compose reads `.env` for the `${...}` values:
            """
        ),
        *notes_file_cells("deploy/production/env.example", [("", "")])[1:],
        md(
            """
            **What the merge produces.** `docker compose config` resolves both files and prints
            the final model, without starting anything. With example values, every service, its
            image and what it publishes:
            """
        ),
        code(
            r'''
            PRODUCTION_FILES = ["-f", "compose.yaml", "-f", "compose.prod.yaml"]
            EXAMPLE_VALUES = {
                "NOTES_IMAGE": "ghcr.io/example/notes-api",
                "TAG": "3f9a1c2",
                "POSTGRES_PASSWORD": "example-password",
                "NOTES_SITE": "203-0-113-10.sslip.io",
                "ACME_EMAIL": "ops@example.com",
                "GRAFANA_ADMIN_PASSWORD": "example-password",
            }


            def compose_config(values: dict[str, str]) -> subprocess.CompletedProcess[str]:
                """docker compose config for the production files with exactly these values."""
                environment = {name: value for name, value in CHILD_ENV.items() if name not in EXAMPLE_VALUES}
                return subprocess.run(
                    ["docker", "compose", *PRODUCTION_FILES, "config", "--format", "json"],
                    cwd=NOTES_API_DIR,
                    capture_output=True,
                    text=True,
                    env={**environment, **values},
                )


            def published(service: dict[str, Any]) -> str:
                """host:port->container/protocol for every published port."""
                ports = service.get("ports", [])
                return ", ".join(
                    f"{port.get('host_ip') or '*'}:{port['published']}->{port['target']}/{port['protocol']}"
                    for port in ports
                )
            '''
        ),
        md("The merged services, with their images and published ports:"),
        code(
            r"""
            if shutil.which("docker"):
                merged = json.loads(compose_config(EXAMPLE_VALUES).stdout)
                for name, service in sorted(merged["services"].items()):
                    print(f"{name:<11}{service['image']:<38}{published(service) or '-'}")
                api_environment = merged["services"]["api"]["environment"]
                print("api database URL:", api_environment["NOTES_DATABASE_URL"])
            else:
                print("SKIP docker compose config: the Docker CLI is not installed")
            """
        ),
        md(
            """
            Only `proxy` is published on every interface (`*`); Prometheus and Grafana listen
            on 127.0.0.1; PostgreSQL and Redis publish nothing. And a forgotten secret stops
            Compose before anything starts:
            """
        ),
        code(
            r"""
            if shutil.which("docker"):
                incomplete = dict(EXAMPLE_VALUES)
                del incomplete["POSTGRES_PASSWORD"]
                failed = compose_config(incomplete)
                print("exit code:", failed.returncode)
                print(failed.stderr.strip().splitlines()[-1])
            """
        ),
    ]


def _https_cells() -> list[NotebookNode]:
    """Step 4: HTTPS with Caddy and Let's Encrypt."""
    return [
        md(
            """
            ### Step 4 — HTTPS: Caddy and Let's Encrypt

            Caddy turns on HTTPS by itself for any site address that is a public hostname:

            | When | What happens |
            | --- | --- |
            | first start | Caddy creates an ACME account (with `ACME_EMAIL`) and asks Let's Encrypt for a certificate for `NOTES_SITE` |
            | the challenge | Let's Encrypt connects to the hostname on port **80** (HTTP-01: fetch a token) or **443** (TLS-ALPN-01) to prove you control it. Both ports must be open in the firewall |
            | stored | certificate and key go into the `caddy-data` volume: keep the volume, or every restart asks again and runs into rate limits |
            | renewal | about 30 days before the 90-day certificate expires, in the background; no cron job |
            | if Let's Encrypt fails | Caddy retries with backoff and falls back to ZeroSSL |
            | plain HTTP | answered with `308 Permanent Redirect` to `https://` (except the challenge path) |

            **sslip.io** answers DNS queries for `<a>-<b>-<c>-<d>.sslip.io` with the address
            `a.b.c.d`, so the hostname exists the moment the server has an IP, with no account.
            A domain you own works the same way: point an `A` record at the server and put
            the name in `NOTES_SITE`.

            **HSTS** (`Strict-Transport-Security: max-age=31536000`) tells browsers to use HTTPS
            for this host for a year, even if a link says `http://`. It is deliberately without
            `includeSubDomains` and `preload`: `sslip.io` is a shared domain.

            The production Caddyfile. Part 1: the global options and the two ways of finding
            the API replicas: normally `dynamic a api 8000` (every running `api` container,
            from Docker's DNS, re-resolved every second); during a rollout a fixed list, chosen
            by `rollout.sh` through two environment variables (Step 7 explains why):
            """
        ),
        *notes_file_cells(
            "deploy/production/Caddyfile",
            [
                ("", ""),
                (
                    "{$NOTES_SITE} {",
                    """
                    Part 2: the site. Security headers, `/metrics` hidden from the internet
                    (Prometheus scrapes the replicas directly), retries for refused
                    connections, and JSON access logs on stdout:
                    """,
                ),
            ],
        )[1:],
        md(
            """
            **Validate it** with the same Caddy image the server runs: once with the defaults,
            once in the pinned mode `rollout.sh` uses. `caddy adapt` shows the JSON Caddy
            actually runs; the `upstreams` part is what changes:
            """
        ),
        code(
            r'''
            CADDY_SCRIPT = (
                "caddy adapt --config /work/Caddyfile 2>/dev/null; echo; "
                "caddy validate --config /work/Caddyfile 2>&1 | tail -n 1"
            )
            UPSTREAMS = re.compile(r'"(dynamic_upstreams|upstreams)":(\{[^}]*\}|\[[^\]]*\])')


            def caddy_check(**environment: str) -> tuple[str, str]:
                """(the reverse proxy's upstream config, caddy validate's verdict)."""
                variables = {"NOTES_SITE": "notes.example.com", "ACME_EMAIL": "ops@example.com"}
                _, output = run_tool(
                    "caddy:2.10",
                    "sh",
                    "-c",
                    CADDY_SCRIPT,
                    mount=PRODUCTION_DIR,
                    environment={**variables, **environment},
                )
                adapted, verdict = output.rsplit("\n", 1)
                upstreams = UPSTREAMS.search(adapted)
                return upstreams[0] if upstreams else "?", verdict


            if HAS_DOCKER:
                print("default:", *caddy_check())
                pinned = caddy_check(
                    NOTES_UPSTREAM_MODE="static", NOTES_UPSTREAMS="notes-api-3:8000 notes-api-4:8000"
                )
                print("pinned: ", *pinned)
            else:
                print("SKIP caddy validate: Docker is not available")
            '''
        ),
    ]


DASHBOARD_SOURCE = r"""
RATIO = "sum(rate({metric}{{{selector}}}[5m])) / clamp_min(sum(rate({metric}[5m])), 1e-9)"
LATENCY = (
    "histogram_quantile({quantile}, "
    "sum by (le) (rate(notes_http_request_duration_seconds_bucket[5m])))"
)
DASHBOARD_PANELS = [  # (title, unit, [(PromQL, legend), ...])
    (
        "Requests per second by route",
        "reqps",
        [("sum by (route) (rate(notes_http_requests_total[1m]))", "{{route}}")],
    ),
    (
        "5xx error ratio (alert above 1%)",
        "percentunit",
        [(RATIO.format(metric="notes_http_requests_total", selector='status=~"5.."'), "5xx")],
    ),
    (
        "Latency percentiles (alert: p95 above 200 ms)",
        "s",
        [(LATENCY.format(quantile=level), f"p{round(level * 100)}") for level in (0.5, 0.95, 0.99)],
    ),
    ("Requests in progress", "short", [("sum(notes_http_requests_in_progress)", "in progress")]),
    ("API replicas answering scrapes", "short", [('count(up{job="notes-api"} == 1)', "up")]),
    (
        "Note writes per second",
        "ops",
        [("sum by (operation) (rate(notes_writes_total[5m]))", "{{operation}}")],
    ),
    (
        "Cache hit ratio",
        "percentunit",
        [(RATIO.format(metric="notes_cache_lookups_total", selector='result="hit"'), "hits")],
    ),
]
PROMETHEUS_SOURCE = {"type": "prometheus", "uid": "prometheus"}  # the provisioned data source
"""

DASHBOARD_WRITE_SOURCE = r'''
def timeseries_panel(
    number: int, title: str, unit: str, queries: list[tuple[str, str]]
) -> dict[str, Any]:
    """One Grafana time-series panel; two per row."""
    return {
        "id": number + 1,
        "type": "timeseries",
        "title": title,
        "datasource": PROMETHEUS_SOURCE,
        "gridPos": {"h": 8, "w": 12, "x": 12 * (number % 2), "y": 8 * (number // 2)},
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
        "targets": [
            {
                "refId": chr(ord("A") + index),
                "datasource": PROMETHEUS_SOURCE,
                "expr": expr,
                "legendFormat": legend,
            }
            for index, (expr, legend) in enumerate(queries)
        ],
    }


dashboard = {
    "uid": "notes-api",
    "title": "Notes API",
    "tags": ["notes-api"],
    "timezone": "utc",
    "schemaVersion": 39,
    "version": 1,
    "refresh": "30s",
    "time": {"from": "now-1h", "to": "now"},
    "panels": [timeseries_panel(number, *panel) for number, panel in enumerate(DASHBOARD_PANELS)],
}
DASHBOARD_PATH = PRODUCTION_DIR / "grafana" / "notes-api.json"
DASHBOARD_PATH.write_text(json.dumps(dashboard, indent=2) + "\n")
print(f"{DASHBOARD_PATH.name}: {len(dashboard['panels'])} panels")
print(*[f"  {panel['title']}" for panel in dashboard["panels"]], sep="\n")
'''


def _monitoring_cells() -> list[NotebookNode]:
    """Step 5: health checks, logs, metrics, alerts."""
    return [
        md(
            """
            ### Step 5 — Monitoring: health checks, logs, metrics, alerts

            Four layers, each answering a different question:

            | Layer | Question | Mechanism |
            | --- | --- | --- |
            | **Health checks** | is each process alive and ready? | Docker health checks (`/health/live`, the worker's `--check`); `rollout.sh` waits for *healthy* before switching traffic; CI's smoke test (`/health/ready`, `/health/startup`) after every deploy |
            | **Uptime** | can a user reach it, with a valid certificate? | the `notes-api-uptime` workflow, from outside, every 15 minutes; GitHub e-mails you when it fails (Step 8) |
            | **Logs** | what happened to *this* request? | structlog JSON lines (with `request_id`) and Caddy's JSON access log on stdout; Docker's `json-file` driver rotates them; read with `dc logs … \\| jq` |
            | **Metrics + alerts** | how is it behaving overall, and is it getting worse? | Prometheus scrapes RED metrics (rate, errors, duration) from every replica; three alert rules; a Grafana dashboard |

            **Prometheus.** It discovers the replicas the same way Caddy does, through Docker's
            DNS: during a rollout replicas come and go, and a fixed target list would be wrong
            within seconds. Each replica runs two Uvicorn processes; the app's multiprocess mode
            (Unit 6.7) sums them in one `/metrics` response:
            """
        ),
        *notes_file_cells("deploy/production/prometheus.yml", [("", "")])[1:],
        md(
            """
            **Alert rules**: every replica down for 2 minutes; more than 1% of requests failing
            for 5 minutes; p95 latency above 200 ms for 10 minutes. The thresholds match the
            load-test targets, so the load test and the alerts agree about what "healthy"
            means. (`for:` avoids alerting on a single slow scrape.)
            """
        ),
        *notes_file_cells("deploy/production/alerts.yml", [("", "")])[1:],
        md(
            """
            Without Alertmanager, a firing alert is visible in Prometheus and Grafana but sends
            no message; the uptime workflow is the alarm that reaches you, and these rules are
            what you look at when it fires. **Check both files** with `promtool`, from the image
            the server runs:
            """
        ),
        code(
            r"""
            if HAS_DOCKER:
                for arguments in (
                    ("check", "config", "prometheus.yml"),
                    ("check", "rules", "alerts.yml"),
                ):
                    exit_code, output = run_tool(
                        "prom/prometheus:v3.5.0",
                        *arguments,
                        mount=PRODUCTION_DIR,
                        mount_at="/etc/prometheus",  # where prometheus.yml expects alerts.yml
                        entrypoint="promtool",
                    )
                    print(f"promtool {' '.join(arguments[:2])}: exit {exit_code}")
                    print(*[f"  {line.strip()}" for line in output.splitlines() if line.strip()], sep="\n")
            else:
                print("SKIP promtool: Docker is not available")
            """
        ),
        md(
            """
            **Grafana** is provisioned from files at start-up: a Prometheus data source with a
            fixed `uid` (so the dashboard can refer to it), and a dashboard provider that loads
            every JSON file in `/etc/grafana/dashboards`:
            """
        ),
        *notes_file_cells("deploy/production/grafana/datasources.yml", [("", "")])[1:],
        md("The dashboard provider:"),
        *notes_file_cells("deploy/production/grafana/dashboards.yml", [("", "")])[1:],
        md(
            """
            **The dashboard** is JSON that nobody should write by hand, so Python generates it:
            one time-series panel per question you will ask during an incident. First the
            panels, as PromQL queries with legends (`{{route}}` is replaced by each series'
            label):
            """
        ),
        code(DASHBOARD_SOURCE),
        md("Then the JSON model, two panels per row, written next to the provisioning files:"),
        code(DASHBOARD_WRITE_SOURCE),
    ]


def _server_cells() -> list[NotebookNode]:
    """Step 6: bootstrap, deploy scripts, backups."""
    return [
        md(
            """
            ### Step 6 — The server: bootstrap, deploy scripts and backups

            Four shell scripts and a helper library run on the server. Shell, because the
            server needs nothing but Docker and bash, and every line maps to a command you
            could type yourself.

            **`bootstrap.sh`** runs once, as root, on a fresh Ubuntu server (`DEPLOY.md`,
            step 7). Part 1: arguments and checks:
            """
        ),
        *notes_file_cells(
            "deploy/production/bootstrap.sh",
            [
                ("", ""),
                (
                    'echo "== packages and automatic security updates"',
                    """
                    Part 2: security updates every day (`unattended-upgrades`), and Docker
                    Engine with the Compose plugin from Docker's own apt repository (Ubuntu's
                    package may be too old for `!reset`):
                    """,
                ),
                (
                    'echo "== the deploy user',
                    """
                    Part 3: the `deploy` user. Its `authorized_keys` holds your key (copied
                    from root's) and the CI key. Membership of the `docker` group is
                    root-equivalent, so both keys must be kept safe; `/srv/notes/.secrets` and
                    `state/` are readable by `deploy` only:
                    """,
                ),
                (
                    'echo "== 2 GB swap',
                    """
                    Part 4: swap as a safety margin while old and new replicas overlap,
                    key-only SSH, and the nightly database backup:
                    """,
                ),
            ],
        )[1:],
        md(
            """
            **`lib.sh`** is sourced by the other scripts: it moves to the project folder, finds
            the state folder (`state/`: `release.env`, `history.log`, `backups/`; the rehearsal
            points `NOTES_STATE_DIR` somewhere else), and builds the compose command with both
            env files: `.env` (secrets) and `state/release.env` (which image is deployed):
            """
        ),
        *notes_file_cells("deploy/production/lib.sh", [("", "")])[1:],
        md(
            """
            **`dc`** is `docker compose` with those files, for everyday use on the server
            (`deploy/production/dc ps`, `dc logs api`, `dc exec db psql -U notes`):
            """
        ),
        *notes_file_cells("deploy/production/dc", [("", "")])[1:],
        md(
            """
            **`backup.sh`** dumps the database with `pg_dump --format custom` (compressed;
            `pg_restore` can restore it table by table) into `state/backups/` and deletes
            dumps older than 14 days. `rollout.sh` calls it before every migration, cron every
            night. Dumps on the server die with the server: `DEPLOY.md` shows how to copy them
            off it.
            """
        ),
        *notes_file_cells("deploy/production/backup.sh", [("", "")])[1:],
        md(
            """
            **`rollout.sh`** is the deploy itself (Step 7 explains the order). Part 1: which
            release. CI passes the commit SHA and the image name; `rollback` picks the release
            before the current one from `history.log`:
            """
        ),
        *notes_file_cells(
            "deploy/production/rollout.sh",
            [
                ("", ""),
                (
                    "if [[ ${SKIP_PULL:-0} != 1 ]]; then",
                    """
                    Part 2: pull the images, make sure the database is up, back it up, and
                    run the migrations in a one-off container while the old replicas keep
                    serving:
                    """,
                ),
                (
                    "pin_upstreams() {",
                    """
                    Part 3: the swap. Pin Caddy to the running replicas, start the new ones
                    next to them (`--no-recreate` keeps the old containers; `--wait` blocks
                    until Docker reports the new ones healthy), pin Caddy to the new ones
                    (the drain), wait for requests in flight, then stop the old replicas with
                    SIGTERM. If the new replicas never become healthy, they are removed and
                    nothing else changes:
                    """,
                ),
                (
                    'log "worker"',
                    """
                    Part 4: replace the worker (SIGTERM; with the Step 2 fix it stops within a
                    second), apply the rest of the stack, let Caddy discover replicas again,
                    have Prometheus re-read its files, check that every replica runs the new
                    image, and record the release:
                    """,
                ),
                (
                    "if [[ ${PRUNE_IMAGES:-1} == 1 ]]; then",
                    """
                    Part 5: keep the five newest images (rollbacks need no download) and
                    remove the rest:
                    """,
                ),
            ],
        )[1:],
        md(
            """
            `%%writefile` creates ordinary files; the scripts must be **executable** (git
            records the mode, so CI's copy is executable too). Then a syntax check with
            `bash -n` and a lint with [ShellCheck](https://www.shellcheck.net/) from its image:
            """
        ),
        code(
            r"""
            SCRIPTS = ("dc", "backup.sh", "rollout.sh", "bootstrap.sh")
            for script in SCRIPTS:
                (PRODUCTION_DIR / script).chmod(0o755)
            (PRODUCTION_DIR / "lib.sh").chmod(0o644)  # sourced, never run
            for script in ("lib.sh", *SCRIPTS):
                syntax = subprocess.run(["bash", "-n", str(PRODUCTION_DIR / script)])
                mode = oct((PRODUCTION_DIR / script).stat().st_mode & 0o777)
                print(f"{script:<13} mode {mode}  bash -n exit {syntax.returncode}")
            if HAS_DOCKER:
                exit_code, output = run_tool(
                    "koalaman/shellcheck:v0.10.0",
                    "-x",
                    "-s",
                    "bash",
                    "lib.sh",
                    *SCRIPTS,
                    mount=PRODUCTION_DIR,
                )
                print(f"shellcheck: exit {exit_code}", output[-500:])
            """
        ),
    ]


ROLLOUT_MERMAID = """
```mermaid
sequenceDiagram
    participant CI as GitHub Actions
    participant R as rollout.sh
    participant C as Caddy
    participant O as old replicas
    participant N as new replicas
    participant DB as PostgreSQL
    CI->>R: ssh: rollout.sh <sha>
    R->>R: docker compose pull
    R->>DB: pg_dump (backup)
    R->>DB: migrate: alembic upgrade head (expand only)
    Note over O,DB: old code keeps serving on the new schema
    R->>C: pin to old replicas (caddy reload)
    R->>N: start, wait until healthy
    R->>C: pin to new replicas (drain)
    Note over C,N: every new request goes to the new code
    R->>O: SIGTERM after 2 s; Uvicorn finishes requests in flight
    R->>R: replace worker, rest of the stack
    R->>C: reload: discover every replica again
    CI->>C: smoke test over HTTPS (rollback on failure)
```
"""

ROLLOUT_ASCII = """
<details><summary>ASCII version</summary>

```text
time ──────────────────────────────────────────────────────────────────────────────►
pull ─ backup ─ migrate ─ pin(old) ─ start new ─ wait healthy ─ pin(new) ─ 2 s ─ SIGTERM old ─ worker ─ unpin
old replicas: ██████████████████████████████████████████████████████████████▓▓▓ (drain, exit)
new replicas:                           ░░░░ starting ░░░░ ██████████████████████████████████
Caddy sends to:   old ─────────────────────────────────────┐ new ─────────────────────────────
schema:       v(n) ── migrate ──► v(n+1) (old code must still work on it: expand/contract)
```

</details>
"""


def _zero_downtime_cells() -> list[NotebookNode]:
    """Step 7: migrations and zero-downtime deploys on this host."""
    return [
        md(
            """
            ### Step 7 — Migrations and zero-downtime deploys on this host

            Platforms such as Kubernetes or Cloud Run do rolling updates for you. On one server
            with Compose there is no orchestrator, so `rollout.sh` does the same thing in
            explicit steps:
            """
        ),
        md(ROLLOUT_MERMAID + ROLLOUT_ASCII),
        md(
            """
            **Why the proxy is pinned twice.** The first rehearsals of this script let Caddy
            find replicas through Docker's DNS during the whole swap. They lost a few requests
            out of about 30 000 per rollout, and each loss had a cause:

            | When | What Caddy did | Result | Fix in `rollout.sh` |
            | --- | --- | --- | --- |
            | new replicas starting | DNS lists a container as soon as it starts, before Uvicorn listens; Caddy tries it, the connection is refused, and the retry cannot resend a POST body it has already read | `502` on a POST | pin Caddy to the *old* replicas before starting new ones |
            | old replicas stopping | Caddy reused a pooled keep-alive connection just as Uvicorn closed it on SIGTERM (`connection reset by peer`) | `502` on a POST | pin Caddy to the *new* replicas, wait 2 s, then SIGTERM |

            Caddy retries GET requests safely, but not a POST whose body it already sent: the
            server might have processed it. The real fix is to never send a request to a
            replica that is starting or stopping. With both pins the proxy-to-app failures
            went to zero (the rehearsal in Step 11 measures it again).

            **What a pin costs.** A pin is a `caddy reload`: Caddy loads the new config and
            gracefully retires the old one. Idle **HTTP/1.1** keep-alive connections from
            clients are closed at that moment; a client that sends a request on one at the
            same instant sees *server disconnected without a response*. The request was never
            processed, and RFC 9110 lets clients retry it; browsers do, and HTTP/2 and HTTP/3
            clients (every browser with Caddy) receive a GOAWAY frame instead and move to a new
            connection. The rehearsal counts such retries separately.

            **Graceful shutdown, end to end.** `docker stop` → SIGTERM to PID 1 → Uvicorn stops
            accepting connections and lets requests in flight finish (`--timeout-graceful-shutdown
            20`) → exit 0. Compose's `stop_grace_period: 30s` is the deadline before SIGKILL;
            it must be longer than the app's own timeout.

            **Migrations run while the old code serves.** The migration step happens before
            the swap, so for a short time the *old* code runs on the *new* schema, and after a
            rollback the old code runs on it for as long as you like. Every migration must
            therefore be backward compatible: **expand → migrate → contract**, spread over
            releases. Renaming `notes.title` to `heading`, for example:

            | Release | Migration (runs before the swap) | Code | Old code still works? |
            | --- | --- | --- | --- |
            | N+1 (expand) | add nullable `heading`; copy `title` into it | writes both columns, reads `title` | yes: `title` is untouched |
            | N+2 (switch) | make `heading` NOT NULL (all rows filled) | writes both, reads `heading` | yes: N+1 writes both |
            | N+3 (contract) | drop `title` | uses only `heading` | yes: N+2 no longer needs `title` |

            Never rename or drop in one step, and never make the old release's queries fail.
            Rolling back the *code* is then always safe; rolling back the *schema*
            (`alembic downgrade`) is a separate, deliberate decision.

            **When a step fails**

            | Fails at | State | What happens next |
            | --- | --- | --- |
            | pull | nothing changed | the job fails; the old release keeps running |
            | backup | nothing changed | `set -e` stops the script before the migration |
            | migration | schema possibly half-migrated (PostgreSQL runs each Alembic migration in a transaction, so usually untouched) | the job fails; old replicas keep serving; read `dc logs`, fix, push |
            | new replicas unhealthy | old replicas pinned and serving | the new containers are removed; the job fails |
            | smoke test after the swap | the new release serves | the workflow runs `rollout.sh rollback` |
            """
        ),
    ]


PIPELINE_MERMAID = """
```mermaid
flowchart LR
    push["push / pull request"] --> lint & types & test
    lint & types & test --> build["build image<br/>+ container smoke test"]
    build --> scan["scan: Trivy, pip-audit"]
    scan -- "main only" --> pushimg["push to GHCR<br/>:sha and :latest"]
    pushimg -- "NOTES_HOST set" --> deploy["deploy: rsync, rollout.sh,<br/>HTTPS smoke test"]
    deploy -- "smoke test fails" --> rollback["rollout.sh rollback"]
    cron["every 15 min"] --> uptime["uptime: /health/ready,<br/>certificate > 14 days"]
```
"""

PIPELINE_ASCII = """
<details><summary>ASCII version</summary>

```text
push / PR ─┬─ lint  ─┐
           ├─ types ─┼─► build (+ smoke) ─► scan ─► push to GHCR ─► deploy ─► (rollback if the
           └─ test  ─┘                       main only ─┘   NOTES_HOST set ─┘   smoke test fails)
schedule (every 15 min) ─► uptime check (HTTPS ready + certificate valid for 14+ days)
```

</details>
"""


def _cicd_cells() -> list[NotebookNode]:
    """Step 8: the workflow's deploy job and the uptime workflow."""
    return [
        md(
            """
            ### Step 8 — CI/CD: deploy on `main`, check uptime every 15 minutes

            Unit 6.8's workflow deployed on version tags. The project deploys **every push to
            `main`** that passes every check; branches and pull requests run the checks only:
            """
        ),
        md(PIPELINE_MERMAID + PIPELINE_ASCII),
        md(
            """
            Part 1 of `.github/workflows/notes-api.yml`: triggers and shared settings. Pushes to
            `main` are never cancelled half-way (a cancelled deploy could stop between the
            migration and the swap):
            """
        ),
        *file_cells(
            "workflows/notes-api.yml",
            f"{WORKFLOWS_TARGET}/notes-api.yml",
            [
                ("", ""),
                (
                    "jobs:",
                    "Part 2: lint and types, unchanged from Unit 6.8, run in parallel:",
                ),
                (
                    "  test:",
                    "Part 3: the tests, against real PostgreSQL and Redis service containers:",
                ),
                (
                    "  build:",
                    """
                    Part 4: build the image once, check that the container starts, and keep
                    the image as an artifact for the next jobs:
                    """,
                ),
                (
                    "  scan:",
                    """
                    Part 5: scan the image and the locked dependencies, then push the image
                    with the commit SHA as its tag (on `main`, or a manual run on `main`):
                    """,
                ),
                (
                    "  deploy:",
                    """
                    Part 6: the deploy job. It runs only after `push`, only when the
                    `NOTES_HOST` variable exists (so pushing before the server is ready is
                    harmless), one at a time, in the `production` environment (whose secrets it
                    can read and where you can require an approval). It copies the Compose
                    files and logs the server in to GHCR with the job's short-lived token for
                    as long as `rollout.sh` runs:
                    """,
                ),
                (
                    "      - name: Smoke test over HTTPS",
                    """
                    Part 7: the smoke test, from outside, over the public URL: ready, migrated,
                    HTTP redirects with 308, HSTS present. If it fails, roll back:
                    """,
                ),
            ],
        )[1:],
        md(
            """
            **The uptime check** is a second workflow on a schedule. It needs no checkout and
            no permissions; it fails when the API is not ready over HTTPS three times in a row,
            or when the certificate expires within 14 days (renewal broke):
            """
        ),
        *file_cells(
            "workflows/notes-api-uptime.yml",
            f"{WORKFLOWS_TARGET}/notes-api-uptime.yml",
            [
                ("", ""),
                ("jobs:", "The job:"),
            ],
        )[1:],
        md(
            """
            **The job graph**, read back from the YAML (the deploy job runs last, and only
            on `main`):
            """
        ),
        code(
            r"""
            workflow = yaml.safe_load((WORKFLOWS_DIR / "notes-api.yml").read_text())
            jobs = workflow["jobs"]
            for name, job in jobs.items():
                needs = job.get("needs", [])
                needs = [needs] if isinstance(needs, str) else needs
                condition = job.get("if", "always")
                print(f"{name:<7} needs {', '.join(needs) or '-':<19} if: {condition[:62]}")
            print("deploy environment:", jobs["deploy"]["environment"]["name"])
            """
        ),
        md(
            """
            **Every secret, and where it lives.** The names are collected from the workflows
            (`secrets.*`, `vars.*`) and from `compose.prod.yaml` (`${VAR:?…}`); each one must
            appear in `DEPLOY.md`, which tells you how to create it:
            """
        ),
        code(
            r"""
            workflow_text = "".join(path.read_text() for path in WORKFLOWS_DIR.glob("notes-api*.yml"))
            compose_text = (NOTES_API_DIR / "compose.prod.yaml").read_text()
            deploy_guide = (NOTES_API_DIR / "DEPLOY.md").read_text()
            github_secrets = set(re.findall(r"secrets\.([A-Z_]+)", workflow_text)) - {"GITHUB_TOKEN"}
            server_values = set(re.findall(r"\$\{([A-Z_]+):\?", compose_text)) - {"NOTES_IMAGE", "TAG"}
            inventory = [
                *[(name, "GitHub: environment secret") for name in sorted(github_secrets)],
                *[
                    (name, "GitHub: repository variable")
                    for name in sorted(set(re.findall(r"vars\.([A-Z_]+)", workflow_text)))
                ],
                *[(name, "server: /srv/notes/.env") for name in sorted(server_values)],
                ("notes_jwt_secret", "server: /srv/notes/.secrets/ (a file)"),
            ]
            for name, place in inventory:
                print(f"{name:<24}{place:<38}in DEPLOY.md: {name in deploy_guide}")
            """
        ),
        md(
            """
            `GITHUB_TOKEN` is not on the list: GitHub creates it for every job and it expires
            when the job ends. **Lint both workflows** with
            [actionlint](https://github.com/rhysd/actionlint) (it also runs ShellCheck on every
            `run:` script):
            """
        ),
        code(
            r"""
            if HAS_DOCKER:
                exit_code, output = run_tool(
                    "rhysd/actionlint:1.7.7",
                    "-no-color",
                    "notes-api.yml",
                    "notes-api-uptime.yml",
                    mount=WORKFLOWS_DIR,
                )
                print(f"actionlint: exit {exit_code}", output or "(no findings)")
            else:
                print("SKIP actionlint: Docker is not available")
            """
        ),
    ]


def _load_test_file_cells() -> list[NotebookNode]:
    """Step 9: the locustfile and the report script."""
    return [
        md(
            """
            ### Step 9 — The load test and its report

            The scenario is Unit 6.8's locustfile with two production changes: certificates
            are verified for every host except `localhost` (the rehearsal's local CA), and the
            pass/fail thresholds can be set from the environment. Part 1: the settings:
            """
        ),
        *notes_file_cells(
            "load/locustfile.py",
            [
                ("", ""),
                ("def verify_tls(", "Part 2: when to verify certificates:"),
                (
                    "@events.test_start.add_listener",
                    "Part 3: one account for the whole run, created before the users start:",
                ),
                (
                    "class NotesUser(HttpUser):",
                    """
                    Part 4: the simulated user (weights 5 : 3 : 1 : 1 for list, read, create,
                    feed):
                    """,
                ),
                (
                    "@events.quitting.add_listener",
                    "Part 5: the gate: exit code 1 when p95 or the failure ratio misses its target:",
                ),
            ],
        )[1:],
        md(
            """
            **The report.** `LOAD_TEST.md` (committed) describes the scenario and the targets
            and has two results sections between markers. `load/report.py` turns Locust's CSV
            into the results tables, adds the **server-side** p95 from Prometheus (the time
            inside the API, without the network), checks the targets and replaces one
            section. Part 1: the targets and the CSV rows:
            """
        ),
        *notes_file_cells(
            "load/report.py",
            [
                ("", ""),
                (
                    "def read_stats(",
                    """
                    Part 2: Locust writes one row per method and name (`GET` and `POST
                    /api/v1/notes` are different rows) plus an `Aggregated` total:
                    """,
                ),
                (
                    "def server_p95_ms(",
                    """
                    Part 3: the server-side 95th percentile, computed by Prometheus from the
                    latency histogram over the test window:
                    """,
                ),
                ("def build_section(", "Part 4: the markdown, with a verdict per target:"),
                (
                    "def replace_section(",
                    "Part 5: replace one section of `LOAD_TEST.md`, and the command line:",
                ),
            ],
        )[1:],
    ]


CI_TESTS_SOURCE = r'''
async def fresh_database(server_url: str, name: str) -> str:
    """An empty database on the shared server."""
    connection = await asyncpg.connect(server_url.replace("postgresql+asyncpg", "postgresql"))
    try:
        await connection.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        await connection.execute(f"CREATE DATABASE {name}")
    finally:
        await connection.close()
    return server_url.rsplit("/", 1)[0] + f"/{name}"


PG_URL, REDIS_URL = start_shared_postgres(), start_shared_redis()
ci_env = {}
if PG_URL and REDIS_URL:
    ci_env = {
        "NOTES_TEST_DATABASE_URL": await fresh_database(PG_URL, "notes_project"),
        "NOTES_TEST_REDIS_URL": REDIS_URL,
    }
if HAS_UV:
    for label, command in (
        ("lint  ", ["uv", "run", "--frozen", "ruff", "check", "."]),
        ("format", ["uv", "run", "--frozen", "ruff", "format", "--check", "."]),
        ("types ", ["uv", "run", "--frozen", "mypy"]),
    ):
        step = run_in_notes(*command)
        print(f"{label}: exit {step.returncode} | {step.stdout.strip().splitlines()[-1]}")
    suite = run_in_notes(
        "uv", "run", "--frozen", "pytest", "-p", "no:cacheprovider", "-rfs", extra_env=ci_env
    )
    summary = tidy_test_output(suite.stdout).splitlines()
    print(summary[-1], f"(exit code {suite.returncode})")
    print(*[line for line in summary if line.startswith(("SKIPPED", "FAILED"))], sep="\n")
'''


def _tests_cells() -> list[NotebookNode]:
    """Step 10: tests for the production setup; the whole suite."""
    return [
        md(
            """
            ### Step 10 — Tests for the production setup

            Configuration is code, so it gets tests. `tests/test_production.py` reads the
            files and checks the properties that matter: nothing but the proxy is public, the
            app services never build, logs rotate, the connection budget fits during a rollout,
            secrets are required (never defaulted), the alerts use metrics the app really
            exports, the scripts are strict and executable, the rollout runs its steps in
            order, the deploy job waits for every check and runs only on `main`. Part 1: imports
            and paths (the workflows live at the repository root, two levels up):
            """
        ),
        *notes_file_cells(
            "tests/test_production.py",
            [
                ("", ""),
                ("class ComposeLoader(yaml.SafeLoader):", "Part 2: the loader for Compose's tags:"),
                (
                    "def load(path: Path)",
                    "Part 3: parse with that loader; the services, once per module:",
                ),
                (
                    "def test_backing_services_publish_no_host_ports",
                    "Part 4: the Compose override: ports and images:",
                ),
                (
                    "def test_every_service_rotates_its_logs",
                    "Part 5: logs and the connection budget:",
                ),
                (
                    "def test_secrets_are_required_not_defaulted",
                    "Part 6: secrets and Caddy:",
                ),
                (
                    "def test_alert_rules_use_metrics_the_app_exports",
                    "Part 7: the alert rules and Prometheus:",
                ),
                ('@pytest.mark.parametrize("script", SCRIPTS)', "Part 8: the scripts:"),
                (
                    "def test_rollout_order_backup_migrate_pin_start_drain_stop",
                    "Part 9: the rollout's order:",
                ),
                (
                    "def start_worker(",
                    """
                    Part 10: the Step 2 regression test. A helper starts the real worker
                    against Redis and waits until arq reports it started:
                    """,
                ),
                (
                    "@pytest.mark.redis",
                    """
                    The test sends SIGTERM like `docker stop` does and expects a clean exit
                    within 10 s (it needs Docker, like the other `redis` tests):
                    """,
                ),
                (
                    "workflows_present = pytest.mark.skipif(",
                    """
                    Part 11: the workflows (skipped when the Notes API is used outside this
                    repository):
                    """,
                ),
                (
                    "@workflows_present\ndef test_workflows_use_only_the_documented_secrets",
                    "Part 12: the secrets and variables, and the uptime schedule:",
                ),
            ],
        )[1:],
        md(
            """
            **The pipeline's checks, locally**: lint, format and types, then the whole suite
            the CI way (service URLs pointing at a fresh database on the shared PostgreSQL
            container, and the shared Redis):
            """
        ),
        code(CI_TESTS_SOURCE),
    ]


REHEARSAL_SETUP_SOURCE = r'''
REHEARSAL_STATE = PHASE6_DIR / "rehearsal_state"  # git-ignored; the server uses /srv/notes/state
REHEARSAL_URL = "https://localhost:58443"
REHEARSAL_ENV = {
    "COMPOSE_PROJECT_NAME": "notes-prod",
    "NOTES_STATE_DIR": str(REHEARSAL_STATE),
    "NOTES_IMAGE": "notes-api",
    "SKIP_PULL": "1",  # the images are built here, not pulled from GHCR
    "PRUNE_IMAGES": "0",  # leave this machine's other images alone
    "POSTGRES_PASSWORD": secrets.token_hex(16),
    "GRAFANA_ADMIN_PASSWORD": secrets.token_urlsafe(16),
    "NOTES_SITE": "localhost",
    "ACME_EMAIL": "ops@example.com",
    "PUBLIC_HTTP_PORT": "58080",
    "PUBLIC_HTTPS_PORT": "58443",
    "PROMETHEUS_PORT": "59090",
    "GRAFANA_PORT": "53000",
}


def production_script(
    script: str, *arguments: str, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run deploy/production/<script> with the rehearsal environment, as CI does over SSH."""
    return subprocess.run(
        [f"deploy/production/{script}", *arguments],
        cwd=NOTES_API_DIR,
        capture_output=True,
        text=True,
        timeout=600,
        env={**CHILD_ENV, **REHEARSAL_ENV, **(extra_env or {})},
    )


def remove_rehearsal_stack() -> subprocess.CompletedProcess[str]:
    """compose down for the rehearsal (volumes too); also the exit hook if a cell fails."""
    # down needs some TAG to read the files; no release is recorded
    return production_script("dc", "down", "--volumes", "--remove-orphans", extra_env={"TAG": "-"})


def rollout_log(run: subprocess.CompletedProcess[str]) -> list[str]:
    """The script's own log lines (Compose's progress lines left out); the tail on failure."""
    lines = [line for line in run.stdout.splitlines() if "rollout.sh:" in line]
    if run.returncode != 0:
        lines += (run.stdout + run.stderr).strip().splitlines()[-15:]
    return lines
'''

REHEARSAL_LOAD_SOURCE = r'''
def send_one(client: httpx.Client, number: int) -> str:
    """One request (every 4th a write). A request on an idle connection the server closed
    without answering is retried once, as browsers do; the outcome says so."""
    for attempt in (1, 2):
        try:
            if number % 4 == 0:
                reply = client.post("/api/v1/notes", json={"title": f"rollout {number}"})
            else:
                reply = client.get("/api/v1/notes?limit=5")
        except httpx.RemoteProtocolError as error:
            if "without sending a response" in str(error) and attempt == 1:
                continue
            return f"error {type(error).__name__}"
        except httpx.HTTPError as error:
            return f"error {type(error).__name__}"
        retried = " (retried on a new connection)" if attempt == 2 else ""
        return f"{reply.request.method} {reply.status_code}{retried}"
    return "unreachable"
'''

REHEARSAL_ROLLOUT_SOURCE = r'''
def rollout_under_load(
    target: str, token: str, users: int = 8
) -> tuple[subprocess.CompletedProcess[str], TallyCounter[str]]:
    """Run rollout.sh <target> while `users` threads keep sending requests; count outcomes."""
    outcomes: TallyCounter[str] = TallyCounter()
    stop, lock = threading.Event(), threading.Lock()

    def user_loop() -> None:
        """Send requests until stopped, counting each outcome."""
        headers = {"Authorization": f"Bearer {token}"}
        with httpx.Client(
            base_url=REHEARSAL_URL, verify=False, trust_env=False, timeout=10, headers=headers
        ) as client:
            number = 0
            while not stop.is_set():
                number += 1
                outcome = send_one(client, number)
                with lock:
                    outcomes[outcome] += 1

    users_threads = [threading.Thread(target=user_loop) for _ in range(users)]
    for thread in users_threads:
        thread.start()
    time.sleep(2)  # traffic flows before the rollout starts ...
    run = production_script("rollout.sh", target)
    time.sleep(2)  # ... and after it ends
    stop.set()
    for thread in users_threads:
        thread.join()
    return run, outcomes
'''


def _rehearsal_cells() -> list[NotebookNode]:
    """Step 11: the production stack on this machine."""
    return [
        md(
            """
            ### Step 11 — Rehearsal: the production stack on this machine

            Before touching a server, run the real scripts against the real production files
            here. The differences from the server are all in environment variables:

            | | Server | Rehearsal |
            | --- | --- | --- |
            | hostname | `203-0-113-10.sslip.io`: Let's Encrypt certificate | `localhost`: Caddy's internal CA (clients use `verify=False`) |
            | public ports | 80 and 443 | 58080 and 58443 |
            | Prometheus / Grafana | 127.0.0.1:9090 / 3000 | 127.0.0.1:59090 / 53000 |
            | images | pulled from GHCR, tagged with the commit SHA | built here, tagged `release-a` and `release-b` (`SKIP_PULL=1`) |
            | state folder | `/srv/notes/state` | `notebooks/_scratch/phase6/rehearsal_state` |
            | secrets | `/srv/notes/.env` | random values generated for this run (never printed) |

            The environment and two helpers: `production_script()` runs a script the way CI
            does over SSH, and `rollout_log()` keeps the script's own log lines:
            """
        ),
        code(REHEARSAL_SETUP_SOURCE),
        md(
            """
            **Two releases.** `release-a` is the 1.0.0 image built from `projects/notes_api/`;
            `release-b` is the same image with one extra label, so Docker sees a different
            image (as it would for the next commit). The JWT secret file is the one Unit 6.8
            created (written again if it is missing):
            """
        ),
        code(
            r"""
            secret_file = NOTES_API_DIR / ".secrets" / "notes_jwt_secret"
            if not secret_file.exists():
                secret_file.parent.mkdir(exist_ok=True)
                secret_file.write_text(secrets.token_urlsafe(32))
                secret_file.chmod(0o444)
            if HAS_DOCKER:
                started = time.perf_counter()
                docker("build", "--quiet", "--tag", "notes-api:release-a", ".", cwd=NOTES_API_DIR)
                release_b_dir = PHASE6_DIR / "release_b"  # a build context with one file
                release_b_dir.mkdir(exist_ok=True)
                (release_b_dir / "Dockerfile").write_text(
                    "FROM notes-api:release-a\nLABEL org.opencontainers.image.revision=release-b\n"
                )
                docker("build", "--quiet", "--tag", "notes-api:release-b", ".", cwd=release_b_dir)
                version_code = "import notes_api; print(notes_api.__version__)"
                version = docker(*"run --rm --entrypoint python notes-api:release-a -c".split(), version_code)
                print(
                    f"release-a and release-b built in {time.perf_counter() - started:.0f} s,"
                    f" version {version}, {image_size_mb('notes-api:release-a'):.0f} MB"
                )
            else:
                print("SKIP the rehearsal: Docker is not available")
            """
        ),
        md(
            """
            **The first deploy**: an empty server. `rollout.sh release-a` starts PostgreSQL and
            Redis, skips the backup (nothing to back up yet), runs the migrations, starts two
            API replicas, the worker, Caddy, Prometheus and Grafana. An exit hook takes the
            rehearsal stack down when the kernel stops, so a failing cell before the clean-up at
            the end of this step cannot leave it (and ports 58080, 58443, 59090, 53000) behind:
            """
        ),
        code(
            r"""
            if HAS_DOCKER:
                remove_rehearsal_stack()  # a clean start
                atexit.register(remove_rehearsal_stack)
                shutil.rmtree(REHEARSAL_STATE, ignore_errors=True)
                started = time.perf_counter()
                first_deploy = production_script("rollout.sh", "release-a")
                print(*rollout_log(first_deploy), sep="\n")
                print(f"exit code {first_deploy.returncode} after {time.perf_counter() - started:.0f} s")
            """
        ),
        md(
            """
            **HTTPS, as a user sees it**: readiness, the startup probe (the schema is at the
            revision the code needs, so the migrations ran), the redirect from HTTP, the
            security headers, and `/metrics` hidden at the proxy:
            """
        ),
        code(
            r"""
            if HAS_DOCKER:
                with httpx.Client(base_url=REHEARSAL_URL, verify=False, trust_env=False) as client:
                    print("ready   :", client.get("/health/ready").json())
                    print("startup :", client.get("/health/startup").json())
                    headers = client.get("/health/live").headers
                    for name in ("strict-transport-security", "x-content-type-options", "server"):
                        print(f"{name:<26}: {headers.get(name, '(not sent)')}")
                    print("/metrics:", client.get("/metrics").status_code)
                redirect = httpx.get("http://localhost:58080/health/live", trust_env=False)
                print("http    :", redirect.status_code, "->", redirect.headers["location"])
            """
        ),
        md(
            """
            The redirect points at port 443 (the server's port), not 58443: the rehearsal's
            port mapping is invisible to Caddy. **Monitoring**: Prometheus finds both
            replicas (it scrapes every 15 s, so the cell waits for the first scrape), the three
            alert rules are loaded and inactive, and Grafana has the provisioned dashboard:
            """
        ),
        code(
            r"""
            if HAS_DOCKER:
                prometheus = "http://127.0.0.1:59090/api/v1"
                for _ in range(40):
                    targets = httpx.get(f"{prometheus}/targets", trust_env=False).json()
                    api_targets = [
                        target["health"]
                        for target in targets["data"]["activeTargets"]
                        if target["labels"]["job"] == "notes-api"
                    ]
                    if api_targets.count("up") == 2:
                        break
                    time.sleep(1)
                print("notes-api targets:", api_targets)
                rules = httpx.get(f"{prometheus}/rules", trust_env=False).json()["data"]["groups"]
                print("alert rules:", [(rule["name"], rule["state"]) for rule in rules[0]["rules"]])
                found = httpx.get(
                    "http://127.0.0.1:53000/api/search",
                    params={"query": "Notes API", "type": "dash-db"},
                    auth=("admin", REHEARSAL_ENV["GRAFANA_ADMIN_PASSWORD"]),
                    trust_env=False,
                ).json()
                print("grafana dashboards:", [(item["title"], item["uid"]) for item in found])
            """
        ),
        md(
            """
            **Structured logs**: one API request (unauthenticated, so `401`), then its line in
            the API's log and in Caddy's access log. Both are JSON objects; the keys are what
            you filter on with `jq` (health checks and scrapes are not logged, so they cannot
            drown the real traffic):
            """
        ),
        code(
            r'''
            def last_json_line(service: str, must_contain: str) -> dict[str, Any]:
                """The newest JSON log line of a service that contains a marker."""
                logs = production_script("dc", "logs", "--no-log-prefix", "--tail", "200", service)
                for line in reversed(logs.stdout.splitlines()):
                    if line.startswith("{") and must_contain in line:
                        return json.loads(line)
                return {}


            if HAS_DOCKER:
                httpx.get(f"{REHEARSAL_URL}/api/v1/notes", verify=False, trust_env=False)
                time.sleep(1)
                api_line = last_json_line("api", '"event": "request"')
                print("api  :", {key: api_line[key] for key in ("event", "method", "path", "status")})
                print("       keys:", sorted(api_line))
                caddy_line = last_json_line("proxy", '"handled request"')
                print("proxy:", sorted(caddy_line))
                print("proxy request keys:", sorted(caddy_line.get("request", {})))
            '''
        ),
        md(
            """
            **Zero downtime, measured.** Eight threads send requests as fast as they can (a
            quarter are writes), through Caddy, while `rollout.sh release-b` replaces every API
            replica and the worker. Every outcome is counted:
            """
        ),
        code(REHEARSAL_LOAD_SOURCE),
        md(
            """
            `rollout_under_load()` runs the script while the threads send requests, from two
            seconds before it starts to two seconds after it ends:
            """
        ),
        code(REHEARSAL_ROLLOUT_SOURCE),
        md("A user for the traffic, then the rollout under load:"),
        code(
            r'''
            def rehearsal_token() -> str:
                """Register a user on the rehearsal stack and return an access token."""
                email, password = f"ops-{secrets.token_hex(3)}@example.com", "a-long-passphrase"
                with httpx.Client(base_url=REHEARSAL_URL, verify=False, trust_env=False) as client:
                    client.post("/api/v1/auth/register", json={"email": email, "password": password})
                    reply = client.post("/api/v1/auth/token", data={"username": email, "password": password})
                return reply.json()["access_token"]


            if HAS_DOCKER:
                rehearsal_access_token = rehearsal_token()
                second_deploy, outcomes = rollout_under_load("release-b", rehearsal_access_token)
                print(*rollout_log(second_deploy), sep="\n")
                total = sum(outcomes.values())
                print(f"\n{total} requests during the rollout:")
                for outcome, count in sorted(outcomes.items()):
                    print(f"  {count:>6}  {outcome}")
                failed = sum(count for outcome, count in outcomes.items() if "20" not in outcome)
                print(f"failed requests: {failed}")
            '''
        ),
        md(
            """
            Read the result by layer: a `5xx` would be the deploy's fault (a request sent to a
            replica that was starting or stopping); `(retried on a new connection)` lines, if
            any, are idle client connections Caddy closed during a reload, retried once like a
            browser would. **The worker step**: from the `worker` line to the next one is how
            long the old worker took to stop and the new one to become healthy (about 38 s
            with the v7 worker, which ignored SIGTERM):
            """
        ),
        code(
            r"""
            if HAS_DOCKER:
                steps = rollout_log(second_deploy)
                times = {line.split(" rollout.sh: ")[1]: line.split()[0] for line in steps}
                start = datetime.strptime(times["worker"], "%H:%M:%S")
                after = next(line for line in steps if "rest of the stack" in line).split()[0]
                elapsed = datetime.strptime(after, "%H:%M:%S") - start
                print(f"worker replaced in {elapsed.seconds} s")
                images = production_script("dc", "ps", "--format", "{{.Service}} {{.Image}}")
                print(*sorted(set(images.stdout.split("\n")) - {""}), sep="\n")
            """
        ),
        md(
            """
            **Rollback** is the same zero-downtime swap, to the release before the current
            one, using the image already on the machine (`SKIP_PULL=1`, as `DEPLOY.md` shows):
            """
        ),
        code(
            r"""
            if HAS_DOCKER:
                rolled_back = production_script("rollout.sh", "rollback")
                print(*rollout_log(rolled_back)[:1], *rollout_log(rolled_back)[-1:], sep="\n")
                print("history.log:")
                print((REHEARSAL_STATE / "history.log").read_text().strip())
                print("release.env:", (REHEARSAL_STATE / "release.env").read_text().split())
            """
        ),
        md(
            """
            **Backups**: one dump before every migration (the first deploy had nothing to back
            up). `pg_restore --list` reads a dump's table of contents without restoring it:
            proof that the file is a usable backup:
            """
        ),
        code(
            r"""
            if HAS_DOCKER:
                dumps = sorted((REHEARSAL_STATE / "backups").glob("notes-*.dump"))
                for dump in dumps:
                    print(f"  {dump.name}  {dump.stat().st_size / 1000:.0f} kB")
                with dumps[-1].open("rb") as dump_file:
                    contents = subprocess.run(
                        ["deploy/production/dc", "exec", "-T", "db", "pg_restore", "--list"],
                        cwd=NOTES_API_DIR,
                        stdin=dump_file,
                        capture_output=True,
                        text=True,
                        env={**CHILD_ENV, **REHEARSAL_ENV},
                    ).stdout
                tables = sorted({line.split()[-2] for line in contents.splitlines() if " TABLE DATA " in line})
                print("tables in the newest dump:", tables)
            """
        ),
        md(
            """
            **The load test.** Locust runs the Step 9 scenario against the rehearsal stack (50
            users, 15 s, through Caddy and TLS), then `load/report.py` writes the results into
            the *local rehearsal* section of `LOAD_TEST.md`, with the server-side p95 from the
            rehearsal's Prometheus:
            """
        ),
        code(
            r"""
            if HAS_DOCKER:
                locust_prefix = PHASE6_DIR / "project_locust"
                locust_options = f"--host {REHEARSAL_URL} --headless -u 50 -r 10 -t 15s --only-summary"
                load_run = subprocess.run(
                    [sys.executable, "-m", "locust", "-f", "load/locustfile.py", *locust_options.split()]
                    + ["--csv", str(locust_prefix)],
                    cwd=NOTES_API_DIR,
                    capture_output=True,
                    text=True,
                    env=CHILD_ENV,
                    timeout=180,
                )
                print("locust exit code (0 = within the targets):", load_run.returncode)
                time.sleep(16)  # one more Prometheus scrape after the last request
                report_options = (
                    f"--stats {locust_prefix}_stats.csv --section local --host {REHEARSAL_URL} "
                    "--users 50 --duration 15s --window 60 --prometheus http://127.0.0.1:59090"
                )
                report = subprocess.run(
                    [sys.executable, "load/report.py", *report_options.split()],
                    cwd=NOTES_API_DIR,
                    capture_output=True,
                    text=True,
                    env=CHILD_ENV,
                )
                print("report exit code:", report.returncode, report.stderr[-300:])
                display(Markdown(report.stdout))
            """
        ),
        md(
            """
            These numbers come from a developer machine, where Locust, Caddy, four Uvicorn
            processes and PostgreSQL share the same CPUs; they prove that the stack, the
            scenario and the report work end to end, not what the server will do. The live
            run fills the second section of `LOAD_TEST.md` after the deploy.

            **Clean up**: remove the rehearsal stack with its volumes, the two release tags,
            the shared PostgreSQL and Redis containers of Step 10, and confirm that no
            container is left running:
            """
        ),
        code(
            r"""
            if HAS_DOCKER:
                down = remove_rehearsal_stack()
                atexit.unregister(remove_rehearsal_stack)
                print("rehearsal stack removed:", down.returncode == 0)
                docker("rmi", "notes-api:release-b", "notes-api:release-a", check=False)
            stop_shared_postgres()
            stop_shared_redis()
            if shutil.which("docker"):
                running = subprocess.run(
                    ["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True
                ).stdout.split()
                reaper = [name for name in running if name.startswith("testcontainers-ryuk")]
                print("containers still running:", sorted(set(running) - set(reaper)) or "none")
                if reaper:
                    print("(testcontainers' reaper, Ryuk, exits by itself when the kernel stops)")
            """
        ),
    ]


PRODUCTION_README_SOURCE = r'''
PRODUCTION_README = """## Production

The production setup runs this stack on one Hetzner Cloud server with Docker Compose:
Caddy (automatic HTTPS from Let's Encrypt, HSTS), two API replicas, the worker, PostgreSQL,
Redis, Prometheus and Grafana. Every push to `main` that passes lint, types, tests, the image
build and the scans is deployed by `.github/workflows/notes-api.yml` with
`deploy/production/rollout.sh`: backup, migrations, then a zero-downtime swap of the replicas,
an HTTPS smoke test and an automatic rollback if it fails. `notes-api-uptime.yml` checks the
live API and its certificate every 15 minutes.

| File | Purpose |
| --- | --- |
| [`DEPLOY.md`](DEPLOY.md) | the runbook: server, secrets, first deploy, HTTPS checks, monitoring, rollback |
| [`LOAD_TEST.md`](LOAD_TEST.md) | the Locust scenario, the targets (p95 < 200 ms, < 1% errors, >= 100 req/s) and the results |
| `compose.prod.yaml` | production overrides merged over `compose.yaml` |
| `deploy/production/` | Caddyfile, Prometheus and alert rules, Grafana provisioning, `bootstrap.sh`, `rollout.sh`, `backup.sh`, `dc` |
| `load/report.py` | turns a Locust CSV into the results section of `LOAD_TEST.md` |
"""  # noqa: E501  (markdown table rows)
readme_path = NOTES_API_DIR / "README.md"
readme = re.sub(r"## Production\n.*?(?=## )", "", readme_path.read_text(), flags=re.S)
readme = readme.replace("## Endpoints", PRODUCTION_README + "\n\n## Endpoints", 1)
readme_path.write_text(readme)
print([line for line in readme.splitlines() if line.startswith("## ")])
'''


def _docs_cells() -> list[NotebookNode]:
    """Step 12: README, the runbook and what happens next."""
    return [
        md(
            """
            ### Step 12 — The README, the runbook and what happens next

            The project README gets a *Production* section after *Deploy* (Unit 6.8 rewrites
            the README, so this cell replaces the section instead of appending a second one):
            """
        ),
        code(PRODUCTION_README_SOURCE),
        md(
            """
            **`DEPLOY.md`** is the runbook for the steps that need you. It is a committed
            document (not generated by the notebook), so you can read it on GitHub next to the
            code. Its steps:
            """
        ),
        code(
            r"""
            deploy_steps = [
                line.removeprefix("## ")
                for line in (NOTES_API_DIR / "DEPLOY.md").read_text().splitlines()
                if line.startswith("## ") and line[3].isdigit()
            ]
            print(*deploy_steps, sep="\n")
            """
        ),
        md(
            """
            **Deployment status: waiting for the user steps.** Everything above was prepared
            and rehearsed on this machine; the live deployment starts when you:

            1. create the Hetzner account, the firewall and the server (`DEPLOY.md` steps 3–5);
            2. bootstrap it and put the secrets on it (steps 6–8);
            3. create `DEPLOY_SSH_KEY` and `DEPLOY_KNOWN_HOSTS` in the `production` environment
               and the `NOTES_HOST` variable (step 9);
            4. push `main` (step 10): CI checks, builds, pushes and deploys;
            5. verify HTTPS and open the dashboards (steps 11–12);
            6. run the live load test (step 13), which fills *Results — live* in
               `LOAD_TEST.md`.
            """
        ),
    ]


QUESTIONS: list[tuple[str, str, str, str]] = [
    (
        "6.1",
        """
        from urllib.parse import parse_qs, urlsplit

        request_line = b"GET /notes?tag=a&tag=b&page= HTTP/1.1"
        method, target, version = request_line.split(b" ")
        print(method, version)
        print(parse_qs(urlsplit(target.decode()).query))
        """,
        """
        `b'GET' b'HTTP/1.1'`, then `{'tag': ['a', 'b']}`. A request arrives as **bytes**, so
        splitting it gives bytes. `parse_qs` maps every name to a *list* (a name may repeat:
        JavaScript's `URLSearchParams.getAll`) and drops blank values such as `page=` unless
        you pass `keep_blank_values=True`.
        """,
        """
        from urllib.parse import parse_qs, urlsplit

        request_line = b"GET /notes?tag=a&tag=b&page= HTTP/1.1"
        method, target, version = request_line.split(b" ")
        print(method, version)
        print(parse_qs(urlsplit(target.decode()).query))
        print(parse_qs("page=", keep_blank_values=True))
        """,
    ),
    (
        "6.1",
        """
        from http import HTTPStatus

        print(HTTPStatus(404).phrase, HTTPStatus.CREATED == 201, HTTPStatus(429).name)
        print(HTTPStatus.NO_CONTENT.is_success, HTTPStatus(503).is_server_error)
        """,
        """
        `Not Found True TOO_MANY_REQUESTS`, then `True True`. `HTTPStatus` is an `IntEnum`, so
        it compares equal to the plain number; `is_success`, `is_client_error`,
        `is_server_error` (*new in 3.12*) classify a status by its hundreds digit.
        """,
        "",
    ),
    (
        "6.1",
        """
        from starlette.datastructures import Headers

        raw = [(b"x-tag", b"a"), (b"x-tag", b"b"), (b"content-type", b"text/plain")]
        headers = Headers(raw=raw)
        print(headers["Content-Type"], headers["X-Tag"], headers.getlist("x-tag"))
        """,
        """
        `text/plain a ['a', 'b']`. ASGI servers pass header names as **lower-case bytes**;
        Starlette's `Headers` is a case-insensitive multi-dict over them: `[...]` returns the
        first value of a repeated header, `getlist` all of them.
        """,
        "",
    ),
    (
        "6.2",
        """
        from pydantic import BaseModel, ValidationError


        class Item(BaseModel):
            \"\"\"An order line.\"\"\"

            quantity: int
            price: float


        item = Item(quantity="3", price=2)
        print(item.quantity, type(item.price).__name__)
        try:
            Item(quantity="3.5", price=1)
        except ValidationError as error:
            print(error.errors()[0]["type"])
        """,
        """
        `3 float`, then `int_parsing`. Pydantic's default *lax* mode converts the string
        `"3"` to `3` and the int `2` to `2.0`, but it will not turn `"3.5"` into an `int`
        (that would lose data), so validation fails with the error type `int_parsing`.
        """,
        "",
    ),
    (
        "6.2",
        """
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()


        @app.get("/notes/{note_id}")
        def read_note(note_id: int) -> dict[str, int]:
            \"\"\"One note by id.\"\"\"
            return {"note_id": note_id}


        @app.get("/notes/latest")
        def latest_note() -> dict[str, str]:
            \"\"\"The newest note.\"\"\"
            return {"note": "latest"}


        reply = TestClient(app).get("/notes/latest")
        print(reply.status_code, reply.json()["detail"][0]["type"])
        """,
        """
        `422 int_parsing`. Routes are tried **in registration order** and the first whose
        path *pattern* matches wins: `/notes/{note_id}` matches `/notes/latest`, and only then
        is `"latest"` validated as an `int`. Register fixed paths before parameterized ones.
        """,
        "",
    ),
    (
        "6.2",
        """
        from pydantic import BaseModel


        class NotePatch(BaseModel):
            \"\"\"The body of a PATCH request.\"\"\"

            title: str | None = None
            pinned: bool = False


        patch = NotePatch.model_validate({"title": None})
        print(patch.model_dump(exclude_unset=True))
        print(patch.model_dump(exclude_none=True))
        """,
        """
        `{'title': None}`, then `{'pinned': False}`. `exclude_unset` keeps what the client
        *sent*, even an explicit `null` (a PATCH that clears the title); `exclude_none` drops
        every `None`, sent or not, and keeps defaults. PATCH handlers want `exclude_unset`.
        """,
        "",
    ),
    (
        "6.3",
        """
        from typing import Annotated

        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient

        calls: list[str] = []


        def get_settings() -> dict[str, str]:
            \"\"\"Settings, recording each call.\"\"\"
            calls.append("settings")
            return {"environment": "test"}


        def get_repository(
            settings: Annotated[dict[str, str], Depends(get_settings)],
        ) -> dict[str, str]:
            \"\"\"A repository that needs the settings.\"\"\"
            return settings


        app = FastAPI()


        @app.get("/")
        def handler(
            settings: Annotated[dict[str, str], Depends(get_settings)],
            repository: Annotated[dict[str, str], Depends(get_repository)],
        ) -> dict[str, bool]:
            \"\"\"Is the settings object the repository got the same one?\"\"\"
            return {"same_object": settings is repository}


        print(TestClient(app).get("/").json(), calls)
        """,
        """
        `{'same_object': True} ['settings']`. Within one request FastAPI calls each
        dependency **once** and reuses the result wherever it is needed (`use_cache=True` by
        default), so the handler and the repository receive the same dict.
        """,
        "",
    ),
    (
        "6.3",
        """
        from collections.abc import Iterator
        from typing import Annotated

        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient

        events: list[str] = []


        def database_session() -> Iterator[str]:
            \"\"\"Open a session for the request; close it afterwards.\"\"\"
            events.append("open")
            yield "session"
            events.append("close")


        app = FastAPI()


        @app.get("/")
        def handler(session: Annotated[str, Depends(database_session)]) -> dict[str, str]:
            \"\"\"Use the session.\"\"\"
            events.append("handler")
            return {"session": session}


        TestClient(app).get("/")
        print(events)
        """,
        """
        `['open', 'handler', 'close']`. A dependency with `yield` is a context manager: the
        code before `yield` runs before the handler, the code after it once the handler has
        finished (here, before `TestClient` returns), which is where sessions are closed.
        """,
        "",
    ),
    (
        "6.3",
        """
        from typing import Annotated

        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient


        def get_clock() -> str:
            \"\"\"The real clock.\"\"\"
            return "real clock"


        def get_service(clock: Annotated[str, Depends(get_clock)]) -> str:
            \"\"\"A service that needs a clock.\"\"\"
            return f"service using {clock}"


        app = FastAPI()


        @app.get("/")
        def handler(service: Annotated[str, Depends(get_service)]) -> dict[str, str]:
            \"\"\"Report which clock the service got.\"\"\"
            return {"service": service}


        app.dependency_overrides[get_clock] = lambda: "fake clock"
        print(TestClient(app).get("/").json())
        """,
        """
        `{'service': 'service using fake clock'}`. Overrides are keyed by the **original
        function** and apply wherever it appears in the dependency graph, including inside
        other dependencies. That is how tests swap one leaf (a clock, a mailer) without
        touching the code that uses it.
        """,
        "",
    ),
    (
        "6.4",
        """
        from sqlalchemy import select
        from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


        class Base(DeclarativeBase):
            \"\"\"The declarative base for this question.\"\"\"


        class Note(Base):
            \"\"\"A note row.\"\"\"

            __tablename__ = "notes"
            id: Mapped[int] = mapped_column(primary_key=True)
            title: Mapped[str]
            body: Mapped[str | None]


        statement = select(Note.title).where(Note.id > 5).order_by(Note.title).limit(3)
        print(statement)
        print(Note.__table__.c.title.nullable, Note.__table__.c.body.nullable)
        """,
        """
        The SQL with **bound parameters**, not values: `SELECT notes.title FROM notes WHERE
        notes.id > :id_1 ORDER BY notes.title LIMIT :param_1` (over four lines), then
        `False True`. The 5 and the 3 travel separately from the SQL text, which is what makes
        SQL injection impossible here. `Mapped[str]` means NOT NULL; `Mapped[str | None]`
        means nullable.
        """,
        "",
    ),
    (
        "6.4",
        """
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


        class LibraryBase(DeclarativeBase):
            \"\"\"The declarative base for this question.\"\"\"


        class Book(LibraryBase):
            \"\"\"A book row.\"\"\"

            __tablename__ = "books"
            id: Mapped[int] = mapped_column(primary_key=True)
            title: Mapped[str]


        engine = create_engine("sqlite://")
        LibraryBase.metadata.create_all(engine)
        with Session(engine) as session:
            session.add(Book(id=1, title="Dune"))
            session.commit()
            first = session.get(Book, 1)
            second = session.scalars(select(Book).where(Book.id == 1)).one()
            print(first is second, first.title)
        """,
        """
        `True Dune`. A `Session` keeps an **identity map**: one Python object per database
        row. However you load row 1 (by primary key or by query), you get the same object
        back, so changes made through one reference are visible through the other.
        """,
        "",
    ),
    (
        "6.4",
        """
        # continuing the previous question (engine and Book)
        with Session(engine) as session:
            session.add(Book(id=2, title="Emma"))
            session.flush()
            print(session.get(Book, 2) is not None)
            session.rollback()
            print(session.get(Book, 2))
        """,
        """
        `True`, then `None`. `flush()` sends the INSERT inside the open transaction (so the
        row is visible to this session) but does not commit; `rollback()` undoes the
        transaction and the row is gone. `commit()` is what makes a change permanent.
        """,
        "",
    ),
    (
        "6.5",
        """
        from datetime import UTC, datetime, timedelta

        import jwt

        key = "k" * 32
        claims = {"sub": "42", "exp": datetime.now(UTC) - timedelta(seconds=1)}
        token = jwt.encode(claims, key, algorithm="HS256")
        try:
            jwt.decode(token, key, algorithms=["HS256"])
        except jwt.PyJWTError as error:
            print(type(error).__name__)
        print(jwt.decode(token, key, algorithms=["HS256"], options={"verify_exp": False})["sub"])
        print(token.count("."))
        """,
        """
        `ExpiredSignatureError`, `42`, `2`. `decode` checks `exp` by default; switching the
        check off shows that the signature itself is fine. A JWT is three base64url parts
        separated by two dots: header, claims, signature. The claims are only *signed*, not
        encrypted, so anyone can read them.
        """,
        "",
    ),
    (
        "6.5",
        """
        from pwdlib import PasswordHash
        from pwdlib.hashers.argon2 import Argon2Hasher

        hasher = PasswordHash((Argon2Hasher(time_cost=1, memory_cost=8192),))
        first, second = hasher.hash("correct horse"), hasher.hash("correct horse")
        print(first == second, hasher.verify("correct horse", first), first.split("$")[1])
        """,
        """
        `False True argon2id`. Every hash gets a fresh random **salt**, so the same password
        never produces the same hash twice (identical passwords stay unrecognisable in a
        leaked table). The salt and the parameters are stored inside the hash string, which
        is how `verify` can recompute it.
        """,
        "",
    ),
    (
        "6.6",
        """
        from fastapi import BackgroundTasks, FastAPI
        from fastapi.testclient import TestClient

        order: list[str] = []
        app = FastAPI()


        @app.post("/notes")
        def create(tasks: BackgroundTasks) -> dict[str, list[str]]:
            \"\"\"Create a note; e-mail about it later.\"\"\"
            tasks.add_task(order.append, "send e-mail")
            order.append("handler")
            return {"seen_by_handler": list(order)}


        print(TestClient(app).post("/notes").json(), order)
        """,
        """
        `{'seen_by_handler': ['handler']} ['handler', 'send e-mail']`. Background tasks run
        **after** the response is sent, in the same process. If the process dies first, the
        task is lost, which is why the Notes API sends webhooks through the outbox and ARQ.
        """,
        "",
    ),
    (
        "6.6",
        """
        import fakeredis

        redis_client = fakeredis.FakeRedis(decode_responses=True)
        print(redis_client.set("lock:export", "worker-1", nx=True, ex=30))
        print(redis_client.set("lock:export", "worker-2", nx=True, ex=30))
        print(redis_client.get("lock:export"), 0 < redis_client.ttl("lock:export") <= 30)
        """,
        """
        `True`, `None`, `worker-1 True`. `SET … NX EX` is an atomic "create if absent, with an
        expiry": the first caller gets the lock, the second gets `None` and the value stays
        `worker-1`. The expiry frees the lock even if its holder crashes.
        """,
        "",
    ),
    (
        "6.7",
        """
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()


        @app.get("/boom")
        def boom() -> None:
            \"\"\"Fail.\"\"\"
            raise RuntimeError("kaput")


        print(TestClient(app, raise_server_exceptions=False).get("/boom").status_code)
        try:
            TestClient(app).get("/boom")
        except RuntimeError as error:
            print("raised in the test:", error)
        """,
        """
        `500`, then `raised in the test: kaput`. A real server turns an unhandled exception
        into a 500. `TestClient` re-raises it by default, so a test fails with the real
        traceback instead of an anonymous 500; `raise_server_exceptions=False` gives you the
        response a client would get.
        """,
        "",
    ),
    (
        "6.7",
        """
        from prometheus_client import CollectorRegistry, Histogram

        registry = CollectorRegistry()
        latency = Histogram("demo_seconds", "Demo latency.", buckets=(0.1, 0.2), registry=registry)
        for seconds in (0.05, 0.15, 0.15, 3.0):
            latency.observe(seconds)
        metric = next(iter(registry.collect()))
        buckets = [sample for sample in metric.samples if sample.name.endswith("_bucket")]
        print({sample.labels["le"]: sample.value for sample in buckets})
        """,
        """
        `{'0.1': 1.0, '0.2': 3.0, '+Inf': 4.0}`. Histogram buckets are **cumulative**: each
        counts the observations *less than or equal to* its bound, and `+Inf` counts them
        all. `histogram_quantile()` (used by the p95 alert) interpolates inside these
        buckets, which is why the app's buckets are dense around 200 ms.
        """,
        "",
    ),
    (
        "6.8",
        """
        # compose.yaml                      # compose.prod.yaml
        # services:                         # services:
        #   proxy:                          #   proxy:
        #     image: caddy:2.10             #     ports: ["443:443"]
        #     ports: ["127.0.0.1:8443:443"]
        #
        # docker compose -f compose.yaml -f compose.prod.yaml config
        # Which ports does proxy publish?
        """,
        """
        **Both**: `127.0.0.1:8443->443` and `443->443`. Compose merges most sequences, `ports`
        included, by **appending**, not replacing. That is why `compose.prod.yaml` writes
        `ports: !override [...]` for the proxy and `ports: !reset []` for PostgreSQL and Redis.
        """,
        r"""
        merge_dir = PHASE6_DIR / "merge_demo"
        merge_dir.mkdir(exist_ok=True)
        (merge_dir / "compose.yaml").write_text(
            'services:\n  proxy:\n    image: caddy:2.10\n    ports: ["127.0.0.1:8443:443"]\n'
        )
        (merge_dir / "compose.prod.yaml").write_text('services:\n  proxy:\n    ports: ["443:443"]\n')
        if shutil.which("docker"):
            merged_demo = subprocess.run(
                "docker compose -f compose.yaml -f compose.prod.yaml config --format json".split(),
                cwd=merge_dir,
                capture_output=True,
                text=True,
            )
            ports = json.loads(merged_demo.stdout)["services"]["proxy"]["ports"]
            print([f"{port.get('host_ip') or '*'}:{port['published']}->{port['target']}" for port in ports])
        else:
            print("SKIP: the Docker CLI is not installed (answer: both ports are published)")
        """,
    ),
    (
        "6.8",
        """
        def peak_connections(replicas: int, processes: int, pool_size: int, max_overflow: int) -> int:
            \"\"\"Database connections while old and new replicas overlap during a rollout.\"\"\"
            return 2 * replicas * processes * (pool_size + max_overflow)


        print(peak_connections(2, 2, 5, 10), peak_connections(2, 2, 5, 5))
        """,
        """
        `120 80`. During a rollout the old and the new replicas run side by side, so the API
        can hold **twice** its normal connections. With Unit 6.8's pool (5 + 10 per process)
        that is 120, above PostgreSQL's default `max_connections` of 100: the new replicas
        would fail to connect in the middle of the deploy. Hence `compose.prod.yaml`: overflow
        5 (80 at the peak, plus 10 for the worker) and `max_connections=150`.
        """,
        "",
    ),
]


def _question_cells() -> list[NotebookNode]:
    """20 predict-the-output questions covering Units 6.1-6.8."""
    unit_counts: dict[str, int] = {}
    for unit, *_ in QUESTIONS:
        unit_counts[unit] = unit_counts.get(unit, 0) + 1
    coverage = ", ".join(f"{count} on Unit {unit}" for unit, count in unit_counts.items())
    cells = [
        md(
            f"""
            ### Phase 6 review — predict the output

            Twenty questions across the whole phase ({coverage}). Decide on the answer before
            opening it, then run the proof cell.
            """
        )
    ]
    for question_number, (unit, snippet, answer, proof) in enumerate(QUESTIONS, start=1):
        cells.append(md(f"#### Question {question_number} (Unit {unit})"))
        cells.extend(predict_cells(snippet=snippet, answer=answer, proof=proof or snippet))
    return cells


def _closing_cells() -> list[NotebookNode]:
    """Phase wrap-up."""
    return [
        md(
            """
            ## Phase 6 — Wrap-up

            | You can now… | Where |
            | --- | --- |
            | explain HTTP, WSGI and ASGI from the socket up, and what a framework adds | 6.1 |
            | build typed APIs with FastAPI and Pydantic v2, structured with dependency injection | 6.2–6.3 |
            | persist data with SQLAlchemy 2.0 and Alembic, and reason about pools, transactions and queries | 6.4 |
            | secure an API: password hashing, JWTs, OAuth2, authorization, the OWASP API Top 10 | 6.5 |
            | move work out of the request: background tasks, ARQ, WebSockets, SSE, caching | 6.6 |
            | test at every level and observe a service in production: logs, metrics, traces | 6.7 |
            | containerize, deploy without downtime, migrate safely, load-test and operate it | 6.8, Project |

            **Next:** the Capstone Project, a Team Task Tracker API, applies every phase of the
            course to a larger specification, from the design documents to a load-tested,
            zero-downtime deployment.
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for the Phase 6 Project."""
    return [
        *_overview_cells(),
        *_architecture_cells(),
        *_release_cells(),
        *_compose_cells(),
        *_https_cells(),
        *_monitoring_cells(),
        *_server_cells(),
        *_zero_downtime_cells(),
        *_cicd_cells(),
        *_load_test_file_cells(),
        *_tests_cells(),
        *_rehearsal_cells(),
        *_docs_cells(),
        *_question_cells(),
        *_closing_cells(),
    ]
