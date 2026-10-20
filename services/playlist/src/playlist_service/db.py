"""Playlist storage: this service's own database (plan.md §11).

Two tables. `playlists` holds one row per playlist. `playlist_songs` holds
one row per song in a playlist, with its `position`. Only song ids are stored;
titles, artists and audio belong to the Catalogue and Streaming services.

Every change to a playlist's songs follows the same steps: lock the playlist
row, read the current order, compute the new order (ordering.py), write it
back. Locking the row makes two simultaneous edits to one playlist run one
after the other instead of overwriting each other.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Uuid,
    delete,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from playlist_service import ordering
from playlist_service.errors import PlaylistNotFound
from playlist_service.ordering import Order, Shuffler


class Base(DeclarativeBase):
    pass


class PlaylistRecord(Base):
    __tablename__ = "playlists"

    playlist_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PlaylistSongRecord(Base):
    __tablename__ = "playlist_songs"
    __table_args__ = (CheckConstraint("position >= 0", name="playlist_songs_position_valid"),)

    playlist_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("playlists.playlist_id", ondelete="CASCADE"), primary_key=True
    )
    song_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    position: Mapped[int] = mapped_column(Integer)


@dataclass(frozen=True, slots=True)
class PlaylistData:
    playlist_id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    songs: Order  # song ids; position is the index
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PlaylistSummaryData:
    playlist_id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    song_count: int
    created_at: datetime
    updated_at: datetime


class Database:
    def __init__(self, url: str) -> None:
        self.engine = create_async_engine(url, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def dispose(self) -> None:
        await self.engine.dispose()


class PlaylistRepository:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        shuffler: Shuffler = ordering.shuffled,
    ) -> None:
        self._sessions = sessions
        self._shuffler = shuffler

    # ── playlists ───────────────────────────────────────────────────────────

    async def create(self, owner_id: uuid.UUID, name: str) -> PlaylistData:
        now = datetime.now(UTC)
        record = PlaylistRecord(
            playlist_id=uuid.uuid4(),
            owner_id=owner_id,
            name=name,
            created_at=now,
            updated_at=now,
        )
        async with self._sessions.begin() as session:
            session.add(record)
        return _data(record, [])

    async def get(self, playlist_id: uuid.UUID) -> PlaylistData | None:
        async with self._sessions() as session:
            record = await session.get(PlaylistRecord, playlist_id)
            if record is None:
                return None
            return _data(record, await _read_order(session, playlist_id))

    async def list_for_owner(
        self, owner_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[PlaylistSummaryData], bool]:
        """Newest first. Returns one page and whether more playlists follow it."""
        statement = (
            select(PlaylistRecord, func.count(PlaylistSongRecord.song_id))
            .outerjoin(
                PlaylistSongRecord, PlaylistSongRecord.playlist_id == PlaylistRecord.playlist_id
            )
            .where(PlaylistRecord.owner_id == owner_id)
            .group_by(PlaylistRecord.playlist_id)
            .order_by(PlaylistRecord.created_at.desc(), PlaylistRecord.playlist_id.desc())
            .limit(limit + 1)  # one extra row tells us whether there is a next page
            .offset(offset)
        )
        async with self._sessions() as session:
            rows = (await session.execute(statement)).all()
        summaries = [
            PlaylistSummaryData(
                playlist_id=record.playlist_id,
                owner_id=record.owner_id,
                name=record.name,
                song_count=song_count,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
            for record, song_count in rows[:limit]
        ]
        return summaries, len(rows) > limit

    async def rename(self, playlist_id: uuid.UUID, name: str) -> PlaylistData:
        async with self._sessions.begin() as session:
            record = await _lock(session, playlist_id)
            record.name = name
            record.updated_at = datetime.now(UTC)
            return _data(record, await _read_order(session, playlist_id))

    async def delete(self, playlist_id: uuid.UUID) -> None:
        async with self._sessions.begin() as session:
            await _lock(session, playlist_id)
            # Deleted explicitly rather than relying on ON DELETE CASCADE, which
            # SQLite (used by the tests) does not enforce by default.
            await session.execute(
                delete(PlaylistSongRecord).where(PlaylistSongRecord.playlist_id == playlist_id)
            )
            await session.execute(
                delete(PlaylistRecord).where(PlaylistRecord.playlist_id == playlist_id)
            )

    # ── songs in a playlist ─────────────────────────────────────────────────

    async def add_song(
        self, playlist_id: uuid.UUID, song_id: uuid.UUID, position: int | None
    ) -> PlaylistData:
        return await self._change_order(
            playlist_id, lambda order: ordering.add_song(order, song_id, position)
        )

    async def remove_song(self, playlist_id: uuid.UUID, song_id: uuid.UUID) -> PlaylistData:
        return await self._change_order(
            playlist_id, lambda order: ordering.remove_song(order, song_id)
        )

    async def reorder(self, playlist_id: uuid.UUID, new_order: Order) -> PlaylistData:
        return await self._change_order(
            playlist_id, lambda order: ordering.reorder(order, new_order)
        )

    async def shuffle(self, playlist_id: uuid.UUID) -> PlaylistData:
        """Saves a new random order, so every later read returns the same one."""
        return await self._change_order(playlist_id, self._shuffler)

    async def _change_order(
        self, playlist_id: uuid.UUID, change: Callable[[Order], Order]
    ) -> PlaylistData:
        async with self._sessions.begin() as session:
            record = await _lock(session, playlist_id)
            new_order = change(await _read_order(session, playlist_id))
            await session.execute(
                delete(PlaylistSongRecord).where(PlaylistSongRecord.playlist_id == playlist_id)
            )
            session.add_all(
                PlaylistSongRecord(playlist_id=playlist_id, song_id=song_id, position=position)
                for position, song_id in enumerate(new_order)
            )
            record.updated_at = datetime.now(UTC)
            return _data(record, new_order)


async def _lock(session: AsyncSession, playlist_id: uuid.UUID) -> PlaylistRecord:
    """The playlist row, locked until the transaction ends (a no-op on SQLite)."""
    record = (
        await session.execute(
            select(PlaylistRecord)
            .where(PlaylistRecord.playlist_id == playlist_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if record is None:
        raise PlaylistNotFound(f"No playlist with id {playlist_id}")
    return record


async def _read_order(session: AsyncSession, playlist_id: uuid.UUID) -> Order:
    rows = await session.execute(
        select(PlaylistSongRecord.song_id)
        .where(PlaylistSongRecord.playlist_id == playlist_id)
        .order_by(PlaylistSongRecord.position)
    )
    return list(rows.scalars())


def _data(record: PlaylistRecord, songs: Order) -> PlaylistData:
    return PlaylistData(
        playlist_id=record.playlist_id,
        owner_id=record.owner_id,
        name=record.name,
        songs=songs,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
