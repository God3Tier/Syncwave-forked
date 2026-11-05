import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Uuid, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserRecord(Base):
    __tablename__ = "users"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UsernameTaken(Exception):
    pass


class Database:
    def __init__(self, url: str) -> None:
        self.engine = create_async_engine(url, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def dispose(self) -> None:
        await self.engine.dispose()


class UserRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get_by_username(self, username: str) -> UserRecord | None:
        async with self._sessions() as session:
            return await session.scalar(select(UserRecord).where(UserRecord.username == username))

    async def get_by_id(self, user_id: uuid.UUID) -> UserRecord | None:
        async with self._sessions() as session:
            return await session.get(UserRecord, user_id)

    async def create(self, username: str, password_hash: str) -> UserRecord:
        user = UserRecord(
            user_id=uuid.uuid4(),
            username=username,
            password_hash=password_hash,
            created_at=datetime.now(UTC),
        )
        try:
            async with self._sessions.begin() as session:
                session.add(user)
                await session.flush()
        except IntegrityError as error:
            raise UsernameTaken(username) from error
        return user
