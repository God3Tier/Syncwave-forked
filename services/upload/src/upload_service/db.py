"""Upload receipts also form a durable outbox, independent of Catalogue state."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, Index, Integer, String, Uuid
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(UTC)


class Status(StrEnum):
    UPLOADING = "UPLOADING"
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class Base(DeclarativeBase):
    pass


class UploadRecord(Base):
    __tablename__ = "uploads"
    __table_args__ = (
        CheckConstraint(
            "status IN ('UPLOADING', 'PENDING', 'PUBLISHED', 'FAILED')",
            name="uploads_status_valid",
        ),
        CheckConstraint("publish_attempts >= 0", name="uploads_attempts_valid"),
        Index("ix_uploads_dispatch", "status", "next_attempt_at"),
    )

    song_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True)
    title: Mapped[str] = mapped_column(String(200))
    artist: Mapped[str] = mapped_column(String(200))
    mood: Mapped[str | None] = mapped_column(String(64))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    audio_reference: Mapped[str] = mapped_column(String(512))
    lyrics_reference: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16))
    event: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    publish_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Database:
    def __init__(self, url: str) -> None:
        self.engine = create_async_engine(url, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def dispose(self) -> None:
        await self.engine.dispose()
