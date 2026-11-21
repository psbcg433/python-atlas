"""Database plumbing: naming conventions, the declarative base, the engine and sessions."""

import uuid
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
SCHEMA_REVISIONS = ("0001", "0002", "0003", "0004", "0005", "0006")  # this code's migrations
SCHEMA_REVISION = SCHEMA_REVISIONS[-1]  # the revision it expects (/health/startup checks it)

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
    connect_args = {}
    if settings.database_pgbouncer:
        # PgBouncer in transaction mode hands each transaction to any server connection, so
        # prepared statements cached on one connection do not exist on the next one.
        connect_args = {
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4()}__",
        }
    return create_async_engine(
        url,
        echo=settings.database_echo,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,  # replace connections the server closed while idle
        connect_args=connect_args,
    )


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Sessions whose objects stay readable after commit (the response is built after it)."""
    return async_sessionmaker(engine, expire_on_commit=False)
