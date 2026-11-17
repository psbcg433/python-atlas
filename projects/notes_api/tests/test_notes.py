"""Behaviour of the Notes API v1 endpoints."""

from typing import Any

import pytest
from fastapi.testclient import TestClient


def create(client: TestClient, **fields: Any) -> dict[str, Any]:
    """POST a note (title defaults to "Buy tea") and return the created note."""
    response = client.post("/notes", json={"title": "Buy tea", **fields})
    assert response.status_code == 201, response.text
    return response.json()


def ids(response: Any) -> list[int]:
    """Ids of the notes on a page."""
    assert response.status_code == 200, response.text
    return [note["id"] for note in response.json()["items"]]


def test_health(client: TestClient) -> None:
    """GET /health answers ok."""
    assert client.get("/health").json() == {"status": "ok"}


def test_create_returns_201_location_and_normalized_fields(client: TestClient) -> None:
    """POST returns 201, a Location header and cleaned-up fields."""
    response = client.post(
        "/notes", json={"title": "  Buy tea  ", "body": "Assam, 500 g", "tags": ["Shop", "shop"]}
    )
    assert response.status_code == 201
    assert response.headers["location"] == "/notes/1"
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
    """Invalid bodies are 422 errors pointing at the bad field."""
    response = client.post("/notes", json=body)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == location


def test_get_one_and_unknown_id(client: TestClient) -> None:
    """GET one note; unknown ids are 404, non-positive ids 422."""
    created = create(client)
    assert client.get("/notes/1").json() == created
    missing = client.get("/notes/99")
    assert (missing.status_code, missing.json()) == (404, {"detail": "note 99 not found"})
    assert client.get("/notes/0").status_code == 422


def test_list_paginates_and_counts_all_matches(client: TestClient) -> None:
    """limit/offset select a page; total counts every match."""
    for number in range(5):
        create(client, title=f"Note {number}")
    response = client.get("/notes", params={"limit": 2, "offset": 2, "sort": "created_at"})
    assert ids(response) == [3, 4]
    assert {key: response.json()[key] for key in ("total", "limit", "offset")} == {
        "total": 5,
        "limit": 2,
        "offset": 2,
    }


def test_list_default_order_is_newest_first(client: TestClient) -> None:
    """Without sort, the newest note comes first."""
    for title in ("first", "second", "third"):
        create(client, title=title)
    assert ids(client.get("/notes")) == [3, 2, 1]


def test_list_filters_by_tag_pinned_and_text(client: TestClient) -> None:
    """tag (all of them), pinned and q filter the list."""
    create(client, title="Buy tea", tags=["shopping", "home"], pinned=True)
    create(client, title="Call Ravi", body="about the TEA estate trip", tags=["home"])
    create(client, title="Pay bill", tags=["shopping"])
    assert ids(client.get("/notes?tag=home&sort=created_at")) == [1, 2]
    assert ids(client.get("/notes?tag=home&tag=shopping")) == [1]
    assert ids(client.get("/notes?pinned=false&sort=created_at")) == [2, 3]
    assert ids(client.get("/notes?q=tea&sort=created_at")) == [1, 2]


def test_list_sorts_titles_ignoring_case(client: TestClient) -> None:
    """sort=title ignores case."""
    for title in ("banana", "Apple", "cherry"):
        create(client, title=title)
    titles = [note["title"] for note in client.get("/notes?sort=title").json()["items"]]
    assert titles == ["Apple", "banana", "cherry"]


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "sort=newest", "x=1"])
def test_list_rejects_bad_parameters(client: TestClient, query: str) -> None:
    """Out-of-range or unknown query parameters are 422 errors."""
    assert client.get(f"/notes?{query}").status_code == 422


def test_put_replaces_every_field(client: TestClient) -> None:
    """PUT resets every field the body leaves out."""
    create(client, tags=["home"], pinned=True, body="old body")
    replaced = client.put("/notes/1", json={"title": "Buy green tea"})
    assert replaced.status_code == 200
    assert {key: replaced.json()[key] for key in ("title", "body", "tags", "pinned")} == {
        "title": "Buy green tea",
        "body": "",
        "tags": [],
        "pinned": False,
    }


def test_patch_changes_only_the_fields_sent(client: TestClient) -> None:
    """PATCH changes only the fields in the body."""
    created = create(client, body="Assam", tags=["home"])
    patched = client.patch("/notes/1", json={"pinned": True}).json()
    assert patched["pinned"] is True
    assert {key: patched[key] for key in ("title", "body", "tags")} == {
        key: created[key] for key in ("title", "body", "tags")
    }
    assert patched["updated_at"] >= created["updated_at"]


def test_patch_without_a_change_keeps_updated_at(client: TestClient) -> None:
    """A PATCH that changes nothing keeps updated_at."""
    created = create(client, pinned=True)
    for body in ({}, {"pinned": True}):
        assert client.patch("/notes/1", json=body).json()["updated_at"] == created["updated_at"]


@pytest.mark.parametrize("body", [{"title": None}, {"pinned": None}, {"colour": "red"}])
def test_patch_rejects_null_and_unknown_fields(client: TestClient, body: dict[str, Any]) -> None:
    """PATCH refuses explicit nulls and unknown fields."""
    create(client)
    assert client.patch("/notes/1", json=body).status_code == 422


def test_delete_then_gone(client: TestClient) -> None:
    """DELETE answers 204 and the note is gone."""
    create(client)
    deleted = client.delete("/notes/1")
    assert (deleted.status_code, deleted.content) == (204, b"")
    assert client.get("/notes/1").status_code == 404


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_unknown_note_is_404_for_every_method(client: TestClient, method: str) -> None:
    """PUT, PATCH and DELETE on an unknown id are 404 errors."""
    kwargs = {} if method == "delete" else {"json": {"title": "x"}}
    response = client.request(method.upper(), "/notes/99", **kwargs)
    assert (response.status_code, response.json()) == (404, {"detail": "note 99 not found"})


def test_openapi_uses_function_names_as_operation_ids(client: TestClient) -> None:
    """operationIds are the handler function names."""
    paths = client.get("/openapi.json").json()["paths"]
    operation_ids = {op["operationId"] for ops in paths.values() for op in ops.values()}
    assert operation_ids == {
        "health",
        "create_note",
        "list_notes",
        "get_note",
        "replace_note",
        "update_note",
        "delete_note",
    }
