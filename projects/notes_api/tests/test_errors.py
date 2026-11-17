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
