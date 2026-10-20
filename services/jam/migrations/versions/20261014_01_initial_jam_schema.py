"""Create Jam, membership, and queue tables."""

import sqlalchemy as sa
from alembic import op

revision = "20261014_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jams",
        sa.Column("jam_id", sa.String(length=36), primary_key=True),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("current_queue_item_id", sa.String(length=36), nullable=True),
        sa.Column("sync_generation", sa.BigInteger(), nullable=True),
    )
    op.create_table(
        "jam_members",
        sa.Column("jam_id", sa.String(length=36), nullable=False),
        sa.Column("participant_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["jam_id"], ["jams.jam_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("jam_id", "participant_id"),
    )
    op.create_table(
        "jam_queue_items",
        sa.Column("queue_item_id", sa.String(length=36), primary_key=True),
        sa.Column("jam_id", sa.String(length=36), nullable=False),
        sa.Column("song_id", sa.String(length=36), nullable=False),
        sa.Column("added_by", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["jam_id"], ["jams.jam_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_jam_queue_items_jam_id", "jam_queue_items", ["jam_id"])


def downgrade() -> None:
    op.drop_index("ix_jam_queue_items_jam_id", table_name="jam_queue_items")
    op.drop_table("jam_queue_items")
    op.drop_table("jam_members")
    op.drop_table("jams")
