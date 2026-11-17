"""Unit 6.4 — Databases with SQLAlchemy 2.0 (with Lab 6.4 and Notes API v3)."""

from nbformat import NotebookNode
from unit_6_1 import SERVER_HELPERS_SOURCE, UNIT_SETUP_SOURCE_2  # one copy of the helpers
from unit_6_2 import NOTES_HELPERS_SOURCE
from unit_6_3 import NOTES_PROJECT_HELPERS_SOURCE, PRUNE_HELPER_SOURCE

from nb_builder import code, md, predict_cells, writefile_cells

UNIT_SETUP_SOURCE = r"""
import asyncio
import atexit
import contextlib
import importlib
import importlib.util
import inspect
import json
import logging
import os
import platform
import random
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import sysconfig
import time
import urllib.request
from collections.abc import AsyncIterator, Callable, Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Annotated, Any

import alembic
import asyncpg
import fastapi
import httpx
import pydantic
import pydantic_settings
import sqlalchemy as sa
import starlette
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import (
    Column,
    ForeignKey,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    event,
    func,
    insert,
    select,
    text,
    tuple_,  # noqa: F401  (for Lab 6.4, exercise 6)
    update,
)
from sqlalchemy import inspect as sa_inspect  # the stdlib inspect stays available
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncAttrs, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    joinedload,
    mapped_column,
    raiseload,
    relationship,
    selectinload,
    sessionmaker,
)
from sqlalchemy.orm.exc import StaleDataError

REPO_ROOT = find_repo_root()
scratch_dir = REPO_ROOT / "notebooks" / "_scratch"  # git-ignored
PHASE6_DIR = scratch_dir / "phase6"
PHASE6_DIR.mkdir(parents=True, exist_ok=True)
os.chdir(REPO_ROOT / "notebooks")  # %%writefile cells use paths relative to notebooks/
if str(PHASE6_DIR) not in sys.path:
    sys.path.insert(0, str(PHASE6_DIR))
CHILD_ENV = {**os.environ, "PYTHON_COLORS": "0", "PYTHONUNBUFFERED": "1", "NO_COLOR": "1"}
CHILD_ENV.pop("FORCE_COLOR", None)
HAS_NODE = shutil.which("node") is not None
HAS_UV = shutil.which("uv") is not None

NOTES_API_DIR = REPO_ROOT / "projects" / "notes_api"  # the Notes API's own uv project
NOTES_SRC = NOTES_API_DIR / "src"
for folder in (NOTES_SRC / "notes_api", NOTES_API_DIR / "tests"):
    folder.mkdir(parents=True, exist_ok=True)  # %%writefile does not create folders
if str(NOTES_SRC) not in sys.path:
    sys.path.insert(0, str(NOTES_SRC))
"""

DATABASE_HELPERS_SOURCE = r'''
POSTGRES_IMAGE = "postgres:18-alpine"
REDIS_IMAGE = "redis:7.4"


def docker_available() -> bool:
    """True if the docker SDK is installed and a Docker daemon answers."""
    if not all(importlib.util.find_spec(name) for name in ("docker", "testcontainers")):
        return False
    try:
        import docker

        docker.from_env().ping()
    except Exception:
        return False
    return True


HAS_DOCKER = docker_available()


class SqlEchoHandler(logging.Handler):
    """Print SQLAlchemy's echo lines as 'SQL: ...', hiding the timing part that varies."""

    def emit(self, record: logging.LogRecord) -> None:
        """Print one statement (or its parameters) to the current stdout."""
        timing = r"\[(generated in|cached since) [\d.]+s( ago)?\] "
        message = re.sub(timing, "", record.getMessage())
        print(f"SQL: {message}")


engine_logger = logging.getLogger("sqlalchemy.engine.Engine")
engine_logger.handlers[:] = [SqlEchoHandler()]  # a handler exists, so echo=True adds no other
engine_logger.propagate = False


class SqlRecorder:
    """Collect every SQL statement an engine sends while the with block runs."""

    def __init__(self, engine: sa.Engine) -> None:
        """Listen on a sync engine (pass async_engine.sync_engine for async engines)."""
        self.engine = engine
        self.statements: list[str] = []

    def _record(self, conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        """before_cursor_execute listener."""
        self.statements.append(" ".join(statement.split()))

    def __enter__(self) -> SqlRecorder:
        """Start listening."""
        event.listen(self.engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Stop listening."""
        event.remove(self.engine, "before_cursor_execute", self._record)

    def show(self, width: int = 150) -> None:
        """Print the statements, numbered and shortened."""
        for number, statement in enumerate(self.statements, start=1):
            print(f"  {number}. {statement[:width]}{'...' if len(statement) > width else ''}")


def mask_plan(plan_lines: Iterable[str]) -> str:
    """An EXPLAIN (ANALYZE) plan without costs and timings, which change from run to run."""
    cleaned = []
    for line in plan_lines:
        if line.lstrip().startswith(("Planning", "Execution", "Buffers")):
            continue
        cleaned.append(re.sub(r"\s*\((cost|actual)[^)]*\)", "", line).rstrip())
    return "\n".join(cleaned)


print(interpreter_label())
print(f"{sa.__version__=}  {asyncpg.__version__=}  {alembic.__version__=}")
demo_mode = "run in Docker" if HAS_DOCKER else "print SKIP messages"
print(f"{HAS_DOCKER=}  (PostgreSQL and Redis demos {demo_mode})")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 6.4 — Databases with SQLAlchemy 2.0

            **Objectives**

            - Design relational schemas: keys, normalization, indexes, constraints,
              transactions and isolation levels; read an `EXPLAIN ANALYZE` plan; run
              PostgreSQL in Docker Compose.
            - Choose a driver (psycopg 3, asyncpg) and size a connection pool.
            - Explain SQLAlchemy's layers: Engine, Connection, Core and ORM.
            - Write typed ORM models with `DeclarativeBase`, `Mapped` and `mapped_column`,
              relationships, mixins and naming conventions.
            - Use the `Session`: unit of work, identity map, `flush` vs `commit`, object states.
            - Query with `select`, joins, aggregates, subqueries, bulk `insert` / `update` /
              `delete`, and print the SQL they emit.
            - Detect N+1 queries and fix them with `selectinload` / `joinedload`; forbid them
              with `raiseload`.
            - Use async SQLAlchemy with FastAPI: a session per request, one transaction per
              request, repositories, ORM → Pydantic.
            - Evolve a schema with Alembic: autogenerate, review, upgrade/downgrade, data
              migrations, expand/contract.
            - Handle concurrency: optimistic locking, `SELECT ... FOR UPDATE`, `IntegrityError`
              → 409, savepoints.
            - Know the alternatives: SQLModel, raw asyncpg, document databases, Redis.
            - Move the **Notes API to v3**: PostgreSQL, many-to-many tags, three migrations.

            **JS bridge**

            | JavaScript / TypeScript | Python | The difference that bites |
            | --- | --- | --- |
            | Prisma schema + `prisma generate` | SQLAlchemy models (`Mapped[...]`) are plain Python classes | no code generation step; the class **is** the schema and the type |
            | `prisma migrate dev` | Alembic `revision --autogenerate` + `upgrade` | autogenerate is a **draft**: you review and edit every migration |
            | TypeORM `@Entity`, `@ManyToMany` | `DeclarativeBase` + `relationship(secondary=...)` | relationships load **lazily** by default: the N+1 trap |
            | TypeORM `EntityManager` / Prisma transactions | `Session`: unit of work + identity map | changes are queued and sent at `flush`; one object per row per session |
            | `pg` / `postgres.js` | asyncpg / psycopg 3 | asyncpg uses `$1` placeholders and the binary protocol |
            | Knex query builder | SQLAlchemy Core (`select(...)`) | statements are objects you can print, compose and reuse |
            | Mongoose | (no ORM needed) Motor / PyMongo, or PostgreSQL `JSONB` | documents are dicts; PostgreSQL often covers the use case |
            | `ioredis` | `redis.asyncio` | same commands, same data types |

            Run the setup cells first. Part 1: imports (SQLAlchemy, asyncpg, Alembic) and the
            project folders:
            """
        ),
        code(UNIT_SETUP_SOURCE),
        md("Part 2: helpers shared with Units 6.1–6.3:"),
        code(UNIT_SETUP_SOURCE_2),
        md(
            """
            Part 3: the server and Notes API helpers from Units 6.1–6.3, and the database
            helpers for this unit: `docker_available()` (PostgreSQL and Redis run in Docker
            when it is there), an echo handler that prints SQLAlchemy's SQL log as `SQL: ...`
            lines without timings, `SqlRecorder(engine)` to collect the statements a block of
            code sends, and `mask_plan()` to strip costs and timings from query plans:
            """
        ),
        code(
            SERVER_HELPERS_SOURCE
            + "\n"
            + NOTES_HELPERS_SOURCE
            + "\n"
            + PRUNE_HELPER_SOURCE
            + "\n"
            + NOTES_PROJECT_HELPERS_SOURCE
            + "\n"
            + DATABASE_HELPERS_SOURCE
        ),
    ]


def _relational_cells() -> list[NotebookNode]:
    """6.4.1 Relational design."""
    return [
        md(
            """
            ### 6.4.1 Relational design

            An ORM does not free you from database design; it makes bad designs easier to
            write. The vocabulary:

            | Concept | Meaning | Example |
            | --- | --- | --- |
            | primary key | uniquely identifies a row; never changes | `notes.id` |
            | natural vs surrogate key | a real-world value (email) vs a generated one (id) | prefer surrogate keys + a `UNIQUE` constraint on the natural one |
            | foreign key | a column that must match a key in another table | `books.author_id → authors.id` |
            | normalization (1NF–3NF) | one fact in one place: atomic columns, no repeating groups, no column that depends on a non-key column | customer address stored once, not on every order |
            | index | a sorted structure for fast lookup and ordering; costs space and slows writes | `CREATE INDEX ... ON notes (created_at, id)` |
            | constraints | rules the database enforces for every client: `NOT NULL`, `UNIQUE`, `CHECK`, `FOREIGN KEY` | `CHECK (price >= 0)` |
            | transaction | a group of statements that succeed or fail together (ACID) | a transfer debits and credits, or neither |

            **Normalization in one picture.** Store a customer's city on every order and one
            update misses rows (an *update anomaly*). Store it once and join:
            """
        ),
        code(
            r'''
            FLAT_SQL = """
            CREATE TABLE orders_flat (id INTEGER PRIMARY KEY, customer TEXT, city TEXT, total INTEGER);
            INSERT INTO orders_flat VALUES (1, 'Asha', 'Pune', 500), (2, 'Asha', 'Pune', 300);
            UPDATE orders_flat SET city = 'Mumbai' WHERE id = 1;  -- Asha moved; one row forgotten
            """
            NORMALIZED_SQL = """
            CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, city TEXT NOT NULL);
            CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id));
            INSERT INTO customers VALUES (1, 'Asha', 'Pune');
            INSERT INTO orders VALUES (1, 1), (2, 1);
            UPDATE customers SET city = 'Mumbai' WHERE name = 'Asha';  -- one fact, one place
            """
            with contextlib.closing(sqlite3.connect(":memory:")) as connection:
                connection.executescript(FLAT_SQL + NORMALIZED_SQL)
                flat = connection.execute(
                    "SELECT DISTINCT customer, city FROM orders_flat ORDER BY city"
                ).fetchall()
                joined = connection.execute(
                    "SELECT DISTINCT c.name, c.city FROM orders o JOIN customers c ON c.id = o.customer_id"
                ).fetchall()
            print(f"flat: {flat}\nnormalized: {joined}")
            '''
        ),
        md(
            """
            **Constraints are the last line of defence.** Validation in the API can be skipped
            by another service, a script or a race between two requests; a constraint cannot.
            Each violation is an `IntegrityError` with a message naming the rule:
            """
        ),
        code(
            r'''
            with contextlib.closing(sqlite3.connect(":memory:")) as connection:
                connection.execute("PRAGMA foreign_keys = ON")  # SQLite needs this per connection
                connection.executescript("""
                    CREATE TABLE authors (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE);
                    CREATE TABLE books (
                        id INTEGER PRIMARY KEY,
                        author_id INTEGER NOT NULL REFERENCES authors(id),
                        price_paise INTEGER NOT NULL CHECK (price_paise >= 0)
                    );
                    INSERT INTO authors VALUES (1, 'asha@example.com');
                """)
                attempts = {
                    "duplicate email": "INSERT INTO authors VALUES (2, 'asha@example.com')",
                    "missing email": "INSERT INTO authors (id) VALUES (3)",
                    "negative price": "INSERT INTO books VALUES (1, 1, -5)",
                    "unknown author": "INSERT INTO books VALUES (2, 99, 100)",
                }
                for label, sql in attempts.items():
                    try:
                        connection.execute(sql)
                    except sqlite3.IntegrityError as error:
                        print(f"{label:16} → IntegrityError: {error}")
            '''
        ),
        md(
            """
            **Transactions and isolation levels.** A transaction is atomic, consistent,
            isolated and durable (ACID). *Isolation* is a dial: stronger levels prevent more
            anomalies between concurrent transactions and cost more conflicts and retries.

            | Level (PostgreSQL) | Dirty read | Non-repeatable read | Phantom read | Serialization anomaly |
            | --- | --- | --- | --- | --- |
            | Read committed (**default**) | no | possible | possible | possible |
            | Repeatable read (snapshot) | no | no | no (in PostgreSQL) | possible |
            | Serializable | no | no | no | no (conflicts abort with a serialization error; retry) |

            The next cells use a real PostgreSQL. **PostgreSQL in Docker Compose** first: a
            `compose.yaml` describes the service (image, credentials for local use only, a
            port on `127.0.0.1`, a volume, a health check); `docker compose up -d --wait`
            starts it and waits for the health check; `down -v` removes the container and the
            volume. The Notes API gets the same file in its v3 section. The cell writes it to
            the scratch folder, uses a free port, runs one query and always tears it down:
            """
        ),
        code(
            r'''
            COMPOSE_DIR = PHASE6_DIR / "postgres_compose"
            COMPOSE_DIR.mkdir(exist_ok=True)
            (COMPOSE_DIR / "compose.yaml").write_text(
                f"""services:
              db:
                image: {POSTGRES_IMAGE}
                environment:
                  POSTGRES_USER: course
                  POSTGRES_PASSWORD: course   # local development only
                  POSTGRES_DB: course
                ports:
                  - "127.0.0.1:${{POSTGRES_PORT}}:5432"
                volumes:
                  - course-db:/var/lib/postgresql
                healthcheck:
                  test: ["CMD-SHELL", "pg_isready -U course -d course"]
                  interval: 1s
                  retries: 30
            volumes:
              course-db:
            """,
                encoding="utf-8",
            )
            print((COMPOSE_DIR / "compose.yaml").read_text(encoding="utf-8").splitlines()[1:4])
            '''
        ),
        md(
            """
            Start it, query it with asyncpg, and remove it again (also when something fails).
            The health check passes while the image's first-start script still restarts the
            server once, so the connection is retried for a few seconds:
            """
        ),
        code(
            r'''
            async def connect_with_retry(dsn: str, attempts: int = 20) -> asyncpg.Connection:
                """Connect, retrying while the image's init script restarts the server."""
                for attempt in range(attempts):
                    try:
                        return await asyncpg.connect(dsn)
                    except OSError, asyncpg.exceptions.CannotConnectNowError:
                        if attempt == attempts - 1:
                            raise
                        await asyncio.sleep(0.5)
                raise AssertionError("unreachable")
            '''
        ),
        md("`compose_round_trip()`: docker compose up --wait, one query, docker compose down -v:"),
        code(
            r'''
            async def compose_round_trip() -> None:
                """docker compose up --wait, one query, docker compose down -v."""
                compose_port = free_port()
                compose = ["docker", "compose", "--project-name", "course-pg"]
                compose_env = {**CHILD_ENV, "POSTGRES_PORT": str(compose_port)}
                try:
                    started = subprocess.run(
                        [*compose, "up", "-d", "--wait"],
                        cwd=COMPOSE_DIR,
                        env=compose_env,
                        capture_output=True,
                        text=True,
                        timeout=180,
                    )
                    print(f"compose up: exit code {started.returncode}")
                    connection = await connect_with_retry(
                        f"postgresql://course:course@127.0.0.1:{compose_port}/course"
                    )
                    version = await connection.fetchval("SHOW server_version")
                    await connection.close()
                    print(f"connected to PostgreSQL {version.split()[0].split('.')[0]}.x on 127.0.0.1:<port>")
                finally:
                    stopped = subprocess.run(
                        [*compose, "down", "-v"],
                        cwd=COMPOSE_DIR,
                        env=compose_env,
                        capture_output=True,
                        text=True,
                        timeout=180,
                    )
                    print(f"compose down -v: exit code {stopped.returncode}")


            if HAS_DOCKER and shutil.which("docker"):
                await compose_round_trip()
            else:
                print(
                    "SKIP docker compose: Docker is not available (the rest of the unit falls back to SQLite)"
                )
            '''
        ),
        md(
            """
            For the rest of the unit one PostgreSQL container is shared: **testcontainers**
            starts it on a random free port and returns its URL. (Starting one per cell would
            cost seconds each time.) `stop_shared_postgres()` stops and removes it: the
            *Clean up* cell at the end of the unit calls it, and an `atexit` hook calls it
            when the kernel shuts down, in case a run stops before the end.
            (testcontainers' reaper container only cleans up after a **crash**; on a normal
            exit testcontainers stops the reaper first.) `PG_URL` is the SQLAlchemy URL
            (`postgresql+asyncpg://...`), `PG_DSN` the plain one asyncpg expects; both are
            `None` without Docker:
            """
        ),
        code(
            r'''
            pg_container = None
            PG_URL: str | None = None
            PG_DSN: str | None = None


            def stop_shared_postgres() -> bool:
                """Stop and remove the shared container if it is running; True if one was stopped."""
                global pg_container
                if pg_container is None:
                    return False
                with contextlib.suppress(Exception):
                    pg_container.stop()
                pg_container = None
                return True


            if HAS_DOCKER:
                from testcontainers.community.postgres import PostgresContainer

                pg_container = PostgresContainer(POSTGRES_IMAGE, driver="asyncpg")
                pg_container.start()
                atexit.register(stop_shared_postgres)  # also on kernel shutdown
                PG_URL = pg_container.get_connection_url()
                PG_DSN = PG_URL.replace("postgresql+asyncpg://", "postgresql://")
                print(
                    "PostgreSQL container running:",
                    re.sub(r"//[^@]+@[^/]+", "//<user>:<password>@<host>:<port>", PG_URL),
                )
            else:
                print("SKIP PostgreSQL: no Docker; PostgreSQL-only cells print SKIP, the rest uses SQLite")


            async def pg_fetch(sql: str, *args: object) -> list[asyncpg.Record]:
                """Run one statement on a fresh asyncpg connection and return the rows."""
                connection = await asyncpg.connect(PG_DSN)
                try:
                    return await connection.fetch(sql, *args)
                finally:
                    await connection.close()
            '''
        ),
        md(
            """
            **Indexes and `EXPLAIN ANALYZE`.** `EXPLAIN` shows the plan PostgreSQL chooses;
            `EXPLAIN ANALYZE` also runs the query and reports what really happened. Without an
            index, finding one customer by email means reading the whole table (*Seq Scan*);
            with one, PostgreSQL walks a B-tree straight to the row (*Index Scan*). The plans
            are printed without costs and timings, which change on every run:
            """
        ),
        code(
            r'''
            async def index_demo() -> None:
                """Plan a lookup before and after creating an index on 100 000 rows."""
                await pg_fetch("DROP TABLE IF EXISTS customers")
                await pg_fetch(
                    "CREATE TABLE customers (id bigint PRIMARY KEY, email text NOT NULL, city text NOT NULL)"
                )
                await pg_fetch(
                    "INSERT INTO customers SELECT n, 'user' || n || '@example.com',"
                    " (ARRAY['Pune','Goa','Delhi'])[n % 3 + 1] FROM generate_series(1, 100000) AS n"
                )
                await pg_fetch("ANALYZE customers")
                query = "EXPLAIN ANALYZE SELECT id FROM customers WHERE email = 'user77777@example.com'"
                print("without an index:\n" + mask_plan(row[0] for row in await pg_fetch(query)))
                await pg_fetch("CREATE INDEX ix_customers_email ON customers (email)")
                print("with ix_customers_email:\n" + mask_plan(row[0] for row in await pg_fetch(query)))


            if PG_DSN:
                await index_demo()
            else:
                print(
                    "SKIP EXPLAIN ANALYZE on PostgreSQL (no Docker). SQLite has EXPLAIN QUERY PLAN; see 6.3.12."
                )
            '''
        ),
        md(
            """
            **Isolation levels for real.** Two connections, one balance. Under *read committed*
            a transaction sees other transactions' commits as soon as they happen, so reading
            twice can give two answers. Under *repeatable read* it keeps its snapshot, and when
            it then tries to update a row someone else changed, PostgreSQL refuses with a
            serialization error (the application should retry the whole transaction):
            """
        ),
        code(
            r'''
            async def isolation_demo(level: str) -> None:
                """Read, let another connection commit a change, read again, then try to write."""
                await pg_fetch("DROP TABLE IF EXISTS accounts")
                await pg_fetch("CREATE TABLE accounts (id int PRIMARY KEY, balance int NOT NULL)")
                await pg_fetch("INSERT INTO accounts VALUES (1, 100)")
                reader, writer = await asyncpg.connect(PG_DSN), await asyncpg.connect(PG_DSN)
                try:
                    transaction = reader.transaction(isolation=level)
                    await transaction.start()
                    first = await reader.fetchval("SELECT balance FROM accounts WHERE id = 1")
                    await writer.execute("UPDATE accounts SET balance = 50 WHERE id = 1")  # commits at once
                    second = await reader.fetchval("SELECT balance FROM accounts WHERE id = 1")
                    try:
                        await reader.execute("UPDATE accounts SET balance = balance - 10 WHERE id = 1")
                        outcome = "update allowed"
                    except asyncpg.exceptions.SerializationError as error:
                        outcome = f"{type(error).__name__}: {error}"
                    await transaction.rollback()
                    print(f"{level:16} first read {first}, second read {second}; {outcome}")
                finally:
                    await reader.close()
                    await writer.close()


            if PG_DSN:
                await isolation_demo("read_committed")
                await isolation_demo("repeatable_read")
            else:
                print("SKIP isolation levels: needs PostgreSQL (Docker)")
            '''
        ),
    ]


def _driver_cells() -> list[NotebookNode]:
    """6.4.2 Drivers and pooling."""
    return [
        md(
            """
            ### 6.4.2 Drivers and pooling

            A **driver** (DBAPI) speaks the database's wire protocol; SQLAlchemy sits on top
            and picks it from the URL: `dialect+driver://user:password@host:port/database`.

            | Driver | URL | Style | Notes |
            | --- | --- | --- | --- |
            | psycopg 3 | `postgresql+psycopg://` | sync **and** async | the successor of psycopg2; uses libpq; server-side binding, `COPY`, pipeline mode |
            | asyncpg | `postgresql+asyncpg://` | async only | its own binary-protocol implementation, very fast; `$1` placeholders; prepared statements by default |
            | aiosqlite | `sqlite+aiosqlite://` | async wrapper around `sqlite3` | tests and small tools |
            | pysqlite (`sqlite3`) | `sqlite://` | sync | in the standard library |

            psycopg 3 is not a course dependency (Appendix A lists asyncpg), so its cell only
            checks for it:
            """
        ),
        code(
            r"""
            if importlib.util.find_spec("psycopg") is None:
                print("SKIP psycopg 3: not installed (not a course dependency). Usage would be:")
                print('    with psycopg.connect(dsn) as conn: conn.execute("SELECT %s::int", (42,)).fetchone()')
                print("    async with await psycopg.AsyncConnection.connect(dsn) as conn: ...")
                print("    SQLAlchemy URL: postgresql+psycopg://user:password@host/db")
            else:
                import psycopg

                print(f"psycopg {psycopg.__version__} is installed")
            """
        ),
        md(
            """
            **asyncpg directly.** Placeholders are `$1, $2, ...`; rows come back as `Record`
            objects (by index or by name); types are converted both ways (Python `date` ↔
            PostgreSQL `date`, lists ↔ arrays):
            """
        ),
        code(
            r'''
            async def asyncpg_basics() -> None:
                """Parameters, records and type conversion."""
                connection = await asyncpg.connect(PG_DSN)
                try:
                    row = await connection.fetchrow(
                        "SELECT $1::text AS city, $2::date AS day, $3::int[] AS scores",
                        "Pune",
                        date(2026, 11, 17),
                        [3, 1, 2],
                    )
                    print(row, "→", row["city"], type(row["day"]).__name__, row["scores"])
                    count = await connection.fetchval("SELECT count(*) FROM customers WHERE city = $1", "Goa")
                    print(f"{count=}")
                finally:
                    await connection.close()


            if PG_DSN:
                await asyncpg_basics()
            else:
                print("SKIP asyncpg: needs PostgreSQL (Docker)")
            '''
        ),
        md(
            """
            **Why pools.** Opening a PostgreSQL connection costs a TCP handshake,
            authentication and a server process: milliseconds each time. A pool keeps a few
            connections open and lends them out. It also **limits concurrency**: 20 queries
            through a pool of 5 run 5 at a time. Each query below sleeps 50 ms on the server:
            """
        ),
        code(
            r'''
            async def pool_demo(pool_size: int) -> float:
                """Seconds for 20 concurrent 50 ms queries through a pool of pool_size."""
                pool = await asyncpg.create_pool(PG_DSN, min_size=pool_size, max_size=pool_size)
                try:
                    started = time.perf_counter()
                    await asyncio.gather(*(pool.execute("SELECT pg_sleep(0.05)") for _ in range(20)))
                    return time.perf_counter() - started
                finally:
                    await pool.close()


            if PG_DSN:
                for size in (5, 20):
                    print(
                        f"pool of {size:2}: {await pool_demo(size):.2f} s for 20 queries "
                        f"(expected about {20 // size * 0.05:.2f} s)"
                    )
            else:
                print("SKIP asyncpg pool: needs PostgreSQL (Docker)")
            '''
        ),
        md(
            """
            SQLAlchemy has its own pool (`QueuePool` by default) with these knobs:
            `pool_size` (connections kept open), `max_overflow` (extra ones allowed under load),
            `pool_timeout` (how long a request waits for a free connection before
            `TimeoutError`), `pool_pre_ping` (test a connection before use) and
            `pool_recycle`. With a pool of 2 and no overflow, a third simultaneous checkout
            waits and then fails (SQLite file database, so it runs everywhere):
            """
        ),
        code(
            r"""
            pool_engine = create_engine(
                f"sqlite:///{PHASE6_DIR / 'pool_demo.db'}",
                poolclass=sa.QueuePool,
                pool_size=2,
                max_overflow=0,
                pool_timeout=0.3,
            )
            first, second = pool_engine.connect(), pool_engine.connect()
            print(pool_engine.pool.status())
            started = time.perf_counter()
            print(
                raised_message(pool_engine.connect).split(",")[0],
                f"after {time.perf_counter() - started:.1f} s",
            )
            first.close()
            third = pool_engine.connect()  # a returned connection is reused
            print(pool_engine.pool.status())
            third.close()
            second.close()
            pool_engine.dispose()
            """
        ),
        md(
            """
            > **Sizing rule of thumb:** total connections = processes × (`pool_size` +
            > `max_overflow`), and that must stay below the server's `max_connections`
            > (100 by default). Four Uvicorn workers with `pool_size=5, max_overflow=10` can
            > open 60. More connections than CPU cores rarely makes PostgreSQL faster; a
            > pooler such as PgBouncer helps when many processes connect.
            """
        ),
    ]


def _architecture_cells() -> list[NotebookNode]:
    """6.4.3 SQLAlchemy architecture."""
    return [
        md(
            """
            ### 6.4.3 SQLAlchemy architecture

            ```mermaid
            graph TB
              ORM["ORM: Session, mapped classes, relationships"] --> Core
              Core["Core: Table, select(), insert(), SQL expression language"] --> Engine
              Engine["Engine: Dialect (SQL flavour) + Pool"] --> Connection
              Connection --> DBAPI["DBAPI driver: sqlite3, asyncpg, psycopg"]
            ```

            <details><summary>ASCII version</summary>

            ```text
            ORM  (Session, mapped classes)
             └── Core  (Table, select(), insert())
                  └── Engine  (Dialect + Pool)  →  Connection  →  DBAPI driver
            ```

            </details>

            | Layer | Object | Job |
            | --- | --- | --- |
            | Engine | `create_engine(url)` | one per database per process: knows the dialect, owns the pool |
            | Connection | `engine.connect()` / `engine.begin()` | one checked-out DBAPI connection; runs statements; `begin()` commits on success |
            | Core | `Table`, `select()`, `insert()` | SQL as Python objects: composable, dialect-aware, safe from injection |
            | ORM | `Session`, mapped classes | rows as objects with identity, relationships and change tracking |

            The Engine and a Connection with raw SQL (`text()`; always pass values as bound
            parameters, never with f-strings):
            """
        ),
        code(
            r"""
            core_engine = create_engine("sqlite://")  # in-memory SQLite
            print(f"{core_engine.dialect.name=}  {core_engine.driver=}  {core_engine.url=}")
            with core_engine.begin() as connection:  # BEGIN ... COMMIT (ROLLBACK on error)
                connection.execute(text("CREATE TABLE cities (name TEXT PRIMARY KEY, population INTEGER)"))
                connection.execute(
                    text("INSERT INTO cities VALUES (:name, :population)"),
                    [{"name": "Pune", "population": 7_400_000}, {"name": "Goa", "population": 1_500_000}],
                )
            with core_engine.connect() as connection:
                result = connection.execute(
                    text("SELECT name, population FROM cities WHERE population > :minimum"),
                    {"minimum": 2_000_000},
                )
                print(result.all())
            """
        ),
        md(
            """
            **Core.** A `Table` describes columns once; `select()`, `insert()`, `update()` and
            `delete()` build statement objects. Printing a statement shows its SQL; compiling
            it for another dialect shows how SQLAlchemy adapts (`LIMIT` vs `FETCH`, quoting,
            placeholders):
            """
        ),
        code(
            r"""
            core_metadata = MetaData()
            cities = Table(
                "cities",
                core_metadata,
                Column("name", String(50), primary_key=True),
                Column("population", sa.Integer),
            )
            big_cities = (
                select(cities.c.name)
                .where(cities.c.population > 1_000_000)
                .order_by(cities.c.population.desc())
                .limit(5)
            )
            print(big_cities)
            print("--- PostgreSQL:\n" + str(big_cities.compile(dialect=postgresql.dialect())))
            print("--- with values inlined (for reading only, never for executing):")
            print(big_cities.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
            with core_engine.connect() as connection:
                print(connection.execute(big_cities).scalars().all())
            """
        ),
        md(
            """
            **Core vs ORM.** The ORM builds on Core: you `select()` mapped classes instead of
            tables and get objects back. Use Core for bulk work and reports, the ORM for
            business objects. The next section defines the ORM models used for the rest of
            the unit.
            """
        ),
    ]


def _model_cells() -> list[NotebookNode]:
    """6.4.4 Typed ORM models."""
    return [
        md(
            """
            ### 6.4.4 Typed ORM models

            SQLAlchemy 2.0 models are typed classes:

            | Piece | Role |
            | --- | --- |
            | `class Base(DeclarativeBase)` | the registry and `MetaData` every model shares |
            | `Mapped[int]`, `Mapped[str \\| None]` | the Python type; `\\| None` makes the column nullable, otherwise `NOT NULL` |
            | `mapped_column(String(100), unique=True, index=True, server_default=...)` | column details the type does not say |
            | `relationship(back_populates=...)` | one-to-many / many-to-one between objects |
            | `relationship(secondary=table)` | many-to-many through an association table |
            | mixins | plain classes with `Mapped` attributes, reused by several models |
            | naming convention | `MetaData(naming_convention=...)` names every constraint and index predictably, so migrations can find them later |

            The bookshop used in this unit: authors write books (one-to-many), books have
            genres (many-to-many) and reviews (one-to-many, deleted with their book). Part 1,
            the base, a mixin and the association table:
            """
        ),
        code(
            r'''
            SHOP_NAMING = {
                "ix": "ix_%(column_0_label)s",
                "uq": "uq_%(table_name)s_%(column_0_name)s",
                "ck": "ck_%(table_name)s_%(constraint_name)s",
                "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
                "pk": "pk_%(table_name)s",
            }


            class ShopBase(AsyncAttrs, DeclarativeBase):
                """Base class of the bookshop models (AsyncAttrs: see 6.4.8)."""

                metadata = MetaData(naming_convention=SHOP_NAMING)


            class TimestampMixin:
                """A created_at column the database fills in."""

                created_at: Mapped[datetime] = mapped_column(server_default=func.now())


            book_genres = Table(
                "book_genres",
                ShopBase.metadata,
                Column("book_id", ForeignKey("books.id", ondelete="CASCADE"), primary_key=True),
                Column("genre_id", ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True),
            )
            print(f"{book_genres.primary_key.name=}")
            '''
        ),
        md(
            """
            Part 2, the four models. Relationship annotations name the other class:
            `Mapped[list[Book]]` works even though `Book` is defined further down, because
            annotations are evaluated lazily (*changed in 3.14*, PEP 649/749; older code
            quotes them: `Mapped[list["Book"]]`). With `back_populates` both sides stay in
            sync in memory:
            """
        ),
        code(
            r'''
            class Author(TimestampMixin, ShopBase):
                """Writes books."""

                __tablename__ = "authors"
                id: Mapped[int] = mapped_column(primary_key=True)
                name: Mapped[str] = mapped_column(String(100), unique=True)
                country: Mapped[str | None] = mapped_column(String(50))
                books: Mapped[list[Book]] = relationship(back_populates="author", order_by="Book.id")


            class Genre(ShopBase):
                """A category; many books share it."""

                __tablename__ = "genres"
                id: Mapped[int] = mapped_column(primary_key=True)
                name: Mapped[str] = mapped_column(String(30), unique=True)


            class Book(TimestampMixin, ShopBase):
                """Belongs to one author; has genres and reviews."""

                __tablename__ = "books"
                __table_args__ = (sa.CheckConstraint("price_paise >= 0", name="price_not_negative"),)
                id: Mapped[int] = mapped_column(primary_key=True)
                title: Mapped[str] = mapped_column(String(200), index=True)
                price_paise: Mapped[int]
                author_id: Mapped[int] = mapped_column(ForeignKey("authors.id"))
                author: Mapped[Author] = relationship(back_populates="books")
                genres: Mapped[list[Genre]] = relationship(secondary=book_genres, order_by=Genre.name)
                reviews: Mapped[list[Review]] = relationship(
                    back_populates="book", cascade="all, delete-orphan"
                )
            '''
        ),
        md("`Review`: a rating of one book:"),
        code(
            r'''
            class Review(ShopBase):
                """A rating of one book."""

                __tablename__ = "reviews"
                id: Mapped[int] = mapped_column(primary_key=True)
                book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
                stars: Mapped[int]
                book: Mapped[Book] = relationship(back_populates="reviews")


            print(sorted(ShopBase.metadata.tables))
            '''
        ),
        md(
            """
            The DDL SQLAlchemy generates for `books`, for SQLite and for PostgreSQL. Notice the
            constraint and index names that came from the naming convention, and `NOT NULL` on
            every column whose type has no `| None`:
            """
        ),
        code(
            r"""
            from sqlalchemy.schema import CreateIndex, CreateTable

            books_table = ShopBase.metadata.tables["books"]
            print(str(CreateTable(books_table).compile(dialect=postgresql.dialect())).strip())
            for index in books_table.indexes:
                print(str(CreateIndex(index).compile(dialect=postgresql.dialect())).strip() + ";")
            sqlite_ddl = str(CreateTable(ShopBase.metadata.tables["authors"]).compile(dialect=sqlite.dialect()))
            print("--- SQLite, authors:", " ".join(sqlite_ddl.split()))
            """
        ),
        md(
            """
            **Under the hood.** `sa_inspect(Model)` returns the mapper: the columns and the
            relationships SQLAlchemy derived from the annotations, including each
            relationship's direction:
            """
        ),
        code(
            r"""
            book_mapper = sa_inspect(Book)
            print([column.key for column in book_mapper.columns])
            for relationship_property in book_mapper.relationships:
                print(
                    f"Book.{relationship_property.key:8} → "
                    f"{relationship_property.mapper.class_.__name__:7} {relationship_property.direction.name}"
                )
            print({column.name: (str(column.type), column.nullable) for column in Author.__table__.columns})
            """
        ),
        md(
            """
            > **Note:** `class Base(MappedAsDataclass, DeclarativeBase)` turns models into
            > dataclasses (typed `__init__`, `__repr__`, `__eq__`). The Notes API keeps plain
            > declarative models; both styles use the same `Mapped` annotations.
            """
        ),
    ]


def _session_cells() -> list[NotebookNode]:
    """6.4.5 Sessions."""
    return [
        md(
            """
            ### 6.4.5 Sessions

            The `Session` is the ORM's workspace for one unit of work (one request, one job):

            | Idea | Meaning |
            | --- | --- |
            | unit of work | you change objects; the session works out the `INSERT` / `UPDATE` / `DELETE` statements and their order |
            | identity map | one Python object per database row per session: loading a row twice gives the **same** object |
            | `flush()` | send the pending changes to the database **inside** the open transaction (ids become known) |
            | `commit()` | flush, then `COMMIT`; by default every object is *expired* and reloads on next access |
            | `rollback()` | undo everything since the transaction began |

            The bookshop lives in a SQLite file; the tables are created from the models and a
            session factory (`sessionmaker`) is configured once:
            """
        ),
        code(
            r"""
            SHOP_DB = PHASE6_DIR / "bookshop.db"
            SHOP_DB.unlink(missing_ok=True)
            shop_engine = create_engine(f"sqlite:///{SHOP_DB}")
            event.listen(
                shop_engine,
                "connect",
                lambda dbapi_connection, _: dbapi_connection.execute("PRAGMA foreign_keys=ON"),
            )
            ShopBase.metadata.create_all(shop_engine)
            ShopSession = sessionmaker(shop_engine)
            print(sa_inspect(shop_engine).get_table_names())
            """
        ),
        md(
            """
            **Unit of work.** New objects are *pending* until the flush. The recorder shows the
            statements: SQLAlchemy inserts authors before books (the foreign key needs the
            author's id), then the association rows, all in one transaction:
            """
        ),
        code(
            r"""
            with ShopSession() as session, SqlRecorder(shop_engine) as recorded:
                classic, fantasy = Genre(name="classic"), Genre(name="fantasy")
                asha = Author(name="Asha Rao", country="India")
                asha.books = [
                    Book(title="Monsoon Letters", price_paise=39900, genres=[classic]),
                    Book(title="The Glass Fort", price_paise=54900, genres=[fantasy]),
                ]
                session.add(asha)
                print(f"before flush: {len(session.new)} pending objects, {asha.id=}")
                session.flush()
                print(f"after flush: {asha.id=}, book ids {[book.id for book in asha.books]}")
                session.commit()
            recorded.show(110)
            """
        ),
        md(
            """
            Now the rest of the shop's data, used by every later demo (a function, so cells
            further down can rebuild it from scratch):
            """
        ),
        code(
            r'''
            def seed_shop(session: Session) -> None:
                """Three more authors, more books and genres, and some reviews."""
                genres = {genre.name: genre for genre in session.scalars(select(Genre))}
                genres |= {
                    name: Genre(name=name)
                    for name in ("classic", "fantasy", "romance", "science")
                    if name not in genres
                }
                ravi = Author(name="Ravi Menon", country="India")
                jane = Author(name="Jane Austen", country="UK")
                new_writer = Author(name="New Writer")  # no country, no books yet
                ravi.books = [
                    Book(title="Stars over Kochi", price_paise=29900, genres=[genres["science"]]),
                    Book(
                        title="Tea and Tides", price_paise=19900, genres=[genres["romance"], genres["classic"]]
                    ),
                ]
                jane.books = [
                    Book(title="Emma", price_paise=24900, genres=[genres["classic"], genres["romance"]]),
                    Book(title="Persuasion", price_paise=22900, genres=[genres["classic"]]),
                ]
                session.add_all([ravi, jane, new_writer])
                session.flush()
                stars = [5, 4, 3, 5, 2, 4, 1, 5]
                books = session.scalars(select(Book).order_by(Book.id)).all()
                session.add_all(
                    Review(book=book, stars=star) for book, star in zip(books * 2, stars, strict=False)
                )


            with ShopSession.begin() as session:  # begin(): commit at the end of the block
                seed_shop(session)
            with ShopSession() as session:
                print(
                    {
                        name: session.scalar(select(func.count()).select_from(model))
                        for name, model in [("authors", Author), ("books", Book), ("reviews", Review)]
                    }
                )
            '''
        ),
        md(
            """
            **Identity map.** Asking twice for the same row, by primary key or by query, gives
            the very same object, and `session.get()` does not even send a second `SELECT`:
            """
        ),
        code(
            r"""
            with ShopSession() as session, SqlRecorder(shop_engine) as recorded:
                first = session.get(Book, 1)
                again = session.get(Book, 1)
                via_query = session.scalars(select(Book).where(Book.title == "Monsoon Letters")).one()
                print(
                    f"{first is again=}  {first is via_query=}  "
                    f"rows in the identity map: {len(session.identity_map)}"
                )
            print(f"{len(recorded.statements)} SELECT statements sent")
            """
        ),
        md(
            """
            **Object states.** Every mapped object is in one of five states; `sa_inspect(obj)`
            reports it:

            | State | Meaning |
            | --- | --- |
            | transient | a new object, not in any session |
            | pending | `session.add()`ed, not flushed yet |
            | persistent | has a row and belongs to a session |
            | deleted | `session.delete()`d and flushed; becomes detached at commit |
            | detached | has a row but no session (the session was closed) |

            (Below, the rollback also undoes the flushed `INSERT`, so the object ends up
            *transient* again, not detached.)
            """
        ),
        code(
            r'''
            def state_of(obj: object) -> str:
                """The state flag sa_inspect reports for a mapped object."""
                info = sa_inspect(obj)
                return next(
                    name
                    for name in ("transient", "pending", "persistent", "deleted", "detached")
                    if getattr(info, name)
                )


            draft = Genre(name="poetry")
            states = [("new object", state_of(draft))]
            with ShopSession() as session:
                session.add(draft)
                states.append(("after add", state_of(draft)))
                session.flush()
                states.append(("after flush", state_of(draft)))
                session.delete(draft)
                session.flush()
                states.append(("after delete + flush", state_of(draft)))
                session.rollback()
                states.append(("after rollback", state_of(draft)))
            states.append(("session closed", state_of(draft)))
            print(states)
            '''
        ),
        md(
            """
            **`flush` vs `commit`.** A flush is not durable: rolling back removes flushed rows.
            After a commit the session *expires* every object, so the next attribute access
            reloads it (one `SELECT`); `expire_on_commit=False` keeps the loaded values, which
            is what an API that builds its response after committing wants:
            """
        ),
        code(
            r"""
            with ShopSession() as session:
                session.add(Genre(name="mystery"))
                session.flush()
                print(
                    "flushed, same transaction sees it:",
                    session.scalar(select(func.count()).where(Genre.name == "mystery")),
                )
                session.rollback()
                print("after rollback:", session.scalar(select(func.count()).where(Genre.name == "mystery")))

            for expire in (True, False):
                with sessionmaker(shop_engine, expire_on_commit=expire)() as session:
                    book = session.get(Book, 1)
                    session.commit()
                    with SqlRecorder(shop_engine) as recorded:
                        _ = book.title
                    print(
                        f"expire_on_commit={expire}: reading book.title after commit sent "
                        f"{len(recorded.statements)} statement(s)"
                    )
            """
        ),
    ]


def _query_cells() -> list[NotebookNode]:
    """6.4.6 Querying."""
    return [
        md(
            """
            ### 6.4.6 Querying

            Everything is a `select()` (or `insert` / `update` / `delete`) built from model
            attributes and run by the session. How results come back:

            | Call | Returns |
            | --- | --- |
            | `session.scalars(stmt).all()` | the first column of each row (usually objects) |
            | `session.execute(stmt).all()` | `Row` tuples (several columns) |
            | `.one()` / `.one_or_none()` / `.first()` | exactly one / at most one / the first |
            | `session.scalar(stmt)` | the first column of the first row |
            | `session.get(Model, key)` | by primary key, using the identity map first |

            Each demo prints the SQL it sent. **Filter, sort, limit:**
            """
        ),
        code(
            r"""
            with ShopSession() as session, SqlRecorder(shop_engine) as recorded:
                cheap = session.scalars(
                    select(Book).where(Book.price_paise < 25000).order_by(Book.price_paise)
                ).all()
                print([(book.title, book.price_paise) for book in cheap])
                in_title = session.scalars(
                    select(Book.title).where(Book.title.icontains("tea") | Book.title.startswith("Em"))
                ).all()
                print(in_title)
            recorded.show()
            """
        ),
        md(
            """
            **Joins.** `join(Book.author)` uses the relationship to write the `ON` clause;
            joining through `Book.genres` goes through the association table:
            """
        ),
        code(
            r"""
            with ShopSession() as session, SqlRecorder(shop_engine) as recorded:
                indian = session.execute(
                    select(Book.title, Author.name)
                    .join(Book.author)
                    .where(Author.country == "India")
                    .order_by(Book.title)
                ).all()
                print(indian)
                classics = session.scalars(
                    select(Book.title).join(Book.genres).where(Genre.name == "classic").order_by(Book.title)
                ).all()
                print(classics)
            recorded.show()
            """
        ),
        md(
            """
            **Aggregates.** `func.count`, `func.avg`, `group_by` and `having`; an outer join keeps
            authors without books (count 0):
            """
        ),
        code(
            r"""
            with ShopSession() as session, SqlRecorder(shop_engine) as recorded:
                per_author = session.execute(
                    select(
                        Author.name,
                        func.count(Book.id).label("books"),
                        func.coalesce(func.avg(Book.price_paise), 0).label("average"),
                    )
                    .outerjoin(Author.books)
                    .group_by(Author.id)
                    .order_by(Author.name)
                ).all()
                print([(name, books, round(average)) for name, books, average in per_author])
                busy = session.scalars(
                    select(Author.name)
                    .join(Author.books)
                    .group_by(Author.id)
                    .having(func.count(Book.id) >= 2)
                    .order_by(Author.name)
                ).all()
                print(f"{busy=}")
            recorded.show(170)
            """
        ),
        md(
            """
            **Subqueries.** A *scalar* subquery (one value, here the average price); a
            *correlated* one (evaluated per outer row: each book's best rating); and `EXISTS`
            (authors without books):
            """
        ),
        code(
            r"""
            with ShopSession() as session, SqlRecorder(shop_engine) as recorded:
                average_price = select(func.avg(Book.price_paise)).scalar_subquery()
                pricey = session.scalars(
                    select(Book.title).where(Book.price_paise > average_price).order_by(Book.title)
                ).all()
                best_stars = (
                    select(func.max(Review.stars))
                    .where(Review.book_id == Book.id)
                    .correlate(Book)
                    .scalar_subquery()
                )
                ratings = session.execute(select(Book.title, best_stars.label("best")).order_by(Book.id)).all()
                idle = session.scalars(
                    select(Author.name).where(~sa.exists().where(Book.author_id == Author.id))
                ).all()
            print(f"{pricey=}\n{ratings=}\n{idle=}")
            recorded.show(170)
            """
        ),
        md(
            """
            **`update` and `delete` statements** change many rows in one statement without
            loading them (the result's `rowcount` says how many). The expression
            `Book.price_paise * 9 // 10` (integer division) runs in the database:
            """
        ),
        code(
            r"""
            with ShopSession.begin() as session, SqlRecorder(shop_engine) as recorded:
                discounted = session.execute(
                    update(Book).where(Book.author_id == 3).values(price_paise=Book.price_paise * 9 // 10)
                )
                removed = session.execute(delete(Review).where(Review.stars <= 1))
                print(f"{discounted.rowcount=}  {removed.rowcount=}")
            recorded.show()
            with ShopSession() as session:
                print(session.execute(select(Book.title, Book.price_paise).where(Book.author_id == 3)).all())
            """
        ),
        md(
            """
            **Bulk inserts.** `session.execute(insert(Model), list_of_dicts)` sends one
            `executemany` without creating objects; `add_all` of objects goes through the
            unit of work (identity map, events, defaults per object). Timings vary; the gap is
            what matters:
            """
        ),
        code(
            r"""
            review_rows = [{"book_id": 1 + number % 6, "stars": 1 + number % 5} for number in range(5000)]
            with ShopSession() as session:
                started = time.perf_counter()
                session.execute(insert(Review), review_rows)
                bulk_seconds = time.perf_counter() - started
                started = time.perf_counter()
                session.add_all(Review(**row) for row in review_rows)
                session.flush()
                orm_seconds = time.perf_counter() - started
                session.rollback()
            print(
                f"insert() with 5000 dicts: {bulk_seconds * 1000:.0f} ms   "
                f"add_all of 5000 objects: {orm_seconds * 1000:.0f} ms"
            )
            """
        ),
    ]


def _loading_cells() -> list[NotebookNode]:
    """6.4.7 Loading strategies."""
    return [
        md(
            """
            ### 6.4.7 Loading strategies

            Relationships load **lazily** by default: `author.books` sends a `SELECT` the first
            time you touch it. In a loop over N authors that is 1 query for the authors plus N
            for their books: the **N+1 problem**, invisible in tests with three rows and
            painful in production with three thousand.

            | Strategy | SQL | Use for |
            | --- | --- | --- |
            | `lazyload` (default) | one `SELECT` per object, on first access | rarely touched relationships, sync code only |
            | `selectinload` | one extra `SELECT ... WHERE id IN (...)` per relationship | collections (one-to-many, many-to-many) |
            | `joinedload` | a `LEFT OUTER JOIN` in the same query | many-to-one (`Book.author`) |
            | `raiseload` / `lazy="raise"` | none: touching it raises | forbidding accidental lazy loads (and async code, where lazy loads cannot work) |

            **Detect it with SQL echo.** An engine with `echo=True` logs every statement (this
            notebook's handler prints them as `SQL:` lines without timings). Listing each
            author's books, the naive way:
            """
        ),
        code(
            r"""
            echo_engine = create_engine(f"sqlite:///{SHOP_DB}", echo=True)
            EchoSession = sessionmaker(echo_engine)
            with EchoSession() as session:
                authors = session.scalars(select(Author).order_by(Author.id)).all()
                for author in authors:
                    print(f"{author.name}: {[book.title for book in author.books]}")  # lazy load per author
            """
        ),
        md(
            """
            Four authors, five `SELECT`s (each `SQL: (...)` line holds the parameters of the
            statement above it). **Fix it with `selectinload`**: two statements whatever the
            number of authors:
            """
        ),
        code(
            r"""
            with EchoSession() as session:
                authors = session.scalars(
                    select(Author).options(selectinload(Author.books)).order_by(Author.id)
                ).all()
                print({author.name: len(author.books) for author in authors})
            """
        ),
        md(
            """
            **`joinedload`** adds a join instead. For a *collection* the joined rows repeat
            each author, so SQLAlchemy 2.x requires `.unique()` on the result; for a
            many-to-one (`Book.author`) it is the natural choice:
            """
        ),
        code(
            r"""
            with EchoSession() as session:
                books = session.scalars(
                    select(Book).options(joinedload(Book.author)).order_by(Book.id).limit(3)
                ).all()
                print([(book.title, book.author.name) for book in books])
            with ShopSession() as session:
                print(
                    raised_message(
                        lambda: session.scalars(select(Author).options(joinedload(Author.books))).all()
                    )[:120]
                )
                print(
                    len(session.scalars(select(Author).options(joinedload(Author.books))).unique().all()),
                    "authors with .unique()",
                )
            """
        ),
        md(
            """
            Counting statements per strategy for the same job (titles and genres of every
            book, with their author), using `SqlRecorder` instead of echo:
            """
        ),
        code(
            r'''
            def books_report(options: list[Any]) -> int:
                """Statements needed to print every book with its author and genres."""
                with ShopSession() as session, SqlRecorder(shop_engine) as recorded:
                    for book in session.scalars(select(Book).options(*options).order_by(Book.id)):
                        _ = (book.title, book.author.name, [genre.name for genre in book.genres])
                return len(recorded.statements)


            strategies = {
                "lazy (default)": [],
                "selectinload both": [selectinload(Book.author), selectinload(Book.genres)],
                "joinedload author + selectinload genres": [joinedload(Book.author), selectinload(Book.genres)],
            }
            for label, options in strategies.items():
                print(f"{label:40} {books_report(options):2} statements")
            '''
        ),
        md(
            """
            **`raiseload`: make N+1 impossible.** `options(raiseload("*"))` turns every lazy
            load of that query into an error; `relationship(lazy="raise")` makes it the
            model's default (the Notes API does this for `Note.tag_objects`). A missing
            `selectinload` then fails loudly in the first test instead of slowly in
            production:
            """
        ),
        code(
            r"""
            with ShopSession() as session:
                strict_author = session.scalars(
                    select(Author).options(raiseload("*")).where(Author.id == 1)
                ).one()
                print(raised_message(lambda: strict_author.books))
                allowed = session.scalars(
                    select(Author).options(selectinload(Author.books), raiseload("*")).where(Author.id == 2)
                ).one()
                print([book.title for book in allowed.books], "(loaded up front, so allowed)")
            """
        ),
    ]


def _async_cells() -> list[NotebookNode]:
    """6.4.8 Async SQLAlchemy."""
    return [
        md(
            """
            ### 6.4.8 Async SQLAlchemy

            The same models and queries work with asyncio: `create_async_engine` (with an async
            driver: `postgresql+asyncpg`, `sqlite+aiosqlite`), `async_sessionmaker`,
            `AsyncSession`, and `await` in front of everything that talks to the database.
            Underneath, SQLAlchemy runs its (sync) ORM inside greenlets, which is why
            `sqlalchemy[asyncio]` installs `greenlet`.

            | Sync | Async |
            | --- | --- |
            | `create_engine(url)` | `create_async_engine(url)` |
            | `sessionmaker(engine)` | `async_sessionmaker(engine, expire_on_commit=False)` |
            | `session.scalars(stmt)` | `await session.scalars(stmt)` |
            | `metadata.create_all(engine)` | `async with engine.begin() as conn: await conn.run_sync(metadata.create_all)` |
            | `book.author` (lazy load) | not allowed: eager-load it, or `await book.awaitable_attrs.author` |

            The bookshop again, this time on PostgreSQL (SQLite through aiosqlite when Docker is
            missing). `run_sync` lets the sync `seed_shop` function from 6.4.5 run unchanged:
            """
        ),
        code(
            r'''
            ASYNC_SHOP_URL = PG_URL or f"sqlite+aiosqlite:///{PHASE6_DIR / 'bookshop_async.db'}"
            async_shop_engine = create_async_engine(ASYNC_SHOP_URL)
            AsyncShopSession = async_sessionmaker(async_shop_engine, expire_on_commit=False)


            def seed_async_shop(session: Session) -> None:
                """Asha's books first (as in 6.4.5), then everything seed_shop adds."""
                session.add(
                    Author(
                        name="Asha Rao",
                        country="India",
                        books=[
                            Book(title="Monsoon Letters", price_paise=39900),
                            Book(title="The Glass Fort", price_paise=54900),
                        ],
                    )
                )
                session.flush()
                seed_shop(session)


            async def rebuild_async_shop() -> None:
                """Drop and recreate the tables, then seed them."""
                async with async_shop_engine.begin() as connection:
                    await connection.run_sync(ShopBase.metadata.drop_all)
                    await connection.run_sync(ShopBase.metadata.create_all)
                async with AsyncShopSession.begin() as session:
                    await session.run_sync(seed_async_shop)


            await rebuild_async_shop()
            '''
        ),
        md("Rebuild and seed the async database, then load authors with their books:"),
        code(
            r"""
            async with AsyncShopSession() as session:
                authors = (
                    await session.scalars(
                        select(Author).options(selectinload(Author.books)).order_by(Author.id)
                    )
                ).all()
                print(
                    async_shop_engine.dialect.name,
                    {author.name: [book.title for book in author.books] for author in authors},
                )
            """
        ),
        md(
            """
            **No implicit I/O.** In async code a lazy load would have to block the event loop,
            so SQLAlchemy refuses with `MissingGreenlet`. Load what you need up front
            (`selectinload`), or await the attribute explicitly through `AsyncAttrs`, which the
            bookshop's base class includes:
            """
        ),
        code(
            r"""
            async with AsyncShopSession() as session:
                author = await session.scalar(select(Author).where(Author.name == "Jane Austen"))
                try:
                    _ = author.books
                except Exception as error:
                    print(f"{type(error).__name__}: {str(error)[:90]}...")
                books = await author.awaitable_attrs.books
                print("awaitable_attrs:", [book.title for book in books])
            """
        ),
        md(
            """
            **Pool sizing.** An async app can start hundreds of requests at once; the pool
            decides how many reach the database together. Twenty concurrent sessions that each
            hold a connection for 50 ms, through a pool of 5 without overflow and through a
            pool that may grow to 20 (`pool_size` + `max_overflow`):
            """
        ),
        code(
            r'''
            async def concurrent_sessions(pool_size: int, max_overflow: int) -> float:
                """Seconds for 20 sessions each running a 50 ms query."""
                engine = create_async_engine(PG_URL, pool_size=pool_size, max_overflow=max_overflow)
                factory = async_sessionmaker(engine)

                async def one_session() -> None:
                    """Hold a connection for 50 ms."""
                    async with factory() as session:
                        await session.execute(text("SELECT pg_sleep(0.05)"))

                started = time.perf_counter()
                await asyncio.gather(*(one_session() for _ in range(20)))
                elapsed = time.perf_counter() - started
                await engine.dispose()
                return elapsed


            if PG_URL:
                for size, overflow in ((5, 0), (5, 15)):
                    print(
                        f"pool_size={size}, max_overflow={overflow:2}: "
                        f"{await concurrent_sessions(size, overflow):.2f} s"
                    )
                print("server max_connections:", (await pg_fetch("SHOW max_connections"))[0][0])
            else:
                print("SKIP pool sizing: needs PostgreSQL (Docker)")
            '''
        ),
    ]


def _fastapi_db_cells() -> list[NotebookNode]:
    """6.4.9 FastAPI integration."""
    return [
        md(
            """
            ### 6.4.9 FastAPI integration

            The pattern the Notes API v3 uses, in miniature:

            | Piece | How |
            | --- | --- |
            | engine and session factory | created once in the **lifespan**, kept on `app.state` (an engine belongs to the event loop that created it) |
            | session dependency | `async with factory() as session, session.begin(): yield session`, so **one transaction per request**: commit if the handler succeeded, roll back if it raised |
            | when to commit | `Depends(get_session, scope="function")`: before the response is sent (6.3.2) |
            | repository | a class holding the session, with methods that build queries; routes never write SQL |
            | ORM → Pydantic | `model_config = ConfigDict(from_attributes=True)` reads attributes; everything the schema needs must be loaded eagerly |

            The schemas: `BookOut` flattens the author to a name and the genres to a list of
            strings with `mode="before"` validators (the input is ORM objects, the output plain
            data):
            """
        ),
        code(
            r'''
            class AuthorIn(BaseModel):
                """Body of POST /authors."""

                name: str = Field(min_length=1, max_length=100)
                country: str | None = None


            class AuthorOut(AuthorIn):
                """An author as the API returns it."""

                model_config = ConfigDict(from_attributes=True)
                id: int


            class BookOut(BaseModel):
                """A book with its author's name and its genre names."""

                model_config = ConfigDict(from_attributes=True)
                id: int
                title: str
                price_paise: int
                author: str
                genres: list[str]

                @field_validator("author", mode="before")
                @classmethod
                def author_name(cls, value: object) -> object:
                    """Accept an Author object and keep its name."""
                    return getattr(value, "name", value)

                @field_validator("genres", mode="before")
                @classmethod
                def genre_names(cls, value: object) -> object:
                    """Accept Genre objects and keep their names."""
                    return [getattr(genre, "name", genre) for genre in value]  # type: ignore[attr-defined]
            '''
        ),
        md(
            """
            The repository and the dependencies. `ShopRepository` is the only code that knows
            about SQL; its queries always eager-load what `BookOut` reads:
            """
        ),
        code(
            r'''
            class ShopRepository:
                """Bookshop queries on one request's session."""

                def __init__(self, session: AsyncSession) -> None:
                    """Use the request's session (and so its transaction)."""
                    self.session = session

                async def books(self, genre: str | None) -> list[Book]:
                    """Books with author and genres loaded, optionally of one genre."""
                    statement = (
                        select(Book)
                        .options(joinedload(Book.author), selectinload(Book.genres))
                        .order_by(Book.id)
                    )
                    if genre:
                        statement = statement.where(Book.genres.any(Genre.name == genre))
                    return list(await self.session.scalars(statement))

                async def add_author(self, data: AuthorIn) -> Author:
                    """INSERT an author; flush so the id (and constraint errors) appear now."""
                    author = Author(**data.model_dump())
                    self.session.add(author)
                    await self.session.flush()
                    return author


            async def get_shop_session(request: Request) -> AsyncIterator[AsyncSession]:
                """One session and one transaction per request."""
                async with request.app.state.session_factory() as session, session.begin():
                    yield session


            def get_shop_repository(
                session: Annotated[AsyncSession, Depends(get_shop_session, scope="function")],
            ) -> ShopRepository:
                """A repository on this request's session."""
                return ShopRepository(session)


            ShopRepositoryDep = Annotated[ShopRepository, Depends(get_shop_repository)]
            '''
        ),
        md(
            "The session dependency is an async generator, so FastAPI treats it as a context manager:"
        ),
        code(
            r"""
            print(f"{inspect.isasyncgenfunction(get_shop_session)=}")
            """
        ),
        md(
            """
            The app: the lifespan owns the engine; a duplicate author name violates
            `uq_authors_name` (raised at the `flush`), and the handler turns `IntegrityError`
            into a 409 while the session dependency rolls the transaction back:
            """
        ),
        code(
            r'''
            @contextlib.asynccontextmanager
            async def shop_lifespan(app: FastAPI) -> AsyncIterator[None]:
                """Create the engine in the app's own event loop; dispose it on shutdown."""
                engine = create_async_engine(ASYNC_SHOP_URL)
                app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
                yield
                await engine.dispose()


            shop_api = FastAPI(lifespan=shop_lifespan)


            @shop_api.exception_handler(IntegrityError)
            async def conflict_handler(request: Request, error: IntegrityError) -> JSONResponse:
                """A database constraint said no: 409, without leaking SQL."""
                return JSONResponse(
                    {"detail": "conflicts with existing data"}, status_code=status.HTTP_409_CONFLICT
                )


            @shop_api.get("/books", response_model=list[BookOut])
            async def list_shop_books(repository: ShopRepositoryDep, genre: str | None = None) -> list[Book]:
                """Books, optionally filtered by genre."""
                return await repository.books(genre)


            @shop_api.post("/authors", response_model=AuthorOut, status_code=status.HTTP_201_CREATED)
            async def create_author(data: AuthorIn, repository: ShopRepositoryDep) -> Author:
                """Create an author (names are unique)."""
                return await repository.add_author(data)


            with TestClient(shop_api) as client:
                print(client.get("/books", params={"genre": "romance"}).json())
                print(client.post("/authors", json={"name": "Kiran Desai", "country": "India"}).json())
                duplicate = client.post("/authors", json={"name": "Kiran Desai"})
                print(duplicate.status_code, duplicate.json())
            '''
        ),
        md("Two authors, a duplicate (409), and proof that the duplicate was rolled back:"),
        code(
            r"""
            async with AsyncShopSession() as session:
                print(
                    "rows named Kiran Desai:",
                    await session.scalar(select(func.count()).where(Author.name == "Kiran Desai")),
                )
            """
        ),
    ]


def _alembic_cells() -> list[NotebookNode]:
    """6.4.10 Alembic."""
    return [
        md(
            """
            ### 6.4.10 Alembic

            `create_all` creates missing tables but never changes existing ones. Real schemas
            evolve while data is in them; **migrations** are versioned scripts that move a
            database from one schema version to the next (and back). Alembic is SQLAlchemy's
            migration tool:

            | Command | Does |
            | --- | --- |
            | `alembic init -t async migrations` | creates `alembic.ini`, `migrations/env.py` (how to connect), `script.py.mako` (the template), `versions/` |
            | `alembic revision --autogenerate -m "..."` | compares the models (`target_metadata`) with the database and **drafts** a migration |
            | `alembic upgrade head` / `downgrade -1` | applies / reverts migrations; the current revision lives in the `alembic_version` table |
            | `alembic current`, `history`, `check` | where the database is, the chain of revisions, "do the models need a migration?" |

            Autogenerate sees new and dropped tables, columns, indexes, unique and foreign keys,
            nullability and (by default) type changes. It **cannot** see renames (a renamed
            column looks like drop + add, which loses the data), data changes, or most
            `CHECK` constraints and server defaults. So: generate, **review and edit**, then
            run.

            The demo works on its own folder in the scratch area and a SQLite file. First,
            `alembic init` with the async template:
            """
        ),
        code(
            r'''
            ALEMBIC_DEMO = PHASE6_DIR / "alembic_demo"
            shutil.rmtree(ALEMBIC_DEMO, ignore_errors=True)
            ALEMBIC_DEMO.mkdir()


            def alembic_cli(*arguments: str) -> str:
                """Run alembic in the demo folder; return its output without paths."""
                run = subprocess.run(
                    [sys.executable, "-m", "alembic", *arguments],
                    cwd=ALEMBIC_DEMO,
                    capture_output=True,
                    text=True,
                    env=CHILD_ENV,
                    timeout=120,
                )
                output = (run.stdout + run.stderr).replace(str(ALEMBIC_DEMO), "<demo>")
                lines = [re.sub(r"INFO  \[alembic\.\S+\] ", "", line) for line in output.splitlines()]
                noise = ("Context impl", "Will assume", "setting up autogenerate plugin")
                return "\n".join(line for line in lines if not line.startswith(noise)).strip()


            print(alembic_cli("init", "-t", "async", "migrations"))
            print(
                sorted(
                    str(path.relative_to(ALEMBIC_DEMO)) for path in ALEMBIC_DEMO.rglob("*") if path.is_file()
                )
            )
            '''
        ),
        md(
            """
            Configure it: the database URL and readable file names in `alembic.ini`, and the
            models' metadata in `env.py` (the template has `target_metadata = None`; with a
            SQLite database, `render_as_batch=True` lets Alembic alter tables by copying them).
            The models live in `shop_models.py`, version 1:
            """
        ),
        code(
            r"""
            ini_path = ALEMBIC_DEMO / "alembic.ini"
            ini_text = ini_path.read_text(encoding="utf-8")
            ini_text = re.sub(
                r"(?m)^sqlalchemy\.url = .*$",
                f"sqlalchemy.url = sqlite+aiosqlite:///{ALEMBIC_DEMO / 'shop.db'}",
                ini_text,
            )
            ini_text = re.sub(
                r"(?m)^# file_template = .*$", "file_template = %%(rev)s_%%(slug)s", ini_text, count=1
            )
            ini_path.write_text(ini_text, encoding="utf-8")
            env_path = ALEMBIC_DEMO / "migrations" / "env.py"
            env_text = env_path.read_text(encoding="utf-8").replace(
                "target_metadata = None", "import shop_models\n\ntarget_metadata = shop_models.Base.metadata"
            )
            env_text = env_text.replace(
                "connection=connection, target_metadata=target_metadata",
                "connection=connection, target_metadata=target_metadata, render_as_batch=True",
            )
            env_path.write_text(env_text, encoding="utf-8")
            print(
                [
                    line
                    for line in env_text.splitlines()
                    if "target_metadata" in line or "render_as_batch" in line
                ]
            )
            """
        ),
        md("The models, version 1 (written by the next cell):"),
        code(
            r'''
            %%writefile _scratch/phase6/alembic_demo/shop_models.py
            """Models for the Alembic demo."""

            from sqlalchemy import ForeignKey, MetaData, String
            from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

            NAMING = {"ix": "ix_%(column_0_label)s", "uq": "uq_%(table_name)s_%(column_0_name)s", "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s", "pk": "pk_%(table_name)s"}


            class Base(DeclarativeBase):
                """Shared metadata with a naming convention."""

                metadata = MetaData(naming_convention=NAMING)


            class Author(Base):
                """An author."""

                __tablename__ = "authors"
                id: Mapped[int] = mapped_column(primary_key=True)
                name: Mapped[str] = mapped_column(String(100), unique=True)


            class Book(Base):
                """A book."""

                __tablename__ = "books"
                id: Mapped[int] = mapped_column(primary_key=True)
                title: Mapped[str] = mapped_column(String(200))
                price: Mapped[int]
                author_id: Mapped[int] = mapped_column(ForeignKey("authors.id"))
            '''
        ),
        md(
            """
            **Autogenerate, then review.** `--rev-id 0001` gives a readable revision id instead
            of a random one. Read the generated `upgrade()` like a code review: are the tables,
            constraints and names what you meant?
            """
        ),
        code(
            r'''
            def migration_body(revision: str, function: str = "upgrade") -> str:
                """The body of upgrade() or downgrade() in a generated migration file."""
                path = next((ALEMBIC_DEMO / "migrations" / "versions").glob(f"{revision}_*.py"))
                source = path.read_text(encoding="utf-8")
                return re.search(rf"def {function}\(\) -> None:\n(.*?)(?=\n\ndef |\Z)", source, re.S)[
                    1
                ].rstrip()


            print(
                alembic_cli("revision", "--autogenerate", "-m", "create authors and books", "--rev-id", "0001")
            )
            print(migration_body("0001"))
            '''
        ),
        md("Apply it, and ask Alembic where the database is:"),
        code(
            r"""
            print(alembic_cli("upgrade", "head"))
            print("current:", alembic_cli("current"))
            demo_inspector = sa_inspect(create_engine(f"sqlite:///{ALEMBIC_DEMO / 'shop.db'}"))
            print(
                sorted(demo_inspector.get_table_names()),
                [column["name"] for column in demo_inspector.get_columns("books")],
            )
            """
        ),
        md(
            """
            **A second migration.** Version 2 of the models adds a nullable `published_on`
            column and an index on `title`. Autogenerate finds both; on SQLite it wraps them in
            `batch_alter_table`:
            """
        ),
        code(
            r"""
            models_path = ALEMBIC_DEMO / "shop_models.py"
            models_v2 = models_path.read_text(encoding="utf-8").replace(
                "    title: Mapped[str] = mapped_column(String(200))\n",
                "    title: Mapped[str] = mapped_column(String(200), index=True)\n"
                "    published_on: Mapped[str | None] = mapped_column(String(10))\n",
            )
            models_path.write_text(models_v2, encoding="utf-8")
            print(
                alembic_cli(
                    "revision", "--autogenerate", "-m", "add published_on and title index", "--rev-id", "0002"
                )
            )
            print(migration_body("0002"))
            print(alembic_cli("upgrade", "head"))
            """
        ),
        md(
            """
            **A data migration** is written by hand: add a `slug` column, fill it from the
            titles with SQL run through `op.get_bind()`, then make it `NOT NULL` and unique. It
            uses a lightweight `sa.table()` description, never the current models, because a
            migration must keep working after the models change again:
            """
        ),
        code(
            r'''
            %%writefile _scratch/phase6/alembic_demo/migrations/versions/0003_book_slugs.py
            """Add books.slug, computed from the titles.

            Revision ID: 0003
            Revises: 0002
            """

            import re

            import sqlalchemy as sa
            from alembic import op

            revision = "0003"
            down_revision = "0002"
            branch_labels = None
            depends_on = None

            books = sa.table("books", sa.column("id", sa.Integer()), sa.column("title", sa.String()), sa.column("slug", sa.String()))


            def upgrade() -> None:
                """Expand, fill, then tighten."""
                op.add_column("books", sa.Column("slug", sa.String(220), nullable=True))
                connection = op.get_bind()
                for book_id, title in connection.execute(sa.select(books.c.id, books.c.title)).all():
                    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") + f"-{book_id}"
                    connection.execute(books.update().where(books.c.id == book_id).values(slug=slug))
                with op.batch_alter_table("books") as batch:
                    batch.alter_column("slug", nullable=False)
                    batch.create_unique_constraint("uq_books_slug", ["slug"])


            def downgrade() -> None:
                """Drop the column (the slugs can be recomputed)."""
                with op.batch_alter_table("books") as batch:
                    batch.drop_constraint("uq_books_slug", type_="unique")
                    batch.drop_column("slug")
            '''
        ),
        md(
            """
            Put some rows in, run the data migration, look at the result; then step back one
            revision and forward again (downgrades must work, or a bad deploy cannot be rolled
            back):
            """
        ),
        code(
            r"""
            demo_engine = create_engine(f"sqlite:///{ALEMBIC_DEMO / 'shop.db'}")
            with demo_engine.begin() as connection:
                connection.execute(text("INSERT INTO authors (id, name) VALUES (1, 'Jane Austen')"))
                connection.execute(
                    text(
                        "INSERT INTO books (title, price, author_id)"
                        " VALUES ('Pride and Prejudice', 24900, 1), ('Emma', 19900, 1)"
                    )
                )
            print(alembic_cli("upgrade", "head"))
            with demo_engine.connect() as connection:
                print(connection.execute(text("SELECT id, slug FROM books ORDER BY id")).all())
            print(alembic_cli("downgrade", "-1"))
            print("current:", alembic_cli("current"))
            print(alembic_cli("upgrade", "head"))
            print(alembic_cli("history"))
            """
        ),
        md(
            """
            **Expand / contract.** Renaming `price` to `price_paise` in one migration would
            break every running copy of the old app the moment it runs. Zero-downtime changes
            go in phases, each deployable on its own:

            | Phase | Migration | App code |
            | --- | --- | --- |
            | 1. expand | add `price_paise` (nullable), copy the data | writes **both** columns, reads the old one |
            | 2. migrate | (backfill rows written meanwhile) | reads the **new** column |
            | 3. contract | drop `price` | uses only `price_paise` |

            The demo runs the expand and the contract migrations back to back (in production,
            at least one deploy sits between them):
            """
        ),
        code(
            r'''
            def migration_source(revision: str, previous: str, upgrade: list[str], downgrade: list[str]) -> str:
                """A minimal migration module built from lines of code."""
                header = [
                    f'"""Expand/contract step {revision}."""',
                    "",
                    "import sqlalchemy as sa",
                    "from alembic import op",
                    "",
                ]
                header += [
                    f'revision = "{revision}"',
                    f'down_revision = "{previous}"',
                    "branch_labels = None",
                    "depends_on = None",
                ]
                upgrade_part = [
                    "",
                    "",
                    "def upgrade() -> None:",
                    '    """Apply."""',
                    *(f"    {line}" for line in upgrade),
                ]
                downgrade_part = [
                    "",
                    "",
                    "def downgrade() -> None:",
                    '    """Revert."""',
                    *(f"    {line}" for line in downgrade),
                ]
                return "\n".join(header + upgrade_part + downgrade_part) + "\n"


            EXPAND = (
                [
                    "op.add_column('books', sa.Column('price_paise', sa.Integer(), nullable=True))",
                    "op.execute('UPDATE books SET price_paise = price')",
                ],
                ["op.drop_column('books', 'price_paise')"],
            )
            '''
        ),
        md(
            "The two steps as lines of code, written as migrations 0004 (expand) and 0005 (contract):"
        ),
        code(
            r"""
            CONTRACT = (
                ["with op.batch_alter_table('books') as batch:", "    batch.drop_column('price')"],
                [
                    "op.add_column('books', sa.Column('price', sa.Integer(), nullable=True))",
                    "op.execute('UPDATE books SET price = price_paise')",
                ],
            )
            demo_versions = ALEMBIC_DEMO / "migrations" / "versions"
            (demo_versions / "0004_expand_price_paise.py").write_text(
                migration_source("0004", "0003", *EXPAND), encoding="utf-8"
            )
            (demo_versions / "0005_contract_price.py").write_text(
                migration_source("0005", "0004", *CONTRACT), encoding="utf-8"
            )
            print(migration_source("0004", "0003", *EXPAND).split("def upgrade")[1].strip())
            """
        ),
        md("Run the expand step, then the contract step, looking at the columns after each:"),
        code(
            r"""
            for target in ("0004", "0005"):
                alembic_cli("upgrade", target)
                with demo_engine.connect() as connection:
                    columns = [column["name"] for column in sa_inspect(connection).get_columns("books")]
                    prices = connection.execute(text("SELECT title, price_paise FROM books ORDER BY id")).all()
                print(f"after {target}: {columns}\n    {prices}")
            demo_engine.dispose()
            """
        ),
    ]


def _concurrency_cells() -> list[NotebookNode]:
    """6.4.11 Concurrency control."""
    return [
        md(
            """
            ### 6.4.11 Concurrency control

            Two requests read the same row, both change it, both write: the second write
            silently overwrites the first. This **lost update** is the classic concurrency bug
            of read-modify-write code.

            | Technique | How | Cost | Use when |
            | --- | --- | --- | --- |
            | atomic `UPDATE` | `SET stock = stock - 3 WHERE stock >= 3` | none | the change fits in one statement |
            | optimistic locking | a `version` column; `UPDATE ... WHERE id = ? AND version = ?`; 0 rows → conflict | a retry (or a 409 for the client) | conflicts are rare; users edit documents |
            | pessimistic locking | `SELECT ... FOR UPDATE` locks the row until commit | others wait | conflicts are frequent; short transactions (stock, money) |
            | constraints | `UNIQUE`, `CHECK`; the loser gets `IntegrityError` | a retry or a 409 | "only one" rules |

            The lost update, reproduced with two sessions on the SQLite bookshop (a stock table
            without a version column):
            """
        ),
        code(
            r'''
            class PlainStock(ShopBase):
                """Stock without any protection."""

                __tablename__ = "plain_stock"
                id: Mapped[int] = mapped_column(primary_key=True)
                quantity: Mapped[int]


            class VersionedStock(ShopBase):
                """Stock with optimistic locking: version_id_col."""

                __tablename__ = "versioned_stock"
                id: Mapped[int] = mapped_column(primary_key=True)
                quantity: Mapped[int]
                version: Mapped[int] = mapped_column(server_default=text("1"))
                __mapper_args__ = {"version_id_col": version}


            def two_buyers(model: type[ShopBase]) -> str:
                """Two sessions both read 10 and both sell 3."""
                model.__table__.drop(shop_engine, checkfirst=True)
                model.__table__.create(shop_engine)
                with ShopSession.begin() as session:
                    session.add(model(id=1, quantity=10))
                with ShopSession() as first, ShopSession() as second:
                    first_stock, second_stock = first.get(model, 1), second.get(model, 1)
                    first_stock.quantity -= 3
                    second_stock.quantity -= 3
                    first.commit()
                    try:
                        second.commit()
                    except StaleDataError as error:
                        return f"second buyer: StaleDataError ({str(error)[:60]}...) → retry or answer 409"
                with ShopSession() as session:
                    return f"final quantity {session.get(model, 1).quantity} (expected 4: one sale was lost)"


            print("no protection:      ", two_buyers(PlainStock))
            '''
        ),
        md(
            """
            **Optimistic locking** with `__mapper_args__ = {"version_id_col": version}`: every
            `UPDATE` checks and bumps the version, so the second buyer's write matches no row
            and SQLAlchemy raises `StaleDataError`. The Notes API maps this to a 409 Problem
            Details response:
            """
        ),
        code(
            r"""
            print("optimistic locking: ", two_buyers(VersionedStock))
            with ShopSession() as session, SqlRecorder(shop_engine) as recorded:
                stock = session.get(VersionedStock, 1)
                stock.quantity -= 1
                session.commit()
            recorded.show()
            """
        ),
        md(
            """
            **Pessimistic locking** with `select(...).with_for_update()` on PostgreSQL: the
            first transaction locks the row; the second one's `SELECT ... FOR UPDATE` **waits**
            until the first commits, then reads the new value, so nothing is lost.
            `with_for_update(skip_locked=True)` returns only unlocked rows instead of waiting,
            the standard trick for job queues where several workers take jobs from one table.
            (The waits below are rounded measurements.)
            """
        ),
        code(
            r'''
            async def locked_purchase(
                label: str, start_delay: float, hold_seconds: float, log: list[str]
            ) -> None:
                """Lock the stock row, wait a little, sell 3, commit."""
                await asyncio.sleep(start_delay)  # makes the order of the two buyers deterministic
                async with AsyncShopSession.begin() as session:
                    started = time.perf_counter()
                    stock = await session.scalar(select(PlainStock).where(PlainStock.id == 1).with_for_update())
                    waited = time.perf_counter() - started
                    log.append(f"{label}: got the lock after {waited:.1f} s, saw quantity {stock.quantity}")
                    await asyncio.sleep(hold_seconds)
                    stock.quantity -= 3


            async def pessimistic_demo() -> None:
                """Two concurrent purchases, then a skip_locked peek."""
                async with async_shop_engine.begin() as connection:
                    await connection.run_sync(PlainStock.__table__.drop, checkfirst=True)
                    await connection.run_sync(PlainStock.__table__.create)
                async with AsyncShopSession.begin() as session:
                    session.add(PlainStock(id=1, quantity=10))
                log: list[str] = []
                await asyncio.gather(
                    locked_purchase("first ", 0.0, 0.3, log), locked_purchase("second", 0.05, 0.0, log)
                )
                print(*log, sep="\n")
                async with AsyncShopSession() as session:
                    print("final quantity:", (await session.get(PlainStock, 1)).quantity)


            if PG_URL:
                await pessimistic_demo()
            else:
                print("SKIP SELECT ... FOR UPDATE: needs PostgreSQL (Docker); SQLite locks the whole database")
            '''
        ),
        md("`skip_locked`: while one session holds the row, a second one simply does not see it:"),
        code(
            r'''
            async def skip_locked_demo() -> None:
                """A worker skips a job another worker has locked."""
                async with AsyncShopSession() as holder, AsyncShopSession() as worker:
                    async with holder.begin(), worker.begin():
                        await holder.scalar(select(PlainStock).with_for_update())
                        free_rows = (
                            await worker.scalars(select(PlainStock).with_for_update(skip_locked=True))
                        ).all()
                        print(f"rows the second worker can take: {free_rows}")


            if PG_URL:
                await skip_locked_demo()
            else:
                print("SKIP skip_locked: needs PostgreSQL (Docker)")
            '''
        ),
        md(
            """
            **Savepoints.** A failed statement poisons the whole transaction (PostgreSQL then
            rejects everything until a rollback). `session.begin_nested()` opens a
            **SAVEPOINT**: if the block fails, only that part is rolled back and the outer
            transaction continues. Importing a list where some names already exist:
            """
        ),
        code(
            r'''
            async def import_authors(names: list[str]) -> dict[str, list[str]]:
                """Insert each author in its own savepoint; skip the duplicates."""
                report: dict[str, list[str]] = {"imported": [], "skipped": []}
                async with AsyncShopSession.begin() as session:
                    for name in names:
                        try:
                            async with session.begin_nested():
                                session.add(Author(name=name))
                            report["imported"].append(name)
                        except IntegrityError:
                            report["skipped"].append(name)
                return report


            print(await import_authors(["Arundhati Roy", "Jane Austen", "Vikram Seth", "Ravi Menon"]))
            async with AsyncShopSession() as session:
                print(sorted((await session.scalars(select(Author.name))).all()))
            '''
        ),
        md(
            """
            `IntegrityError` → 409 was shown in 6.4.9 (`POST /authors` twice). The Notes API
            uses all of these: a `version` column for notes (409 on a stale `PATCH`), a unique
            tag name with a savepoint for the "two requests create the same new tag" race, and
            a generic `IntegrityError` handler as a safety net.
            """
        ),
    ]


def _alternatives_cells() -> list[NotebookNode]:
    """6.4.12 Alternatives."""
    return [
        md(
            """
            ### 6.4.12 Alternatives

            | Option | What it is | Choose it when |
            | --- | --- | --- |
            | **SQLModel** | Pydantic + SQLAlchemy in one class (by FastAPI's author) | small CRUD apps where one model can be table, input and output |
            | **raw asyncpg** | SQL strings and the driver | hot paths, bulk loads (`COPY`), when the ORM is in the way |
            | **document databases** (MongoDB with Motor/PyMongo, DynamoDB) | JSON documents, flexible schema | data that really is document-shaped, few cross-document queries |
            | **PostgreSQL `JSONB`** | documents inside a relational database, indexable | flexible attributes next to relational data |
            | **Redis** | in-memory data structures with persistence options | caches, counters, rate limits, queues, leaderboards (Unit 6.6) |

            SQLModel is not a course dependency, so its cell only checks for it:
            """
        ),
        code(
            r"""
            if importlib.util.find_spec("sqlmodel") is None:
                print("SKIP SQLModel: not installed (not a course dependency). The same Book would be:")
                print(
                    "    class Book(SQLModel, table=True):\n"
                    "        id: int | None = Field(default=None, primary_key=True)\n"
                    "        title: str = Field(index=True)"
                )
            else:
                import sqlmodel

                print(f"sqlmodel {sqlmodel.__version__} is installed")
            """
        ),
        md(
            """
            **Raw asyncpg for bulk loads.** `copy_records_to_table` uses PostgreSQL's `COPY`
            protocol, much faster than row-by-row `INSERT`s (`executemany`). 20 000 rows each
            way; timings vary:
            """
        ),
        code(
            r'''
            async def bulk_load_demo() -> None:
                """executemany vs COPY for the same rows."""
                rows = [
                    (number, f"sensor-{number % 50}", random.Random(number).random())
                    for number in range(20_000)
                ]
                connection = await asyncpg.connect(PG_DSN)
                try:
                    await connection.execute(
                        "DROP TABLE IF EXISTS readings;"
                        " CREATE TABLE readings (id int, sensor text, value float8)"
                    )
                    started = time.perf_counter()
                    await connection.executemany("INSERT INTO readings VALUES ($1, $2, $3)", rows)
                    insert_seconds = time.perf_counter() - started
                    await connection.execute("TRUNCATE readings")
                    started = time.perf_counter()
                    await connection.copy_records_to_table(
                        "readings", records=rows, columns=["id", "sensor", "value"]
                    )
                    copy_seconds = time.perf_counter() - started
                    count = await connection.fetchval("SELECT count(*) FROM readings")
                finally:
                    await connection.close()
                print(f"{count} rows; executemany {insert_seconds:.2f} s, COPY {copy_seconds:.3f} s")


            if PG_DSN:
                await bulk_load_demo()
            else:
                print("SKIP asyncpg COPY: needs PostgreSQL (Docker)")
            '''
        ),
        md(
            """
            **Documents in PostgreSQL.** A `JSONB` column stores parsed JSON; `->>` extracts a
            field as text, `@>` asks "does the document contain this", and a GIN index makes
            containment queries fast. Often this is enough to avoid a second database:
            """
        ),
        code(
            r'''
            async def jsonb_demo() -> None:
                """Store order events as documents and query inside them."""
                events = [
                    {"type": "order", "city": "Pune", "items": 3},
                    {"type": "refund", "city": "Goa"},
                    {"type": "order", "city": "Goa", "items": 1},
                ]
                await pg_fetch("DROP TABLE IF EXISTS events")
                await pg_fetch("CREATE TABLE events (id serial PRIMARY KEY, doc jsonb NOT NULL)")
                await pg_fetch("CREATE INDEX ix_events_doc ON events USING gin (doc)")
                for event_document in events:
                    await pg_fetch("INSERT INTO events (doc) VALUES ($1::jsonb)", json.dumps(event_document))
                orders = await pg_fetch(
                    "SELECT doc->>'city' AS city, (doc->>'items')::int AS items FROM events"
                    """ WHERE doc @> '{"type": "order"}' ORDER BY id"""
                )
                print([dict(row) for row in orders])


            if PG_DSN:
                await jsonb_demo()
            else:
                print("SKIP JSONB: needs PostgreSQL (Docker)")
            '''
        ),
        md(
            """
            **Redis data types.** Redis keeps data structures in memory, each with its own
            commands. The cell starts a Redis container, tries one command family per type
            with `redis.asyncio`, and always removes the container (with fakeredis as the
            fallback when Docker is missing and fakeredis is installed):

            | Type | Commands | Typical use |
            | --- | --- | --- |
            | string | `SET`, `GET`, `INCR`, `EXPIRE` | caches, counters, rate limits |
            | hash | `HSET`, `HGETALL` | an object's fields |
            | list | `LPUSH`, `RPOP` | simple queues |
            | set | `SADD`, `SINTER` | tags, unique visitors |
            | sorted set | `ZINCRBY`, `ZREVRANGE` | leaderboards, priority queues |
            """
        ),
        code(
            r'''
            import redis.asyncio as redis_asyncio


            async def redis_tour(client: redis_asyncio.Redis) -> None:
                """One example per data type."""
                await client.set("page:views", 0, ex=60)
                await client.incr("page:views", 3)
                print(
                    "string:",
                    await client.get("page:views"),
                    "ttl ≤ 60:",
                    0 < await client.ttl("page:views") <= 60,
                )
                await client.hset("book:1", mapping={"title": "Emma", "author": "Jane Austen"})
                print("hash:", await client.hgetall("book:1"))
                await client.lpush("jobs", "send-email", "resize-image")
                print("list (queue):", await client.rpop("jobs"), await client.rpop("jobs"))
                await client.sadd("tags:emma", "classic", "romance")
                await client.sadd("tags:persuasion", "classic")
                print("set intersection:", await client.sinter("tags:emma", "tags:persuasion"))
                for player, points in (("asha", 30), ("ravi", 45), ("asha", 20)):
                    await client.zincrby("leaderboard", points, player)
                print("sorted set:", await client.zrevrange("leaderboard", 0, -1, withscores=True))
            '''
        ),
        md("Start Redis in Docker for this cell only, take the tour, remove the container:"),
        code(
            r"""
            if HAS_DOCKER:
                from testcontainers.community.redis import RedisContainer

                with RedisContainer(REDIS_IMAGE) as redis_container:
                    redis_client = redis_asyncio.Redis(
                        host=redis_container.get_container_host_ip(),
                        port=int(redis_container.get_exposed_port(6379)),
                        decode_responses=True,
                    )
                    await redis_tour(redis_client)
                    await redis_client.aclose()
            elif importlib.util.find_spec("fakeredis"):
                import fakeredis

                await redis_tour(fakeredis.FakeAsyncRedis(decode_responses=True))
            else:
                print("SKIP Redis: no Docker and no fakeredis")
            """
        ),
    ]


def _predict_cells() -> list[NotebookNode]:
    """Three predict-the-output questions for Unit 6.4."""
    return [
        md(
            """
            ### Predict the output — Unit 6.4

            Three questions about the session. Decide first, then run the proof.
            """
        ),
        *predict_cells(
            """
            with ShopSession() as session:
                book = session.get(Book, 1)
                book.title = "Renamed"                      # no flush, no commit
                found = session.scalars(select(Book).where(Book.title == "Renamed")).all()
                print(len(found), found[0] is book if found else None)
                session.rollback()
            """,
            """
            `1 True`. Before running a query the session **autoflushes** pending changes, so
            the `UPDATE` is sent first and the `SELECT` finds the renamed row; the identity
            map then hands back the same `book` object. The rollback undoes it all.
            """,
            r"""
            with ShopSession() as session:
                book = session.get(Book, 1)
                book.title = "Renamed"
                found = session.scalars(select(Book).where(Book.title == "Renamed")).all()
                print(len(found), found[0] is book if found else None)
                session.rollback()
            """,
        ),
        *predict_cells(
            """
            with ShopSession() as session:
                emma = session.scalars(select(Book).where(Book.title == "Emma")).one()
                session.execute(update(Book).where(Book.title == "Emma").values(price_paise=0))
                print(emma.price_paise)
                session.rollback()
            """,
            """
            `0`. An ORM-enabled `update()` statement synchronizes the objects already in the
            session (`synchronize_session="auto"`: evaluate the `WHERE` in Python when it can,
            otherwise fetch the affected ids), so the loaded `emma` sees the new price without
            a reload.
            """,
            r"""
            with ShopSession() as session:
                emma = session.scalars(select(Book).where(Book.title == "Emma")).one()
                session.execute(update(Book).where(Book.title == "Emma").values(price_paise=0))
                print(emma.price_paise)
                session.rollback()
            """,
        ),
        *predict_cells(
            """
            with ShopSession() as session:
                asha = session.scalars(select(Author).where(Author.name == "Asha Rao")).one()
                emma = session.scalars(select(Book).where(Book.title == "Emma")).one()
                emma.author = asha                          # set the many-to-one side only
                print(emma in asha.books, len(session.dirty))
                session.rollback()
            """,
            """
            `True 0`. `back_populates` keeps both sides in sync: setting `emma.author` queues
            `emma` for `asha.books`. Reading `asha.books` then lazy-loads the collection, and
            that query **autoflushes** first: the `UPDATE books SET author_id = ...` is sent,
            the loaded collection contains `emma`, and nothing is dirty any more. The change
            is still inside the open transaction, so the rollback undoes it.
            """,
            r"""
            with ShopSession() as session:
                asha = session.scalars(select(Author).where(Author.name == "Asha Rao")).one()
                emma = session.scalars(select(Book).where(Book.title == "Emma")).one()
                emma.author = asha
                print(emma in asha.books, len(session.dirty))
                session.rollback()
            """,
        ),
    ]


LAB64_GIVEN_QUERIES_SOURCE = r'''
class QBase(DeclarativeBase):
    """Base for the given notes schema of exercises 2-3."""


q_note_tags = Table(
    "q_note_tags",
    QBase.metadata,
    Column("note_id", ForeignKey("q_notes.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("q_tags.id", ondelete="CASCADE"), primary_key=True),
)


class QTag(QBase):
    """A tag."""

    __tablename__ = "q_tags"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(30), unique=True)
    notes: Mapped[list[QNote]] = relationship(secondary=q_note_tags, back_populates="tags")


class QNote(QBase):
    """A note (tags load lazily, the default)."""

    __tablename__ = "q_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    pinned: Mapped[bool] = mapped_column(default=False)
    created_on: Mapped[date]
    tags: Mapped[list[QTag]] = relationship(
        secondary=q_note_tags, back_populates="notes", order_by=QTag.name
    )

'''

LAB64_GIVEN_SEED_SOURCE = r'''
Q_SEED = [
    ("Buy tea", True, ["shop", "food"]),
    ("Call Ravi", False, ["home"]),
    ("Draft: plan", False, ["work"]),
    ("Pay rent", True, ["home", "bills"]),
    ("Fix bug", False, ["work"]),
    ("Read book", False, []),
    ("Draft: email", False, []),
]


def fresh_q_engine() -> sa.Engine:
    """A new SQLite file with the seven seeded notes (note n was created on 2026-11-0n)."""
    path = PHASE6_DIR / "lab_queries.db"
    path.unlink(missing_ok=True)
    engine = create_engine(f"sqlite:///{path}")
    event.listen(
        engine,
        "connect",
        lambda dbapi_connection, _: dbapi_connection.execute("PRAGMA foreign_keys=ON"),
    )
    QBase.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        tags = {name: QTag(name=name) for name in ("bills", "food", "home", "shop", "work")}
        for day, (title, pinned, names) in enumerate(Q_SEED, start=1):
            session.add(
                QNote(
                    title=title,
                    pinned=pinned,
                    created_on=date(2026, 11, day),
                    tags=[tags[name] for name in names],
                )
            )
    return engine


def titles_with_tags_slow(session: Session) -> list[tuple[str, list[str]]]:
    """Every note's title and tag names: the N+1 way (one query per note for its tags)."""
    notes = session.scalars(select(QNote).order_by(QNote.id))
    return [(note.title, [tag.name for tag in note.tags]) for note in notes]
'''

LAB64_GIVEN_OTHERS_SOURCE = r'''
class DocBase(DeclarativeBase):
    """Base for exercise 5."""


class LabDocument(DocBase):
    """A document with optimistic locking."""

    __tablename__ = "lab_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    content: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column()
    __mapper_args__ = {"version_id_col": version}


class DocumentConflictError(Exception):
    """Somebody changed the document since it was read."""


def fresh_documents() -> sessionmaker[Session]:
    """A session factory on a new database holding document 1 ("first draft", version 1)."""
    path = PHASE6_DIR / "lab_documents.db"
    path.unlink(missing_ok=True)
    engine = create_engine(
        f"sqlite:///{path}", connect_args={"check_same_thread": False}
    )  # def routes run in worker threads
    DocBase.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(LabDocument(id=1, content="first draft"))
    return factory

'''

LAB64_GIVEN_ITEMS_SOURCE = r'''
class ItemBase(DeclarativeBase):
    """Base for exercise 6."""


class LabItem(ItemBase):
    """A searchable, pageable item."""

    __tablename__ = "lab_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime]


ITEM_WORDS = [
    "river",
    "Rice",
    "ridge",
    "Ring",
    "robot",
    "Ruby",
    "rust",
    "Rain",
    "atlas",
    "Basil",
    "cedar",
    "Delta",
]

'''

LAB64_GIVEN_ITEMS_DB_SOURCE = r'''
def fresh_items_engine() -> sa.Engine:
    """3000 items with mixed-case titles; every three share a timestamp (the id breaks ties)."""
    path = PHASE6_DIR / "lab_items.db"
    path.unlink(missing_ok=True)
    engine = create_engine(f"sqlite:///{path}")
    ItemBase.metadata.create_all(engine)
    rng = random.Random(42)
    start = datetime(2026, 1, 1)
    rows = [
        {
            "title": f"{rng.choice(ITEM_WORDS)} {rng.choice(ITEM_WORDS).lower()} {number}",
            "created_at": start + timedelta(minutes=number // 3),
        }
        for number in range(3000)
    ]
    with engine.begin() as connection:
        connection.execute(insert(LabItem), rows)
    return engine
'''


def _lab_setup_cells() -> list[NotebookNode]:
    """Lab 6.4 introduction and given code."""
    return [
        md(
            """
            ### Lab 6.4

            | Exercise | Syllabus item | You write |
            | --- | --- | --- |
            | 1 | Notes API v3 on PostgreSQL with typed models and many-to-many tags | `LabBase`, `LabTag`, `lab_note_tags`, `LabNote`, `add_lab_note` |
            | 2 | Eight queries with the emitted SQL printed | `build_eight_queries()` |
            | 3 | Detect and fix an N+1 problem | `count_statements`, `titles_with_tags_fast`, `strict_note` |
            | 4 | Three Alembic migrations | `write_lab_migrations(versions_dir)` |
            | 5 | An optimistic-locking conflict returning 409 | `update_document`, `build_documents_app` |
            | 6 | Indexed search and keyset pagination | `create_lab_indexes`, `search_prefix`, `keyset_items` |

            The *Notes API v3* section after the lab applies the same ideas to the real
            project. The given code comes first: a seeded notes schema for exercises 2 and 3
            (`QNote`, `QTag`, `fresh_q_engine()`, and the slow `titles_with_tags_slow`):
            """
        ),
        code(LAB64_GIVEN_QUERIES_SOURCE),
        md("The seed data, a fresh-database helper, and the slow (N+1) listing for exercise 3:"),
        code(LAB64_GIVEN_SEED_SOURCE),
        md(
            """
            For exercises 5 and 6: a versioned `LabDocument` with `DocumentConflictError` and
            `fresh_documents()`, and 3000 `LabItem`s from `fresh_items_engine()`:
            """
        ),
        code(LAB64_GIVEN_OTHERS_SOURCE),
        md("And the 3000 searchable items for exercise 6:"),
        code(LAB64_GIVEN_ITEMS_SOURCE),
        md(
            "`fresh_items_engine()` fills a new SQLite file with them (seeded, so always the same rows):"
        ),
        code(LAB64_GIVEN_ITEMS_DB_SOURCE),
        md(
            """
            For exercise 4: an Alembic project in the scratch folder (a sync `env.py` with
            batch mode for SQLite, no models: migrations are written by hand) and
            `lab_alembic(*arguments)`, which runs a command there and raises with the output
            if it fails:
            """
        ),
        code(
            r'''
            LAB_ALEMBIC = PHASE6_DIR / "lab_alembic"
            LAB_ALEMBIC_DB = LAB_ALEMBIC / "links.db"
            (LAB_ALEMBIC / "migrations" / "versions").mkdir(parents=True, exist_ok=True)
            (LAB_ALEMBIC / "alembic.ini").write_text(
                f"[alembic]\nscript_location = migrations\nsqlalchemy.url = sqlite:///{LAB_ALEMBIC_DB}\n",
                encoding="utf-8",
            )
            (LAB_ALEMBIC / "migrations" / "env.py").write_text(
                "from alembic import context\nfrom sqlalchemy import create_engine\n\n"
                "engine = create_engine(context.config.get_main_option('sqlalchemy.url'))\n"
                "with engine.connect() as connection:\n"
                "    context.configure(connection=connection, target_metadata=None, render_as_batch=True)\n"
                "    with context.begin_transaction():\n"
                "        context.run_migrations()\n",
                encoding="utf-8",
            )
            (LAB_ALEMBIC / "migrations" / "script.py.mako").write_text('"""${message}"""\n', encoding="utf-8")


            def reset_lab_alembic() -> Path:
                """Delete the database and every migration file; return the versions folder."""
                LAB_ALEMBIC_DB.unlink(missing_ok=True)
                versions = LAB_ALEMBIC / "migrations" / "versions"
                for migration in versions.glob("*.py"):
                    migration.unlink()
                shutil.rmtree(versions / "__pycache__", ignore_errors=True)
                return versions
            '''
        ),
        md(
            "`lab_alembic()`: run alembic in the lab project; return the output, raise if it failed:"
        ),
        code(
            r'''
            def lab_alembic(*arguments: str) -> str:
                """Run alembic in the lab project; return the output, raise if it failed."""
                run = subprocess.run(
                    [sys.executable, "-m", "alembic", *arguments],
                    cwd=LAB_ALEMBIC,
                    capture_output=True,
                    text=True,
                    env=CHILD_ENV,
                    timeout=120,
                )
                if run.returncode != 0:
                    raise RuntimeError(
                        f"alembic {' '.join(arguments)} failed: {run.stderr.strip().splitlines()[-1:]}"
                    )
                return run.stdout + run.stderr


            print(
                sorted(str(path.relative_to(LAB_ALEMBIC)) for path in LAB_ALEMBIC.rglob("*") if path.is_file())
            )
            '''
        ),
    ]


def _lab_exercise_1_cells() -> list[NotebookNode]:
    """Lab 6.4 exercise 1."""
    return [
        md(
            """
            #### Exercise 1 — Notes API v3 models with many-to-many tags

            Write typed models on your own base:

            - `LabBase(DeclarativeBase)` whose `MetaData` uses a naming convention with at
              least `"pk": "pk_%(table_name)s"` and `"uq": "uq_%(table_name)s_%(column_0_name)s"`.
            - `LabTag` (table `lab_tags`): `id`, `name` (`String(30)`, unique, not null).
            - `lab_note_tags` (a `Table`): `note_id` → `lab_notes.id` and `tag_id` →
              `lab_tags.id`, both `ON DELETE CASCADE`, together the primary key.
            - `LabNote` (table `lab_notes`): `id`, `title` (`String(200)`), `body` (`Text`,
              default `""`), `pinned` (default `False`), `created_at` (timezone-aware, default
              now in UTC), all `NOT NULL`; `tags` is a many-to-many relationship ordered by
              tag name.
            - `add_lab_note(session, title, tag_names) -> LabNote`: reuses existing tags
              (one row per name), creates missing ones, flushes, returns the note.

            The checks run on SQLite, then once more on the PostgreSQL container
            (`run_sync` lets the same sync code run on an async connection; SQLite again
            without Docker).
            """
        ),
        md("Your solution:"),
        code(
            r'''
            class LabBase(DeclarativeBase):
                """Base with a naming convention (see the exercise text)."""


            def add_lab_note(session: Session, title: str, tag_names: list[str]) -> Any:
                """Create a note, reusing tags that already exist."""
                raise NotImplementedError


            LabTag: Any = None  # replace with your model class
            lab_note_tags: Any = None  # replace with your association Table
            LabNote: Any = None  # replace with your model class
            '''
        ),
        md("Check exercise 1. The helpers first:"),
        code(
            r'''
            def lab_schema() -> dict[str, object]:
                """Tables, nullability, the association primary key and constraint names on SQLite."""
                engine = create_engine("sqlite://")
                LabBase.metadata.create_all(engine)
                inspector = sa_inspect(engine)
                return {
                    "tables": sorted(inspector.get_table_names()),
                    "note columns": {
                        column["name"]: column["nullable"] for column in inspector.get_columns("lab_notes")
                    },
                    "link key": inspector.get_pk_constraint("lab_note_tags")["constrained_columns"],
                    "unique": [
                        constraint["name"] for constraint in inspector.get_unique_constraints("lab_tags")
                    ],
                }


            def lab_sqlite_engine() -> sa.Engine:
                """An in-memory SQLite database with the lab tables and foreign keys on."""
                engine = create_engine("sqlite://")
                event.listen(
                    engine,
                    "connect",
                    lambda dbapi_connection, _: dbapi_connection.execute("PRAGMA foreign_keys=ON"),
                )
                LabBase.metadata.create_all(engine)
                return engine
            '''
        ),
        md(
            "`lab_tag_scenario()`: two notes sharing a tag, then deleting one note (bind: Engine or Connection):"
        ),
        code(
            r'''
            def lab_tag_scenario(bind: Any) -> dict[str, object]:
                """Two notes sharing a tag, then deleting one note (bind: Engine or Connection)."""
                with Session(bind) as session:
                    add_lab_note(session, "Buy tea", ["shop", "food"])
                    add_lab_note(session, "Rice", ["shop"])
                    session.expire_all()  # read back from the database, so order_by applies
                    note = session.scalars(select(LabNote).where(LabNote.title == "Buy tea")).one()
                    result = {
                        "tags": session.scalar(select(func.count()).select_from(LabTag)),
                        "names": [tag.name for tag in note.tags],
                        "body": note.body,
                        "pinned": note.pinned,
                        "has created_at": note.created_at is not None,
                    }
                    session.delete(note)
                    session.flush()
                    result["links after delete"] = session.scalar(
                        select(func.count()).select_from(lab_note_tags)
                    )
                    return result
            '''
        ),
        md(
            "Run the same scenario once on PostgreSQL through an async engine (stored for the checks):"
        ),
        code(
            r'''
            async def lab_scenario_on_postgres() -> object:
                """The same scenario through an async engine (PostgreSQL if available)."""
                try:
                    engine = create_async_engine(PG_URL or "sqlite+aiosqlite://")
                    async with engine.begin() as connection:
                        await connection.run_sync(LabBase.metadata.drop_all)
                        await connection.run_sync(LabBase.metadata.create_all)
                        result = await connection.run_sync(lab_tag_scenario)
                        await connection.run_sync(LabBase.metadata.drop_all)
                    await engine.dispose()
                    return result
                except Exception as error:  # a check cell must never stop Run All
                    return f"raised {type(error).__name__}: {error}"


            lab_postgres_result = await lab_scenario_on_postgres()
            '''
        ),
        md("The checks:"),
        code(
            r"""
            EXPECTED_SCENARIO = {
                "tags": 2,
                "names": ["food", "shop"],
                "body": "",
                "pinned": False,
                "has created_at": True,
                "links after delete": 1,
            }
            run_checks(
                [
                    (
                        "three tables",
                        lambda: lab_schema()["tables"],
                        ["lab_note_tags", "lab_notes", "lab_tags"],
                    ),
                    (
                        "every note column is NOT NULL",
                        lambda: lab_schema()["note columns"],
                        {"id": False, "title": False, "body": False, "pinned": False, "created_at": False},
                    ),
                    (
                        "composite key on the association table",
                        lambda: lab_schema()["link key"],
                        ["note_id", "tag_id"],
                    ),
                    ("named unique constraint", lambda: lab_schema()["unique"], ["uq_lab_tags_name"]),
                    (
                        "created_at is timezone-aware",
                        lambda: LabNote.__table__.c.created_at.type.timezone,
                        True,
                    ),
                    (
                        "tags are shared; defaults; cascade (SQLite)",
                        lambda: lab_tag_scenario(lab_sqlite_engine()),
                        EXPECTED_SCENARIO,
                    ),
                    ("the same on PostgreSQL", lambda: lab_postgres_result, EXPECTED_SCENARIO),
                ]
            )
            """
        ),
    ]


def _lab_exercise_2_3_cells() -> list[NotebookNode]:
    """Lab 6.4 exercises 2-3."""
    return [
        md(
            """
            #### Exercise 2 — eight queries with the emitted SQL printed

            Write `build_eight_queries()`, returning a dict of SQLAlchemy statements over
            `QNote` / `QTag` (seeded by
            `fresh_q_engine()`; note *n* was created on 2026-11-0*n*):

            | Key | Statement | Expected result |
            | --- | --- | --- |
            | `pinned_titles` | titles of pinned notes, by title | `["Buy tea", "Pay rent"]` |
            | `tagged_work` | titles of notes tagged `work`, by id | `["Draft: plan", "Fix bug"]` |
            | `count_per_tag` | `(tag name, number of notes)` for every tag, most notes first, then by name | `[("home", 2), ("work", 2), ("bills", 1), ("food", 1), ("shop", 1)]` |
            | `popular_tags` | names of tags on at least 2 notes, by name (`HAVING`) | `["home", "work"]` |
            | `untagged` | titles of notes without tags, by id | `["Read book", "Draft: email"]` |
            | `latest_per_tag` | `(tag name, title of the newest note with that tag)`, by tag name (a subquery) | 5 pairs |
            | `unpin_old` | an `update()`: unpin the **pinned** notes created before 2026-11-03 | 1 row changed |
            | `delete_drafts` | a `delete()`: notes whose title starts with `Draft:` | 2 rows deleted |

            The check runs each statement on a freshly seeded database and then prints the SQL
            of all eight.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            def build_eight_queries() -> dict[str, sa.Executable]:
                """The eight statements, by key (see the table)."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 2:"),
        code(
            r'''
            def run_lab_query(key: str) -> object:
                """Run one statement on fresh data: rows for SELECT, (rowcount, pinned titles) for DML."""
                statement = build_eight_queries()[key]
                engine = fresh_q_engine()
                try:
                    with Session(engine) as session, session.begin():
                        result = session.execute(statement)
                        if not statement.is_select:  # UPDATE / DELETE
                            pinned = session.scalars(
                                select(QNote.title).where(QNote.pinned).order_by(QNote.title)
                            ).all()
                            return result.rowcount, pinned
                        rows = [tuple(row) for row in result.all()]
                finally:
                    engine.dispose()
                return [row[0] for row in rows] if rows and len(rows[0]) == 1 else rows
            '''
        ),
        md("The checks:"),
        code(
            r"""
            run_checks(
                [
                    ("pinned_titles", lambda: run_lab_query("pinned_titles"), ["Buy tea", "Pay rent"]),
                    ("tagged_work", lambda: run_lab_query("tagged_work"), ["Draft: plan", "Fix bug"]),
                    (
                        "count_per_tag",
                        lambda: run_lab_query("count_per_tag"),
                        [("home", 2), ("work", 2), ("bills", 1), ("food", 1), ("shop", 1)],
                    ),
                    ("popular_tags", lambda: run_lab_query("popular_tags"), ["home", "work"]),
                    ("untagged", lambda: run_lab_query("untagged"), ["Read book", "Draft: email"]),
                    (
                        "latest_per_tag",
                        lambda: run_lab_query("latest_per_tag"),
                        [
                            ("bills", "Pay rent"),
                            ("food", "Buy tea"),
                            ("home", "Pay rent"),
                            ("shop", "Buy tea"),
                            ("work", "Fix bug"),
                        ],
                    ),
                    ("unpin_old", lambda: run_lab_query("unpin_old"), (1, ["Pay rent"])),
                    ("delete_drafts", lambda: run_lab_query("delete_drafts")[0], 2),
                ]
            )
            try:
                for key, statement in build_eight_queries().items():
                    print(f"-- {key}\n{statement.compile(dialect=sqlite.dialect())}")
            except NotImplementedError:
                print("(the SQL is printed here once build_eight_queries is written)")
            """
        ),
        md(
            """
            #### Exercise 3 — detect and fix an N+1 problem

            `titles_with_tags_slow(session)` (given) is correct but sends one query per note.

            - `count_statements(engine, action) -> tuple[int, object]`: open a `Session` on
              `engine`, call `action(session)`, and return how many SQL statements reached the
              database (listen to the engine's `before_cursor_execute` event and remove the
              listener afterwards) together with the action's result.
            - `titles_with_tags_fast(session)`: the same result in at most **2** statements.
            - `strict_note(session, note_id) -> QNote`: load one note with `raiseload("*")`, so
              touching `note.tags` raises instead of querying.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            def count_statements(engine: sa.Engine, action: Callable[[Session], object]) -> tuple[int, object]:
                """Statements sent while action(session) runs, and its result."""
                raise NotImplementedError


            def titles_with_tags_fast(session: Session) -> list[tuple[str, list[str]]]:
                """Same as titles_with_tags_slow, in at most two statements."""
                raise NotImplementedError


            def strict_note(session: Session, note_id: int) -> QNote:
                """One note whose relationships refuse to lazy-load."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 3:"),
        code(
            r'''
            def strict_tags_error() -> str:
                """What touching the tags of a strict note raises."""
                engine = fresh_q_engine()
                with Session(engine) as session:
                    note = strict_note(session, 1)
                    return raised_error_name(lambda: note.tags)


            def listeners_left_behind() -> int:
                """Listeners count_statements added and did not remove."""
                engine = fresh_q_engine()
                before = len(engine.dispatch.before_cursor_execute)
                count_statements(engine, lambda session: session.get(QNote, 1))
                return len(engine.dispatch.before_cursor_execute) - before


            q_engine = fresh_q_engine()
            '''
        ),
        md("The checks:"),
        code(
            r"""
            run_checks(
                [
                    (
                        "counting: get() twice is one statement",
                        lambda: count_statements(
                            q_engine, lambda session: (session.get(QNote, 1), session.get(QNote, 1))
                        )[0],
                        1,
                    ),
                    (
                        "the slow version is 1 + 7 statements",
                        lambda: count_statements(q_engine, titles_with_tags_slow)[0],
                        8,
                    ),
                    (
                        "the fast version is at most 2",
                        lambda: count_statements(q_engine, titles_with_tags_fast)[0] <= 2,
                        True,
                    ),
                    (
                        "same result",
                        lambda: (
                            count_statements(q_engine, titles_with_tags_fast)[1]
                            == count_statements(q_engine, titles_with_tags_slow)[1]
                        ),
                        True,
                    ),
                    ("the listener is removed afterwards", listeners_left_behind, 0),
                    ("raiseload makes lazy loads fail", strict_tags_error, "InvalidRequestError"),
                ]
            )
            """
        ),
    ]


def _lab_exercise_4_cells() -> list[NotebookNode]:
    """Lab 6.4 exercise 4."""
    return [
        md(
            """
            #### Exercise 4 — three Alembic migrations

            Write `write_lab_migrations(versions_dir)`, which writes three migration files for
            a `links` table into the given folder (the lab Alembic project above runs them on
            SQLite, in batch mode):

            | File | Revision (`down_revision`) | `upgrade()` | `downgrade()` |
            | --- | --- | --- | --- |
            | `0001_create_links.py` | `"0001"` (`None`) | create `links`: `id` integer primary key, `url` `String(500)` not null, `title` `String(200)` **nullable** | drop the table |
            | `0002_clicks_and_unique_url.py` | `"0002"` (`"0001"`) | add `clicks` integer not null with server default `"0"`; add unique constraint `uq_links_url` on `url` | remove both |
            | `0003_fill_titles.py` | `"0003"` (`"0002"`) | **data migration**: set `title = url` where `title` is null, then make `title` not null | make `title` nullable again |

            Each file needs the module-level `revision`, `down_revision`, `branch_labels` and
            `depends_on` variables, and `upgrade()` / `downgrade()` functions using
            `from alembic import op`. Use `op.batch_alter_table("links")` for column changes
            and constraints (SQLite cannot `ALTER` them in place).
            """
        ),
        md("Your solution:"),
        code(
            r'''
            def write_lab_migrations(versions_dir: Path) -> None:
                """Write 0001_create_links.py, 0002_clicks_and_unique_url.py, 0003_fill_titles.py."""
                raise NotImplementedError
            '''
        ),
        md(
            "Check exercise 4 (each run starts from an empty database and an empty versions folder):"
        ),
        code(
            r'''
            def lab_migration_run() -> dict[str, object]:
                """Write the migrations, walk them up and down, and record what happened."""
                write_lab_migrations(reset_lab_alembic())
                report: dict[str, object] = {"chain": re.findall(r"(\S+) -> (\w+)", lab_alembic("history"))}
                lab_alembic("upgrade", "0002")
                engine = create_engine(f"sqlite:///{LAB_ALEMBIC_DB}")
                with engine.begin() as connection:
                    connection.execute(text("INSERT INTO links (url) VALUES ('https://a.example')"))
                report["at 0002"] = {
                    column["name"]: column["nullable"] for column in sa_inspect(engine).get_columns("links")
                }
                lab_alembic("upgrade", "head")
                with engine.connect() as connection:
                    report["rows"] = [
                        tuple(row) for row in connection.execute(text("SELECT url, title, clicks FROM links"))
                    ]
                report["title nullable at head"] = {
                    column["name"]: column["nullable"] for column in sa_inspect(engine).get_columns("links")
                }["title"]
                with engine.connect() as connection:
                    report["duplicate url"] = raised_error_name(
                        lambda: connection.execute(
                            text("INSERT INTO links (url, title) VALUES ('https://a.example', 'again')")
                        )
                    )
                lab_alembic("downgrade", "base")
                report["tables after downgrade"] = sa_inspect(engine).get_table_names()
                engine.dispose()
                return report
            '''
        ),
        md("The checks:"),
        code(
            r"""
            run_checks(
                [
                    (
                        "three revisions in a chain",
                        lambda: lab_migration_run()["chain"],
                        [("0002", "0003"), ("0001", "0002"), ("<base>", "0001")],
                    ),
                    (
                        "schema at 0002",
                        lambda: lab_migration_run()["at 0002"],
                        {"id": False, "url": False, "title": True, "clicks": False},
                    ),
                    (
                        "data migration filled the title",
                        lambda: lab_migration_run()["rows"],
                        [("https://a.example", "https://a.example", 0)],
                    ),
                    ("title is NOT NULL at head", lambda: lab_migration_run()["title nullable at head"], False),
                    ("url is unique", lambda: lab_migration_run()["duplicate url"], "IntegrityError"),
                    (
                        "downgrade base removes the table",
                        lambda: lab_migration_run()["tables after downgrade"],
                        ["alembic_version"],
                    ),
                ]
            )
            """
        ),
    ]


def _lab_exercise_5_6_cells() -> list[NotebookNode]:
    """Lab 6.4 exercises 5-6."""
    return [
        md(
            """
            #### Exercise 5 — an optimistic-locking conflict returning 409

            `LabDocument` (given) has a `version_id_col`. Write:

            - `update_document(session, document_id, content, expected_version)`: load the
              document (`LookupError` if missing); if its version is not `expected_version`
              raise `DocumentConflictError`; otherwise change the content and flush, turning
              a `StaleDataError` (somebody committed in between) into `DocumentConflictError`
              too. Return the document.
            - `build_documents_app(session_factory) -> FastAPI` with a session dependency that
              opens one transaction per request and commits **before** the response is sent
              (`scope="function"`), and:
              - `GET /documents/{document_id}` → `{"id", "content", "version"}`, or 404
                `{"detail": "document not found"}`;
              - `PATCH /documents/{document_id}` with body `{"content": str, "version": int}`
                → 200 and the updated document, 404 as above, or **409**
                `{"detail": "version conflict"}`.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            def update_document(
                session: Session, document_id: int, content: str, expected_version: int
            ) -> LabDocument:
                """Change a document if it is still at expected_version."""
                raise NotImplementedError


            def build_documents_app(session_factory: sessionmaker[Session]) -> FastAPI:
                """GET and PATCH /documents/{document_id} with 404 and 409 answers."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 5:"),
        code(
            r'''
            def documents_scenario() -> list[tuple[int, object]]:
                """PATCH with the right version, again with the old one, then GET; plus a 404."""
                with TestClient(build_documents_app(fresh_documents())) as client:
                    calls = [
                        client.patch("/documents/1", json={"content": "second draft", "version": 1}),
                        client.patch("/documents/1", json={"content": "lost edit", "version": 1}),
                        client.get("/documents/1"),
                        client.patch("/documents/9", json={"content": "x", "version": 1}),
                    ]
                    return [(response.status_code, response.json()) for response in calls]


            def documents_race() -> str:
                """Two sessions read version 1; the first commits; the second's flush must fail."""
                factory = fresh_documents()
                with factory() as first, factory() as second:
                    second.get(LabDocument, 1)  # second has read version 1 too
                    update_document(first, 1, "first wins", 1)
                    first.commit()
                    return raised_error_name(lambda: update_document(second, 1, "second loses", 1))
            '''
        ),
        md("The checks:"),
        code(
            r"""
            run_checks(
                [
                    (
                        "PATCH with the current version",
                        lambda: documents_scenario()[0],
                        (200, {"id": 1, "content": "second draft", "version": 2}),
                    ),
                    (
                        "PATCH with a stale version → 409",
                        lambda: documents_scenario()[1],
                        (409, {"detail": "version conflict"}),
                    ),
                    (
                        "the stale edit was not saved",
                        lambda: documents_scenario()[2],
                        (200, {"id": 1, "content": "second draft", "version": 2}),
                    ),
                    (
                        "unknown document → 404",
                        lambda: documents_scenario()[3],
                        (404, {"detail": "document not found"}),
                    ),
                    (
                        "wrong expected version",
                        lambda: raised_error_name(lambda: update_document(fresh_documents()(), 1, "x", 7)),
                        "DocumentConflictError",
                    ),
                    ("a concurrent commit is caught at flush", documents_race, "DocumentConflictError"),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 6 — indexed search and keyset pagination

            On the 3000 `LabItem`s from `fresh_items_engine()`:

            - `create_lab_indexes(engine)`: an **expression index** `ix_lab_items_title_lower`
              on `lower(title)`, and `ix_lab_items_created_at_id` on `(created_at, id)`. (An
              `Index(...)` object attaches itself to the table's metadata, so every later
              `create_all` would create it too; plain `CREATE INDEX` statements through
              `text()` avoid that here.)
            - `search_prefix(session, prefix, limit=20) -> list[str]`: titles starting with
              `prefix`, ignoring case, ordered by `lower(title)` then `id`. Write the condition
              as a **range** on `lower(title)` (`>= prefix` and `<` the prefix with its last
              character incremented) so SQLite can use the expression index.
            - `keyset_items(session, after, limit) -> list[LabItem]`: newest first by
              `(created_at, id)`; when `after` is a `(created_at, id)` tuple, only items
              strictly before it (`tuple_` comparison).

            The checks compare your results with plain Python and look at `EXPLAIN QUERY PLAN`
            for the statements your functions send.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            def create_lab_indexes(engine: sa.Engine) -> None:
                """The two indexes (see the exercise text)."""
                raise NotImplementedError


            def search_prefix(session: Session, prefix: str, limit: int = 20) -> list[str]:
                """Case-insensitive prefix search on an index."""
                raise NotImplementedError


            def keyset_items(session: Session, after: tuple[datetime, int] | None, limit: int) -> list[LabItem]:
                """Newest first; strictly before after when given."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 6. The helpers:"),
        code(
            r'''
            def last_query_plan(engine: sa.Engine, action: Callable[[Session], object]) -> str:
                """EXPLAIN QUERY PLAN of the last SELECT that action(session) sent."""
                sent: list[tuple[str, Any]] = []

                def remember(conn: Any, cursor: Any, statement: str, parameters: Any, *rest: Any) -> None:
                    """Keep each statement with its parameters."""
                    sent.append((statement, parameters))

                event.listen(engine, "before_cursor_execute", remember)
                try:
                    with Session(engine) as session:
                        action(session)
                finally:
                    event.remove(engine, "before_cursor_execute", remember)
                statement, parameters = [
                    item for item in sent if item[0].lstrip().upper().startswith("SELECT")
                ][-1]
                with engine.connect() as connection:
                    return " | ".join(
                        row[-1]
                        for row in connection.exec_driver_sql("EXPLAIN QUERY PLAN " + statement, parameters)
                    )


            def indexed_items() -> tuple[sa.Engine, list[tuple[int, str, datetime]]]:
                """A fresh engine with your indexes, and every row for brute-force answers."""
                engine = fresh_items_engine()
                create_lab_indexes(engine)
                with engine.connect() as connection:
                    rows = [
                        tuple(row)
                        for row in connection.execute(select(LabItem.id, LabItem.title, LabItem.created_at))
                    ]
                return engine, rows
            '''
        ),
        md("`walk_items()`: ids of every item, page by page through keyset_items:"),
        code(
            r'''
            def walk_items(engine: sa.Engine, page_size: int) -> list[int]:
                """Ids of every item, page by page through keyset_items."""
                ids, after = [], None
                with Session(engine) as session:
                    while page := keyset_items(session, after, page_size):
                        ids += [item.id for item in page]
                        after = (page[-1].created_at, page[-1].id)
                return ids
            '''
        ),
        md("The checks:"),
        code(
            r'''
            def expected_prefix(rows: list[tuple[int, str, datetime]], prefix: str, limit: int) -> list[str]:
                """The right answer, computed in Python."""
                matching = sorted(
                    (title.lower(), item_id, title)
                    for item_id, title, _ in rows
                    if title.lower().startswith(prefix.lower())
                )
                return [title for _, _, title in matching[:limit]]


            def expected_order(rows: list[tuple[int, str, datetime]]) -> list[int]:
                """Every id, newest first by (created_at, id)."""
                return [
                    item_id for item_id, _, _ in sorted(rows, key=lambda row: (row[2], row[0]), reverse=True)
                ]


            def prefix_search_is_right(prefix: str, limit: int) -> bool:
                """search_prefix agrees with Python on a fresh, indexed database."""
                engine, rows = indexed_items()
                with Session(engine) as session:
                    return search_prefix(session, prefix, limit) == expected_prefix(rows, prefix, limit)


            def keyset_walk_is_right() -> bool:
                """Walking keyset pages visits every id once, newest first."""
                engine, rows = indexed_items()
                return walk_items(engine, 700) == expected_order(rows)
            '''
        ),
        md("The checks:"),
        code(
            r"""
            run_checks(
                [
                    ("prefix search matches Python", lambda: prefix_search_is_right("Ri", 15), True),
                    ("case does not matter", lambda: prefix_search_is_right("rUbY", 50), True),
                    (
                        "the search uses the expression index",
                        lambda: (
                            "USING INDEX ix_lab_items_title_lower"
                            in last_query_plan(
                                indexed_items()[0], lambda session: search_prefix(session, "ri", 5)
                            )
                        ),
                        True,
                    ),
                    ("keyset pages cover every item in order", keyset_walk_is_right, True),
                    (
                        "the page query uses the composite index",
                        lambda: (
                            "ix_lab_items_created_at_id"
                            in last_query_plan(
                                indexed_items()[0],
                                lambda session: keyset_items(session, (datetime(2026, 1, 1, 8, 0), 1500), 10),
                            )
                        ),
                        True,
                    ),
                ]
            )
            """
        ),
    ]


NOTES_V3_PYPROJECT_TOML = r"""
%%writefile ../projects/notes_api/pyproject.toml
[project]
name = "notes-api"
version = "0.3.0"
description = "The Phase 6 Notes API: a FastAPI service built step by step from Unit 6.2 to 6.8."
readme = "README.md"
requires-python = ">=3.15"
dependencies = [
    "fastapi[standard]>=0.163.1",
    "alembic>=1.20.1",
    "asyncpg>=0.32.0",
    "pydantic-settings>=2.16.2",
    "sqlalchemy[asyncio]>=2.1.9",
]

[dependency-groups]
dev = [
    "aiosqlite>=0.22.1",
    "pytest>=9.2.0",
    "respx>=0.23.1",
    "testcontainers>=4.15.0",
]

[build-system]
requires = ["uv_build>=0.13,<0.14"]
build-backend = "uv_build"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
addopts = "-q"
markers = ["postgres: needs Docker; runs against PostgreSQL in a testcontainer"]
filterwarnings = ["ignore::DeprecationWarning:testcontainers.*"]
"""

NOTES_V3_ENV_EXAMPLE = r"""
%%writefile ../projects/notes_api/.env.example
# Copy this file to .env and fill in real values. .env is git-ignored: never commit secrets.
# Every variable starts with NOTES_ (see src/notes_api/core/config.py).
NOTES_ENVIRONMENT=development
NOTES_DEBUG=false
# Generate a key with: python -c "import secrets; print(secrets.token_urlsafe(32))"
NOTES_API_KEY=change-me
# A JSON list of browser origins allowed by CORS.
NOTES_CORS_ORIGINS=["http://localhost:5173"]
NOTES_MAX_UPLOAD_BYTES=1048576
NOTES_HTTP_TIMEOUT_SECONDS=5
# PostgreSQL from compose.yaml (docker compose up -d --wait); SQLite also works:
# NOTES_DATABASE_URL=sqlite+aiosqlite:///./notes.db
NOTES_DATABASE_URL=postgresql+asyncpg://notes:notes@localhost:5432/notes
NOTES_DATABASE_ECHO=false
"""

NOTES_V3_README_MD = r"""
%%writefile ../projects/notes_api/README.md
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
"""

NOTES_V3_COMPOSE_YAML = r"""
%%writefile ../projects/notes_api/compose.yaml
# Local PostgreSQL for the Notes API:  docker compose up -d --wait   (stop: docker compose down)
# The password is for local development only; real deployments read secrets from the platform.
services:
  db:
    image: postgres:18-alpine
    environment:
      POSTGRES_USER: notes
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-notes}
      POSTGRES_DB: notes
    ports:
      - "127.0.0.1:${POSTGRES_PORT:-5432}:5432"
    volumes:
      - notes-db:/var/lib/postgresql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U notes -d notes"]
      interval: 2s
      timeout: 3s
      retries: 15

volumes:
  notes-db:
"""

NOTES_V3_ALEMBIC_INI = r"""
%%writefile ../projects/notes_api/alembic.ini
# Alembic configuration for the Notes API. The database URL is not stored here: env.py reads
# it from the app settings (NOTES_DATABASE_URL or .env), unless a caller sets sqlalchemy.url.

[alembic]
script_location = %(here)s/alembic
prepend_sys_path = src
file_template = %%(rev)s_%%(slug)s
timezone = UTC
truncate_slug_length = 40
path_separator = os


[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console
qualname =

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
"""

NOTES_V3_ALEMBIC_ENV_PY = r'''
%%writefile ../projects/notes_api/alembic/env.py
"""Alembic environment: runs migrations through the async engine (asyncpg or aiosqlite)."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import notes_api.models  # noqa: F401  (importing the models registers their tables)
from notes_api.core.config import get_settings
from notes_api.db import Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata  # what autogenerate compares the database with


def database_url() -> str:
    """sqlalchemy.url if a caller set it (tests, notebook), else the app settings."""
    return (
        config.get_main_option("sqlalchemy.url") or get_settings().database_url.get_secret_value()
    )


def run_migrations_offline() -> None:
    """`alembic upgrade --sql`: print the SQL instead of running it."""
    context.configure(url=database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run the migrations on one connection (batch mode lets SQLite alter tables)."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Open an async engine without a pool, run the migrations synchronously inside it."""
    engine = create_async_engine(database_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
'''

NOTES_V3_ALEMBIC_SCRIPT_PY_MAKO = r'''
%%writefile ../projects/notes_api/alembic/script.py.mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}
revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    """Apply this migration."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Undo this migration."""
    ${downgrades if downgrades else "pass"}
'''

NOTES_V3_ALEMBIC_VERSIONS_0001_CREATE_NOTES_PY = r'''
%%writefile ../projects/notes_api/alembic/versions/0001_create_notes.py
"""Create the notes table (tags kept as comma-separated text for now).

Revision ID: 0001
Revises:
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create notes and the index used by keyset pagination."""
    op.create_table(
        "notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), server_default="", nullable=False),
        sa.Column("tags", sa.Text(), server_default="", nullable=False),
        sa.Column("pinned", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notes")),
    )
    op.create_index("ix_notes_created_at_id", "notes", ["created_at", "id"])


def downgrade() -> None:
    """Drop the notes table."""
    op.drop_index("ix_notes_created_at_id", table_name="notes")
    op.drop_table("notes")
'''

NOTES_V3_ALEMBIC_VERSIONS_0002_TAGS_MANY_TO_MANY_PY = r'''
%%writefile ../projects/notes_api/alembic/versions/0002_tags_many_to_many.py
"""Move tags into their own table (many-to-many), copying the existing data.

Expand (create tags and note_tags), migrate the data, contract (drop notes.tags). Here the
three steps share one migration; with old app versions still running you would ship the
contract step in a later release.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Lightweight table stubs: a migration must not import today's models (they will change).
notes_table = sa.table("notes", sa.column("id", sa.Integer()), sa.column("tags", sa.Text()))
tags_table = sa.table("tags", sa.column("id", sa.Integer()), sa.column("name", sa.String()))
links_table = sa.table(
    "note_tags", sa.column("note_id", sa.Integer()), sa.column("tag_id", sa.Integer())
)


def split_tags(text: str) -> list[str]:
    """Names from the old comma-separated column, in order, without blanks or repeats."""
    return list(dict.fromkeys(name.strip() for name in text.split(",") if name.strip()))


def upgrade() -> None:
    """Expand, copy the data, contract."""
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=30), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tags")),
        sa.UniqueConstraint("name", name=op.f("uq_tags_name")),
    )
    op.create_table(
        "note_tags",
        sa.Column("note_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["note_id"], ["notes.id"], name=op.f("fk_note_tags_note_id_notes"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"], ["tags.id"], name=op.f("fk_note_tags_tag_id_tags"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("note_id", "tag_id", name=op.f("pk_note_tags")),
    )
    connection = op.get_bind()
    rows = connection.execute(sa.select(notes_table.c.id, notes_table.c.tags)).all()
    names = sorted({name for _note_id, text in rows for name in split_tags(text)})
    if names:
        connection.execute(tags_table.insert(), [{"name": name} for name in names])
        tag_ids = dict(connection.execute(sa.select(tags_table.c.name, tags_table.c.id)).all())
        links = [
            {"note_id": note_id, "tag_id": tag_ids[name]}
            for note_id, text in rows
            for name in split_tags(text)
        ]
        connection.execute(links_table.insert(), links)
    with op.batch_alter_table("notes") as batch:
        batch.drop_column("tags")


def downgrade() -> None:
    """Put the text column back, fill it from the links, drop the new tables."""
    with op.batch_alter_table("notes") as batch:
        batch.add_column(sa.Column("tags", sa.Text(), server_default="", nullable=False))
    connection = op.get_bind()
    pairs = connection.execute(
        sa.select(links_table.c.note_id, tags_table.c.name)
        .join(tags_table, tags_table.c.id == links_table.c.tag_id)
        .order_by(links_table.c.note_id, tags_table.c.name)
    ).all()
    names_by_note: dict[int, list[str]] = {}
    for note_id, name in pairs:
        names_by_note.setdefault(note_id, []).append(name)
    for note_id, names in names_by_note.items():
        connection.execute(
            notes_table.update().where(notes_table.c.id == note_id).values(tags=",".join(names))
        )
    op.drop_table("note_tags")
    op.drop_table("tags")
'''

NOTES_V3_ALEMBIC_VERSIONS_0003_VERSION_AND_SEARCH_PY = r'''
%%writefile ../projects/notes_api/alembic/versions/0003_version_and_search.py
"""Add the optimistic-locking version column and trigram search indexes.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEARCH_COLUMNS = ("title", "body")


def upgrade() -> None:
    """version starts at 1 for existing rows; PostgreSQL gets pg_trgm GIN indexes."""
    with op.batch_alter_table("notes") as batch:
        batch.add_column(
            sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False)
        )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for column in SEARCH_COLUMNS:  # a plain index on other databases
        op.create_index(
            f"ix_notes_{column}_trgm",
            "notes",
            [column],
            postgresql_using="gin",
            postgresql_ops={column: "gin_trgm_ops"},
        )


def downgrade() -> None:
    """Drop the indexes and the column (the pg_trgm extension stays installed)."""
    for column in SEARCH_COLUMNS:
        op.drop_index(f"ix_notes_{column}_trgm", table_name="notes")
    with op.batch_alter_table("notes") as batch:
        batch.drop_column("version")
'''

NOTES_V3_INIT_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/__init__.py
"""Notes API: a FastAPI service built step by step in Phase 6 of the course."""

__version__ = "0.3.0"
'''

NOTES_V3_CORE_CONFIG_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/core/config.py
"""Application settings: environment variables (prefix NOTES_) and an optional .env file."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_KEYS = {"", "change-me"}


class Settings(BaseSettings):
    """Every configurable value of the Notes API, validated once at startup."""

    model_config = SettingsConfigDict(
        env_prefix="NOTES_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Notes API"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    api_key: SecretStr | None = None  # the admin router answers 503 until it is set
    cors_origins: list[str] = ["http://localhost:5173"]
    max_upload_bytes: int = Field(default=1_048_576, gt=0)
    http_timeout_seconds: float = Field(default=5.0, gt=0)
    database_url: SecretStr = SecretStr("postgresql+asyncpg://notes:notes@localhost:5432/notes")
    database_echo: bool = False  # log every SQL statement (development only)
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)

    @model_validator(mode="after")
    def require_real_key_in_production(self) -> Settings:
        """Refuse to start in production without a real API key."""
        key = None if self.api_key is None else self.api_key.get_secret_value()
        if self.environment == "production" and (key is None or key in PLACEHOLDER_KEYS):
            raise ValueError("NOTES_API_KEY must be set to a real secret in production")
        return self


@lru_cache
def get_settings() -> Settings:
    """The process-wide settings, read from the environment once and then cached."""
    return Settings()
'''

NOTES_V3_EXCEPTIONS_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/exceptions.py
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
'''

NOTES_V3_CORE_ERRORS_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/core/errors.py
"""Domain errors and RFC 9457 Problem Details responses for every error the API returns."""

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from notes_api.core.middleware import REQUEST_ID_HEADER
from notes_api.exceptions import DomainError

PROBLEM_JSON = "application/problem+json"


class ProblemDetail(BaseModel):
    """The RFC 9457 body (used for the OpenAPI docs; responses are built as dicts)."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    request_id: str | None = None
    errors: list[dict[str, Any]] | None = None


def problem_response(
    request: Request,
    status_code: int,
    detail: str | None = None,
    *,
    problem_type: str | None = None,
    title: str | None = None,
    headers: dict[str, str] | None = None,
    **extra: Any,
) -> JSONResponse:
    """Build an application/problem+json response; the request id links it to the logs."""
    request_id = getattr(request.state, "request_id", None)
    body = {
        "type": f"/problems/{problem_type}" if problem_type else "about:blank",
        "title": title or HTTPStatus(status_code).phrase,
        "status": status_code,
        "detail": detail,
        "instance": request.url.path,
        "request_id": request_id,
        **extra,
    }
    all_headers = {**(headers or {}), **({REQUEST_ID_HEADER: request_id} if request_id else {})}
    return JSONResponse(
        {key: value for key, value in body.items() if value is not None},
        status_code=status_code,
        media_type=PROBLEM_JSON,
        headers=all_headers,
    )


async def domain_error_handler(request: Request, error: DomainError) -> JSONResponse:
    """DomainError subclasses → their own status, type and title."""
    return problem_response(
        request,
        error.status_code,
        str(error),
        problem_type=error.problem_type,
        title=error.title,
    )


async def http_error_handler(request: Request, error: StarletteHTTPException) -> JSONResponse:
    """HTTPException (ours, and Starlette's 404/405) → Problem Details."""
    detail = error.detail if isinstance(error.detail, str) else None
    return problem_response(request, error.status_code, detail, headers=error.headers)


async def validation_error_handler(request: Request, error: RequestValidationError) -> JSONResponse:
    """422 with one entry per problem (location, message, type), without echoing input."""
    problems = [
        {"loc": list(problem["loc"]), "msg": problem["msg"], "type": problem["type"]}
        for problem in error.errors()
    ]
    return problem_response(
        request,
        HTTPStatus.UNPROCESSABLE_CONTENT,
        f"{len(problems)} validation error(s)",
        problem_type="validation-error",
        title="Invalid request",
        errors=problems,
    )


async def integrity_error_handler(request: Request, error: IntegrityError) -> JSONResponse:
    """A constraint the database enforced (unique, foreign key) → 409, without SQL details."""
    return problem_response(
        request,
        HTTPStatus.CONFLICT,
        "the change conflicts with existing data",
        problem_type="conflict",
        title="Conflict",
    )


async def unhandled_error_handler(request: Request, error: Exception) -> JSONResponse:
    """Any other exception → a generic 500; details stay in the server log."""
    return problem_response(request, HTTPStatus.INTERNAL_SERVER_ERROR, "unexpected error")


def install_error_handlers(app: FastAPI) -> None:
    """Register every handler on the app."""
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
'''

NOTES_V3_DB_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/db.py
"""Database plumbing: naming conventions, the declarative base, the engine and sessions."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, event
from sqlalchemy.engine import Dialect
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator

from notes_api.core.config import Settings

# Predictable constraint names, so Alembic can find (and drop) them later.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UTCDateTime(TypeDecorator[datetime]):
    """A timezone-aware timestamp stored in UTC (SQLite's naive values come back as UTC)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        """Refuse naive datetimes; convert aware ones to UTC."""
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime: pass an aware one (UTC)")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        """Attach UTC to naive values (SQLite has no time zone type)."""
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class Base(DeclarativeBase):
    """Base class of every model: shared metadata and type mapping."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {datetime: UTCDateTime}


def enable_sqlite_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
    """SQLite ignores foreign keys (and ON DELETE CASCADE) unless each connection opts in."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_engine_from_settings(settings: Settings) -> AsyncEngine:
    """An async engine: a connection pool for PostgreSQL, foreign keys switched on for SQLite."""
    url = settings.database_url.get_secret_value()
    if url.startswith("sqlite"):
        engine = create_async_engine(url, echo=settings.database_echo)
        event.listen(engine.sync_engine, "connect", enable_sqlite_foreign_keys)
        return engine
    return create_async_engine(
        url,
        echo=settings.database_echo,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,  # replace connections the server closed while idle
    )


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Sessions whose objects stay readable after commit (the response is built after it)."""
    return async_sessionmaker(engine, expire_on_commit=False)
'''

NOTES_V3_MODELS_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/models.py
"""SQLAlchemy 2.0 typed models: notes and tags (many-to-many), with optimistic locking."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, ForeignKey, Index, String, Table, Text, false, func, text
from sqlalchemy.ext.associationproxy import AssociationProxy, association_proxy
from sqlalchemy.orm import Mapped, mapped_column, relationship

from notes_api.db import Base


def utc_now() -> datetime:
    """The current time in UTC (the default clock)."""
    return datetime.now(UTC)


class TimestampMixin:
    """created_at / updated_at for any model (the service sets them; the server has defaults)."""

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


note_tags = Table(
    "note_tags",
    Base.metadata,
    Column("note_id", ForeignKey("notes.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Tag(Base):
    """A tag name, stored once and shared by many notes."""

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(30), unique=True)


class Note(TimestampMixin, Base):
    """A note; tags is a list of names backed by the many-to-many tag_objects relationship."""

    __tablename__ = "notes"
    __table_args__ = (
        Index("ix_notes_created_at_id", "created_at", "id"),  # keyset pagination
        Index(  # trigram indexes make ILIKE '%text%' searches fast on PostgreSQL
            "ix_notes_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index(
            "ix_notes_body_trgm",
            "body",
            postgresql_using="gin",
            postgresql_ops={"body": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, server_default="")
    pinned: Mapped[bool] = mapped_column(server_default=false())
    version: Mapped[int] = mapped_column(server_default=text("1"))
    tag_objects: Mapped[list[Tag]] = relationship(
        secondary=note_tags, order_by=Tag.name, lazy="raise"
    )
    tags: AssociationProxy[list[str]] = association_proxy("tag_objects", "name")

    __mapper_args__: dict[str, Any] = {"version_id_col": version}  # UPDATE ... WHERE version = ?

    def __repr__(self) -> str:
        """Short form for logs and notebooks."""
        return f"Note(id={self.id!r}, title={self.title!r}, version={self.version!r})"
'''

NOTES_V3_SCHEMAS_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/schemas.py
"""Request and response schemas for the Notes API (Pydantic v2).

One schema per direction: NoteCreate (POST/PUT body), NoteUpdate (PATCH body, every field
optional), NoteRead (responses, with server-owned fields) and NoteFilters (query parameters).
Page envelopes live in pagination.py, error bodies in core/errors.py.
"""

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
    field_validator,
    model_validator,
)

MAX_TAGS = 10


def require_slug(value: str) -> str:
    """Allow lowercase letters, digits and dashes (checked after stripping and lower-casing)."""
    if not re.fullmatch(r"[a-z0-9-]+", value):
        raise ValueError("tags use lowercase letters, digits and dashes")
    return value


def unique_in_order(tags: list[str]) -> list[str]:
    """Drop repeated tags, keeping the first occurrence."""
    return list(dict.fromkeys(tags))


Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Body = Annotated[str, Field(max_length=10_000)]
Tag = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True, min_length=1, max_length=30),
    AfterValidator(require_slug),
]
Tags = Annotated[list[Tag], Field(max_length=MAX_TAGS)]
SortOrder = Literal["created_at", "-created_at", "updated_at", "-updated_at", "title", "-title"]


class NoteCreate(BaseModel):
    """Body of POST /notes and PUT /notes/{note_id}: every field a client may set."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [{"title": "Buy tea", "body": "Assam, 500 g", "tags": ["shopping"]}]
        },
    )

    title: Title
    body: Body = ""
    tags: Tags = []
    pinned: bool = False

    @field_validator("tags")
    @classmethod
    def drop_duplicate_tags(cls, tags: list[str]) -> list[str]:
        """Keep each tag once."""
        return unique_in_order(tags)


class NoteUpdate(BaseModel):
    """Body of PATCH /notes/{note_id}: only the fields being changed."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"pinned": True, "version": 1}]}
    )

    title: Title | None = None
    body: Body | None = None
    tags: Tags | None = None
    pinned: bool | None = None
    version: Annotated[
        int | None, Field(ge=1, description="The version you read; a mismatch is a 409.")
    ] = None

    @field_validator("tags")
    @classmethod
    def drop_duplicate_tags(cls, tags: list[str] | None) -> list[str] | None:
        """Keep each tag once."""
        return None if tags is None else unique_in_order(tags)

    @model_validator(mode="after")
    def reject_explicit_null(self) -> NoteUpdate:
        """None means "not sent"; an explicit null is an error (no field is nullable)."""
        nulled = sorted(name for name in self.model_fields_set if getattr(self, name) is None)
        if nulled:
            raise ValueError(f"fields cannot be null: {', '.join(nulled)}")
        return self


class NoteRead(BaseModel):
    """A note as the API returns it."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    body: str
    tags: list[str]
    pinned: bool
    version: int
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def word_count(self) -> int:
        """Words in the body (derived, never stored)."""
        return len(self.body.split())


class NoteFilters(BaseModel):
    """Query parameters of GET /notes: filtering, sorting and pagination."""

    model_config = ConfigDict(extra="forbid")

    q: Annotated[str | None, Field(max_length=100, description="Text in title or body.")] = None
    tag: Annotated[list[Tag], Field(description="Only notes that have all these tags.")] = []
    pinned: bool | None = None
    sort: SortOrder = "-created_at"
    limit: Annotated[int, Field(ge=1, le=100)] = 20
    offset: Annotated[int, Field(ge=0)] = 0


class FeedParams(BaseModel):
    """Query parameters of GET /notes/feed: keyset (cursor) pagination, newest first."""

    model_config = ConfigDict(extra="forbid")

    cursor: Annotated[str | None, Field(description="next_cursor from the previous page.")] = None
    limit: Annotated[int, Field(ge=1, le=100)] = 20


class LinkPreview(BaseModel):
    """The title of one link found in a note's body (or why it could not be fetched)."""

    url: str
    status_code: int | None = None
    title: str | None = None
    error: str | None = None


class ImportReport(BaseModel):
    """Result of POST /admin/import."""

    filename: str
    imported: int
    ids: list[int]
'''

NOTES_V3_REPOSITORIES_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/repositories.py
"""Storage behind a Protocol: the service depends on NoteRepository, not on a database.

Unit 6.3 shipped an in-memory implementation; Unit 6.4 replaces it with SqlNoteRepository,
which has the same methods, so the service and the routers barely change.
"""

from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import Select, delete, func, or_, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.exc import StaleDataError

from notes_api.exceptions import VersionConflictError
from notes_api.models import Note, Tag
from notes_api.pagination import CursorKey
from notes_api.schemas import NoteCreate, NoteFilters


class NoteRepository(Protocol):
    """What the service needs from storage."""

    async def add(self, data: NoteCreate, now: datetime) -> Note:
        """Store a new note and return it with its id."""
        ...

    async def get(self, note_id: int) -> Note | None:
        """The note with this id, or None."""
        ...

    async def search(self, filters: NoteFilters) -> tuple[list[Note], int]:
        """One page of matching notes and the total number of matches."""
        ...

    async def feed(self, limit: int, after: CursorKey | None) -> list[Note]:
        """Up to limit notes, newest first, strictly older than the key after."""
        ...

    async def update(self, note: Note, changes: dict[str, Any], now: datetime) -> Note:
        """Apply field changes (tags as a list of names), stamp updated_at, return the note."""
        ...

    async def delete(self, note: Note) -> None:
        """Remove a note returned by this repository."""
        ...

    async def delete_all(self) -> int:
        """Remove every note; return how many there were."""
        ...


class SqlNoteRepository:
    """NoteRepository on an AsyncSession: SQL filters, sorts and pages; tags always eager."""

    def __init__(self, session: AsyncSession) -> None:
        """Work inside the request's session (and so its transaction)."""
        self.session = session

    @staticmethod
    def _select() -> Select[tuple[Note]]:
        """SELECT notes plus one extra query for all their tags (no N+1, no lazy loads)."""
        return select(Note).options(selectinload(Note.tag_objects))

    async def _tags(self, names: list[str]) -> list[Tag]:
        """Tag rows for these names (sorted), creating missing ones; a savepoint absorbs a race."""
        if not names:
            return []
        found = await self.session.scalars(select(Tag).where(Tag.name.in_(names)))
        by_name = {tag.name: tag for tag in found}
        for name in names:
            if name in by_name:
                continue
            try:
                async with self.session.begin_nested():  # SAVEPOINT
                    tag = Tag(name=name)
                    self.session.add(tag)
                by_name[name] = tag
            except IntegrityError:  # another transaction inserted it first: use theirs
                by_name[name] = await self.session.scalar(select(Tag).where(Tag.name == name))
        return sorted((by_name[name] for name in names), key=lambda tag: tag.name)

    async def _flush(self, note: Note) -> None:
        """Send pending changes; a version mismatch becomes a domain conflict."""
        note_id = note.id  # read it now: after a failed flush the session needs a rollback
        try:
            await self.session.flush()
        except StaleDataError as error:
            raise VersionConflictError(note_id) from error

    async def add(self, data: NoteCreate, now: datetime) -> Note:
        """INSERT the note and its tag links; flush so the id is known."""
        note = Note(**data.model_dump(exclude={"tags"}), created_at=now, updated_at=now)
        note.tag_objects = await self._tags(data.tags)
        self.session.add(note)
        await self.session.flush()
        return note

    async def get(self, note_id: int) -> Note | None:
        """One note with its tags."""
        return await self.session.scalar(self._select().where(Note.id == note_id))

    async def search(self, filters: NoteFilters) -> tuple[list[Note], int]:
        """WHERE for the filters, COUNT for the total, ORDER BY + LIMIT/OFFSET for the page."""
        conditions = [Note.tag_objects.any(Tag.name == name) for name in filters.tag]
        if filters.pinned is not None:
            conditions.append(Note.pinned == filters.pinned)
        if filters.q:
            conditions.append(
                or_(
                    Note.title.icontains(filters.q, autoescape=True),
                    Note.body.icontains(filters.q, autoescape=True),
                )
            )
        total = await self.session.scalar(select(func.count(Note.id)).where(*conditions))
        field_name = filters.sort.removeprefix("-")
        column = func.lower(Note.title) if field_name == "title" else getattr(Note, field_name)
        if filters.sort.startswith("-"):
            order = [column.desc(), Note.id.desc()]
        else:
            order = [column.asc(), Note.id.asc()]
        page = self._select().where(*conditions).order_by(*order)
        notes = await self.session.scalars(page.offset(filters.offset).limit(filters.limit))
        return list(notes), total or 0

    async def feed(self, limit: int, after: CursorKey | None) -> list[Note]:
        """Keyset page: WHERE (created_at, id) < (:created_at, :id) on an index, no OFFSET."""
        statement = self._select().order_by(Note.created_at.desc(), Note.id.desc())
        if after is not None:
            statement = statement.where(tuple_(Note.created_at, Note.id) < tuple_(*after))
        return list(await self.session.scalars(statement.limit(limit)))

    async def update(self, note: Note, changes: dict[str, Any], now: datetime) -> Note:
        """Change attributes; the flush sends UPDATE ... WHERE id = ? AND version = ?."""
        changes = dict(changes)
        tag_names = changes.pop("tags", None)
        for name, value in changes.items():
            setattr(note, name, value)
        if tag_names is not None:
            note.tag_objects = await self._tags(tag_names)
        note.updated_at = now
        await self._flush(note)
        return note

    async def delete(self, note: Note) -> None:
        """DELETE the note (its tag links go by ON DELETE CASCADE)."""
        await self.session.delete(note)
        await self._flush(note)

    async def delete_all(self) -> int:
        """Bulk DELETE statements: every note, then every tag."""
        result = await self.session.execute(delete(Note))
        await self.session.execute(delete(Tag))
        return result.rowcount
'''

NOTES_V3_SERVICES_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/services.py
"""Business logic: what the API does, independent of HTTP and of how notes are stored."""

import asyncio
import csv
import io
import json
import re
from collections.abc import Callable
from datetime import datetime
from http import HTTPStatus

import httpx
from pydantic import TypeAdapter, ValidationError

from notes_api.exceptions import NoteNotFoundError, UploadRejectedError, VersionConflictError
from notes_api.models import Note, utc_now
from notes_api.pagination import decode_cursor, encode_cursor
from notes_api.repositories import NoteRepository
from notes_api.schemas import LinkPreview, NoteCreate, NoteFilters, NoteUpdate

URL_PATTERN = re.compile(r"https?://[^\s<>\"')]+")
TITLE_PATTERN = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
MAX_LINKS = 5
IMPORT_ADAPTER = TypeAdapter(list[NoteCreate])


class NoteService:
    """Use cases for notes; the repository and the clock are injected."""

    def __init__(self, repository: NoteRepository, clock: Callable[[], datetime] = utc_now) -> None:
        """Keep the collaborators."""
        self.repository = repository
        self.clock = clock

    async def create(self, data: NoteCreate) -> Note:
        """Store a new note stamped with the current time."""
        return await self.repository.add(data, self.clock())

    async def get(self, note_id: int) -> Note:
        """The note, or NoteNotFoundError (the API turns it into a 404 problem)."""
        note = await self.repository.get(note_id)
        if note is None:
            raise NoteNotFoundError(note_id)
        return note

    async def search(self, filters: NoteFilters) -> tuple[list[Note], int]:
        """One page of matching notes and the total."""
        return await self.repository.search(filters)

    async def feed(self, limit: int, cursor: str | None) -> tuple[list[Note], str | None]:
        """A keyset page, newest first, and the cursor of the next page (None at the end)."""
        after = decode_cursor(cursor) if cursor else None
        notes = await self.repository.feed(limit + 1, after)  # one extra: is there a next page?
        page = notes[:limit]
        has_more = len(notes) > limit
        next_cursor = encode_cursor((page[-1].created_at, page[-1].id)) if has_more else None
        return page, next_cursor

    async def replace(self, note_id: int, data: NoteCreate) -> Note:
        """PUT: every client-owned field gets the new value (or its default)."""
        note = await self.get(note_id)
        return await self.repository.update(note, data.model_dump(), self.clock())

    async def update(self, note_id: int, changes: NoteUpdate) -> Note:
        """PATCH: check the expected version, apply the fields sent, move updated_at on change."""
        note = await self.get(note_id)
        if changes.version is not None and changes.version != note.version:
            raise VersionConflictError(note_id, expected=changes.version, actual=note.version)
        sent = changes.model_dump(exclude_unset=True, exclude={"version"})
        if all(getattr(note, name) == value for name, value in sent.items()):
            return note
        return await self.repository.update(note, sent, self.clock())

    async def delete(self, note_id: int) -> None:
        """Delete a note, or NoteNotFoundError."""
        note = await self.get(note_id)
        await self.repository.delete(note)

    async def import_notes(self, notes: list[NoteCreate]) -> list[Note]:
        """Create every note of an import, in file order."""
        return [await self.create(note) for note in notes]

    async def delete_all(self) -> int:
        """Remove every note."""
        return await self.repository.delete_all()


def parse_import(filename: str, content: bytes) -> list[NoteCreate]:
    """Notes from a .json list or a .csv file (title, body, tags separated by ';', pinned)."""
    try:
        text = content.decode("utf-8-sig")
        if filename.endswith(".json"):
            return IMPORT_ADAPTER.validate_python(json.loads(text))
        rows = [
            {**row, "tags": [tag for tag in (row.get("tags") or "").split(";") if tag]}
            for row in csv.DictReader(io.StringIO(text))
        ]
        return IMPORT_ADAPTER.validate_python(rows)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
        reason = f"{type(error).__name__}: {str(error).splitlines()[0]}"
        raise UploadRejectedError(reason, HTTPStatus.UNPROCESSABLE_CONTENT) from error


class LinkPreviewer:
    """Fetch the <title> of links in a note through the app's shared HTTP client."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        """Use the pooled client created by the lifespan."""
        self.client = client

    async def preview(self, url: str) -> LinkPreview:
        """One link: its status and title, or the error name (never raises)."""
        try:
            response = await self.client.get(url)
        except httpx.HTTPError as error:
            return LinkPreview(url=url, error=type(error).__name__)
        match = TITLE_PATTERN.search(response.text)
        title = " ".join(match[1].split()) if match else None
        return LinkPreview(url=url, status_code=response.status_code, title=title)

    async def previews(self, body: str) -> list[LinkPreview]:
        """The first MAX_LINKS distinct links of a body, fetched concurrently."""
        urls = list(dict.fromkeys(URL_PATTERN.findall(body)))[:MAX_LINKS]
        return list(await asyncio.gather(*(self.preview(url) for url in urls)))
'''

NOTES_V3_CORE_LIFESPAN_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/core/lifespan.py
"""Startup and shutdown: create shared resources once and keep them on app.state."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from notes_api import __version__
from notes_api.core.config import Settings
from notes_api.db import create_engine_from_settings, make_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the database pool and one HTTP client; close both on shutdown."""
    settings: Settings = app.state.settings
    engine = create_engine_from_settings(settings)  # connects lazily, on first use
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    try:
        async with httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": f"notes-api/{__version__}"},
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        ) as http_client:
            app.state.http_client = http_client
            yield
    finally:
        await engine.dispose()  # close every pooled database connection
'''

NOTES_V3_DEPENDENCIES_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/dependencies.py
"""Dependencies shared by the routers, exported as Annotated aliases.

Resolution graph of a notes request:

    NoteServiceDep ── get_note_service ──┬── get_note_repository ── get_session ── app.state
                                         └── get_clock
    ApiKeyDep ── require_api_key ──┬── get_app_settings ── request.app.state
                                   └── X-API-Key header (APIKeyHeader)
"""

import secrets
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from notes_api.core.config import Settings
from notes_api.models import utc_now
from notes_api.repositories import NoteRepository, SqlNoteRepository
from notes_api.services import LinkPreviewer, NoteService

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_app_settings(request: Request) -> Settings:
    """The settings this app was created with (create_app stores them on app.state)."""
    return request.app.state.settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session and one transaction per request: commit on success, roll back on error."""
    async with request.app.state.session_factory() as session, session.begin():
        yield session


# scope="function": commit before the response is sent, so a failed commit is a 500/409,
# never a 200 for data that was not saved (the default scope would commit after sending).
SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]


def get_note_repository(session: SessionDep) -> NoteRepository:
    """The SQL repository on this request's session."""
    return SqlNoteRepository(session)


def get_clock() -> Callable[[], datetime]:
    """The clock for timestamps (tests override it with dependency_overrides)."""
    return utc_now


def get_http_client(request: Request) -> httpx.AsyncClient:
    """The pooled HTTP client the lifespan created."""
    return request.app.state.http_client


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
RepositoryDep = Annotated[NoteRepository, Depends(get_note_repository)]
ClockDep = Annotated[Callable[[], datetime], Depends(get_clock)]
HttpClientDep = Annotated[httpx.AsyncClient, Depends(get_http_client)]


def get_note_service(repository: RepositoryDep, clock: ClockDep) -> NoteService:
    """A NoteService wired to this app's repository and clock (one per request)."""
    return NoteService(repository, clock)


def get_link_previewer(client: HttpClientDep) -> LinkPreviewer:
    """A LinkPreviewer on the shared HTTP client."""
    return LinkPreviewer(client)


async def require_api_key(
    settings: SettingsDep, api_key: Annotated[str | None, Depends(api_key_header)]
) -> None:
    """Router-level guard: 503 when no key is configured, 401 when the header is wrong."""
    if settings.api_key is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "admin API disabled: set NOTES_API_KEY"
        )
    expected = settings.api_key.get_secret_value().encode()
    if api_key is None or not secrets.compare_digest(api_key.encode(), expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing or invalid X-API-Key header")


NoteServiceDep = Annotated[NoteService, Depends(get_note_service)]
LinkPreviewerDep = Annotated[LinkPreviewer, Depends(get_link_previewer)]
ApiKeyDep = Depends(require_api_key)
'''

NOTES_V3_ROUTERS_HEALTH_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/routers/health.py
"""/health (liveness) and /health/ready (readiness: can we reach the database?)."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from notes_api.dependencies import SessionDep

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe: the process answers (no database call)."""
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(session: SessionDep) -> dict[str, str]:
    """Readiness probe: 503 until the database answers SELECT 1."""
    try:
        await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as error:
        detail = f"database unavailable: {type(error).__name__}"
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail) from error
    return {"status": "ok", "database": "ok"}
'''

NOTES_V3_MAIN_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/main.py
"""The Notes API application factory.

Unit 6.4 version: create_app() wires settings, error handlers, middleware, the lifespan (now
with a database engine) and the routers. Later units add authentication (6.5), background
jobs and caching (6.6), observability (6.7) and deployment (6.8).

Serve it with `uvicorn notes_api.main:app` (module-level app) or
`uvicorn --factory notes_api.main:create_app` (a fresh app per process).
"""

from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles

from notes_api import __version__
from notes_api.core.config import Settings, get_settings
from notes_api.core.errors import install_error_handlers
from notes_api.core.lifespan import lifespan
from notes_api.core.middleware import REQUEST_ID_HEADER, RequestIdMiddleware, TimingMiddleware
from notes_api.routers import admin, health, notes, pages

PACKAGE_DIR = Path(__file__).resolve().parent
API_PREFIX = "/api/v1"


def operation_id(route: APIRoute) -> str:
    """Use the function name as the OpenAPI operationId (clean names in generated clients)."""
    return route.name


def install_middleware(app: FastAPI, settings: Settings) -> None:
    """Add middleware; the last one added is the outermost (it sees the request first)."""
    app.add_middleware(TimingMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-API-Key", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER, "Location", "Server-Timing"],
        max_age=600,
    )
    app.add_middleware(RequestIdMiddleware)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a fully wired app; tests pass their own Settings, servers use the environment."""
    settings = settings or get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        summary="Create, search and organize notes.",
        description="Built step by step in Phase 6 of the course. Errors are RFC 9457 problems.",
        debug=settings.debug,
        lifespan=lifespan,
        generate_unique_id_function=operation_id,
        openapi_tags=[
            {"name": "notes", "description": "Create, read, update and delete notes."},
            {"name": "admin", "description": "Bulk operations; need the X-API-Key header."},
            {"name": "health", "description": "Liveness probe for load balancers and tests."},
        ],
    )
    app.state.settings = settings
    install_error_handlers(app)
    install_middleware(app, settings)
    api_router = APIRouter(prefix=API_PREFIX)
    api_router.include_router(notes.router)
    api_router.include_router(admin.router)
    app.include_router(health.router)
    app.include_router(api_router)
    app.include_router(pages.router)
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
    return app


app = create_app()
'''

NOTES_V3_TESTS_CONFTEST_PY = r'''
%%writefile ../projects/notes_api/tests/conftest.py
"""Shared fixtures: every test gets its own app and its own SQLite database file."""

import asyncio
import secrets
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from helpers import create_tables
from notes_api.core.config import Settings
from notes_api.main import create_app


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests on asyncio (the anyio pytest plugin ships with anyio)."""
    return "asyncio"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Test settings: no .env file, a key generated for this run, a fresh SQLite file."""
    return Settings(
        _env_file=None,
        environment="test",
        api_key=SecretStr(secrets.token_urlsafe(16)),
        cors_origins=["http://localhost:5173"],
        max_upload_bytes=2048,
        database_url=SecretStr(f"sqlite+aiosqlite:///{tmp_path / 'notes.db'}"),
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    """A fresh app on an empty database for each test."""
    asyncio.run(create_tables(settings))
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """A TestClient; entering it runs the lifespan (startup and shutdown)."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def admin_headers(settings: Settings) -> dict[str, str]:
    """Headers carrying the valid API key."""
    assert settings.api_key is not None
    return {"X-API-Key": settings.api_key.get_secret_value()}
'''

NOTES_V3_TESTS_HELPERS_PY = r'''
%%writefile ../projects/notes_api/tests/helpers.py
"""Small helpers shared by the test modules."""

from typing import Any

from fastapi.testclient import TestClient

from notes_api.core.config import Settings
from notes_api.db import Base, create_engine_from_settings


def create(client: TestClient, **fields: Any) -> dict[str, Any]:
    """POST a note (title defaults to "Buy tea") and return the created note."""
    response = client.post("/api/v1/notes", json={"title": "Buy tea", **fields})
    assert response.status_code == 201, response.text
    return response.json()


def ids(response: Any) -> list[int]:
    """Ids of the notes on a page."""
    assert response.status_code == 200, response.text
    return [note["id"] for note in response.json()["items"]]


async def create_tables(settings: Settings) -> None:
    """CREATE TABLE for every model (fast; the PostgreSQL tests run the Alembic migrations)."""
    engine = create_engine_from_settings(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()
'''

NOTES_V3_TESTS_TEST_NOTES_PY = r'''
%%writefile ../projects/notes_api/tests/test_notes.py
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
'''

NOTES_V3_TESTS_TEST_ADMIN_PY = r'''
%%writefile ../projects/notes_api/tests/test_admin.py
"""The admin router: a router-level API key, uploads with validation, export and wipe."""

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from helpers import create, create_tables
from notes_api.core.config import Settings
from notes_api.main import create_app

IMPORT = "/api/v1/admin/import"
NOTES_JSON = json.dumps([{"title": "Tea", "tags": ["shop"]}, {"title": "Rice", "pinned": True}])
NOTES_CSV = "title,body,tags,pinned\nTea,Assam,shop;food,false\nRice,,shop,true\n"


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}])
def test_every_admin_route_needs_the_key(client: TestClient, headers: dict[str, str]) -> None:
    """Missing or wrong keys are 401 problems on every admin route."""
    for method, path in [("GET", "/api/v1/admin/export"), ("DELETE", "/api/v1/admin/notes")]:
        response = client.request(method, path, headers=headers)
        assert response.status_code == 401
        assert response.json()["detail"] == "missing or invalid X-API-Key header"


def test_admin_is_disabled_without_a_configured_key(settings: Settings) -> None:
    """No NOTES_API_KEY: the admin router answers 503, the rest of the API works."""
    without_key = settings.model_copy(update={"api_key": None})
    asyncio.run(create_tables(without_key))
    app: FastAPI = create_app(without_key)
    with TestClient(app) as client:
        assert client.get("/api/v1/admin/export", headers={"X-API-Key": "x"}).status_code == 503
        assert client.get("/api/v1/notes").status_code == 200


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
    notes = client.get("/api/v1/notes", params={"sort": "created_at"}).json()["items"]
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
'''

NOTES_V3_TESTS_TEST_REPOSITORY_PY = r'''
%%writefile ../projects/notes_api/tests/test_repository.py
"""SqlNoteRepository on a real (SQLite) database: sessions, loading, locking, savepoints."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from helpers import create_tables
from notes_api.core.config import Settings
from notes_api.db import create_engine_from_settings, make_session_factory
from notes_api.exceptions import VersionConflictError
from notes_api.models import Note, Tag
from notes_api.repositories import SqlNoteRepository
from notes_api.schemas import NoteCreate

pytestmark = pytest.mark.anyio
NOW = datetime(2026, 11, 17, 9, 30, tzinfo=UTC)


@pytest.fixture
async def session_factory(settings: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A session factory on a fresh database."""
    await create_tables(settings)
    engine = create_engine_from_settings(settings)
    yield make_session_factory(engine)
    await engine.dispose()


async def add_note(factory: async_sessionmaker[AsyncSession], **fields: object) -> int:
    """Create and commit one note; return its id."""
    async with factory() as session, session.begin():
        note = await SqlNoteRepository(session).add(NoteCreate(title="Tea", **fields), NOW)
        return note.id


async def test_tag_rows_are_shared(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Two notes tagged 'shop' share one Tag row."""
    await add_note(session_factory, tags=["shop", "food"])
    await add_note(session_factory, tags=["shop"])
    async with session_factory() as session:
        assert await session.scalar(select(func.count(Tag.id))) == 2


async def test_lazy_loading_is_switched_off(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """lazy='raise': touching tags without eager loading fails loudly instead of an N+1."""
    note_id = await add_note(session_factory, tags=["shop"])
    async with session_factory() as session:
        plain = await session.get(Note, note_id)
        assert plain is not None
        with pytest.raises(InvalidRequestError, match="lazy='raise'"):
            _ = plain.tags
        loaded = await SqlNoteRepository(session).get(note_id)
        assert loaded is not None and loaded.tags == ["shop"]


async def test_timestamps_come_back_in_utc(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """UTCDateTime attaches UTC to SQLite's naive values."""
    note_id = await add_note(session_factory)
    async with session_factory() as session:
        note = await SqlNoteRepository(session).get(note_id)
        assert note is not None and note.created_at == NOW and note.created_at.tzinfo is UTC


async def test_concurrent_update_raises_version_conflict(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Two sessions read version 1; the second UPDATE matches no row → VersionConflictError."""
    note_id = await add_note(session_factory)
    async with session_factory() as first, session_factory() as second:
        first_note = await SqlNoteRepository(first).get(note_id)
        second_note = await SqlNoteRepository(second).get(note_id)
        assert first_note is not None and second_note is not None
        await SqlNoteRepository(first).update(first_note, {"title": "First"}, NOW)
        await first.commit()
        with pytest.raises(VersionConflictError):
            await SqlNoteRepository(second).update(second_note, {"title": "Second"}, NOW)
    async with session_factory() as session:
        stored = await session.get(Note, note_id)
        assert stored is not None and (stored.title, stored.version) == ("First", 2)


async def test_delete_all_counts_rows(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Bulk DELETE removes notes, their links (cascade) and tags."""
    await add_note(session_factory, tags=["a"])
    await add_note(session_factory, tags=["b"])
    async with session_factory() as session, session.begin():
        assert await SqlNoteRepository(session).delete_all() == 2
    async with session_factory() as session:
        assert await session.scalar(select(func.count(Tag.id))) == 0
'''

NOTES_V3_TESTS_TEST_MIGRATIONS_PY = r'''
%%writefile ../projects/notes_api/tests/test_migrations.py
"""The Alembic migrations run up and down on SQLite, and 0002 copies the tag data."""

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

PROJECT_DIR = Path(__file__).resolve().parent.parent


def alembic_config(database_file: Path) -> Config:
    """alembic.ini with the URL of a test database."""
    config = Config(PROJECT_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_file}")
    config.attributes["configure_logger"] = False
    return config


def test_upgrade_downgrade_round_trip(tmp_path: Path) -> None:
    """head creates every table; base removes them again."""
    database_file = tmp_path / "migrations.db"
    config = alembic_config(database_file)
    command.upgrade(config, "head")
    engine = sa.create_engine(f"sqlite:///{database_file}")
    assert set(sa.inspect(engine).get_table_names()) == {
        "alembic_version",
        "notes",
        "tags",
        "note_tags",
    }
    command.downgrade(config, "base")
    assert sa.inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()


def test_data_migration_moves_tags_and_back(tmp_path: Path) -> None:
    """0002 turns 'shop,food' text into rows; downgrading writes the text back."""
    database_file = tmp_path / "data.db"
    config = alembic_config(database_file)
    command.upgrade(config, "0001")
    engine = sa.create_engine(f"sqlite:///{database_file}")
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO notes (title, tags) VALUES ('Tea', 'shop,food')"))
        connection.execute(sa.text("INSERT INTO notes (title, tags) VALUES ('Rice', 'shop')"))
    command.upgrade(config, "0002")
    with engine.connect() as connection:
        links = connection.execute(
            sa.text(
                "SELECT notes.title, tags.name FROM note_tags JOIN notes ON notes.id = note_id"
                " JOIN tags ON tags.id = tag_id ORDER BY notes.title, tags.name"
            )
        ).all()
    assert [tuple(row) for row in links] == [("Rice", "shop"), ("Tea", "food"), ("Tea", "shop")]
    command.downgrade(config, "0001")
    with engine.connect() as connection:
        rows = connection.execute(sa.text("SELECT title, tags FROM notes ORDER BY id")).all()
    assert [tuple(row) for row in rows] == [("Tea", "food,shop"), ("Rice", "shop")]
    engine.dispose()
'''

NOTES_V3_TESTS_TEST_POSTGRES_PY = r'''
%%writefile ../projects/notes_api/tests/test_postgres.py
"""The same app on PostgreSQL in Docker: migrations, drift check, trigram search, races.

Skipped when Docker is not available. Run only these: `uv run pytest -m postgres`; skip them:
`uv run pytest -m "not postgres"`.
"""

import asyncio
import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from notes_api.core.config import Settings
from notes_api.main import create_app
from notes_api.repositories import SqlNoteRepository
from notes_api.schemas import NoteCreate

pytestmark = pytest.mark.postgres
PROJECT_DIR = Path(__file__).resolve().parent.parent
POSTGRES_IMAGE = "postgres:18-alpine"


def docker_available() -> bool:
    """True if a Docker daemon answers."""
    try:
        import docker

        docker.from_env().ping()
    except Exception:
        return False
    return True


def alembic_config(url: str) -> Config:
    """alembic.ini pointed at the container."""
    config = Config(PROJECT_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="module")
def postgres_url() -> Iterator[str]:
    """Start PostgreSQL once for this module, migrate it to head, remove it afterwards."""
    if not docker_available():
        pytest.skip("Docker is not available")
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as container:
        url = container.get_connection_url()
        command.upgrade(alembic_config(url), "head")
        yield url


@pytest.fixture
def empty_url(postgres_url: str) -> str:
    """The database with every row removed and ids restarted."""

    async def truncate() -> None:
        """TRUNCATE all tables."""
        engine = create_async_engine(postgres_url)
        async with engine.begin() as connection:
            await connection.execute(sa.text("TRUNCATE notes, tags RESTART IDENTITY CASCADE"))
        await engine.dispose()

    asyncio.run(truncate())
    return postgres_url


def test_models_match_the_migrations(postgres_url: str) -> None:
    """alembic check: autogenerate finds no difference between the models and the schema."""
    command.check(alembic_config(postgres_url))


def test_api_round_trip_on_postgres(empty_url: str) -> None:
    """Create, search (ILIKE), feed, PATCH with versions and the 409, on the real database."""
    settings = Settings(
        _env_file=None,
        environment="test",
        api_key=SecretStr(secrets.token_urlsafe(16)),
        database_url=SecretStr(empty_url),
    )
    with TestClient(create_app(settings)) as client:
        for title in ("Buy Tea", "Steep the tea", "Call Ravi"):
            assert (
                client.post("/api/v1/notes", json={"title": title, "tags": ["x"]}).status_code
                == 201
            )
        found = client.get("/api/v1/notes", params={"q": "TEA", "sort": "title"}).json()
        assert [note["title"] for note in found["items"]] == ["Buy Tea", "Steep the tea"]
        feed = client.get("/api/v1/notes/feed", params={"limit": 2}).json()
        assert [note["id"] for note in feed["items"]] == [3, 2] and feed["next_cursor"]
        assert (
            client.patch("/api/v1/notes/1", json={"pinned": True, "version": 1}).json()["version"]
            == 2
        )
        assert (
            client.patch("/api/v1/notes/1", json={"pinned": False, "version": 1}).status_code == 409
        )
        assert client.get("/health/ready").json()["database"] == "ok"


def test_trigram_index_serves_substring_search(empty_url: str) -> None:
    """EXPLAIN shows ILIKE '%tea%' using the GIN trigram index (sequential scans off)."""

    async def plan() -> str:
        """The query plan of a title search."""
        async_engine = create_async_engine(empty_url)
        async with async_engine.begin() as connection:
            await connection.execute(sa.text("SET LOCAL enable_seqscan = off"))
            rows = await connection.execute(
                sa.text("EXPLAIN SELECT id FROM notes WHERE title ILIKE '%tea%'")
            )
            text = "\n".join(row[0] for row in rows)
        await async_engine.dispose()
        return text

    assert "ix_notes_title_trgm" in asyncio.run(plan())


def test_concurrent_new_tag_is_absorbed_by_the_savepoint(empty_url: str) -> None:
    """Two transactions add one new tag; a SAVEPOINT absorbs the loser's unique violation."""
    now = datetime(2026, 11, 17, tzinfo=UTC)

    async def race() -> list[list[str]]:
        """Run the two transactions concurrently and report each note's tags."""
        engine = create_async_engine(empty_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        first_flushed = asyncio.Event()

        async def first() -> list[str]:
            """Insert the tag, hold the transaction open for a moment, then commit."""
            async with factory() as session, session.begin():
                note = await SqlNoteRepository(session).add(
                    NoteCreate(title="A", tags=["race"]), now
                )
                first_flushed.set()
                await asyncio.sleep(0.3)  # the second transaction blocks on the unique index
                return list(note.tags)

        async def second(session_factory: async_sessionmaker[AsyncSession]) -> list[str]:
            """Insert the same tag while the first transaction still holds it."""
            await first_flushed.wait()
            async with session_factory() as session, session.begin():
                note = await SqlNoteRepository(session).add(
                    NoteCreate(title="B", tags=["race"]), now
                )
                return list(note.tags)

        results = await asyncio.gather(first(), second(factory))
        async with engine.connect() as connection:
            tag_count = await connection.scalar(sa.text("SELECT count(*) FROM tags"))
        await engine.dispose()
        assert tag_count == 1
        return list(results)

    assert asyncio.run(race()) == [["race"], ["race"]]
'''


def _notes_v3_intro_cells() -> list[NotebookNode]:
    """Notes API v3: introduction, pruning and project files."""
    return [
        md(
            """
            ### Notes API v3 — the project files

            v2's in-memory repository is replaced by PostgreSQL through async SQLAlchemy.
            Because the service depends on the `NoteRepository` Protocol, the routers, the
            pages and most of the service do not change:

            | v2 (Unit 6.3) | v3 (this unit) |
            | --- | --- |
            | `Note` dataclass | SQLAlchemy models `Note`, `Tag`, `note_tags` (many-to-many), `TimestampMixin`, `UTCDateTime` (`models.py`, `db.py`) |
            | `InMemoryNoteRepository` | `SqlNoteRepository(session)`: SQL filters, sorting, `COUNT`, keyset feed on `(created_at, id)`, eager-loaded tags, `lazy="raise"` |
            | repository on `app.state` | engine + session factory on `app.state` (lifespan); `get_session` yields one transaction per request, committed before the response (`scope="function"`) |
            | tags in insertion order | tags are shared rows, returned sorted by name (an association proxy keeps `note.tags` a list of names) |
            | last write wins | `version` column (`version_id_col`); `PATCH` with a stale `version` → **409** Problem Details; `IntegrityError` → 409 |
            | substring search in Python | `ILIKE` served by `pg_trgm` GIN indexes on PostgreSQL |
            | no schema management | Alembic: `0001` create notes, `0002` tags many-to-many (with a data migration), `0003` version column + trigram indexes |
            | — | `compose.yaml` for a local PostgreSQL, `/health/ready` checks the database |
            | tests on a fresh app | tests on a fresh **SQLite file** per test (fast), plus `test_postgres.py` on a PostgreSQL testcontainer |

            The cells write only the files that changed or are new (30 of 49). First, remove
            files of other versions (nothing, after a full run; the files of a later unit when
            you re-run this one):
            """
        ),
        code(
            r'''
            NOTES_V3_FILES = """
            .env.example README.md alembic.ini compose.yaml pyproject.toml ruff.toml alembic/env.py
            alembic/script.py.mako alembic/versions/0001_create_notes.py
            alembic/versions/0002_tags_many_to_many.py alembic/versions/0003_version_and_search.py
            src/notes_api/__init__.py src/notes_api/db.py src/notes_api/dependencies.py
            src/notes_api/exceptions.py src/notes_api/main.py src/notes_api/models.py
            src/notes_api/pagination.py src/notes_api/repositories.py src/notes_api/schemas.py
            src/notes_api/services.py src/notes_api/core/__init__.py src/notes_api/core/config.py
            src/notes_api/core/errors.py src/notes_api/core/lifespan.py src/notes_api/core/middleware.py
            src/notes_api/routers/__init__.py src/notes_api/routers/admin.py src/notes_api/routers/health.py
            src/notes_api/routers/notes.py src/notes_api/routers/pages.py src/notes_api/static/style.css
            src/notes_api/templates/_note.html src/notes_api/templates/_notes.html
            src/notes_api/templates/base.html src/notes_api/templates/index.html tests/conftest.py
            tests/helpers.py tests/test_admin.py tests/test_errors.py tests/test_links.py
            tests/test_middleware.py tests/test_migrations.py tests/test_notes.py tests/test_pages.py
            tests/test_pagination.py tests/test_postgres.py tests/test_repository.py tests/test_settings.py
            """.split()
            print("removed:", prune_notes_project(NOTES_V3_FILES))
            print(f"{len(NOTES_V3_FILES)} files in v3")
            '''
        ),
        md(
            """
            **Project metadata.** Runtime: SQLAlchemy (with asyncio), asyncpg, Alembic. Tests:
            aiosqlite (fast SQLite tests) and testcontainers (the PostgreSQL tests). The
            `postgres` marker lets you run either group alone:
            """
        ),
        code(NOTES_V3_PYPROJECT_TOML),
        md("`.env.example` gains the database settings:"),
        code(NOTES_V3_ENV_EXAMPLE),
        *writefile_cells(
            NOTES_V3_README_MD,
            [
                (
                    "",
                    "The README, part 1: versions and how to run v3 (Compose, Alembic, Uvicorn, pytest).",
                ),
                ("## Endpoints", "Part 2: endpoints (new: `/health/ready`, `version` on PATCH)."),
                (
                    "## Layout",
                    "Part 3: the layout, now with `db.py`, `alembic/` and `compose.yaml`.",
                ),
            ],
        ),
        md(
            """
            **`compose.yaml`**, the file from 6.4.1 for the Notes API: PostgreSQL 18 on
            `127.0.0.1` only, a named volume, a health check. The password is a local
            development default, overridable with `POSTGRES_PASSWORD`:
            """
        ),
        code(NOTES_V3_COMPOSE_YAML),
    ]


def _notes_v3_code_cells() -> list[NotebookNode]:
    """Notes API v3: package code."""
    return [
        md(
            "Version 0.3.0, and the settings gain `database_url` (a `SecretStr`: it contains a password), echo and pool sizes:"
        ),
        code(NOTES_V3_INIT_PY),
        *writefile_cells(
            NOTES_V3_CORE_CONFIG_PY,
            [
                ("", "Part 1 of `config.py`: the settings, now with the database."),
                (
                    '    @model_validator(mode="after")',
                    "Part 2: the production check (continues the class).",
                ),
                ("@lru_cache", "Part 3: the cached reader (unchanged)."),
            ],
        ),
        md("`exceptions.py` adds `VersionConflictError` (409):"),
        *writefile_cells(
            NOTES_V3_EXCEPTIONS_PY,
            [
                ("", "Part 1 of `exceptions.py`: the base and *note not found*."),
                (
                    "class VersionConflictError(DomainError):",
                    "Part 2: the optimistic-locking conflict.",
                ),
                ("class InvalidCursorError(", "Part 3: cursors and uploads (unchanged)."),
            ],
        ),
        md(
            "`core/errors.py` adds a handler that turns any `IntegrityError` into a 409 problem without SQL details:"
        ),
        *writefile_cells(
            NOTES_V3_CORE_ERRORS_PY,
            [
                ("", "Part 1 of `errors.py`: imports and the problem model."),
                ("def problem_response(", "Part 2: the response builder."),
                ("async def domain_error_handler(", "Part 3: domain, HTTP and validation errors."),
                (
                    "async def integrity_error_handler(",
                    "Part 4: database conflicts, the 500, and the installer.",
                ),
            ],
        ),
        md(
            """
            **`db.py`** (new): the naming convention, `UTCDateTime` (aware timestamps on every
            database, refusing naive ones), the declarative `Base`, and the engine factory:
            a pool for PostgreSQL, foreign keys switched on for SQLite:
            """
        ),
        *writefile_cells(
            NOTES_V3_DB_PY,
            [
                ("", "Part 1 of `db.py`: imports and the naming convention."),
                ("class UTCDateTime(", "Part 2: a type decorator for UTC timestamps."),
                (
                    "class Base(DeclarativeBase):",
                    "Part 3: the base, the SQLite pragma, the engine and the session factory.",
                ),
            ],
        ),
        md(
            """
            **`models.py`**: `TimestampMixin`, the association table, `Tag`, and `Note` with
            its indexes (keyset and trigram), `version_id_col`, a `lazy="raise"` relationship
            and the `tags` association proxy:
            """
        ),
        *writefile_cells(
            NOTES_V3_MODELS_PY,
            [
                ("", "Part 1 of `models.py`: the clock, the mixin and the association table."),
                ("class Tag(Base):", "Part 2: `Tag`."),
                ("class Note(TimestampMixin, Base):", "Part 3: `Note`."),
            ],
        ),
        md(
            "`schemas.py`: `NoteRead` gains `version` and `NoteUpdate` an optional expected `version`:"
        ),
        *writefile_cells(
            NOTES_V3_SCHEMAS_PY,
            [
                ("", "Part 1 of `schemas.py`: imports and the tag helpers."),
                ("Title = Annotated[", "Part 2: reusable `Annotated` types."),
                ("class NoteCreate(BaseModel):", "Part 3: `NoteCreate`."),
                ("class NoteUpdate(BaseModel):", "Part 4: `NoteUpdate` with `version`."),
                (
                    "class NoteRead(BaseModel):",
                    "Part 5: `NoteRead` (now with `version`) and `NoteFilters`.",
                ),
                (
                    "class FeedParams(BaseModel):",
                    "Part 6: feed parameters, link previews, import reports.",
                ),
            ],
        ),
        md(
            """
            **`repositories.py`**: the same Protocol, now implemented by `SqlNoteRepository`.
            Every query eager-loads tags with `selectinload`; `_tags` creates missing tags
            inside a savepoint so a concurrent insert of the same tag is absorbed; `_flush`
            turns `StaleDataError` into `VersionConflictError`:
            """
        ),
        *writefile_cells(
            NOTES_V3_REPOSITORIES_PY,
            [
                ("", "Part 1 of `repositories.py`: imports."),
                ("class NoteRepository(Protocol):", "Part 2: the Protocol (unchanged)."),
                (
                    "class SqlNoteRepository:",
                    "Part 3: the SQL repository: base query, tags with a savepoint, flush.",
                ),
                (
                    '    async def add(self, data: NoteCreate, now: datetime) -> Note:\n        """INSERT',
                    "Part 4: add, get, and search with `COUNT`, `ILIKE` and `ORDER BY`.",
                ),
                (
                    '    async def feed(self, limit: int, after: CursorKey | None) -> list[Note]:\n        """Keyset',
                    "Part 5: the keyset feed, update, delete and the bulk wipe.",
                ),
            ],
        ),
        md("`services.py`: `update` checks the expected version before changing anything:"),
        *writefile_cells(
            NOTES_V3_SERVICES_PY,
            [
                ("", "Part 1 of `services.py`: imports and constants."),
                ("class NoteService:", "Part 2: `NoteService`: create, get, search, feed."),
                (
                    "    async def replace(",
                    "Part 3: replace, update with the version check, delete, import, wipe.",
                ),
                ("def parse_import(", "Part 4: parsing uploads (unchanged)."),
                ("class LinkPreviewer:", "Part 5: link previews (unchanged)."),
            ],
        ),
        md(
            "`core/lifespan.py`: the engine and session factory join the HTTP client on `app.state`; the engine is disposed on shutdown:"
        ),
        code(NOTES_V3_CORE_LIFESPAN_PY),
        md(
            """
            `dependencies.py`: `get_session` (one transaction per request, `scope="function"`)
            and a repository built on it; the rest of the graph is unchanged:
            """
        ),
        *writefile_cells(
            NOTES_V3_DEPENDENCIES_PY,
            [
                ("", "Part 1 of `dependencies.py`: the graph and imports."),
                (
                    "def get_app_settings(",
                    "Part 2: settings, the session, the repository, the clock, the HTTP client.",
                ),
                (
                    "def get_note_service(",
                    "Part 3: the service, link previews and the API key (unchanged).",
                ),
            ],
        ),
        md("`routers/health.py` adds a readiness probe that runs `SELECT 1`:"),
        code(NOTES_V3_ROUTERS_HEALTH_PY),
        md("`main.py` changes only its docstring (the factory already wires everything):"),
        *writefile_cells(
            NOTES_V3_MAIN_PY,
            [
                ("", "Part 1 of `main.py`: imports and constants."),
                ("def operation_id(", "Part 2: operation ids and the middleware stack."),
                ("def create_app(", "Part 3: the factory and the module-level app."),
            ],
        ),
    ]


def _notes_v3_migration_cells() -> list[NotebookNode]:
    """Notes API v3: Alembic files."""
    return [
        md(
            """
            **Alembic.** `alembic.ini` keeps no URL: `env.py` takes `sqlalchemy.url` when a
            caller sets it (tests, this notebook) and otherwise the app's settings
            (`NOTES_DATABASE_URL`), so credentials never live in a committed file:
            """
        ),
        *writefile_cells(
            NOTES_V3_ALEMBIC_INI,
            [
                ("", "`alembic.ini`, part 1: where the scripts are and how files are named."),
                ("[loggers]", "Part 2: logging."),
            ],
        ),
        *writefile_cells(
            NOTES_V3_ALEMBIC_ENV_PY,
            [
                (
                    "",
                    "`alembic/env.py`, part 1: the models' metadata and where the URL comes from.",
                ),
                (
                    "def run_migrations_offline(",
                    "Part 2: offline (`--sql`) and online runs through the async engine.",
                ),
            ],
        ),
        md(
            "The template `alembic revision` fills in (typed, with docstrings, like the rest of the code):"
        ),
        code(NOTES_V3_ALEMBIC_SCRIPT_PY_MAKO),
        md(
            """
            **The three migrations.** `0001` is v1/v2's shape: tags as comma-separated text.
            Readable revision ids (`0001`...) instead of random hashes keep the history easy to
            follow:
            """
        ),
        *writefile_cells(
            NOTES_V3_ALEMBIC_VERSIONS_0001_CREATE_NOTES_PY,
            [
                ("", "`0001_create_notes.py`: the table and the keyset index."),
                ("def downgrade(", "Its downgrade."),
            ],
        ),
        md(
            """
            `0002` moves tags into their own table: **expand** (create `tags` and `note_tags`),
            **migrate the data** (split the text, insert names, link them), **contract** (drop
            `notes.tags`). It uses `sa.table()` stubs, never the models, and its downgrade
            restores the text:
            """
        ),
        *writefile_cells(
            NOTES_V3_ALEMBIC_VERSIONS_0002_TAGS_MANY_TO_MANY_PY,
            [
                ("", "`0002_tags_many_to_many.py`, part 1: table stubs and the tag splitter."),
                ("def upgrade(", "Part 2: expand, migrate, contract."),
                ("def downgrade(", "Part 3: the way back."),
            ],
        ),
        md(
            "`0003` adds the version column (1 for existing rows) and, on PostgreSQL, `pg_trgm` and the trigram indexes:"
        ),
        *writefile_cells(
            NOTES_V3_ALEMBIC_VERSIONS_0003_VERSION_AND_SEARCH_PY,
            [
                ("", "`0003_version_and_search.py`: upgrade."),
                ("def downgrade(", "Its downgrade."),
            ],
        ),
    ]


def _notes_v3_test_cells() -> list[NotebookNode]:
    """Notes API v3: tests."""
    return [
        md(
            """
            **Tests.** Every test gets its own SQLite file (`tmp_path`), so tests stay isolated
            and fast; `create_tables` builds the schema from the models. The v2 tests run
            unchanged against the database-backed app:
            """
        ),
        *writefile_cells(
            NOTES_V3_TESTS_CONFTEST_PY,
            [
                ("", "Part 1 of `conftest.py`: imports and the anyio backend for async tests."),
                (
                    "@pytest.fixture\ndef settings(",
                    "Part 2: settings with a per-test SQLite file, the app, the client.",
                ),
            ],
        ),
        code(NOTES_V3_TESTS_HELPERS_PY),
        md(
            "`test_notes.py` adds versions, the 409, shared sorted tags, `LIKE` escaping and readiness:"
        ),
        *writefile_cells(
            NOTES_V3_TESTS_TEST_NOTES_PY,
            [
                ("", "Part 1 of `test_notes.py`: health and creating notes."),
                (
                    '@pytest.mark.parametrize(\n    ("body", "location")',
                    "Part 2: invalid input, fetching one note.",
                ),
                (
                    "def test_list_paginates_and_counts_all_matches(",
                    "Part 3: listing and filtering.",
                ),
                ("def test_put_replaces_every_field(", "Part 4: PUT and PATCH."),
                (
                    '@pytest.mark.parametrize("body"',
                    "Part 5: bad PATCH bodies, DELETE, 404s, OpenAPI.",
                ),
                ("def test_patch_with_the_current_version_bumps_it(", "Part 6: new in v3."),
            ],
        ),
        md("`test_admin.py`: the *admin disabled* test now builds its app on the test database:"),
        *writefile_cells(
            NOTES_V3_TESTS_TEST_ADMIN_PY,
            [
                ("", "Part 1 of `test_admin.py`: the router-level key."),
                (
                    '@pytest.mark.parametrize(\n    ("filename", "content", "content_type"),\n    [(',
                    "Part 2: importing JSON and CSV.",
                ),
                (
                    '@pytest.mark.parametrize(\n    ("filename", "content", "content_type", "status")',
                    "Part 3: rejected uploads, export and wipe.",
                ),
            ],
        ),
        md(
            '`test_repository.py` (new) tests the repository directly: shared tags, `lazy="raise"`, UTC, the version conflict, bulk delete:'
        ),
        *writefile_cells(
            NOTES_V3_TESTS_TEST_REPOSITORY_PY,
            [
                ("", "Part 1: a session factory fixture and a helper."),
                ("async def test_tag_rows_are_shared(", "Part 2: tags, lazy loading, timestamps."),
                (
                    "async def test_concurrent_update_raises_version_conflict(",
                    "Part 3: the conflict and the bulk delete.",
                ),
            ],
        ),
        md(
            "`test_migrations.py` (new) runs the migrations up and down on SQLite and checks the data migration:"
        ),
        *writefile_cells(
            NOTES_V3_TESTS_TEST_MIGRATIONS_PY,
            [
                ("", "Part 1: configuration and the round trip."),
                (
                    "def test_data_migration_moves_tags_and_back(",
                    "Part 2: the data migration both ways.",
                ),
            ],
        ),
        md(
            """
            `test_postgres.py` (new) starts its own PostgreSQL testcontainer (skipped without
            Docker), migrates it with Alembic, and tests what SQLite cannot: `alembic check`
            on the real schema, the trigram index in the query plan, and a real race between
            two transactions creating the same tag:
            """
        ),
        *writefile_cells(
            NOTES_V3_TESTS_TEST_POSTGRES_PY,
            [
                ("", "Part 1 of `test_postgres.py`: imports and constants."),
                (
                    "def docker_available(",
                    "Part 2: Docker detection, Alembic configuration, the container fixture.",
                ),
                (
                    "@pytest.fixture\ndef empty_url(",
                    "Part 3: an empty database per test, and the drift check.",
                ),
                ("def test_api_round_trip_on_postgres(", "Part 4: the API on PostgreSQL."),
                ("def test_trigram_index_serves_substring_search(", "Part 5: the trigram index."),
                (
                    "def test_concurrent_new_tag_is_absorbed_by_the_savepoint(",
                    "Part 6: the savepoint under a real race.",
                ),
            ],
        ),
    ]


def _notes_v3_run_cells() -> list[NotebookNode]:
    """Notes API v3: try it, migrate PostgreSQL, serve, test, clean up."""
    return [
        md(
            """
            **Try it in the kernel** on a SQLite file (tables from the models), including the
            stale-version 409:
            """
        ),
        code(
            r"""
            notes_main = reload_notes_api()  # re-imports every notes_api module from disk
            NotesSettings = sys.modules["notes_api.core.config"].Settings
            notes_db = sys.modules["notes_api.db"]

            demo_db = PHASE6_DIR / "notes_v3_demo.db"
            demo_db.unlink(missing_ok=True)
            notes_settings = NotesSettings(
                _env_file=None,
                environment="test",
                api_key=secrets.token_urlsafe(16),
                database_url=f"sqlite+aiosqlite:///{demo_db}",
            )
            schema_engine = notes_db.create_engine_from_settings(notes_settings)
            async with schema_engine.begin() as connection:
                await connection.run_sync(notes_db.Base.metadata.create_all)
            await schema_engine.dispose()

            with TestClient(notes_main.create_app(notes_settings)) as client:
                created = client.post(
                    "/api/v1/notes", json={"title": "Buy tea", "tags": ["shop", "Food"]}
                ).json()
                print({key: created[key] for key in ("id", "tags", "version")})
                print(
                    "PATCH v1:",
                    client.patch("/api/v1/notes/1", json={"pinned": True, "version": 1}).json()["version"],
                )
                stale = client.patch(
                    "/api/v1/notes/1",
                    json={"title": "Lost edit", "version": 1},
                    headers={"X-Request-ID": "demo-409"},
                )
                show_response(stale)
                print("ready:", client.get("/health/ready").json())
            """
        ),
        md(
            """
            **Migrate PostgreSQL with Alembic.** The Notes API gets its own database on the
            shared container (so `alembic check` compares only its tables). `upgrade head` runs
            the three migrations; `current` reports where the database is; `check` confirms
            the models and the migrated schema agree. Without Docker the same commands run on
            a SQLite file:
            """
        ),
        code(
            r'''
            if PG_DSN:
                await pg_fetch("DROP DATABASE IF EXISTS notes")
                await pg_fetch("CREATE DATABASE notes")
                NOTES_DB_URL = PG_URL.rsplit("/", 1)[0] + "/notes"
            else:
                (PHASE6_DIR / "notes_v3_alembic.db").unlink(missing_ok=True)
                NOTES_DB_URL = f"sqlite+aiosqlite:///{PHASE6_DIR / 'notes_v3_alembic.db'}"
            NOTES_DB_ENV = {"NOTES_DATABASE_URL": NOTES_DB_URL}


            def notes_alembic(*arguments: str) -> str:
                """Run alembic in projects/notes_api against NOTES_DB_URL; return its log lines."""
                run = run_in_notes(sys.executable, "-m", "alembic", *arguments, extra_env=NOTES_DB_ENV)
                lines = [
                    re.sub(r"^INFO  \[alembic\.\S+\] ", "", line)
                    for line in (run.stdout + run.stderr).splitlines()
                ]
                noise = ("Context impl", "Will assume", "setting up autogenerate plugin", "Detected sequence")
                return (
                    "\n".join(line for line in lines if line and not line.startswith(noise))
                    or f"exit code {run.returncode}"
                )


            print(notes_alembic("upgrade", "head"))
            print("current:", notes_alembic("current"))
            print("check:", notes_alembic("check"))
            '''
        ),
        md(
            """
            The data migration on real data: go back to `0001`, insert notes with
            comma-separated tags the old way, upgrade again, and look at the new tables and
            the indexes PostgreSQL now has:
            """
        ),
        code(
            r'''
            async def notes_data_migration_demo() -> None:
                """Old-style rows at 0001, then upgrade, then inspect."""
                print(notes_alembic("downgrade", "0001"))
                connection = await asyncpg.connect(
                    NOTES_DB_URL.replace("postgresql+asyncpg://", "postgresql://")
                )
                try:
                    await connection.execute(
                        "INSERT INTO notes (title, tags) VALUES ('Buy tea', 'shop,food'),"
                        " ('Pay rent', 'home,bills'), ('Call Ravi', 'home')"
                    )
                    print(notes_alembic("upgrade", "head"))
                    links = await connection.fetch(
                        "SELECT n.title, t.name FROM note_tags l JOIN notes n ON n.id = l.note_id"
                        " JOIN tags t ON t.id = l.tag_id ORDER BY n.id, t.name"
                    )
                    print([tuple(row) for row in links])
                    indexes = await connection.fetch(
                        "SELECT indexname FROM pg_indexes WHERE tablename = 'notes' ORDER BY indexname"
                    )
                    print(
                        [row[0] for row in indexes],
                        await connection.fetchval("SELECT version FROM notes WHERE title = 'Buy tea'"),
                    )
                    await connection.execute("TRUNCATE notes, tags RESTART IDENTITY CASCADE")
                finally:
                    await connection.close()


            if PG_DSN:
                await notes_data_migration_demo()
            else:
                print("SKIP the PostgreSQL data-migration demo (no Docker); test_migrations.py covers SQLite")
            '''
        ),
        md(
            """
            **Serve it for real** on the migrated PostgreSQL database: Uvicorn in a child
            process with `NOTES_DATABASE_URL` and a key generated now. A search goes through
            the trigram-indexed `ILIKE`; a stale `PATCH` gets the 409; readiness reports the
            database:
            """
        ),
        code(
            r"""
            served_key = secrets.token_urlsafe(16)
            server_env = {**NOTES_DB_ENV, "NOTES_API_KEY": served_key}
            with uvicorn_server("notes_api.main:app", app_dir=NOTES_SRC, extra_env=server_env) as base_url:
                with httpx.Client(base_url=base_url, trust_env=False) as client:
                    for title, tags in [
                        ("Buy Assam tea", ["shop"]),
                        ("Steep the tea", ["kitchen"]),
                        ("Call Ravi", ["home"]),
                    ]:
                        client.post("/api/v1/notes", json={"title": title, "tags": tags})
                    found = client.get("/api/v1/notes", params={"q": "TEA", "sort": "title"}).json()
                    print([note["title"] for note in found["items"]], found["total"])
                    client.patch("/api/v1/notes/1", json={"pinned": True, "version": 1})
                    conflict = client.patch("/api/v1/notes/1", json={"pinned": False, "version": 1})
                    print(conflict.status_code, conflict.json()["detail"])
                    print(client.get("/health/ready").json())
                    print(client.delete("/api/v1/admin/notes", headers={"X-API-Key": served_key}).json())
            """
        ),
        md(
            """
            **Run the suite.** With the kernel's environment, the fast SQLite tests only
            (`-m "not postgres"`):
            """
        ),
        code(
            r"""
            pytest_run = run_in_notes(
                sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-m", "not postgres"
            )
            print(tidy_test_output(pytest_run.stdout + pytest_run.stderr).splitlines()[-1])
            print(f"{pytest_run.returncode=}")
            """
        ),
        md(
            """
            And the whole suite as its own uv project, the way CI and the Unit 6.8 image will
            run it: `uv lock` adds the database packages to `projects/notes_api/uv.lock`, and
            `uv run --frozen pytest` runs every test, including `test_postgres.py`, which
            starts (and removes) its own PostgreSQL container:
            """
        ),
        code(
            r"""
            if HAS_UV:
                lock_run = run_in_notes("uv", "lock")
                print(lock_summary(lock_run.stderr))
                if lock_run.returncode == 0:
                    uv_pytest = run_in_notes("uv", "run", "--frozen", "pytest", "-p", "no:cacheprovider", "-rs")
                    summary = tidy_test_output(uv_pytest.stdout).splitlines()
                    print(summary[-1], f"(exit code {uv_pytest.returncode})")
                    print(*[line for line in summary if line.startswith("SKIPPED")], sep="\n")
                else:
                    print("SKIP uv run pytest: uv lock failed (offline with an empty cache?)")
            else:
                print("SKIP: the uv command is not on PATH")
            """
        ),
        md("The project after Unit 6.4:"),
        code(
            r"""
            print(notes_tree())
            """
        ),
        md(
            """
            **Clean up.** Stop and remove the PostgreSQL container this unit started, and
            dispose the engines that still hold connections:
            """
        ),
        code(
            r"""
            await async_shop_engine.dispose()
            shop_engine.dispose()
            echo_engine.dispose()
            if pg_container is not None:
                container_id = pg_container.get_wrapped_container().id
                stop_shared_postgres()
                still_there = subprocess.run(
                    ["docker", "ps", "-aq", "--filter", f"id={container_id}"], capture_output=True, text=True
                ).stdout.strip()
                print(f"PostgreSQL container stopped and removed: {not still_there}")
            else:
                print("no container to stop")
            """
        ),
        md(
            """
            What v3 leaves for later: anyone with the URL can read and change every note (Unit
            6.5: users, password hashing, JWT, ownership, and closing the link-preview SSRF
            hole); no caching or background work (6.6); logs, metrics and traces (6.7); a
            container image, migrations at deploy time and production settings (6.8).
            """
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 6.4."""
    return [
        md(
            """
            ### Recap — Unit 6.4

            | Concept | One-line takeaway | JS / TS equivalent |
            | --- | --- | --- |
            | Relational design | surrogate keys + unique natural keys, normalize, index what you filter and sort by, let constraints enforce rules | (same SQL) |
            | Transactions | ACID; read committed by default; repeatable read and serializable abort on conflict: retry | `BEGIN ... COMMIT` in `pg` |
            | `EXPLAIN ANALYZE` | Seq Scan vs Index Scan; measure before adding indexes | same |
            | Drivers and pools | asyncpg / psycopg 3; pool size × processes < `max_connections` | `pg.Pool` |
            | Architecture | Engine (dialect + pool) → Connection → Core → ORM | Knex (Core) vs Prisma/TypeORM (ORM) |
            | Typed models | `DeclarativeBase`, `Mapped[...]`, `mapped_column`, `relationship`, mixins, naming conventions | Prisma schema, TypeORM entities |
            | Session | unit of work, identity map, autoflush; `flush` ≠ `commit`; object states | TypeORM `EntityManager` |
            | Querying | `select` / `join` / `group_by` / subqueries / `update` / `delete` / bulk `insert`; print the SQL | Prisma `findMany`, Knex |
            | Loading | lazy by default → N+1; `selectinload` for collections, `joinedload` for many-to-one, `raiseload` to forbid | Prisma `include` |
            | Async | `create_async_engine`, `AsyncSession`, no lazy loads (`MissingGreenlet`), `run_sync` | (Node is async-only) |
            | FastAPI integration | engine in the lifespan, session per request, transaction per request, repositories, `from_attributes` | NestJS + TypeORM module |
            | Alembic | autogenerate drafts, you review; upgrade/downgrade; data migrations; expand → migrate → contract | `prisma migrate`, Knex migrations |
            | Concurrency | atomic updates, optimistic `version_id_col` → 409, `FOR UPDATE` / `SKIP LOCKED`, savepoints | TypeORM `@VersionColumn`, `pessimistic_write` |
            | Alternatives | SQLModel, raw asyncpg (`COPY`), JSONB, MongoDB, Redis data types | Prisma, `pg`, Mongoose, ioredis |

            **Further reading**

            - SQLAlchemy 2.x: [Unified Tutorial](https://docs.sqlalchemy.org/en/20/tutorial/),
              [ORM declarative mapping](https://docs.sqlalchemy.org/en/20/orm/declarative_tables.html),
              [relationship loading techniques](https://docs.sqlalchemy.org/en/20/orm/queryguide/relationships.html),
              [asyncio extension](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html),
              [versioning (optimistic locking)](https://docs.sqlalchemy.org/en/20/orm/versioning.html),
              [constraint naming conventions](https://docs.sqlalchemy.org/en/20/core/constraints.html#configuring-constraint-naming-conventions)
            - [Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html),
              [autogenerate](https://alembic.sqlalchemy.org/en/latest/autogenerate.html),
              [batch mode for SQLite](https://alembic.sqlalchemy.org/en/latest/batch.html)
            - PostgreSQL: [transaction isolation](https://www.postgresql.org/docs/current/transaction-iso.html),
              [using EXPLAIN](https://www.postgresql.org/docs/current/using-explain.html),
              [indexes](https://www.postgresql.org/docs/current/indexes.html),
              [pg_trgm](https://www.postgresql.org/docs/current/pgtrgm.html),
              [JSON types](https://www.postgresql.org/docs/current/datatype-json.html),
              [explicit locking](https://www.postgresql.org/docs/current/explicit-locking.html)
            - [asyncpg](https://magicstack.github.io/asyncpg/current/),
              [psycopg 3](https://www.psycopg.org/psycopg3/docs/),
              [testcontainers-python](https://testcontainers-python.readthedocs.io/),
              [Docker Compose](https://docs.docker.com/compose/),
              [Redis data types](https://redis.io/docs/latest/develop/data-types/)
            - Python: [`sqlite3`](https://docs.python.org/3/library/sqlite3.html),
              [PEP 249 (DB-API 2.0)](https://peps.python.org/pep-0249/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 6.4, Lab 6.4 and Notes API v3."""
    return [
        *_overview_cells(),
        *_relational_cells(),
        *_driver_cells(),
        *_architecture_cells(),
        *_model_cells(),
        *_session_cells(),
        *_query_cells(),
        *_loading_cells(),
        *_async_cells(),
        *_fastapi_db_cells(),
        *_alembic_cells(),
        *_concurrency_cells(),
        *_alternatives_cells(),
        *_predict_cells(),
        *_lab_setup_cells(),
        *_lab_exercise_1_cells(),
        *_lab_exercise_2_3_cells(),
        *_lab_exercise_4_cells(),
        *_lab_exercise_5_6_cells(),
        *_notes_v3_intro_cells(),
        *_notes_v3_code_cells(),
        *_notes_v3_migration_cells(),
        *_notes_v3_test_cells(),
        *_notes_v3_run_cells(),
        *_recap_cells(),
    ]
