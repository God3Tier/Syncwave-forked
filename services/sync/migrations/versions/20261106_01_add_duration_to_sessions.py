"""Persist the authoritative media duration for automatic track completion."""

import sqlalchemy as sa
from alembic import op

revision = "20261106_01"
down_revision = "20261014_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sync_sessions") as batch:
        batch.add_column(sa.Column("duration_ms", sa.BigInteger(), nullable=True))
    op.execute("UPDATE sync_sessions SET duration_ms = 1 WHERE duration_ms IS NULL")
    with op.batch_alter_table("sync_sessions") as batch:
        batch.alter_column("duration_ms", nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("sync_sessions") as batch:
        batch.drop_column("duration_ms")
