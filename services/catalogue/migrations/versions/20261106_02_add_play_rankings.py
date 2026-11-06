"""add play rankings

Revision ID: 20261106_02
Revises: 20261106_01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261106_02"
down_revision: str | None = "20261106_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "songs", sa.Column("play_count", sa.BigInteger(), server_default="0", nullable=False)
    )
    op.create_table(
        "song_plays",
        sa.Column("playback_id", sa.Uuid(), nullable=False),
        sa.Column("song_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["song_id"], ["songs.song_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("playback_id"),
    )
    op.create_index("ix_song_plays_song_id", "song_plays", ["song_id"])


def downgrade() -> None:
    op.drop_index("ix_song_plays_song_id", table_name="song_plays")
    op.drop_table("song_plays")
    op.drop_column("songs", "play_count")
