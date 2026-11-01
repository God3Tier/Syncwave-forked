"""add mood to songs

Revision ID: 20261031_01
Revises: 20261020_01
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261031_01"
down_revision: str | None = "20261020_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("songs", sa.Column("mood", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("songs", "mood")