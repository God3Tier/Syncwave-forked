"""Real API/SQLite transactions with deterministic storage and broker adapters."""

import io
import wave
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from upload_service import main
from upload_service.db import Base


@dataclass
class FakeStorage:
    objects: dict[str, bytes] = field(default_factory=dict)
    content_types: dict[str, str] = field(default_factory=dict)
    deleted: list[str] = field(default_factory=list)
    fail_extension: str | None = None

    def put(self, key: str, file: BinaryIO, content_type: str) -> None:
        self.objects[key] = file.read()
        self.content_types[key] = content_type
        if self.fail_extension and key.endswith(self.fail_extension):
            raise OSError("simulated S3 timeout after writing")

    def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)

    def ready(self) -> None:
        pass

    def close(self) -> None:
        pass


@dataclass
class FakePublisher:
    events: list[dict[str, Any]] = field(default_factory=list)
    fail: bool = False

    async def publish(self, event: dict[str, Any]) -> None:
        if self.fail:
            raise ConnectionError("simulated broker outage")
        self.events.append(event)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, storage: FakeStorage
) -> Iterator[TestClient]:
    path = (tmp_path / "upload.db").as_posix()
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    monkeypatch.setenv("UPLOAD_MAX_AUDIO_BYTES", "4096")
    monkeypatch.setenv("UPLOAD_MAX_LYRICS_BYTES", "256")
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    monkeypatch.setattr(main, "S3Storage", lambda _: storage)
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture
def wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * 80)
    return buffer.getvalue()


def run(client: TestClient, operation: Any, *args: Any) -> Any:
    """Run database work on the same event loop as the API."""
    assert client.portal is not None
    return client.portal.call(operation, *args)
