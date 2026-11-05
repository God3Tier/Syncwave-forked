"""initial playlist schema

Revision ID: 20261017_01
Revises:
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261017_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "playlists",
        sa.Column("playlist_id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_playlists_owner_id", "playlists", ["owner_id"])
    op.create_table(
        "playlist_songs",
        sa.Column(
            "playlist_id",
            sa.Uuid(),
            sa.ForeignKey("playlists.playlist_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("song_id", sa.Uuid(), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint("position >= 0", name="playlist_songs_position_valid"),
    )


def downgrade() -> None:
    op.drop_table("playlist_songs")
    op.drop_index("ix_playlists_owner_id", table_name="playlists")
    op.drop_table("playlists")
