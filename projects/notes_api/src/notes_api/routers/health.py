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
