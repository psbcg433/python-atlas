"""/health (liveness) and /health/ready (readiness: can we reach the database?)."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from notes_api.dependencies import SessionDep

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe: the process answers (no database call)."""
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(session: SessionDep) -> dict[str, str]:
    """Readiness probe: 503 until the database answers SELECT 1."""
    try:
        await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as error:
        detail = f"database unavailable: {type(error).__name__}"
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail) from error
    return {"status": "ok", "database": "ok"}
