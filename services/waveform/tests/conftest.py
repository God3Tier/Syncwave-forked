"""Shared fixtures. The tests use SQLite (aiosqlite) instead of Postgres,
in-memory fakes instead of RabbitMQ and S3, and a fake decoder that reads raw
PCM instead of running ffmpeg (test_waveform.py covers ffmpeg itself)."""

import json
import os
import tempfile
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any, BinaryIO

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine

from waveform_service.api.main import app
from waveform_service.shared.db import Base, Database, WaveformRepository
from waveform_service.shared.errors import PermanentError
from waveform_service.shared.events import QUEUE
from waveform_service.shared.storage import ObjectNotFound, ObjectTooLarge
from waveform_service.worker.handler import WaveformHandler

# Read by the API's lifespan through get_settings().
API_DATABASE = Path(tempfile.gettempdir()) / f"syncwave-waveform-api-tests-{os.getpid()}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{API_DATABASE.as_posix()}"

MAX_BYTES = 1024
POINTS = 4
SAMPLE_RATE = 8
# Band levels 4 times a second at 8 Hz is one frame every 2 samples:
# the 8 samples below make 4 frames of 3 bands.
FRAME_RATE = 4
BAND_COUNT = 3
# 8 samples at 8 Hz: 1 second, peaks [0.5, 1.0, 0.0, 0.003] in 4 slices
PCM = np.array([0, 16384, -32768, 8192, 0, 0, 100, -100], dtype="<i2").tobytes()
UNDECODABLE = b"BAD not audio"


def fake_decoder(path: str) -> np.ndarray:
    data = Path(path).read_bytes()
    if data.startswith(b"BAD"):
        raise PermanentError("AUDIO_UNDECODABLE", "ffmpeg could not decode the audio")
    return np.frombuffer(data, dtype="<i2")


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


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.downloads: list[str] = []

    def download(self, key: str, destination: BinaryIO, max_bytes: int) -> None:
        self.downloads.append(key)
        if key not in self.objects:
            raise ObjectNotFound(f"S3 object {key} does not exist")
        if len(self.objects[key]) > max_bytes:
            raise ObjectTooLarge(f"S3 object {key} is larger than {max_bytes} bytes")
        destination.write(self.objects[key])


@pytest.fixture
async def repository(tmp_path: Path) -> AsyncIterator[WaveformRepository]:
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'worker.db').as_posix()}")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield WaveformRepository(database.sessions)
    await database.dispose()


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def publisher() -> FakePublisher:
    return FakePublisher()


@pytest.fixture
def handler(
    repository: WaveformRepository, storage: FakeStorage, publisher: FakePublisher
) -> WaveformHandler:
    return WaveformHandler(
        repository,
        storage,
        publisher,
        decoder=fake_decoder,
        sample_rate=SAMPLE_RATE,
        points=POINTS,
        frame_rate=FRAME_RATE,
        band_count=BAND_COUNT,
        max_bytes=MAX_BYTES,
    )


@pytest.fixture
def song_uploaded() -> Callable[..., dict[str, Any]]:
    """Builds a SongUploaded event (contracts/events/song-uploaded.schema.json)."""

    def build(*, song_id: str | None = None) -> dict[str, Any]:
        song_id = song_id or str(uuid.uuid4())
        event_id = str(uuid.uuid4())
        return {
            "event_id": event_id,
            "event_type": "SongUploaded",
            "version": 1,
            "song_id": song_id,
            "timestamp": "2026-10-08T12:00:00.000Z",
            "producer": "upload",
            "correlation_id": event_id,
            "payload": {
                "audio_reference": f"audio/{song_id}.mp3",
                "lyrics_reference": f"lyrics/{song_id}.lrc",
            },
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
