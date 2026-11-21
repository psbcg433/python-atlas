"""Unit 6.2 — FastAPI Fundamentals and Pydantic v2 (with Lab 6.2 and Notes API v1)."""

from helpers_module import setup_cells
from nbformat import NotebookNode

from nb_builder import code, md, predict_cells, writefile_cells

UNIT_SETUP_SOURCE = r"""
import asyncio
import contextlib
import dataclasses
import importlib
import importlib.util
import inspect
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import typing
import urllib.request
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

import anyio
import fastapi
import httpx
import pydantic
import starlette
import uvicorn
from fastapi import Body, FastAPI, HTTPException, Query, Response, status
from fastapi import Path as PathParam  # fastapi.Path, renamed: pathlib.Path is used for files
from fastapi.testclient import TestClient
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    HttpUrl,
    TypeAdapter,
    ValidationError,
    computed_field,
    field_validator,
    model_validator,
)

"""

NOTES_HELPERS_SOURCE = r'''
def reload_notes_api() -> ModuleType:
    """Forget every notes_api module and import notes_api.main again from the files on disk."""
    for cache_folder in NOTES_SRC.rglob("__pycache__"):
        shutil.rmtree(cache_folder)  # a .pyc written in the same second could hide an edit
    for module_name in [name for name in sys.modules if name.split(".")[0] == "notes_api"]:
        del sys.modules[module_name]
    importlib.invalidate_caches()
    return importlib.import_module("notes_api.main")


def validation_problems(thunk: Callable[[], object]) -> list[tuple[str, str]] | str:
    """Run thunk; list (dotted location, error type) for each validation problem, or "no error"."""
    try:
        thunk()
    except ValidationError as error:
        return [(".".join(map(str, problem["loc"])), problem["type"]) for problem in error.errors()]
    return "no error"


def tidy_test_output(text: str) -> str:
    """Hide timings and machine paths in pytest / uv output."""
    text = re.sub(r"\d+(\.\d+)?m?s\b", "<time>", text)
    return text.replace(str(REPO_ROOT), "<repo>").strip()


print(interpreter_label())
print(f"{fastapi.__version__=}  {starlette.__version__=}")
print(f"{pydantic.VERSION=}  {uvicorn.__version__=}")
print(f"{HAS_NODE=}  {HAS_UV=}  Notes API folder: {NOTES_API_DIR.relative_to(REPO_ROOT)}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 6.2 — FastAPI Fundamentals and Pydantic v2

            **Objectives**

            - Explain what FastAPI adds on top of Starlette and Pydantic, and trace a request
              through it.
            - Declare path operations with typed path, query and body parameters, including
              enums, path converters, constrained `Annotated` parameters and query-parameter
              models.
            - Model data with Pydantic v2: field types and constraints, validators, computed
              fields, serialization options, configuration, strict mode, `TypeAdapter`, custom
              `Annotated` types, and validation errors.
            - Design separate Create / Update / Read schemas and implement PATCH correctly.
            - Shape responses: response models, status codes, response classes, headers,
              cookies, `HTTPException`.
            - Choose between `async def` and `def` handlers, and prove the difference under
              load.
            - Use and customize the generated OpenAPI docs, and generate a TypeScript client.
            - Explain how FastAPI turns a function signature into a validated endpoint.
            - Start the **Notes API** (`projects/notes_api/`) that the rest of Phase 6 grows.

            **JS bridge**

            | JavaScript / TypeScript | FastAPI + Pydantic | The difference that bites |
            | --- | --- | --- |
            | Express route + `req.params` / `req.query` | typed function parameters | values arrive **converted and validated**; a bad `int` is a 422, not `NaN` |
            | zod schema + `z.infer<typeof Schema>` | a Pydantic model **is** the type | one class gives validation, the static type, serialization and the JSON Schema |
            | `schema.parse(data)` / `safeParse` | `Model.model_validate(data)` raises `ValidationError` | errors are a structured list (`errors()`), not one message |
            | NestJS DTO + `class-validator` decorators | Pydantic model + `Field(...)` constraints | constraints live in type hints (`Annotated`) |
            | `@nestjs/swagger`, `fastify-swagger` | built in: `/docs`, `/redoc`, `/openapi.json` | the docs come from the same types that validate, so they cannot drift |
            | Supertest (`request(app).get(...)`) | `TestClient(app).get(...)` | in-process, no port; `httpx.AsyncClient` + `ASGITransport` for async tests |
            | `async` everywhere in Node | `async def` **or** `def` handlers | a blocking call inside `async def` freezes every request; `def` runs in a thread pool |

            Run the setup cells first. Part 1: the imports (FastAPI, Starlette, Pydantic,
            Uvicorn):
            """
        ),
        *setup_cells(
            "6.2",
            UNIT_SETUP_SOURCE,
            """
            Part 2: the shared helpers. `from phase6_helpers import *` loads [`phase6_helpers.py`](phase6_helpers.py), the
            module that holds every helper Phase 6 shares: Unit 6.1's error and timing helpers
            (`raised_error_name`, `raised_message`, `interpreter_label`, `Timer`, `fresh_import`,
            `mask_dates`) and server helpers (`free_port`, `wait_for_health`,
            `background_server`, `uvicorn_server`: start a server in a child process, wait for
            `/health`, always stop it), plus three this unit introduces for the Notes API:
            `reload_notes_api()` re-imports the app after a `%%writefile` cell changed it,
            `validation_problems()` lists a `ValidationError`'s problems, and
            `tidy_test_output()` hides timings in pytest output. `enter_phase6(*NOTES_FOLDERS)`
            creates `projects/notes_api/src/notes_api/` and `tests/` and puts `src/` on
            `sys.path`, so the kernel can import the app the notebook writes:
            """,
            folders="*NOTES_FOLDERS",
        ),
    ]


def _architecture_cells() -> list[NotebookNode]:
    """6.2.1 Architecture."""
    return [
        md(
            """
            ### 6.2.1 Architecture

            FastAPI is a thin layer that joins three things:

            | Part | Provides | You saw it in |
            | --- | --- | --- |
            | **Starlette** | the ASGI app, routing, `Request`/`Response`, middleware, WebSockets, `TestClient` | 6.1.6–6.1.7 |
            | **Pydantic v2** | parsing and validating input, serializing output, JSON Schema (its core is written in Rust) | Unit 4.6, 6.2.5 |
            | **OpenAPI** | a machine-readable description of every route, generated from the same type hints; served at `/openapi.json` with Swagger UI at `/docs` and ReDoc at `/redoc` | 6.2.9 |

            What FastAPI itself adds: reading your function signature to decide where each
            parameter comes from (path, query, header, cookie, body), dependency injection
            (Unit 6.3), and wiring validation errors to 422 responses.

            **Request lifecycle**

            ```mermaid
            flowchart TD
                A["Uvicorn: bytes → ASGI scope + messages"] --> B["Middleware stack<br/>(ServerErrorMiddleware → user middleware → ExceptionMiddleware)"]
                B --> C["Router: match method + path → APIRoute"]
                C --> D["Solve parameters and dependencies<br/>path, query, headers, cookies, body"]
                D -->|"invalid"| E["RequestValidationError → 422 JSON"]
                D -->|"valid"| F["Call your endpoint<br/>async def: on the loop · def: in the thread pool"]
                F -->|"raises HTTPException"| G["exception handler → error JSON"]
                F -->|"returns a value"| H["Validate/serialize with response_model"]
                H --> I["JSONResponse → ASGI messages → Uvicorn → bytes"]
            ```

            <details><summary>ASCII version</summary>

            ```text
            Uvicorn (bytes → scope/messages)
              → middleware stack (ServerErrorMiddleware → yours → ExceptionMiddleware)
                → router: match method + path → APIRoute
                  → solve params/dependencies (path, query, header, cookie, body)
                      invalid → RequestValidationError → 422
                  → call endpoint (async def on the loop; def in the thread pool)
                      HTTPException → handler → error JSON
                  → response_model validation + serialization
                → JSONResponse → ASGI messages → Uvicorn → bytes
            ```

            </details>

            `FastAPI` **is** a Starlette application (a subclass), so everything from 6.1.6
            applies: it is an ASGI callable with `(scope, receive, send)`. A new app already
            has three routes, the docs:
            """
        ),
        code(
            """
            from starlette.applications import Starlette

            hello_app = FastAPI()
            print(f"{FastAPI.__mro__[1]=}")
            print(f"{issubclass(FastAPI, Starlette)=}  {inspect.iscoroutinefunction(FastAPI.__call__)=}")
            for route in hello_app.routes:
                print(f"{type(route).__name__:<6} {route.path}")
            """
        ),
        md(
            """
            The middleware stack is built on the first request. Each layer wraps the next,
            exactly like the request-id middleware in 6.1.6. Walking the `.app` attributes shows
            the onion, from the outside in: Starlette's `ServerErrorMiddleware` (turns crashes
            into 500s), FastAPI's `ExceptionTelemetryMiddleware` (built-in OpenTelemetry hooks,
            inactive until a tracer or meter provider is configured, Unit 6.7), the user
            middleware (`BaseHTTPMiddleware` wraps the decorated function), `ExceptionMiddleware`
            (runs exception handlers such as the 422 one), `AsyncExitStackMiddleware` (cleans up
            `yield` dependencies, Unit 6.3), and finally the router. The exact layers vary by
            version:
            """
        ),
        code(
            """
            from starlette.routing import Router


            @hello_app.middleware("http")
            async def add_timing_header(
                request: fastapi.Request, call_next: Callable[..., Awaitable[Response]]
            ) -> Response:
                \"\"\"A user middleware: runs before and after every request.\"\"\"
                response = await call_next(request)
                response.headers["x-handled-by"] = "add_timing_header"
                return response


            layer: Any = hello_app.build_middleware_stack()
            while not isinstance(layer, Router):
                print(type(layer).__name__)
                layer = layer.app
            print(type(layer).__name__, "(the router: matches the path, calls the endpoint)")
            """
        ),
        md(
            """
            The lifecycle, observed. The endpoint prints when it runs; a valid request goes
            through the middleware and the endpoint; an invalid one is rejected with 422
            **before** the endpoint is called (no "endpoint called" line):
            """
        ),
        code(
            '''
            @hello_app.get("/square/{number}")
            async def square(number: int) -> dict[str, int]:
                """Square a number taken from the path."""
                print(f"  endpoint called with {number=} ({type(number).__name__})")
                return {"number": number, "square": number * number}


            with TestClient(hello_app) as client:
                print("GET /square/12")
                ok = client.get("/square/12")
                print(f"  -> {ok.status_code} {ok.json()} x-handled-by={ok.headers['x-handled-by']}")
                print("GET /square/twelve")
                bad = client.get("/square/twelve")
                print(f"  -> {bad.status_code} {bad.json()['detail'][0]['msg']}")
            '''
        ),
    ]


def _path_operation_cells() -> list[NotebookNode]:
    """6.2.2 Path operations."""
    return [
        md(
            """
            ### 6.2.2 Path operations

            A **path operation** is a path plus an HTTP method plus the function that handles
            it. There is one decorator per method, and `api_route` for several at once:

            | Decorator | Typical use |
            | --- | --- |
            | `@app.get(path)` | read |
            | `@app.post(path)` | create |
            | `@app.put(path)` | replace |
            | `@app.patch(path)` | partial update |
            | `@app.delete(path)` | delete |
            | `@app.head(path)`, `@app.options(path)`, `@app.trace(path)` | rarely written by hand (CORS middleware answers OPTIONS preflights, Unit 6.3) |
            | `@app.api_route(path, methods=[...])` | one function for several methods |

            A small catalog API shows each decorator. `TestClient` calls the ASGI app
            in-process (like Supertest), so no server is needed:
            """
        ),
        code(
            '''
            catalog_app = FastAPI(title="Catalog demo")
            CATALOG: dict[int, str] = {1: "Assam tea", 2: "Clay mug"}


            @catalog_app.get("/items")
            async def list_items() -> dict[int, str]:
                """GET: read the collection."""
                return CATALOG


            @catalog_app.post("/items", status_code=201)
            async def add_item(name: str) -> dict[str, object]:
                """POST: create (name comes from the query string here; bodies are 6.2.4)."""
                item_id = max(CATALOG) + 1
                CATALOG[item_id] = name
                return {"id": item_id, "name": name}


            @catalog_app.put("/items/{item_id}")
            async def replace_item(item_id: int, name: str) -> dict[str, object]:
                """PUT: replace the item at a known URL."""
                CATALOG[item_id] = name
                return {"id": item_id, "name": name}


            @catalog_app.delete("/items/{item_id}", status_code=204)
            async def delete_item(item_id: int) -> None:
                """DELETE: no body in the response (204)."""
                CATALOG.pop(item_id, None)


            @catalog_app.api_route("/ping", methods=["GET", "POST"])
            async def ping(request: fastapi.Request) -> dict[str, str]:
                """One function, two methods."""
                return {"method": request.method}
            '''
        ),
        md(
            """
            Exercise every route. Two details: JSON object keys are always strings, so the
            `int` keys of `CATALOG` arrive as `"2"`, `"3"`; and only declared methods are routed,
            so `HEAD` and `PATCH` get **405 Method Not Allowed** (plain Starlette routes answer
            `HEAD` for every `GET` route; FastAPI's do not, unless you add `"HEAD"` with
            `api_route`):
            """
        ),
        code(
            """
            with TestClient(catalog_app) as client:
                print(client.post("/items", params={"name": "Steel kettle"}).json())
                print(client.put("/items/2", params={"name": "Glass mug"}).json())
                print(client.delete("/items/1").status_code, client.get("/items").json())
                print(client.get("/ping").json(), client.post("/ping").json())
                print(f"{client.head('/items').status_code=}  {client.patch('/items/2').status_code=}")
            """
        ),
        md(
            """
            #### Typed path parameters

            A `{name}` in the path becomes the function parameter with the same name. Its
            annotation decides the conversion: `/items/7` gives `item_id == 7` as an `int`;
            `/items/seven` is rejected with **422** and a structured error, before your code
            runs. Constraints (`ge`, `le`, …) go in `fastapi.Path` (imported here as
            `PathParam`, because `pathlib.Path` is also in use):
            """
        ),
        code(
            '''
            orders_app = FastAPI()


            @orders_app.get("/orders/{order_id}")
            async def get_order(order_id: Annotated[int, PathParam(ge=1, le=9999)]) -> dict[str, object]:
                """A path parameter that must be an int from 1 to 9999."""
                return {"order_id": order_id, "type": type(order_id).__name__}


            with TestClient(orders_app) as client:
                for path in ("/orders/42", "/orders/forty-two", "/orders/0"):
                    response = client.get(path)
                    print(f"{path:<20} {response.status_code} {response.json()}")
            '''
        ),
        md(
            """
            #### Enum path parameters

            A `StrEnum` (*new in 3.11*) restricts a parameter to fixed values, and the allowed
            values appear in the docs as a drop-down. An unknown value is a 422 listing the
            choices:
            """
        ),
        code(
            '''
            class ReportPeriod(StrEnum):
                """Allowed values for the {period} path parameter."""

                DAY = "day"
                WEEK = "week"
                MONTH = "month"


            reports_app = FastAPI()


            @reports_app.get("/reports/{period}")
            async def get_report(period: ReportPeriod) -> dict[str, object]:
                """period arrives as a ReportPeriod member, not a plain string."""
                return {
                    "period": period,
                    "is_member": isinstance(period, ReportPeriod),
                    "days": {"day": 1, "week": 7, "month": 30}[period],
                }


            with TestClient(reports_app) as client:
                print(client.get("/reports/week").json())
                print(client.get("/reports/year").json()["detail"][0]["msg"])
            '''
        ),
        md(
            """
            #### Path converters

            A plain `{name}` matches one segment (no `/`). Starlette's converters change that:
            `{file_path:path}` matches the rest of the path including slashes, and `int`,
            `float`, `uuid` converters match only those shapes (FastAPI still validates with
            the annotation):
            """
        ),
        code(
            '''
            files_app = FastAPI()


            @files_app.get("/files/{file_path:path}")
            async def read_file_info(file_path: str) -> dict[str, str]:
                """file_path may contain slashes."""
                return {"file_path": file_path}


            @files_app.get("/users/{user_id:uuid}")
            async def get_user(user_id: UUID) -> dict[str, str]:
                """Only UUID-shaped segments match this route."""
                return {"user_id": str(user_id), "version": f"v{user_id.version}"}


            with TestClient(files_app) as client:
                print(client.get("/files/reports/2026/november.csv").json())
                print(client.get("/users/12345678-1234-4678-9234-567812345678").json())
                print(client.get("/users/not-a-uuid").status_code, "(no route matched)")
            '''
        ),
        md(
            """
            #### Route ordering

            Routes are tried **in the order they were declared**; the first match wins (like
            Express). A fixed path such as `/users/me` must therefore come before
            `/users/{username}`, or the parameterized route captures it:
            """
        ),
        code(
            '''
            def build_users_app(me_first: bool) -> FastAPI:
                """Declare /users/me before or after /users/{username}."""
                users_app = FastAPI()

                async def read_me() -> dict[str, str]:
                    """The fixed route."""
                    return {"route": "current user"}

                async def read_user(username: str) -> dict[str, str]:
                    """The parameterized route."""
                    return {"route": f"user {username!r}"}

                routes = [("/users/me", read_me), ("/users/{username}", read_user)]
                for path, endpoint in routes if me_first else reversed(routes):
                    users_app.get(path)(endpoint)  # the decorator, called directly
                return users_app


            for me_first in (True, False):
                with TestClient(build_users_app(me_first)) as client:
                    print(f"{me_first=}: GET /users/me -> {client.get('/users/me').json()}")
            '''
        ),
    ]


def _query_cells() -> list[NotebookNode]:
    """6.2.3 Query parameters."""
    return [
        md(
            """
            ### 6.2.3 Query parameters

            A function parameter that is **not** in the path and is a simple type (str, int,
            bool, list of those, …) is read from the query string:

            | Declaration | Meaning |
            | --- | --- |
            | `page: int = 1` | optional, default 1, converted to int |
            | `q: str \\| None = None` | optional, `None` when absent |
            | `term: str` | **required** (no default): missing → 422 |
            | `archived: bool = False` | `true/1/yes/on` and `false/0/no/off` are accepted |
            | `tag: Annotated[list[str], Query()] = []` | repeated keys: `?tag=a&tag=b` → `["a", "b"]` (`Query()` is needed for lists) |
            | `limit: Annotated[int, Query(ge=1, le=100)] = 20` | validated range |
            | `Query(alias="page-size")` | the URL name differs from the Python name |
            | `Query(deprecated=True)`, `Query(include_in_schema=False)` | documentation flags |

            One endpoint with all of them:
            """
        ),
        code(
            '''
            search_app = FastAPI()


            @search_app.get("/search")
            async def search(
                term: str,
                q: str | None = None,
                page: int = 1,
                archived: bool = False,
                tag: Annotated[list[str], Query()] = [],  # noqa: B006 (FastAPI copies defaults)
                limit: Annotated[int, Query(ge=1, le=100)] = 20,
                page_size: Annotated[int, Query(alias="page-size", ge=1)] = 10,
            ) -> dict[str, object]:
                """Echo the parsed query parameters with their Python types."""
                values = {
                    "term": term,
                    "q": q,
                    "page": page,
                    "archived": archived,
                    "tag": tag,
                    "limit": limit,
                    "page_size": page_size,
                }
                return {name: f"{value!r}" for name, value in values.items()}
            '''
        ),
        md(
            """
            Call it with different query strings. Note `"archived": "True"` from `yes`, the
            list from repeated keys, and the 422 errors pointing at the exact parameter (`loc`):
            """
        ),
        code(
            """
            with TestClient(search_app) as client:
                print(client.get("/search", params={"term": "tea"}).json())
                print(client.get("/search?term=tea&archived=yes&tag=green&tag=loose&page-size=50").json())
                for bad_query in ("", "term=tea&limit=500", "term=tea&page=two"):
                    detail = client.get(f"/search?{bad_query}").json()["detail"][0]
                    print(f"{bad_query!r:<22} -> 422 {detail['loc']} {detail['msg']}")
            """
        ),
        md(
            """
            > **Note:** a mutable default like `= []` is normally a bug in Python (Unit 1.10),
            > but FastAPI copies parameter defaults for every request, so it is safe here.
            > `Annotated[list[str], Query(default_factory=list)]` avoids the lint warning.

            #### Query-parameter models

            When an endpoint takes many filters, group them in a Pydantic model and declare it
            as `Annotated[Model, Query()]`. Each field becomes a query parameter, the model's
            validators run, and `extra="forbid"` rejects unknown parameters (catching typos
            like `?limt=5`):
            """
        ),
        code(
            '''
            class ProductFilters(BaseModel):
                """Every filter for GET /products, validated together."""

                model_config = ConfigDict(extra="forbid")

                category: str | None = None
                min_price: Annotated[Decimal, Field(ge=0)] = Decimal(0)
                max_price: Annotated[Decimal | None, Field(ge=0)] = None
                in_stock: bool | None = None
                sort: Literal["price", "-price", "name"] = "name"
                limit: Annotated[int, Field(ge=1, le=100)] = 20


            products_app = FastAPI()


            @products_app.get("/products")
            async def list_products(filters: Annotated[ProductFilters, Query()]) -> ProductFilters:
                """Return the parsed filters (a real handler would query with them)."""
                return filters


            with TestClient(products_app) as client:
                print(client.get("/products?category=tea&max_price=500&sort=-price").json())
                for bad_query in ("limt=5", "sort=cheapest"):
                    detail = client.get(f"/products?{bad_query}").json()["detail"][0]
                    print(f"{bad_query!r:<16} -> {detail['type']}: {detail['msg']}")
            '''
        ),
    ]


def _body_cells() -> list[NotebookNode]:
    """6.2.4 Request bodies."""
    return [
        md(
            """
            ### 6.2.4 Request bodies

            A parameter annotated with a **Pydantic model** is read from the JSON body. FastAPI
            decides each parameter's source with these rules:

            | Parameter | Source |
            | --- | --- |
            | name appears in the path template | path |
            | simple type (int, str, bool, list of them, …) | query |
            | Pydantic model (or dataclass, `TypedDict`) | body |
            | `Annotated[..., Body()]` / `Query()` / `Header()` / `Cookie()` / `PathParam()` | explicit |

            So one endpoint can mix all three. `NewOrder` is the body; `shop_id` comes from
            the path; `dry_run` from the query:
            """
        ),
        code(
            '''
            class NewOrder(BaseModel):
                """The JSON body of POST /shops/{shop_id}/orders."""

                sku: str
                quantity: Annotated[int, Field(gt=0, le=50)]
                gift_note: str | None = None


            orders_body_app = FastAPI()


            @orders_body_app.post("/shops/{shop_id}/orders", status_code=201)
            async def place_order(shop_id: int, order: NewOrder, dry_run: bool = False) -> dict[str, object]:
                """Mix path, body and query parameters."""
                return {
                    "shop_id": shop_id,
                    "dry_run": dry_run,
                    "order": order,
                    "order_type": type(order).__name__,
                }


            with TestClient(orders_body_app) as client:
                response = client.post("/shops/3/orders?dry_run=true", json={"sku": "TEA-500", "quantity": 2})
                print(response.status_code, response.json())
                invalid = client.post("/shops/3/orders", json={"sku": "TEA-500", "quantity": 0, "extra": 1})
                print(invalid.status_code, [(error["loc"], error["msg"]) for error in invalid.json()["detail"]])
                print(
                    client.post(
                        "/shops/3/orders", content=b"{not json", headers={"content-type": "application/json"}
                    ).json()["detail"][0]["type"]
                )
            '''
        ),
        md(
            """
            Errors point into the body (`["body", "quantity"]`); malformed JSON gives
            `json_invalid`. The unknown `extra` key was **ignored**: models ignore extra keys by
            default (6.2.5 shows `extra="forbid"`).

            #### Several bodies, and `Body(embed=True)`

            With **one** model parameter, the body *is* that model's JSON. With **two or more**
            body parameters, FastAPI expects an object keyed by parameter name. A single
            scalar can join the body with `Body()`. And `Body(embed=True)` makes a single model
            expect `{"order": {...}}` instead of `{...}`, useful when a client wraps payloads:
            """
        ),
        code(
            '''
            class Customer(BaseModel):
                """A second body model."""

                name: str
                email: EmailStr


            embed_app = FastAPI()


            @embed_app.post("/checkout")
            async def checkout(
                order: NewOrder, customer: Customer, priority: Annotated[int, Body(ge=1, le=3)] = 1
            ) -> dict[str, object]:
                """Two models and a scalar: the body is {"order": ..., "customer": ..., "priority": ...}."""
                return {"order": order.sku, "customer": customer.email, "priority": priority}


            @embed_app.post("/orders-embedded")
            async def place_embedded(order: Annotated[NewOrder, Body(embed=True)]) -> NewOrder:
                """embed=True: the body must be {"order": {...}}."""
                return order


            with TestClient(embed_app) as client:
                order_json = {"sku": "MUG-02", "quantity": 1}
                print(
                    client.post(
                        "/checkout",
                        json={
                            "order": order_json,
                            "customer": {"name": "Asha", "email": "asha@example.com"},
                            "priority": 2,
                        },
                    ).json()
                )
                print(client.post("/orders-embedded", json={"order": order_json}).json())
                print(client.post("/orders-embedded", json=order_json).json()["detail"][0]["loc"])
            '''
        ),
    ]


def _pydantic_field_cells() -> list[NotebookNode]:
    """6.2.5 Pydantic v2 models: field types, constraints, validators."""
    return [
        md(
            """
            ### 6.2.5 Pydantic v2 models

            A Pydantic model is a class whose annotations are a schema. Creating an instance
            **parses** the input (converting where it is safe) and **validates** it; the result
            is a typed object. The same class serializes back to JSON and describes itself as
            JSON Schema. In zod terms: the class is both the schema and `z.infer<…>`.

            #### Field types

            | Type | Accepts | Becomes |
            | --- | --- | --- |
            | `EmailStr` | a valid address (needs `email-validator`, installed with FastAPI) | `str`, domain lower-cased |
            | `HttpUrl` | `http`/`https` URLs only | `HttpUrl` object (`.host`, `.path`); trailing `/` added to bare hosts |
            | `UUID` | UUID strings or objects | `uuid.UUID` |
            | `Decimal` | strings, ints, floats | `decimal.Decimal`, exact; serialized to JSON as a **string** |
            | `datetime` / `date` | ISO 8601 strings, Unix timestamps | `datetime` (time zone kept) |
            | `Literal["a", "b"]` | exactly those values | the value |
            | another `BaseModel` | a dict (or model) | a nested model instance |
            | `list[T]`, `dict[str, T]`, `T \\| None` | containers / optional | validated element by element |
            """
        ),
        code(
            '''
            class Address(BaseModel):
                """A nested model."""

                city: str
                pin_code: str


            class Supplier(BaseModel):
                """One field of each common type."""

                supplier_id: UUID
                contact_email: EmailStr
                website: HttpUrl
                credit_limit: Decimal
                onboarded_at: datetime
                tier: Literal["gold", "silver", "bronze"]
                address: Address
                tags: list[str] = []


            supplier = Supplier.model_validate(
                {
                    "supplier_id": "6f1c1a5e-8f3a-4c55-9b1e-1f2d3c4b5a69",
                    "contact_email": "Orders@Chai-Traders.IN",
                    "website": "https://chai-traders.in",
                    "credit_limit": "250000.50",
                    "onboarded_at": "2026-11-17T09:30:00+05:30",
                    "tier": "gold",
                    "address": {"city": "Pune", "pin_code": "411001"},
                }
            )
            for field_name in Supplier.model_fields:
                value = getattr(supplier, field_name)
                print(f"{field_name:<14} {type(value).__name__:<9} {value!r}")
            '''
        ),
        md(
            """
            Invalid input is reported field by field, all at once (zod's `safeParse` error
            list, not just the first problem):
            """
        ),
        code(
            """
            try:
                Supplier.model_validate(
                    {
                        "supplier_id": "123",
                        "contact_email": "not-an-email",
                        "website": "ftp://files.example",
                        "credit_limit": "lots",
                        "onboarded_at": "yesterday",
                        "tier": "platinum",
                        "address": {"city": "Pune"},
                    }
                )
            except ValidationError as error:
                print(f"{error.error_count()} errors")
                for problem in error.errors():
                    print(f"  {'.'.join(map(str, problem['loc'])):<17} {problem['type']}")
            """
        ),
        md(
            """
            #### `Field` constraints

            `Field(...)` adds constraints and metadata to one field; in `Annotated[...]` form the
            constraint travels with the type and can be reused:

            | Argument | For | Example |
            | --- | --- | --- |
            | `min_length`, `max_length` | str, list, dict | `Field(min_length=1, max_length=200)` |
            | `gt`, `ge`, `lt`, `le`, `multiple_of` | numbers | `Field(gt=0, le=50)` |
            | `max_digits`, `decimal_places` | `Decimal` | `Field(max_digits=10, decimal_places=2)` |
            | `pattern` | str (regex) | `Field(pattern=r"^[A-Z]{3}-\\d{3}$")` |
            | `default`, `default_factory` | any | `Field(default_factory=list)` |
            | `alias`, `validation_alias`, `serialization_alias` | names on the wire | `Field(alias="sku-code")` |
            | `title`, `description`, `examples`, `deprecated` | docs (6.2.9) | `Field(description="Price in rupees")` |
            | `strict`, `frozen`, `exclude`, `repr` | behaviour per field | `Field(exclude=True)` |
            """
        ),
        code(
            '''
            type Quantity = Annotated[int, Field(gt=0, le=50)]  # a reusable constrained type


            class LineItem(BaseModel):
                """Constraints from Field and from a reusable Annotated alias."""

                sku: Annotated[str, Field(pattern=r"^[A-Z]{3}-\\d{3}$", examples=["TEA-500"])]
                quantity: Quantity
                unit_price: Annotated[Decimal, Field(gt=0, max_digits=8, decimal_places=2)]
                notes: Annotated[list[str], Field(default_factory=list, max_length=3)]
                internal_code: Annotated[str, Field(exclude=True)] = "n/a"


            print(LineItem(sku="TEA-500", quantity=3, unit_price="240.00").model_dump())
            for bad in (
                {"sku": "tea-500"},
                {"quantity": 51},
                {"unit_price": "1.999"},
                {"notes": ["a", "b", "c", "d"]},
            ):
                data = {"sku": "TEA-500", "quantity": 1, "unit_price": "1.00", **bad}
                message = raised_message(lambda data=data: LineItem(**data)).splitlines()[2].strip()
                print(f"{bad!s:<32} -> {message}")
            '''
        ),
        md(
            """
            > **Note:** `type Quantity = Annotated[...]` is a PEP 695 type alias (*new in
            > 3.12*); Pydantic understands it. `internal_code` has `exclude=True`, so it never
            > appears in `model_dump()` output.

            #### `field_validator`, `model_validator`, `computed_field`

            - `@field_validator("name")` runs for one or more fields. `mode="after"` (default)
              receives the already-parsed value; `mode="before"` receives the raw input (to
              clean it up before parsing). Return the value to keep; raise `ValueError` to
              reject.
            - `@model_validator(mode="after")` sees the whole model: **cross-field** rules
              (end after start, passwords match). `mode="before"` gets the raw dict.
            - `@computed_field` on a property adds a derived value to serialization and the
              schema (but it is never accepted as input).
            """
        ),
        code(
            '''
            class Booking(BaseModel):
                """Validators on fields and on the whole model, plus a computed field."""

                guest_name: str
                room_type: Literal["single", "double", "suite"]
                check_in: date
                check_out: date
                nightly_rate: Decimal

                @field_validator("guest_name")
                @classmethod
                def title_case_name(cls, value: str) -> str:
                    """After parsing: normalize spacing and capitalization."""
                    return " ".join(part.capitalize() for part in value.split())

                @field_validator("room_type", mode="before")
                @classmethod
                def lowercase_room(cls, value: object) -> object:
                    """Before parsing: accept "Double" by lower-casing raw strings first."""
                    return value.lower() if isinstance(value, str) else value

                @model_validator(mode="after")
                def check_dates(self) -> Booking:
                    """Cross-field rule: at least one night."""
                    if self.check_out <= self.check_in:
                        raise ValueError("check_out must be after check_in")
                    return self

                @computed_field
                @property
                def total(self) -> Decimal:
                    """Derived, serialized, never accepted as input."""
                    return self.nightly_rate * (self.check_out - self.check_in).days
            '''
        ),
        md("Valid and invalid bookings; the computed `total` appears in the dump:"),
        code(
            """
            booking = Booking(
                guest_name="  asha   rao ",
                room_type="Double",
                check_in="2026-12-01",
                check_out="2026-12-04",
                nightly_rate="3500",
            )
            print(booking.model_dump())
            print(
                raised_message(
                    lambda: Booking(
                        guest_name="Ravi",
                        room_type="suite",
                        check_in="2026-12-04",
                        check_out="2026-12-01",
                        nightly_rate="9000",
                    )
                ).splitlines()[1]
            )
            print(f"{'total' in Booking.model_json_schema(mode='serialization')['properties']=}")
            """
        ),
    ]


def _pydantic_serialization_cells() -> list[NotebookNode]:
    """6.2.5 Pydantic v2 models: dumping, validating, config, strictness, errors."""
    return [
        md(
            """
            #### `model_dump` options, `model_validate` / `model_validate_json`

            | Call | Result |
            | --- | --- |
            | `model_dump()` | dict of Python objects (`Decimal`, `datetime` stay objects) |
            | `model_dump(mode="json")` | dict of JSON-safe values (strings for `Decimal`, ISO dates) |
            | `model_dump(include={...})` / `exclude={...}` | pick or drop fields (nested sets allowed) |
            | `model_dump(exclude_unset=True)` | only fields the input actually set (PATCH, 6.2.6) |
            | `model_dump(exclude_defaults=True)` / `exclude_none=True` | drop fields equal to their default / `None` |
            | `model_dump(by_alias=True)` | use aliases as keys |
            | `model_dump_json(indent=2)` | a JSON **string**, produced in Rust (faster than `json.dumps(model_dump())`) |
            | `Model.model_validate(obj)` | validate a dict (or an object with `from_attributes`) |
            | `Model.model_validate_json(text)` | parse and validate JSON text in one step (faster than `json.loads` first) |
            """
        ),
        code(
            """
            print(f"{booking.model_dump(include={'guest_name', 'total'})=}")
            print(f"{booking.model_dump(mode='json', exclude={'check_in', 'check_out'})=}")
            print(booking.model_dump_json(indent=2, include={"guest_name", "nightly_rate", "total"}))
            """
        ),
        md("`exclude_unset`, `exclude_defaults` and `exclude_none` on a model with defaults:"),
        code(
            '''
            class Preferences(BaseModel):
                """Every field has a default."""

                theme: Literal["light", "dark"] = "light"
                page_size: int = 20
                nickname: str | None = None


            sent = Preferences.model_validate({"theme": "light", "nickname": None})
            print(f"{sent.model_fields_set=}")
            print(f"{sent.model_dump()=}")
            print(f"{sent.model_dump(exclude_unset=True)=}")
            print(f"{sent.model_dump(exclude_defaults=True)=}")
            print(f"{sent.model_dump(exclude_none=True)=}")
            '''
        ),
        md(
            """
            `model_validate_json` parses bytes or text directly (one pass, in Rust), and
            `model_validate` with `from_attributes=True` reads attributes of any object (a
            dataclass, an ORM row in Unit 6.4):
            """
        ),
        code(
            '''
            print(Preferences.model_validate_json(b'{"theme": "dark", "page_size": "50"}'))


            @dataclasses.dataclass
            class PreferencesRow:
                """Stands in for a database row object."""

                theme: str
                page_size: int
                nickname: str | None


            row = PreferencesRow(theme="dark", page_size=10, nickname="chai-lover")
            print(Preferences.model_validate(row, from_attributes=True))
            print(raised_error_name(lambda: Preferences.model_validate(row)))
            '''
        ),
        md(
            """
            #### `ConfigDict`

            `model_config = ConfigDict(...)` sets behaviour for the whole model:

            | Option | Effect |
            | --- | --- |
            | `extra="forbid"` / `"ignore"` (default) / `"allow"` | reject, drop or keep unknown keys |
            | `frozen=True` | instances are immutable **and hashable** (value objects, dict keys) |
            | `from_attributes=True` | `model_validate(obj)` reads attributes (ORM mode) |
            | `str_strip_whitespace=True` | strip every `str` field |
            | `alias_generator=to_camel` + `validate_by_name=True` | camelCase on the wire, snake_case in Python |
            | `strict=True` | no type coercion anywhere in the model |
            | `validate_assignment=True` | re-validate on attribute assignment |
            | `json_schema_extra={...}` | extra JSON Schema keys (examples, 6.2.9) |
            """
        ),
        code(
            '''
            class StrictSignup(BaseModel):
                """extra="forbid" and str_strip_whitespace=True."""

                model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

                username: Annotated[str, Field(min_length=3)]


            class Currency(BaseModel):
                """frozen=True: immutable and hashable, a value object."""

                model_config = ConfigDict(frozen=True)

                code: str
                minor_units: int = 2


            print(StrictSignup(username="   asha  "))
            print(raised_message(lambda: StrictSignup(username="asha", is_admin=True)).splitlines()[2].strip())
            inr = Currency(code="INR")
            print(f"{hash(inr) == hash(Currency(code='INR'))=}  {({inr: 'rupee'})[Currency(code='INR')]=}")
            print(raised_message(lambda: setattr(inr, "code", "USD")).splitlines()[2].strip())
            '''
        ),
        md(
            """
            **camelCase on the wire.** JavaScript clients expect `firstName`; Python code wants
            `first_name`. An alias generator converts every field name; `validate_by_name=True`
            also accepts the Python name; `by_alias=True` when dumping produces camelCase.
            (FastAPI dumps response models by alias automatically.)
            """
        ),
        code(
            '''
            from pydantic.alias_generators import to_camel


            class CamelModel(BaseModel):
                """Base class: camelCase JSON, snake_case Python."""

                model_config = ConfigDict(
                    alias_generator=to_camel, validate_by_name=True, validate_by_alias=True
                )


            class UserProfile(CamelModel):
                """Inherits the camelCase config."""

                first_name: str
                last_login_at: datetime | None = None
                is_email_verified: bool = False


            profile = UserProfile.model_validate({"firstName": "Meena", "isEmailVerified": True})
            print(profile)
            print(profile.model_dump(by_alias=True, mode="json"))
            print(UserProfile(first_name="Ravi").first_name)
            '''
        ),
        md(
            """
            #### Strict vs lax mode

            By default Pydantic is **lax**: it converts input when no information is lost
            (`"42"` → `42`, `42.0` → `42`, even `True` → `1`), and refuses lossy conversions
            (`4.5` → int is an error). That suits query strings and forms, which are always
            text. **Strict** mode accepts only the exact type: per field (`Field(strict=True)`
            or `StrictInt`), per model (`ConfigDict(strict=True)`), or per call
            (`model_validate(data, strict=True)`). In strict JSON mode, a few unambiguous
            conversions remain (an ISO string is still accepted for `datetime`).
            """
        ),
        code(
            '''
            class Counter(BaseModel):
                """One lax field, one strict field."""

                lax_count: int = 0
                strict_count: Annotated[int, Field(strict=True)] = 0


            def parsed_or_error(field_name: str, raw_value: object) -> str:
                """The parsed value of one Counter field, or the error type."""
                try:
                    return repr(getattr(Counter(**{field_name: raw_value}), field_name))
                except ValidationError as error:
                    return error.errors()[0]["type"]


            for raw_value in ("42", 42.0, True, 4.5):
                lax_result = parsed_or_error("lax_count", raw_value)
                strict_result = parsed_or_error("strict_count", raw_value)
                print(f"{raw_value!r:<6} lax -> {lax_result:<15} strict -> {strict_result}")
            print(validation_problems(lambda: Counter.model_validate({"lax_count": "42"}, strict=True)))
            '''
        ),
        md(
            """
            #### `TypeAdapter`

            Not everything is a model. `TypeAdapter(T)` gives any type the model methods:
            validate a `list[int]`, a `dict[str, Decimal]`, a `TypedDict` or a union; dump it to
            JSON; produce its JSON Schema. Build adapters once (module level): construction
            compiles a validator.
            """
        ),
        code(
            """
            price_list = TypeAdapter(dict[str, Annotated[Decimal, Field(gt=0)]])
            prices = price_list.validate_json('{"TEA-500": "240.00", "MUG-02": 199}')
            print(f"{prices=}")
            print(f"{price_list.dump_json(prices)=}")
            print(f"{price_list.json_schema()=}")
            print(raised_message(lambda: price_list.validate_python({"TEA-500": -1})).splitlines()[1:3])
            """
        ),
        md(
            """
            #### `ValidationError.errors()`

            Every problem is a dict with the same keys, which is what FastAPI returns in a
            422's `detail` list. Clients (and your tests) should use `type` and `loc`, which are
            stable, not `msg`, which is for humans:

            | Key | Meaning |
            | --- | --- |
            | `type` | machine-readable error code (`missing`, `int_parsing`, `greater_than`, …) |
            | `loc` | path to the bad value: `("items", 2, "quantity")` |
            | `msg` | human-readable message |
            | `input` | the value that failed |
            | `ctx` | parameters of the constraint (`{"gt": 0}`) |
            | `url` | documentation link for the error type |

            `errors(include_url=False, include_context=False)` trims it; `error.json()` gives
            JSON text:
            """
        ),
        code(
            '''
            class Cart(BaseModel):
                """A nested list, so errors have multi-part locations."""

                items: list[LineItem]


            try:
                Cart.model_validate(
                    {
                        "items": [
                            {"sku": "TEA-500", "quantity": 1, "unit_price": "10"},
                            {"sku": "TEA-500", "quantity": 0, "unit_price": "10"},
                        ]
                    }
                )
            except ValidationError as error:
                problem = error.errors()[0]
                for key in ("type", "loc", "msg", "input", "ctx", "url"):
                    print(f"{key:<6} {problem[key]!r}")
                print(error.errors(include_url=False, include_context=False))
            '''
        ),
        md(
            """
            #### `Annotated` custom types

            `Annotated[base, validator, serializer, ...]` builds a reusable type with its own
            parsing and output rules, without subclassing:

            | Marker | Runs |
            | --- | --- |
            | `BeforeValidator(fn)` | before the base type's validation, on raw input |
            | `AfterValidator(fn)` | after it, on the typed value |
            | `PlainValidator(fn)` | instead of it |
            | `PlainSerializer(fn, when_used="json")` | when dumping |
            | `StringConstraints(strip_whitespace=True, to_lower=True, ...)` | str clean-up and limits |

            A tag type for the Notes API, and a rupee amount that is a `Decimal` in Python and a
            formatted string in JSON. Order matters: `StringConstraints(pattern=...)` checks
            the **raw** string, before `strip_whitespace` and `to_lower`, so the pattern check
            goes in an `AfterValidator`:
            """
        ),
        code(
            '''
            from pydantic import AfterValidator, BeforeValidator, PlainSerializer, StringConstraints


            def require_slug(value: str) -> str:
                """Allow lowercase letters, digits and dashes only."""
                if not re.fullmatch(r"[a-z0-9-]+", value):
                    raise ValueError("use lowercase letters, digits and dashes")
                return value


            type Tag = Annotated[
                str,
                StringConstraints(strip_whitespace=True, to_lower=True, min_length=1, max_length=30),
                AfterValidator(require_slug),
            ]
            type Rupees = Annotated[
                Decimal,
                BeforeValidator(lambda raw: str(raw).replace(",", "").removeprefix("₹")),
                PlainSerializer(lambda amount: f"₹{amount:,.2f}", return_type=str, when_used="json"),
            ]


            class Expense(BaseModel):
                """Uses both custom types."""

                amount: Rupees
                tags: list[Tag]


            expense = Expense(amount="₹1,25,000.5", tags=["  Travel ", "Q4"])
            print(expense)
            print(expense.model_dump_json())
            print(raised_message(lambda: Expense(amount=1, tags=["team lunch"])).splitlines()[2].strip())
            '''
        ),
        md(
            """
            **Under the hood.** A model class is built by `ModelMetaclass` (Unit 2.5's
            metaclass machinery): it reads the annotations, builds a **core schema** (a tree of
            plain dicts), and hands it to `pydantic-core`, which compiles a `SchemaValidator`
            and `SchemaSerializer` in Rust. Instances keep their data in `__dict__` plus a set
            of the fields that were set:
            """
        ),
        code(
            """
            print(f"{type(Expense).__name__=}  {type(Expense.__pydantic_validator__).__name__=}")
            print(f"{Expense.__pydantic_core_schema__['type']=}  {list(Expense.model_fields)=}")
            print(f"{Expense.model_fields['tags']=}")
            print(f"{expense.__dict__=}")
            print(f"{expense.model_fields_set=}")
            print(f"{Expense.__pydantic_validator__.validate_python({'amount': '10', 'tags': ['x']})=}")
            """
        ),
    ]


def _schema_design_cells() -> list[NotebookNode]:
    """6.2.6 Schema design."""
    return [
        md(
            """
            ### 6.2.6 Schema design

            One resource usually needs **several schemas**, because the client and the server
            own different fields at different moments:

            | Schema | Used for | Fields |
            | --- | --- | --- |
            | `UserCreate` | `POST` body | what the client provides, including secrets (`password`) |
            | `UserUpdate` | `PATCH` body | the same fields, **all optional** |
            | `UserRead` | responses | server-owned fields too (`id`, `created_at`), and **never** secrets |
            | (internal) | storage | everything, e.g. `password_hash` |

            A shared base class avoids repeating the common fields. `extra="forbid"` on input
            schemas turns client typos into 422s instead of silently ignored keys:
            """
        ),
        code(
            '''
            class UserBase(BaseModel):
                """Fields every user schema shares."""

                username: Annotated[str, Field(min_length=3, max_length=30, pattern=r"^[a-z0-9_]+$")]
                email: EmailStr
                display_name: Annotated[str, Field(max_length=60)] = ""


            class UserCreate(UserBase):
                """POST body: the client sends a password."""

                model_config = ConfigDict(extra="forbid")

                password: Annotated[str, Field(min_length=12)]


            class UserUpdate(BaseModel):
                """PATCH body: every field optional, nothing required."""

                model_config = ConfigDict(extra="forbid")

                email: EmailStr | None = None
                display_name: Annotated[str | None, Field(max_length=60)] = None


            class UserRead(UserBase):
                """Response: server-owned fields, no password."""

                model_config = ConfigDict(from_attributes=True)

                id: int
                created_at: datetime
            '''
        ),
        md(
            """
            The same data through each schema. The stored record has a `password_hash`;
            validating it as `UserRead` drops it, so it can never leak into a response:
            """
        ),
        code(
            """
            new_user = UserCreate(username="asha_r", email="asha@example.com", password="correct horse battery")
            stored = {
                **new_user.model_dump(exclude={"password"}),
                "id": 1,
                "password_hash": "argon2:...",
                "created_at": datetime(2026, 11, 17, 9, 0, tzinfo=UTC),
            }
            print(UserRead.model_validate(stored).model_dump(mode="json"))
            print(
                validation_problems(
                    lambda: UserCreate(
                        username="ravi", email="ravi@example.com", password="short", is_admin=True
                    )
                )
            )
            print(f"{sorted(UserRead.model_fields)=}")
            """
        ),
        md(
            """
            #### PATCH with `exclude_unset`

            A PATCH body says "change these fields". The Update schema makes every field
            optional, which creates a problem: `None` now means both "not sent" and "set it to
            null". `model_dump(exclude_unset=True)` resolves it: it contains only the keys the
            client actually sent. Merge that into the stored record:

            | Client sends | `exclude_unset=True` | `exclude_none=True` (wrong) |
            | --- | --- | --- |
            | `{"display_name": "Asha R"}` | `{"display_name": "Asha R"}` | same |
            | `{"display_name": null}` (clear it) | `{"display_name": None}` | `{}`: the clear is lost |
            | `{}` | `{}` | `{}` |
            """
        ),
        code(
            '''
            def apply_patch(record: dict[str, object], changes: UserUpdate) -> dict[str, object]:
                """Merge only the fields the client sent into a copy of record."""
                return {**record, **changes.model_dump(exclude_unset=True)}


            record = {"username": "asha_r", "email": "asha@example.com", "display_name": "Asha"}
            for body in ({"display_name": "Asha R"}, {"display_name": None}, {}):
                changes = UserUpdate.model_validate(body)
                print(
                    f"{body!s:<28} unset-> {apply_patch(record, changes)['display_name']!r:<9}"
                    f" none-> {({**record, **changes.model_dump(exclude_none=True)})['display_name']!r}"
                )
            '''
        ),
        md(
            """
            > **Warning:** with `exclude_unset`, a client can also send `{"email": null}` for a
            > field that must never be null. The Notes API's Update schema (after Lab 6.2)
            > rejects explicit `null` for non-nullable fields with a `model_validator`.
            """
        ),
    ]


BLOCKING_API_MODULE = r'''
%%writefile _scratch/phase6/blocking_api.py
"""Four ways to wait 0.2 s in a FastAPI handler, for the 6.2.8 load test."""

import asyncio
import threading
import time

import anyio.to_thread
from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool

DELAY_SECONDS = 0.2
app = FastAPI()


@app.get("/health")
async def health() -> dict[str, str]:
    """Answers at once, unless the event loop is blocked."""
    return {"status": "ok"}


@app.get("/async-blocking")
async def async_blocking() -> dict[str, str]:
    """WRONG: a blocking call inside async def freezes the event loop."""
    time.sleep(DELAY_SECONDS)
    return {"thread": threading.current_thread().name}


@app.get("/sync-blocking")
def sync_blocking() -> dict[str, str]:
    """A plain def handler: FastAPI runs it in the thread pool, so blocking is fine."""
    time.sleep(DELAY_SECONDS)
    return {"thread": threading.current_thread().name}


@app.get("/async-sleep")
async def async_sleep() -> dict[str, str]:
    """async def with a non-blocking wait: the loop serves others meanwhile."""
    await asyncio.sleep(DELAY_SECONDS)
    return {"thread": threading.current_thread().name}


@app.get("/async-offloaded")
async def async_offloaded() -> dict[str, str]:
    """async def that pushes one blocking call to the thread pool explicitly."""
    await run_in_threadpool(time.sleep, DELAY_SECONDS)
    return {"thread": threading.current_thread().name}


@app.get("/thread-pool")
async def thread_pool() -> dict[str, int]:
    """The size of the thread pool that def handlers share (AnyIO's default limiter)."""
    return {"total_tokens": int(anyio.to_thread.current_default_thread_limiter().total_tokens)}
'''

PRODUCTS_API_MODULE = r'''
%%writefile _scratch/phase6/products_api.py
"""A documented API: OpenAPI metadata, tags, examples and clean operation ids."""

from decimal import Decimal
from typing import Annotated

from fastapi import Body, FastAPI, HTTPException, Query, status
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field


def operation_id(route: APIRoute) -> str:
    """Use the function name as the operationId: generated clients get listProducts, not
    list_products_products_get."""
    return route.name


app = FastAPI(
    title="Products API",
    version="1.2.0",
    summary="A small catalog, documented for humans and code generators.",
    description="Prices are in **rupees**. Every list endpoint is paginated.",
    contact={"name": "Catalog team", "email": "catalog@example.com"},
    license_info={"name": "MIT", "identifier": "MIT"},
    openapi_tags=[
        {"name": "products", "description": "Browse and manage products."},
        {"name": "health", "description": "Liveness probe."},
    ],
    generate_unique_id_function=operation_id,
)


class ProductCreate(BaseModel):
    """What a client sends to create a product."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"name": "Assam tea", "price": "240.00", "tags": ["tea"]}]},
    )

    name: Annotated[str, Field(min_length=1, max_length=80, description="Display name.")]
    price: Annotated[Decimal, Field(gt=0, decimal_places=2, description="Price in rupees.")]
    tags: Annotated[list[str], Field(default_factory=list, examples=[["tea", "loose-leaf"]])]


class ProductRead(ProductCreate):
    """What the API returns."""

    id: int


class ErrorMessage(BaseModel):
    """The body of an error response."""

    detail: str


PRODUCTS: dict[int, ProductRead] = {
    1: ProductRead(id=1, name="Assam tea", price=Decimal("240.00"), tags=["tea"]),
}


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/products", tags=["products"], summary="List products")
async def list_products(limit: Annotated[int, Query(ge=1, le=100)] = 20) -> list[ProductRead]:
    """Return up to `limit` products, oldest first."""
    return list(PRODUCTS.values())[:limit]


@app.get(
    "/products/{product_id}",
    tags=["products"],
    responses={404: {"model": ErrorMessage, "description": "No product with this id."}},
)
async def get_product(product_id: int) -> ProductRead:
    """Fetch one product."""
    if product_id not in PRODUCTS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"product {product_id} not found")
    return PRODUCTS[product_id]


@app.post(
    "/products",
    tags=["products"],
    status_code=status.HTTP_201_CREATED,
    response_description="The created product, with its id.",
)
async def create_product(
    product: Annotated[
        ProductCreate,
        Body(
            openapi_examples={
                "tea": {"summary": "A tea", "value": {"name": "Darjeeling", "price": "320.00"}},
                "mug": {"summary": "A mug", "value": {"name": "Clay mug", "price": "199.00"}},
            }
        ),
    ],
) -> ProductRead:
    """Create a product."""
    created = ProductRead(id=max(PRODUCTS) + 1, **product.model_dump())
    PRODUCTS[created.id] = created
    return created


@app.get("/legacy/products-export", tags=["products"], deprecated=True)
async def legacy_export() -> list[ProductRead]:
    """Old endpoint kept for one more release (shown struck through in /docs)."""
    return list(PRODUCTS.values())


@app.get("/internal/metrics", include_in_schema=False)
async def internal_metrics() -> dict[str, int]:
    """Hidden from the docs."""
    return {"products": len(PRODUCTS)}
'''


def _response_cells() -> list[NotebookNode]:
    """6.2.7 Responses."""
    return [
        md(
            """
            ### 6.2.7 Responses

            #### `response_model`

            The response model is the contract for what leaves the server. FastAPI validates
            the returned value against it and serializes **only its fields**, so extra data
            (a password hash, internal flags) is dropped even if the handler returns it. Set it
            with `response_model=...` in the decorator, or with the return annotation (FastAPI
            uses the annotation when no `response_model` is given). Options:
            `response_model_exclude_unset`, `response_model_exclude_none`,
            `response_model_include/exclude`; `response_model=None` turns it off.
            """
        ),
        code(
            '''
            users_api = FastAPI()
            USER_ROWS = {
                1: {
                    "id": 1,
                    "username": "asha_r",
                    "email": "asha@example.com",
                    "display_name": "",
                    "password_hash": "argon2:secret",
                    "created_at": datetime(2026, 11, 17, tzinfo=UTC),
                }
            }


            @users_api.get("/users/{user_id}", response_model=UserRead)
            async def read_user_row(user_id: int) -> dict[str, object]:
                """Returns the raw row; response_model filters it to UserRead's fields."""
                return USER_ROWS[user_id]


            @users_api.get(
                "/users/{user_id}/compact", response_model=UserRead, response_model_exclude_defaults=True
            )
            async def read_user_compact(user_id: int) -> dict[str, object]:
                """Same row; fields still equal to their defaults (display_name="") are left out."""
                return USER_ROWS[user_id]


            with TestClient(users_api) as client:
                print(client.get("/users/1").json())
                print(client.get("/users/1/compact").json())
            '''
        ),
        md(
            """
            If the handler returns something that does not fit the response model, that is a
            **server** bug, so FastAPI raises `ResponseValidationError` (a 500), never sending
            invalid data:
            """
        ),
        code(
            '''
            @users_api.get("/broken")
            async def broken_user() -> UserRead:
                """The return annotation is the response model; this dict lacks required fields."""
                return {"username": "x"}  # type: ignore[return-value]


            with TestClient(users_api, raise_server_exceptions=False) as client:
                print(client.get("/broken").status_code)
            with TestClient(users_api) as client:
                print(raised_error_name(lambda: client.get("/broken")))
            '''
        ),
        md(
            """
            #### Status codes

            `status_code=` in the decorator sets the success code and documents it; the
            `fastapi.status` module has named constants (`status.HTTP_201_CREATED`). A `204`
            response has no body. To choose the code at run time, declare a `response: Response`
            parameter and set `response.status_code` (an upsert `PUT`: 201 when created, 200
            when replaced):
            """
        ),
        code(
            '''
            status_app = FastAPI()
            SETTINGS: dict[str, str] = {}


            @status_app.put("/settings/{key}", status_code=status.HTTP_200_OK)
            async def upsert_setting(
                key: str, value: Annotated[str, Body(embed=True)], response: Response
            ) -> dict[str, str]:
                """201 when the key is new, 200 when it is replaced."""
                if key not in SETTINGS:
                    response.status_code = status.HTTP_201_CREATED
                SETTINGS[key] = value
                return {key: value}


            @status_app.delete("/settings/{key}", status_code=status.HTTP_204_NO_CONTENT)
            async def delete_setting(key: str) -> None:
                """204: success, nothing to say."""
                SETTINGS.pop(key, None)


            with TestClient(status_app) as client:
                themes = ("dark", "light")
                print([client.put("/settings/theme", json={"value": theme}).status_code for theme in themes])
                deleted = client.delete("/settings/theme")
                print(f"{deleted.status_code=} {deleted.content=}  {status.HTTP_422_UNPROCESSABLE_CONTENT=}")
            '''
        ),
        md(
            """
            #### Response classes

            Returning a dict, list or model gives a `JSONResponse`. Return a `Response` subclass
            yourself for anything else; it is sent as is (**no response-model filtering**).
            `response_class=` sets the default class for a route and documents the media type.

            | Class | Use |
            | --- | --- |
            | `JSONResponse(content, status_code, headers)` | JSON with a custom status or headers |
            | `PlainTextResponse`, `HTMLResponse` | text / HTML |
            | `StreamingResponse(iterator, media_type)` | a body produced piece by piece (NDJSON, CSV exports, server-sent events) |
            | `FileResponse(path, filename=...)` | a file from disk, with `Content-Length`, `ETag`, `Last-Modified`, `Content-Disposition` |
            | `RedirectResponse(url, status_code=307)` | redirects (307/308 keep the method and body; 301/302/303 may turn POST into GET) |
            """
        ),
        code(
            '''
            from fastapi.responses import (
                FileResponse,
                HTMLResponse,
                JSONResponse,
                PlainTextResponse,
                RedirectResponse,
                StreamingResponse,
            )

            responses_app = FastAPI()


            @responses_app.get("/accepted")
            async def accepted_job() -> JSONResponse:
                """A JSONResponse with its own status code and header."""
                return JSONResponse(
                    {"job_id": "job-42", "state": "queued"},
                    status_code=202,
                    headers={"Location": "/jobs/job-42"},
                )


            @responses_app.get("/robots.txt", response_class=PlainTextResponse)
            async def robots() -> str:
                """response_class turns the returned str into text/plain."""
                return "User-agent: *\\nDisallow: /admin/\\n"


            @responses_app.get("/hello.html", response_class=HTMLResponse)
            async def hello_page() -> str:
                """An HTML page from a string."""
                return "<h1>Hello from FastAPI</h1>"


            with TestClient(responses_app) as client:
                job = client.get("/accepted")
                print(job.status_code, job.headers["location"], job.json())
                for path in ("/robots.txt", "/hello.html"):
                    reply = client.get(path)
                    print(f"{path:<12} {reply.headers['content-type']:<26} {reply.text!r}")
            '''
        ),
        md(
            """
            `StreamingResponse` takes a sync or async iterator. Here an export streams one JSON
            object per line (NDJSON) without building the whole body in memory; the client reads
            it line by line:
            """
        ),
        code(
            '''
            async def order_lines(count: int) -> AsyncIterator[str]:
                """Yield one JSON document per line, as a database cursor would."""
                for order_id in range(1, count + 1):
                    yield json.dumps({"order_id": order_id, "total": order_id * 120}) + "\\n"
                    await asyncio.sleep(0)  # let other tasks run between rows


            @responses_app.get("/orders/export")
            async def export_orders(count: Annotated[int, Query(ge=1, le=1000)] = 3) -> StreamingResponse:
                """Stream NDJSON."""
                return StreamingResponse(order_lines(count), media_type="application/x-ndjson")


            with (
                TestClient(responses_app) as client,
                client.stream("GET", "/orders/export?count=3") as streamed,
            ):
                print(streamed.headers["content-type"], streamed.headers.get("content-length"))
                for line in streamed.iter_lines():
                    print(" ", json.loads(line))
            '''
        ),
        md(
            """
            `FileResponse` serves a file efficiently and fills in the caching headers;
            `filename=` adds `Content-Disposition: attachment` so browsers download it.
            `RedirectResponse` defaults to **307**; use 308 for a permanent move that keeps the
            method:
            """
        ),
        code(
            '''
            report_path = PHASE6_DIR / "sales_report.csv"
            report_path.write_text("month,revenue\\n2026-10,125000\\n2026-11,142000\\n", encoding="utf-8")


            @responses_app.get("/reports/sales.csv")
            async def download_report() -> FileResponse:
                """Send a file from disk as a download."""
                return FileResponse(report_path, media_type="text/csv", filename="sales-2026.csv")


            @responses_app.get("/old-reports/sales.csv")
            async def moved_report() -> RedirectResponse:
                """Permanent move that keeps the method."""
                return RedirectResponse("/reports/sales.csv", status_code=status.HTTP_308_PERMANENT_REDIRECT)


            with TestClient(responses_app) as client:
                download = client.get("/reports/sales.csv")
                for header in (
                    "content-type",
                    "content-length",
                    "content-disposition",
                    "etag",
                    "last-modified",
                ):
                    value = "<varies>" if header in ("etag", "last-modified") else download.headers[header]
                    print(f"{header:<20} {value}")
                moved = client.get("/old-reports/sales.csv", follow_redirects=False)
                print(
                    moved.status_code,
                    moved.headers["location"],
                    "| followed:",
                    client.get("/old-reports/sales.csv").status_code,
                )
            '''
        ),
        md(
            """
            #### Headers and cookies

            To add headers or cookies **and** keep returning plain data (so the response model
            still applies), declare a `response: Response` parameter and modify it. Request
            headers are read with `Header()` (the parameter `user_agent` reads `User-Agent`:
            underscores become dashes, and matching ignores case); cookies with `Cookie()`.
            Cookie flags matter for security: `httponly` (no JavaScript access), `secure`
            (HTTPS only), `samesite` (CSRF protection), `max_age`.
            """
        ),
        code(
            '''
            from fastapi import Cookie, Header

            session_app = FastAPI()


            @session_app.post("/login")
            async def login(response: Response) -> dict[str, str]:
                """Set a session cookie and a custom header on a normal JSON response."""
                response.set_cookie(
                    "session_id", "s-123", httponly=True, secure=True, samesite="lax", max_age=3600
                )
                response.headers["X-Login-Count"] = "1"
                return {"status": "logged in"}


            @session_app.get("/whoami")
            async def whoami(
                session_id: Annotated[str | None, Cookie()] = None,
                user_agent: Annotated[str | None, Header()] = None,
            ) -> dict[str, str | None]:
                """Read a cookie and a request header."""
                return {"session_id": session_id, "user_agent": user_agent}


            @session_app.post("/logout")
            async def logout(response: Response) -> dict[str, str]:
                """Delete the cookie (an expired Set-Cookie)."""
                response.delete_cookie("session_id")
                return {"status": "logged out"}


            with TestClient(session_app, base_url="https://testserver") as client:
                logged_in = client.post("/login")
                print(logged_in.headers["set-cookie"])
                print(
                    logged_in.headers["x-login-count"],
                    client.get("/whoami", headers={"User-Agent": "notes-cli/1.0"}).json(),
                )
                print(re.sub(r"expires=[^;]+", "expires=<now>", client.post("/logout").headers["set-cookie"]))
            '''
        ),
        md(
            """
            #### `HTTPException`

            Raise `HTTPException(status_code, detail, headers)` anywhere in a handler (or in a
            function it calls) to stop and send an error. FastAPI's version accepts any
            JSON-serializable `detail` (a string, or a dict with a machine-readable code) and
            extra headers. The body is always `{"detail": ...}`. In Express terms: `throw
            createError(404, ...)` instead of `return res.status(404).json(...)`.
            """
        ),
        code(
            '''
            errors_app = FastAPI()
            TAKEN_USERNAMES = {"asha_r"}


            @errors_app.get("/notes/{note_id}")
            async def find_note(
                note_id: int, authorization: Annotated[str | None, Header()] = None
            ) -> dict[str, int]:
                """401 without credentials, 404 for unknown notes."""
                if authorization is None:
                    raise HTTPException(
                        status.HTTP_401_UNAUTHORIZED,
                        detail="not authenticated",
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                if note_id != 1:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"note {note_id} not found")
                return {"id": note_id}


            @errors_app.post("/users", status_code=201)
            async def register(username: Annotated[str, Body(embed=True)]) -> dict[str, str]:
                """409 with a structured detail when the name is taken."""
                if username in TAKEN_USERNAMES:
                    raise HTTPException(
                        status.HTTP_409_CONFLICT, detail={"code": "username_taken", "field": "username"}
                    )
                return {"username": username}


            with TestClient(errors_app) as client:
                unauthenticated = client.get("/notes/1")
                print(
                    unauthenticated.status_code,
                    unauthenticated.json(),
                    unauthenticated.headers["www-authenticate"],
                )
                print(client.get("/notes/7", headers={"Authorization": "Bearer t"}).json())
                taken = client.post("/users", json={"username": "asha_r"})
                print(taken.status_code, taken.json())
            '''
        ),
    ]


def _async_vs_sync_cells() -> list[NotebookNode]:
    """6.2.8 async def vs def handlers."""
    return [
        md(
            """
            ### 6.2.8 `async def` vs `def` handlers

            FastAPI accepts both, and runs them differently:

            | Handler | Runs | A blocking call inside it (`time.sleep`, `requests.get`, a sync DB driver) |
            | --- | --- | --- |
            | `async def` | **on the event loop**, in the server's only thread | **blocks every request** on that worker until it returns |
            | `def` | in AnyIO's **thread pool** (`run_in_threadpool`), default 40 threads | blocks only its own thread; at most 40 such calls at once per process |
            | `async def` + `await run_in_threadpool(fn, ...)` | loop, with one call pushed to the pool | fine: only that call uses a thread |

            Rules of thumb: use `async def` when everything you await is async (httpx
            `AsyncClient`, async database drivers, `asyncio.sleep`); use plain `def` when you call
            blocking libraries; never call blocking code directly inside `async def`. CPU-heavy
            work blocks either way (the GIL, Unit 5.1): send it to a process pool or a job queue
            (Unit 6.6).

            Which thread runs each kind of handler:
            """
        ),
        code(
            '''
            threads_app = FastAPI()


            @threads_app.get("/sync")
            def sync_handler() -> dict[str, str]:
                """def: called in a worker thread."""
                return {"thread": threading.current_thread().name}


            @threads_app.get("/async")
            async def async_handler() -> dict[str, object]:
                """async def: called on the event loop's thread."""
                limiter = anyio.to_thread.current_default_thread_limiter()
                return {"thread": threading.current_thread().name, "pool_size": limiter.total_tokens}


            with TestClient(threads_app) as client:
                print("def       ->", client.get("/sync").json())
                async_reply = client.get("/async").json()
                print(
                    "async def ->",
                    async_reply | {"thread": re.sub(r"-[0-9a-f]{6,}$", "-<id>", async_reply["thread"])},
                )
            '''
        ),
        md(
            """
            > **Note:** `TestClient` runs the app's event loop in its own thread, whose name you
            > see for `async def`; under Uvicorn it is the main thread. `def` handlers always run
            > in "AnyIO worker thread"s.

            #### A blocking demo under load

            The app below has the same 0.2 s wait written four ways. It runs under Uvicorn in a
            child process (one worker, like a single container), and each endpoint gets 10
            concurrent requests. A fifth measurement sends one `/health` request **while** 10
            `/async-blocking` requests are in flight:
            """
        ),
        *writefile_cells(
            BLOCKING_API_MODULE,
            [
                (
                    "",
                    "Part 1 of `blocking_api.py`: the health check and the **wrong** way to wait.",
                ),
                (
                    '@app.get("/sync-blocking")',
                    "Part 2: three correct ways, and the thread-pool size.",
                ),
            ],
        ),
        md("Run the load test (times vary by machine; the pattern does not):"),
        code(
            '''
            async def timed_burst(client: httpx.AsyncClient, path: str, request_count: int) -> float:
                """Wall time for request_count concurrent GETs of path."""
                started = time.perf_counter()
                await asyncio.gather(*(client.get(path) for _ in range(request_count)))
                return time.perf_counter() - started


            async def health_latency_during(client: httpx.AsyncClient, path: str, request_count: int) -> float:
                """How long /health takes while request_count requests to path are running."""
                burst = asyncio.gather(*(client.get(path) for _ in range(request_count)))
                await asyncio.sleep(0.05)  # let the burst reach the server first
                started = time.perf_counter()
                await client.get("/health")
                latency = time.perf_counter() - started
                await burst
                return latency


            limits = httpx.Limits(max_connections=100, max_keepalive_connections=100)
            with uvicorn_server("blocking_api:app") as base_url:
                async with httpx.AsyncClient(
                    base_url=base_url, limits=limits, timeout=60, trust_env=False
                ) as client:
                    for path in ("/async-blocking", "/sync-blocking", "/async-sleep", "/async-offloaded"):
                        seconds = await timed_burst(client, path, 10)
                        print(f"{path:<17} 10 requests x 0.2 s: {seconds:5.2f} s")
                    latency = await health_latency_during(client, "/async-blocking", 10)
                    print(f"/health while /async-blocking is busy: {latency:5.2f} s (normally ~0.001 s)")
                    pool = (await client.get("/thread-pool")).json()["total_tokens"]
                    seconds = await timed_burst(client, "/sync-blocking", 60)
                    print(f"/sync-blocking with 60 requests and a pool of {pool}: {seconds:5.2f} s")
            '''
        ),
        md(
            """
            What to notice:

            - **`/async-blocking`** serializes: 10 × 0.2 s ≈ 2 s, and even `/health` waits for
              the queue, because the event loop is stuck in `time.sleep`. This is the single
              most common FastAPI performance bug.
            - **`/sync-blocking`** overlaps the waits in the thread pool: ≈ 0.2 s.
            - **`/async-sleep`** and **`/async-offloaded`** overlap too.
            - **60 sync requests** need two rounds (40 threads, then 20): ≈ 0.4 s. The pool
              size can be raised (`anyio.to_thread.current_default_thread_limiter().total_tokens
              = 100` in a lifespan handler), but more threads cost memory and GIL contention;
              async drivers scale further.
            """
        ),
    ]


def _openapi_cells() -> list[NotebookNode]:
    """6.2.9 OpenAPI."""
    return [
        md(
            """
            ### 6.2.9 OpenAPI

            FastAPI generates an **OpenAPI 3.1** document from your routes and models and
            serves it with two UIs:

            | URL | What | Turn off / move |
            | --- | --- | --- |
            | `/openapi.json` | the machine-readable description | `FastAPI(openapi_url=None)` disables all three |
            | `/docs` | Swagger UI: try requests in the browser | `docs_url=None` or another path |
            | `/redoc` | ReDoc: readable reference docs | `redoc_url=None` |

            What you can add, and where:

            | Level | Options |
            | --- | --- |
            | app | `title`, `version`, `summary`, `description` (Markdown), `contact`, `license_info`, `openapi_tags`, `servers`, `generate_unique_id_function` |
            | route | `tags`, `summary`, `description` (or the docstring), `response_description`, `responses={404: {...}}`, `deprecated=True`, `include_in_schema=False`, `operation_id` |
            | model / field | `Field(description=..., examples=[...])`, `model_config = ConfigDict(json_schema_extra={"examples": [...]})` |
            | parameter | `Body(openapi_examples={...})`, `Query(description=..., deprecated=True)` |

            A documented demo API (served from the scratch folder):
            """
        ),
        *writefile_cells(
            PRODUCTS_API_MODULE,
            [
                ("", "Part 1 of `products_api.py`: app metadata and clean operation ids."),
                (
                    "class ProductCreate(BaseModel):",
                    "Part 2: schemas with descriptions and examples, and the data.",
                ),
                (
                    '@app.get("/health"',
                    "Part 3: read endpoints, one with a documented 404 response.",
                ),
                (
                    "@app.post(",
                    "Part 4: create (named request examples), a deprecated route and a hidden one.",
                ),
            ],
        ),
        md(
            """
            The three documentation URLs, and the parts of the generated document. Notice the
            operation ids (function names, thanks to `generate_unique_id_function`), the hidden
            `/internal/metrics` route, the deprecated flag, and the `HTTPValidationError`
            schema FastAPI adds for 422 responses:
            """
        ),
        code(
            """
            products_api = fresh_import("products_api")
            with TestClient(products_api.app) as client:
                for path in ("/docs", "/redoc"):
                    page = client.get(path)
                    title = re.search(r"<title>(.*?)</title>", page.text)[1]
                    print(f"{path:<7} {page.status_code} {page.headers['content-type']:<24} {title}")
                products_openapi = client.get("/openapi.json").json()
            info = products_openapi["info"]
            print(f"OpenAPI {products_openapi['openapi']}: {info['title']} {info['version']}")
            for path, operations in products_openapi["paths"].items():
                for method, operation in operations.items():
                    flag = " (deprecated)" if operation.get("deprecated") else ""
                    name, tags = operation["operationId"], operation["tags"]
                    print(f"  {method.upper():<5} {path:<26} {name:<15} tags={tags}{flag}")
            print(f"{sorted(products_openapi['components']['schemas'])=}")
            """
        ),
        md(
            """
            The request-body schema with its examples, and the documented responses of
            `GET /products/{product_id}`:
            """
        ),
        code(
            """
            print(json.dumps(products_openapi["components"]["schemas"]["ProductCreate"], indent=2)[:900])
            print(
                json.dumps(products_openapi["paths"]["/products/{product_id}"]["get"]["responses"], indent=1)[
                    :700
                ]
            )
            """
        ),
        md(
            """
            #### Generating a TypeScript client

            Because the contract is machine-readable, the frontend never has to hand-write
            request code or types. Real projects use a generator:

            | Tool | Produces |
            | --- | --- |
            | `openapi-typescript` (+ `openapi-fetch`) | `.d.ts` types for every path and schema, plus a typed `fetch` wrapper |
            | `@hey-api/openapi-ts`, `orval` | typed SDK functions, optionally TanStack Query hooks |
            | `openapi-generator` | clients for many languages |

            ```bash
            npx openapi-typescript http://127.0.0.1:8000/openapi.json -o src/api/schema.d.ts
            ```

            That needs the npm registry, so the notebook does not run it. Instead, a small
            generator shows what such tools do. Part 1 maps JSON Schema to TypeScript types and
            writes one `interface` per component schema:
            """
        ),
        code(
            r'''
            def ts_type(schema: dict[str, Any]) -> str:
                """TypeScript type for a JSON Schema fragment (the common cases)."""
                if "$ref" in schema:
                    return schema["$ref"].rsplit("/", 1)[1]
                if "anyOf" in schema:
                    return " | ".join(ts_type(option) for option in schema["anyOf"])
                if "enum" in schema:
                    return " | ".join(json.dumps(value) for value in schema["enum"])
                if "const" in schema:
                    return json.dumps(schema["const"])
                match schema.get("type"):
                    case "string":
                        return "string"
                    case "integer" | "number":
                        return "number"
                    case "boolean":
                        return "boolean"
                    case "null":
                        return "null"
                    case "array":
                        item = ts_type(schema.get("items", {}))
                        return f"({item})[]" if " " in item else f"{item}[]"
                    case "object":
                        return f"Record<string, {ts_type(schema.get('additionalProperties') or {})}>"
                return "unknown"
            '''
        ),
        md(
            """
            Then one exported `interface` per component schema (`?` marks optional properties):
            """
        ),
        code(
            r'''
            def typescript_declarations(openapi: dict[str, Any]) -> str:
                """One exported interface (or type) per component schema."""
                lines = [
                    f"// Generated from {openapi['info']['title']} {openapi['info']['version']}. Do not edit."
                ]
                for name, schema in openapi["components"]["schemas"].items():
                    if "properties" not in schema:
                        lines.append(f"export type {name} = {ts_type(schema)};")
                        continue
                    required = set(schema.get("required", []))
                    lines.append(f"export interface {name} {{")
                    for prop, prop_schema in schema["properties"].items():
                        lines.append(f"  {prop}{'' if prop in required else '?'}: {ts_type(prop_schema)};")
                    lines.append("}")
                return "\n".join(lines)
            '''
        ),
        md(
            """
            Part 2 writes one `async` function per operation (named after its `operationId`, in
            camelCase), as an ES module that runs on Node's built-in `fetch`. JSDoc comments
            point at the `.d.ts` types, so editors type-check calls even in plain JavaScript:
            """
        ),
        code(
            r'''
            def operation_function(
                path: str, method: str, operation: dict[str, Any], types_file: str
            ) -> list[str]:
                """JavaScript lines for one operation: an async function named after its operationId."""
                name = re.sub(r"_(\w)", lambda match: match[1].upper(), operation["operationId"])
                parameters = operation.get("parameters", [])
                path_names = [parameter["name"] for parameter in parameters if parameter["in"] == "path"]
                has_query = any(parameter["in"] == "query" for parameter in parameters)
                has_body = "requestBody" in operation
                arguments = [
                    "baseUrl",
                    *path_names,
                    *(["body"] if has_body else []),
                    *(["query = {}"] if has_query else []),
                ]
                success = next(
                    (reply for code, reply in operation["responses"].items() if code.startswith("2")), {}
                )
                result_schema = success.get("content", {}).get("application/json", {}).get("schema", {})
                result_type = ts_type(result_schema).replace("Record<string, unknown>", "object")
                if "$ref" in json.dumps(result_schema):
                    result_type = f'import("./{types_file}").{result_type}'
                url_path = re.sub(r"\{(\w+)\}", r"${encodeURIComponent(\1)}", path)
                lines = [
                    f"/** {operation.get('summary', name)}. @returns {{Promise<{result_type}>}} */",
                    f"export async function {name}({', '.join(arguments)}) {{",
                    f"  const url = new URL(`${{baseUrl}}{url_path}`);",
                ]
                if has_query:
                    lines += [
                        "  for (const [key, value] of Object.entries(query)) {",
                        "    for (const item of [value].flat()) url.searchParams.append(key, item);",
                        "  }",
                    ]
                body_argument = "body" if has_body else "undefined"
                return [*lines, f"  return request({method.upper()!r}, url, {body_argument});", "}"]
            '''
        ),
        md(
            """
            The module: a shared `request` helper, then one function per operation:
            """
        ),
        code(
            r'''
            def javascript_client(openapi: dict[str, Any], types_file: str) -> str:
                """An ES module with one fetch-based function per operation."""
                lines = [
                    f"// Generated client for {openapi['info']['title']}. Do not edit.",
                    "async function request(method, url, body) {",
                    '  const headers = { "content-type": "application/json" };',
                    "  const payload = body === undefined ? undefined : JSON.stringify(body);",
                    "  const response = await fetch(url, { method, headers, body: payload });",
                    "  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);",
                    "  return response.status === 204 ? null : response.json();",
                    "}",
                ]
                for path, operations in openapi["paths"].items():
                    for method, operation in operations.items():
                        lines += operation_function(path, method, operation, types_file)
                return "\n".join(lines)
            '''
        ),
        md(
            """
            Generate both files for the Products API, print the types, and run a small Node
            script that imports the client and calls the API served by Uvicorn (skipped without
            `node`):
            """
        ),
        code(
            '''
            CLIENT_DEMO_SOURCE = """
            import { createProduct, getProduct, listProducts } from "./products_client.mjs";
            const baseUrl = process.argv[2];
            const created = await createProduct(baseUrl, { name: "Clay mug", price: "199.00", tags: ["mug"] });
            console.log("created:", created);
            console.log("fetched:", (await getProduct(baseUrl, created.id)).name);
            console.log("listed:", (await listProducts(baseUrl, { limit: 5 })).map((product) => product.name));
            try { await getProduct(baseUrl, 999); } catch (error) { console.log("error:", error.message); }
            """
            (PHASE6_DIR / "products_types.d.ts").write_text(
                typescript_declarations(products_openapi) + "\\n", encoding="utf-8"
            )
            (PHASE6_DIR / "products_client.mjs").write_text(
                javascript_client(products_openapi, "products_types.d.ts") + "\\n", encoding="utf-8"
            )
            (PHASE6_DIR / "products_demo.mjs").write_text(CLIENT_DEMO_SOURCE.strip() + "\\n", encoding="utf-8")
            print((PHASE6_DIR / "products_types.d.ts").read_text(encoding="utf-8"))
            if HAS_NODE:
                with uvicorn_server("products_api:app") as base_url:
                    node_run = subprocess.run(
                        ["node", "products_demo.mjs", base_url],
                        cwd=PHASE6_DIR,
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                print(mask_dates(node_run.stdout + node_run.stderr))
            else:
                print("SKIP the Node demo: the node command is not installed")
            '''
        ),
        md(
            """
            The generated client file, for reference (in a real project it lives in the
            frontend repository and is regenerated in CI whenever `/openapi.json` changes):
            """
        ),
        code(
            """
            print((PHASE6_DIR / "products_client.mjs").read_text(encoding="utf-8")[:1500])
            """
        ),
    ]


def _internals_cells() -> list[NotebookNode]:
    """6.2.10 How FastAPI uses Python."""
    return [
        md(
            """
            ### 6.2.10 How FastAPI uses Python

            Nothing in FastAPI is magic; it is the introspection tools from Phases 1–3:

            1. **Decorators** (Unit 1.12): `app.get(path)` returns a decorator that creates an
               `APIRoute` for your function, stores it, and returns the function **unchanged**.
            2. **`inspect.signature`** (Unit 3.x, 4.2): FastAPI reads every parameter's name,
               default and annotation.
            3. **`Annotated`** (PEP 593): extra metadata (`Query(ge=1)`, `Body(embed=True)`)
               rides along in the annotation without changing the type that type checkers see.
            4. **Classification**: in the path template → path; a model → body; a simple type →
               query; explicit markers win. The result is a `Dependant` object, solved per
               request.
            5. **Pydantic** builds a validator for each parameter and for the response model,
               once, when the route is created; each request only runs them.

            Steps 1 and 2. The decorator gave back the same function object, and the route keeps
            a reference to it:
            """
        ),
        code(
            '''
            introspect_app = FastAPI()


            async def place_order_v2(
                shop_id: int,
                order: NewOrder,
                dry_run: bool = False,
                limit: Annotated[int, Query(ge=1, le=100)] = 20,
                user_agent: Annotated[str | None, fastapi.Header()] = None,
            ) -> dict[str, object]:
                """An endpoint with every kind of parameter."""
                return {}


            decorated = introspect_app.post("/shops/{shop_id}/orders")(place_order_v2)
            route = introspect_app.routes[-1]
            print(
                f"{decorated is place_order_v2=}  {type(route).__name__=}  {route.endpoint is place_order_v2=}"
            )
            for name, parameter in inspect.signature(place_order_v2).parameters.items():
                default = (
                    "(required)" if parameter.default is inspect.Parameter.empty else repr(parameter.default)
                )
                print(f"  {name:<10} {parameter.annotation!s:<60.60} default={default}")
            '''
        ),
        md(
            """
            Step 3: `Annotated[int, Query(ge=1, le=100)]` is still `int` to a type checker;
            `typing.get_args` unpacks the metadata FastAPI reads. *New in 3.14* (PEP 649/749):
            annotations are evaluated lazily, and `annotationlib.get_annotations` can read them
            even when they mention names that do not exist yet (`Format.FORWARDREF`); FastAPI
            and Pydantic use the same machinery:
            """
        ),
        code(
            """
            import annotationlib

            limit_annotation = typing.get_type_hints(place_order_v2, include_extras=True)["limit"]
            base_type, *metadata = typing.get_args(limit_annotation)
            print(f"{typing.get_origin(limit_annotation) is Annotated=}  {base_type=}  {metadata=}")


            def handler_with_future_type(note: NoteNotDefinedYet) -> None:  # noqa: F821
                \"\"\"Its annotation names a class that does not exist (yet).\"\"\"


            print(raised_error_name(lambda: annotationlib.get_annotations(handler_with_future_type)))
            forward = annotationlib.get_annotations(
                handler_with_future_type, format=annotationlib.Format.FORWARDREF
            )
            print(re.sub(r" at 0x[0-9a-f]+", "", repr(forward)))
            """
        ),
        md(
            """
            Step 4: FastAPI's classification, read from the route's `Dependant` (an internal
            object: the attribute names can change between versions):
            """
        ),
        code(
            """
            dependant = route.dependant
            for kind in ("path_params", "query_params", "header_params", "cookie_params", "body_params"):
                print(f"{kind:<14} {[param.name for param in getattr(dependant, kind)]}")
            print(f"{route.response_model=}  {route.status_code=}  {sorted(route.methods)=}")
            """
        ),
        md(
            """
            The same rules in a dozen lines, the annotation-driven injector idea from Unit 1.12.11
            grown up. It gets the same answer for this endpoint:
            """
        ),
        code(
            '''
            def classify_parameters(path: str, endpoint: Callable[..., object]) -> dict[str, list[str]]:
                """Decide where each parameter comes from, roughly as FastAPI does."""
                path_names = set(re.findall(r"\\{(\\w+)", path))
                sources: dict[str, list[str]] = {"path": [], "query": [], "header": [], "body": []}
                for name, annotation in typing.get_type_hints(endpoint, include_extras=True).items():
                    if name == "return":
                        continue
                    markers = (
                        typing.get_args(annotation)[1:] if typing.get_origin(annotation) is Annotated else ()
                    )
                    base = typing.get_args(annotation)[0] if markers else annotation
                    if name in path_names:
                        sources["path"].append(name)
                    elif any(isinstance(marker, fastapi.params.Header) for marker in markers):
                        sources["header"].append(name)
                    elif inspect.isclass(base) and issubclass(base, BaseModel):
                        sources["body"].append(name)
                    else:
                        sources["query"].append(name)
                return sources


            print(classify_parameters("/shops/{shop_id}/orders", place_order_v2))
            '''
        ),
        md(
            """
            Step 5: the validators are Pydantic objects built at startup. The body parameter's
            field carries a `TypeAdapter`-like validator for `NewOrder`; the response model is
            validated the same way. Each request just calls them:
            """
        ),
        code(
            """
            body_field = dependant.body_params[0]
            print(f"{body_field.name=}  {body_field.field_info.annotation=}")
            print(f"{type(NewOrder.__pydantic_validator__).__name__=}")
            print(NewOrder.__pydantic_validator__.validate_json(b'{"sku": "TEA-500", "quantity": 2}'))
            print(f"{route.dependant.call is place_order_v2=}")
            """
        ),
    ]


def _predict_cells() -> list[NotebookNode]:
    """Predict-the-output questions for Unit 6.2."""
    return [
        md(
            """
            ### Predict the output — Unit 6.2

            Three questions on routing, PATCH semantics and lax parsing.
            """
        ),
        *predict_cells(
            """
            app = FastAPI()

            @app.get("/users/{user_id}")
            async def read_user(user_id: int) -> dict[str, int]:
                return {"user_id": user_id}

            @app.get("/users/me")
            async def read_me() -> dict[str, str]:
                return {"user": "me"}

            print(TestClient(app).get("/users/me").status_code)
            """,
            """
            `422`. Routes are tried in declaration order, `/users/{user_id}` matches the path
            `/users/me` first, and `"me"` fails the `int` conversion. Declare fixed paths before
            parameterized ones (6.2.2).
            """,
            '''
            predict_app = FastAPI()


            @predict_app.get("/users/{user_id}")
            async def predict_read_user(user_id: int) -> dict[str, int]:
                """Declared first, so it wins."""
                return {"user_id": user_id}


            @predict_app.get("/users/me")
            async def predict_read_me() -> dict[str, str]:
                """Never reached for /users/me."""
                return {"user": "me"}


            print(TestClient(predict_app).get("/users/me").status_code)
            ''',
        ),
        *predict_cells(
            """
            changes = Preferences.model_validate({"nickname": None})
            print(changes.model_dump(exclude_unset=True))
            print(changes.model_dump(exclude_none=True))
            """,
            """
            `{'nickname': None}` and then `{'theme': 'light', 'page_size': 20}`.
            `exclude_unset` keeps exactly what the client sent, including an explicit `null`
            (so a PATCH can clear a field); `exclude_none` drops every `None`, losing the
            client's intent, and keeps defaults the client never sent.
            """,
            """
            changes = Preferences.model_validate({"nickname": None})
            print(changes.model_dump(exclude_unset=True))
            print(changes.model_dump(exclude_none=True))
            """,
        ),
        *predict_cells(
            """
            class Price(BaseModel):
                amount: Decimal
                count: int

            price = Price(amount="12.50", count=True)
            print(price.count, price.model_dump_json())
            """,
            """
            `1 {"amount":"12.50","count":1}`. Lax mode converts `True` to `1` (a bool is a
            lossless int), and JSON mode writes `Decimal` as a **string** so no precision is
            lost; JavaScript clients must not parse it as a float. Use `Field(strict=True)` to
            refuse booleans.
            """,
            '''
            class Price(BaseModel):
                """Lax int, Decimal amount."""

                amount: Decimal
                count: int


            price = Price(amount="12.50", count=True)
            print(price.count, price.model_dump_json())
            ''',
        ),
    ]


def _lab_cells_part_1() -> list[NotebookNode]:
    """Lab 6.2 exercises 1-2."""
    return [
        md(
            """
            ### Lab 6.2

            Five exercises: the first version of a notes API, its filters, a registration
            model, PATCH, and a benchmark. Every check uses `TestClient` or
            `httpx.ASGITransport` (no server, no network). Replace each `raise
            NotImplementedError` (or `pass`), then run the check cell; until then the checks
            print FAIL, which is expected. After the lab, *Notes API v1* writes the reference
            version into `projects/notes_api/`; do the lab first.

            #### Exercise 1 — Notes API v1: CRUD with Create / Update / Read schemas

            Define three schemas and `create_notes_app()`:

            - `NoteCreate`: `title` (stripped, 1–100 characters), `body` (at most 1000
              characters, default `""`), `pinned` (default `False`); unknown keys → 422.
            - `NoteUpdate`: the same three fields, **all optional** (default `None`); unknown
              keys → 422. (Exercise 4 uses the idea.)
            - `NoteRead`: `id`, `title`, `body`, `pinned`, `created_at` (a `datetime`).
            - `create_notes_app()` returns a **new** `FastAPI` app with its own empty in-memory
              store on every call (ids start at 1):

            | Route | Behaviour |
            | --- | --- |
            | `POST /notes` | `NoteCreate` body → 201, `NoteRead` JSON, `Location: /notes/<id>` |
            | `GET /notes` | 200, every note as `NoteRead`, in id order |
            | `GET /notes/{note_id}` | 200 `NoteRead`; unknown id → 404 `{"detail": "note <id> not found"}` |
            | `PUT /notes/{note_id}` | `NoteCreate` body replaces every field (omitted ones get their defaults) → 200 |
            | `DELETE /notes/{note_id}` | 204 with an empty body; unknown id → 404 |
            """
        ),
        md("Your solution:"),
        code(
            '''
            class NoteCreate(BaseModel):
                """POST/PUT body: title (stripped, 1-100), body (max 1000, default ""), pinned."""


            class NoteUpdate(BaseModel):
                """PATCH body: the same fields, all optional; unknown keys rejected."""


            class NoteRead(BaseModel):
                """Response: id, title, body, pinned, created_at."""


            def create_notes_app() -> FastAPI:
                """Notes API v1: a fresh app with its own empty in-memory store."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 1:"),
        code(
            r'''
            def notes_v1_reads(client: TestClient, results: dict[str, object]) -> None:
                """Create two notes, then read them back (fills results)."""
                first = client.post("/notes", json={"title": "  Buy tea  ", "pinned": True})
                first_note = {key: value for key, value in first.json().items() if key != "created_at"}
                results["create"] = (first.status_code, first.headers.get("location"), first_note)
                results["created_at"] = type(datetime.fromisoformat(first.json()["created_at"])).__name__
                client.post("/notes", json={"title": "Call Ravi", "body": "about the trip"})
                results["list"] = [note["title"] for note in client.get("/notes").json()]
                results["get"] = client.get("/notes/2").json()["body"]
                results["missing"] = (client.get("/notes/99").status_code, client.get("/notes/99").json())
                results["bad id"] = client.get("/notes/abc").status_code
                bad_bodies = [
                    {"title": "   "},
                    {"title": "x" * 101},
                    {"title": "ok", "color": "red"},
                    {"body": "x"},
                ]
                results["invalid"] = [client.post("/notes", json=body).status_code for body in bad_bodies]


            def notes_v1_writes(client: TestClient, results: dict[str, object]) -> None:
                """Replace and delete note 1 (fills results)."""
                replaced = client.put("/notes/1", json={"title": "Buy green tea"})
                results["put"] = (replaced.status_code, replaced.json()["title"], replaced.json()["pinned"])
                results["put missing"] = client.put("/notes/99", json={"title": "x"}).status_code
                deleted = client.delete("/notes/1")
                gone = client.get("/notes/1").status_code
                results["delete"] = (
                    deleted.status_code,
                    deleted.content,
                    gone,
                    client.delete("/notes/1").status_code,
                )
            '''
        ),
        md(
            """
            Run the scenario on a fresh app (and check that a second app starts empty):
            """
        ),
        code(
            r"""
            notes_v1: dict[str, object] = {}
            try:
                with TestClient(create_notes_app()) as client:
                    notes_v1_reads(client, notes_v1)
                    notes_v1_writes(client, notes_v1)
                with TestClient(create_notes_app()) as fresh_client:
                    notes_v1["fresh store"] = fresh_client.get("/notes").json()
            except Exception as error:
                notes_v1["error"] = f"{type(error).__name__}: {error}"
            print(notes_v1.get("error", "scenario ran"))
            """
        ),
        md(
            """
            Check the endpoints:
            """
        ),
        code(
            r"""
            run_checks(
                [
                    (
                        "POST: 201, Location, stripped title",
                        lambda: notes_v1["create"],
                        (201, "/notes/1", {"id": 1, "title": "Buy tea", "body": "", "pinned": True}),
                    ),
                    ("created_at parses as a datetime", lambda: notes_v1["created_at"], "datetime"),
                    ("GET /notes in id order", lambda: notes_v1["list"], ["Buy tea", "Call Ravi"]),
                    ("GET /notes/2", lambda: notes_v1["get"], "about the trip"),
                    (
                        "unknown id -> 404 detail",
                        lambda: notes_v1["missing"],
                        (404, {"detail": "note 99 not found"}),
                    ),
                    ("non-integer id -> 422", lambda: notes_v1["bad id"], 422),
                    ("invalid bodies -> 422", lambda: notes_v1["invalid"], [422, 422, 422, 422]),
                    ("PUT replaces every field", lambda: notes_v1["put"], (200, "Buy green tea", False)),
                    ("PUT unknown id -> 404", lambda: notes_v1["put missing"], 404),
                    ("DELETE: 204 empty, then 404", lambda: notes_v1["delete"], (204, b"", 404, 404)),
                    ("each app has its own store", lambda: notes_v1["fresh store"], []),
                ]
            )
            """
        ),
        md(
            """
            Check the schemas:
            """
        ),
        code(
            r"""
            run_checks(
                [
                    (
                        "NoteUpdate: three optional fields",
                        lambda: (NoteUpdate().model_dump(exclude_unset=True), sorted(NoteUpdate.model_fields)),
                        ({}, ["body", "pinned", "title"]),
                    ),
                    (
                        "NoteUpdate forbids extras",
                        lambda: validation_problems(lambda: NoteUpdate(color="red")),
                        [("color", "extra_forbidden")],
                    ),
                    (
                        "NoteRead fields",
                        lambda: sorted(NoteRead.model_fields),
                        ["body", "created_at", "id", "pinned", "title"],
                    ),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 2 — validated filtering and pagination parameters

            Write `NoteFilters`, a query-parameter model, and `filter_notes(notes, filters)`:

            - `q`: optional text, at most 50 characters; matches notes whose title **or** body
              contains it, ignoring case.
            - `pinned`: optional bool; when given, only notes with that value.
            - `sort`: one of `"id"`, `"-id"`, `"title"`, `"-title"` (default `"id"`); titles
              compare case-insensitively; `-` means descending.
            - `limit`: 1–50, default 10. `offset`: ≥ 0, default 0.
            - Unknown query parameters → 422 (`extra="forbid"`).
            - `filter_notes(notes, filters)` returns `{"items": [...], "total": N, "limit": ...,
              "offset": ...}`, where `total` counts **all** matches before pagination.

            The check cell serves `SAMPLE_NOTES` through a given endpoint,
            `GET /notes` with `filters: Annotated[NoteFilters, Query()]`.
            """
        ),
        code(
            """
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
            """
        ),
        md("Your solution:"),
        code(
            '''
            class NoteFilters(BaseModel):
                """Query parameters for GET /notes: q, pinned, sort, limit, offset; extras rejected."""


            def filter_notes(notes: list[dict[str, Any]], filters: NoteFilters) -> dict[str, object]:
                """Filter, sort and paginate notes; total counts matches before pagination."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 2:"),
        code(
            r'''
            filters_app = FastAPI()


            @filters_app.get("/notes")
            async def search_sample_notes(filters: Annotated[NoteFilters, Query()]) -> dict[str, object]:
                """Given endpoint: apply the learner's model and function to SAMPLE_NOTES."""
                return filter_notes(SAMPLE_NOTES, filters)


            def filters_page(query: str) -> tuple[int, dict[str, Any]]:
                """Status code and JSON body of GET /notes?query."""
                with TestClient(filters_app, raise_server_exceptions=False) as client:
                    response = client.get(f"/notes?{query}")
                return response.status_code, response.json() if response.status_code != 500 else {}


            def page_ids(query: str) -> object:
                """(ids on the page, total), or the status code if the request failed."""
                status_code, page = filters_page(query)
                if status_code != 200:
                    return status_code
                return [note["id"] for note in page["items"]], page["total"]
            '''
        ),
        md(
            """
            Check filtering, sorting and paging:
            """
        ),
        code(
            r"""
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
                        lambda: filters_page("limit=2&offset=4")[1] | {"items": None},
                        {"items": None, "total": 8, "limit": 2, "offset": 4},
                    ),
                ]
            )
            """
        ),
        md(
            """
            Check the validation of the parameters:
            """
        ),
        code(
            r"""
            run_checks(
                [
                    ("limit=0 -> 422", lambda: page_ids("limit=0"), 422),
                    ("limit=51 -> 422", lambda: page_ids("limit=51"), 422),
                    ("offset=-1 -> 422", lambda: page_ids("offset=-1"), 422),
                    ("sort=newest -> 422", lambda: page_ids("sort=newest"), 422),
                    ("q longer than 50 -> 422", lambda: page_ids("q=" + "x" * 51), 422),
                    ("unknown parameter -> 422", lambda: page_ids("colour=red"), 422),
                ]
            )
            """
        ),
    ]


def _lab_cells_part_2() -> list[NotebookNode]:
    """Lab 6.2 exercises 3-5."""
    return [
        md(
            """
            #### Exercise 3 — a `UserRegistration` model with cross-field validation

            Write `UserRegistration` (unknown keys rejected):

            - `username`: stripped and lower-cased, then 3–20 characters of `a-z`, `0-9`, `_`.
            - `email`: an `EmailStr`.
            - `password`: at least 12 characters, with at least one letter **and** one digit.
            - `password_confirm`: must equal `password` (error message contains
              `passwords do not match`); **excluded** from `model_dump()`.
            - `birth_date` and `signup_date` (both `date`): the user must be at least 13 years
              old on `signup_date` (message contains `at least 13`).
            - `accept_terms`: must be `True`.

            The checks look at error **locations** (where the problem is), not the exact error
            types, so any correct validator style passes.
            """
        ),
        md("Your solution:"),
        code(
            '''
            class UserRegistration(BaseModel):
                """Sign-up form with field rules and cross-field rules (see the exercise text)."""

                @model_validator(mode="before")
                @classmethod
                def not_written_yet(cls, data: object) -> object:
                    """Placeholder: delete it when you add the fields and validators."""
                    raise NotImplementedError
            '''
        ),
        md("Check exercise 3:"),
        code(
            r'''
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


            def signup_dump(**changes: object) -> dict[str, Any]:
                """model_dump(mode="json") of VALID_SIGNUP with changes applied."""
                return UserRegistration.model_validate({**VALID_SIGNUP, **changes}).model_dump(mode="json")
            '''
        ),
        md(
            """
            Check the field rules:
            """
        ),
        code(
            r"""
            run_checks(
                [
                    (
                        "valid registration dumps cleanly",
                        signup_dump,
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
                ]
            )
            """
        ),
        md(
            """
            Check the remaining rules, including the cross-field ones:
            """
        ),
        code(
            r"""
            run_checks(
                [
                    (
                        "terms must be accepted",
                        lambda: signup_error_locations(accept_terms=False),
                        ["accept_terms"],
                    ),
                    ("unknown key rejected", lambda: signup_error_locations(is_admin=True), ["is_admin"]),
                    (
                        "passwords differ",
                        lambda: (
                            "passwords do not match" in signup_messages(password_confirm="chai4ever-and-less")
                        ),
                        True,
                    ),
                    (
                        "13th birthday is the cutoff",
                        lambda: signup_dump(birth_date="2013-11-17")["birth_date"],
                        "2013-11-17",
                    ),
                    (
                        "one day too young",
                        lambda: "at least 13" in signup_messages(birth_date="2013-11-18"),
                        True,
                    ),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 4 — a PATCH endpoint

            Write `NotePatch` and `create_patch_app(seed)`. The app keeps a **copy** of `seed`
            (a dict of id → note dict with `id`, `title`, `body`, `pinned`, `version`) and has:

            - `GET /notes/{note_id}` → the note (404 `{"detail": "note <id> not found"}` if
              unknown);
            - `PATCH /notes/{note_id}` with a `NotePatch` body → the updated note. Only the
              fields the client **sent** change (`exclude_unset`). `version` goes up by one only
              when a value actually changed (`{}` or the same values leave it alone).

            `NotePatch` has optional `title` (stripped, 1–100), `body` (≤ 1000) and `pinned`;
            unknown keys → 422; and an explicit `null` for any field → 422 (none of them is
            nullable).
            """
        ),
        md("Your solution:"),
        code(
            '''
            class NotePatch(BaseModel):
                """PATCH body: optional title/body/pinned; explicit null and unknown keys rejected."""


            def create_patch_app(seed: dict[int, dict[str, Any]]) -> FastAPI:
                """GET and PATCH /notes/{note_id} over a copy of seed."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 4:"),
        code(
            r'''
            PATCH_SEED = {1: {"id": 1, "title": "Buy tea", "body": "Assam", "pinned": False, "version": 1}}


            def patch_scenario() -> dict[str, Any]:
                """A fixed sequence of PATCH requests against a fresh app."""
                results: dict[str, Any] = {}
                with TestClient(create_patch_app(PATCH_SEED)) as client:
                    results["pin"] = client.patch("/notes/1", json={"pinned": True}).json()
                    results["retitle"] = client.patch("/notes/1", json={"title": "  Buy green tea "}).json()
                    results["empty"] = client.patch("/notes/1", json={}).json()["version"]
                    results["same value"] = client.patch("/notes/1", json={"pinned": True}).json()["version"]
                    bad_bodies = [{"title": None}, {"pinned": None}, {"title": ""}, {"color": "red"}]
                    results["errors"] = [client.patch("/notes/1", json=body).status_code for body in bad_bodies]
                    missing = client.patch("/notes/99", json={"pinned": True}).status_code
                    results["missing"] = (missing, client.get("/notes/99").json())
                    results["get"] = client.get("/notes/1").json()
                return results


            try:
                patched = patch_scenario()
            except Exception as error:
                patched = {"error": f"{type(error).__name__}: {error}"}
            print(patched.get("error", "scenario ran"))
            '''
        ),
        md(
            """
            Check exercise 4:
            """
        ),
        code(
            r"""
            run_checks(
                [
                    (
                        "only pinned changes, version 2",
                        lambda: patched["pin"],
                        {"id": 1, "title": "Buy tea", "body": "Assam", "pinned": True, "version": 2},
                    ),
                    (
                        "title stripped, version 3",
                        lambda: tuple(patched["retitle"][key] for key in ("title", "body", "version")),
                        ("Buy green tea", "Assam", 3),
                    ),
                    ("{} changes nothing", lambda: patched["empty"], 3),
                    ("same value changes nothing", lambda: patched["same value"], 3),
                    ("null, empty title, unknown key -> 422", lambda: patched["errors"], [422, 422, 422, 422]),
                    ("unknown id -> 404", lambda: patched["missing"], (404, {"detail": "note 99 not found"})),
                    ("GET sees the changes", lambda: patched["get"]["title"], "Buy green tea"),
                    (
                        "seed was not modified",
                        lambda: (patched["get"]["version"], PATCH_SEED[1]["version"]),
                        (3, 1),
                    ),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 5 — a blocking-vs-async benchmark

            Write two functions:

            - `async benchmark_endpoints(app, paths, request_count=8)`: for each path, send
              `request_count` **concurrent** GET requests to `app` through
              `httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bench")`
              and measure the wall time; return `{path: seconds}` in the order of `paths`.
            - `diagnose(timings, delay, request_count)`: for each path, `"serialized"` if its
              time is at least `0.75 * delay * request_count` (the requests ran one after
              another), else `"concurrent"`.

            The check runs them on `bench_app`, whose three endpoints each wait `BENCH_DELAY`
            seconds in a different way, then checks `diagnose` on its own.
            """
        ),
        code(
            '''
            BENCH_DELAY = 0.05
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
            '''
        ),
        md("Your solution:"),
        code(
            '''
            async def benchmark_endpoints(
                app: FastAPI, paths: list[str], request_count: int = 8
            ) -> dict[str, float]:
                """Wall seconds for request_count concurrent GETs of each path, in order."""
                raise NotImplementedError


            def diagnose(timings: dict[str, float], delay: float, request_count: int) -> dict[str, str]:
                """ "serialized" if a path took at least 0.75 * delay * request_count, else "concurrent"."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 5:"),
        code(
            r"""
            bench_paths = ["/async-blocking", "/sync-blocking", "/async-sleep"]
            try:
                bench_timings = await benchmark_endpoints(bench_app, bench_paths, request_count=8)
            except Exception as error:
                bench_timings = {"error": f"{type(error).__name__}"}
            if all(isinstance(seconds, float) for seconds in bench_timings.values()):
                print({path: f"{seconds:.3f} s" for path, seconds in bench_timings.items()})
            """
        ),
        md(
            """
            Check exercise 5:
            """
        ),
        code(
            r"""
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
                        lambda: bench_timings["/sync-blocking"] < 0.2 and bench_timings["/async-sleep"] < 0.2,
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
            """
        ),
    ]


NOTES_PYPROJECT = r"""
%%writefile ../projects/notes_api/pyproject.toml
[project]
name = "notes-api"
version = "0.1.0"
description = "The Phase 6 Notes API: a FastAPI service built step by step from Unit 6.2 to 6.8."
readme = "README.md"
requires-python = ">=3.15"
dependencies = [
    "fastapi[standard]>=0.163.1",
]

[dependency-groups]
dev = [
    "pytest>=9.2.0",
]

[build-system]
requires = ["uv_build>=0.13,<0.14"]
build-backend = "uv_build"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
addopts = "-q"
"""

NOTES_RUFF = r"""
%%writefile ../projects/notes_api/ruff.toml
# Extends the course configuration; notes_api (src/) and the tests are first-party imports.
extend = "../../pyproject.toml"
src = ["src", "tests"]
"""

NOTES_README = r"""
%%writefile ../projects/notes_api/README.md
# Notes API

A FastAPI service for creating, searching and organizing notes. It is built step by step in
Phase 6 of the course (`notebooks/phase6_web_fastapi.ipynb`); the notebook writes these files.

| Version | Unit | Adds |
| --- | --- | --- |
| v1 | 6.2 | CRUD path operations, Pydantic v2 schemas, filtering and pagination, OpenAPI |

## Run

```bash
cd projects/notes_api
uv run uvicorn notes_api.main:app --reload   # creates .venv; http://127.0.0.1:8000/docs
uv run pytest
```

## Endpoints

| Method | Path | Success | Notes |
| --- | --- | --- | --- |
| `GET` | `/health` | 200 | liveness probe |
| `POST` | `/notes` | 201 | `Location` header; body `NoteCreate` |
| `GET` | `/notes` | 200 | `q`, `tag` (repeatable), `pinned`, `sort`, `limit` (1-100), `offset` |
| `GET` | `/notes/{note_id}` | 200 | 404 if unknown |
| `PUT` | `/notes/{note_id}` | 200 | replaces every field |
| `PATCH` | `/notes/{note_id}` | 200 | only the fields sent; explicit `null` is rejected |
| `DELETE` | `/notes/{note_id}` | 204 | |

## Layout

```text
src/notes_api/
├── __init__.py   # version
├── main.py       # the FastAPI app and its path operations
├── schemas.py    # Pydantic models: NoteCreate, NoteUpdate, NoteRead, NoteFilters, NotePage
└── store.py      # in-memory storage (replaced by a database in Unit 6.4)
tests/            # pytest + TestClient
```
"""

NOTES_INIT = r'''
%%writefile ../projects/notes_api/src/notes_api/__init__.py
"""Notes API: a FastAPI service built step by step in Phase 6 of the course."""

__version__ = "0.1.0"
'''

NOTES_SCHEMAS = r'''
%%writefile ../projects/notes_api/src/notes_api/schemas.py
"""Request and response schemas for the Notes API (Pydantic v2).

One schema per direction: NoteCreate (POST/PUT body), NoteUpdate (PATCH body, every field
optional), NoteRead (responses, with server-owned fields), NoteFilters (query parameters) and
NotePage (one page of results).
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


class NotePage(BaseModel):
    """One page of notes, plus what a client needs to ask for the next one."""

    items: list[NoteRead]
    total: int
    limit: int
    offset: int


class ErrorMessage(BaseModel):
    """Body of 404 responses (and every HTTPException)."""

    detail: str
'''

NOTES_STORE = r'''
%%writefile ../projects/notes_api/src/notes_api/store.py
"""In-memory storage for notes. Unit 6.4 replaces it with SQLAlchemy behind the same methods."""

import dataclasses
import itertools
from collections.abc import Callable
from datetime import UTC, datetime

from notes_api.schemas import NoteCreate, NoteFilters, NoteUpdate


@dataclasses.dataclass(slots=True)
class Note:
    """A stored note: the server's own record, not a schema."""

    id: int
    title: str
    body: str
    tags: list[str]
    pinned: bool
    created_at: datetime
    updated_at: datetime


class NoteNotFoundError(LookupError):
    """No note has the requested id."""

    def __init__(self, note_id: int) -> None:
        """Remember the id; the message is what the API sends as the 404 detail."""
        super().__init__(f"note {note_id} not found")
        self.note_id = note_id


def utc_now() -> datetime:
    """The current time in UTC (the default clock)."""
    return datetime.now(UTC)


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


class NoteStore:
    """Notes in a dict, ids from a counter. Used only from async handlers (one thread)."""

    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        """Start empty; clock supplies created_at/updated_at (injectable for tests)."""
        self.clock = clock
        self._notes: dict[int, Note] = {}
        self._ids = itertools.count(1)

    def clear(self) -> None:
        """Remove every note and restart ids at 1."""
        self._notes.clear()
        self._ids = itertools.count(1)

    def add(self, data: NoteCreate) -> Note:
        """Store a new note."""
        now = self.clock()
        note = Note(id=next(self._ids), **data.model_dump(), created_at=now, updated_at=now)
        self._notes[note.id] = note
        return note

    def get(self, note_id: int) -> Note:
        """The note with this id, or NoteNotFoundError."""
        try:
            return self._notes[note_id]
        except KeyError:
            raise NoteNotFoundError(note_id) from None

    def search(self, filters: NoteFilters) -> tuple[list[Note], int]:
        """One page of matching notes, and how many notes match in total."""
        found = [note for note in self._notes.values() if matches(note, filters)]
        descending = filters.sort.startswith("-")
        found.sort(key=sort_key(filters.sort.removeprefix("-")), reverse=descending)
        return found[filters.offset : filters.offset + filters.limit], len(found)

    def replace(self, note_id: int, data: NoteCreate) -> Note:
        """Replace every client-owned field (PUT)."""
        note = self.get(note_id)
        replaced = dataclasses.replace(note, **data.model_dump(), updated_at=self.clock())
        self._notes[note_id] = replaced
        return replaced

    def update(self, note_id: int, changes: NoteUpdate) -> Note:
        """Apply only the fields the client sent (PATCH); updated_at moves only on a change."""
        note = self.get(note_id)
        sent = changes.model_dump(exclude_unset=True)
        if all(getattr(note, name) == value for name, value in sent.items()):
            return note
        updated = dataclasses.replace(note, **sent, updated_at=self.clock())
        self._notes[note_id] = updated
        return updated

    def delete(self, note_id: int) -> None:
        """Remove the note, or raise NoteNotFoundError."""
        self.get(note_id)
        del self._notes[note_id]
'''

NOTES_MAIN = r'''
%%writefile ../projects/notes_api/src/notes_api/main.py
"""The Notes API application.

Unit 6.2 version: path operations, Pydantic schemas, response models, status codes, errors and
OpenAPI metadata. Later units add dependency injection and routers (6.3), a database (6.4),
authentication (6.5), background jobs and caching (6.6), observability (6.7) and deployment (6.8).
"""

from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Path, Query, Response, status
from fastapi.routing import APIRoute

from notes_api import __version__
from notes_api.schemas import ErrorMessage, NoteCreate, NoteFilters, NotePage, NoteRead, NoteUpdate
from notes_api.store import Note, NoteNotFoundError, NoteStore


def operation_id(route: APIRoute) -> str:
    """Use the function name as the OpenAPI operationId (clean names in generated clients)."""
    return route.name


app = FastAPI(
    title="Notes API",
    version=__version__,
    summary="Create, search and organize notes.",
    description="Built step by step in Phase 6 of the course. Timestamps are UTC, ISO 8601.",
    openapi_tags=[
        {"name": "notes", "description": "Create, read, update and delete notes."},
        {"name": "health", "description": "Liveness probe for load balancers and tests."},
    ],
    generate_unique_id_function=operation_id,
)

notes_store = NoteStore()  # module-level for now; Unit 6.3 turns it into a dependency

NoteId = Annotated[int, Path(ge=1, description="The note's id.")]
NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorMessage, "description": "No note has this id."}
}


def find_note(note_id: int) -> Note:
    """The stored note, or an HTTP 404."""
    try:
        return notes_store.get(note_id)
    except NoteNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.post("/notes", response_model=NoteRead, status_code=status.HTTP_201_CREATED, tags=["notes"])
async def create_note(note: NoteCreate, response: Response) -> Note:
    """Create a note; the Location header points at it."""
    created = notes_store.add(note)
    response.headers["Location"] = app.url_path_for("get_note", note_id=str(created.id))
    return created


@app.get("/notes", response_model=NotePage, tags=["notes"])
async def list_notes(filters: Annotated[NoteFilters, Query()]) -> dict[str, object]:
    """Search, filter, sort and paginate notes."""
    notes, total = notes_store.search(filters)
    return {"items": notes, "total": total, "limit": filters.limit, "offset": filters.offset}


@app.get("/notes/{note_id}", response_model=NoteRead, responses=NOT_FOUND, tags=["notes"])
async def get_note(note_id: NoteId) -> Note:
    """Fetch one note."""
    return find_note(note_id)


@app.put("/notes/{note_id}", response_model=NoteRead, responses=NOT_FOUND, tags=["notes"])
async def replace_note(note_id: NoteId, note: NoteCreate) -> Note:
    """Replace every field of a note (omitted fields get their defaults)."""
    find_note(note_id)
    return notes_store.replace(note_id, note)


@app.patch("/notes/{note_id}", response_model=NoteRead, responses=NOT_FOUND, tags=["notes"])
async def update_note(note_id: NoteId, changes: NoteUpdate) -> Note:
    """Change only the fields sent in the body."""
    find_note(note_id)
    return notes_store.update(note_id, changes)


@app.delete(
    "/notes/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=NOT_FOUND,
    tags=["notes"],
)
async def delete_note(note_id: NoteId) -> None:
    """Delete a note."""
    find_note(note_id)
    notes_store.delete(note_id)
'''

NOTES_CONFTEST = r'''
%%writefile ../projects/notes_api/tests/conftest.py
"""Shared fixtures: a TestClient whose in-memory store starts empty for every test."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from notes_api.main import app, notes_store


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A TestClient for the app, on an empty store."""
    notes_store.clear()
    with TestClient(app) as test_client:
        yield test_client
'''

NOTES_TESTS = r'''
%%writefile ../projects/notes_api/tests/test_notes.py
"""Behaviour of the Notes API v1 endpoints."""

from typing import Any

import pytest
from fastapi.testclient import TestClient


def create(client: TestClient, **fields: Any) -> dict[str, Any]:
    """POST a note (title defaults to "Buy tea") and return the created note."""
    response = client.post("/notes", json={"title": "Buy tea", **fields})
    assert response.status_code == 201, response.text
    return response.json()


def ids(response: Any) -> list[int]:
    """Ids of the notes on a page."""
    assert response.status_code == 200, response.text
    return [note["id"] for note in response.json()["items"]]


def test_health(client: TestClient) -> None:
    """GET /health answers ok."""
    assert client.get("/health").json() == {"status": "ok"}


def test_create_returns_201_location_and_normalized_fields(client: TestClient) -> None:
    """POST returns 201, a Location header and cleaned-up fields."""
    response = client.post(
        "/notes", json={"title": "  Buy tea  ", "body": "Assam, 500 g", "tags": ["Shop", "shop"]}
    )
    assert response.status_code == 201
    assert response.headers["location"] == "/notes/1"
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
    """Invalid bodies are 422 errors pointing at the bad field."""
    response = client.post("/notes", json=body)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == location


def test_get_one_and_unknown_id(client: TestClient) -> None:
    """GET one note; unknown ids are 404, non-positive ids 422."""
    created = create(client)
    assert client.get("/notes/1").json() == created
    missing = client.get("/notes/99")
    assert (missing.status_code, missing.json()) == (404, {"detail": "note 99 not found"})
    assert client.get("/notes/0").status_code == 422


def test_list_paginates_and_counts_all_matches(client: TestClient) -> None:
    """limit/offset select a page; total counts every match."""
    for number in range(5):
        create(client, title=f"Note {number}")
    response = client.get("/notes", params={"limit": 2, "offset": 2, "sort": "created_at"})
    assert ids(response) == [3, 4]
    assert {key: response.json()[key] for key in ("total", "limit", "offset")} == {
        "total": 5,
        "limit": 2,
        "offset": 2,
    }


def test_list_default_order_is_newest_first(client: TestClient) -> None:
    """Without sort, the newest note comes first."""
    for title in ("first", "second", "third"):
        create(client, title=title)
    assert ids(client.get("/notes")) == [3, 2, 1]


def test_list_filters_by_tag_pinned_and_text(client: TestClient) -> None:
    """tag (all of them), pinned and q filter the list."""
    create(client, title="Buy tea", tags=["shopping", "home"], pinned=True)
    create(client, title="Call Ravi", body="about the TEA estate trip", tags=["home"])
    create(client, title="Pay bill", tags=["shopping"])
    assert ids(client.get("/notes?tag=home&sort=created_at")) == [1, 2]
    assert ids(client.get("/notes?tag=home&tag=shopping")) == [1]
    assert ids(client.get("/notes?pinned=false&sort=created_at")) == [2, 3]
    assert ids(client.get("/notes?q=tea&sort=created_at")) == [1, 2]


def test_list_sorts_titles_ignoring_case(client: TestClient) -> None:
    """sort=title ignores case."""
    for title in ("banana", "Apple", "cherry"):
        create(client, title=title)
    titles = [note["title"] for note in client.get("/notes?sort=title").json()["items"]]
    assert titles == ["Apple", "banana", "cherry"]


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "sort=newest", "x=1"])
def test_list_rejects_bad_parameters(client: TestClient, query: str) -> None:
    """Out-of-range or unknown query parameters are 422 errors."""
    assert client.get(f"/notes?{query}").status_code == 422


def test_put_replaces_every_field(client: TestClient) -> None:
    """PUT resets every field the body leaves out."""
    create(client, tags=["home"], pinned=True, body="old body")
    replaced = client.put("/notes/1", json={"title": "Buy green tea"})
    assert replaced.status_code == 200
    assert {key: replaced.json()[key] for key in ("title", "body", "tags", "pinned")} == {
        "title": "Buy green tea",
        "body": "",
        "tags": [],
        "pinned": False,
    }


def test_patch_changes_only_the_fields_sent(client: TestClient) -> None:
    """PATCH changes only the fields in the body."""
    created = create(client, body="Assam", tags=["home"])
    patched = client.patch("/notes/1", json={"pinned": True}).json()
    assert patched["pinned"] is True
    assert {key: patched[key] for key in ("title", "body", "tags")} == {
        key: created[key] for key in ("title", "body", "tags")
    }
    assert patched["updated_at"] >= created["updated_at"]


def test_patch_without_a_change_keeps_updated_at(client: TestClient) -> None:
    """A PATCH that changes nothing keeps updated_at."""
    created = create(client, pinned=True)
    for body in ({}, {"pinned": True}):
        assert client.patch("/notes/1", json=body).json()["updated_at"] == created["updated_at"]


@pytest.mark.parametrize("body", [{"title": None}, {"pinned": None}, {"colour": "red"}])
def test_patch_rejects_null_and_unknown_fields(client: TestClient, body: dict[str, Any]) -> None:
    """PATCH refuses explicit nulls and unknown fields."""
    create(client)
    assert client.patch("/notes/1", json=body).status_code == 422


def test_delete_then_gone(client: TestClient) -> None:
    """DELETE answers 204 and the note is gone."""
    create(client)
    deleted = client.delete("/notes/1")
    assert (deleted.status_code, deleted.content) == (204, b"")
    assert client.get("/notes/1").status_code == 404


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_unknown_note_is_404_for_every_method(client: TestClient, method: str) -> None:
    """PUT, PATCH and DELETE on an unknown id are 404 errors."""
    kwargs = {} if method == "delete" else {"json": {"title": "x"}}
    response = client.request(method.upper(), "/notes/99", **kwargs)
    assert (response.status_code, response.json()) == (404, {"detail": "note 99 not found"})


def test_openapi_uses_function_names_as_operation_ids(client: TestClient) -> None:
    """operationIds are the handler function names."""
    paths = client.get("/openapi.json").json()["paths"]
    operation_ids = {op["operationId"] for ops in paths.values() for op in ops.values()}
    assert operation_ids == {
        "health",
        "create_note",
        "list_notes",
        "get_note",
        "replace_note",
        "update_note",
        "delete_note",
    }
'''


def _notes_project_cells() -> list[NotebookNode]:
    """Notes API v1: the project files written into projects/notes_api/."""
    return [
        md(
            """
            ### Notes API v1 — the project files

            Unit 6.2's techniques, assembled into the application the rest of Phase 6 grows.
            The cells below **write the files** of `projects/notes_api/` (compare them with your
            Lab 6.2 answers). It is a uv project of its own from the start, so it can get its
            own lock file now and a container image in Unit 6.8:

            ```text
            projects/notes_api/
            ├── pyproject.toml        # dependencies: fastapi[standard]; dev: pytest
            ├── uv.lock               # created by `uv lock` below
            ├── ruff.toml             # extends the course's ruff settings
            ├── README.md
            ├── src/notes_api/
            │   ├── __init__.py       # __version__
            │   ├── schemas.py        # NoteCreate / NoteUpdate / NoteRead / NoteFilters / NotePage
            │   ├── store.py          # NoteStore: in-memory, replaced by SQLAlchemy in 6.4
            │   └── main.py           # the FastAPI app and its path operations
            └── tests/
                ├── conftest.py       # `client` fixture: TestClient on an empty store
                └── test_notes.py
            ```

            The course's own environment (the notebook kernel) has the same packages, so the
            notebook can import `notes_api` from `src/` directly.

            First the project metadata. `pythonpath = ["src"]` lets pytest import the package
            even without installing it:
            """
        ),
        code(NOTES_PYPROJECT),
        md("Ruff settings (inherit the course configuration):"),
        code(NOTES_RUFF),
        md("The README: what the service is, how to run it and how to test it:"),
        code(NOTES_README),
        md("The package marker with the version that `/openapi.json` reports:"),
        code(NOTES_INIT),
        md(
            """
            **`schemas.py`.** Reusable `Annotated` types (`Title`, `Tag`, `Tags`), the three
            directions of the note (Create, Update, Read), the query-parameter model and the
            page envelope. `NoteUpdate` rejects an explicit `null`, the hole in plain
            `exclude_unset` PATCH handling noted in 6.2.6. `NoteRead.word_count` is a computed
            field:
            """
        ),
        *writefile_cells(
            NOTES_SCHEMAS,
            [
                ("", "Part 1 of `schemas.py`: imports and the slug check for tags."),
                (
                    "def unique_in_order(",
                    "Part 2: reusable `Annotated` types for titles, bodies, tags, sort orders.",
                ),
                ("class NoteCreate(BaseModel):", "Part 3: `NoteCreate`, the body of POST and PUT."),
                (
                    "class NoteUpdate(BaseModel):",
                    "Part 4: `NoteUpdate`, the PATCH body, which rejects explicit `null`.",
                ),
                (
                    "class NoteRead(BaseModel):",
                    "Part 5: `NoteRead` (computed `word_count`) and the query model `NoteFilters`.",
                ),
                ("class NotePage(BaseModel):", "Part 6: the page envelope and the error body."),
            ],
        ),
        md(
            """
            **`store.py`.** The storage layer: a `Note` dataclass (the server's record), a
            `NoteNotFoundError`, and `NoteStore` with `add / get / search / replace / update /
            delete`. The clock is injectable so tests can control time. Unit 6.4 swaps the dict
            for SQLAlchemy behind the same method names, so `main.py` will barely change:
            """
        ),
        *writefile_cells(
            NOTES_STORE,
            [
                ("", "Part 1 of `store.py`: the stored record, the not-found error and the clock."),
                ("def matches(", "Part 2: the filtering and sorting helpers."),
                ("class NoteStore:", "Part 3: `NoteStore`, creating and reading notes."),
                (
                    "    def search(",
                    "Part 4: search, replace, update and delete (this part continues the class).",
                ),
            ],
        ),
        md(
            """
            **`main.py`.** The app with OpenAPI metadata and function-name operation ids, a
            health check and the six note operations. Handlers return `Note` dataclasses;
            `response_model=NoteRead` converts and filters them. The store is a module-level
            object for now; Unit 6.3 replaces it with dependency injection (and splits the
            routes into an `APIRouter`):
            """
        ),
        *writefile_cells(
            NOTES_MAIN,
            [
                ("", "Part 1 of `main.py`: imports and the operation-id function."),
                (
                    "app = FastAPI(",
                    "Part 2: the app and its OpenAPI metadata, the store, shared types, health.",
                ),
                ('@app.post("/notes"', "Part 3: create, list and fetch."),
                ('@app.put("/notes/{note_id}"', "Part 4: replace, update and delete."),
            ],
        ),
        md(
            """
            Import the app from the files just written and walk through the API with
            `TestClient`. Timestamps are left out of the printout because they change on every
            run:
            """
        ),
        code(
            '''
            notes_main = reload_notes_api()
            notes_main.notes_store.clear()


            def short(note: dict[str, Any]) -> dict[str, Any]:
                """A note without its timestamps."""
                return {key: value for key, value in note.items() if not key.endswith("_at")}


            with TestClient(notes_main.app) as client:
                created = client.post(
                    "/notes",
                    json={"title": "Buy tea", "body": "Assam, 500 g", "tags": ["Shopping"], "pinned": True},
                )
                print(created.status_code, created.headers["location"], short(created.json()))
                client.post("/notes", json={"title": "Call Ravi", "body": "about the trip", "tags": ["home"]})
                client.post("/notes", json={"title": "Pay the electricity bill", "tags": ["home", "bills"]})
                page = client.get("/notes", params={"tag": "home", "sort": "title", "limit": 10}).json()
                print("tag=home:", [note["title"] for note in page["items"]], "total", page["total"])
                print(
                    "PATCH:",
                    short(client.patch("/notes/2", json={"pinned": True, "tags": ["home", "travel"]}).json()),
                )
                print("PATCH null:", client.patch("/notes/2", json={"title": None}).json()["detail"][0]["msg"])
                print(
                    "DELETE:", client.delete("/notes/3").status_code, "then GET:", client.get("/notes/3").json()
                )
            '''
        ),
        md(
            """
            **Tests.** The `client` fixture clears the module-level store before each test
            (which is exactly the coupling Unit 6.3's dependency injection removes). The tests
            cover every route, the validation rules, filtering and sorting, PATCH semantics and
            the OpenAPI operation ids:
            """
        ),
        code(NOTES_CONFTEST),
        *writefile_cells(
            NOTES_TESTS,
            [
                ("", "Part 1 of `test_notes.py`: two helpers and the health check."),
                ("def test_create_returns_201", "Part 2: creating notes, valid and invalid."),
                ("def test_get_one_and_unknown_id", "Part 3: fetching one note, and pagination."),
                ("def test_list_default_order", "Part 4: default order and filters."),
                (
                    "def test_list_sorts_titles_ignoring_case",
                    "Part 5: sorting, bad parameters and PUT.",
                ),
                ("def test_patch_changes_only", "Part 6: PATCH semantics and DELETE."),
                (
                    '@pytest.mark.parametrize("method"',
                    "Part 7: 404 for every method, and the operation ids.",
                ),
            ],
        ),
        md(
            """
            Run the suite with the kernel's environment (`python -m pytest` inside the project
            folder, where `pyproject.toml` configures pytest):
            """
        ),
        code(
            """
            pytest_run = subprocess.run(
                [sys.executable, "-m", "pytest", "-p", "no:cacheprovider"],
                cwd=NOTES_API_DIR,
                capture_output=True,
                text=True,
                env=CHILD_ENV,
                timeout=300,
            )
            print(tidy_test_output(pytest_run.stdout + pytest_run.stderr).splitlines()[-1])
            print(f"{pytest_run.returncode=}")
            """
        ),
        md(
            """
            And as a project of its own: `uv lock` resolves the dependencies into
            `projects/notes_api/uv.lock` (unchanged on later runs unless `pyproject.toml`
            changes), and `uv run pytest` creates the project's own `.venv` (git-ignored) and
            runs the tests there, which is what CI and the Docker image in Unit 6.8 will do.
            The first run downloads or links packages and takes a few seconds; offline, uv uses
            its cache or the cell prints a skip message:
            """
        ),
        code(
            """
            if HAS_UV:
                lock_run = subprocess.run(
                    ["uv", "lock"],
                    cwd=NOTES_API_DIR,
                    capture_output=True,
                    text=True,
                    env=CHILD_ENV,
                    timeout=600,
                )
                print(
                    tidy_test_output(lock_run.stderr).splitlines()[-1]
                    if lock_run.stderr
                    else lock_run.returncode
                )
                if lock_run.returncode == 0:
                    uv_pytest = subprocess.run(
                        ["uv", "run", "--frozen", "pytest", "-p", "no:cacheprovider"],
                        cwd=NOTES_API_DIR,
                        capture_output=True,
                        text=True,
                        env=CHILD_ENV,
                        timeout=600,
                    )
                    print(
                        tidy_test_output(uv_pytest.stdout).splitlines()[-1],
                        f"(exit code {uv_pytest.returncode})",
                    )
                else:
                    print("SKIP uv run pytest: uv lock failed (offline with an empty cache?)")
            else:
                print("SKIP: the uv command is not on PATH")
            print(f"{(NOTES_API_DIR / 'uv.lock').exists()=}")
            """
        ),
        md(
            """
            Finally, the real thing: Uvicorn serves `notes_api.main:app` from `src/` in a child
            process; the 6.2.9 generator turns its live `/openapi.json` into TypeScript types and
            a client; a Node script uses the client to create and query notes (skipped without
            `node`). This is the contract a frontend team would build against:
            """
        ),
        code(
            '''
            NOTES_DEMO_SOURCE = """
            import { createNote, listNotes, updateNote } from "./notes_client.mjs";
            const baseUrl = process.argv[2];
            const tea = await createNote(baseUrl, { title: "Buy tea", tags: ["shopping"] });
            await createNote(baseUrl, { title: "Plan the Goa trip", body: "tickets, hotel", tags: ["travel"] });
            await updateNote(baseUrl, tea.id, { pinned: true });
            const pinned = await listNotes(baseUrl, { pinned: true });
            console.log("pinned:", pinned.items.map((note) => note.title), "total:", pinned.total);
            const travel = await listNotes(baseUrl, { tag: ["travel"], sort: "title" });
            console.log("travel:", travel.items.map((note) => `${note.title} (${note.word_count} words)`));
            """
            with uvicorn_server("notes_api.main:app", app_dir=NOTES_SRC) as base_url:
                notes_openapi = httpx.get(f"{base_url}/openapi.json", trust_env=False).json()
                (PHASE6_DIR / "notes_types.d.ts").write_text(
                    typescript_declarations(notes_openapi) + "\\n", encoding="utf-8"
                )
                (PHASE6_DIR / "notes_client.mjs").write_text(
                    javascript_client(notes_openapi, "notes_types.d.ts") + "\\n", encoding="utf-8"
                )
                (PHASE6_DIR / "notes_demo.mjs").write_text(NOTES_DEMO_SOURCE.strip() + "\\n", encoding="utf-8")
                if HAS_NODE:
                    node_run = subprocess.run(
                        ["node", "notes_demo.mjs", base_url],
                        cwd=PHASE6_DIR,
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    print(node_run.stdout + node_run.stderr)
                else:
                    print("SKIP the Node demo: the node command is not installed")
            print(
                re.search(
                    r"export interface NoteRead \\{.*?\\}",
                    (PHASE6_DIR / "notes_types.d.ts").read_text(encoding="utf-8"),
                    re.S,
                )[0]
            )
            '''
        ),
        md(
            """
            What v1 deliberately leaves for later units: the module-level `notes_store` (tests
            must reset it; Unit 6.3 injects it with `Depends`), one big module of routes (6.3:
            `APIRouter`), no settings or CORS (6.3), memory-only storage (6.4: SQLAlchemy and
            Alembic), no users (6.5: authentication and ownership), no background work (6.6),
            no metrics or tracing (6.7), no container (6.8).
            """
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 6.2."""
    return [
        md(
            """
            ### Recap — Unit 6.2

            | Concept | One-line takeaway | JS / TS equivalent |
            | --- | --- | --- |
            | Architecture | FastAPI = Starlette (ASGI, routing) + Pydantic (validation) + OpenAPI; it reads your signatures | Fastify + JSON Schema, NestJS |
            | Path operations | one decorator per method; typed path params; `StrEnum`; `{x:path}`; first declared route wins | `app.get("/x/:id")` |
            | Query parameters | non-path simple params; `Annotated[int, Query(ge=1, le=100)]`; lists need `Query()`; query models with `extra="forbid"` | `req.query` + zod |
            | Request bodies | a model parameter is the body; several bodies are keyed by name; `Body(embed=True)` | `express.json()` + DTO |
            | Pydantic v2 | types + `Field` constraints; `field_validator` / `model_validator` / `computed_field`; `model_dump` options; `ConfigDict`; lax vs strict; `TypeAdapter`; `errors()`; `Annotated` types | zod (`z.object`, `.refine`, `.transform`, `safeParse`) |
            | Schema design | Create / Update / Read schemas; PATCH = `exclude_unset`; reject explicit `null` | separate DTOs |
            | Responses | `response_model` filters output; `status_code`; `JSONResponse`, `StreamingResponse`, `FileResponse`, `RedirectResponse`; `response: Response` for headers/cookies; `HTTPException` | `res.status().json()`, `res.cookie()` |
            | `async def` vs `def` | blocking code in `async def` freezes the worker; `def` runs in a 40-thread pool; offload with `run_in_threadpool` | (Node has no sync handlers) |
            | OpenAPI | `/docs`, `/redoc`, `/openapi.json`; metadata, tags, examples, operation ids; generate typed clients | `@nestjs/swagger`, `openapi-typescript` |
            | How it works | decorators register routes; `inspect.signature` + `Annotated` metadata classify parameters; validators compiled once | reflect-metadata in NestJS |

            **Further reading**

            - [FastAPI tutorial](https://fastapi.tiangolo.com/tutorial/) (path, query and body
              parameters, response models, status codes, `async`),
              [Starlette responses](https://www.starlette.io/responses/)
            - [Pydantic: models](https://docs.pydantic.dev/latest/concepts/models/),
              [fields](https://docs.pydantic.dev/latest/concepts/fields/),
              [validators](https://docs.pydantic.dev/latest/concepts/validators/),
              [serialization](https://docs.pydantic.dev/latest/concepts/serialization/),
              [strict mode](https://docs.pydantic.dev/latest/concepts/strict_mode/),
              [type adapter](https://docs.pydantic.dev/latest/concepts/type_adapter/)
            - [`inspect`](https://docs.python.org/3/library/inspect.html),
              [`typing.Annotated`](https://docs.python.org/3/library/typing.html#typing.Annotated),
              [`annotationlib`](https://docs.python.org/3/library/annotationlib.html),
              [`enum.StrEnum`](https://docs.python.org/3/library/enum.html#enum.StrEnum)
            - [PEP 593](https://peps.python.org/pep-0593/) (`Annotated`),
              [PEP 649](https://peps.python.org/pep-0649/) / [PEP 749](https://peps.python.org/pep-0749/) (lazy annotations),
              [PEP 695](https://peps.python.org/pep-0695/) (`type` aliases)
            - [OpenAPI 3.1 specification](https://spec.openapis.org/oas/v3.1.0),
              [openapi-typescript](https://openapi-ts.dev/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 6.2, Lab 6.2 and Notes API v1."""
    return [
        *_overview_cells(),
        *_architecture_cells(),
        *_path_operation_cells(),
        *_query_cells(),
        *_body_cells(),
        *_pydantic_field_cells(),
        *_pydantic_serialization_cells(),
        *_schema_design_cells(),
        *_response_cells(),
        *_async_vs_sync_cells(),
        *_openapi_cells(),
        *_internals_cells(),
        *_predict_cells(),
        *_lab_cells_part_1(),
        *_lab_cells_part_2(),
        *_notes_project_cells(),
        *_recap_cells(),
    ]
