"""Unit 6.3 — Dependency Injection and Application Structure (with Lab 6.3 and Notes API v2)."""

from helpers_module import setup_cells
from nbformat import NotebookNode

from nb_builder import code, md, predict_cells, writefile_cells

UNIT_SETUP_SOURCE = r"""
import ast
import asyncio
import base64
import binascii  # noqa: F401  (for Lab 6.3, exercise 6)
import contextlib
import contextvars
import importlib
import importlib.util
import inspect
import json
import logging
import os
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import typing
import urllib.request
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Iterator
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from http import HTTPStatus
from pathlib import Path
from typing import Annotated, Any, Literal

import fastapi
import httpx
import pydantic
import pydantic_settings
import starlette
import uvicorn
from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    FastAPI,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import APIKeyHeader  # noqa: F401  (for Lab 6.3, exercise 2)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp, Message, Receive, Scope, Send

"""

PRUNE_HELPER_SOURCE = r'''
GENERATED_AREAS = ("src", "tests", "alembic")  # folders the notebook writes
GENERATED_FILES = ("alembic.ini", "compose.yaml", ".env.example")  # loose files it writes


def prune_notes_project(keep: Iterable[str]) -> list[str]:
    """Delete Notes API files that the version about to be written does not have.

    keep lists the version's files relative to projects/notes_api/. .venv, .env, uv.lock and
    the caches are never touched. Returns the removed paths; also creates the folders that
    the writefile cells need (a line starting with %% here would confuse notebook linters).
    """
    keep_set = set(keep)
    candidates = [
        path
        for area in GENERATED_AREAS
        for path in (NOTES_API_DIR / area).rglob("*")
        if path.is_file()
    ]
    loose_files = [NOTES_API_DIR / name for name in GENERATED_FILES]
    candidates += [path for path in loose_files if path.is_file()]
    removed = []
    for path in candidates:
        relative = path.relative_to(NOTES_API_DIR).as_posix()
        if "__pycache__" in path.parts or relative not in keep_set:
            path.unlink()
            if "__pycache__" not in path.parts:
                removed.append(relative)
    for area in GENERATED_AREAS:
        folders = sorted((NOTES_API_DIR / area).rglob("*"), key=lambda path: -len(path.parts))
        for folder in [*folders, NOTES_API_DIR / area]:
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
    for relative in keep_set:
        (NOTES_API_DIR / relative).parent.mkdir(parents=True, exist_ok=True)
    return sorted(removed)
'''

NOTES_PROJECT_HELPERS_SOURCE = r'''
def notes_tree() -> str:
    """The Notes API files as an indented tree (no .venv, caches, lock file or local data)."""
    skipped = {".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
    lines = []
    for path in sorted(NOTES_API_DIR.rglob("*")):
        relative = path.relative_to(NOTES_API_DIR)
        local_file = path.name in {"uv.lock", ".env"} or path.suffix == ".db"
        if skipped & set(relative.parts) or local_file:
            continue
        indent = "    " * (len(relative.parts) - 1)
        lines.append(f"{indent}{relative.name}{'/' if path.is_dir() else ''}")
    return "\n".join(lines)


def run_in_notes(
    *command: str, timeout: float = 600, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a command inside projects/notes_api (CHILD_ENV, captured text output)."""
    return subprocess.run(
        list(command),
        cwd=NOTES_API_DIR,
        capture_output=True,
        text=True,
        env={**CHILD_ENV, **(extra_env or {})},
        timeout=timeout,
    )


def lock_summary(uv_stderr: str) -> str:
    """Count the Added / Removed / Updated lines that  prints."""
    verbs = ("Added", "Removed", "Updated")
    counts = {verb: len(re.findall(rf"^{verb} ", uv_stderr, re.M)) for verb in verbs}
    resolved = re.search(r"Resolved (\d+) packages", uv_stderr)
    changes = ", ".join(f"{count} {verb.lower()}" for verb, count in counts.items())
    return f"uv lock: {resolved[1] if resolved else '?'} packages resolved, {changes}"


def show_response(response: httpx.Response, *header_names: str) -> None:
    """Print the status, the chosen headers and the body (JSON when possible)."""
    headers = {name: response.headers.get(name) for name in header_names}
    try:
        body: object = response.json()
    except ValueError:
        body = response.text[:200]
    print(response.status_code, headers if header_names else "", body)


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


print(interpreter_label())
print(f"{fastapi.__version__=}  {starlette.__version__=}  {pydantic_settings.__version__=}")
print(f"{HAS_UV=}  Notes API folder: {NOTES_API_DIR.relative_to(REPO_ROOT)}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 6.3 — Dependency Injection and Application Structure

            **Objectives**

            - Use `Depends` for shared parameters, nested and parameterized dependencies, class
              dependencies and `Annotated` aliases; know what is cached per request.
            - Write `yield` dependencies with setup, teardown and error handling, and choose
              when their teardown runs.
            - Attach dependencies to the whole app, a router or one route, and replace any of
              them in tests with `dependency_overrides`.
            - Structure an application: a `create_app()` factory, routers, schemas, models,
              services, repositories and core config, with dependencies pointing inwards.
            - Organize and version routes with `APIRouter`.
            - Configure the app with `pydantic-settings`, `.env` files and `SecretStr`.
            - Write middleware (Starlette's `BaseHTTPMiddleware` and pure ASGI), order it, and add
              request ids with `contextvars`, timing, GZip and CORS.
            - Return every error as RFC 9457 Problem Details.
            - Manage shared resources with the lifespan.
            - Read headers, cookies, forms and uploads safely; paginate with offsets and
              cursors; render HTML with Jinja2 and HTMX.
            - Turn the Notes API into **v2**: layered, configured, injectable and testable.

            **JS bridge**

            | JavaScript / TypeScript | FastAPI | The difference that bites |
            | --- | --- | --- |
            | NestJS `@Injectable()` providers + constructor injection | `Depends(callable)` in a parameter | no container or module registry: the **function signature** is the wiring |
            | NestJS request-scoped providers | dependencies are cached **per request** | a value computed twice in one request is reused unless `use_cache=False` |
            | Express middleware `(req, res, next)` | ASGI middleware `(scope, receive, send)` or `BaseHTTPMiddleware` | the last middleware **added** runs **first** |
            | `express.Router()` / Fastify plugins with a `prefix` | `APIRouter(prefix=..., tags=..., dependencies=...)` | routers are merged into the app at `include_router` time |
            | `dotenv` + zod schema for `process.env` | `pydantic-settings` `BaseSettings` | values are parsed **and validated**; a bad variable stops startup |
            | the `cors` package | `CORSMiddleware` | preflight is answered by the middleware; the browser enforces CORS, not the server |
            | an error-handling middleware `(err, req, res, next)` | `@app.exception_handler(ErrorType)` | handlers are looked up by exception class (MRO), not by order |
            | Jest `jest.mock()` / NestJS `overrideProvider` | `app.dependency_overrides[original] = fake` | override the **dependency function**, not a module import |
            | Supertest | `TestClient` (sync) / `httpx.AsyncClient` + `ASGITransport` | `with TestClient(app)` runs the lifespan; without `with` it does not |

            Run the setup cells first. Part 1: the imports (FastAPI, Starlette,
            pydantic-settings):
            """
        ),
        *setup_cells(
            "6.3",
            UNIT_SETUP_SOURCE,
            """
            Part 2: the shared helpers from [`phase6_helpers.py`](phase6_helpers.py): the error, timing and server helpers of
            Unit 6.1, the Notes API helpers of Unit 6.2 (`reload_notes_api`,
            `validation_problems`, `tidy_test_output`), and the ones this unit introduces:
            `prune_notes_project(keep)` removes files of other Notes API versions before a
            version is written (so re-running any unit gives exactly that version),
            `notes_tree()` prints the project layout, `run_in_notes(*command)` runs a command in
            the project folder, `lock_summary()` condenses `uv lock` output, `show_response()`
            prints a response compactly, and `temporary_env(**variables)` sets environment
            variables for one `with` block:
            """,
            folders="*NOTES_FOLDERS",
        ),
    ]


def _depends_cells() -> list[NotebookNode]:
    """6.3.1 Depends."""
    return [
        md(
            """
            ### 6.3.1 `Depends`

            A **dependency** is any callable FastAPI calls for you before the handler. Its
            parameters are resolved exactly like a handler's (path, query, header, body, or
            *other dependencies*), and its return value is passed to the parameter that asked
            for it. That gives you, without a DI container:

            | Need | Dependency form |
            | --- | --- |
            | the same query parameters on many routes | a function dependency |
            | a dependency configured differently per route | a **parameterized** dependency (a class with `__call__`, or a factory) |
            | layers: service needs repository needs session | **nested** dependencies |
            | a value used twice in one request | resolved **once per request** (cached) |
            | a dependency whose result is a typed object | a **class** as the dependency (`Depends()` with no argument) |
            | the same `Depends(...)` on many parameters | an **`Annotated` alias** |

            Start with the simplest one: shared pagination parameters. The dependency's
            parameters show up in the OpenAPI document of every route that uses it:
            """
        ),
        code(
            r'''
            def page_params(
                page: Annotated[int, Query(ge=1)] = 1, size: Annotated[int, Query(ge=1, le=100)] = 20
            ) -> dict[str, int]:
                """Shared query parameters: which page and how big."""
                return {"page": page, "size": size}


            catalog_app = FastAPI()


            @catalog_app.get("/books")
            async def list_books(paging: Annotated[dict[str, int], Depends(page_params)]) -> dict[str, object]:
                """Books, one page at a time."""
                return {"resource": "books", **paging}


            @catalog_app.get("/authors")
            async def list_authors(
                paging: Annotated[dict[str, int], Depends(page_params)],
            ) -> dict[str, object]:
                """Authors, one page at a time."""
                return {"resource": "authors", **paging}


            with TestClient(catalog_app) as client:
                print(client.get("/books", params={"page": 3}).json())
                print(client.get("/authors", params={"size": 500}).status_code, "(size > 100 is rejected)")
                openapi = client.get("/openapi.json").json()
            print([parameter["name"] for parameter in openapi["paths"]["/authors"]["get"]["parameters"]])
            '''
        ),
        md(
            """
            **Parameterized dependencies.** `Depends` takes a callable, so you can configure one
            first. An instance of a class with `__call__` is a callable whose settings live in
            `__init__`; each route gets its own configured instance. Here, one checker class
            protects routes with different required roles (the role arrives in a header for the
            demo; Unit 6.5 does real authentication):
            """
        ),
        code(
            r'''
            class RoleChecker:
                """A configurable dependency: allow only callers with one of the given roles."""

                def __init__(self, *allowed_roles: str) -> None:
                    """Remember which roles may pass."""
                    self.allowed_roles = set(allowed_roles)

                def __call__(self, x_role: Annotated[str, Header()] = "guest") -> str:
                    """FastAPI calls the instance: read the header, allow or refuse."""
                    if x_role not in self.allowed_roles:
                        raise HTTPException(status.HTTP_403_FORBIDDEN, f"role {x_role!r} not allowed")
                    return x_role


            roles_app = FastAPI()


            @roles_app.get("/reports")
            async def reports(role: Annotated[str, Depends(RoleChecker("editor", "admin"))]) -> dict[str, str]:
                """Editors and admins only."""
                return {"seen_by": role}


            @roles_app.delete("/reports")
            async def purge_reports(role: Annotated[str, Depends(RoleChecker("admin"))]) -> dict[str, str]:
                """Admins only."""
                return {"purged_by": role}


            with TestClient(roles_app) as client:
                print(client.get("/reports", headers={"X-Role": "editor"}).json())
                print(client.delete("/reports", headers={"X-Role": "editor"}).json())
            '''
        ),
        md(
            """
            A **factory function** does the same job: it returns a new dependency function
            that closes over the configuration. Use whichever reads better; the class form is
            easier to inspect (`checker.allowed_roles`) and to compare in tests:
            """
        ),
        code(
            r'''
            def require_header(header_name: str) -> Callable[[Request], str]:
                """Build a dependency that insists on one request header."""

                def header_dependency(request: Request) -> str:
                    """Return the header's value or answer 400."""
                    value = request.headers.get(header_name)
                    if value is None:
                        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"missing {header_name} header")
                    return value

                return header_dependency


            tenant_app = FastAPI()


            @tenant_app.get("/dashboard")
            async def dashboard(tenant: Annotated[str, Depends(require_header("X-Tenant"))]) -> dict[str, str]:
                """Data for one tenant."""
                return {"tenant": tenant}


            with TestClient(tenant_app) as client:
                print(client.get("/dashboard", headers={"X-Tenant": "acme"}).json())
                print(client.get("/dashboard").json())
            '''
        ),
        md(
            """
            **Nested dependencies.** A dependency can depend on others; FastAPI resolves the
            whole graph, innermost first. This is how layers are wired: the route asks for a
            service, the service dependency asks for a repository, the repository dependency
            asks for a connection. The log shows the resolution order:
            """
        ),
        code(
            r'''
            resolution_log: list[str] = []


            def get_connection() -> str:
                """Innermost: a (fake) database connection."""
                resolution_log.append("get_connection")
                return "connection#1"


            def get_book_repository(connection: Annotated[str, Depends(get_connection)]) -> dict[str, str]:
                """Middle: a repository using the connection."""
                resolution_log.append("get_book_repository")
                return {"repository": "books", "connection": connection}


            def get_book_service(
                repository: Annotated[dict[str, str], Depends(get_book_repository)],
            ) -> dict[str, object]:
                """Outer: a service using the repository."""
                resolution_log.append("get_book_service")
                return {"service": "books", "repository": repository}


            layered_app = FastAPI()


            @layered_app.get("/books/{book_id}")
            async def read_book(
                book_id: int, service: Annotated[dict[str, object], Depends(get_book_service)]
            ) -> dict[str, object]:
                """The handler only sees the finished service."""
                resolution_log.append("read_book")
                return {"book_id": book_id, **service}


            with TestClient(layered_app) as client:
                print(client.get("/books/7").json())
            print(" → ".join(resolution_log))
            '''
        ),
        md(
            """
            **Per-request caching.** If two dependencies (or the handler and a dependency) ask
            for the same dependency, FastAPI calls it **once per request** and shares the
            result. A new request calls it again. `Depends(..., use_cache=False)` opts out
            when you really want a fresh value each time it is mentioned:
            """
        ),
        code(
            r'''
            call_counts = {"cached": 0, "uncached": 0}


            def cached_token() -> str:
                """Counted each time FastAPI calls it."""
                call_counts["cached"] += 1
                return f"token-{call_counts['cached']}"


            def uncached_token() -> str:
                """Same, but asked for with use_cache=False."""
                call_counts["uncached"] += 1
                return f"fresh-{call_counts['uncached']}"


            def audit(token: Annotated[str, Depends(cached_token)]) -> str:
                """A dependency that also needs the token."""
                return f"audit saw {token}"


            cache_app = FastAPI()


            @cache_app.get("/")
            async def cache_demo(
                token: Annotated[str, Depends(cached_token)],
                audit_line: Annotated[str, Depends(audit)],
                first: Annotated[str, Depends(uncached_token, use_cache=False)],
                second: Annotated[str, Depends(uncached_token, use_cache=False)],
            ) -> dict[str, str]:
                """Four mentions of two dependencies."""
                return {"token": token, "audit": audit_line, "first": first, "second": second}


            with TestClient(cache_app) as client:
                print(client.get("/").json())
                client.get("/")
            print(f"{call_counts=}  (2 requests: cached called once per request, uncached twice)")
            '''
        ),
        md(
            """
            **Class dependencies.** A class is a callable too: `Depends(Paginator)` calls
            `Paginator(...)`, reading its `__init__` parameters from the request. When the
            annotation already names the class, `Depends()` with no argument means "the
            annotated type". The handler then gets a real, typed object with methods:
            """
        ),
        code(
            r'''
            class Paginator:
                """Query parameters for paging, plus the arithmetic that goes with them."""

                def __init__(
                    self, page: Annotated[int, Query(ge=1)] = 1, size: Annotated[int, Query(ge=1, le=50)] = 10
                ) -> None:
                    """FastAPI fills page and size from the query string."""
                    self.page = page
                    self.size = size

                @property
                def offset(self) -> int:
                    """Rows to skip."""
                    return (self.page - 1) * self.size

                def slice(self, items: list[int]) -> list[int]:
                    """This page of a list."""
                    return items[self.offset : self.offset + self.size]


            numbers_app = FastAPI()


            @numbers_app.get("/numbers")
            async def numbers(paginator: Annotated[Paginator, Depends()]) -> dict[str, object]:
                """Depends() with no argument uses the annotated class."""
                return {"offset": paginator.offset, "items": paginator.slice(list(range(1, 101)))}


            with TestClient(numbers_app) as client:
                print(client.get("/numbers", params={"page": 3, "size": 5}).json())
            '''
        ),
        md(
            """
            **`Annotated` aliases.** Writing `Annotated[Paginator, Depends()]` on every route is
            noisy. A type alias carries the dependency with it: routes say `paging: PagingDep`
            and nothing else. The Notes API exports its dependencies this way
            (`NoteServiceDep`, `SettingsDep`, ...). The alias is an ordinary object you can
            inspect:
            """
        ),
        code(
            r'''
            PagingDep = Annotated[Paginator, Depends()]
            TenantDep = Annotated[str, Depends(require_header("X-Tenant"))]

            alias_app = FastAPI()


            @alias_app.get("/invoices")
            async def invoices(tenant: TenantDep, paging: PagingDep) -> dict[str, object]:
                """Two dependencies, no Depends() noise in the signature."""
                return {"tenant": tenant, "page": paging.page, "size": paging.size}


            with TestClient(alias_app) as client:
                print(client.get("/invoices?page=2", headers={"X-Tenant": "acme"}).json())
            print(f"{typing.get_args(PagingDep)=}")
            '''
        ),
        md(
            """
            **Under the hood: the resolution graph.** When a route is registered, FastAPI walks
            the signature once and stores a `Dependant` tree on the route
            (`route.dependant`): the request parameters it needs and its sub-dependencies,
            recursively. The helper below prints that tree for the layered route from above,
            which is the diagram you would otherwise draw by hand:

            ```mermaid
            graph LR
              read_book --> get_book_service --> get_book_repository --> get_connection
              read_book -.path.-> book_id
            ```

            <details><summary>ASCII version</summary>

            ```text
            read_book(book_id, service)
            └── get_book_service(repository)
                └── get_book_repository(connection)
                    └── get_connection()
            ```

            </details>
            """
        ),
        code(
            r'''
            def dependency_tree(dependant: Any, depth: int = 0) -> list[str]:
                """Lines describing a Dependant: its own parameters, then each sub-dependency."""
                name = getattr(dependant.call, "__name__", type(dependant.call).__name__)
                own = [
                    param.name
                    for param in dependant.path_params + dependant.query_params + dependant.header_params
                ]
                lines = [f"{'    ' * depth}{name}({', '.join(own)})"]
                for sub_dependant in dependant.dependencies:
                    lines += dependency_tree(sub_dependant, depth + 1)
                return lines


            book_route = next(
                route for route in layered_app.routes if getattr(route, "path", "") == "/books/{book_id}"
            )
            print("\n".join(dependency_tree(book_route.dependant)))
            print()
            invoices_route = next(
                route for route in alias_app.routes if getattr(route, "path", "") == "/invoices"
            )
            print("\n".join(dependency_tree(invoices_route.dependant)))
            '''
        ),
        md(
            """
            > **Note:** recent FastAPI versions (0.163 here) add `Depends(..., max_concurrency=N)`:
            > at most N calls of that dependency run at once and the others wait, which is a
            > cheap way to protect a fragile downstream service. The limit belongs to the
            > `Depends` object, so share it through an alias. Check `inspect.signature(Depends)`
            > on your version before relying on it:
            """
        ),
        code(
            r'''
            print(
                "max_concurrency" in inspect.signature(Depends).parameters,
                "scope" in inspect.signature(Depends).parameters,
            )

            in_flight = {"now": 0, "peak": 0}


            async def fragile_upstream() -> str:
                """Pretend to call a service that cannot take parallel requests."""
                in_flight["now"] += 1
                in_flight["peak"] = max(in_flight["peak"], in_flight["now"])
                await asyncio.sleep(0.02)
                in_flight["now"] -= 1
                return "ok"


            UpstreamDep = Annotated[str, Depends(fragile_upstream, max_concurrency=2)]
            limited_app = FastAPI()


            @limited_app.get("/proxy")
            async def proxy(result: UpstreamDep) -> dict[str, str]:
                """Uses the rate-limited dependency."""
                return {"upstream": result}


            async def burst_limited() -> None:
                """Ten concurrent requests through the ASGI transport."""
                transport = httpx.ASGITransport(app=limited_app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    await asyncio.gather(*(client.get("/proxy") for _ in range(10)))


            await burst_limited()
            print(f"{in_flight['peak']=} (never more than 2 at once)")
            '''
        ),
    ]


def _yield_cells() -> list[NotebookNode]:
    """6.3.2 yield dependencies."""
    return [
        md(
            """
            ### 6.3.2 `yield` dependencies

            A dependency written as a generator gets **setup** (code before `yield`), gives
            the yielded value to the handler, and runs **teardown** (code after `yield`)
            later. It is a context manager that FastAPI enters and exits for you: database
            sessions, locks, temporary files, spans. Several of them unwind in **reverse
            order** (last set up, first torn down), like nested `with` blocks:
            """
        ),
        code(
            r'''
            teardown_log: list[str] = []


            async def open_session() -> AsyncIterator[str]:
                """Outer resource."""
                teardown_log.append("session: open")
                yield "session"
                teardown_log.append("session: close")


            async def open_transaction(session: Annotated[str, Depends(open_session)]) -> AsyncIterator[str]:
                """Inner resource, built on the outer one."""
                teardown_log.append("transaction: begin")
                yield f"transaction on {session}"
                teardown_log.append("transaction: end")


            yield_app = FastAPI()


            @yield_app.get("/work")
            async def do_work(transaction: Annotated[str, Depends(open_transaction)]) -> dict[str, str]:
                """The handler runs between setup and teardown."""
                teardown_log.append("handler")
                return {"used": transaction}


            with TestClient(yield_app) as client:
                print(client.get("/work").json())
            print(*teardown_log, sep="\n")
            '''
        ),
        md(
            """
            **Exceptions.** If the handler (or a later dependency) raises, the exception is
            thrown **into** the generator at the `yield`. Catch it to roll back, and re-raise
            so the normal error handling still happens (swallowing it would leave FastAPI
            without a response). `finally` runs in every case:
            """
        ),
        code(
            r'''
            transaction_log: list[str] = []


            async def unit_of_work() -> AsyncIterator[list[str]]:
                """Commit if the handler succeeded, roll back if it raised."""
                pending: list[str] = []
                try:
                    yield pending
                    transaction_log.append(f"commit {pending}")
                except Exception as error:
                    transaction_log.append(f"rollback {pending} because {type(error).__name__}")
                    raise  # keep the original error: FastAPI turns it into the response
                finally:
                    transaction_log.append("release connection")


            uow_app = FastAPI()


            @uow_app.post("/orders/{quantity}")
            async def place_order(
                quantity: int, work: Annotated[list[str], Depends(unit_of_work)]
            ) -> dict[str, int]:
                """Record the order; refuse impossible quantities."""
                work.append(f"order x{quantity}")
                if quantity > 5:
                    raise HTTPException(status.HTTP_409_CONFLICT, "not enough stock")
                return {"ordered": quantity}


            with TestClient(uow_app) as client:
                print(client.post("/orders/2").json())
                print(client.post("/orders/9").json())
            print(*transaction_log, sep="\n")
            '''
        ),
        md(
            """
            **When does teardown run?** This matters for databases: if the commit happens in
            teardown and teardown runs *after the response has been sent*, a failing commit
            can no longer change the response, and the client may get `200 OK` for data
            that was never saved. FastAPI lets you choose with `Depends(..., scope=...)`:

            | `scope` | Teardown runs | Use it for |
            | --- | --- | --- |
            | `"function"` | after the handler **and** response serialization, **before** the response is sent | transactions (commit before answering) |
            | `"request"` (the default for `yield` dependencies) | after the response has been sent | resources a streaming response still needs |

            The event log proves the order; a middleware marks the moment the response left
            the app:
            """
        ),
        code(
            r'''
            scope_events: list[str] = []


            async def request_scoped() -> AsyncIterator[None]:
                """Default scope."""
                yield
                scope_events.append("teardown: scope='request' (default)")


            async def function_scoped() -> AsyncIterator[None]:
                """Function scope."""
                yield
                scope_events.append("teardown: scope='function'")


            scope_app = FastAPI()


            @scope_app.middleware("http")
            async def mark_response(request: Request, call_next: RequestResponseEndpoint) -> Response:
                """Record when the response passes back through the middleware."""
                response = await call_next(request)
                scope_events.append("middleware: response leaves the app")
                return response


            @scope_app.get("/")
            async def scoped(
                first: Annotated[None, Depends(request_scoped)],
                second: Annotated[None, Depends(function_scoped, scope="function")],
            ) -> dict[str, bool]:
                """Two dependencies with different scopes."""
                scope_events.append("handler returns")
                return {"ok": True}


            with TestClient(scope_app) as client:
                client.get("/")
            print(*scope_events, sep="\n")
            '''
        ),
        md(
            """
            > **Warning:** with the default scope, an exception raised in teardown can no
            > longer become an error response. The Notes API's database session (Unit 6.4)
            > therefore uses `scope="function"`, so a failed commit is a 409 or 500, never a
            > 200 for lost data.

            **Under the hood.** FastAPI checks the kind of callable with `inspect` and wraps
            generators in context managers: `asynccontextmanager` for `async def ... yield`,
            and for a plain `def ... yield` a context manager whose steps run in the thread
            pool (so blocking setup code does not freeze the event loop):
            """
        ),
        code(
            r'''
            def sync_resource() -> Iterator[str]:
                """A blocking (def) yield dependency: FastAPI runs it in a worker thread."""
                yield threading.current_thread().name


            thread_app = FastAPI()


            @thread_app.get("/thread")
            async def which_thread(resource_thread: Annotated[str, Depends(sync_resource)]) -> dict[str, str]:
                """Compare the dependency's thread with the handler's."""
                return {"dependency": resource_thread, "handler": threading.current_thread().name}


            print(f"{inspect.isgeneratorfunction(sync_resource)=}")
            print(f"{inspect.isasyncgenfunction(open_session)=}")
            with TestClient(thread_app) as client:
                threads = client.get("/thread").json()
            print({role: re.sub(r"-[0-9a-f]+$", "-<id>", name) for role, name in threads.items()})
            '''
        ),
    ]


def _scope_cells() -> list[NotebookNode]:
    """6.3.3 Dependency scopes."""
    return [
        md(
            """
            ### 6.3.3 Dependency scopes

            Some dependencies are about the request, not about a parameter: logging, an API
            key check, a rate limit. Their return value is not used, so they are listed in a
            `dependencies=[...]` argument instead of a parameter. They can be attached at
            three levels:

            | Level | Where | Applies to |
            | --- | --- | --- |
            | app | `FastAPI(dependencies=[...])` | every route |
            | router | `APIRouter(dependencies=[...])` or `include_router(router, dependencies=[...])` | every route of that router |
            | route | `@router.get(..., dependencies=[...])` | one route |

            They run outermost first (app → router → route), then the parameter dependencies:
            """
        ),
        code(
            r'''
            level_log: list[str] = []


            def make_marker(label: str) -> Callable[[], None]:
                """A dependency that only records that it ran."""

                def marker() -> None:
                    """Record the level."""
                    level_log.append(label)

                return marker


            def handler_param() -> str:
                """An ordinary parameter dependency."""
                level_log.append("parameter dependency")
                return "value"


            levels_app = FastAPI(dependencies=[Depends(make_marker("app"))])
            reports_router = APIRouter(prefix="/reports", dependencies=[Depends(make_marker("router"))])


            @reports_router.get("/daily", dependencies=[Depends(make_marker("route"))])
            async def daily_report(value: Annotated[str, Depends(handler_param)]) -> dict[str, str]:
                """One route under all three levels."""
                level_log.append("handler")
                return {"value": value}


            levels_app.include_router(reports_router, dependencies=[Depends(make_marker("include_router"))])
            with TestClient(levels_app) as client:
                client.get("/reports/daily")
            print(" → ".join(level_log))
            '''
        ),
        md(
            """
            **`dependency_overrides`.** Every app has a dict mapping an original dependency to a
            replacement. FastAPI consults it while resolving, so tests can swap the database,
            the clock or an external client without touching application code. The key is
            the **original callable** (the function inside `Depends(...)`), even when routes use
            an `Annotated` alias. Clear the dict afterwards (a pytest fixture does it in
            `finally`):
            """
        ),
        code(
            r'''
            def get_clock() -> Callable[[], datetime]:
                """Production clock."""
                return lambda: datetime.now(UTC)


            ClockDep = Annotated[Callable[[], datetime], Depends(get_clock)]
            greeting_app = FastAPI()


            @greeting_app.get("/greeting")
            async def greeting(clock: ClockDep) -> dict[str, str]:
                """Morning or evening, depending on the injected clock."""
                return {"greeting": "Good morning" if clock().hour < 12 else "Good evening"}


            def fixed_clock() -> Callable[[], datetime]:
                """Test clock: always 08:30 UTC."""
                return lambda: datetime(2026, 11, 17, 8, 30, tzinfo=UTC)


            greeting_app.dependency_overrides[get_clock] = fixed_clock
            try:
                with TestClient(greeting_app) as client:
                    print("overridden:", client.get("/greeting").json())
            finally:
                greeting_app.dependency_overrides.clear()
            print(f"{greeting_app.dependency_overrides=}")
            '''
        ),
        md(
            """
            The same pattern as a pytest fixture, the way the Notes API tests use it. An
            override can be any callable, including an instance holding a fake; route-level
            and router-level dependencies can be overridden too:
            """
        ),
        code(
            r'''
            class FakeMailer:
                """Collects messages instead of sending them."""

                def __init__(self) -> None:
                    """Start with an empty outbox."""
                    self.outbox: list[str] = []

                def send(self, address: str, text: str) -> None:
                    """Record a message."""
                    self.outbox.append(f"{address}: {text}")


            def get_mailer() -> FakeMailer:
                """Production would return an SMTP client here."""
                raise RuntimeError("no SMTP server in the notebook")


            signup_app = FastAPI()


            @signup_app.post("/signup/{address}")
            async def signup(
                address: str, mailer: Annotated[FakeMailer, Depends(get_mailer)]
            ) -> dict[str, str]:
                """Send a welcome email."""
                mailer.send(address, "welcome!")
                return {"status": "sent"}
            '''
        ),
        md("`overridden()`: what a pytest fixture does: install an override, always remove it:"),
        code(
            r'''
            @contextlib.contextmanager
            def overridden(
                app: FastAPI, original: Callable[..., Any], replacement: Callable[..., Any]
            ) -> Iterator[None]:
                """What a pytest fixture does: install an override, always remove it."""
                app.dependency_overrides[original] = replacement
                try:
                    yield
                finally:
                    app.dependency_overrides.pop(original, None)


            fake_mailer = FakeMailer()
            with overridden(signup_app, get_mailer, lambda: fake_mailer), TestClient(signup_app) as client:
                print(client.post("/signup/asha@example.com").json(), fake_mailer.outbox)
            '''
        ),
    ]


def _structure_cells() -> list[NotebookNode]:
    """6.3.4 Project structure."""
    return [
        md(
            """
            ### 6.3.4 Project structure

            One `main.py` is fine for twenty lines. Past that, split the code by **job**, and
            let dependencies point **inwards**: HTTP details at the edge, business rules in
            the middle, storage behind an interface.

            | Layer | Folder / module | Knows about | Must not know about |
            | --- | --- | --- | --- |
            | Routers | `routers/` | HTTP: paths, status codes, schemas, dependencies | SQL, storage details |
            | Schemas | `schemas.py` | the JSON shapes clients send and receive | the database |
            | Services | `services.py` | business rules and use cases | FastAPI, HTTP |
            | Repositories | `repositories.py` | how records are stored and queried | HTTP |
            | Models | `models.py` | the records themselves (dataclasses, ORM models) | everything above |
            | Core | `core/` | settings, error handlers, middleware, lifespan | business rules |
            | App factory | `main.py` → `create_app()` | how the pieces are wired | |

            ```mermaid
            graph LR
              main[main.create_app] --> routers --> services --> repositories --> models
              routers --> schemas
              main --> core
              routers -.Depends.-> dependencies --> services
            ```

            <details><summary>ASCII version</summary>

            ```text
            main.create_app ──► routers ──► services ──► repositories ──► models
                 │                 │
                 └──► core         └──► schemas
            ```

            </details>

            **Why a factory?** `create_app(settings)` returns a new, fully wired app each time.
            Tests build one app per test (no shared state, no global to reset), a CLI can
            build one with different settings, and `uvicorn --factory pkg.main:create_app`
            builds it inside the server process.

            To see the structure in miniature, the next cells write a tiny **library** package
            into the scratch folder: a repository, a service with one business rule, a
            router, and a factory. First the folder:
            """
        ),
        code(
            r'''
            LIBRARY_DIR = PHASE6_DIR / "library_demo"
            LIBRARY_DIR.mkdir(exist_ok=True)
            (LIBRARY_DIR / "__init__.py").write_text(
                '"""A tiny layered FastAPI package."""\n', encoding="utf-8"
            )
            print(sorted(path.name for path in LIBRARY_DIR.iterdir()))
            '''
        ),
        md(
            """
            The repository: a `Protocol` (what the service needs) and an in-memory
            implementation. No FastAPI import here:
            """
        ),
        code(
            r'''
            %%writefile _scratch/phase6/library_demo/repositories.py
            """Storage: a Protocol and an in-memory implementation."""

            from typing import Protocol


            class BookRepository(Protocol):
                """What the service needs from storage."""

                def add(self, isbn: str, title: str) -> None:
                    """Store a book."""
                    ...

                def titles(self) -> dict[str, str]:
                    """Every book, isbn → title."""
                    ...


            class InMemoryBookRepository:
                """Books in a dict."""

                def __init__(self) -> None:
                    """Start empty."""
                    self._books: dict[str, str] = {}

                def add(self, isbn: str, title: str) -> None:
                    """Store a book."""
                    self._books[isbn] = title

                def titles(self) -> dict[str, str]:
                    """A copy, so callers cannot change storage."""
                    return dict(self._books)
            '''
        ),
        md(
            """
            The service holds the business rule (an ISBN may be added once) and raises a
            domain exception, not an `HTTPException`; it would work the same from a CLI:
            """
        ),
        code(
            r'''
            %%writefile _scratch/phase6/library_demo/services.py
            """Business rules, independent of HTTP."""

            from library_demo.repositories import BookRepository


            class DuplicateBookError(Exception):
                """The ISBN is already in the catalogue."""


            class BookService:
                """Use cases for the catalogue."""

                def __init__(self, repository: BookRepository) -> None:
                    """Depend on the Protocol, not on a concrete class."""
                    self.repository = repository

                def add_book(self, isbn: str, title: str) -> None:
                    """Add a book once."""
                    if isbn in self.repository.titles():
                        raise DuplicateBookError(isbn)
                    self.repository.add(isbn, title)

                def catalogue(self) -> dict[str, str]:
                    """Every book."""
                    return self.repository.titles()
            '''
        ),
        md(
            """
            The router is the only layer that speaks HTTP: it translates the domain error to
            a 409 and gets its service through `Depends`:
            """
        ),
        code(
            r'''
            %%writefile _scratch/phase6/library_demo/routers.py
            """HTTP layer: paths, status codes, dependency wiring."""

            from typing import Annotated

            from fastapi import APIRouter, Depends, HTTPException, Request, status

            from library_demo.services import BookService, DuplicateBookError


            def get_book_service(request: Request) -> BookService:
                """A service on the repository this app created."""
                return BookService(request.app.state.book_repository)


            BookServiceDep = Annotated[BookService, Depends(get_book_service)]
            router = APIRouter(prefix="/books", tags=["books"])


            @router.post("/{isbn}", status_code=status.HTTP_201_CREATED)
            def add_book(isbn: str, title: str, service: BookServiceDep) -> dict[str, str]:
                """Add a book; 409 if the ISBN exists."""
                try:
                    service.add_book(isbn, title)
                except DuplicateBookError as error:
                    raise HTTPException(status.HTTP_409_CONFLICT, f"{error} already exists") from error
                return {"isbn": isbn, "title": title}


            @router.get("")
            def list_books(service: BookServiceDep) -> dict[str, str]:
                """The whole catalogue."""
                return service.catalogue()
            '''
        ),
        md(
            """
            And the factory that wires it all: each call makes a new app with its **own**
            repository on `app.state`, plus a health route:
            """
        ),
        code(
            r'''
            %%writefile _scratch/phase6/library_demo/main.py
            """The application factory."""

            from fastapi import FastAPI

            from library_demo.repositories import InMemoryBookRepository
            from library_demo.routers import router


            def create_app() -> FastAPI:
                """A fully wired app with its own storage."""
                app = FastAPI(title="Library")
                app.state.book_repository = InMemoryBookRepository()
                app.include_router(router)

                @app.get("/health")
                def health() -> dict[str, str]:
                    """Liveness probe."""
                    return {"status": "ok"}

                return app
            '''
        ),
        md(
            """
            Two apps from the same factory do not share anything, which is exactly what tests
            need. A module-level `app = FastAPI()` with a module-level store (Notes API v1)
            cannot give you that without manual resets:
            """
        ),
        code(
            r"""
            for module_name in [name for name in sys.modules if name.startswith("library_demo")]:
                del sys.modules[module_name]
            importlib.invalidate_caches()
            library_main = importlib.import_module("library_demo.main")

            first_app, second_app = library_main.create_app(), library_main.create_app()
            with TestClient(first_app) as first_client, TestClient(second_app) as second_client:
                print(first_client.post("/books/978-1", params={"title": "Dune"}).json())
                print(first_client.post("/books/978-1", params={"title": "Dune"}).json())
                print("first app:", first_client.get("/books").json())
                print("second app:", second_client.get("/books").json())
            """
        ),
        md(
            """
            **Under the hood: checking the dependency direction.** `ast` can read each
            module's imports without running it. The rule "routers → services → repositories,
            never backwards, and only routers/main import FastAPI" becomes a test you can
            keep in CI:
            """
        ),
        code(
            r'''
            def import_graph(package_dir: Path) -> dict[str, set[str]]:
                """For each module of a package: the top-level names of everything it imports."""
                graph: dict[str, set[str]] = {}
                for path in sorted(package_dir.glob("*.py")):
                    imported: set[str] = set()
                    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                        if isinstance(node, ast.ImportFrom) and node.module:
                            imported.add(node.module)
                        elif isinstance(node, ast.Import):
                            imported.update(alias.name for alias in node.names)
                    graph[path.stem] = imported
                return graph


            LAYER_ORDER = ["main", "routers", "services", "repositories"]
            library_graph = import_graph(LIBRARY_DIR)
            for module, imports in library_graph.items():
                local = sorted(
                    name.removeprefix("library_demo.") for name in imports if name.startswith("library_demo.")
                )
                print(f"{module:13} imports {local}  fastapi={'fastapi' in imports}")
            backwards = [
                (module, name)
                for module, imports in library_graph.items()
                if module in LAYER_ORDER
                for name in imports
                if name.removeprefix("library_demo.") in LAYER_ORDER[: LAYER_ORDER.index(module)]
            ]
            print(f"{backwards=}")
            '''
        ),
        md(
            """
            Finally the real server: `uvicorn --factory` calls `create_app()` itself, in the
            server process (with `--workers 4`, once per worker):
            """
        ),
        code(
            r"""
            with uvicorn_server("library_demo.main:create_app", extra_args=["--factory"]) as base_url:
                with httpx.Client(base_url=base_url, trust_env=False) as client:
                    print(client.post("/books/978-2", params={"title": "Emma"}).json())
                    print(client.get("/books").json())
            """
        ),
    ]


def _router_cells() -> list[NotebookNode]:
    """6.3.5 APIRouter."""
    return [
        md(
            """
            ### 6.3.5 `APIRouter`

            An `APIRouter` is a mini app: it collects path operations with shared settings,
            and `app.include_router(router)` copies them into the app. Everything you can
            pass to a route can be given once for the whole router:

            | `APIRouter(...)` / `include_router(...)` argument | Effect |
            | --- | --- |
            | `prefix="/orders"` | prepended to every path (both places; they add up) |
            | `tags=["orders"]` | groups the routes in `/docs` |
            | `dependencies=[Depends(...)]` | run for every route (6.3.3) |
            | `responses={404: {...}}` | extra documented responses for every route |
            | `deprecated=True` | marks every route deprecated in OpenAPI |
            | `include_in_schema=False` | hides the routes from OpenAPI (HTML pages, internal routes) |

            Routers nest: a feature router is included in an `/api` router, which is included
            in the app. The paths add up.

            > **Note:** *changed in recent FastAPI versions (0.163 here)*: `include_router` no
            > longer copies routes into `app.routes`; it adds one `_IncludedRouter` entry that
            > resolves the router's routes lazily (later additions to the router still show
            > up). Use `app.openapi()["paths"]` (or `app.url_path_for`) to list routes, not
            > `app.routes`:
            """
        ),
        code(
            r'''
            orders_router = APIRouter(
                prefix="/orders", tags=["orders"], responses={404: {"description": "No such order"}}
            )
            customers_router = APIRouter(prefix="/customers", tags=["customers"])


            @orders_router.get("/{order_id}")
            async def get_order(order_id: int) -> dict[str, int]:
                """One order."""
                return {"order_id": order_id}


            @customers_router.get("/{customer_id}/orders")
            async def customer_orders(customer_id: int) -> dict[str, object]:
                """A customer's orders."""
                return {"customer_id": customer_id, "orders": []}


            api_router = APIRouter(prefix="/api")
            api_router.include_router(orders_router)
            api_router.include_router(customers_router)
            shop_app = FastAPI()
            shop_app.include_router(api_router)

            print([type(route).__name__ for route in shop_app.routes][-2:])
            shop_openapi = shop_app.openapi()
            print({path: sorted(operations) for path, operations in shop_openapi["paths"].items()})
            print(
                shop_openapi["paths"]["/api/orders/{order_id}"]["get"]["tags"],
                list(shop_openapi["paths"]["/api/orders/{order_id}"]["get"]["responses"]),
            )
            print(shop_app.url_path_for("customer_orders", customer_id="42"))
            '''
        ),
        md(
            """
            **Versioning.** When a response shape must change incompatibly, keep the old one
            running under its old prefix and add the new one beside it. Each version is a
            router; the old one is marked `deprecated` (OpenAPI shows it crossed out) and a
            router-level dependency adds `Deprecation` and `Sunset` headers so clients notice.
            Path versioning (`/v1`, `/v2`) is the most common choice; header or media-type
            versioning (`Accept: application/vnd.shop.v2+json`) keeps URLs stable but is
            harder to try in a browser:
            """
        ),
        code(
            r'''
            PRODUCTS = {1: ("Assam tea", 24900)}  # price in paise


            def deprecation_headers(response: Response) -> None:
                """Router-level dependency: tell clients this version is going away."""
                response.headers["Deprecation"] = "true"
                response.headers["Sunset"] = "Wed, 30 Jun 2027 00:00:00 GMT"


            v1_router = APIRouter(
                prefix="/v1", tags=["v1"], deprecated=True, dependencies=[Depends(deprecation_headers)]
            )
            v2_router = APIRouter(prefix="/v2", tags=["v2"])


            @v1_router.get("/products/{product_id}")
            async def get_product_v1(product_id: int) -> dict[str, object]:
                """v1: price as rupees in a float (the mistake v2 fixes)."""
                name, paise = PRODUCTS[product_id]
                return {"name": name, "price": paise / 100}


            @v2_router.get("/products/{product_id}")
            async def get_product_v2(product_id: int) -> dict[str, object]:
                """v2: integer minor units plus a currency."""
                name, paise = PRODUCTS[product_id]
                return {"name": name, "price": {"amount": paise, "currency": "INR", "minor_units": 2}}


            versioned_app = FastAPI()
            versioned_app.include_router(v1_router)
            versioned_app.include_router(v2_router)
            with TestClient(versioned_app) as client:
                show_response(client.get("/v1/products/1"), "deprecation", "sunset")
                show_response(client.get("/v2/products/1"))
            '''
        ),
        md("Which operations OpenAPI marks as deprecated (v1 only):"),
        code(
            r"""
            print(
                {
                    path: operation["get"].get("deprecated", False)
                    for path, operation in versioned_app.openapi()["paths"].items()
                }
            )
            """
        ),
    ]


def _settings_cells() -> list[NotebookNode]:
    """6.3.6 Configuration."""
    return [
        md(
            """
            ### 6.3.6 Configuration

            The [twelve-factor](https://12factor.net/config) rule: configuration that differs
            between environments (URLs, keys, flags) comes from **environment variables**, not
            from code. `pydantic-settings` reads them into a typed, validated model:

            | Feature | How |
            | --- | --- |
            | variable names | field name, upper-cased, plus `env_prefix` (`SHOP_PORT` for `port`) |
            | types | parsed like any Pydantic field: `"8080"` → `8080`, `"yes"` → `True`, JSON for lists and models |
            | nested settings | `env_nested_delimiter="__"`: `SHOP_SMTP__HOST` → `smtp.host` |
            | `.env` file | `env_file=".env"`; real environment variables win over the file |
            | secrets | `SecretStr`: shown as `**********`, read with `.get_secret_value()` |
            | files with secrets | `secrets_dir="/run/secrets"`: one file per field (Docker / Kubernetes secrets) |
            | validation | a wrong value stops the app at startup with a clear error |

            Precedence, highest first: arguments passed to the constructor → environment
            variables → `.env` file → `secrets_dir` files → field defaults.
            """
        ),
        code(
            r'''
            class SmtpSettings(BaseModel):
                """A nested group of settings."""

                host: str = "localhost"
                port: int = 25


            class ShopSettings(BaseSettings):
                """Settings for a demo shop service."""

                model_config = SettingsConfigDict(env_prefix="SHOP_", env_nested_delimiter="__", extra="ignore")

                name: str = "Demo shop"
                debug: bool = False
                port: int = Field(default=8000, ge=1, le=65535)
                allowed_hosts: list[str] = ["localhost"]
                api_key: SecretStr = SecretStr("")
                smtp: SmtpSettings = SmtpSettings()


            with temporary_env(
                SHOP_DEBUG="yes",
                SHOP_PORT="8080",
                SHOP_ALLOWED_HOSTS='["shop.example", "admin.shop.example"]',
                SHOP_SMTP__HOST="mail.internal",
            ):
                shop_settings = ShopSettings(_env_file=None)
            print(shop_settings.model_dump(exclude={"api_key"}))
            '''
        ),
        md(
            """
            **`.env` files and precedence.** The file is a list of `NAME=value` lines; keep it
            out of git (the course's `.gitignore` already ignores `.env`) and commit a
            `.env.example` with placeholders instead, so a new developer knows what to set.
            The demo writes a `.env` into the scratch folder with a key **generated now**, then
            shows that a real environment variable overrides the file:
            """
        ),
        code(
            r"""
            demo_env_file = PHASE6_DIR / "shop.env"
            generated_key = secrets.token_urlsafe(24)
            demo_env_file.write_text(
                f"SHOP_NAME=Shop from .env\nSHOP_PORT=9000\nSHOP_API_KEY={generated_key}\n", encoding="utf-8"
            )

            from_file = ShopSettings(_env_file=demo_env_file)
            with temporary_env(SHOP_PORT="7000"):
                env_wins = ShopSettings(_env_file=demo_env_file)
            explicit_wins = ShopSettings(_env_file=demo_env_file, port=6000)
            print(f"{from_file.name=}  {from_file.port=}")
            print(f"{env_wins.port=} (environment beats .env)  {explicit_wins.port=} (arguments beat both)")
            print(f"{from_file.api_key.get_secret_value() == generated_key=}")
            """
        ),
        md(
            """
            **`SecretStr`.** A secret should never end up in a log line, a traceback or an
            error response. `SecretStr` hides its value in `repr`, `str` and JSON dumps; only
            an explicit `.get_secret_value()` reveals it:
            """
        ),
        code(
            r"""
            print(repr(from_file.api_key))
            print(f"{from_file!r}"[:120], "...")
            print(from_file.model_dump(mode="json")["api_key"])
            print(f"{len(from_file.api_key.get_secret_value())=}")
            """
        ),
        md(
            """
            **Validation at startup.** A typo in a variable is caught before the app serves a
            single request, and the error names the variable's field:
            """
        ),
        code(
            r"""
            with temporary_env(SHOP_PORT="eighty", SHOP_DEBUG="sometimes"):
                print(validation_problems(lambda: ShopSettings(_env_file=None)))
            """
        ),
        md(
            """
            **Secret files.** Docker and Kubernetes mount secrets as files. With `secrets_dir`,
            a file named after the field supplies its value (lower priority than environment
            variables):
            """
        ),
        code(
            r'''
            secrets_folder = PHASE6_DIR / "shop_secrets"
            secrets_folder.mkdir(exist_ok=True)
            (secrets_folder / "shop_api_key").write_text(secrets.token_hex(16), encoding="utf-8")


            class MountedSecretsSettings(ShopSettings):
                """ShopSettings that also read /run/secrets-style files."""

                model_config = SettingsConfigDict(env_prefix="SHOP_", secrets_dir=secrets_folder)


            mounted = MountedSecretsSettings(_env_file=None)
            print(f"{len(mounted.api_key.get_secret_value())=} (read from {secrets_folder.name}/shop_api_key)")
            '''
        ),
        md(
            """
            **A cached settings dependency.** Reading and validating the environment on every
            request would be wasteful, and settings should not change while the process runs.
            `@lru_cache` on a getter makes it a process-wide singleton; `Depends(get_settings)`
            injects it; tests replace it with `dependency_overrides` (or call
            `get_settings.cache_clear()` after changing the environment):
            """
        ),
        code(
            r'''
            @lru_cache
            def get_shop_settings() -> ShopSettings:
                """Read the environment once per process."""
                return ShopSettings(_env_file=None)


            ShopSettingsDep = Annotated[ShopSettings, Depends(get_shop_settings)]
            settings_app = FastAPI()


            @settings_app.get("/info")
            async def shop_info(settings: ShopSettingsDep) -> dict[str, object]:
                """Uses the cached settings."""
                return {"name": settings.name, "debug": settings.debug}


            print(f"{get_shop_settings() is get_shop_settings()=}")
            settings_app.dependency_overrides[get_shop_settings] = lambda: ShopSettings(
                _env_file=None, name="Test shop", debug=True
            )
            with TestClient(settings_app) as client:
                print("in a test:", client.get("/info").json())
            settings_app.dependency_overrides.clear()
            with temporary_env(SHOP_NAME="Changed"):
                print("cached, ignores the change:", get_shop_settings().name)
                get_shop_settings.cache_clear()
                print("after cache_clear():", get_shop_settings().name)
            get_shop_settings.cache_clear()
            '''
        ),
        md(
            """
            > **Note:** the Notes API keeps both ideas: `get_settings()` is the cached reader
            > used when `create_app()` gets no settings, and `create_app(settings)` stores the
            > settings on `app.state`, so each test app carries its own settings and nothing
            > global has to be cleared.
            """
        ),
    ]


def _middleware_cells() -> list[NotebookNode]:
    """6.3.7 Middleware."""
    return [
        md(
            """
            ### 6.3.7 Middleware

            Middleware wraps the **whole app**: it sees every request before routing and every
            response after it, including 404s and requests no dependency ever touches. Use it
            for cross-cutting concerns (timing, request ids, compression, security headers);
            use dependencies for anything that needs route information or typed parameters.

            Starlette offers two styles:

            | | `BaseHTTPMiddleware` (`@app.middleware("http")`) | Pure ASGI middleware |
            | --- | --- | --- |
            | Shape | `async def mw(request, call_next) -> Response` | a class with `async __call__(scope, receive, send)` |
            | Ease | very easy, like Express `(req, res, next)` | more code: you wrap `send` to change the response |
            | Cost | creates `Request`/`Response` objects, an extra task and memory streams per request | almost none |
            | Context variables set by the endpoint | not visible after `call_next` | visible (same task) |
            | Streaming / WebSocket | HTTP only | anything, including `websocket` and `lifespan` scopes |

            First the easy style: a timing header with `@app.middleware("http")`:
            """
        ),
        code(
            r'''
            timed_app = FastAPI()


            @timed_app.middleware("http")
            async def add_process_time(request: Request, call_next: RequestResponseEndpoint) -> Response:
                """Measure the handler and report it in X-Process-Time (seconds)."""
                started = time.perf_counter()
                response = await call_next(request)
                response.headers["X-Process-Time"] = f"{time.perf_counter() - started:.4f}"
                return response


            @timed_app.get("/slow")
            async def slow() -> dict[str, str]:
                """Takes about 50 ms."""
                await asyncio.sleep(0.05)
                return {"status": "done"}


            with TestClient(timed_app) as client:
                elapsed = float(client.get("/slow").headers["x-process-time"])
                missing = client.get("/missing")
            print(f"{elapsed >= 0.05=}  404 responses are timed too: {'x-process-time' in missing.headers}")
            '''
        ),
        md(
            """
            The same kind of job as a **pure ASGI** middleware: a class that receives the next
            app, and an `__call__` that wraps `send` to add headers when the
            `http.response.start` message goes out. This one adds security headers to every
            HTTP response and leaves other scope types alone:
            """
        ),
        code(
            r'''
            class SecurityHeadersMiddleware:
                """Pure ASGI: add standard security headers to every HTTP response."""

                HEADERS = {
                    "X-Content-Type-Options": "nosniff",
                    "X-Frame-Options": "DENY",
                    "Referrer-Policy": "no-referrer",
                }

                def __init__(self, app: ASGIApp) -> None:
                    """Wrap the next app in the stack."""
                    self.app = app

                async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
                    """Pass the request through; edit the response start message on its way out."""
                    if scope["type"] != "http":
                        await self.app(scope, receive, send)
                        return

                    async def send_with_headers(message: Message) -> None:
                        """Add the headers to the first response message."""
                        if message["type"] == "http.response.start":
                            headers = MutableHeaders(scope=message)
                            for name, value in self.HEADERS.items():
                                headers.setdefault(name, value)
                        await send(message)

                    await self.app(scope, receive, send_with_headers)


            secure_app = FastAPI()
            secure_app.add_middleware(SecurityHeadersMiddleware)


            @secure_app.get("/page")
            async def page() -> dict[str, str]:
                """Any route."""
                return {"page": "home"}
            '''
        ),
        md("Every response now carries the three headers, whatever the route returned:"),
        code(
            r"""
            with TestClient(secure_app) as client:
                show_response(
                    client.get("/page"), "x-content-type-options", "x-frame-options", "referrer-policy"
                )
            """
        ),
        md(
            """
            **A difference you can observe.** `BaseHTTPMiddleware` runs the rest of the app in
            a separate task, so a `ContextVar` the endpoint sets is **not** visible after
            `call_next`. In a pure ASGI middleware the endpoint runs in the same task and the
            value is there. (Middleware that *sets* a variable before calling the app works in
            both, which is what request ids need.)
            """
        ),
        code(
            r'''
            endpoint_marker: contextvars.ContextVar[str] = contextvars.ContextVar(
                "endpoint_marker", default="unset"
            )
            seen_after_endpoint: dict[str, str] = {}


            class PureMarkerReader:
                """Pure ASGI: read the variable after the endpoint ran."""

                def __init__(self, app: ASGIApp) -> None:
                    """Wrap the next app."""
                    self.app = app

                async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
                    """Call the app, then look at the variable."""
                    await self.app(scope, receive, send)
                    if scope["type"] == "http":
                        seen_after_endpoint["pure ASGI"] = endpoint_marker.get()


            marker_app = FastAPI()
            marker_app.add_middleware(PureMarkerReader)


            @marker_app.middleware("http")
            async def base_marker_reader(request: Request, call_next: RequestResponseEndpoint) -> Response:
                """BaseHTTPMiddleware: read the variable after call_next."""
                response = await call_next(request)
                seen_after_endpoint["BaseHTTPMiddleware"] = endpoint_marker.get()
                return response


            @marker_app.get("/mark")
            async def mark() -> dict[str, bool]:
                """Set the variable inside the endpoint."""
                endpoint_marker.set("set by the endpoint")
                return {"ok": True}
            '''
        ),
        md("Call the endpoint and compare what each middleware saw after it ran:"),
        code(
            r"""
            with TestClient(marker_app) as client:
                client.get("/mark")
            print(seen_after_endpoint)
            """
        ),
        md(
            """
            **Cost.** A rough comparison: 300 requests through an app with five pass-through
            middlewares of each kind, in-process via `ASGITransport`. Timings vary by machine;
            the ratio is what to look at:
            """
        ),
        code(
            r'''
            class PassThrough:
                """A pure ASGI middleware that does nothing."""

                def __init__(self, app: ASGIApp) -> None:
                    """Wrap the next app."""
                    self.app = app

                async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
                    """Just call the next app."""
                    await self.app(scope, receive, send)


            async def base_pass_through(request: Request, call_next: RequestResponseEndpoint) -> Response:
                """A BaseHTTPMiddleware that does nothing."""
                return await call_next(request)


            def stacked_app(use_pure: bool) -> FastAPI:
                """An app with five do-nothing middlewares of one kind."""
                app = FastAPI()
                for _ in range(5):
                    if use_pure:
                        app.add_middleware(PassThrough)
                    else:
                        app.add_middleware(BaseHTTPMiddleware, dispatch=base_pass_through)
                app.add_api_route("/ping", lambda: {"pong": True})
                return app


            async def time_requests(app: FastAPI, request_count: int = 300) -> float:
                """Seconds for sequential requests through the ASGI transport."""
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test"
                ) as client:
                    started = time.perf_counter()
                    for _ in range(request_count):
                        await client.get("/ping")
                    return time.perf_counter() - started
            '''
        ),
        md("Time 300 requests through each stack (the ratio matters, not the absolute numbers):"),
        code(
            r"""
            pure_seconds, base_seconds = (
                await time_requests(stacked_app(True)),
                await time_requests(stacked_app(False)),
            )
            print(
                f"pure ASGI: {pure_seconds:.3f} s   BaseHTTPMiddleware: {base_seconds:.3f} s   "
                f"ratio {base_seconds / pure_seconds:.1f}x"
            )
            """
        ),
        md(
            """
            **Request ids with `contextvars`.** Give every request an id, put it in the
            response header, and make it available to **any** code that runs for that request
            (logs above all) without passing it through every function. A `ContextVar` is
            the tool: each request runs in its own task with its own context, so concurrent
            requests never see each other's id. This is the `RequestIdFilter` idea from Unit
            5.4, now fed by middleware (here the easy style; Lab 6.3 asks for a pure ASGI
            version):
            """
        ),
        code(
            r'''
            request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


            class RequestIdFilter(logging.Filter):
                """Copy the current request id onto every log record."""

                def filter(self, record: logging.LogRecord) -> bool:
                    """Add record.request_id; never drop a record."""
                    record.request_id = request_id.get()
                    return True


            log_lines: list[str] = []


            class ListHandler(logging.Handler):
                """Keep formatted log lines in a list (instead of stderr) for the notebook."""

                def emit(self, record: logging.LogRecord) -> None:
                    """Store one line."""
                    log_lines.append(self.format(record))


            demo_logger = logging.getLogger("demo.requests")
            demo_logger.handlers[:] = [ListHandler()]
            demo_logger.handlers[0].setFormatter(logging.Formatter("[%(request_id)s] %(message)s"))
            demo_logger.addFilter(RequestIdFilter())
            demo_logger.setLevel(logging.INFO)
            demo_logger.propagate = False
            print(f"{demo_logger.filters=}")
            '''
        ),
        md(
            """
            The middleware sets the variable (reusing a client-supplied `X-Request-ID` when it
            looks safe), and a function deep in the "service layer" logs without knowing
            anything about requests. Five concurrent requests each log with their own id:
            """
        ),
        code(
            r'''
            ids_app = FastAPI()


            @ids_app.middleware("http")
            async def assign_request_id(request: Request, call_next: RequestResponseEndpoint) -> Response:
                """Set the id for this request's context and echo it in the response."""
                incoming = request.headers.get("X-Request-ID", "")
                current = incoming if re.fullmatch(r"[\w.-]{1,64}", incoming) else uuid.uuid4().hex[:8]
                token = request_id.set(current)
                try:
                    response = await call_next(request)
                finally:
                    request_id.reset(token)
                response.headers["X-Request-ID"] = current
                return response


            async def charge_card(amount: int) -> None:
                """Deep inside the service layer: no request object here."""
                demo_logger.info("charging %d paise", amount)
                await asyncio.sleep(0.01)
                demo_logger.info("charged")


            @ids_app.post("/pay/{amount}")
            async def pay(amount: int) -> dict[str, int]:
                """Calls the service."""
                await charge_card(amount)
                return {"paid": amount}
            '''
        ),
        md(
            "`five_payments()`: concurrent requests, ids chosen by the client so the output is stable:"
        ),
        code(
            r'''
            async def five_payments() -> list[str]:
                """Concurrent requests, ids chosen by the client so the output is stable."""
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=ids_app), base_url="http://test"
                ) as client:
                    responses = await asyncio.gather(
                        *(
                            client.post(f"/pay/{amount}", headers={"X-Request-ID": f"req-{amount}"})
                            for amount in (100, 200, 300)
                        )
                    )
                return [response.headers["x-request-id"] for response in responses]


            log_lines.clear()
            print(await five_payments())
            print(
                *sorted(log_lines, key=lambda line: line.split("]")[0]), sep="\n"
            )  # grouped by request, in order
            '''
        ),
        md(
            """
            **GZip.** `GZipMiddleware` compresses responses when the client sends
            `Accept-Encoding: gzip` and the body is at least `minimum_size` bytes (small bodies
            are not worth the CPU). JSON compresses very well:
            """
        ),
        code(
            r'''
            gzip_app = FastAPI()
            gzip_app.add_middleware(GZipMiddleware, minimum_size=500)


            @gzip_app.get("/report")
            async def report(rows: int = 200) -> list[dict[str, object]]:
                """A repetitive JSON report."""
                return [{"row": number, "status": "ok", "region": "south"} for number in range(rows)]


            with TestClient(gzip_app) as client:
                for rows, encoding in [(200, "gzip"), (2, "gzip"), (200, "identity")]:
                    response = client.get(
                        "/report", params={"rows": rows}, headers={"Accept-Encoding": encoding}
                    )
                    print(
                        f"rows={rows:3} accept={encoding:8} → "
                        f"content-encoding={response.headers.get('content-encoding')}, "
                        f"{len(response.content)} bytes of JSON, "
                        f"{response.num_bytes_downloaded} bytes on the wire"
                    )
            '''
        ),
        md(
            """
            **Ordering.** `app.add_middleware()` puts the new middleware **outside** the ones
            already added, so the last one added sees the request first and the response last,
            like layers of an onion. Starlette also adds its own layers around yours:
            `ServerErrorMiddleware` (outermost, turns crashes into 500s) and
            `ExceptionMiddleware` (innermost, runs your exception handlers). The demo logs
            enter/exit and then walks the built stack through each layer's `.app` attribute:
            """
        ),
        code(
            r'''
            onion_log: list[str] = []


            def logging_middleware(label: str) -> type:
                """Build a pure ASGI middleware class that logs entering and leaving."""

                class Layer:
                    """One onion layer."""

                    def __init__(self, app: ASGIApp) -> None:
                        """Wrap the next app."""
                        self.app = app

                    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
                        """Log around the inner app."""
                        if scope["type"] == "http":
                            onion_log.append(f"enter {label}")
                        await self.app(scope, receive, send)
                        if scope["type"] == "http":
                            onion_log.append(f"leave {label}")

                Layer.__name__ = f"Layer{label}"
                return Layer


            onion_app = FastAPI()
            for label in ("A", "B", "C"):  # added in this order
                onion_app.add_middleware(logging_middleware(label))
            onion_app.add_api_route("/", lambda: onion_log.append("handler") or {"ok": True})
            with TestClient(onion_app) as client:
                client.get("/")
            print(" → ".join(onion_log))
            '''
        ),
        md(
            """
            `build_middleware_stack()` returns the outermost layer; each layer keeps the next
            one in `.app`. Following that chain shows the real stack, and
            `app.user_middleware` lists your own middleware, outermost first:
            """
        ),
        code(
            r"""
            layer = onion_app.build_middleware_stack()
            stack_names = []
            while layer is not None and len(stack_names) < 12:
                stack_names.append(type(layer).__name__)
                layer = getattr(layer, "app", None)
            print(" → ".join(stack_names))
            print(
                [middleware.cls.__name__ for middleware in onion_app.user_middleware],
                "(app.user_middleware: outermost first)",
            )
            """
        ),
        md(
            """
            Read the chain from the left: the server calls `ServerErrorMiddleware` first,
            then (in this FastAPI version) `ExceptionTelemetryMiddleware`, then your
            middleware in reverse order of adding, then `ExceptionMiddleware`, the router and
            finally the route. Layer names after the router depend on the FastAPI version.

            A sensible order for an API, outermost first: request id (so even errors and CORS
            rejections carry an id) → CORS (so preflight requests are answered early) → GZip
            → timing → the app. The Notes API v2 uses exactly this order.
            """
        ),
    ]


def _cors_cells() -> list[NotebookNode]:
    """6.3.8 CORS."""
    return [
        md(
            """
            ### 6.3.8 CORS

            Browsers apply the **same-origin policy**: JavaScript on `http://localhost:5173`
            (scheme + host + port) may send requests to `http://localhost:8000` but may not
            **read** the responses unless that server opts in with CORS headers.

            | Request kind | When | What the browser does |
            | --- | --- | --- |
            | simple | `GET`/`HEAD`/`POST` with only simple headers and a form or text content type | sends it, then checks `Access-Control-Allow-Origin` before letting the page read the response |
            | preflighted | any other method (`PUT`, `PATCH`, `DELETE`), JSON bodies, custom headers like `X-API-Key` | first sends `OPTIONS` with `Origin`, `Access-Control-Request-Method` and `-Headers`; only if the answer allows it, sends the real request |

            ```mermaid
            sequenceDiagram
              participant Page as Page on :5173
              participant API as API on :8000
              Page->>API: OPTIONS /notes/1  (Origin, Access-Control-Request-Method: PATCH)
              API-->>Page: 200  Access-Control-Allow-Origin / -Methods / -Headers / Max-Age
              Page->>API: PATCH /notes/1  (Origin)
              API-->>Page: 200  Access-Control-Allow-Origin  (+ Expose-Headers)
            ```

            <details><summary>ASCII version</summary>

            ```text
            page :5173                         API :8000
               | OPTIONS + Origin + Request-Method ->|
               |<- 200 + Allow-Origin/Methods/Headers|
               | PATCH + Origin -------------------->|
               |<- 200 + Allow-Origin ---------------|
            ```

            </details>

            `CORSMiddleware` answers preflight requests itself and adds the headers to real
            responses:
            """
        ),
        code(
            r'''
            cors_app = FastAPI()
            cors_app.add_middleware(
                CORSMiddleware,
                allow_origins=["http://localhost:5173"],
                allow_methods=["GET", "POST", "PATCH"],
                allow_headers=["Content-Type", "X-API-Key"],
                expose_headers=["X-Request-ID"],
                max_age=600,
            )


            @cors_app.patch("/items/{item_id}")
            async def patch_item(item_id: int) -> dict[str, int]:
                """A route a browser would preflight."""
                return {"patched": item_id}


            PREFLIGHT = {
                "Access-Control-Request-Method": "PATCH",
                "Access-Control-Request-Headers": "content-type,x-api-key",
            }
            with TestClient(cors_app) as client:
                allowed = client.options("/items/1", headers={"Origin": "http://localhost:5173", **PREFLIGHT})
                print(
                    allowed.status_code,
                    {
                        name: value
                        for name, value in allowed.headers.items()
                        if name.startswith("access-control")
                    },
                )
                refused = client.options("/items/1", headers={"Origin": "https://evil.example", **PREFLIGHT})
                print(refused.status_code, refused.text, "allow-origin" in str(refused.headers))
            '''
        ),
        md(
            """
            On the real request the middleware adds `Access-Control-Allow-Origin` (and
            `Expose-Headers`: without it, page JavaScript cannot read custom response headers
            such as `X-Request-ID`). Two things that surprise people:

            1. **CORS is not access control.** The server still **runs** the request from a
               foreign origin; only the browser refuses to show the response to the page.
               Tools like curl, servers and scripts ignore CORS completely. Protect data with
               authentication (Unit 6.5), not with CORS.
            2. With `allow_credentials=True` (cookies), the browser rejects a literal `*`
               origin; list the origins (or use `allow_origin_regex`).
            """
        ),
        code(
            r'''
            executed: list[int] = []


            @cors_app.post("/items")
            async def create_item(item_id: int) -> dict[str, int]:
                """Records that it ran."""
                executed.append(item_id)
                return {"created": item_id}


            with TestClient(cors_app) as client:
                real = client.patch("/items/1", headers={"Origin": "http://localhost:5173"})
                print(
                    real.headers.get("access-control-allow-origin"),
                    real.headers.get("access-control-expose-headers"),
                )
                foreign = client.post(
                    "/items", params={"item_id": 7}, headers={"Origin": "https://evil.example"}
                )
            print(
                f"{foreign.status_code=}  {executed=}  "
                f"allow-origin header: {foreign.headers.get('access-control-allow-origin')}"
            )
            '''
        ),
        md(
            """
            `allow_origin_regex` matches families of origins (preview deployments, local
            ports); the matching origin is echoed back, never the regex:
            """
        ),
        code(
            r"""
            regex_app = FastAPI()
            regex_app.add_middleware(
                CORSMiddleware,
                allow_origin_regex=r"https://(.+\.)?shop\.example|http://localhost:\d+",
                allow_methods=["*"],
            )
            regex_app.add_api_route("/ping", lambda: {"pong": True})
            with TestClient(regex_app) as client:
                for origin in (
                    "https://pr-42.shop.example",
                    "http://localhost:3000",
                    "https://shop.example.evil.com",
                ):
                    response = client.get("/ping", headers={"Origin": origin})
                    print(f"{origin:32} → {response.headers.get('access-control-allow-origin')}")
            """
        ),
    ]


def _error_cells() -> list[NotebookNode]:
    """6.3.9 Error handling."""
    return [
        md(
            """
            ### 6.3.9 Error handling

            Three kinds of errors reach the edge of an API:

            | Kind | Raised by | Default response |
            | --- | --- | --- |
            | domain errors (`InsufficientStockError`) | your services | **500** unless you register a handler |
            | `HTTPException` | routers, dependencies, Starlette (404/405) | `{"detail": ...}` with its status |
            | `RequestValidationError` | FastAPI, before your handler runs | 422 with a list of problems |

            Services should raise **domain** exceptions (Unit 1.14's `AppError` idea, Unit 2's
            `InventoryError` hierarchy) and stay free of HTTP. One handler per base class maps
            them to responses. Handlers are looked up by the exception's class **MRO**, so a
            handler for the base class catches every subclass:
            """
        ),
        code(
            r'''
            class InventoryError(Exception):
                """Base class of the Phase 2 inventory errors; carries an error code and status."""

                error_code = "inventory_error"
                status_code = 400


            class UnknownProductError(InventoryError, LookupError):
                """No product with this SKU."""

                error_code = "unknown_product"
                status_code = 404


            class InsufficientStockError(InventoryError):
                """Not enough units to fulfil the request."""

                error_code = "insufficient_stock"
                status_code = 409


            STOCK = {"tea": 3}
            inventory_app = FastAPI()


            @inventory_app.exception_handler(InventoryError)
            async def inventory_error_handler(request: Request, error: InventoryError) -> JSONResponse:
                """One handler for the whole hierarchy."""
                return JSONResponse(
                    {"error": error.error_code, "message": str(error)}, status_code=error.status_code
                )
            '''
        ),
        md("`reserve()`: domain code raises domain errors; no HTTPException here:"),
        code(
            r'''
            @inventory_app.post("/reserve/{sku}/{quantity}")
            async def reserve(sku: str, quantity: int) -> dict[str, int]:
                """Domain code raises domain errors; no HTTPException here."""
                if sku not in STOCK:
                    raise UnknownProductError(f"no product {sku!r}")
                if STOCK[sku] < quantity:
                    raise InsufficientStockError(f"only {STOCK[sku]} {sku} left")
                STOCK[sku] -= quantity
                return {"left": STOCK[sku]}


            with TestClient(inventory_app) as client:
                for path in ("/reserve/tea/2", "/reserve/tea/5", "/reserve/rice/1"):
                    show_response(client.post(path))
            '''
        ),
        md(
            """
            **Overriding the validation error format.** The default 422 body echoes the
            client's `input` and uses FastAPI's own shape. Register a handler for
            `RequestValidationError` to change it; here a compact `{field: message}` map, the
            kind of shape a form on a web page can use directly:
            """
        ),
        code(
            r'''
            class Signup(BaseModel):
                """A form body."""

                email: str = Field(pattern=r".+@.+")
                age: int = Field(ge=13)


            form_app = FastAPI()


            @form_app.exception_handler(RequestValidationError)
            async def compact_validation_handler(
                request: Request, error: RequestValidationError
            ) -> JSONResponse:
                """Field name → first message, without echoing the input."""
                fields = {".".join(map(str, problem["loc"][1:])): problem["msg"] for problem in error.errors()}
                return JSONResponse({"invalid_fields": fields}, status_code=422)


            @form_app.post("/signup")
            async def signup_form(signup: Signup) -> dict[str, str]:
                """Accept a valid signup."""
                return {"welcome": signup.email}


            with TestClient(form_app) as client:
                show_response(client.post("/signup", json={"email": "not-an-email", "age": 9}))
            '''
        ),
        md(
            """
            **RFC 9457 Problem Details.** Every API inventing its own error shape is a pain for
            clients. [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) (which replaced RFC
            7807) standardizes one, served as `application/problem+json`:

            | Member | Meaning | Example |
            | --- | --- | --- |
            | `type` | URI identifying the problem type (documentation page); `about:blank` when the status says it all | `/problems/insufficient-stock` |
            | `title` | short, human-readable summary of the **type** (same for every occurrence) | `Insufficient stock` |
            | `status` | the HTTP status code, repeated for convenience | `409` |
            | `detail` | explanation of **this** occurrence | `only 3 tea left` |
            | `instance` | URI of this occurrence (often the request path) | `/reserve/tea/5` |
            | extension members | anything else useful | `request_id`, `errors` (validation problems) |

            The demo turns `HTTPException` (including Starlette's own 404 and 405) into
            problem documents. Lab 6.3 asks you to cover domain and validation errors too:
            """
        ),
        code(
            r'''
            def problem(
                request: Request, status_code: int, detail: str | None, problem_type: str = "about:blank"
            ) -> JSONResponse:
                """An application/problem+json response."""
                body = {
                    "type": problem_type,
                    "title": HTTPStatus(status_code).phrase,
                    "status": status_code,
                    "detail": detail,
                    "instance": request.url.path,
                }
                return JSONResponse(
                    {key: value for key, value in body.items() if value is not None},
                    status_code=status_code,
                    media_type="application/problem+json",
                )


            problem_app = FastAPI()


            @problem_app.exception_handler(StarletteHTTPException)
            async def http_problem_handler(request: Request, error: StarletteHTTPException) -> JSONResponse:
                """HTTPException → Problem Details (keeping its headers, e.g. Allow on a 405)."""
                response = problem(
                    request, error.status_code, error.detail if isinstance(error.detail, str) else None
                )
                response.headers.update(error.headers or {})
                return response


            @problem_app.get("/orders/{order_id}")
            async def find_order(order_id: int) -> dict[str, int]:
                """Only order 1 exists."""
                if order_id != 1:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, f"order {order_id} does not exist")
                return {"order_id": 1}
            '''
        ),
        md("A missing order, a wrong method and an unknown path, all as Problem Details:"),
        code(
            r"""
            with TestClient(problem_app) as client:
                for method, path in [("GET", "/orders/9"), ("POST", "/orders/1"), ("GET", "/nowhere")]:
                    response = client.request(method, path)
                    print(response.status_code, response.headers["content-type"], response.json())
            """
        ),
        md(
            """
            `problem()` gets the title from the standard library: `http.HTTPStatus(404).phrase`
            is `"Not Found"`. *Changed in 3.13*: `422` is now named `UNPROCESSABLE_CONTENT` and
            `413` `CONTENT_TOO_LARGE`, matching RFC 9110 (the old names are aliases):
            """
        ),
        code(
            r"""
            print(HTTPStatus(422).name, HTTPStatus(413).name, HTTPStatus(422).phrase)
            print(f"{HTTPStatus.UNPROCESSABLE_ENTITY is HTTPStatus.UNPROCESSABLE_CONTENT=}")
            """
        ),
        md(
            """
            **Unexpected exceptions.** Anything without a handler reaches
            `ServerErrorMiddleware`: it sends a plain 500 (or, with `FastAPI(debug=True)`, an
            HTML traceback page, which must never be on in production) and re-raises so the
            server logs the traceback. `TestClient` re-raises too, unless you pass
            `raise_server_exceptions=False`. A handler registered for `Exception` lets you
            return a Problem Details 500 without leaking internals:
            """
        ),
        code(
            r'''
            async def divide(number: int) -> dict[str, float]:
                """Crashes on zero."""
                return {"result": 1 / number}


            async def unexpected_handler(request: Request, error: Exception) -> JSONResponse:
                """A generic 500 problem; the details stay in the server log."""
                return problem(request, 500, "unexpected error; quote the request id when reporting it")


            def make_crash_app(with_handler: bool) -> FastAPI:
                """Handlers must be registered before the app starts, so build a fresh app each time."""
                app = FastAPI()
                app.add_api_route("/divide/{number}", divide)
                if with_handler:
                    app.add_exception_handler(Exception, unexpected_handler)
                return app


            with TestClient(make_crash_app(False), raise_server_exceptions=False) as client:
                plain = client.get("/divide/0")
            print(plain.status_code, plain.headers["content-type"], plain.text)
            with TestClient(make_crash_app(True), raise_server_exceptions=False) as client:
                print(client.get("/divide/0").json())
            print(
                f"{raised_error_name(lambda: TestClient(make_crash_app(True)).get('/divide/0'))=}"
                " (TestClient re-raises by default, even after a handler answered)"
            )
            '''
        ),
        md(
            """
            **Under the hood.** Handlers live in a dict keyed by exception class (or status
            code). Starlette's `ExceptionMiddleware` walks the raised exception's MRO and uses
            the first class it finds, which is why one `InventoryError` handler covers
            `InsufficientStockError`:
            """
        ),
        code(
            r"""
            print(
                {
                    getattr(key, "__name__", key): handler.__name__
                    for key, handler in inventory_app.exception_handlers.items()
                }
            )
            print([cls.__name__ for cls in InsufficientStockError.__mro__])
            """
        ),
    ]


def _lifespan_cells() -> list[NotebookNode]:
    """6.3.10 Lifespan."""
    return [
        md(
            """
            ### 6.3.10 Lifespan

            Some objects must exist **once per process**, not once per request: a database
            engine with its connection pool, an HTTP client with keep-alive connections, a
            Redis client. Create them at startup, close them at shutdown. The **lifespan** is
            an async context manager the server enters before serving the first request (the
            ASGI `lifespan.startup` message from Unit 6.1.6) and exits on shutdown:

            | Part | Runs | Typical code |
            | --- | --- | --- |
            | before `yield` | once, before any request | create engine, client, pools; warm caches |
            | `yield` | while the app serves requests | |
            | after `yield` | once, on shutdown (Ctrl+C, SIGTERM) | close clients, dispose engines, flush buffers |

            > **Note:** `TestClient` runs the lifespan only when used as a context manager
            > (`with TestClient(app) as client:`). Without `with`, startup never happens and
            > anything the lifespan creates is missing.
            """
        ),
        code(
            r'''
            lifespan_log: list[str] = []


            @contextlib.asynccontextmanager
            async def logging_lifespan(app: FastAPI) -> AsyncIterator[None]:
                """Record startup and shutdown."""
                lifespan_log.append("startup")
                app.state.started_at = "startup ran"
                yield
                lifespan_log.append("shutdown")


            life_app = FastAPI(lifespan=logging_lifespan)


            @life_app.get("/status")
            async def life_status(request: Request) -> dict[str, str]:
                """Reads what the lifespan stored."""
                return {"state": getattr(request.app.state, "started_at", "startup never ran")}


            print("without with:", TestClient(life_app).get("/status").json(), lifespan_log)
            with TestClient(life_app) as client:
                print("with:", client.get("/status").json(), lifespan_log)
            print("after the with block:", lifespan_log)
            '''
        ),
        md(
            """
            **Shared resources on `app.state`.** A realistic lifespan creates a SQLAlchemy async
            engine (SQLite in memory here; Unit 6.4 uses PostgreSQL), an `httpx.AsyncClient`
            (with a mock transport standing in for a remote API) and a Redis client. A Redis
            client from `redis.asyncio` connects lazily, on the first command, so creating it
            needs no server; Units 6.4 and 6.6 use a real Redis. Dependencies read the objects
            back from `request.app.state`:
            """
        ),
        code(
            r'''
            import redis.asyncio as redis_asyncio
            from sqlalchemy import text
            from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


            def fake_rates_api(request: httpx.Request) -> httpx.Response:
                """Stands in for a remote exchange-rate service."""
                return httpx.Response(200, json={"base": "INR", "USD": 0.012})


            @contextlib.asynccontextmanager
            async def resources_lifespan(app: FastAPI) -> AsyncIterator[None]:
                """Create one engine, one HTTP client and one Redis client; close all three."""
                app.state.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
                app.state.redis = redis_asyncio.from_url("redis://127.0.0.1:6399/0")  # no connection yet
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(fake_rates_api), base_url="https://rates.example"
                ) as client:
                    app.state.http_client = client
                    yield
                await app.state.redis.aclose()
                await app.state.engine.dispose()


            def get_engine(request: Request) -> AsyncEngine:
                """The engine the lifespan created."""
                return request.app.state.engine


            def get_http_client(request: Request) -> httpx.AsyncClient:
                """The HTTP client the lifespan created."""
                return request.app.state.http_client
            '''
        ),
        md(
            """
            Two requests reuse the **same** client object (one connection pool) and the same
            engine; after shutdown the client is closed:
            """
        ),
        code(
            r'''
            resources_app = FastAPI(lifespan=resources_lifespan)
            seen_clients: list[int] = []


            @resources_app.get("/rates")
            async def rates(
                engine: Annotated[AsyncEngine, Depends(get_engine)],
                client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
            ) -> dict[str, object]:
                """Uses both shared resources."""
                seen_clients.append(id(client))
                async with engine.connect() as connection:
                    sqlite_version = (await connection.execute(text("select sqlite_version()"))).scalar_one()
                upstream = (await client.get("/latest")).json()
                return {"usd": upstream["USD"], "sqlite": sqlite_version.split(".")[0] + ".x"}


            with TestClient(resources_app) as client:
                print(client.get("/rates").json(), client.get("/rates").json())
                shared_client = resources_app.state.http_client
            print(f"{len(set(seen_clients))=} (one client for every request)  {shared_client.is_closed=}")
            '''
        ),
        md(
            """
            **Lifespan state.** Instead of `app.state`, the lifespan may `yield` a dict; each
            request then sees a shallow copy as `request.state`. It keeps resources out of the
            global app object and makes it obvious what a request may use:
            """
        ),
        code(
            r'''
            @contextlib.asynccontextmanager
            async def state_lifespan(app: FastAPI) -> AsyncIterator[dict[str, object]]:
                """Yield the shared objects instead of attaching them to app.state."""
                async with httpx.AsyncClient(transport=httpx.MockTransport(fake_rates_api)) as client:
                    yield {"rates_client": client, "region": "south"}


            state_app = FastAPI(lifespan=state_lifespan)


            @state_app.get("/region")
            async def region(request: Request) -> dict[str, object]:
                """Read lifespan state from request.state."""
                return {"region": request.state.region, "client_open": not request.state.rates_client.is_closed}


            with TestClient(state_app) as client:
                print(client.get("/region").json())
            '''
        ),
        md(
            """
            **Failing at startup is a feature.** If the lifespan raises before `yield` (bad
            settings, an unreachable required service), the server refuses to start instead
            of serving broken requests. (The older `@app.on_event("startup")` hooks are
            deprecated; use the lifespan.)
            """
        ),
        code(
            r'''
            @contextlib.asynccontextmanager
            async def failing_lifespan(app: FastAPI) -> AsyncIterator[None]:
                """Refuse to start without a required setting."""
                if not os.environ.get("PAYMENTS_API_URL"):
                    raise RuntimeError("PAYMENTS_API_URL is not set")
                yield


            broken_app = FastAPI(lifespan=failing_lifespan)


            def start_broken_app() -> None:
                """Enter the TestClient, which runs startup."""
                with TestClient(broken_app):
                    pass


            print(raised_message(start_broken_app))
            '''
        ),
    ]


def _request_cells() -> list[NotebookNode]:
    """6.3.11 Requests, headers, cookies, forms and uploads."""
    return [
        md(
            """
            ### 6.3.11 Requests, headers, cookies, forms and uploads

            Most handlers only need typed parameters, but the raw `Request` is always available
            when you need something unusual. Everything a request carries:

            | What | Typed parameter | Raw access |
            | --- | --- | --- |
            | header | `user_agent: Annotated[str \\| None, Header()]` (`_` → `-`) | `request.headers["user-agent"]` |
            | repeated header | `x_tag: Annotated[list[str], Header()]` | `request.headers.getlist("x-tag")` |
            | cookie | `session_id: Annotated[str \\| None, Cookie()]` | `request.cookies` |
            | form field | `title: Annotated[str, Form()]` | `await request.form()` |
            | file | `file: UploadFile` | `(await request.form())["file"]` |
            | body bytes | | `await request.body()`, `request.stream()` |
            | client address | | `request.client.host` |
            """
        ),
        code(
            r'''
            raw_app = FastAPI()


            @raw_app.post("/inspect")
            async def inspect_request(
                request: Request,
                user_agent: Annotated[str | None, Header()] = None,
                x_tag: Annotated[list[str] | None, Header()] = None,
                session_id: Annotated[str | None, Cookie()] = None,
            ) -> dict[str, object]:
                """Typed parameters next to the raw Request."""
                return {
                    "method": request.method,
                    "path": request.url.path,
                    "query": dict(request.query_params),
                    "user_agent": user_agent,
                    "x_tag": x_tag,
                    "session_id": session_id,
                    "body_bytes": len(await request.body()),
                    "client": request.client.host if request.client else None,
                }


            with TestClient(raw_app) as client:
                client.cookies.set("session_id", "abc123")
                headers = [("User-Agent", "notebook/1.0"), ("X-Tag", "red"), ("X-Tag", "blue")]
                print(client.post("/inspect?page=2", headers=headers, content=b"hello").json())
            '''
        ),
        md(
            """
            **Setting cookies.** A `response: Response` parameter lets the handler add headers
            and cookies to whatever it returns. Session cookies should be `HttpOnly` (no
            JavaScript access), `Secure` (HTTPS only), and `SameSite=Lax` or `Strict` (not sent
            on most cross-site requests, the main CSRF defence; more in Unit 6.5):
            """
        ),
        code(
            r'''
            cookie_app = FastAPI()


            @cookie_app.post("/login")
            async def login(response: Response) -> dict[str, str]:
                """Set a session cookie with safe attributes."""
                response.set_cookie(
                    "session_id",
                    secrets.token_urlsafe(16),
                    httponly=True,
                    secure=True,
                    samesite="lax",
                    max_age=3600,
                )
                return {"status": "logged in"}


            @cookie_app.post("/logout")
            async def logout(response: Response) -> dict[str, str]:
                """Expire the cookie."""
                response.delete_cookie("session_id")
                return {"status": "logged out"}


            with TestClient(cookie_app) as client:
                set_cookie = client.post("/login").headers["set-cookie"]
                print(re.sub(r"session_id=[^;]+", "session_id=<random>", set_cookie))
                print(re.sub(r"expires=[^;]+", "expires=<now>", client.post("/logout").headers["set-cookie"]))
            '''
        ),
        md(
            """
            **Forms.** HTML forms send `application/x-www-form-urlencoded` (fields only) or
            `multipart/form-data` (fields and files). `Form()` reads one field; a Pydantic model
            marked `Form()` reads them all and validates them together. Parsing forms needs
            the `python-multipart` package (part of `fastapi[standard]`):
            """
        ),
        code(
            r'''
            class ContactForm(BaseModel):
                """All fields of a contact form."""

                name: str = Field(min_length=1)
                email: str = Field(pattern=r".+@.+")
                newsletter: bool = False


            forms_app = FastAPI()


            @forms_app.post("/search")
            async def search_form(
                query: Annotated[str, Form()], limit: Annotated[int, Form()] = 10
            ) -> dict[str, object]:
                """Individual form fields."""
                return {"query": query, "limit": limit}


            @forms_app.post("/contact")
            async def contact(form: Annotated[ContactForm, Form()]) -> ContactForm:
                """A whole form as one model."""
                return form


            print(f"{importlib.util.find_spec('python_multipart') is not None=}")
            with TestClient(forms_app) as client:
                print(client.post("/search", data={"query": "tea", "limit": "5"}).json())
                print(
                    client.post(
                        "/contact", data={"name": "Asha", "email": "asha@example.com", "newsletter": "on"}
                    ).json()
                )
                print(client.post("/contact", data={"name": "", "email": "nope"}).status_code)
            '''
        ),
        md(
            """
            **`UploadFile`.** A file parameter arrives as an `UploadFile`: `filename` and
            `content_type` (both **client-supplied**, never trust them), `size`, and `file`, a
            `SpooledTemporaryFile` that stays in memory up to 1 MB and then moves to disk. Its
            async methods `read`, `seek` and `close` run in a thread. `list[UploadFile]`
            accepts several files under one field name:
            """
        ),
        code(
            r'''
            upload_app = FastAPI()


            @upload_app.post("/attachments")
            async def attach(files: list[UploadFile], note: Annotated[str, Form()] = "") -> dict[str, object]:
                """Describe every uploaded file."""
                described = []
                for upload in files:
                    head = await upload.read(8)
                    await upload.seek(0)
                    described.append(
                        {
                            "name": upload.filename,
                            "type": upload.content_type,
                            "size": upload.size,
                            "head": head.hex(),
                            "spooled_in": type(upload.file).__name__,
                        }
                    )
                return {"note": note, "files": described}


            with TestClient(upload_app) as client:
                parts = [
                    ("files", ("notes.txt", b"plain text", "text/plain")),
                    ("files", ("fake.pdf", b"not really", "application/pdf")),
                ]
                print(
                    json.dumps(
                        client.post("/attachments", files=parts, data={"note": "two files"}).json(), indent=1
                    )
                )
            '''
        ),
        md(
            """
            **Validating uploads.** Check what the file **is**, not what the client says: read
            its first bytes and compare with known signatures ("magic numbers"). Enforce a size
            limit by reading at most `limit + 1` bytes. Answer `415 Unsupported Media Type` and
            `413 Content Too Large`. The demo accepts PDF documents only (Lab 6.3 does images):
            """
        ),
        code(
            r'''
            MAX_DOCUMENT_BYTES = 1024
            documents_app = FastAPI()


            @documents_app.post("/documents", status_code=status.HTTP_201_CREATED)
            async def upload_document(file: UploadFile) -> dict[str, object]:
                """Accept a small PDF; check the signature and the size, not the headers."""
                content = await file.read(MAX_DOCUMENT_BYTES + 1)
                if len(content) > MAX_DOCUMENT_BYTES:
                    raise HTTPException(
                        status.HTTP_413_CONTENT_TOO_LARGE, f"limit is {MAX_DOCUMENT_BYTES} bytes"
                    )
                if not content.startswith(b"%PDF-"):
                    raise HTTPException(
                        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "only PDF documents are accepted"
                    )
                return {"filename": file.filename, "bytes": len(content)}


            with TestClient(documents_app) as client:
                for name, payload, claimed_type in [
                    ("report.pdf", b"%PDF-1.7 tiny", "application/pdf"),
                    ("evil.pdf", b"MZ\x90\x00 an executable", "application/pdf"),
                    ("huge.pdf", b"%PDF-1.7" + b"0" * 5000, "application/pdf"),
                ]:
                    response = client.post("/documents", files={"file": (name, payload, claimed_type)})
                    print(f"{name:10} → {response.status_code} {response.json()}")
            '''
        ),
        md(
            """
            **Under the hood: the limit comes too late.** By the time the handler runs,
            `python-multipart` has already received and spooled the **whole** body; the
            handler's check only stops you from *keeping* a huge file. To refuse oversized
            uploads before reading them, check at the edge: a reverse proxy
            (`client_max_body_size` in nginx) or a pure ASGI middleware that rejects a large
            `Content-Length` and counts streamed bytes. (`add_middleware` is refused once an
            app has served a request, because the stack is built on first use; wrapping the
            app object by hand works at any time, since middleware is just an ASGI wrapper.)
            """
        ),
        code(
            r'''
            class MaxBodySizeMiddleware:
                """Refuse request bodies over max_bytes before the app reads them."""

                def __init__(self, app: ASGIApp, max_bytes: int) -> None:
                    """Wrap the next app."""
                    self.app = app
                    self.max_bytes = max_bytes

                async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
                    """Check Content-Length, then count chunks as they arrive."""
                    if scope["type"] != "http":
                        await self.app(scope, receive, send)
                        return
                    declared = int(Headers(scope=scope).get("content-length") or 0)
                    if declared > self.max_bytes:
                        await JSONResponse({"detail": "body too large"}, status_code=413)(scope, receive, send)
                        return
                    received = 0

                    async def counting_receive() -> Message:
                        """Pass messages through, failing once the limit is crossed."""
                        nonlocal received
                        message = await receive()
                        received += len(message.get("body", b""))
                        if received > self.max_bytes:
                            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "body too large")
                        return message

                    await self.app(scope, counting_receive, send)


            guarded_documents_app = MaxBodySizeMiddleware(
                documents_app, max_bytes=2048
            )  # middleware is just a wrapper
            with TestClient(guarded_documents_app) as client:
                print(
                    client.post(
                        "/documents", files={"file": ("huge.pdf", b"%PDF-" + b"0" * 5000, "application/pdf")}
                    ).json()
                )
            '''
        ),
    ]


def _pagination_cells() -> list[NotebookNode]:
    """6.3.12 Pagination."""
    return [
        md(
            """
            ### 6.3.12 Pagination

            | | Offset (`?limit=20&offset=40`) | Keyset / cursor (`?limit=20&cursor=...`) |
            | --- | --- | --- |
            | Jump to page 7 | yes | no (only next/previous) |
            | Total count | easy (`COUNT(*)`) | optional, often skipped |
            | Rows inserted or deleted while paging | pages **shift**: duplicates or skipped rows | stable: "the rows after this key" |
            | Cost of a deep page | the database still walks `offset` rows | an index seek, same cost on every page |
            | Sort order | anything | needs a **unique** sort key, e.g. `(created_at, id)` |

            The shifting problem in four lines: read page 1, someone inserts a new row at the
            front, read page 2:
            """
        ),
        code(
            r'''
            feed_items = [f"post-{number}" for number in range(10, 0, -1)]  # newest first


            def offset_page(items: list[str], limit: int, offset: int) -> list[str]:
                """Rows offset .. offset + limit."""
                return items[offset : offset + limit]


            first_page = offset_page(feed_items, limit=3, offset=0)
            feed_items.insert(0, "post-11")  # a new post arrives
            second_page = offset_page(feed_items, limit=3, offset=3)
            print(f"{first_page=}\n{second_page=}  ← post-8 is shown twice")
            '''
        ),
        md(
            """
            Keyset pagination asks for "the rows after the last one I saw", so new rows at the
            front do not move anything. Here the key is the post number (unique and sortable):
            """
        ),
        code(
            r'''
            feed_items = [f"post-{number}" for number in range(10, 0, -1)]


            def keyset_page(items: list[str], limit: int, before_number: int | None) -> list[str]:
                """Up to limit posts older than before_number (all posts when None)."""
                older = [
                    item for item in items if before_number is None or int(item.split("-")[1]) < before_number
                ]
                return older[:limit]


            first_page = keyset_page(feed_items, limit=3, before_number=None)
            feed_items.insert(0, "post-11")
            second_page = keyset_page(feed_items, limit=3, before_number=int(first_page[-1].split("-")[1]))
            print(f"{first_page=}\n{second_page=}  ← continues exactly where page 1 ended")
            '''
        ),
        md(
            """
            **Under the hood: why deep offsets are slow.** On 200 000 rows in SQLite,
            `OFFSET 199000` makes the database produce and throw away 199 000 rows; the
            keyset query seeks straight into the primary-key index. `EXPLAIN QUERY PLAN` shows
            the difference (timings vary):
            """
        ),
        code(
            r"""
            with contextlib.closing(sqlite3.connect(":memory:")) as connection:
                connection.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY, title TEXT)")
                connection.executemany(
                    "INSERT INTO posts (title) VALUES (?)", ((f"post {number}",) for number in range(200_000))
                )
                offset_sql = "SELECT id FROM posts ORDER BY id LIMIT 20 OFFSET 199000"
                keyset_sql = "SELECT id FROM posts WHERE id > 199000 ORDER BY id LIMIT 20"
                for label, sql in [("offset", offset_sql), ("keyset", keyset_sql)]:
                    started = time.perf_counter()
                    for _ in range(20):
                        rows = connection.execute(sql).fetchall()
                    elapsed_ms = (time.perf_counter() - started) / 20 * 1000
                    plan = connection.execute("EXPLAIN QUERY PLAN " + sql).fetchall()[0][-1]
                    print(f"{label}: first id {rows[0][0]}, {elapsed_ms:.2f} ms per query, plan: {plan}")
            """
        ),
        md(
            """
            **A generic `Page[T]`.** Every list endpoint returns the same envelope around a
            different item type, which is what generics are for. Pydantic supports the PEP 695
            syntax `class Page[ItemT](BaseModel)`; FastAPI names each concrete version in
            OpenAPI (`Page_Product_`). A `CursorPage[T]` replaces `total`/`offset` with
            `next_cursor`. Here the cursor is just the last id as text; production cursors are
            **opaque** (for example base64-encoded JSON of the sort key) so clients cannot
            construct or depend on them, and the server must validate them (Lab 6.3, exercise
            6):
            """
        ),
        code(
            r'''
            class Page[ItemT](BaseModel):
                """One page of an offset-paginated list."""

                items: list[ItemT]
                total: int
                limit: int
                offset: int


            class CursorPage[ItemT](BaseModel):
                """One page of a keyset-paginated list."""

                items: list[ItemT]
                next_cursor: str | None


            class Product(BaseModel):
                """A catalogue item."""

                id: int
                name: str


            CATALOGUE = [Product(id=number, name=f"product {number}") for number in range(1, 8)]
            paging_app = FastAPI()


            @paging_app.get("/products", response_model=Page[Product])
            async def product_page(limit: int = 3, offset: int = 0) -> dict[str, object]:
                """Offset pagination."""
                return {
                    "items": CATALOGUE[offset : offset + limit],
                    "total": len(CATALOGUE),
                    "limit": limit,
                    "offset": offset,
                }
            '''
        ),
        md(
            "`product_feed()`: keyset pagination on the id (a plain cursor, to keep the demo short):"
        ),
        code(
            r'''
            @paging_app.get("/products/feed", response_model=CursorPage[Product])
            async def product_feed(limit: int = 3, after: int = 0) -> dict[str, object]:
                """Keyset pagination on the id (a plain cursor, to keep the demo short)."""
                items = [product for product in CATALOGUE if product.id > after][:limit]
                more = bool(items) and items[-1].id < CATALOGUE[-1].id
                return {"items": items, "next_cursor": str(items[-1].id) if more else None}


            with TestClient(paging_app) as client:
                print(client.get("/products", params={"offset": 6}).json())
                cursor, ids = "0", []
                while cursor is not None:
                    feed = client.get("/products/feed", params={"after": cursor}).json()
                    ids.append([item["id"] for item in feed["items"]])
                    cursor = feed["next_cursor"]
                print(
                    ids,
                    sorted(name for name in paging_app.openapi()["components"]["schemas"] if "Page" in name),
                )
            '''
        ),
    ]


def _pages_cells() -> list[NotebookNode]:
    """6.3.13 Server-rendered pages."""
    return [
        md(
            """
            ### 6.3.13 Server-rendered pages

            Not every screen needs a JavaScript framework. FastAPI renders HTML with
            **Jinja2** (`Jinja2Templates`), serves CSS and images with `StaticFiles`, and
            handles forms with the classic **Post/Redirect/Get** pattern. **HTMX** adds small
            interactive updates: attributes like `hx-get` make the browser fetch an HTML
            *fragment* and swap it into the page, with no hand-written JavaScript.

            | Piece | Role |
            | --- | --- |
            | `Jinja2Templates(directory=...)` | loads templates; `TemplateResponse(request, name, context)` renders one |
            | autoescaping | `{{ value }}` escapes `<`, `>`, `&`, quotes: user text cannot inject HTML |
            | `{% extends %}` / `{% block %}` / `{% include %}` | layouts and reusable fragments |
            | `url_for('route_name', ...)` inside templates | links that follow route changes |
            | `app.mount("/static", StaticFiles(directory=...), name="static")` | files served as they are |
            | `RedirectResponse(url, status_code=303)` after a POST | a reload does not submit the form twice |
            | `HX-Request: true` header | HTMX asks for a fragment: return a partial template |

            First the templates (written by the cell into the scratch folder): a layout, the
            page, and a fragment the page includes and HTMX can fetch alone:
            """
        ),
        code(
            r'''
            TEMPLATE_DIR = PHASE6_DIR / "templates_demo"
            STATIC_DIR = PHASE6_DIR / "static_demo"
            for folder in (TEMPLATE_DIR, STATIC_DIR):
                folder.mkdir(exist_ok=True)
            DEMO_TEMPLATES = {
                "layout.html": """<!doctype html>
            <html><head><title>{% block title %}Shop{% endblock %}</title>
            <link rel="stylesheet" href="{{ url_for('static', path='shop.css') }}"></head>
            <body>{% block content %}{% endblock %}</body></html>""",
                "products.html": """{% extends "layout.html" %}
            {% block content %}<h1>Products</h1>
            {% for error in errors %}<p class="error">{{ error }}</p>{% endfor %}
            <form method="post" action="{{ url_for('add_product') }}">
            <input name="name"><button>Add</button></form>
            <input name="q" hx-get="{{ url_for('product_list') }}" hx-target="#list"
                   hx-trigger="input changed delay:300ms">
            <div id="list">{% include "_product_list.html" %}</div>{% endblock %}""",
                "_product_list.html": """<ul>{% for name in names %}<li>{{ name }}</li>{% else %}<li>none</li>
                {%- endfor %}</ul>""",
            }
            for name, source in DEMO_TEMPLATES.items():
                (TEMPLATE_DIR / name).write_text(source + "\n", encoding="utf-8")
            (STATIC_DIR / "shop.css").write_text("body { font-family: sans-serif; }\n", encoding="utf-8")
            print(sorted(path.name for path in TEMPLATE_DIR.iterdir()))
            '''
        ),
        md(
            """
            The app: a page, a form handler that redirects with **303 See Other** (the browser
            then GETs the page), an invalid form shown again with a 422, a fragment route for
            HTMX, and the static mount. User input is escaped automatically:
            """
        ),
        code(
            r'''
            templates = Jinja2Templates(directory=TEMPLATE_DIR)
            product_names = ["Assam tea", "Basmati rice"]
            html_app = FastAPI()
            html_app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


            @html_app.get("/", response_class=HTMLResponse)
            async def product_page_html(request: Request) -> HTMLResponse:
                """The full page."""
                return templates.TemplateResponse(
                    request, "products.html", {"names": product_names, "errors": []}
                )


            @html_app.get("/list", response_class=HTMLResponse)
            async def product_list(request: Request, q: str = "") -> HTMLResponse:
                """The fragment HTMX swaps into #list."""
                matching = [name for name in product_names if q.casefold() in name.casefold()]
                return templates.TemplateResponse(request, "_product_list.html", {"names": matching})


            @html_app.post("/", response_class=HTMLResponse)
            async def add_product(request: Request, name: Annotated[str, Form()] = "") -> Response:
                """Post/Redirect/Get: add, then send the browser back to the page."""
                if not name.strip():
                    context = {"names": product_names, "errors": ["name is required"]}
                    return templates.TemplateResponse(request, "products.html", context, status_code=422)
                product_names.append(name.strip())
                return RedirectResponse(
                    request.url_for("product_page_html"), status_code=status.HTTP_303_SEE_OTHER
                )
            '''
        ),
        md(
            """
            A browser session, step by step (TestClient follows redirects like a browser,
            unless told not to):
            """
        ),
        code(
            r"""
            with TestClient(html_app) as client:
                page = client.get("/")
                print(
                    page.headers["content-type"],
                    "<link" in page.text,
                    client.get("/static/shop.css").status_code,
                )
                posted = client.post("/", data={"name": "<script>alert(1)</script>"}, follow_redirects=False)
                print(posted.status_code, posted.headers["location"])
                print(
                    "escaped:",
                    "&lt;script&gt;" in client.get("/").text,
                    " raw tag present:",
                    "<script>alert" in client.get("/").text,
                )
                print("invalid form:", client.post("/", data={"name": "  "}).status_code)
                print(
                    "HTMX fragment:",
                    client.get("/list", params={"q": "ric"}, headers={"HX-Request": "true"}).text,
                )
            """
        ),
        md(
            """
            > **Note:** a page with forms that change data also needs CSRF protection (a token
            > in the form, or `SameSite` cookies plus checking `Origin`); Unit 6.5 covers it.

            **When to choose something else**

            | Choose | When | Python tool |
            | --- | --- | --- |
            | FastAPI + Jinja2/HTMX | an API first, plus a few server-rendered pages | this unit |
            | **Django + Django REST Framework** | a database-heavy product with many models, an admin back office, users and permissions out of the box, server-rendered pages everywhere | `django`, `djangorestframework` |
            | **GraphQL** | many client types needing different slices of a rich object graph; one endpoint, client-chosen fields | `strawberry-graphql` (works inside FastAPI) |
            | plain REST (FastAPI) | resource-shaped data, caching by URL, simple clients | this phase |

            Django gives you an ORM, migrations, an admin UI, auth and forms in one package, at
            the price of its own conventions (and a sync-first core). GraphQL moves the
            "which fields" decision to the client and needs extra care with N+1 queries
            (dataloaders) and caching. Neither package is a course dependency, so the cell
            only checks for them and shows what the same endpoint looks like:
            """
        ),
        code(
            r"""
            ALTERNATIVES = {
                "django": "path('products/', ProductList.as_view())  # DRF generic view + ModelSerializer",
                "rest_framework": "class ProductSerializer(serializers.ModelSerializer): ...",
                "strawberry": "@strawberry.type class Query: products: list[Product] = strawberry.field(...)",
            }
            for package, example in ALTERNATIVES.items():
                if importlib.util.find_spec(package) is None:
                    print(f"SKIP {package}: not installed (not a course dependency). Shape: {example}")
                else:
                    print(f"{package} is installed: {example}")
            """
        ),
    ]


def _predict_cells() -> list[NotebookNode]:
    """Three predict-the-output questions for Unit 6.3."""
    return [
        md(
            """
            ### Predict the output — Unit 6.3

            Three short questions about what you just saw. Decide on your answer before
            opening it.
            """
        ),
        *predict_cells(
            """
            calls = []

            def get_user() -> str:
                calls.append("user")
                return "asha"

            def get_permissions(user: Annotated[str, Depends(get_user)]) -> list[str]:
                calls.append("permissions")
                return [f"{user}:read"]

            @app.get("/")
            def home(user: Annotated[str, Depends(get_user)],
                     permissions: Annotated[list[str], Depends(get_permissions)]) -> dict:
                return {"user": user}

            client.get("/"); client.get("/")
            print(calls)
            """,
            """
            `['user', 'permissions', 'user', 'permissions']`. Within one request `get_user`
            is needed twice (by the handler and by `get_permissions`) but called **once**:
            dependencies are cached per request. The second request starts with an empty
            cache, so everything runs again.
            """,
            r'''
            predict_calls: list[str] = []


            def predict_get_user() -> str:
                """Counted dependency."""
                predict_calls.append("user")
                return "asha"


            def predict_get_permissions(user: Annotated[str, Depends(predict_get_user)]) -> list[str]:
                """Depends on the user."""
                predict_calls.append("permissions")
                return [f"{user}:read"]


            predict_app = FastAPI()


            @predict_app.get("/")
            def predict_home(
                user: Annotated[str, Depends(predict_get_user)],
                permissions: Annotated[list[str], Depends(predict_get_permissions)],
            ) -> dict[str, str]:
                """Uses both."""
                return {"user": user}


            with TestClient(predict_app) as client:
                client.get("/")
                client.get("/")
            print(predict_calls)
            ''',
        ),
        *predict_cells(
            """
            def header_layer(value: str) -> type:
                class Layer:                       # pure ASGI middleware
                    def __init__(self, app): self.app = app
                    async def __call__(self, scope, receive, send):
                        async def send_wrapper(message):
                            if message["type"] == "http.response.start":
                                MutableHeaders(scope=message)["X-Layer"] = value
                            await send(message)
                        await self.app(scope, receive, send_wrapper)
                return Layer

            app.add_middleware(header_layer("A"))
            app.add_middleware(header_layer("B"))
            print(client.get("/").headers["X-Layer"])
            """,
            """
            `B`. `B` was added last, so it is the **outer** layer. On the way out the response
            start message passes through `A`'s `send_wrapper` first (it sets `A`), then through
            `B`'s, which overwrites the header with `B`. The outermost middleware has the last
            word on the response.
            """,
            r'''
            def header_layer(value: str) -> type:
                """A pure ASGI middleware class that sets X-Layer to value."""

                class Layer:
                    """Sets one header on the way out."""

                    def __init__(self, app: ASGIApp) -> None:
                        """Wrap the next app."""
                        self.app = app

                    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
                        """Overwrite X-Layer on the response start message."""

                        async def send_wrapper(message: Message) -> None:
                            """Edit the headers, then pass the message on."""
                            if message["type"] == "http.response.start":
                                MutableHeaders(scope=message)["X-Layer"] = value
                            await send(message)

                        await self.app(scope, receive, send_wrapper)

                return Layer


            layered_headers_app = FastAPI()
            layered_headers_app.add_api_route("/", lambda: {"ok": True})
            layered_headers_app.add_middleware(header_layer("A"))
            layered_headers_app.add_middleware(header_layer("B"))
            with TestClient(layered_headers_app) as client:
                print(client.get("/").headers["X-Layer"])
            ''',
        ),
        *predict_cells(
            """
            def get_settings() -> str:
                return "production settings"

            SettingsDep = Annotated[str, Depends(get_settings)]

            @app.get("/which")
            def which(settings: SettingsDep) -> dict:
                return {"settings": settings}

            app.dependency_overrides[SettingsDep] = lambda: "test settings"     # (1)
            print(client.get("/which").json())
            app.dependency_overrides = {get_settings: lambda: "test settings"}  # (2)
            print(client.get("/which").json())
            """,
            """
            `{'settings': 'production settings'}` then `{'settings': 'test settings'}`.
            Overrides are looked up by the **dependency callable** (`get_settings`), not by the
            `Annotated` alias, so line (1) adds a key FastAPI never asks for. Line (2) uses
            the function as the key and works.
            """,
            r'''
            def predict_get_settings() -> str:
                """The real dependency."""
                return "production settings"


            PredictSettingsDep = Annotated[str, Depends(predict_get_settings)]
            override_app = FastAPI()


            @override_app.get("/which")
            def which(settings: PredictSettingsDep) -> dict[str, str]:
                """Report the injected settings."""
                return {"settings": settings}


            with TestClient(override_app) as client:
                override_app.dependency_overrides[PredictSettingsDep] = lambda: "test settings"
                print(client.get("/which").json())
                override_app.dependency_overrides = {predict_get_settings: lambda: "test settings"}
                print(client.get("/which").json())
            ''',
        ),
    ]


def _lab_setup_cells() -> list[NotebookNode]:
    """Lab 6.3 introduction and setup."""
    return [
        md(
            """
            ### Lab 6.3

            Six exercises, one per syllabus item. Each builds a small app in the notebook; the
            *Notes API v2* section after the lab shows how the same ideas fit together in the
            real project. Replace each `raise NotImplementedError`, then run the check cell
            below it. Until then the checks print FAIL; that is expected.

            | Exercise | Syllabus item | You write |
            | --- | --- | --- |
            | 1 | Notes API v2: layered structure and settings | `LabSettings`, `get_lab_settings`, `get_lab_store`, `create_lab_app` |
            | 2 | A router-level API key | `build_admin_app(api_key)` |
            | 3 | Request-ID and timing middleware | `LabRequestIdMiddleware`, `LabTimingMiddleware` |
            | 4 | Problem Details errors | `install_problem_handlers(app)` |
            | 5 | A lifespan-managed HTTP client | `build_weather_app(transport)` |
            | 6 | Uploads and cursor pagination | `build_avatar_app`, `encode_event_cursor`, `decode_event_cursor`, `build_events_app` |

            Run the setup cell first. It defines what the exercises are given: a note store,
            a fake clock (`ManualClock`, as in Lab 6.1), a context variable for request ids,
            and a small library app with domain errors:
            """
        ),
        code(
            r'''
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


            class ManualClock:
                """A clock that returns the given readings in order (as in Lab 6.1)."""

                def __init__(self, *readings: float) -> None:
                    """Store the readings to hand out."""
                    self.readings = list(readings)

                def __call__(self) -> float:
                    """Return the next reading."""
                    return self.readings.pop(0)


            lab_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
                "lab_request_id", default=None
            )
            print(f"{ManualClock(1.0, 2.5)()=}  {lab_request_id.get()=}")
            '''
        ),
        md("The library app for exercise 4 (its routes raise every kind of error):"),
        code(
            r'''
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
            '''
        ),
        md(
            "`build_library_app()`: routes that raise a domain error, an HTTPException and validation errors:"
        ),
        code(
            r'''
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
            '''
        ),
    ]


def _lab_exercise_1_2_cells() -> list[NotebookNode]:
    """Lab 6.3 exercises 1-2."""
    return [
        md(
            """
            #### Exercise 1 — Notes API v2: layered structure and settings

            Write:

            - `LabSettings(BaseSettings)`: environment prefix `LAB_NOTES_`; fields `app_name`
              (default `"Lab Notes"`), `api_key` (a **required** `SecretStr`), `page_size`
              (default 20, between 1 and 100), `cors_origins` (`list[str]`, default empty).
            - `get_lab_settings()`: returns `LabSettings()`, cached with `@lru_cache`.
            - `get_lab_store(request)`: a dependency returning the store the lifespan put on
              `app.state.store`.
            - `create_lab_app(settings) -> FastAPI`: an app titled `settings.app_name`, with the
              settings on `app.state.settings`; a lifespan that creates a fresh `LabNoteStore`;
              `GET /health` → `{"status": "ok"}`; and an `APIRouter` with prefix
              `/api/v1/notes` and tag `notes`: `POST ""` (body `LabNoteIn`, 201, returns the
              stored note) and `GET ""` (the newest `settings.page_size` notes). Both routes get
              the store through `Depends(get_lab_store)`.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            class LabSettings(BaseSettings):
                """Settings for the lab Notes API (see the exercise text)."""

                @pydantic.model_validator(mode="before")
                @classmethod
                def not_written_yet(cls, data: object) -> object:
                    """Placeholder: delete it when you add the configuration and fields."""
                    raise NotImplementedError


            @lru_cache
            def get_lab_settings() -> LabSettings:
                """The settings, read once per process."""
                raise NotImplementedError


            def get_lab_store(request: fastapi.Request) -> LabNoteStore:
                """The store the lifespan created."""
                raise NotImplementedError


            def create_lab_app(settings: LabSettings) -> FastAPI:
                """A layered app with its own store (see the exercise text)."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 1. First the helpers the checks use:"),
        code(
            r'''
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
            '''
        ),
        md("The checks:"),
        code(
            r'''
            def cached_settings_are_shared() -> bool:
                """get_lab_settings returns the same object twice."""
                with temporary_env(LAB_NOTES_API_KEY="cached-key"):
                    get_lab_settings.cache_clear()
                    shared = get_lab_settings() is get_lab_settings()
                get_lab_settings.cache_clear()
                return shared
            '''
        ),
        md("The checks:"),
        code(
            r"""
            run_checks(
                [
                    (
                        "env variables are parsed",
                        lambda: lab_settings_from_env(
                            LAB_NOTES_API_KEY="k",
                            LAB_NOTES_PAGE_SIZE="5",
                            LAB_NOTES_CORS_ORIGINS='["http://localhost:5173"]',
                        ),
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
                        lambda: "lab-secret-123" in repr(LabSettings(_env_file=None, api_key="lab-secret-123")),
                        False,
                    ),
                    ("get_lab_settings is cached", cached_settings_are_shared, True),
                    ("POST returns 201", lambda: lab_app_scenario(20)["statuses"], [201, 201, 201]),
                    (
                        "GET lists newest first",
                        lambda: lab_app_scenario(20)["first"],
                        ["Note 2", "Note 1", "Note 0"],
                    ),
                    ("page_size limits the list", lambda: lab_app_scenario(2)["first"], ["Note 2", "Note 1"]),
                ]
            )
            """
        ),
        md("More checks:"),
        code(
            r"""
            run_checks(
                [
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
            """
        ),
        md(
            """
            #### Exercise 2 — a router-level API key

            Write `build_admin_app(api_key) -> FastAPI` with:

            - `GET /health` → `{"status": "ok"}`, open to everybody;
            - an `APIRouter(prefix="/admin", tags=["admin"], dependencies=[...])` whose
              dependency checks the `X-API-Key` header for **every** route in it:
              missing → **401** `{"detail": "missing API key"}`; wrong → **403**
              `{"detail": "invalid API key"}` (compare with `secrets.compare_digest`);
            - `GET /admin/stats` → `{"notes": 0}` and `DELETE /admin/cache` → `{"cleared": True}`.

            Read the header with `APIKeyHeader(name="X-API-Key", auto_error=False)` so that
            `/docs` shows an *Authorize* button for the admin routes only.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            def build_admin_app(api_key: str) -> FastAPI:
                """Public /health plus an /admin router guarded by an X-API-Key dependency."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 2:"),
        code(
            r'''
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
            '''
        ),
        md("The checks:"),
        code(
            r"""
            run_checks(
                [
                    (
                        "no key",
                        lambda: admin_statuses({}),
                        [
                            (200, {"status": "ok"}),
                            (401, {"detail": "missing API key"}),
                            (401, {"detail": "missing API key"}),
                        ],
                    ),
                    (
                        "wrong key",
                        lambda: admin_statuses({"X-API-Key": "guess"}),
                        [
                            (200, {"status": "ok"}),
                            (403, {"detail": "invalid API key"}),
                            (403, {"detail": "invalid API key"}),
                        ],
                    ),
                    (
                        "right key",
                        lambda: admin_statuses({"X-API-Key": "s3cret-admin-key"}),
                        [(200, {"status": "ok"}), (200, {"notes": 0}), (200, {"cleared": True})],
                    ),
                    (
                        "OpenAPI: an apiKey header scheme on admin routes only",
                        admin_security,
                        ([("apiKey", "header", "X-API-Key")], True, False),
                    ),
                ]
            )
            """
        ),
    ]


def _lab_exercise_3_4_cells() -> list[NotebookNode]:
    """Lab 6.3 exercises 3-4."""
    return [
        md(
            """
            #### Exercise 3 — request-ID and timing middleware

            Write two **pure ASGI** middleware classes (not `BaseHTTPMiddleware`); both pass
            non-HTTP scopes (lifespan, websocket) straight through.

            - `LabRequestIdMiddleware(app)`: if the request has an `X-Request-ID` matching
              `[A-Za-z0-9-]{1,64}`, use it, otherwise use `uuid.uuid4().hex`. Set
              `lab_request_id` (from the setup cell) for the duration of the request and
              **reset** it afterwards; add the id as the `X-Request-ID` response header.
            - `LabTimingMiddleware(app, clock=time.perf_counter)`: read the clock when the
              request arrives and again when the response starts; add
              `Server-Timing: app;dur=<milliseconds with one decimal>`.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            class LabRequestIdMiddleware:
                """Pure ASGI request-id middleware (see the exercise text)."""

                def __init__(self, app: ASGIApp) -> None:
                    """Wrap the next app."""
                    raise NotImplementedError

                async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
                    """Handle one connection scope."""
                    raise NotImplementedError


            class LabTimingMiddleware:
                """Pure ASGI Server-Timing middleware (see the exercise text)."""

                def __init__(self, app: ASGIApp, clock: Callable[[], float] = time.perf_counter) -> None:
                    """Wrap the next app; clock is injectable."""
                    raise NotImplementedError

                async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
                    """Handle one connection scope."""
                    raise NotImplementedError
            '''
        ),
        md("Check exercise 3:"),
        code(
            r'''
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
                except Exception as error:  # a check cell must never stop Run All
                    return f"raised {type(error).__name__}"
                return lab_request_id.get()


            reset_probe = await lab_reset_probe()
            '''
        ),
        md("The checks:"),
        code(
            r"""
            run_checks(
                [
                    (
                        "a new id is 32 hex digits",
                        lambda: bool(re.fullmatch(r"[0-9a-f]{32}", lab_middleware_call({})["header"] or "")),
                        True,
                    ),
                    (
                        "the endpoint sees the same id",
                        lambda: (lambda result: result["seen"] == result["header"])(lab_middleware_call({})),
                        True,
                    ),
                    (
                        "a valid incoming id is kept",
                        lambda: lab_middleware_call({"X-Request-ID": "order-42"})["header"],
                        "order-42",
                    ),
                    (
                        "an invalid incoming id is replaced",
                        lambda: lab_middleware_call({"X-Request-ID": "bad id;drop"})["header"] != "bad id;drop",
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
            """
        ),
        md(
            """
            #### Exercise 4 — Problem Details errors

            Write `install_problem_handlers(app)` so that **every** error of
            `build_library_app()` is an `application/problem+json` response:

            - `LoanError` and subclasses: `type` `/problems/<problem_type>`, `title` from the
              class, `status` from the class, `detail` = `str(error)`, `instance` = the
              request path.
            - `HTTPException` (yours and Starlette's 404/405): `type` `about:blank`, `title` =
              `HTTPStatus(status).phrase`, `detail` = the exception's detail, `instance`; keep
              the exception's headers.
            - `RequestValidationError`: 422, `type` `/problems/validation-error`, `title`
              `Invalid request`, `detail` `"<N> validation error(s)"`, `instance`, and
              `errors`: a list of `{"loc": [...], "msg": ..., "type": ...}` (no `input`).
            """
        ),
        md("Your solution:"),
        code(
            r'''
            def install_problem_handlers(app: FastAPI) -> None:
                """Register Problem Details handlers on app (see the exercise text)."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 4:"),
        code(
            r'''
            def library_problem(method: str, path: str, **request_options: object) -> tuple[object, ...]:
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


            PROBLEM = "application/problem+json"
            '''
        ),
        md("The checks:"),
        code(
            r"""
            run_checks(
                [
                    (
                        "domain 404",
                        lambda: library_problem("GET", "/books/7"),
                        (
                            404,
                            PROBLEM,
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
                        "HTTPException body",
                        lambda: library_problem("GET", "/teapot"),
                        (
                            418,
                            PROBLEM,
                            {
                                "type": "about:blank",
                                "title": "I'm a Teapot",
                                "status": 418,
                                "detail": "I refuse to brew coffee",
                                "instance": "/teapot",
                            },
                        ),
                    ),
                    ("unknown route", lambda: library_problem("GET", "/nowhere")[:2], (404, PROBLEM)),
                    (
                        "wrong method",
                        lambda: library_problem("DELETE", "/books/1")[2]["title"],
                        "Method Not Allowed",
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
                        "validation problem",
                        lambda: library_problem("POST", "/members", json={"name": "", "age": -1})[2],
                        {
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
                        },
                    ),
                    (
                        "a valid request still works",
                        lambda: library_problem("POST", "/members", json={"name": "Ravi", "age": 30})[2],
                        {"name": "Ravi", "age": 30},
                    ),
                ]
            )
            """
        ),
    ]


def _lab_exercise_5_6_cells() -> list[NotebookNode]:
    """Lab 6.3 exercises 5-6."""
    return [
        md(
            """
            #### Exercise 5 — a lifespan-managed HTTP client

            Write `build_weather_app(transport) -> FastAPI`. Its lifespan creates **one**
            `httpx.AsyncClient(base_url="https://weather.example", transport=transport,
            timeout=2.0)`, stores it as `app.state.weather_client`, and closes it on shutdown.
            `GET /forecast/{city}` calls the upstream `GET /v1/forecast?city=<city>` with that
            client:

            | Upstream answer | Your response |
            | --- | --- |
            | 200 `{"city": ..., "temp_c": ..., "summary": ...}` | 200 `{"city": ..., "temperature": temp_c, "summary": ...}` |
            | 404 | 404 `{"detail": "unknown city <city>"}` |
            | any 5xx | 502 `{"detail": "weather service failed"}` |
            | `httpx.TimeoutException` | 504 `{"detail": "weather service timed out"}` |

            The checks pass an `httpx.MockTransport`, so nothing leaves the notebook.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            def build_weather_app(transport: httpx.AsyncBaseTransport) -> FastAPI:
                """An app whose lifespan owns one upstream HTTP client (see the exercise text)."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 5:"),
        code(
            r'''
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
                    results = {
                        city: (lambda response: (response.status_code, response.json()))(
                            client.get(f"/forecast/{city}")
                        )
                        for city in ("pune", "atlantis", "crash", "slow")
                    }
                    same_client = app.state.weather_client is first_client
                return {
                    "results": results,
                    "received": received[0],
                    "same client": same_client,
                    "closed after shutdown": first_client.is_closed,
                    "base url": str(first_client.base_url),
                }
            '''
        ),
        md("The checks:"),
        code(
            r"""
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
            """
        ),
        md(
            """
            #### Exercise 6 — uploads and cursor pagination

            **Uploads.** `build_avatar_app(max_bytes) -> FastAPI` with `POST /avatars` taking
            `file: UploadFile`. Read at most `max_bytes + 1` bytes. Too large → **413**
            `{"detail": "avatar larger than <max_bytes> bytes"}`. Decide the kind from the
            **content**, not the headers: PNG files start with `b"\\x89PNG\\r\\n\\x1a\\n"`, JPEG
            files with `b"\\xff\\xd8\\xff"`; anything else → **415**
            `{"detail": "only PNG or JPEG images"}`. Success → **201**
            `{"filename": ..., "kind": "png" | "jpeg", "bytes": <size>}`.

            **Cursor pagination.** Events are dicts `{"id": int, "at": "<ISO time>", "name":
            str}`. `encode_event_cursor(at, event_id)` returns an **opaque** cursor: URL-safe
            base64 (padding stripped) of the JSON list `[at, event_id]`;
            `decode_event_cursor(cursor)` reverses it and raises `ValueError` for anything that
            is not a valid cursor. `build_events_app(events) -> FastAPI` serves
            `GET /events?limit=10&cursor=...` (limit 1–50): events **newest first** by
            `(at, id)`, only those strictly older than the cursor's key, as
            `{"items": [...], "next_cursor": <cursor of the last item, or None on the last
            page>}`. A bad cursor → **400** `{"detail": "invalid cursor"}`. The app must read
            the `events` list on every request (so events added later appear).
            """
        ),
        md("Your solution:"),
        code(
            r'''
            def build_avatar_app(max_bytes: int) -> FastAPI:
                """POST /avatars with size and content checks (see the exercise text)."""
                raise NotImplementedError


            def encode_event_cursor(at: str, event_id: int) -> str:
                """Opaque cursor for the key (at, event_id)."""
                raise NotImplementedError


            def decode_event_cursor(cursor: str) -> tuple[str, int]:
                """The key inside a cursor, or ValueError."""
                raise NotImplementedError


            def build_events_app(events: list[dict[str, object]]) -> FastAPI:
                """GET /events with keyset pagination (see the exercise text)."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 6:"),
        code(
            r'''
            PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
            JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 20


            def avatar_upload(name: str, content: bytes, claimed_type: str) -> tuple[int, object]:
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
                pages, params = [], {"limit": limit}
                with TestClient(build_events_app(events)) as client:
                    while True:
                        page = client.get("/events", params=params).json()
                        pages.append([event["id"] for event in page["items"]])
                        if add_between and len(pages) == 1:
                            events.append({"id": 99, "at": "2026-11-17T10:00:00Z", "name": "late"})
                        if page["next_cursor"] is None:
                            return pages
                        params = {"limit": limit, "cursor": page["next_cursor"]}
            '''
        ),
        md("The checks:"),
        code(
            r'''
            def bad_cursor_response() -> tuple[int, object]:
                """Status and body for a cursor the app never issued."""
                with TestClient(build_events_app(lab_events())) as client:
                    response = client.get("/events", params={"cursor": "definitely-not-a-cursor"})
                return response.status_code, response.json()
            '''
        ),
        md("The checks:"),
        code(
            r"""
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
                        lambda: decode_event_cursor(encode_event_cursor("2026-11-17T09:05:00Z", 3)),
                        ("2026-11-17T09:05:00Z", 3),
                    ),
                    (
                        "cursor is opaque",
                        lambda: (
                            "2026" in encode_event_cursor("2026-11-17T09:05:00Z", 3)
                            or "=" in encode_event_cursor("2026-11-17T09:05:00Z", 3)
                        ),
                        False,
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
            """
        ),
    ]


NOTES_V2_PYPROJECT_TOML = r"""
%%writefile ../projects/notes_api/pyproject.toml
[project]
name = "notes-api"
version = "0.2.0"
description = "The Phase 6 Notes API: a FastAPI service built step by step from Unit 6.2 to 6.8."
readme = "README.md"
requires-python = ">=3.15"
dependencies = [
    "fastapi[standard]>=0.163.1",
    "pydantic-settings>=2.16.2",
]

[dependency-groups]
dev = [
    "pytest>=9.2.0",
    "respx>=0.23.1",
]

[build-system]
requires = ["uv_build>=0.13,<0.14"]
build-backend = "uv_build"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
addopts = "-q"
"""

NOTES_V2_RUFF_TOML = r"""
%%writefile ../projects/notes_api/ruff.toml
# Extends the course configuration; notes_api (src/) and the tests are first-party imports.
extend = "../../pyproject.toml"
src = ["src", "tests"]
"""

NOTES_V2_ENV_EXAMPLE = r"""
%%writefile ../projects/notes_api/.env.example
# Copy this file to .env and fill in real values. .env is git-ignored: never commit secrets.
# Every variable starts with NOTES_ (see src/notes_api/core/config.py).
NOTES_ENVIRONMENT=development
NOTES_DEBUG=false
# Generate a key with: python -c "import secrets; print(secrets.token_urlsafe(32))"
NOTES_API_KEY=change-me
# A JSON list of browser origins allowed by CORS.
NOTES_CORS_ORIGINS=["http://localhost:5173"]
NOTES_MAX_UPLOAD_BYTES=1048576
NOTES_HTTP_TIMEOUT_SECONDS=5
"""

NOTES_V2_README_MD = r"""
%%writefile ../projects/notes_api/README.md
# Notes API

A FastAPI service for creating, searching and organizing notes. It is built step by step in
Phase 6 of the course (`notebooks/phase6_web_fastapi.ipynb`); the notebook writes these files.

| Version | Unit | Adds |
| --- | --- | --- |
| v1 | 6.2 | CRUD path operations, Pydantic v2 schemas, filtering and pagination, OpenAPI |
| v2 | 6.3 | `create_app()` factory, routers under `/api/v1`, settings, dependency injection, middleware, CORS, Problem Details errors, lifespan HTTP client, uploads, cursor pagination, HTML pages |

## Run

```bash
cd projects/notes_api
cp .env.example .env                          # then put a real NOTES_API_KEY in .env
uv run uvicorn notes_api.main:app --reload    # http://127.0.0.1:8000/ and /docs
uv run pytest
```


## Endpoints

| Method | Path | Success | Notes |
| --- | --- | --- | --- |
| `GET` | `/health` | 200 | liveness probe |
| `POST` | `/api/v1/notes` | 201 | `Location` header; body `NoteCreate` |
| `GET` | `/api/v1/notes` | 200 | `q`, `tag` (repeatable), `pinned`, `sort`, `limit` (1-100), `offset` → `Page[NoteRead]` |
| `GET` | `/api/v1/notes/feed` | 200 | newest first; `limit`, `cursor` → `CursorPage[NoteRead]` |
| `GET` | `/api/v1/notes/{note_id}` | 200 | 404 problem if unknown |
| `PUT` | `/api/v1/notes/{note_id}` | 200 | replaces every field |
| `PATCH` | `/api/v1/notes/{note_id}` | 200 | only the fields sent; explicit `null` is rejected |
| `DELETE` | `/api/v1/notes/{note_id}` | 204 | |
| `GET` | `/api/v1/notes/{note_id}/links` | 200 | titles of the links in the body |
| `POST` | `/api/v1/admin/import` | 201 | `X-API-Key`; multipart `.json` / `.csv` file |
| `GET` | `/api/v1/admin/export` | 200 | `X-API-Key`; JSON download |
| `DELETE` | `/api/v1/admin/notes` | 200 | `X-API-Key`; removes every note |
| `GET` | `/` | 200 | HTML page (Jinja2 + HTMX); `POST /notes` form, `POST /notes/{id}/pin` |

Errors are `application/problem+json` (RFC 9457) with `type`, `title`, `status`, `detail`,
`instance` and `request_id`. Every response carries `X-Request-ID` and `Server-Timing`.


## Layout

```text
src/notes_api/
├── main.py           # create_app(): settings, handlers, middleware, lifespan, routers
├── core/             # config.py, errors.py, middleware.py, lifespan.py
├── routers/          # health.py, notes.py, admin.py, pages.py  (HTTP only)
├── dependencies.py   # Annotated aliases: NoteServiceDep, SettingsDep, ApiKeyDep, ...
├── services.py       # NoteService, parse_import, LinkPreviewer  (business logic)
├── repositories.py   # NoteRepository Protocol + InMemoryNoteRepository (storage)
├── models.py         # Note (domain record)
├── exceptions.py     # DomainError and subclasses (no FastAPI)
├── schemas.py        # Pydantic request/response models
├── pagination.py     # Page[T], CursorPage[T], cursors
├── templates/        # Jinja2 templates
└── static/           # CSS
tests/                # pytest + TestClient, one app per test (create_app)
```

Dependencies point inwards: routers → services → repositories → models. Nothing in
`services.py`, `repositories.py`, `models.py` or `exceptions.py` imports FastAPI;
`core/errors.py` maps domain exceptions to HTTP responses.
"""

NOTES_V2_CORE_CONFIG_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/core/config.py
"""Application settings: environment variables (prefix NOTES_) and an optional .env file."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_KEYS = {"", "change-me"}


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
    api_key: SecretStr | None = None  # the admin router answers 503 until it is set
    cors_origins: list[str] = ["http://localhost:5173"]
    max_upload_bytes: int = Field(default=1_048_576, gt=0)
    http_timeout_seconds: float = Field(default=5.0, gt=0)

    @model_validator(mode="after")
    def require_real_key_in_production(self) -> Settings:
        """Refuse to start in production without a real API key."""
        key = None if self.api_key is None else self.api_key.get_secret_value()
        if self.environment == "production" and (key is None or key in PLACEHOLDER_KEYS):
            raise ValueError("NOTES_API_KEY must be set to a real secret in production")
        return self


@lru_cache
def get_settings() -> Settings:
    """The process-wide settings, read from the environment once and then cached."""
    return Settings()
'''

NOTES_V2_CORE_ERRORS_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/core/errors.py
"""Domain errors and RFC 9457 Problem Details responses for every error the API returns."""

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
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
    )


async def http_error_handler(request: Request, error: StarletteHTTPException) -> JSONResponse:
    """HTTPException (ours, and Starlette's 404/405) → Problem Details."""
    detail = error.detail if isinstance(error.detail, str) else None
    return problem_response(request, error.status_code, detail, headers=error.headers)


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


async def unhandled_error_handler(request: Request, error: Exception) -> JSONResponse:
    """Any other exception → a generic 500; details stay in the server log."""
    return problem_response(request, HTTPStatus.INTERNAL_SERVER_ERROR, "unexpected error")


def install_error_handlers(app: FastAPI) -> None:
    """Register every handler on the app."""
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
'''

NOTES_V2_CORE_INIT_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/core/__init__.py
"""Cross-cutting pieces: settings, errors, middleware and the lifespan."""
'''

NOTES_V2_CORE_LIFESPAN_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/core/lifespan.py
"""Startup and shutdown: create shared resources once and keep them on app.state."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from notes_api import __version__
from notes_api.core.config import Settings
from notes_api.repositories import InMemoryNoteRepository


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the repository and one pooled HTTP client; close the client on shutdown."""
    settings: Settings = app.state.settings
    app.state.note_repository = InMemoryNoteRepository()
    async with httpx.AsyncClient(
        timeout=settings.http_timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": f"notes-api/{__version__}"},
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    ) as http_client:
        app.state.http_client = http_client
        yield
    # leaving the async with closed every pooled connection
'''

NOTES_V2_CORE_MIDDLEWARE_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/core/middleware.py
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
'''

NOTES_V2_DEPENDENCIES_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/dependencies.py
"""Dependencies shared by the routers, exported as Annotated aliases.

Resolution graph of a notes request:

    NoteServiceDep ── get_note_service ──┬── get_note_repository ── request.app.state
                                         └── get_clock
    ApiKeyDep ── require_api_key ──┬── get_app_settings ── request.app.state
                                   └── X-API-Key header (APIKeyHeader)
"""

import secrets
from collections.abc import Callable
from datetime import datetime
from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader  # noqa: F401  (for Lab 6.3, exercise 2)

from notes_api.core.config import Settings
from notes_api.models import utc_now
from notes_api.repositories import NoteRepository
from notes_api.services import LinkPreviewer, NoteService

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_app_settings(request: Request) -> Settings:
    """The settings this app was created with (create_app stores them on app.state)."""
    return request.app.state.settings


def get_note_repository(request: Request) -> NoteRepository:
    """The repository the lifespan created."""
    return request.app.state.note_repository


def get_clock() -> Callable[[], datetime]:
    """The clock for timestamps (tests override it with dependency_overrides)."""
    return utc_now


def get_http_client(request: Request) -> httpx.AsyncClient:
    """The pooled HTTP client the lifespan created."""
    return request.app.state.http_client


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
RepositoryDep = Annotated[NoteRepository, Depends(get_note_repository)]
ClockDep = Annotated[Callable[[], datetime], Depends(get_clock)]
HttpClientDep = Annotated[httpx.AsyncClient, Depends(get_http_client)]


def get_note_service(repository: RepositoryDep, clock: ClockDep) -> NoteService:
    """A NoteService wired to this app's repository and clock (one per request)."""
    return NoteService(repository, clock)


def get_link_previewer(client: HttpClientDep) -> LinkPreviewer:
    """A LinkPreviewer on the shared HTTP client."""
    return LinkPreviewer(client)


async def require_api_key(
    settings: SettingsDep, api_key: Annotated[str | None, Depends(api_key_header)]
) -> None:
    """Router-level guard: 503 when no key is configured, 401 when the header is wrong."""
    if settings.api_key is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "admin API disabled: set NOTES_API_KEY"
        )
    expected = settings.api_key.get_secret_value().encode()
    if api_key is None or not secrets.compare_digest(api_key.encode(), expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing or invalid X-API-Key header")


NoteServiceDep = Annotated[NoteService, Depends(get_note_service)]
LinkPreviewerDep = Annotated[LinkPreviewer, Depends(get_link_previewer)]
ApiKeyDep = Depends(require_api_key)
'''

NOTES_V2_EXCEPTIONS_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/exceptions.py
"""Domain exceptions: plain Python, no FastAPI (core/errors.py maps them to HTTP)."""

from http import HTTPStatus


class DomainError(Exception):
    """A business rule failed. Subclasses choose the status, a problem type and a title."""

    status_code: int = HTTPStatus.BAD_REQUEST
    problem_type: str = "domain-error"
    title: str = "Request breaks a business rule"


class NoteNotFoundError(DomainError, LookupError):
    """No note has the requested id."""

    status_code = HTTPStatus.NOT_FOUND
    problem_type = "note-not-found"
    title = "Note not found"

    def __init__(self, note_id: int) -> None:
        """Remember the id; the message becomes the problem's detail."""
        super().__init__(f"note {note_id} not found")
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
'''

NOTES_V2_INIT_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/__init__.py
"""Notes API: a FastAPI service built step by step in Phase 6 of the course."""

__version__ = "0.2.0"
'''

NOTES_V2_MAIN_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/main.py
"""The Notes API application factory.

Unit 6.3 version: create_app() wires settings, error handlers, middleware, the lifespan and the
routers. Later units add a database (6.4), authentication (6.5), background jobs and caching
(6.6), observability (6.7) and deployment (6.8).

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
from notes_api.core.config import Settings, get_settings
from notes_api.core.errors import install_error_handlers
from notes_api.core.lifespan import lifespan
from notes_api.core.middleware import REQUEST_ID_HEADER, RequestIdMiddleware, TimingMiddleware
from notes_api.routers import admin, health, notes, pages

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
        allow_headers=["Content-Type", "X-API-Key", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER, "Location", "Server-Timing"],
        max_age=600,
    )
    app.add_middleware(RequestIdMiddleware)


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
        generate_unique_id_function=operation_id,
        openapi_tags=[
            {"name": "notes", "description": "Create, read, update and delete notes."},
            {"name": "admin", "description": "Bulk operations; need the X-API-Key header."},
            {"name": "health", "description": "Liveness probe for load balancers and tests."},
        ],
    )
    app.state.settings = settings
    install_error_handlers(app)
    install_middleware(app, settings)
    api_router = APIRouter(prefix=API_PREFIX)
    api_router.include_router(notes.router)
    api_router.include_router(admin.router)
    app.include_router(health.router)
    app.include_router(api_router)
    app.include_router(pages.router)
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
    return app


app = create_app()
'''

NOTES_V2_MODELS_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/models.py
"""Domain models: the server's own records (Unit 6.4 turns them into SQLAlchemy models)."""

import dataclasses
from datetime import UTC, datetime


def utc_now() -> datetime:
    """The current time in UTC (the default clock)."""
    return datetime.now(UTC)


@dataclasses.dataclass(slots=True)
class Note:
    """A stored note."""

    id: int
    title: str
    body: str
    tags: list[str]
    pinned: bool
    created_at: datetime
    updated_at: datetime
'''

NOTES_V2_PAGINATION_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/pagination.py
"""Generic page envelopes and opaque keyset cursors."""

import base64
import binascii
import json
from datetime import datetime

from pydantic import BaseModel

from notes_api.exceptions import InvalidCursorError

type CursorKey = tuple[datetime, int]  # (created_at, id) of the last note on a page


class Page[ItemT](BaseModel):
    """One page of an offset-paginated list."""

    items: list[ItemT]
    total: int
    limit: int
    offset: int


class CursorPage[ItemT](BaseModel):
    """One page of a keyset-paginated list; pass next_cursor back to get the next page."""

    items: list[ItemT]
    limit: int
    next_cursor: str | None


def encode_cursor(key: CursorKey) -> str:
    """Opaque URL-safe text for (created_at, id): clients must not build or parse it."""
    created_at, note_id = key
    raw = json.dumps([created_at.isoformat(), note_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> CursorKey:
    """The (created_at, id) inside a cursor, or InvalidCursorError."""
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        created_text, note_id = json.loads(raw)
        if not isinstance(note_id, int):
            raise TypeError("id must be an integer")
        return datetime.fromisoformat(created_text), note_id
    except (binascii.Error, ValueError, TypeError) as error:
        raise InvalidCursorError(f"cursor {cursor!r} is not valid") from error
'''

NOTES_V2_REPOSITORIES_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/repositories.py
"""Storage behind a Protocol: the service depends on NoteRepository, not on a database.

Unit 6.3 ships an in-memory implementation; Unit 6.4 adds a SQLAlchemy one with the same
methods, so the service and the routers do not change.
"""

import dataclasses
import itertools
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from notes_api.models import Note
from notes_api.pagination import CursorKey
from notes_api.schemas import NoteCreate, NoteFilters


class NoteRepository(Protocol):
    """What the service needs from storage."""

    async def add(self, data: NoteCreate, now: datetime) -> Note:
        """Store a new note and return it with its id."""
        ...

    async def get(self, note_id: int) -> Note | None:
        """The note with this id, or None."""
        ...

    async def search(self, filters: NoteFilters) -> tuple[list[Note], int]:
        """One page of matching notes and the total number of matches."""
        ...

    async def feed(self, limit: int, after: CursorKey | None) -> list[Note]:
        """Up to limit notes, newest first, strictly older than the key after."""
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


def matches(note: Note, filters: NoteFilters) -> bool:
    """True if the note passes every filter."""
    if filters.pinned is not None and note.pinned != filters.pinned:
        return False
    if not set(filters.tag) <= set(note.tags):
        return False
    if filters.q:
        needle = filters.q.casefold()
        return needle in note.title.casefold() or needle in note.body.casefold()
    return True


def sort_key(field_name: str) -> Callable[[Note], tuple[object, int]]:
    """Sort by one field (text ignores case), then by id so the order is always stable."""

    def key(note: Note) -> tuple[object, int]:
        """The sort key of one note."""
        value = getattr(note, field_name)
        return (value.casefold() if isinstance(value, str) else value, note.id)

    return key


class InMemoryNoteRepository:
    """Notes in a dict, ids from a counter: one instance per app, created by the lifespan."""

    def __init__(self) -> None:
        """Start empty."""
        self._notes: dict[int, Note] = {}
        self._ids = itertools.count(1)

    async def add(self, data: NoteCreate, now: datetime) -> Note:
        """Store a new note."""
        note = Note(id=next(self._ids), **data.model_dump(), created_at=now, updated_at=now)
        self._notes[note.id] = note
        return dataclasses.replace(note)

    async def get(self, note_id: int) -> Note | None:
        """A copy of the stored note, so callers cannot change storage by accident."""
        note = self._notes.get(note_id)
        return None if note is None else dataclasses.replace(note, tags=list(note.tags))

    async def search(self, filters: NoteFilters) -> tuple[list[Note], int]:
        """Filter, sort, then slice one page."""
        found = [note for note in self._notes.values() if matches(note, filters)]
        descending = filters.sort.startswith("-")
        found.sort(key=sort_key(filters.sort.removeprefix("-")), reverse=descending)
        return found[filters.offset : filters.offset + filters.limit], len(found)

    async def feed(self, limit: int, after: CursorKey | None) -> list[Note]:
        """Newest first by (created_at, id); keyset: only keys smaller than after."""
        ordered = sorted(self._notes.values(), key=lambda note: (note.created_at, note.id))
        older = [
            note
            for note in reversed(ordered)
            if after is None or (note.created_at, note.id) < after
        ]
        return older[:limit]

    async def update(self, note: Note, changes: dict[str, Any], now: datetime) -> Note:
        """Store a changed copy of the note."""
        updated = dataclasses.replace(note, **changes, updated_at=now)
        self._notes[note.id] = updated
        return dataclasses.replace(updated, tags=list(updated.tags))

    async def delete(self, note: Note) -> None:
        """Remove one note."""
        del self._notes[note.id]

    async def delete_all(self) -> int:
        """Remove every note and restart ids at 1."""
        count = len(self._notes)
        self._notes.clear()
        self._ids = itertools.count(1)
        return count
'''

NOTES_V2_ROUTERS_ADMIN_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/routers/admin.py
"""/api/v1/admin: bulk import (file upload), export and wipe. Every route needs X-API-Key."""

from http import HTTPStatus

from fastapi import APIRouter, UploadFile, status
from fastapi.responses import JSONResponse

from notes_api.dependencies import ApiKeyDep, NoteServiceDep, SettingsDep
from notes_api.exceptions import UploadRejectedError
from notes_api.schemas import ImportReport, NoteFilters, NoteRead
from notes_api.services import parse_import

ALLOWED_UPLOADS = {".json": {"application/json"}, ".csv": {"text/csv", "application/vnd.ms-excel"}}

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[ApiKeyDep])


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
    file: UploadFile, service: NoteServiceDep, settings: SettingsDep
) -> ImportReport:
    """Create notes from an uploaded .json list or .csv file (all or nothing)."""
    content = await read_upload(file, settings.max_upload_bytes)
    notes = parse_import(file.filename or "", content)
    created = await service.import_notes(notes)
    return ImportReport(
        filename=file.filename or "", imported=len(created), ids=[note.id for note in created]
    )


@router.get("/export")
async def export_notes(service: NoteServiceDep) -> JSONResponse:
    """Every note as a downloadable JSON file."""
    notes, _total = await service.search(NoteFilters(limit=100, sort="created_at"))
    payload = [NoteRead.model_validate(note).model_dump(mode="json") for note in notes]
    headers = {"Content-Disposition": 'attachment; filename="notes.json"'}
    return JSONResponse(payload, headers=headers)


@router.delete("/notes")
async def delete_all_notes(service: NoteServiceDep) -> dict[str, int]:
    """Remove every note."""
    return {"deleted": await service.delete_all()}
'''

NOTES_V2_ROUTERS_HEALTH_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/routers/health.py
"""/health: the liveness probe (unversioned: load balancers and tests call it)."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}
'''

NOTES_V2_ROUTERS_INIT_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/routers/__init__.py
"""One APIRouter per area: health, notes, admin and the server-rendered pages."""
'''

NOTES_V2_ROUTERS_NOTES_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/routers/notes.py
"""/api/v1/notes: CRUD, search with offset pages, a keyset feed, and link previews."""

from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Request, Response, status

from notes_api.core.errors import PROBLEM_JSON, ProblemDetail
from notes_api.dependencies import LinkPreviewerDep, NoteServiceDep
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

router = APIRouter(prefix="/notes", tags=["notes"])


@router.post("", response_model=NoteRead, status_code=status.HTTP_201_CREATED)
async def create_note(
    note: NoteCreate, service: NoteServiceDep, request: Request, response: Response
) -> Note:
    """Create a note; the Location header points at it."""
    created = await service.create(note)
    response.headers["Location"] = request.app.url_path_for("get_note", note_id=str(created.id))
    return created


@router.get("", response_model=Page[NoteRead])
async def list_notes(
    filters: Annotated[NoteFilters, Query()], service: NoteServiceDep
) -> dict[str, object]:
    """Search, filter, sort and paginate notes (offset pagination)."""
    notes, total = await service.search(filters)
    return {"items": notes, "total": total, "limit": filters.limit, "offset": filters.offset}


@router.get("/feed", response_model=CursorPage[NoteRead])
async def notes_feed(
    params: Annotated[FeedParams, Query()], service: NoteServiceDep
) -> dict[str, object]:
    """Newest notes first, with keyset (cursor) pagination."""
    notes, next_cursor = await service.feed(params.limit, params.cursor)
    return {"items": notes, "limit": params.limit, "next_cursor": next_cursor}


@router.get("/{note_id}", response_model=NoteRead, responses=NOT_FOUND)
async def get_note(note_id: NoteId, service: NoteServiceDep) -> Note:
    """Fetch one note."""
    return await service.get(note_id)


@router.put("/{note_id}", response_model=NoteRead, responses=NOT_FOUND)
async def replace_note(note_id: NoteId, note: NoteCreate, service: NoteServiceDep) -> Note:
    """Replace every field of a note (omitted fields get their defaults)."""
    return await service.replace(note_id, note)


@router.patch("/{note_id}", response_model=NoteRead, responses=NOT_FOUND)
async def update_note(note_id: NoteId, changes: NoteUpdate, service: NoteServiceDep) -> Note:
    """Change only the fields sent in the body."""
    return await service.update(note_id, changes)


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND)
async def delete_note(note_id: NoteId, service: NoteServiceDep) -> None:
    """Delete a note."""
    await service.delete(note_id)


@router.get("/{note_id}/links", response_model=list[LinkPreview], responses=NOT_FOUND)
async def note_links(
    note_id: NoteId, service: NoteServiceDep, previewer: LinkPreviewerDep
) -> list[LinkPreview]:
    """Titles of the links in a note's body, fetched with the shared HTTP client."""
    note = await service.get(note_id)
    return await previewer.previews(note.body)
'''

NOTES_V2_ROUTERS_PAGES_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/routers/pages.py
"""Server-rendered pages: Jinja2 templates, a form with redirect-after-POST, HTMX partials."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, Header, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from notes_api.dependencies import NoteServiceDep
from notes_api.schemas import NoteCreate, NoteFilters, NoteUpdate

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(include_in_schema=False)  # HTML for people, not part of the JSON API


@router.get("/", response_class=HTMLResponse)
async def notes_page(
    request: Request,
    service: NoteServiceDep,
    q: str = "",
    hx_request: Annotated[str | None, Header()] = None,
) -> Response:
    """The notes page; for an HTMX search request only the list fragment."""
    notes, total = await service.search(NoteFilters(q=q or None, limit=50))
    context = {"notes": notes, "total": total, "q": q, "errors": [], "form": {}}
    template = "_notes.html" if hx_request == "true" else "index.html"
    return templates.TemplateResponse(request, template, context)


@router.post("/notes", response_class=HTMLResponse)
async def create_from_form(
    request: Request,
    service: NoteServiceDep,
    title: Annotated[str, Form()] = "",
    body: Annotated[str, Form()] = "",
    tags: Annotated[str, Form()] = "",
) -> Response:
    """Create a note from the HTML form, then redirect (303) so a reload does not re-post."""
    form = {"title": title, "body": body, "tags": tags}
    try:
        data = NoteCreate(
            title=title, body=body, tags=[tag for tag in tags.replace(",", " ").split() if tag]
        )
    except ValidationError as error:
        notes, total = await service.search(NoteFilters(limit=50))
        errors = [
            f"{'.'.join(map(str, problem['loc']))}: {problem['msg']}" for problem in error.errors()
        ]
        context = {"notes": notes, "total": total, "q": "", "errors": errors, "form": form}
        return templates.TemplateResponse(
            request, "index.html", context, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT
        )
    await service.create(data)
    return RedirectResponse(request.url_for("notes_page"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/notes/{note_id}/pin", response_class=HTMLResponse)
async def toggle_pin(request: Request, note_id: int, service: NoteServiceDep) -> Response:
    """HTMX: flip the pinned flag and return just this note's fragment."""
    note = await service.get(note_id)
    note = await service.update(note_id, NoteUpdate(pinned=not note.pinned))
    return templates.TemplateResponse(request, "_note.html", {"note": note})
'''

NOTES_V2_SCHEMAS_PY = r'''
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
    Field,
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

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"pinned": True}]})

    title: Title | None = None
    body: Body | None = None
    tags: Tags | None = None
    pinned: bool | None = None

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
'''

NOTES_V2_SERVICES_PY = r'''
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

import httpx
from pydantic import TypeAdapter, ValidationError

from notes_api.exceptions import NoteNotFoundError, UploadRejectedError
from notes_api.models import Note, utc_now
from notes_api.pagination import decode_cursor, encode_cursor
from notes_api.repositories import NoteRepository
from notes_api.schemas import LinkPreview, NoteCreate, NoteFilters, NoteUpdate

URL_PATTERN = re.compile(r"https?://[^\s<>\"')]+")
TITLE_PATTERN = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
MAX_LINKS = 5
IMPORT_ADAPTER = TypeAdapter(list[NoteCreate])


class NoteService:
    """Use cases for notes; the repository and the clock are injected."""

    def __init__(self, repository: NoteRepository, clock: Callable[[], datetime] = utc_now) -> None:
        """Keep the collaborators."""
        self.repository = repository
        self.clock = clock

    async def create(self, data: NoteCreate) -> Note:
        """Store a new note stamped with the current time."""
        return await self.repository.add(data, self.clock())

    async def get(self, note_id: int) -> Note:
        """The note, or NoteNotFoundError (the API turns it into a 404 problem)."""
        note = await self.repository.get(note_id)
        if note is None:
            raise NoteNotFoundError(note_id)
        return note

    async def search(self, filters: NoteFilters) -> tuple[list[Note], int]:
        """One page of matching notes and the total."""
        return await self.repository.search(filters)

    async def feed(self, limit: int, cursor: str | None) -> tuple[list[Note], str | None]:
        """A keyset page, newest first, and the cursor of the next page (None at the end)."""
        after = decode_cursor(cursor) if cursor else None
        notes = await self.repository.feed(limit + 1, after)  # one extra: is there a next page?
        page = notes[:limit]
        has_more = len(notes) > limit
        next_cursor = encode_cursor((page[-1].created_at, page[-1].id)) if has_more else None
        return page, next_cursor

    async def replace(self, note_id: int, data: NoteCreate) -> Note:
        """PUT: every client-owned field gets the new value (or its default)."""
        note = await self.get(note_id)
        return await self.repository.update(note, data.model_dump(), self.clock())

    async def update(self, note_id: int, changes: NoteUpdate) -> Note:
        """PATCH: apply only the fields sent; updated_at moves only on a real change."""
        note = await self.get(note_id)
        sent = changes.model_dump(exclude_unset=True)
        if all(getattr(note, name) == value for name, value in sent.items()):
            return note
        return await self.repository.update(note, sent, self.clock())

    async def delete(self, note_id: int) -> None:
        """Delete a note, or NoteNotFoundError."""
        note = await self.get(note_id)
        await self.repository.delete(note)

    async def import_notes(self, notes: list[NoteCreate]) -> list[Note]:
        """Create every note of an import, in file order."""
        return [await self.create(note) for note in notes]

    async def delete_all(self) -> int:
        """Remove every note."""
        return await self.repository.delete_all()


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


class LinkPreviewer:
    """Fetch the <title> of links in a note through the app's shared HTTP client."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        """Use the pooled client created by the lifespan."""
        self.client = client

    async def preview(self, url: str) -> LinkPreview:
        """One link: its status and title, or the error name (never raises)."""
        try:
            response = await self.client.get(url)
        except httpx.HTTPError as error:
            return LinkPreview(url=url, error=type(error).__name__)
        match = TITLE_PATTERN.search(response.text)
        title = " ".join(match[1].split()) if match else None
        return LinkPreview(url=url, status_code=response.status_code, title=title)

    async def previews(self, body: str) -> list[LinkPreview]:
        """The first MAX_LINKS distinct links of a body, fetched concurrently."""
        urls = list(dict.fromkeys(URL_PATTERN.findall(body)))[:MAX_LINKS]
        return list(await asyncio.gather(*(self.preview(url) for url in urls)))
'''

NOTES_V2_STATIC_STYLE_CSS = r"""
%%writefile ../projects/notes_api/src/notes_api/static/style.css
body { font-family: system-ui, sans-serif; margin: 0 auto; max-width: 42rem; padding: 1rem; }
.new-note { display: grid; gap: 0.5rem; margin-bottom: 1rem; }
.notes { list-style: none; padding: 0; }
.note { border: 1px solid #ccc; border-radius: 0.5rem; margin: 0.5rem 0; padding: 0.5rem 1rem; }
.note.pinned { border-color: #c80; background: #fff8e8; }
.tag { background: #eef; border-radius: 0.25rem; font-size: 0.8rem; margin-left: 0.25rem; padding: 0 0.3rem; }
.error { color: #b00; margin: 0; }
"""

NOTES_V2_TEMPLATES_BASE_HTML = r"""
%%writefile ../projects/notes_api/src/notes_api/templates/base.html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Notes{% endblock %}</title>
  <link rel="stylesheet" href="{{ url_for('static', path='style.css') }}">
  {# HTMX is optional: without it the form and links still work as plain HTML. #}
  <script src="https://unpkg.com/htmx.org@2.0.4" defer></script>
</head>
<body>
  <main>{% block content %}{% endblock %}</main>
</body>
</html>
"""

NOTES_V2_TEMPLATES_INDEX_HTML = r"""
%%writefile ../projects/notes_api/src/notes_api/templates/index.html
{% extends "base.html" %}
{% block content %}
<h1>Notes</h1>
<form method="post" action="{{ url_for('create_from_form') }}" class="new-note">
  {% for error in errors %}<p class="error">{{ error }}</p>{% endfor %}
  <input name="title" placeholder="Title" value="{{ form.title or '' }}">
  <textarea name="body" placeholder="Body">{{ form.body or '' }}</textarea>
  <input name="tags" placeholder="tags, separated by spaces" value="{{ form.tags or '' }}">
  <button type="submit">Add note</button>
</form>
<input type="search" name="q" value="{{ q }}" placeholder="Search"
       hx-get="{{ url_for('notes_page') }}" hx-trigger="input changed delay:300ms"
       hx-target="#notes" hx-push-url="true">
<div id="notes">{% include "_notes.html" %}</div>
{% endblock %}
"""

NOTES_V2_TEMPLATES_NOTE_HTML = r"""
%%writefile ../projects/notes_api/src/notes_api/templates/_note.html
<li class="note{{ ' pinned' if note.pinned }}" id="note-{{ note.id }}">
  <strong>{{ note.title }}</strong>
  {% for tag in note.tags %}<span class="tag">{{ tag }}</span>{% endfor %}
  <p>{{ note.body }}</p>
  <button hx-post="{{ url_for('toggle_pin', note_id=note.id) }}" hx-target="#note-{{ note.id }}"
          hx-swap="outerHTML">{{ "Unpin" if note.pinned else "Pin" }}</button>
</li>
"""

NOTES_V2_TEMPLATES_NOTES_HTML = r"""
%%writefile ../projects/notes_api/src/notes_api/templates/_notes.html
<p class="count">{{ total }} note{{ "" if total == 1 else "s" }}</p>
<ul class="notes">
  {% for note in notes %}{% include "_note.html" %}{% else %}<li class="empty">No notes yet.</li>{% endfor %}
</ul>
"""

NOTES_V2_TESTS_CONFTEST_PY = r'''
%%writefile ../projects/notes_api/tests/conftest.py
"""Shared fixtures: every test gets its own app from create_app(), so no state leaks."""

import secrets
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from notes_api.core.config import Settings
from notes_api.main import create_app


@pytest.fixture
def settings() -> Settings:
    """Test settings: no .env file, a key generated for this run, a small upload limit."""
    return Settings(
        _env_file=None,
        environment="test",
        api_key=SecretStr(secrets.token_urlsafe(16)),
        cors_origins=["http://localhost:5173"],
        max_upload_bytes=2048,
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    """A fresh app (and so a fresh in-memory repository) for each test."""
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """A TestClient; entering it runs the lifespan (startup and shutdown)."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def admin_headers(settings: Settings) -> dict[str, str]:
    """Headers carrying the valid API key."""
    assert settings.api_key is not None
    return {"X-API-Key": settings.api_key.get_secret_value()}
'''

NOTES_V2_TESTS_HELPERS_PY = r'''
%%writefile ../projects/notes_api/tests/helpers.py
"""Small helpers shared by the test modules."""

from typing import Any

from fastapi.testclient import TestClient


def create(client: TestClient, **fields: Any) -> dict[str, Any]:
    """POST a note (title defaults to "Buy tea") and return the created note."""
    response = client.post("/api/v1/notes", json={"title": "Buy tea", **fields})
    assert response.status_code == 201, response.text
    return response.json()


def ids(response: Any) -> list[int]:
    """Ids of the notes on a page."""
    assert response.status_code == 200, response.text
    return [note["id"] for note in response.json()["items"]]
'''

NOTES_V2_TESTS_TEST_ADMIN_PY = r'''
%%writefile ../projects/notes_api/tests/test_admin.py
"""The admin router: a router-level API key, uploads with validation, export and wipe."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from helpers import create
from notes_api.core.config import Settings
from notes_api.main import create_app

IMPORT = "/api/v1/admin/import"
NOTES_JSON = json.dumps([{"title": "Tea", "tags": ["shop"]}, {"title": "Rice", "pinned": True}])
NOTES_CSV = "title,body,tags,pinned\nTea,Assam,shop;food,false\nRice,,shop,true\n"


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}])
def test_every_admin_route_needs_the_key(client: TestClient, headers: dict[str, str]) -> None:
    """Missing or wrong keys are 401 problems on every admin route."""
    for method, path in [("GET", "/api/v1/admin/export"), ("DELETE", "/api/v1/admin/notes")]:
        response = client.request(method, path, headers=headers)
        assert response.status_code == 401
        assert response.json()["detail"] == "missing or invalid X-API-Key header"


def test_admin_is_disabled_without_a_configured_key() -> None:
    """No NOTES_API_KEY: the admin router answers 503, the rest of the API works."""
    app: FastAPI = create_app(Settings(_env_file=None, api_key=None))
    with TestClient(app) as client:
        assert client.get("/api/v1/admin/export", headers={"X-API-Key": "x"}).status_code == 503
        assert client.get("/api/v1/notes").status_code == 200


@pytest.mark.parametrize(
    ("filename", "content", "content_type"),
    [("notes.json", NOTES_JSON, "application/json"), ("notes.csv", NOTES_CSV, "text/csv")],
)
def test_import_json_and_csv(
    client: TestClient,
    admin_headers: dict[str, str],
    filename: str,
    content: str,
    content_type: str,
) -> None:
    """Both formats create the same notes."""
    files = {"file": (filename, content.encode(), content_type)}
    report = client.post(IMPORT, files=files, headers=admin_headers)
    assert report.status_code == 201, report.text
    assert report.json() == {"filename": filename, "imported": 2, "ids": [1, 2]}
    notes = client.get("/api/v1/notes", params={"sort": "created_at"}).json()["items"]
    assert [(note["title"], note["pinned"]) for note in notes] == [("Tea", False), ("Rice", True)]


@pytest.mark.parametrize(
    ("filename", "content", "content_type", "status"),
    [
        ("notes.txt", b"hello", "text/plain", 415),
        ("notes.json", b"[]", "text/csv", 415),
        ("notes.json", b"[" + b" " * 4096 + b"]", "application/json", 413),
        ("notes.json", b'[{"title": ""}]', "application/json", 422),
        ("notes.json", b"not json", "application/json", 422),
    ],
)
def test_import_rejects_bad_files(
    client: TestClient,
    admin_headers: dict[str, str],
    filename: str,
    content: bytes,
    content_type: str,
    status: int,
) -> None:
    """Wrong type → 415, too large → 413, invalid content → 422; nothing is imported."""
    files = {"file": (filename, content, content_type)}
    response = client.post(IMPORT, files=files, headers=admin_headers)
    assert response.status_code == status, response.text
    assert response.json()["type"] == "/problems/upload-rejected"
    assert client.get("/api/v1/notes").json()["total"] == 0


def test_export_and_delete_all(client: TestClient, admin_headers: dict[str, str]) -> None:
    """Export downloads every note; delete removes them all."""
    create(client, title="Tea")
    create(client, title="Rice")
    export = client.get("/api/v1/admin/export", headers=admin_headers)
    assert export.headers["content-disposition"] == 'attachment; filename="notes.json"'
    assert [note["title"] for note in export.json()] == ["Tea", "Rice"]
    assert client.delete("/api/v1/admin/notes", headers=admin_headers).json() == {"deleted": 2}
    assert client.get("/api/v1/notes").json()["total"] == 0
'''

NOTES_V2_TESTS_TEST_ERRORS_PY = r'''
%%writefile ../projects/notes_api/tests/test_errors.py
"""Every error is an RFC 9457 Problem Details document."""

from fastapi.testclient import TestClient

PROBLEM_KEYS = {"type", "title", "status", "detail", "instance", "request_id"}


def test_not_found_problem(client: TestClient) -> None:
    """A domain NoteNotFoundError becomes a typed 404 problem."""
    response = client.get("/api/v1/notes/5")
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert PROBLEM_KEYS <= body.keys()
    assert (body["type"], body["title"], body["status"], body["instance"]) == (
        "/problems/note-not-found",
        "Note not found",
        404,
        "/api/v1/notes/5",
    )


def test_validation_problem_lists_every_error_without_echoing_input(client: TestClient) -> None:
    """422 problems list location, message and type for each error, but not the input."""
    body = client.post("/api/v1/notes", json={"title": "", "pinned": "maybe"}).json()
    assert body["status"] == 422
    assert [error["loc"] for error in body["errors"]] == [["body", "title"], ["body", "pinned"]]
    assert all(error.keys() == {"loc", "msg", "type"} for error in body["errors"])


def test_framework_errors_are_problems_too(client: TestClient) -> None:
    """Unknown routes (404) and wrong methods (405) use the same format."""
    unknown = client.get("/nope")
    wrong_method = client.post("/health")
    assert (unknown.status_code, unknown.json()["title"]) == (404, "Not Found")
    assert (wrong_method.status_code, wrong_method.json()["type"]) == (405, "about:blank")
    assert wrong_method.headers["allow"] == "GET"
'''

NOTES_V2_TESTS_TEST_LINKS_PY = r'''
%%writefile ../projects/notes_api/tests/test_links.py
"""Link previews use the lifespan's shared HTTP client; respx fakes the remote sites."""

import httpx
import respx
from fastapi.testclient import TestClient

from helpers import create


@respx.mock
def test_link_titles_are_fetched(client: TestClient) -> None:
    """Each distinct link is fetched once; titles are extracted; failures are reported."""
    respx.get("https://docs.example/fastapi").respond(200, html="<title> FastAPI\n docs </title>")
    respx.get("https://slow.example/").mock(side_effect=httpx.ConnectTimeout("too slow"))
    body = (
        "read https://docs.example/fastapi and https://slow.example/ (https://docs.example/fastapi)"
    )
    create(client, body=body)
    previews = client.get("/api/v1/notes/1/links").json()
    assert previews == [
        {
            "url": "https://docs.example/fastapi",
            "status_code": 200,
            "title": "FastAPI docs",
            "error": None,
        },
        {
            "url": "https://slow.example/",
            "status_code": None,
            "title": None,
            "error": "ConnectTimeout",
        },
    ]
    assert respx.calls.call_count == 2


def test_the_client_lives_as_long_as_the_app(app: object) -> None:
    """The lifespan opens one client at startup and closes it at shutdown."""
    with TestClient(app) as client:  # type: ignore[arg-type]
        http_client = client.app.state.http_client  # type: ignore[attr-defined]
        assert not http_client.is_closed
    assert http_client.is_closed
'''

NOTES_V2_TESTS_TEST_MIDDLEWARE_PY = r'''
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
    """Outermost first: request id, CORS, GZip, timing (the last one added runs first)."""
    names = [middleware.cls.__name__ for middleware in app.user_middleware]
    assert names == ["RequestIdMiddleware", "CORSMiddleware", "GZipMiddleware", "TimingMiddleware"]
    assert {RequestIdMiddleware, TimingMiddleware} <= {
        middleware.cls for middleware in app.user_middleware
    }
'''

NOTES_V2_TESTS_TEST_NOTES_PY = r'''
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
'''

NOTES_V2_TESTS_TEST_PAGES_PY = r'''
%%writefile ../projects/notes_api/tests/test_pages.py
"""Server-rendered pages: templates, a form with redirect, HTMX fragments, static files."""

from fastapi.testclient import TestClient

from helpers import create


def test_page_lists_notes_as_html(client: TestClient) -> None:
    """GET / renders the full page with every note, escaped."""
    create(client, title="Buy <tea>", tags=["shop"])
    page = client.get("/")
    assert page.headers["content-type"].startswith("text/html")
    assert "<!doctype html>" in page.text
    assert "Buy &lt;tea&gt;" in page.text and "Buy <tea>" not in page.text


def test_htmx_search_returns_only_the_fragment(client: TestClient) -> None:
    """With HX-Request: true the response is the list fragment, not a whole page."""
    create(client, title="Tea")
    create(client, title="Rice")
    fragment = client.get("/", params={"q": "tea"}, headers={"HX-Request": "true"}).text
    assert "<html" not in fragment
    assert "Tea" in fragment and "Rice" not in fragment


def test_form_post_redirects_with_303(client: TestClient) -> None:
    """A valid form creates the note and redirects back (Post/Redirect/Get)."""
    response = client.post(
        "/notes", data={"title": "From the form", "tags": "home, todo"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "http://testserver/"
    note = client.get("/api/v1/notes/1").json()
    assert (note["title"], note["tags"]) == ("From the form", ["home", "todo"])


def test_invalid_form_is_shown_again_with_errors(client: TestClient) -> None:
    """An invalid form re-renders the page (422) with the message and the typed values."""
    response = client.post("/notes", data={"title": "", "body": "keep me"})
    assert response.status_code == 422
    assert "title:" in response.text and "keep me" in response.text


def test_htmx_pin_returns_one_note(client: TestClient) -> None:
    """The pin button swaps in the updated fragment of one note."""
    create(client, title="Tea")
    fragment = client.post("/notes/1/pin").text
    assert 'class="note pinned"' in fragment and "Unpin" in fragment


def test_static_css_is_served(client: TestClient) -> None:
    """StaticFiles serves the stylesheet."""
    response = client.get("/static/style.css")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/css")
'''

NOTES_V2_TESTS_TEST_PAGINATION_PY = r'''
%%writefile ../projects/notes_api/tests/test_pagination.py
"""Keyset (cursor) pagination on /api/v1/notes/feed."""

from fastapi.testclient import TestClient

from helpers import create

FEED = "/api/v1/notes/feed"


def test_feed_walks_every_note_newest_first(client: TestClient) -> None:
    """Following next_cursor visits each note once, newest first, then stops."""
    for number in range(7):
        create(client, title=f"Note {number}")
    seen: list[int] = []
    params: dict[str, object] = {"limit": 3}
    while True:
        page = client.get(FEED, params=params).json()
        seen += [note["id"] for note in page["items"]]
        if page["next_cursor"] is None:
            break
        params = {"limit": 3, "cursor": page["next_cursor"]}
    assert seen == [7, 6, 5, 4, 3, 2, 1]


def test_feed_is_stable_when_notes_are_added(client: TestClient) -> None:
    """A note created between two pages does not shift the next page (unlike offsets)."""
    for number in range(4):
        create(client, title=f"Note {number}")
    first = client.get(FEED, params={"limit": 2}).json()
    create(client, title="Brand new")
    second = client.get(FEED, params={"limit": 2, "cursor": first["next_cursor"]}).json()
    assert [note["id"] for note in second["items"]] == [2, 1]


def test_bad_cursor_is_a_400_problem(client: TestClient) -> None:
    """A cursor the API did not issue is rejected with a clear problem type."""
    response = client.get(FEED, params={"cursor": "not-a-cursor"})
    assert response.status_code == 400
    assert response.json()["type"] == "/problems/invalid-cursor"
'''

NOTES_V2_TESTS_TEST_SETTINGS_PY = r'''
%%writefile ../projects/notes_api/tests/test_settings.py
"""pydantic-settings: environment variables, .env files, secrets and validation."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from notes_api.core.config import Settings, get_settings


def test_environment_variables_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """NOTES_* variables are read and converted (JSON for lists)."""
    monkeypatch.setenv("NOTES_DEBUG", "true")
    monkeypatch.setenv("NOTES_CORS_ORIGINS", '["https://a.example", "https://b.example"]')
    monkeypatch.setenv("NOTES_MAX_UPLOAD_BYTES", "4096")
    settings = Settings(_env_file=None)
    assert (settings.debug, settings.cors_origins, settings.max_upload_bytes) == (
        True,
        ["https://a.example", "https://b.example"],
        4096,
    )


def test_env_file_is_read_and_variables_win(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A .env file supplies values; a real environment variable overrides it."""
    env_file = tmp_path / ".env"
    env_file.write_text("NOTES_APP_NAME=From file\nNOTES_API_KEY=file-key\n", encoding="utf-8")
    monkeypatch.setenv("NOTES_API_KEY", "env-key")
    settings = Settings(_env_file=env_file)
    assert settings.app_name == "From file"
    assert settings.api_key is not None and settings.api_key.get_secret_value() == "env-key"


def test_secret_is_hidden_in_repr_and_dumps() -> None:
    """SecretStr never shows its value unless asked explicitly."""
    settings = Settings(_env_file=None, api_key="s3cret-value")
    assert "s3cret-value" not in repr(settings)
    assert settings.model_dump()["api_key"].get_secret_value() == "s3cret-value"
    assert settings.model_dump(mode="json")["api_key"] == "**********"


@pytest.mark.parametrize("key", [None, "change-me"])
def test_production_needs_a_real_key(key: str | None) -> None:
    """Missing or placeholder keys stop a production app from starting."""
    with pytest.raises(ValidationError, match="NOTES_API_KEY"):
        Settings(_env_file=None, environment="production", api_key=key)


def test_get_settings_is_cached() -> None:
    """The settings dependency builds Settings once per process."""
    get_settings.cache_clear()
    assert get_settings() is get_settings()
    get_settings.cache_clear()
'''


def _notes_v2_intro_cells() -> list[NotebookNode]:
    """Notes API v2: introduction, pruning and project metadata."""
    return [
        md(
            """
            ### Notes API v2 — the project files

            Unit 6.3, applied to the real project. v1 was one module with a module-level
            `notes_store`; v2 is a layered package built by a factory, and the store is
            **injected**:

            | v1 (Unit 6.2) | v2 (this unit) |
            | --- | --- |
            | `app = FastAPI()` at import time | `create_app(settings)` factory (`app = create_app()` stays for `uvicorn notes_api.main:app`) |
            | one `main.py` with every route | `routers/`: `health`, `notes` and `admin` under `/api/v1`, `pages` for HTML |
            | module-level `notes_store`, tests clear it | `NoteRepository` Protocol + `InMemoryNoteRepository` created by the lifespan; `NoteService` injected with `Depends` |
            | no configuration | `core/config.py`: `Settings` from `NOTES_*` variables and `.env`, committed `.env.example` |
            | `{"detail": ...}` errors | RFC 9457 Problem Details for every error (`core/errors.py`, domain errors in `exceptions.py`) |
            | no middleware | request ids (`ContextVar`), `Server-Timing`, GZip, CORS |
            | offset pages only | `Page[T]` + a keyset feed with opaque cursors (`CursorPage[T]`) |
            | JSON only | uploads (admin import), link previews through a lifespan HTTP client, Jinja2 + HTMX pages |

            Every file is written by a cell below, in dependency order (core first, routers
            and the factory last, then the tests). First, remove files that belong to other
            versions: after a full run that is only v1's `store.py`; when you re-run this unit
            after Unit 6.4 it also removes v3's database files, so the folder is exactly v2:
            """
        ),
        code(
            r'''
            NOTES_V2_FILES = """
            .env.example README.md pyproject.toml ruff.toml src/notes_api/__init__.py
            src/notes_api/dependencies.py src/notes_api/exceptions.py src/notes_api/main.py
            src/notes_api/models.py src/notes_api/pagination.py src/notes_api/repositories.py
            src/notes_api/schemas.py src/notes_api/services.py src/notes_api/core/__init__.py
            src/notes_api/core/config.py src/notes_api/core/errors.py src/notes_api/core/lifespan.py
            src/notes_api/core/middleware.py src/notes_api/routers/__init__.py
            src/notes_api/routers/admin.py src/notes_api/routers/health.py src/notes_api/routers/notes.py
            src/notes_api/routers/pages.py src/notes_api/static/style.css src/notes_api/templates/_note.html
            src/notes_api/templates/_notes.html src/notes_api/templates/base.html
            src/notes_api/templates/index.html tests/conftest.py tests/helpers.py tests/test_admin.py
            tests/test_errors.py tests/test_links.py tests/test_middleware.py tests/test_notes.py
            tests/test_pages.py tests/test_pagination.py tests/test_settings.py
            """.split()
            print("removed:", prune_notes_project(NOTES_V2_FILES))
            print(f"{len(NOTES_V2_FILES)} files to write")
            '''
        ),
        md(
            """
            **Project metadata.** v2 adds `pydantic-settings` (runtime) and `respx` (tests:
            fake remote websites for the link previews):
            """
        ),
        code(NOTES_V2_PYPROJECT_TOML),
        md("Ruff settings (unchanged from v1):"),
        code(NOTES_V2_RUFF_TOML),
        md(
            """
            **`.env.example`** is committed and documents every setting with a placeholder.
            Copy it to `.env` (git-ignored) and put real values there; the app refuses to
            start in production with the placeholder key:
            """
        ),
        code(NOTES_V2_ENV_EXAMPLE),
        *writefile_cells(
            NOTES_V2_README_MD,
            [
                ("", "The README, part 1: what changed and how to run it."),
                ("## Endpoints", "Part 2: the endpoint table (note the `/api/v1` prefix)."),
                ("## Layout", "Part 3: the package layout and the dependency direction."),
            ],
        ),
        md("The version moves to 0.2.0; `core/` gets a package marker:"),
        code(NOTES_V2_INIT_PY),
        md("`core/` becomes a package (settings, errors, middleware and the lifespan live there):"),
        code(NOTES_V2_CORE_INIT_PY),
    ]


def _notes_v2_core_cells() -> list[NotebookNode]:
    """Notes API v2: core/ and the domain layers."""
    return [
        md(
            """
            **`core/config.py`.** The 6.3.6 pattern: `Settings` with the `NOTES_` prefix, an
            optional `.env`, a `SecretStr` key, and a validator that refuses placeholder keys
            in production. `get_settings()` is the cached reader `create_app()` falls back to:
            """
        ),
        *writefile_cells(
            NOTES_V2_CORE_CONFIG_PY,
            [
                ("", "Part 1 of `config.py`: the settings model."),
                ("@lru_cache", "Part 2: the cached reader."),
            ],
        ),
        md(
            """
            **`exceptions.py`.** Domain errors as plain Python: each class carries the HTTP
            status, a problem type slug and a title, but imports nothing from FastAPI, so
            services can raise them without knowing about HTTP:
            """
        ),
        *writefile_cells(
            NOTES_V2_EXCEPTIONS_PY,
            [
                ("", "Part 1 of `exceptions.py`: the base class and *note not found*."),
                ("class InvalidCursorError(", "Part 2: bad cursors and rejected uploads."),
            ],
        ),
        md(
            """
            **`core/middleware.py`.** Pure ASGI middleware (6.3.7): `RequestIdMiddleware`
            reuses a safe incoming `X-Request-ID` or makes one, stores it in a `ContextVar`
            (for logs) and on `scope["state"]` (for error handlers, which may run outside the
            middleware), and echoes it; `TimingMiddleware` adds `Server-Timing`:
            """
        ),
        *writefile_cells(
            NOTES_V2_CORE_MIDDLEWARE_PY,
            [
                (
                    "",
                    "Part 1 of `middleware.py`: imports, the header name and the context variable.",
                ),
                ("class RequestIdMiddleware:", "Part 2: the request-id middleware."),
                ("class TimingMiddleware:", "Part 3: the timing middleware (clock injectable)."),
            ],
        ),
        md(
            """
            **`core/errors.py`.** Problem Details for everything (6.3.9): one builder, one
            handler per kind of error, and `install_error_handlers(app)`. The 422 handler
            lists location, message and type of each problem but never echoes the input:
            """
        ),
        *writefile_cells(
            NOTES_V2_CORE_ERRORS_PY,
            [
                ("", "Part 1 of `errors.py`: imports and the documented problem model."),
                ("def problem_response(", "Part 2: the response builder (adds the request id)."),
                (
                    "async def domain_error_handler(",
                    "Part 3: handlers for domain errors, HTTPException and validation.",
                ),
                (
                    "async def unhandled_error_handler(",
                    "Part 4: the generic 500 and the installer.",
                ),
            ],
        ),
        md(
            """
            **`models.py`.** The domain record is still a dataclass; Unit 6.4 turns it into a
            SQLAlchemy model:
            """
        ),
        code(NOTES_V2_MODELS_PY),
        md(
            """
            **`schemas.py`.** v1's schemas, minus the page and error envelopes (now generic, in
            `pagination.py` and `core/errors.py`), plus three new ones: the feed's query
            parameters, a link preview and the import report:
            """
        ),
        *writefile_cells(
            NOTES_V2_SCHEMAS_PY,
            [
                ("", "Part 1 of `schemas.py`: imports and the tag helpers."),
                ("Title = Annotated[", "Part 2: reusable `Annotated` types."),
                ("class NoteCreate(BaseModel):", "Part 3: `NoteCreate`."),
                ("class NoteUpdate(BaseModel):", "Part 4: `NoteUpdate` (rejects explicit `null`)."),
                (
                    "class NoteRead(BaseModel):",
                    "Part 5: `NoteRead` and the query model `NoteFilters`.",
                ),
                (
                    "class FeedParams(BaseModel):",
                    "Part 6: feed parameters, link previews, import reports.",
                ),
            ],
        ),
        md(
            """
            **`pagination.py`.** `Page[T]` and `CursorPage[T]` (6.3.12) and the opaque cursor:
            URL-safe base64 of `[created_at, id]`; anything else is an `InvalidCursorError`
            (a 400 problem):
            """
        ),
        *writefile_cells(
            NOTES_V2_PAGINATION_PY,
            [
                ("", "Part 1 of `pagination.py`: the generic envelopes."),
                ("def encode_cursor(", "Part 2: encoding and validating cursors."),
            ],
        ),
        md(
            """
            **`repositories.py`.** The storage boundary. The service depends on the
            `NoteRepository` **Protocol**; `InMemoryNoteRepository` is v2's implementation
            (v1's `NoteStore`, now async so the SQL version in 6.4 is a drop-in). It returns
            copies, so callers cannot change stored notes by accident:
            """
        ),
        *writefile_cells(
            NOTES_V2_REPOSITORIES_PY,
            [
                ("", "Part 1 of `repositories.py`: docstring and imports."),
                ("class NoteRepository(Protocol):", "Part 2: the Protocol the service depends on."),
                ("def matches(", "Part 3: filtering and sorting helpers (from v1)."),
                (
                    "class InMemoryNoteRepository:",
                    "Part 4: the in-memory implementation: add, get, search.",
                ),
                (
                    '    async def feed(self, limit: int, after: CursorKey | None) -> list[Note]:\n        """Newest',
                    "Part 5: the keyset feed, update and delete (continues the class).",
                ),
            ],
        ),
        md(
            """
            **`services.py`.** The use cases: `NoteService` (with the PATCH rule "`updated_at`
            moves only on a real change"), `parse_import` for uploaded `.json`/`.csv` files, and
            `LinkPreviewer`, which fetches page titles concurrently through the shared client.
            Nothing here imports FastAPI:
            """
        ),
        *writefile_cells(
            NOTES_V2_SERVICES_PY,
            [
                ("", "Part 1 of `services.py`: imports and constants."),
                ("class NoteService:", "Part 2: `NoteService`: create, get, search, feed."),
                (
                    "    async def replace(",
                    "Part 3: replace, update, delete, import, wipe (continues the class).",
                ),
                ("def parse_import(", "Part 4: parsing an uploaded file into validated notes."),
                (
                    "class LinkPreviewer:",
                    "Part 5: link previews through the lifespan's HTTP client.",
                ),
            ],
        ),
        md(
            """
            **`core/lifespan.py`.** One repository and one pooled `httpx.AsyncClient` per app,
            closed on shutdown (6.3.10):
            """
        ),
        code(NOTES_V2_CORE_LIFESPAN_PY),
    ]


def _notes_v2_http_cells() -> list[NotebookNode]:
    """Notes API v2: dependencies, routers, templates and the factory."""
    return [
        md(
            """
            **`dependencies.py`.** Where `Depends` replaces the module-level store: small
            functions read what the lifespan created from `request.app.state`, build a
            `NoteService` per request, and check the API key. Routers import only the
            `Annotated` aliases. The docstring draws the resolution graph:
            """
        ),
        *writefile_cells(
            NOTES_V2_DEPENDENCIES_PY,
            [
                (
                    "",
                    "Part 1 of `dependencies.py`: the graph, imports and the API-key header scheme.",
                ),
                (
                    "def get_app_settings(",
                    "Part 2: getters for app-scoped objects and their aliases.",
                ),
                (
                    "def get_note_service(",
                    "Part 3: the service, the link previewer and the router-level key check.",
                ),
            ],
        ),
        md("The routers package and the health router:"),
        code(NOTES_V2_ROUTERS_INIT_PY),
        md("The health router: an unversioned `/health` liveness probe:"),
        code(NOTES_V2_ROUTERS_HEALTH_PY),
        md(
            """
            **`routers/notes.py`.** The v1 operations on an `APIRouter(prefix="/notes")` (the
            app adds `/api/v1`), each one line of HTTP translation around a service call, plus
            the feed (declared before `/{note_id}`) and link previews:
            """
        ),
        *writefile_cells(
            NOTES_V2_ROUTERS_NOTES_PY,
            [
                ("", "Part 1 of `routers/notes.py`: shared types and the router."),
                (
                    '@router.post("", response_model=NoteRead',
                    "Part 2: create, list (offset pages) and the keyset feed.",
                ),
                (
                    '@router.get("/{note_id}", response_model=NoteRead',
                    "Part 3: one note: get, put, patch, delete, links.",
                ),
            ],
        ),
        md(
            """
            **`routers/admin.py`.** The router-level API key (`dependencies=[ApiKeyDep]`) guards
            every admin route. `read_upload` checks extension, declared type and size
            (`max_bytes + 1` read) before `parse_import` validates the content:
            """
        ),
        *writefile_cells(
            NOTES_V2_ROUTERS_ADMIN_PY,
            [
                ("", "Part 1 of `routers/admin.py`: the guarded router and upload checks."),
                ('@router.post("/import"', "Part 2: import, export and wipe."),
            ],
        ),
        md(
            """
            **`routers/pages.py`.** The HTML side (6.3.13): the page, the HTMX fragment for
            search (same route, chosen by the `HX-Request` header), the form with
            Post/Redirect/Get, and an HTMX pin toggle. `include_in_schema=False` keeps it out
            of the API docs:
            """
        ),
        *writefile_cells(
            NOTES_V2_ROUTERS_PAGES_PY,
            [
                ("", "Part 1 of `routers/pages.py`: templates and the page."),
                (
                    '@router.post("/notes", response_class=HTMLResponse)',
                    "Part 2: the form and the pin toggle.",
                ),
            ],
        ),
        md("The templates: a layout, the page, the list fragment and one note:"),
        code(NOTES_V2_TEMPLATES_BASE_HTML),
        md("The page: the new-note form, the HTMX search box and the list:"),
        code(NOTES_V2_TEMPLATES_INDEX_HTML),
        md("The list fragment, which HTMX swaps in after a search:"),
        code(NOTES_V2_TEMPLATES_NOTES_HTML),
        md("One note, with a pin button that replaces only this item:"),
        code(NOTES_V2_TEMPLATES_NOTE_HTML),
        md("The stylesheet `StaticFiles` serves:"),
        code(NOTES_V2_STATIC_STYLE_CSS),
        md(
            """
            **`main.py`.** The factory wires it all, in this order: settings on `app.state`,
            error handlers, middleware (request id outermost, then CORS, GZip, timing), the
            routers (JSON under `/api/v1`), the static mount:
            """
        ),
        *writefile_cells(
            NOTES_V2_MAIN_PY,
            [
                ("", "Part 1 of `main.py`: imports and constants."),
                ("def operation_id(", "Part 2: operation ids and the middleware stack."),
                ("def create_app(", "Part 3: the factory, and the module-level app for `uvicorn`."),
            ],
        ),
    ]


def _notes_v2_test_cells() -> list[NotebookNode]:
    """Notes API v2: the test suite."""
    return [
        md(
            """
            **Tests.** No more resetting a global: the `app` fixture builds a fresh app with
            test settings (a key generated per run, a small upload limit, no `.env`), so every
            test starts empty. Helpers live in `tests/helpers.py`:
            """
        ),
        *writefile_cells(
            NOTES_V2_TESTS_CONFTEST_PY,
            [
                ("", "Part 1 of `conftest.py`: test settings."),
                (
                    "@pytest.fixture\ndef app(",
                    "Part 2: one app per test, its client, admin headers.",
                ),
            ],
        ),
        md("`tests/helpers.py`: small functions the test modules share (create a note, list ids):"),
        code(NOTES_V2_TESTS_HELPERS_PY),
        md("The v1 behaviour tests, moved to `/api/v1` and Problem Details:"),
        *writefile_cells(
            NOTES_V2_TESTS_TEST_NOTES_PY,
            [
                ("", "Part 1 of `test_notes.py`: health and creating notes."),
                (
                    '@pytest.mark.parametrize(\n    ("body", "location")',
                    "Part 2: invalid input, fetching one note.",
                ),
                (
                    "def test_list_paginates_and_counts_all_matches(",
                    "Part 3: listing and filtering.",
                ),
                ("def test_put_replaces_every_field(", "Part 4: PUT and PATCH."),
                (
                    '@pytest.mark.parametrize("body"',
                    "Part 5: bad PATCH bodies, DELETE, 404s, OpenAPI.",
                ),
            ],
        ),
        md("Cursor pagination:"),
        code(NOTES_V2_TESTS_TEST_PAGINATION_PY),
        md("The admin router: the key, the uploads, export and wipe:"),
        *writefile_cells(
            NOTES_V2_TESTS_TEST_ADMIN_PY,
            [
                ("", "Part 1 of `test_admin.py`: the router-level key."),
                (
                    '@pytest.mark.parametrize(\n    ("filename", "content", "content_type"),\n    [(',
                    "Part 2: importing JSON and CSV.",
                ),
                (
                    '@pytest.mark.parametrize(\n    ("filename", "content", "content_type", "status")',
                    "Part 3: rejected uploads, export and wipe.",
                ),
            ],
        ),
        md("Middleware and CORS:"),
        *writefile_cells(
            NOTES_V2_TESTS_TEST_MIDDLEWARE_PY,
            [
                ("", "Part 1 of `test_middleware.py`: request ids and timing."),
                ("def test_large_responses_are_gzipped(", "Part 2: GZip and CORS."),
                (
                    "def test_simple_cors_request_exposes_headers(",
                    "Part 3: exposed headers and the stack order.",
                ),
            ],
        ),
        md("Problem Details:"),
        code(NOTES_V2_TESTS_TEST_ERRORS_PY),
        md("Settings:"),
        *writefile_cells(
            NOTES_V2_TESTS_TEST_SETTINGS_PY,
            [
                ("", "Part 1 of `test_settings.py`: environment variables and `.env`."),
                (
                    "def test_secret_is_hidden_in_repr_and_dumps(",
                    "Part 2: secrets, production rules, caching.",
                ),
            ],
        ),
        md("Link previews with `respx` faking the remote sites, and the client's lifetime:"),
        *writefile_cells(
            NOTES_V2_TESTS_TEST_LINKS_PY,
            [
                ("", "Part 1 of `test_links.py`: fetching titles."),
                (
                    "def test_the_client_lives_as_long_as_the_app(",
                    "Part 2: the lifespan opens and closes the client.",
                ),
            ],
        ),
        md("The HTML pages:"),
        *writefile_cells(
            NOTES_V2_TESTS_TEST_PAGES_PY,
            [
                ("", "Part 1 of `test_pages.py`: the page and the HTMX search fragment."),
                (
                    "def test_form_post_redirects_with_303(",
                    "Part 2: forms, the pin toggle and static files.",
                ),
            ],
        ),
    ]


def _notes_v2_run_cells() -> list[NotebookNode]:
    """Notes API v2: try it, test it, serve it."""
    return [
        md(
            """
            **Try it in the kernel.** Import the package from the files just written, build an
            app with test settings (a key generated now) and walk through the new features:
            """
        ),
        code(
            r"""
            notes_main = reload_notes_api()  # re-imports every notes_api module from disk
            NotesSettings = sys.modules["notes_api.core.config"].Settings

            demo_key = secrets.token_urlsafe(16)
            notes_settings = NotesSettings(_env_file=None, environment="test", api_key=demo_key)
            notes_v2 = notes_main.create_app(notes_settings)

            with TestClient(notes_v2) as client:
                created = client.post(
                    "/api/v1/notes",
                    json={"title": "Buy tea", "tags": ["shop"]},
                    headers={"X-Request-ID": "demo-1"},
                )
                print(
                    created.status_code,
                    created.headers["location"],
                    created.headers["x-request-id"],
                    {key: value for key, value in created.json().items() if not key.endswith("_at")},
                )
                show_response(client.get("/api/v1/notes/42", headers={"X-Request-ID": "demo-2"}))
                csv_file = ("notes.csv", b"title,tags\nCall Ravi,home\nPlan the trip,travel;home\n", "text/csv")
                show_response(
                    client.post(
                        "/api/v1/admin/import", files={"file": csv_file}, headers={"X-API-Key": demo_key}
                    )
                )
                show_response(
                    client.post(
                        "/api/v1/admin/import", files={"file": csv_file}, headers={"X-Request-ID": "demo-3"}
                    )
                )
                feed = client.get("/api/v1/notes/feed", params={"limit": 2}).json()
                print(
                    [note["title"] for note in feed["items"]], "next cursor:", feed["next_cursor"] is not None
                )
                print("HTML page:", client.get("/").text.count('class="note'), "notes rendered")
            """
        ),
        md(
            """
            **Run this version's tests** with the kernel's environment (the root project has the
            same packages). Each unit runs only the test files its version adds or changes
            (`NEW_TESTS`; in v2 that is every test file); the full suite runs once, in the Phase 6 Project:
            """
        ),
        code(
            r"""
            NEW_TESTS = __NEW_TESTS__
            pytest_run = run_in_notes(sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *NEW_TESTS)
            print(tidy_test_output(pytest_run.stdout + pytest_run.stderr).splitlines()[-1])
            print(f"{pytest_run.returncode=}")
            """
        ),
        md(
            """
            And as its own uv project: `uv lock` adds `pydantic-settings` and `respx` to
            `projects/notes_api/uv.lock`, and `uv run --frozen pytest` runs the same tests in the
            project's own `.venv`:
            """
        ),
        code(
            r"""
            if HAS_UV:
                lock_run = run_in_notes("uv", "lock")
                print(lock_summary(lock_run.stderr))
                if lock_run.returncode == 0:
                    uv_pytest = run_in_notes(
                        "uv", "run", "--frozen", "pytest", "-p", "no:cacheprovider", *NEW_TESTS
                    )
                    print(
                        tidy_test_output(uv_pytest.stdout).splitlines()[-1],
                        f"(exit code {uv_pytest.returncode})",
                    )
                else:
                    print("SKIP uv run pytest: uv lock failed (offline with an empty cache?)")
            else:
                print("SKIP: the uv command is not on PATH")
            """
        ),
        md(
            """
            **Serve it for real.** Uvicorn runs `notes_api.main:app` in a child process; the key
            comes from an environment variable generated for this run (the way a deployment
            injects secrets), not from a file. One request shows the middleware at work:
            `X-Request-ID`, `Server-Timing`, and gzip for a large response:
            """
        ),
        code(
            r"""
            served_key = secrets.token_urlsafe(16)
            server_env = {"NOTES_API_KEY": served_key, "NOTES_ENVIRONMENT": "production"}
            with uvicorn_server("notes_api.main:app", app_dir=NOTES_SRC, extra_env=server_env) as base_url:
                with httpx.Client(base_url=base_url, trust_env=False) as client:
                    for number in range(15):
                        client.post(
                            "/api/v1/notes", json={"title": f"Note {number}", "body": "lorem ipsum " * 10}
                        )
                    listing = client.get("/api/v1/notes", headers={"Accept-Encoding": "gzip"})
                    print(
                        listing.status_code,
                        listing.headers["content-encoding"],
                        re.sub(r"[\d.]+$", "<ms>", listing.headers["server-timing"]),
                    )
                    print("request id:", len(listing.headers["x-request-id"]), "hex characters")
                    print("admin without key:", client.delete("/api/v1/admin/notes").status_code)
                    print(
                        "admin with key:",
                        client.delete("/api/v1/admin/notes", headers={"X-API-Key": served_key}).json(),
                    )
                    print(
                        "docs page:",
                        client.get("/docs").status_code,
                        " HTML page:",
                        client.get("/").headers["content-type"],
                    )
            """
        ),
        md("The project now looks like this:"),
        code(
            r"""
            print(notes_tree())
            """
        ),
        md(
            """
            What v2 deliberately leaves for later: data lives in memory and disappears on
            restart (Unit 6.4: PostgreSQL, SQLAlchemy, Alembic); one shared API key instead of
            users (6.5: authentication, ownership, CSRF for the pages); link previews fetch
            arbitrary URLs from the server, a server-side request forgery risk that 6.5
            closes; no background jobs or caching (6.6); logs, metrics and traces (6.7);
            container and deployment (6.8).
            """
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 6.3."""
    return [
        md(
            """
            ### Recap — Unit 6.3

            | Concept | One-line takeaway | JS / TS equivalent |
            | --- | --- | --- |
            | `Depends` | a callable resolved from the request; nested, parameterized (classes, factories), cached per request; share it with `Annotated` aliases | NestJS providers, but wired by signatures |
            | `yield` dependencies | setup / teardown around the handler, exceptions thrown in at `yield`; `scope="function"` to finish before the response | `try/finally` in middleware |
            | Dependency scopes | `dependencies=[...]` on the app, a router or a route; `dependency_overrides` swaps any dependency in tests | `overrideProvider`, `jest.mock` |
            | Project structure | `create_app()` factory; routers → services → repositories → models; core for config/errors/middleware | NestJS modules / layered Express apps |
            | `APIRouter` | prefix, tags, dependencies, responses per router; nest routers; version with `/v1`, `/v2` | `express.Router()`, Fastify plugins |
            | Configuration | `BaseSettings`: env vars, `.env`, nested, `SecretStr`, validated at startup; cached getter | `dotenv` + zod |
            | Middleware | `BaseHTTPMiddleware` is easy, pure ASGI is cheaper and keeps context; last added runs first; request ids in a `ContextVar` | Express middleware, `AsyncLocalStorage` |
            | CORS | the browser asks (preflight), `CORSMiddleware` answers; not a security boundary | the `cors` package |
            | Errors | domain exceptions + handlers by class; override validation errors; RFC 9457 `application/problem+json` | error middleware, `http-problem-details` |
            | Lifespan | create pools and clients once, close them on shutdown; `TestClient` needs `with` | server `listen` / `close` hooks |
            | Requests | headers, cookies, forms, `UploadFile`; check content signatures and sizes; limit bodies at the edge | `multer`, `cookie-parser` |
            | Pagination | offsets shift and slow down; keyset cursors are stable and indexed; generic `Page[T]` | cursor connections (GraphQL) |
            | Server-rendered pages | Jinja2 (autoescaping), `StaticFiles`, Post/Redirect/Get, HTMX fragments | EJS / Handlebars + htmx |

            **Further reading**

            - FastAPI: [dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/),
              [dependencies with yield](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/),
              [testing dependencies](https://fastapi.tiangolo.com/advanced/testing-dependencies/),
              [bigger applications](https://fastapi.tiangolo.com/tutorial/bigger-applications/),
              [settings](https://fastapi.tiangolo.com/advanced/settings/),
              [middleware](https://fastapi.tiangolo.com/tutorial/middleware/),
              [CORS](https://fastapi.tiangolo.com/tutorial/cors/),
              [handling errors](https://fastapi.tiangolo.com/tutorial/handling-errors/),
              [lifespan events](https://fastapi.tiangolo.com/advanced/events/),
              [request files](https://fastapi.tiangolo.com/tutorial/request-files/),
              [templates](https://fastapi.tiangolo.com/advanced/templates/)
            - [Starlette middleware](https://www.starlette.io/middleware/),
              [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/),
              [HTMX documentation](https://htmx.org/docs/)
            - Python: [`contextvars`](https://docs.python.org/3/library/contextvars.html),
              [`contextlib`](https://docs.python.org/3/library/contextlib.html),
              [`http.HTTPStatus`](https://docs.python.org/3/library/http.html#http.HTTPStatus),
              [`ast`](https://docs.python.org/3/library/ast.html),
              [`functools.lru_cache`](https://docs.python.org/3/library/functools.html#functools.lru_cache)
            - Standards: [RFC 9457 Problem Details](https://www.rfc-editor.org/rfc/rfc9457),
              [Fetch standard: CORS](https://fetch.spec.whatwg.org/#http-cors-protocol),
              [RFC 6265 cookies](https://www.rfc-editor.org/rfc/rfc6265),
              [The Twelve-Factor App: config](https://12factor.net/config),
              [PEP 695](https://peps.python.org/pep-0695/) (generic classes),
              [PEP 567](https://peps.python.org/pep-0567/) (context variables)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 6.3, Lab 6.3 and Notes API v2."""
    return [
        *_overview_cells(),
        *_depends_cells(),
        *_yield_cells(),
        *_scope_cells(),
        *_structure_cells(),
        *_router_cells(),
        *_settings_cells(),
        *_middleware_cells(),
        *_cors_cells(),
        *_error_cells(),
        *_lifespan_cells(),
        *_request_cells(),
        *_pagination_cells(),
        *_pages_cells(),
        *_predict_cells(),
        *_lab_setup_cells(),
        *_lab_exercise_1_2_cells(),
        *_lab_exercise_3_4_cells(),
        *_lab_exercise_5_6_cells(),
        *_notes_v2_intro_cells(),
        *_notes_v2_core_cells(),
        *_notes_v2_http_cells(),
        *_notes_v2_test_cells(),
        *_notes_v2_run_cells(),
        *_recap_cells(),
    ]
