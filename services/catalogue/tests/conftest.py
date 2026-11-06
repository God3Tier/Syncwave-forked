"""Shared fixtures. The tests use SQLite (aiosqlite) instead of Postgres, and
in-memory fakes instead of RabbitMQ."""

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

from catalogue_service.api.main import app
from catalogue_service.shared.db import Base, CatalogueRepository, Database
from catalogue_service.shared.events import QUEUE_SONG_UPLOADED as QUEUE

# Read by the API's lifespan through get_settings().
API_DATABASE = Path(tempfile.gettempdir()) / f"syncwave-catalogue-api-tests-{os.getpid()}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{API_DATABASE.as_posix()}"

MAX_BYTES = 1024  # unused by Catalogue (no S3 reads); kept for fixture symmetry


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# ── API ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def api_db() -> Iterator[Engine]:
    """A fresh schema in the API's database; seed rows through this engine."""
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
        pass  # Windows: still open; it is in the temp folder anyway


# ── worker ──────────────────────────────────────────────────────────────────


class FakeMessage:
    """Stands in for aio_pika's IncomingMessage and records how it was settled."""

    def __init__(self, body: bytes, headers: dict[str, Any]) -> None:
        self.body = body
        self.headers = headers
        self.message_id = str(uuid.uuid4())
        self.content_type = "application/json"
        self.content_encoding = None
        self.correlation_id = None
        self.timestamp = None
        self.type = "SongUploaded"
        self.app_id = "upload"
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
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.dead_lettered: list[tuple[str, bytes]] = []

    async def publish_event(self, event: dict[str, Any], routing_key: str) -> None:
        self.events.append((routing_key, event))

    async def dead_letter(self, message: FakeMessage, queue: str) -> None:
        self.dead_lettered.append((queue, message.body))


@pytest.fixture
async def repository(tmp_path: Path) -> AsyncIterator[CatalogueRepository]:
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'worker.db').as_posix()}")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield CatalogueRepository(database.sessions)
    await database.dispose()


@pytest.fixture
def publisher() -> FakePublisher:
    return FakePublisher()


@pytest.fixture
def handler(repository: CatalogueRepository, publisher: FakePublisher):
    from catalogue_service.worker.handler import CatalogueHandler

    return CatalogueHandler(repository, publisher)


@pytest.fixture
def song_uploaded() -> Callable[..., dict[str, Any]]:
    """Builds a SongUploaded event (contracts/events/song-uploaded.schema.json)."""

    def build(
        *,
        song_id: str | None = None,
        lyrics_reference: str | None = None,
        title: str = "Demo",
        artist: str = "SyncWave Artist",
        audio_reference: str | None = None,
        duration_ms: int | None = None,
        uploader_id: str | None = None,
    ) -> dict[str, Any]:
        song_id = song_id or str(uuid.uuid4())
        event_id = str(uuid.uuid4())
        payload: dict[str, Any] = {
            "audio_reference": audio_reference or f"audio/{song_id}.mp3",
            "title": title,
            "artist": artist,
        }
        if lyrics_reference is not None:
            payload["lyrics_reference"] = lyrics_reference or f"lyrics/{song_id}.lrc"
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        if uploader_id is not None:
            payload["uploader_id"] = uploader_id
        return {
            "event_id": event_id,
            "event_type": "SongUploaded",
            "version": 1,
            "song_id": song_id,
            "timestamp": "2026-10-08T12:00:00.000Z",
            "producer": "upload",
            "correlation_id": event_id,
            "payload": payload,
        }

    return build


@pytest.fixture
def make_message() -> Callable[..., FakeMessage]:
    """A delivery of `event`; `failures` earlier attempts are recorded in x-death
    the way RabbitMQ records a trip through the retry queue."""

    def make(event: dict[str, Any] | bytes, *, failures: int = 0) -> FakeMessage:
        body = event if isinstance(event, bytes) else json.dumps(event).encode()
        headers: dict[str, Any] = {}
        if failures:
            headers["x-death"] = [
                {"queue": QUEUE, "reason": "rejected", "count": failures},
                {"queue": f"{QUEUE}.retry", "reason": "expired", "count": failures},
            ]
        return FakeMessage(body, headers)

    return make
