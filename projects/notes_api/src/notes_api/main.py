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
