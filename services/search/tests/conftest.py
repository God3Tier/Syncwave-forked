"""Shared fixtures. The tests use SQLite (aiosqlite) instead of Postgres, and
in-memory fakes instead of RabbitMQ/Catalogue."""

import json
import os
import tempfile
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine

from search_service.api.main import app
from search_service.shared.catalogue_client import SongData
from search_service.shared.db import Base, Database, SearchRepository
from search_service.shared.errors import PermanentError
from search_service.shared.events import QUEUE_SONG_READY

API_DATABASE = Path(tempfile.gettempdir()) / f"syncwave-search-api-tests-{os.getpid()}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{API_DATABASE.as_posix()}"
os.environ.setdefault("CATALOGUE_URL", "http://catalogue:8080")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# ── API ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def api_db() -> Iterator[Engine]:
    engine = create_engine(f"sqlite:///{API_DATABASE.as_posix()}")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def client(api_db: Engine) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def pytest_sessionfinish() -> None:
    try:
        API_DATABASE.unlink(missing_ok=True)
    except PermissionError:
        pass


# ── worker ──────────────────────────────────────────────────────────────────


class FakeMessage:
    def __init__(self, body: bytes, headers: dict[str, Any]) -> None:
        self.body = body
        self.headers = headers
        self.message_id = str(uuid.uuid4())
        self.content_type = "application/json"
        self.content_encoding = None
        self.correlation_id = None
        self.timestamp = None
        self.type = "SongReady"
        self.app_id = "catalogue"
        self.outcome: str | None = None

    async def ack(self) -> None:
        self._settle("ack")

    async def reject(self, requeue: bool = False) -> None:
        self._settle("requeue" if requeue else "retry")

    def _settle(self, outcome: str) -> None:
        assert self.outcome is None, f"message settled twice: {self.outcome}, then {outcome}"
        self.outcome = outcome


class FakePublisher:
    def __init__(self) -> None:
        self.dead_lettered: list[tuple[str, bytes]] = []

    async def dead_letter(self, message: FakeMessage, queue: str) -> None:
        self.dead_lettered.append((queue, message.body))


class FakeCatalogueClient:
    def __init__(self, songs: dict[str, SongData] | None = None) -> None:
        self.songs = songs or {}

    async def get_song(self, song_id) -> SongData:
        key = str(song_id)
        if key in self.songs:
            return self.songs[key]
        raise PermanentError("SONG_NOT_FOUND", f"No song {song_id}")


@pytest.fixture
async def repository(tmp_path: Path) -> AsyncIterator[SearchRepository]:
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'worker.db').as_posix()}")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield SearchRepository(database.sessions)
    await database.dispose()


@pytest.fixture
def publisher() -> FakePublisher:
    return FakePublisher()


@pytest.fixture
def catalogue_client() -> FakeCatalogueClient:
    return FakeCatalogueClient()


@pytest.fixture
def handler(repository, publisher, catalogue_client):
    from search_service.worker.handler import SearchHandler

    return SearchHandler(repository, publisher, catalogue_client)


@pytest.fixture
def song_ready() -> Callable[..., dict[str, Any]]:
    def build(
        *, song_id: str | None = None, title: str = "Demo", artist: str = "Artist"
    ) -> dict[str, Any]:
        song_id = song_id or str(uuid.uuid4())
        event_id = str(uuid.uuid4())
        return {
            "event_id": event_id,
            "event_type": "SongReady",
            "version": 1,
            "song_id": song_id,
            "timestamp": "2026-10-08T12:05:00.000Z",
            "producer": "catalogue",
            "payload": {"song_id": song_id},
            "_title": title,
            "_artist": artist,
        }

    return build


@pytest.fixture
def make_message() -> Callable[..., FakeMessage]:
    def make(event: dict[str, Any] | bytes, *, failures: int = 0) -> FakeMessage:
        body = (
            event
            if isinstance(event, bytes)
            else json.dumps({k: v for k, v in event.items() if not k.startswith("_")}).encode()
        )
        headers: dict[str, Any] = {}
        if failures:
            headers["x-death"] = [
                {"queue": QUEUE_SONG_READY, "reason": "rejected", "count": failures},
                {"queue": f"{QUEUE_SONG_READY}.retry", "reason": "expired", "count": failures},
            ]
        return FakeMessage(body, headers)

    return make
