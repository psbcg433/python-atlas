"""Add users; every note gets an owner (existing notes go to a disabled legacy account).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_OWNER = "legacy-owner@notes.invalid"  # cannot log in: no password, not active
users_table = sa.table(
    "users",
    sa.column("id", sa.Integer()),
    sa.column("email", sa.String()),
    sa.column("is_active", sa.Boolean()),
)
notes_table = sa.table("notes", sa.column("id", sa.Integer()), sa.column("owner_id", sa.Integer()))


def upgrade() -> None:
    """Create users, add notes.owner_id (nullable), backfill it, then make it required."""
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=20), server_default="user", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("oidc_subject", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("oidc_subject", name=op.f("uq_users_oidc_subject")),
    )
    with op.batch_alter_table("notes") as batch:
        batch.add_column(sa.Column("owner_id", sa.Integer(), nullable=True))
    connection = op.get_bind()
    if connection.execute(sa.select(sa.func.count()).select_from(notes_table)).scalar():
        connection.execute(users_table.insert().values(email=LEGACY_OWNER, is_active=False))
        legacy_id = connection.execute(
            sa.select(users_table.c.id).where(users_table.c.email == LEGACY_OWNER)
        ).scalar_one()
        connection.execute(notes_table.update().values(owner_id=legacy_id))
    with op.batch_alter_table("notes") as batch:
        batch.alter_column("owner_id", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key(
            op.f("fk_notes_owner_id_users"), "users", ["owner_id"], ["id"], ondelete="CASCADE"
        )
        batch.create_index(op.f("ix_notes_owner_id"), ["owner_id"])


def downgrade() -> None:
    """Drop ownership and the users table (the legacy account goes with it)."""
    with op.batch_alter_table("notes") as batch:
        batch.drop_index(op.f("ix_notes_owner_id"))
        batch.drop_constraint(op.f("fk_notes_owner_id_users"), type_="foreignkey")
        batch.drop_column("owner_id")
    op.drop_table("users")
