"""Upload receipts and durable event outbox."""

import sqlalchemy as sa
from alembic import op

revision = "20261024_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "uploads",
        sa.Column("song_id", sa.Uuid(), primary_key=True),
        sa.Column("event_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("artist", sa.String(200), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("audio_reference", sa.String(512), nullable=False),
        sa.Column("lyrics_reference", sa.String(512), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("event", sa.JSON(), nullable=True),
        sa.Column("publish_attempts", sa.Integer(), nullable=False),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('UPLOADING', 'PENDING', 'PUBLISHED', 'FAILED')",
            name="uploads_status_valid",
        ),
        sa.CheckConstraint("publish_attempts >= 0", name="uploads_attempts_valid"),
    )
    op.create_index("ix_uploads_dispatch", "uploads", ["status", "next_attempt_at"])


def downgrade() -> None:
    op.drop_index("ix_uploads_dispatch", table_name="uploads")
    op.drop_table("uploads")
