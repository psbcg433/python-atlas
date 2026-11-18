"""Domain errors and RFC 9457 Problem Details responses for every error the API returns."""

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
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
        headers=error.headers or None,
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


async def integrity_error_handler(request: Request, error: IntegrityError) -> JSONResponse:
    """A constraint the database enforced (unique, foreign key) → 409, without SQL details."""
    return problem_response(
        request,
        HTTPStatus.CONFLICT,
        "the change conflicts with existing data",
        problem_type="conflict",
        title="Conflict",
    )


async def unhandled_error_handler(request: Request, error: Exception) -> JSONResponse:
    """Any other exception → a generic 500; details stay in the server log."""
    return problem_response(request, HTTPStatus.INTERNAL_SERVER_ERROR, "unexpected error")


def install_error_handlers(app: FastAPI) -> None:
    """Register every handler on the app."""
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
