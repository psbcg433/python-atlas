"""Behaviour of the /api/v1/notes endpoints."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from helpers import create, ids

NOTES = "/api/v1/notes"


def test_health(client: TestClient) -> None:
    """GET /health answers ok."""
    assert client.get("/health").json() == {"status": "ok"}


def test_create_returns_201_location_and_normalized_fields(client: TestClient) -> None:
    """POST returns 201, a Location header and cleaned-up fields."""
    response = client.post(
        NOTES, json={"title": "  Buy tea  ", "body": "Assam, 500 g", "tags": ["Shop", "shop"]}
    )
    assert response.status_code == 201
    assert response.headers["location"] == "/api/v1/notes/1"
    note = response.json()
    assert {key: note[key] for key in ("id", "title", "tags", "pinned", "word_count")} == {
        "id": 1,
        "title": "Buy tea",
        "tags": ["shop"],
        "pinned": False,
        "word_count": 3,
    }
    assert note["created_at"] == note["updated_at"]


@pytest.mark.parametrize(
    ("body", "location"),
    [
        ({}, ["body", "title"]),
        ({"title": "   "}, ["body", "title"]),
        ({"title": "x", "color": "red"}, ["body", "color"]),
        ({"title": "x", "tags": ["two words"]}, ["body", "tags", 0]),
        ({"title": "x", "tags": [f"tag-{number}" for number in range(11)]}, ["body", "tags"]),
    ],
)
def test_create_rejects_invalid_input(
    client: TestClient, body: dict[str, Any], location: list[Any]
) -> None:
    """Invalid bodies are 422 problems pointing at the bad field."""
    response = client.post(NOTES, json=body)
    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"] == location


def test_get_one_and_unknown_id(client: TestClient) -> None:
    """GET returns the note; an unknown id is a 404 problem."""
    create(client)
    assert client.get(f"{NOTES}/1").json()["title"] == "Buy tea"
    missing = client.get(f"{NOTES}/99")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "note 99 not found"


def test_list_paginates_and_counts_all_matches(client: TestClient) -> None:
    """limit/offset select a page; total counts every match."""
    for number in range(5):
        create(client, title=f"Note {number}")
    page = client.get(NOTES, params={"limit": 2, "offset": 2, "sort": "created_at"}).json()
    assert [note["title"] for note in page["items"]] == ["Note 2", "Note 3"]
    assert (page["total"], page["limit"], page["offset"]) == (5, 2, 2)


def test_list_filters_by_tag_pinned_and_text(client: TestClient) -> None:
    """tag (all of them), pinned and q filters combine."""
    create(client, title="Tea", tags=["shop", "food"], pinned=True)
    create(client, title="Rice", tags=["shop"], body="basmati")
    create(client, title="Call Ravi", tags=["home"])
    assert ids(client.get(NOTES, params={"tag": ["shop", "food"]})) == [1]
    assert ids(client.get(NOTES, params={"pinned": False, "sort": "title"})) == [3, 2]
    assert ids(client.get(NOTES, params={"q": "BASMATI"})) == [2]


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "sort=size", "color=red"])
def test_list_rejects_bad_parameters(client: TestClient, query: str) -> None:
    """Out-of-range, unknown or extra query parameters are 422 problems."""
    assert client.get(f"{NOTES}?{query}").status_code == 422


def test_put_replaces_every_field(client: TestClient) -> None:
    """PUT resets omitted fields to their defaults."""
    create(client, body="old body", tags=["shop"], pinned=True)
    replaced = client.put(f"{NOTES}/1", json={"title": "New title"}).json()
    assert (replaced["title"], replaced["body"], replaced["tags"], replaced["pinned"]) == (
        "New title",
        "",
        [],
        False,
    )


def test_patch_changes_only_the_fields_sent(client: TestClient) -> None:
    """PATCH keeps the other fields and moves updated_at."""
    created = create(client, body="Assam", tags=["shop"])
    patched = client.patch(f"{NOTES}/1", json={"pinned": True}).json()
    assert (patched["pinned"], patched["body"], patched["tags"]) == (True, "Assam", ["shop"])
    assert patched["updated_at"] > created["updated_at"]


def test_patch_without_a_change_keeps_updated_at(client: TestClient) -> None:
    """Sending the current values is not a change."""
    created = create(client, pinned=True)
    patched = client.patch(f"{NOTES}/1", json={"pinned": True}).json()
    assert patched["updated_at"] == created["updated_at"]


@pytest.mark.parametrize("body", [{"title": None}, {"pinned": None}, {"color": "red"}])
def test_patch_rejects_null_and_unknown_fields(client: TestClient, body: dict[str, Any]) -> None:
    """Explicit null and unknown fields are 422 problems."""
    create(client)
    assert client.patch(f"{NOTES}/1", json=body).status_code == 422


def test_delete_then_gone(client: TestClient) -> None:
    """DELETE returns 204 with no body; the note is gone afterwards."""
    create(client)
    response = client.delete(f"{NOTES}/1")
    assert (response.status_code, response.content) == (204, b"")
    assert client.get(f"{NOTES}/1").status_code == 404


@pytest.mark.parametrize("method", ["GET", "PUT", "PATCH", "DELETE"])
def test_unknown_note_is_404_for_every_method(client: TestClient, method: str) -> None:
    """Every operation on a missing note is a 404 problem."""
    response = client.request(method, f"{NOTES}/7", json={"title": "x"})
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"


def test_openapi_uses_function_names_and_versioned_paths(client: TestClient) -> None:
    """Operation ids are function names; JSON routes live under /api/v1; pages are hidden."""
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    assert paths[NOTES]["post"]["operationId"] == "create_note"
    assert paths[f"{NOTES}/feed"]["get"]["operationId"] == "notes_feed"
    assert "/" not in paths
    assert "Page_NoteRead_" in schema["components"]["schemas"]


def test_patch_with_the_current_version_bumps_it(client: TestClient) -> None:
    """Sending the version you read succeeds and increments it."""
    assert create(client)["version"] == 1
    patched = client.patch(f"{NOTES}/1", json={"pinned": True, "version": 1}).json()
    assert patched["version"] == 2


def test_patch_with_a_stale_version_is_a_409_problem(client: TestClient) -> None:
    """Optimistic locking: an old version means someone else changed the note first."""
    create(client)
    client.patch(f"{NOTES}/1", json={"title": "Changed elsewhere"})
    stale = client.patch(f"{NOTES}/1", json={"pinned": True, "version": 1})
    assert stale.status_code == 409
    assert stale.json()["type"] == "/problems/version-conflict"
    assert stale.json()["detail"] == "note 1 is at version 2, not 1; read it again"
    assert client.get(f"{NOTES}/1").json()["pinned"] is False


def test_tags_are_returned_sorted_and_shared(client: TestClient) -> None:
    """Tags come back in name order; the same name is one row shared by many notes."""
    assert create(client, tags=["work", "Home"])["tags"] == ["home", "work"]
    create(client, title="Second", tags=["home"])
    assert ids(client.get(NOTES, params={"tag": "home", "sort": "created_at"})) == [1, 2]


def test_search_treats_percent_and_underscore_literally(client: TestClient) -> None:
    """q is escaped for LIKE: '%' only matches a real percent sign."""
    create(client, title="100% done")
    create(client, title="Plain")
    assert ids(client.get(NOTES, params={"q": "%"})) == [1]
    assert ids(client.get(NOTES, params={"q": "_"})) == []


def test_readiness_checks_the_database(client: TestClient) -> None:
    """/health/ready runs SELECT 1 through the session dependency."""
    assert client.get("/health/ready").json() == {"status": "ok", "database": "ok"}
