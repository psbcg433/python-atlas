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
