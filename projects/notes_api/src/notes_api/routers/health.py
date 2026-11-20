"""Probes for orchestrators (Kubernetes, Compose, load balancers).

- /health and /health/live: liveness. The process answers; no dependency is touched, so a
  database outage never makes the orchestrator restart every API process.
- /health/ready: readiness. The database and Redis answer; until then, send no traffic here.
- /health/startup: startup. The database schema is at the revision this code needs.
"""

import asyncio

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from notes_api.db import SCHEMA_REVISION
from notes_api.dependencies import RedisDep, SettingsDep

router = APIRouter(tags=["health"])
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
    except Exception as error:
        checks["database"] = f"unavailable: {type(error).__name__}"
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
            await redis.ping()
        checks["redis"] = "ok"
    except Exception as error:
        checks["redis"] = f"unavailable: {type(error).__name__}"
    return report(checks)


@router.get("/health/startup")
async def startup(request: Request, settings: SettingsDep) -> JSONResponse:
    """Startup probe: the schema is migrated to SCHEMA_REVISION (when the check is enabled)."""
    try:
        revision = await database_revision(request)
    except Exception as error:
        return report({"database": f"unavailable: {type(error).__name__}"})
    if not settings.check_migrations:
        return report({"database": "ok", "migrations": "ok"})
    migrations = "ok" if revision == SCHEMA_REVISION else f"at {revision}, need {SCHEMA_REVISION}"
    return report({"database": "ok", "migrations": migrations})
