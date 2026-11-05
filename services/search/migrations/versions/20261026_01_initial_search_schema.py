"""initial search schema

Revision ID: 20261026_01
Revises:
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261026_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "search_index",
        sa.Column("song_id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("artist", sa.String(256), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("search_index")
