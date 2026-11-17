"""The Notes API application factory.

Unit 6.4 version: create_app() wires settings, error handlers, middleware, the lifespan (now
with a database engine) and the routers. Later units add authentication (6.5), background
jobs and caching (6.6), observability (6.7) and deployment (6.8).

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
