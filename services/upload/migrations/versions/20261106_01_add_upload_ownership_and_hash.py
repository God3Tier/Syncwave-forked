"""Add uploader ownership and exact-byte deduplication fields."""

import sqlalchemy as sa
from alembic import op

revision = "20261106_01"
down_revision = "20261101_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("uploads", sa.Column("uploader_id", sa.Uuid(), nullable=True))
    op.add_column("uploads", sa.Column("content_sha256", sa.CHAR(64), nullable=True))
    op.create_index("ix_uploads_uploader_id", "uploads", ["uploader_id"])
    op.create_index(
        "uq_uploads_content_sha256",
        "uploads",
        ["content_sha256"],
        unique=True,
        postgresql_where=sa.text("content_sha256 IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_uploads_content_sha256", table_name="uploads")
    op.drop_index("ix_uploads_uploader_id", table_name="uploads")
    op.drop_column("uploads", "content_sha256")
    op.drop_column("uploads", "uploader_id")
