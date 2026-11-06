"""Persist the prepared next track and readiness exclusions."""

import sqlalchemy as sa
from alembic import op

revision = "20261106_02"
down_revision = "20261106_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sync_sessions") as batch:
        batch.add_column(sa.Column("pending_track", sa.JSON(), nullable=True))
        batch.add_column(
            sa.Column("ignored_participant_ids", sa.JSON(), server_default="[]", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("sync_sessions") as batch:
        batch.drop_column("ignored_participant_ids")
        batch.drop_column("pending_track")
