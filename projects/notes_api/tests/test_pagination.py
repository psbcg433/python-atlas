"""Keyset (cursor) pagination on /api/v1/notes/feed."""

from fastapi.testclient import TestClient

from helpers import create

FEED = "/api/v1/notes/feed"


def test_feed_walks_every_note_newest_first(client: TestClient) -> None:
    """Following next_cursor visits each note once, newest first, then stops."""
    for number in range(7):
        create(client, title=f"Note {number}")
    seen: list[int] = []
    params: dict[str, object] = {"limit": 3}
    while True:
        page = client.get(FEED, params=params).json()
        seen += [note["id"] for note in page["items"]]
        if page["next_cursor"] is None:
            break
        params = {"limit": 3, "cursor": page["next_cursor"]}
    assert seen == [7, 6, 5, 4, 3, 2, 1]


def test_feed_is_stable_when_notes_are_added(client: TestClient) -> None:
    """A note created between two pages does not shift the next page (unlike offsets)."""
    for number in range(4):
        create(client, title=f"Note {number}")
    first = client.get(FEED, params={"limit": 2}).json()
    create(client, title="Brand new")
    second = client.get(FEED, params={"limit": 2, "cursor": first["next_cursor"]}).json()
    assert [note["id"] for note in second["items"]] == [2, 1]


def test_bad_cursor_is_a_400_problem(client: TestClient) -> None:
    """A cursor the API did not issue is rejected with a clear problem type."""
    response = client.get(FEED, params={"cursor": "not-a-cursor"})
    assert response.status_code == 400
    assert response.json()["type"] == "/problems/invalid-cursor"
