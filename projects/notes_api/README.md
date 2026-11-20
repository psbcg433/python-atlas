# Notes API

A FastAPI service for creating, searching and organizing notes. It is built step by step in
Phase 6 of the course (`notebooks/phase6_web_fastapi.ipynb`); the notebook writes these files.


| Version | Unit | Adds |
| --- | --- | --- |
| v1 | 6.2 | CRUD path operations, Pydantic v2 schemas, filtering and pagination, OpenAPI |
| v2 | 6.3 | `create_app()` factory, routers under `/api/v1`, settings, dependency injection, middleware, CORS, Problem Details errors, lifespan HTTP client, uploads, cursor pagination, HTML pages |
| v3 | 6.4 | PostgreSQL with async SQLAlchemy 2.0 (typed models, many-to-many tags), a session per request, Alembic migrations, optimistic locking (409), trigram search, keyset pagination on an index |
| v4 | 6.5 | users (Argon2id), JWT access tokens with scopes and roles, rotating refresh tokens with reuse detection, logout and revocation, owner-only notes, hashed API keys, Redis login rate limiting, cookie login with CSRF for the pages, OpenID Connect login, SSRF-safe link previews, security headers, log redaction |
| v5 | 6.6 | an ARQ worker: transactional outbox relay, signed webhooks with retries and a dead-letter list, exports with SSE progress, scheduled clean-up with locks; a WebSocket feed fanned out through Redis pub/sub; ETags, 304 and Cache-Control; Redis cache-aside with stampede protection and hit-rate stats; a welcome email from BackgroundTasks |
| v6 | 6.7 | the test suite reorganised (async client tests, PostgreSQL rollback-per-test with factories, Schemathesis contract tests, an OpenAPI snapshot) and run in CI against service containers; JSON logs with request and trace ids (structlog), Prometheus metrics on `/metrics`, OpenTelemetry tracing, optional Sentry, liveness / readiness / startup probes |
| v7 | 6.8 | a multi-stage uv Dockerfile (non-root, read-only), a Compose stack (db, redis, migrate job, api, worker, Caddy with TLS), an Nginx alternative, Kubernetes / systemd / Procfile / Cloud Run targets, Docker secrets, PgBouncer mode, a worker health check, a CI/CD pipeline (lint, types, test, build, scan, push, deploy), a graceful-shutdown test and a Locust load test with a p95 gate |


## Run

```bash
cd projects/notes_api
cp .env.example .env                          # then set NOTES_JWT_SECRET (and the rest) in .env
docker compose up -d --wait                   # PostgreSQL 18 and Redis 7.4 on 127.0.0.1
uv run alembic upgrade head                   # create the tables
uv run uvicorn notes_api.main:app --reload    # http://127.0.0.1:8000/ and /docs
uv run python -m notes_api.worker             # the ARQ worker (second terminal)
uv run pytest                                 # fast tests + PostgreSQL / Redis tests (Docker)
uv run pytest -m "not postgres and not redis" # only the fast tests (SQLite, fakeredis)
UPDATE_SNAPSHOTS=1 uv run pytest -k snapshot  # record a deliberate OpenAPI change
docker compose down                           # add -v to delete the data volume
```

Local plain HTTP: set `NOTES_COOKIE_SECURE=false`, or the browser will not send the session
cookie. Register `NOTES_ADMIN_EMAILS` addresses to get admin accounts.

Observability: every log line is JSON with `request_id`, `trace_id` and `span_id`
(`NOTES_LOG_JSON=false` for console output); Prometheus scrapes `GET /metrics`;
`NOTES_OTEL_EXPORTER=otlp` sends traces to an OpenTelemetry Collector at `NOTES_OTEL_ENDPOINT`;
`NOTES_SENTRY_DSN` turns on error tracking. Probes: `/health/live`, `/health/ready`
(database and Redis), `/health/startup` (schema at the expected migration).

CI (`.github/workflows/notes-api.yml`) runs the whole suite against PostgreSQL and Redis service
containers: the tests read `NOTES_TEST_DATABASE_URL` and `NOTES_TEST_REDIS_URL`, and start
testcontainers only when those are not set.


## Deploy

```bash
mkdir -p .secrets && openssl rand -base64 32 > .secrets/notes_jwt_secret && chmod 444 .secrets/notes_jwt_secret
docker compose up -d --build --wait           # db, redis, migrate (one-off), api, worker, proxy
curl -k https://localhost:8443/health/ready   # Caddy terminates TLS (its local CA for localhost)
docker compose up -d --wait --scale api=3     # stateless API: Caddy balances the replicas
uv run locust -f load/locustfile.py --host https://localhost:8443 --headless -u 20 -r 10 -t 30s
docker compose down                           # -v also deletes the database volume
```

The image (`Dockerfile`) runs Uvicorn with `WEB_CONCURRENCY` worker processes, trusts proxy
headers, and shuts down gracefully (20 s) on SIGTERM. `deploy/` holds the Caddyfile, an Nginx
equivalent, Kubernetes manifests (probes, rolling updates, a migrate Job, an autoscaler), a
systemd unit and a Cloud Run service; `Procfile` covers Heroku-style platforms. CI/CD:
`.github/workflows/notes-api.yml`.


## Production

The production setup runs this stack on one Hetzner Cloud server with Docker Compose:
Caddy (automatic HTTPS from Let's Encrypt, HSTS), two API replicas, the worker, PostgreSQL,
Redis, Prometheus and Grafana. Every push to `main` that passes lint, types, tests, the image
build and the scans is deployed by `.github/workflows/notes-api.yml` with
`deploy/production/rollout.sh`: backup, migrations, then a zero-downtime swap of the replicas,
an HTTPS smoke test and an automatic rollback if it fails. `notes-api-uptime.yml` checks the
live API and its certificate every 15 minutes.

| File | Purpose |
| --- | --- |
| [`DEPLOY.md`](DEPLOY.md) | the runbook: server, secrets, first deploy, HTTPS checks, monitoring, rollback |
| [`LOAD_TEST.md`](LOAD_TEST.md) | the Locust scenario, the targets (p95 < 200 ms, < 1% errors, >= 100 req/s) and the results |
| `compose.prod.yaml` | production overrides merged over `compose.yaml` |
| `deploy/production/` | Caddyfile, Prometheus and alert rules, Grafana provisioning, `bootstrap.sh`, `rollout.sh`, `backup.sh`, `dc` |
| `load/report.py` | turns a Locust CSV into the results section of `LOAD_TEST.md` |


## Endpoints

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| `GET` | `/health`, `/health/live` | none | liveness (no dependency calls) |
| `GET` | `/health/ready`, `/health/startup` | none | readiness (database + Redis), startup (migrations at head) |
| `GET` | `/metrics` | none (block it at the proxy) | Prometheus text format |
| `POST` | `/api/v1/auth/register` | none | 201; rate limited; never accepts a role |
| `POST` | `/api/v1/auth/token` | none | OAuth2 password form (`username` = email, optional `scope`); rate limited (429 + `Retry-After`) |
| `POST` | `/api/v1/auth/refresh` | refresh token | rotation: each refresh token works once; reuse revokes the family |
| `POST` | `/api/v1/auth/logout` | refresh token (+ bearer) | revokes the family and denies the access token |
| `GET` | `/api/v1/auth/oauth/login`, `/oauth/callback` | none | OpenID Connect (Authorization Code + PKCE); 404 unless configured |
| `GET` | `/api/v1/users/me` | bearer or key | the current user |
| `POST/GET/DELETE` | `/api/v1/users/me/api-keys[/{id}]` | bearer | keys are shown once, stored as SHA-256, limited to scopes |
| `POST/GET` | `/api/v1/notes` | `notes:write` / `notes:read` | only the caller's notes |
| `GET` | `/api/v1/notes/feed` | `notes:read` | keyset pagination |
| `GET/PUT/PATCH/DELETE` | `/api/v1/notes/{note_id}` | `notes:read` / `notes:write` | someone else's note is a 404; PATCH `version` → 409 if stale |
| `GET` | `/api/v1/notes/{note_id}/links` | `notes:read` | link titles; private addresses are never fetched |
| `GET/PUT/DELETE` | `/api/v1/users/me/webhook` | bearer | a public URL; PUT returns the signing secret once |
| `POST` | `/api/v1/exports` | any user | 202 + `Location`; an ARQ job builds the export |
| `GET` | `/api/v1/exports/{id}`, `/download`, `/events` | owner | status, JSON file, `text/event-stream` progress (`Last-Event-ID`) |
| `WS` | `/api/v1/ws` | first message `{"token": ...}` | live note events; server pings; 1008 on bad auth |
| `POST/GET/DELETE` | `/api/v1/admin/import`, `/export`, `/notes` | admin role + `admin` scope | bulk operations |
| `GET/POST` | `/api/v1/admin/cache-stats`, `/webhooks/dead[/{id}/retry]` | admin | cache hit rate; dead-letter list and replay |
| `GET/POST` | `/login`, `/logout`, `/`, `/notes`, `/notes/{id}/pin` | session cookie + CSRF token | HTML (Jinja2 + HTMX) |

Credentials: `Authorization: Bearer <access token>` or `X-API-Key: nk_...`. Errors are
`application/problem+json` (RFC 9457). Every response carries `X-Request-ID`,
`Server-Timing` and security headers (HSTS, CSP, `X-Content-Type-Options`, `X-Frame-Options`).
`GET /api/v1/notes/{id}` sends `ETag` and `Cache-Control: private, no-cache` and answers
`If-None-Match` with 304. Webhooks carry `X-Notes-Event-Id` and
`X-Notes-Signature: t=<unix time>,v1=<HMAC-SHA256 of "t.body">`.


## Layout

```text
src/notes_api/
├── main.py           # create_app(): settings, security, handlers, middleware, routers
├── core/             # config, errors, middleware, lifespan, logging (structlog + redaction),
│                     # metrics (Prometheus), tracing (OpenTelemetry), sentry
├── routers/          # health, auth, users, notes, exports, realtime, admin, pages
├── dependencies.py   # principal / scopes / roles, sessions, Redis, services as Annotated aliases
├── auth.py           # AuthService: register, login, rotate, logout, API keys, OIDC accounts
├── oauth.py          # OidcClient: Authorization Code + PKCE, ID-token verification
├── security.py       # Argon2id hasher, TokenService (PyJWT), Principal, scopes
├── ratelimit.py      # FixedWindowRateLimiter on Redis
├── worker.py         # ARQ tasks (relay, webhooks, exports, purge) + run_worker()
├── events.py         # outbox events, Redis channels, webhook signatures
├── cache.py          # NoteCache: cache-aside, TTL jitter, stampede lock, stats
├── exports.py        # export progress in Redis Streams, SSE formatting
├── mailer.py         # Mailer protocol, LogMailer, the welcome email
├── services.py       # NoteService (owner-scoped), parse_import, LinkPreviewer (SSRF-safe)
├── repositories.py   # NoteRepository / SqlNoteRepository, SqlUserRepository
├── models.py         # User, RefreshToken, ApiKey, OutboxEvent, Note, Tag, note_tags
├── db.py             # Base (naming convention), UTCDateTime, engine, session factory
├── exceptions.py     # DomainError and subclasses (no FastAPI)
├── schemas.py        # Pydantic request/response models
├── pagination.py     # Page[T], CursorPage[T], cursors
├── templates/        # Jinja2 templates (login, notes)
└── static/           # CSS
alembic/              # env.py (async) + versions/0001-0006
compose.yaml          # the stack: db, redis, migrate, api, worker, proxy (Caddy)
Dockerfile            # multi-stage uv build, non-root runtime; .dockerignore
deploy/               # Caddyfile, nginx.conf, k8s/, systemd/, cloudrun/
load/locustfile.py    # load test with a p95 < 200 ms gate
Procfile              # web / worker / release for a PaaS
tests/                # pytest: one app, SQLite file and fakeredis per test; factories.py;
                      # PostgreSQL / Redis tests use CI services or testcontainers;
                      # test_contract.py: Schemathesis + snapshots/openapi.json
```


## Dependency rule

Dependencies point inwards: routers → services → repositories → models. Nothing in
`services.py`, `auth.py`, `security.py`, `repositories.py`, `models.py`, `db.py` or
`exceptions.py` imports FastAPI; `core/errors.py` maps domain exceptions to HTTP responses.
