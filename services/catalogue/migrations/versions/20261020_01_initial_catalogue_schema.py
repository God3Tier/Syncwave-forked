"""initial catalogue schema

Revision ID: 20261020_01
Revises:
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261020_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "songs",
        sa.Column("song_id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("artist", sa.String(256), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("audio_reference", sa.String(1024), nullable=False),
        sa.Column("lyrics_reference", sa.String(1024), nullable=True),
        sa.Column("source_event_id", sa.String(64), nullable=True),
        sa.Column("lyrics_status", sa.String(16), nullable=False),
        sa.Column("waveform_status", sa.String(16), nullable=False),
        sa.Column("processing_status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "lyrics_status IN ('PENDING', 'PROCESSING', 'READY', 'FAILED')",
            name="songs_lyrics_status_valid",
        ),
        sa.CheckConstraint(
            "waveform_status IN ('PENDING', 'PROCESSING', 'READY', 'FAILED')",
            name="songs_waveform_status_valid",
        ),
        sa.CheckConstraint(
            "processing_status IN ('PROCESSING', 'PARTIAL', 'READY', 'FAILED')",
            name="songs_processing_status_valid",
        ),
    )


def downgrade() -> None:
    op.drop_table("songs")
