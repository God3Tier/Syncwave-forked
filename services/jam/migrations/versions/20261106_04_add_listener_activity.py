"""Persist the latest server-observed Jam listener activity."""

import sqlalchemy as sa
from alembic import op

revision = "20261106_04"
down_revision = "20261106_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jams") as batch:
        batch.add_column(
            sa.Column(
                "last_listener_active_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("jams") as batch:
        batch.drop_column("last_listener_active_at")
