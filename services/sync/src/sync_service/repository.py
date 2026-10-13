from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import JSON, BigInteger, Float, String, delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SyncSessionRecord(Base):
    __tablename__ = "sync_sessions"

    jam_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    generation: Mapped[int] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(String(32))
    queue_item_id: Mapped[str] = mapped_column(String(36))
    song_id: Mapped[str] = mapped_column(String(36))
    owner_id: Mapped[str] = mapped_column(String(36))
    participant_ids: Mapped[list[str]] = mapped_column(JSON)
    anchor_server_time_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    anchor_position_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    playback_rate: Mapped[float] = mapped_column(Float, default=1.0)
    prepare_deadline_ms: Mapped[int] = mapped_column(BigInteger)


class SyncCommandRecord(Base):
    __tablename__ = "sync_commands"

    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    jam_id: Mapped[str] = mapped_column(String(36), index=True)


@dataclass(frozen=True, slots=True)
class PersistedSession:
    jam_id: UUID
    generation: int
    state: str
    queue_item_id: UUID
    song_id: UUID
    owner_id: UUID
    participant_ids: tuple[UUID, ...]
    anchor_server_time_ms: int | None
    anchor_position_ms: int
    playback_rate: float
    prepare_deadline_ms: int


class SessionRepository:
    def __init__(self, database_url: str) -> None:
        self._engine = create_async_engine(database_url, pool_pre_ping=True)
        self._sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine,
            expire_on_commit=False,
        )

    async def initialize(self) -> None:
        async with self._engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self._engine.dispose()

    async def ping(self) -> None:
        async with self._sessions() as database:
            await database.execute(text("SELECT 1"))

    async def load(self) -> tuple[list[PersistedSession], dict[UUID, UUID]]:
        async with self._sessions() as database:
            session_rows = (await database.scalars(select(SyncSessionRecord))).all()
            command_rows = (await database.scalars(select(SyncCommandRecord))).all()

        sessions = [
            PersistedSession(
                jam_id=UUID(row.jam_id),
                generation=row.generation,
                state=row.state,
                queue_item_id=UUID(row.queue_item_id),
                song_id=UUID(row.song_id),
                owner_id=UUID(row.owner_id),
                participant_ids=tuple(UUID(value) for value in row.participant_ids),
                anchor_server_time_ms=row.anchor_server_time_ms,
                anchor_position_ms=row.anchor_position_ms,
                playback_rate=row.playback_rate,
                prepare_deadline_ms=row.prepare_deadline_ms,
            )
            for row in session_rows
        ]
        commands = {UUID(row.request_id): UUID(row.jam_id) for row in command_rows}
        return sessions, commands

    async def save_session(self, session: PersistedSession) -> None:
        async with self._sessions.begin() as database:
            await self._upsert_session(database, session)

    async def save_start(self, request_id: UUID, session: PersistedSession) -> None:
        async with self._sessions.begin() as database:
            await self._upsert_session(database, session)
            command = await database.get(SyncCommandRecord, str(request_id))
            if command is None:
                database.add(
                    SyncCommandRecord(
                        request_id=str(request_id),
                        jam_id=str(session.jam_id),
                    )
                )

    async def clear(self) -> None:
        async with self._sessions.begin() as database:
            await database.execute(delete(SyncCommandRecord))
            await database.execute(delete(SyncSessionRecord))

    @staticmethod
    async def _upsert_session(database: AsyncSession, value: PersistedSession) -> None:
        row = await database.get(SyncSessionRecord, str(value.jam_id))
        fields = {
            "generation": value.generation,
            "state": value.state,
            "queue_item_id": str(value.queue_item_id),
            "song_id": str(value.song_id),
            "owner_id": str(value.owner_id),
            "participant_ids": [str(item) for item in value.participant_ids],
            "anchor_server_time_ms": value.anchor_server_time_ms,
            "anchor_position_ms": value.anchor_position_ms,
            "playback_rate": value.playback_rate,
            "prepare_deadline_ms": value.prepare_deadline_ms,
        }
        if row is None:
            database.add(SyncSessionRecord(jam_id=str(value.jam_id), **fields))
            return
        for name, field_value in fields.items():
            setattr(row, name, field_value)
