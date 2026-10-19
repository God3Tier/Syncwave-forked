"""initial lyrics schema

Revision ID: 20261017_01
Revises:
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261017_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lyrics",
        sa.Column("song_id", sa.Uuid(), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("lines", sa.JSON().with_variant(postgresql.JSONB(), "postgresql")),
        sa.Column("line_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("source_event_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('PROCESSING', 'READY', 'FAILED')", name="lyrics_status_valid"
        ),
    )


def downgrade() -> None:
    op.drop_table("lyrics")
