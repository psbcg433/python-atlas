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
