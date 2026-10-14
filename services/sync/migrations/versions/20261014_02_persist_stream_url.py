"""Persist the dependency-resolved stream URL."""

import sqlalchemy as sa
from alembic import op

revision = "20261014_02"
down_revision = "20261013_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sync_sessions") as batch:
        batch.add_column(sa.Column("stream_url", sa.String(length=2048)))
    connection = op.get_bind()
    sessions = sa.table(
        "sync_sessions",
        sa.column("song_id", sa.String()),
        sa.column("stream_url", sa.String()),
    )
    connection.execute(
        sessions.update().values(
            stream_url="/api/streaming/songs/" + sessions.c.song_id + "/audio"
        )
    )
    with op.batch_alter_table("sync_sessions") as batch:
        batch.alter_column("stream_url", nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("sync_sessions") as batch:
        batch.drop_column("stream_url")
