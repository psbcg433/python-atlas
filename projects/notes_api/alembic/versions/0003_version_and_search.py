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
