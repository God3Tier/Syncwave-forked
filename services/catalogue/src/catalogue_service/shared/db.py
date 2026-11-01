"""Catalogue storage: one row per song in this service's own database (plan.md §11).

The row's processing_status is the derived idempotency state: a song whose
processing is READY is never reverted by a stale failure (plan.md §16).
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Uuid
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class StageStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


class ProcessingStatus(StrEnum):
    PROCESSING = "PROCESSING"
    PARTIAL = "PARTIAL"
    READY = "READY"
    FAILED = "FAILED"


class Base(DeclarativeBase):
    pass


class SongRecord(Base):
    __tablename__ = "songs"
    __table_args__ = (
        CheckConstraint(
            "lyrics_status IN ('PENDING', 'PROCESSING', 'READY', 'FAILED')",
            name="songs_lyrics_status_valid",
        ),
        CheckConstraint(
            "waveform_status IN ('PENDING', 'PROCESSING', 'READY', 'FAILED')",
            name="songs_waveform_status_valid",
        ),
        CheckConstraint(
            "processing_status IN ('PROCESSING', 'PARTIAL', 'READY', 'FAILED')",
            name="songs_processing_status_valid",
        ),
    )

    song_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    title: Mapped[str] = mapped_column(String(256))
    artist: Mapped[str] = mapped_column(String(256))
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_reference: Mapped[str] = mapped_column(String(1024))
    mood: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lyrics_reference: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    lyrics_status: Mapped[str] = mapped_column(String(16))
    waveform_status: Mapped[str] = mapped_column(String(16))
    processing_status: Mapped[str] = mapped_column(String(16))
    # event_id of the SongUploaded event that created this record
    source_event_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def derive_processing_status(lyrics_status: str, waveform_status: str) -> str:
    """Derive overall readiness from the two stage statuses (contracts/README.md)."""
    lyrics_ready = lyrics_status == StageStatus.READY
    waveform_ready = waveform_status == StageStatus.READY
    lyrics_failed = lyrics_status == StageStatus.FAILED
    waveform_failed = waveform_status == StageStatus.FAILED
    if lyrics_ready and waveform_ready:
        return ProcessingStatus.READY
    if lyrics_failed and waveform_failed:
        return ProcessingStatus.FAILED
    if (lyrics_ready and waveform_failed) or (lyrics_failed and waveform_ready):
        return ProcessingStatus.PARTIAL
    return ProcessingStatus.PROCESSING


class Database:
    def __init__(self, url: str) -> None:
        self.engine = create_async_engine(url, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def dispose(self) -> None:
        await self.engine.dispose()


class CatalogueRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, song_id: uuid.UUID) -> SongRecord | None:
        async with self._sessions() as session:
            return await session.get(SongRecord, song_id)

    async def create_song(
        self,
        song_id: uuid.UUID,
        title: str,
        artist: str,
        audio_reference: str,
        lyrics_reference: str | None,
        duration_ms: int | None,
        event_id: str,
        mood: str | None = None,
    ) -> tuple[SongRecord, bool]:
        """Inserts a new song. Returns (record, created). If a song with this
        song_id already exists (duplicate upload event), returns it unchanged
        with created=False: the first write wins."""
        async with self._sessions.begin() as session:
            existing = await session.get(SongRecord, song_id)
            if existing is not None:
                return existing, False
            now = datetime.now(UTC)
            lyrics_status = StageStatus.READY if not lyrics_reference else StageStatus.PROCESSING
            waveform_status = StageStatus.PROCESSING
            record = SongRecord(
                song_id=song_id,
                title=title,
                artist=artist,
                duration_ms=duration_ms,
                audio_reference=audio_reference,
                mood=mood,
                lyrics_reference=lyrics_reference,
                lyrics_status=lyrics_status,
                waveform_status=waveform_status,
                processing_status=derive_processing_status(lyrics_status, waveform_status),
                source_event_id=event_id,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
            return record, True

    async def set_lyrics_status(
        self, song_id: uuid.UUID, status: str, event_id: str | None
    ) -> SongRecord | None:
        """Updates lyrics_status, never overwriting an already READY result.
        Recomputes processing_status. Returns the updated record, or None if
        the song does not exist."""
        async with self._sessions.begin() as session:
            record = await session.get(SongRecord, song_id)
            if record is None:
                return None
            if record.lyrics_status == StageStatus.READY:
                return record
            record.lyrics_status = status
            record.source_event_id = event_id
            record.processing_status = derive_processing_status(
                record.lyrics_status, record.waveform_status
            )
            record.updated_at = datetime.now(UTC)
            return record

    async def set_waveform_status(
        self,
        song_id: uuid.UUID,
        status: str,
        event_id: str | None,
        duration_ms: int | None = None,
    ) -> SongRecord | None:
        """Updates waveform_status (and duration_ms when reported), never
        overwriting an already READY result. Recomputes processing_status.
        Returns the updated record, or None if the song does not exist."""
        async with self._sessions.begin() as session:
            record = await session.get(SongRecord, song_id)
            if record is None:
                return None
            if record.waveform_status == StageStatus.READY:
                return record
            record.waveform_status = status
            if duration_ms is not None:
                record.duration_ms = duration_ms
            record.source_event_id = event_id
            record.processing_status = derive_processing_status(
                record.lyrics_status, record.waveform_status
            )
            record.updated_at = datetime.now(UTC)
            return record
