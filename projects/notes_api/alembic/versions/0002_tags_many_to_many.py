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
