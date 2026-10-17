"""Waveform storage: one row per song in this service's own database (plan.md §11).

The row's status is also the worker's idempotency state (plan.md §16): a
song whose waveform is READY is never processed again.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    Integer,
    LargeBinary,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, undefer

from waveform_service.shared.waveform import Bands


class Status(StrEnum):
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


class Base(DeclarativeBase):
    pass


class WaveformRecord(Base):
    __tablename__ = "waveforms"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PROCESSING', 'READY', 'FAILED')", name="waveforms_status_valid"
        ),
    )

    song_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    # Peak amplitudes 0..1, one per equal-length slice of the song; set once READY
    peaks: Mapped[list[float] | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"))
    points: Mapped[int] = mapped_column(Integer, server_default="0")
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    # Rate the audio was decoded at to compute the peaks and bands
    sample_rate: Mapped[int | None] = mapped_column(Integer)
    # Visualiser levels (shared/waveform.py Bands): one byte per band per frame,
    # band_frame_rate frames a second; set once READY. Deferred: only the bands
    # endpoint needs these bytes, so other reads skip them.
    bands: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    band_edges_hz: Mapped[list[float] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    band_frame_rate: Mapped[float | None] = mapped_column(Float)
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


class WaveformRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, song_id: uuid.UUID, *, with_bands: bool = False) -> WaveformRecord | None:
        options = [undefer(WaveformRecord.bands)] if with_bands else []
        async with self._sessions() as session:
            return await session.get(WaveformRecord, song_id, options=options)

    async def mark_processing(self, song_id: uuid.UUID, event_id: str) -> None:
        async with self._sessions.begin() as session:
            await _upsert(
                session,
                song_id,
                status=Status.PROCESSING,
                peaks=None,
                points=0,
                duration_ms=None,
                sample_rate=None,
                **NO_BANDS,
                error_code=None,
                error_message=None,
                source_event_id=event_id,
            )

    async def mark_ready(
        self,
        song_id: uuid.UUID,
        peaks: list[float],
        duration_ms: int,
        sample_rate: int,
        bands: Bands,
    ) -> None:
        async with self._sessions.begin() as session:
            await _upsert(
                session,
                song_id,
                status=Status.READY,
                peaks=peaks,
                points=len(peaks),
                duration_ms=duration_ms,
                sample_rate=sample_rate,
                bands=bands.levels,
                band_edges_hz=bands.edges_hz,
                band_frame_rate=bands.frame_rate,
                error_code=None,
                error_message=None,
            )

    async def mark_failed(
        self, song_id: uuid.UUID, event_id: str | None, code: str, message: str
    ) -> bool:
        """Records a failure. Returns False, changing nothing, if the waveform is
        already READY: successful processing is never undone (plan.md §16)."""
        async with self._sessions.begin() as session:
            record = await session.get(WaveformRecord, song_id)
            if record is not None and record.status == Status.READY:
                return False
            await _upsert(
                session,
                song_id,
                status=Status.FAILED,
                peaks=None,
                points=0,
                duration_ms=None,
                sample_rate=None,
                **NO_BANDS,
                error_code=code,
                error_message=message,
                source_event_id=event_id,
            )
            return True


NO_BANDS: dict[str, Any] = {"bands": None, "band_edges_hz": None, "band_frame_rate": None}


async def _upsert(session: AsyncSession, song_id: uuid.UUID, **fields: Any) -> None:
    now = datetime.now(UTC)
    record = await session.get(WaveformRecord, song_id)
    if record is None:
        session.add(WaveformRecord(song_id=song_id, created_at=now, updated_at=now, **fields))
        return
    for name, value in fields.items():
        setattr(record, name, value)
    record.updated_at = now
