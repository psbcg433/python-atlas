"""The admin router: a router-level API key, uploads with validation, export and wipe."""

import json

import pytest
from fastapi.testclient import TestClient

from helpers import ANONYMOUS, auth_headers, create

IMPORT = "/api/v1/admin/import"
NOTES_JSON = json.dumps([{"title": "Tea", "tags": ["shop"]}, {"title": "Rice", "pinned": True}])
NOTES_CSV = "title,body,tags,pinned\nTea,Assam,shop;food,false\nRice,,shop,true\n"


def test_admin_routes_need_an_admin(client: TestClient, admin_headers: dict[str, str]) -> None:
    """Anonymous → 401, ordinary user → 403, admin → 200 on every admin route."""
    for method, path in [("GET", "/api/v1/admin/export"), ("DELETE", "/api/v1/admin/notes")]:
        assert client.request(method, path, headers=ANONYMOUS).status_code == 401
        forbidden = client.request(method, path)
        assert (forbidden.status_code, forbidden.json()["type"]) == (403, "/problems/forbidden")
        assert client.request(method, path, headers=admin_headers).status_code == 200


def test_admin_token_without_the_admin_scope_is_refused(anonymous: TestClient) -> None:
    """The role is not enough: a token issued without the admin scope cannot use admin routes."""
    narrow = auth_headers(anonymous, "admin@example.com", scope="notes:read notes:write")
    response = anonymous.get("/api/v1/admin/export", headers=narrow)
    assert (response.status_code, response.json()["detail"]) == (403, "missing scope(s): admin")


@pytest.mark.parametrize(
    ("filename", "content", "content_type"),
    [("notes.json", NOTES_JSON, "application/json"), ("notes.csv", NOTES_CSV, "text/csv")],
)
def test_import_json_and_csv(
    client: TestClient,
    admin_headers: dict[str, str],
    filename: str,
    content: str,
    content_type: str,
) -> None:
    """Both formats create the same notes."""
    files = {"file": (filename, content.encode(), content_type)}
    report = client.post(IMPORT, files=files, headers=admin_headers)
    assert report.status_code == 201, report.text
    assert report.json() == {"filename": filename, "imported": 2, "ids": [1, 2]}
    params = {"sort": "created_at"}
    notes = client.get("/api/v1/notes", params=params, headers=admin_headers).json()["items"]
    assert [(note["title"], note["pinned"]) for note in notes] == [("Tea", False), ("Rice", True)]


@pytest.mark.parametrize(
    ("filename", "content", "content_type", "status"),
    [
        ("notes.txt", b"hello", "text/plain", 415),
        ("notes.json", b"[]", "text/csv", 415),
        ("notes.json", b"[" + b" " * 4096 + b"]", "application/json", 413),
        ("notes.json", b'[{"title": ""}]', "application/json", 422),
        ("notes.json", b"not json", "application/json", 422),
    ],
)
def test_import_rejects_bad_files(
    client: TestClient,
    admin_headers: dict[str, str],
    filename: str,
    content: bytes,
    content_type: str,
    status: int,
) -> None:
    """Wrong type → 415, too large → 413, invalid content → 422; nothing is imported."""
    files = {"file": (filename, content, content_type)}
    response = client.post(IMPORT, files=files, headers=admin_headers)
    assert response.status_code == status, response.text
    assert response.json()["type"] == "/problems/upload-rejected"
    assert client.get("/api/v1/notes").json()["total"] == 0


def test_export_and_delete_all(client: TestClient, admin_headers: dict[str, str]) -> None:
    """Export downloads every note; delete removes them all."""
    create(client, title="Tea")
    create(client, title="Rice")
    export = client.get("/api/v1/admin/export", headers=admin_headers)
    assert export.headers["content-disposition"] == 'attachment; filename="notes.json"'
    assert [note["title"] for note in export.json()] == ["Tea", "Rice"]
    assert client.delete("/api/v1/admin/notes", headers=admin_headers).json() == {"deleted": 2}
    assert client.get("/api/v1/notes").json()["total"] == 0
