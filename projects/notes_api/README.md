# Notes API

A FastAPI service for creating, searching and organizing notes. It is built step by step in
Phase 6 of the course (`notebooks/phase6_web_fastapi.ipynb`); the notebook writes these files.

| Version | Unit | Adds |
| --- | --- | --- |
| v1 | 6.2 | CRUD path operations, Pydantic v2 schemas, filtering and pagination, OpenAPI |

## Run

```bash
cd projects/notes_api
uv run uvicorn notes_api.main:app --reload   # creates .venv; http://127.0.0.1:8000/docs
uv run pytest
```

## Endpoints

| Method | Path | Success | Notes |
| --- | --- | --- | --- |
| `GET` | `/health` | 200 | liveness probe |
| `POST` | `/notes` | 201 | `Location` header; body `NoteCreate` |
| `GET` | `/notes` | 200 | `q`, `tag` (repeatable), `pinned`, `sort`, `limit` (1-100), `offset` |
| `GET` | `/notes/{note_id}` | 200 | 404 if unknown |
| `PUT` | `/notes/{note_id}` | 200 | replaces every field |
| `PATCH` | `/notes/{note_id}` | 200 | only the fields sent; explicit `null` is rejected |
| `DELETE` | `/notes/{note_id}` | 204 | |

## Layout

```text
src/notes_api/
├── __init__.py   # version
├── main.py       # the FastAPI app and its path operations
├── schemas.py    # Pydantic models: NoteCreate, NoteUpdate, NoteRead, NoteFilters, NotePage
└── store.py      # in-memory storage (replaced by a database in Unit 6.4)
tests/            # pytest + TestClient
```
