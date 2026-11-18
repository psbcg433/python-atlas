"""SQLAlchemy 2.0 typed models: users, their notes and tags, refresh tokens and API keys."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, ForeignKey, Index, String, Table, Text, false, func, text, true
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


class User(TimestampMixin, Base):
    """An account. password_hash is None for users who only sign in with a third party."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), server_default="user")
    is_active: Mapped[bool] = mapped_column(server_default=true())
    oidc_subject: Mapped[str | None] = mapped_column(String(255), unique=True)  # "issuer|sub"
    webhook_url: Mapped[str | None] = mapped_column(String(500))
    webhook_secret: Mapped[str | None] = mapped_column(String(64))  # needed to sign: not hashed

    def __repr__(self) -> str:
        """Never show the hash."""
        return f"User(id={self.id!r}, email={self.email!r}, role={self.role!r})"


class RefreshToken(Base):
    """One opaque refresh token (only its SHA-256 is stored); a family shares one login."""

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    scopes: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]  # set when it was exchanged (rotation)
    revoked_at: Mapped[datetime | None]  # set at logout or when reuse was detected


class ApiKey(TimestampMixin, Base):
    """A personal API key: shown once, stored as a SHA-256, limited to some scopes."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    prefix: Mapped[str] = mapped_column(String(16))  # shown in lists, so users can tell keys apart
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[str] = mapped_column(String(200))
    last_used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]


class OutboxEvent(Base):
    """A domain event written in the same transaction as the change (transactional outbox).

    The relay worker publishes it (Redis pub/sub) and hands webhooks to the queue; webhook
    attempts are counted here, and an event that keeps failing ends up 'dead'.
    """

    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_events_published_at_id", "published_at", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[str] = mapped_column(Text)  # JSON
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    published_at: Mapped[datetime | None]  # set by the relay
    webhook_status: Mapped[str] = mapped_column(String(20), server_default="none")
    webhook_attempts: Mapped[int] = mapped_column(server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)


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
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
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
