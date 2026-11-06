from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String, delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from jam_service.models import JamLifecycle, JamState, QueueItem


class Base(DeclarativeBase):
    pass


class JamRecord(Base):
    __tablename__ = "jams"

    jam_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    join_code: Mapped[str] = mapped_column(String(8), unique=True, index=True)
    owner_id: Mapped[str] = mapped_column(String(36))
    state: Mapped[str] = mapped_column(String(32))
    current_queue_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    sync_generation: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    lifecycle_state: Mapped[str] = mapped_column(String(16), default=JamLifecycle.ACTIVE.value)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_listener_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    autoplay_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    autoplay_seen_song_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    autoplay_prompt_deadline_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    autoplay_batch_number: Mapped[int] = mapped_column(Integer, default=0)
    autoplay_catalogue_rechecked: Mapped[bool] = mapped_column(default=False)


class JamMemberRecord(Base):
    __tablename__ = "jam_members"

    jam_id: Mapped[str] = mapped_column(
        ForeignKey("jams.jam_id", ondelete="CASCADE"), primary_key=True
    )
    participant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str | None] = mapped_column(String(24), nullable=True)


class JamQueueRecord(Base):
    __tablename__ = "jam_queue_items"

    queue_item_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    jam_id: Mapped[str] = mapped_column(ForeignKey("jams.jam_id", ondelete="CASCADE"), index=True)
    song_id: Mapped[str] = mapped_column(String(36))
    added_by: Mapped[str] = mapped_column(String(36))
    position: Mapped[int] = mapped_column(Integer)


@dataclass(slots=True)
class PersistedJam:
    jam_id: UUID
    join_code: str
    owner_id: UUID
    state: JamState
    current_queue_item_id: UUID | None
    sync_generation: int | None
    participant_ids: list[UUID]
    participant_usernames: dict[UUID, str]
    queue: list[QueueItem]
    lifecycle_state: JamLifecycle = JamLifecycle.ACTIVE
    ended_at: datetime | None = None
    last_listener_active_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    autoplay_mode: str | None = None
    autoplay_seen_song_ids: list[UUID] = field(default_factory=list)
    autoplay_prompt_deadline_ms: int | None = None
    autoplay_batch_number: int = 0
    autoplay_catalogue_rechecked: bool = False


class JamRepository:
    def __init__(self, database_url: str) -> None:
        self._engine = create_async_engine(database_url, pool_pre_ping=True)
        self._sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, expire_on_commit=False
        )

    async def initialize(self) -> None:
        async with self._engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self._engine.dispose()

    async def ping(self) -> None:
        async with self._sessions() as database:
            await database.execute(text("SELECT 1"))

    async def load(self) -> list[PersistedJam]:
        async with self._sessions() as database:
            jams = (await database.scalars(select(JamRecord))).all()
            members = (await database.scalars(select(JamMemberRecord))).all()
            queue = (
                await database.scalars(select(JamQueueRecord).order_by(JamQueueRecord.position))
            ).all()
        return [
            PersistedJam(
                jam_id=UUID(row.jam_id),
                join_code=row.join_code,
                owner_id=UUID(row.owner_id),
                state=JamState(row.state),
                current_queue_item_id=(
                    UUID(row.current_queue_item_id) if row.current_queue_item_id else None
                ),
                sync_generation=row.sync_generation,
                participant_ids=[
                    UUID(member.participant_id) for member in members if member.jam_id == row.jam_id
                ],
                participant_usernames={
                    UUID(member.participant_id): (
                        member.username or f"Member {member.participant_id[:8]}"
                    )
                    for member in members
                    if member.jam_id == row.jam_id
                },
                queue=[
                    QueueItem(
                        queue_item_id=UUID(item.queue_item_id),
                        song_id=UUID(item.song_id),
                        added_by=UUID(item.added_by),
                        position=item.position,
                    )
                    for item in queue
                    if item.jam_id == row.jam_id
                ],
                lifecycle_state=JamLifecycle(row.lifecycle_state),
                ended_at=row.ended_at,
                last_listener_active_at=(
                    row.last_listener_active_at
                    if row.last_listener_active_at.tzinfo is not None
                    else row.last_listener_active_at.replace(tzinfo=UTC)
                ),
                autoplay_mode=row.autoplay_mode,
                autoplay_seen_song_ids=[
                    UUID(value) for value in (row.autoplay_seen_song_ids or [])
                ],
                autoplay_prompt_deadline_ms=row.autoplay_prompt_deadline_ms,
                autoplay_batch_number=row.autoplay_batch_number,
                autoplay_catalogue_rechecked=row.autoplay_catalogue_rechecked,
            )
            for row in jams
        ]

    async def save(self, jam: PersistedJam) -> None:
        jam_id = str(jam.jam_id)
        async with self._sessions.begin() as database:
            row = await database.get(JamRecord, jam_id)
            values = {
                "join_code": jam.join_code,
                "owner_id": str(jam.owner_id),
                "state": jam.state.value,
                "current_queue_item_id": (
                    str(jam.current_queue_item_id) if jam.current_queue_item_id else None
                ),
                "sync_generation": jam.sync_generation,
                "lifecycle_state": jam.lifecycle_state.value,
                "ended_at": jam.ended_at,
                "last_listener_active_at": jam.last_listener_active_at,
                "autoplay_mode": jam.autoplay_mode,
                "autoplay_seen_song_ids": [
                    str(value) for value in (jam.autoplay_seen_song_ids or [])
                ],
                "autoplay_prompt_deadline_ms": jam.autoplay_prompt_deadline_ms,
                "autoplay_batch_number": jam.autoplay_batch_number,
                "autoplay_catalogue_rechecked": jam.autoplay_catalogue_rechecked,
            }
            if row is None:
                database.add(JamRecord(jam_id=jam_id, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            await database.execute(delete(JamMemberRecord).where(JamMemberRecord.jam_id == jam_id))
            await database.execute(delete(JamQueueRecord).where(JamQueueRecord.jam_id == jam_id))
            database.add_all(
                [
                    JamMemberRecord(
                        jam_id=jam_id,
                        participant_id=str(member_id),
                        username=jam.participant_usernames.get(member_id),
                    )
                    for member_id in jam.participant_ids
                ]
                + [
                    JamQueueRecord(
                        queue_item_id=str(item.queue_item_id),
                        jam_id=jam_id,
                        song_id=str(item.song_id),
                        added_by=str(item.added_by),
                        position=item.position,
                    )
                    for item in jam.queue
                ]
            )

    async def touch_listener_activity(self, jam_id: UUID, active_at: datetime) -> None:
        """Persist listener presence without rewriting room membership or queue rows."""
        async with self._sessions.begin() as database:
            row = await database.get(JamRecord, str(jam_id))
            if row is not None:
                row.last_listener_active_at = active_at

    async def listener_activity(self) -> dict[UUID, datetime]:
        """Return durable activity for active rooms so expiry does not trust process cache."""
        async with self._sessions() as database:
            rows = (
                await database.execute(
                    select(JamRecord.jam_id, JamRecord.last_listener_active_at).where(
                        JamRecord.lifecycle_state == JamLifecycle.ACTIVE.value
                    )
                )
            ).all()
        return {
            UUID(jam_id): (
                active_at if active_at.tzinfo is not None else active_at.replace(tzinfo=UTC)
            )
            for jam_id, active_at in rows
        }
