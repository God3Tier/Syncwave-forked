"""Add a short, unique code for joining a Jam."""

import sqlalchemy as sa
from alembic import op

revision = "20261106_02"
down_revision = "20261106_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jams") as batch:
        batch.add_column(sa.Column("join_code", sa.String(length=8), nullable=True))

    connection = op.get_bind()
    jam_ids = connection.execute(sa.text("SELECT jam_id FROM jams ORDER BY jam_id")).scalars()
    for index, jam_id in enumerate(jam_ids, start=10_000_000):
        connection.execute(
            sa.text("UPDATE jams SET join_code = :join_code WHERE jam_id = :jam_id"),
            {"join_code": str(index), "jam_id": jam_id},
        )

    with op.batch_alter_table("jams") as batch:
        batch.alter_column("join_code", nullable=False)
        batch.create_index("ix_jams_join_code", ["join_code"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("jams") as batch:
        batch.drop_index("ix_jams_join_code")
        batch.drop_column("join_code")
