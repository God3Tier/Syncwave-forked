"""Search storage: one row per indexed (ready) song in this service's own DB."""

import base64
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Uuid, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SearchRecord(Base):
    __tablename__ = "search_index"

    song_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    title: Mapped[str] = mapped_column(String(256))
    artist: Mapped[str] = mapped_column(String(256))
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Database:
    def __init__(self, url: str) -> None:
        self.engine = create_async_engine(url, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def dispose(self) -> None:
        await self.engine.dispose()


class SearchRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def upsert(self, song_id: uuid.UUID, title: str, artist: str) -> SearchRecord:
        """Insert or update the indexed row for a song. Idempotent: re-indexing
        keeps indexed_at, so a duplicate SongReady or a rebuild does not move the
        song to the top of the results."""
        now = datetime.now(UTC)
        try:
            async with self._sessions.begin() as session:
                record = await session.get(SearchRecord, song_id)
                if record is None:
                    record = SearchRecord(
                        song_id=song_id,
                        title=title,
                        artist=artist,
                        indexed_at=now,
                    )
                    session.add(record)
                else:
                    record.title = title
                    record.artist = artist
                await session.flush()
                return record
        except IntegrityError:
            async with self._sessions.begin() as session:
                record = await session.get(SearchRecord, song_id)
                if record is None:
                    raise
                record.title = title
                record.artist = artist
                return record

    async def get(self, song_id: uuid.UUID) -> SearchRecord | None:
        async with self._sessions() as session:
            return await session.get(SearchRecord, song_id)

    async def search(
        self,
        query: str | None,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[SearchRecord], str | None]:
        stmt = select(SearchRecord)
        if query:
            cleaned = query.strip()
            if cleaned:
                q = cleaned.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                lowered = f"%{q}%"
                stmt = stmt.where(
                    SearchRecord.title.ilike(lowered, escape="\\")
                    | SearchRecord.artist.ilike(lowered, escape="\\")
                )
        if cursor is not None:
            cursor_indexed_at, cursor_song_id = decode_cursor(cursor)
            stmt = stmt.where(
                (SearchRecord.indexed_at < cursor_indexed_at)
                | (
                    (SearchRecord.indexed_at == cursor_indexed_at)
                    & (SearchRecord.song_id < cursor_song_id)
                )
            )
        stmt = stmt.order_by(SearchRecord.indexed_at.desc(), SearchRecord.song_id.desc()).limit(
            limit + 1
        )
        async with self._sessions() as session:
            rows = (await session.scalars(stmt)).all()
        has_more = len(rows) > limit
        rows = list(rows[:limit])
        next_cursor: str | None = None
        if has_more and rows:
            next_cursor = encode_cursor(rows[-1].indexed_at, rows[-1].song_id)
        return rows, next_cursor


def encode_cursor(indexed_at: datetime, song_id: uuid.UUID) -> str:
    payload = json.dumps({"indexed_at": indexed_at.isoformat(), "song_id": str(song_id)}).encode()
    return base64.urlsafe_b64encode(payload).decode()


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Raises ValueError for a token encode_cursor did not produce."""
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return datetime.fromisoformat(payload["indexed_at"]), uuid.UUID(payload["song_id"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("invalid cursor") from exc
