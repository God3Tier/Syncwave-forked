"""Add optional uploader ownership to catalogue songs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261106_01"
down_revision: str | None = "20261031_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("songs", sa.Column("uploader_id", sa.Uuid(), nullable=True))
    op.create_index("ix_songs_uploader_id", "songs", ["uploader_id"])


def downgrade() -> None:
    op.drop_index("ix_songs_uploader_id", table_name="songs")
    op.drop_column("songs", "uploader_id")
