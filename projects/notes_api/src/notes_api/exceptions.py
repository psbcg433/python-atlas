"""Domain exceptions: plain Python, no FastAPI (core/errors.py maps them to HTTP)."""

from http import HTTPStatus


class DomainError(Exception):
    """A business rule failed. Subclasses choose the status, a problem type and a title."""

    status_code: int = HTTPStatus.BAD_REQUEST
    problem_type: str = "domain-error"
    title: str = "Request breaks a business rule"
    headers: dict[str, str] = {}


class NoteNotFoundError(DomainError, LookupError):
    """No note has the requested id."""

    status_code = HTTPStatus.NOT_FOUND
    problem_type = "note-not-found"
    title = "Note not found"

    def __init__(self, note_id: int) -> None:
        """Remember the id; the message becomes the problem's detail."""
        super().__init__(f"note {note_id} not found")
        self.note_id = note_id


class VersionConflictError(DomainError):
    """Optimistic locking: the note changed since the client (or this request) read it."""

    status_code = HTTPStatus.CONFLICT
    problem_type = "version-conflict"
    title = "Version conflict"

    def __init__(
        self, note_id: int, expected: int | None = None, actual: int | None = None
    ) -> None:
        """Explain which versions clashed when they are known."""
        if expected is None or actual is None:
            message = f"note {note_id} was changed by another request; read it again"
        else:
            message = f"note {note_id} is at version {actual}, not {expected}; read it again"
        super().__init__(message)
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


class AuthenticationError(DomainError):
    """Missing, invalid, expired or revoked credentials (401)."""

    status_code = HTTPStatus.UNAUTHORIZED
    problem_type = "not-authenticated"
    title = "Authentication required"

    def __init__(self, detail: str, scopes: list[str] | None = None) -> None:
        """Keep the reason; the WWW-Authenticate header tells clients how to authenticate."""
        super().__init__(detail)
        challenge = "Bearer"
        if scopes:
            challenge += f' scope="{" ".join(scopes)}"'
        self.headers = {"WWW-Authenticate": challenge}


class PermissionDeniedError(DomainError):
    """Authenticated, but not allowed to do this (403)."""

    status_code = HTTPStatus.FORBIDDEN
    problem_type = "forbidden"
    title = "Not allowed"


class EmailTakenError(DomainError):
    """Registration with an email that already has an account (409)."""

    status_code = HTTPStatus.CONFLICT
    problem_type = "email-taken"
    title = "Email already registered"


class RateLimitedError(DomainError):
    """Too many attempts; Retry-After says when to try again (429)."""

    status_code = HTTPStatus.TOO_MANY_REQUESTS
    problem_type = "rate-limited"
    title = "Too many requests"

    def __init__(self, retry_after: int) -> None:
        """Remember how many seconds the client must wait."""
        super().__init__(f"too many attempts; retry in {retry_after} s")
        self.retry_after = retry_after
        self.headers = {"Retry-After": str(retry_after)}


class ApiKeyNotFoundError(DomainError, LookupError):
    """The caller has no API key with this id (someone else's key is 'not found' too)."""

    status_code = HTTPStatus.NOT_FOUND
    problem_type = "api-key-not-found"
    title = "API key not found"

    def __init__(self, key_id: int) -> None:
        """Remember the id."""
        super().__init__(f"API key {key_id} not found")
        self.key_id = key_id


class ExportNotFoundError(DomainError, LookupError):
    """No export with this id for the caller (or it expired)."""

    status_code = HTTPStatus.NOT_FOUND
    problem_type = "export-not-found"
    title = "Export not found"

    def __init__(self, export_id: str) -> None:
        """Remember the id."""
        super().__init__(f"export {export_id} not found")
        self.export_id = export_id


class InvalidWebhookError(DomainError, ValueError):
    """A webhook URL the server will not call (not public http(s))."""

    status_code = HTTPStatus.UNPROCESSABLE_CONTENT
    problem_type = "invalid-webhook"
    title = "Webhook URL refused"
