"""Lyrics storage: one row per song in this service's own database (plan.md §11).

The row's status is also the worker's idempotency state (plan.md §16): a
song whose lyrics are READY is never processed again.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Status(StrEnum):
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


class Base(DeclarativeBase):
    pass


class LyricsRecord(Base):
    __tablename__ = "lyrics"
    __table_args__ = (
        CheckConstraint("status IN ('PROCESSING', 'READY', 'FAILED')", name="lyrics_status_valid"),
    )

    song_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    # [{"time_ms": int, "text": str}, ...] sorted by time_ms; set once READY
    lines: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    line_count: Mapped[int] = mapped_column(Integer, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    # event_id of the SongUploaded event last processed for this song
    source_event_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Database:
    def __init__(self, url: str) -> None:
        self.engine = create_async_engine(url, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def dispose(self) -> None:
        await self.engine.dispose()


class LyricsRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, song_id: uuid.UUID) -> LyricsRecord | None:
        async with self._sessions() as session:
            return await session.get(LyricsRecord, song_id)

    async def mark_processing(self, song_id: uuid.UUID, event_id: str) -> None:
        async with self._sessions.begin() as session:
            await _upsert(
                session,
                song_id,
                status=Status.PROCESSING,
                lines=None,
                line_count=0,
                error_code=None,
                error_message=None,
                source_event_id=event_id,
            )

    async def mark_ready(self, song_id: uuid.UUID, lines: list[dict[str, Any]]) -> None:
        async with self._sessions.begin() as session:
            await _upsert(
                session,
                song_id,
                status=Status.READY,
                lines=lines,
                line_count=len(lines),
                error_code=None,
                error_message=None,
            )

    async def mark_failed(
        self, song_id: uuid.UUID, event_id: str | None, code: str, message: str
    ) -> bool:
        """Records a failure. Returns False, changing nothing, if the lyrics are
        already READY: successful processing is never undone (plan.md §16)."""
        async with self._sessions.begin() as session:
            record = await session.get(LyricsRecord, song_id)
            if record is not None and record.status == Status.READY:
                return False
            await _upsert(
                session,
                song_id,
                status=Status.FAILED,
                lines=None,
                line_count=0,
                error_code=code,
                error_message=message,
                source_event_id=event_id,
            )
            return True


async def _upsert(session: AsyncSession, song_id: uuid.UUID, **fields: Any) -> None:
    now = datetime.now(UTC)
    record = await session.get(LyricsRecord, song_id)
    if record is None:
        session.add(LyricsRecord(song_id=song_id, created_at=now, updated_at=now, **fields))
        return
    for name, value in fields.items():
        setattr(record, name, value)
    record.updated_at = now
