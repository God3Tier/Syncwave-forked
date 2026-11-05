"""Shared fixtures. The tests use SQLite (aiosqlite) instead of Postgres, and a
fake Catalogue so no test needs a network."""

import os
import tempfile
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine

from playlist_service.api.main import app
from playlist_service.auth import Account, current_account
from playlist_service.db import Base
from playlist_service.errors import CatalogueUnavailable

# Read by the API's lifespan through get_settings().
API_DATABASE = Path(tempfile.gettempdir()) / f"syncwave-playlist-api-tests-{os.getpid()}.db"
# The tests start no gRPC server; tests/test_grpc.py builds its own.
os.environ["GRPC_PORT"] = "0"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{API_DATABASE.as_posix()}"

OWNER_ID = "5d1f3a7e-2b94-4c60-8e15-a7c3f9b2d041"


@pytest.fixture
def api_db() -> Iterator[Engine]:
    """A fresh schema in the API's database."""
    engine = create_engine(f"sqlite:///{API_DATABASE.as_posix()}")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


class FakeCatalogue:
    """Knows every song by default; `known` limits it, `down` makes it unreachable."""

    def __init__(self, known: set[uuid.UUID] | None = None, *, down: bool = False) -> None:
        self.known = known
        self.down = down
        self.asked: list[uuid.UUID] = []

    async def exists(self, song_id: uuid.UUID) -> bool:
        self.asked.append(song_id)
        if self.down:
            raise CatalogueUnavailable("the Catalogue is down")
        return self.known is None or song_id in self.known


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def catalogue() -> FakeCatalogue:
    return FakeCatalogue()


@pytest.fixture
def client(api_db: Engine, catalogue: FakeCatalogue) -> Iterator[TestClient]:
    app.dependency_overrides[current_account] = lambda: Account(uuid.UUID(OWNER_ID))
    with TestClient(app) as test_client:
        # Replace the real HTTP client the lifespan built.
        app.state.catalogue = catalogue
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def create_playlist(client: TestClient) -> Callable[..., dict[str, Any]]:
    def create(name: str = "Rainy day", owner_id: str = OWNER_ID) -> dict[str, Any]:
        app.dependency_overrides[current_account] = lambda: Account(uuid.UUID(owner_id))
        response = client.post("/playlists", json={"name": name})
        assert response.status_code == 201, response.text
        app.dependency_overrides[current_account] = lambda: Account(uuid.UUID(OWNER_ID))
        return response.json()

    return create


@pytest.fixture
def song_ids() -> Callable[[int], list[str]]:
    def make(count: int) -> list[str]:
        return [str(uuid.uuid4()) for _ in range(count)]

    return make


@pytest.fixture
def playlist_with_songs(
    client: TestClient,
    create_playlist: Callable[..., dict[str, Any]],
    song_ids: Callable[[int], list[str]],
) -> Callable[[int], tuple[str, list[str]]]:
    """A playlist holding `count` songs; returns its id and the songs in order."""

    def build(count: int) -> tuple[str, list[str]]:
        playlist_id = create_playlist()["playlist_id"]
        songs = song_ids(count)
        for song_id in songs:
            response = client.post(f"/playlists/{playlist_id}/songs", json={"song_id": song_id})
            assert response.status_code == 200, response.text
        return playlist_id, songs

    return build


def pytest_sessionfinish() -> None:
    try:
        API_DATABASE.unlink(missing_ok=True)
    except PermissionError:
        pass  # Windows: still open; it is in the temp folder anyway
