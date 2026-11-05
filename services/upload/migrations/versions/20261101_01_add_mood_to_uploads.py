"""Optional mood label, sent on to Catalogue in SongUploaded."""

import sqlalchemy as sa
from alembic import op

revision = "20261101_01"
down_revision = "20261024_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("uploads", sa.Column("mood", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("uploads", "mood")
