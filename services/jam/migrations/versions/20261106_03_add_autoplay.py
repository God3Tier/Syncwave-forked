"""Persist Jam autoplay mode and consumed songs."""

import sqlalchemy as sa
from alembic import op

revision = "20261106_03"
down_revision = "20261106_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jams") as batch:
        batch.add_column(sa.Column("autoplay_mode", sa.String(length=16), nullable=True))
        batch.add_column(
            sa.Column("autoplay_seen_song_ids", sa.JSON(), server_default="[]", nullable=False)
        )
        batch.add_column(sa.Column("autoplay_prompt_deadline_ms", sa.BigInteger(), nullable=True))
        batch.add_column(
            sa.Column("autoplay_batch_number", sa.Integer(), server_default="0", nullable=False)
        )
        batch.add_column(
            sa.Column(
                "autoplay_catalogue_rechecked", sa.Boolean(), server_default=sa.false(), nullable=False
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("jams") as batch:
        batch.drop_column("autoplay_catalogue_rechecked")
        batch.drop_column("autoplay_batch_number")
        batch.drop_column("autoplay_prompt_deadline_ms")
        batch.drop_column("autoplay_seen_song_ids")
        batch.drop_column("autoplay_mode")
