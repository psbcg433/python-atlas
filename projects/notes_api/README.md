# Notes API

A FastAPI service for creating, searching and organizing notes. It is built step by step in
Phase 6 of the course (`notebooks/phase6_web_fastapi.ipynb`); the notebook writes these files.

| Version | Unit | Adds |
| --- | --- | --- |
| v1 | 6.2 | CRUD path operations, Pydantic v2 schemas, filtering and pagination, OpenAPI |
| v2 | 6.3 | `create_app()` factory, routers under `/api/v1`, settings, dependency injection, middleware, CORS, Problem Details errors, lifespan HTTP client, uploads, cursor pagination, HTML pages |
| v3 | 6.4 | PostgreSQL with async SQLAlchemy 2.0 (typed models, many-to-many tags), a session per request, Alembic migrations, optimistic locking (409), trigram search, keyset pagination on an index |

## Run

```bash
cd projects/notes_api
cp .env.example .env                          # then put a real NOTES_API_KEY in .env
docker compose up -d --wait                   # PostgreSQL 18 on 127.0.0.1:5432
uv run alembic upgrade head                   # create the tables
uv run uvicorn notes_api.main:app --reload    # http://127.0.0.1:8000/ and /docs
uv run pytest                                 # SQLite tests + PostgreSQL tests (needs Docker)
uv run pytest -m "not postgres"               # only the fast SQLite tests
docker compose down                           # add -v to delete the data volume
```

New migration after changing `models.py`: `uv run alembic revision --autogenerate -m "..."`,
review the file in `alembic/versions/`, then `uv run alembic upgrade head`.


## Endpoints

| Method | Path | Success | Notes |
| --- | --- | --- | --- |
| `GET` | `/health` | 200 | liveness probe |
| `GET` | `/health/ready` | 200 | readiness: runs `SELECT 1` (503 without a database) |
| `POST` | `/api/v1/notes` | 201 | `Location` header; body `NoteCreate` |
| `GET` | `/api/v1/notes` | 200 | `q`, `tag` (repeatable), `pinned`, `sort`, `limit` (1-100), `offset` → `Page[NoteRead]` |
| `GET` | `/api/v1/notes/feed` | 200 | newest first; `limit`, `cursor` → `CursorPage[NoteRead]` |
| `GET` | `/api/v1/notes/{note_id}` | 200 | 404 problem if unknown |
| `PUT` | `/api/v1/notes/{note_id}` | 200 | replaces every field |
| `PATCH` | `/api/v1/notes/{note_id}` | 200 | only the fields sent; explicit `null` is rejected; optional `version` → 409 if stale |
| `DELETE` | `/api/v1/notes/{note_id}` | 204 | |
| `GET` | `/api/v1/notes/{note_id}/links` | 200 | titles of the links in the body |
| `POST` | `/api/v1/admin/import` | 201 | `X-API-Key`; multipart `.json` / `.csv` file |
| `GET` | `/api/v1/admin/export` | 200 | `X-API-Key`; JSON download |
| `DELETE` | `/api/v1/admin/notes` | 200 | `X-API-Key`; removes every note |
| `GET` | `/` | 200 | HTML page (Jinja2 + HTMX); `POST /notes` form, `POST /notes/{id}/pin` |

Errors are `application/problem+json` (RFC 9457) with `type`, `title`, `status`, `detail`,
`instance` and `request_id`. Every response carries `X-Request-ID` and `Server-Timing`.


## Layout

```text
src/notes_api/
├── main.py           # create_app(): settings, handlers, middleware, lifespan, routers
├── core/             # config.py, errors.py, middleware.py, lifespan.py
├── routers/          # health.py, notes.py, admin.py, pages.py  (HTTP only)
├── dependencies.py   # Annotated aliases: NoteServiceDep, SettingsDep, ApiKeyDep, ...
├── services.py       # NoteService, parse_import, LinkPreviewer  (business logic)
├── repositories.py   # NoteRepository Protocol + SqlNoteRepository (storage)
├── models.py         # SQLAlchemy models: Note, Tag, note_tags
├── db.py             # Base (naming convention), UTCDateTime, engine, session factory
├── exceptions.py     # DomainError and subclasses (no FastAPI)
├── schemas.py        # Pydantic request/response models
├── pagination.py     # Page[T], CursorPage[T], cursors
├── templates/        # Jinja2 templates
└── static/           # CSS
alembic/              # env.py (async) + versions/0001-0003
alembic.ini
compose.yaml          # local PostgreSQL
tests/                # pytest + TestClient, one app and one SQLite file per test;
                      # test_postgres.py runs on PostgreSQL in a testcontainer
```

Dependencies point inwards: routers → services → repositories → models. Nothing in
`services.py`, `repositories.py`, `models.py`, `db.py` or `exceptions.py` imports FastAPI;
`core/errors.py` maps domain exceptions to HTTP responses.
