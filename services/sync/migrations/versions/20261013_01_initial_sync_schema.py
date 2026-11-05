"""Create Sync session and idempotent command tables."""

import sqlalchemy as sa
from alembic import op

revision = "20261013_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())
    if "sync_sessions" not in existing_tables:
        op.create_table(
            "sync_sessions",
            sa.Column("jam_id", sa.String(length=36), nullable=False),
            sa.Column("generation", sa.BigInteger(), nullable=False),
            sa.Column("state", sa.String(length=32), nullable=False),
            sa.Column("queue_item_id", sa.String(length=36), nullable=False),
            sa.Column("song_id", sa.String(length=36), nullable=False),
            sa.Column("owner_id", sa.String(length=36), nullable=False),
            sa.Column("participant_ids", sa.JSON(), nullable=False),
            sa.Column("anchor_server_time_ms", sa.BigInteger(), nullable=True),
            sa.Column("anchor_position_ms", sa.BigInteger(), nullable=False),
            sa.Column("playback_rate", sa.Float(), nullable=False),
            sa.Column("prepare_deadline_ms", sa.BigInteger(), nullable=False),
            sa.PrimaryKeyConstraint("jam_id"),
        )
    if "sync_commands" not in existing_tables:
        op.create_table(
            "sync_commands",
            sa.Column("request_id", sa.String(length=36), nullable=False),
            sa.Column("jam_id", sa.String(length=36), nullable=False),
            sa.PrimaryKeyConstraint("request_id"),
        )
        op.create_index("ix_sync_commands_jam_id", "sync_commands", ["jam_id"])


def downgrade() -> None:
    op.drop_index("ix_sync_commands_jam_id", table_name="sync_commands")
    op.drop_table("sync_commands")
    op.drop_table("sync_sessions")
