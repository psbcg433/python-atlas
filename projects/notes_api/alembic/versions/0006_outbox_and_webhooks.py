"""Add the transactional outbox and per-user webhook settings.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Two nullable user columns and the outbox table."""
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("webhook_url", sa.String(length=500), nullable=True))
        batch.add_column(sa.Column("webhook_secret", sa.String(length=64), nullable=True))
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("webhook_status", sa.String(length=20), server_default="none", nullable=False),
        sa.Column("webhook_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_outbox_events_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_events")),
    )
    op.create_index(op.f("ix_outbox_events_user_id"), "outbox_events", ["user_id"])
    op.create_index("ix_outbox_events_published_at_id", "outbox_events", ["published_at", "id"])


def downgrade() -> None:
    """Drop the outbox and the webhook columns."""
    op.drop_index("ix_outbox_events_published_at_id", table_name="outbox_events")
    op.drop_index(op.f("ix_outbox_events_user_id"), table_name="outbox_events")
    op.drop_table("outbox_events")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("webhook_secret")
        batch.drop_column("webhook_url")
