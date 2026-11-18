"""Broken Object Level Authorization (OWASP API1): users see and change only their own notes."""

import pytest
from fastapi.testclient import TestClient

from helpers import auth_headers, create

NOTES = "/api/v1/notes"


@pytest.fixture
def intruder(client: TestClient) -> dict[str, str]:
    """Bearer headers of a second, unrelated user."""
    return auth_headers(client, "intruder@example.com")


@pytest.mark.parametrize("method", ["GET", "PUT", "PATCH", "DELETE"])
def test_someone_elses_note_is_not_found(
    client: TestClient, intruder: dict[str, str], method: str
) -> None:
    """Every operation on another user's note is a 404, exactly like a missing note (no 403
    that would confirm the id exists)."""
    note = create(client, title="Mine")
    response = client.request(
        method, f"{NOTES}/{note['id']}", json={"title": "pwned"}, headers=intruder
    )
    missing = client.request(method, f"{NOTES}/9999", json={"title": "x"}, headers=intruder)
    assert response.status_code == missing.status_code == 404
    assert client.get(f"{NOTES}/{note['id']}").json()["title"] == "Mine"


def test_lists_feeds_and_links_are_per_user(client: TestClient, intruder: dict[str, str]) -> None:
    """Search, the feed and link previews only ever touch the caller's notes."""
    note = create(client, title="Mine")
    client.post(NOTES, json={"title": "Theirs"}, headers=intruder)
    assert [item["title"] for item in client.get(NOTES).json()["items"]] == ["Mine"]
    assert [
        item["title"] for item in client.get(f"{NOTES}/feed", headers=intruder).json()["items"]
    ] == ["Theirs"]
    assert client.get(f"{NOTES}/{note['id']}/links", headers=intruder).status_code == 404
