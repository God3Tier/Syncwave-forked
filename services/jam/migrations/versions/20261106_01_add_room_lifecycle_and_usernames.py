"""Add room lifecycle and account display names."""

import sqlalchemy as sa
from alembic import op

revision = "20261106_01"
down_revision = "20261014_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jams") as batch:
        batch.add_column(
            sa.Column(
                "lifecycle_state",
                sa.String(length=16),
                nullable=False,
                server_default="ACTIVE",
            )
        )
        batch.add_column(sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("jam_members") as batch:
        batch.add_column(sa.Column("username", sa.String(length=24), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jam_members") as batch:
        batch.drop_column("username")
    with op.batch_alter_table("jams") as batch:
        batch.drop_column("ended_at")
        batch.drop_column("lifecycle_state")
