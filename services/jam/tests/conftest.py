import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

TEST_DATABASE_PATH = Path(tempfile.gettempdir()) / f"syncwave-jam-tests-{os.getpid()}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DATABASE_PATH.as_posix()}"
os.environ["SYNC_GRPC_TARGET"] = ""
os.environ["PLAYLIST_GRPC_TARGET"] = ""
os.environ["CATALOGUE_HTTP_URL"] = ""

from jam_service.auth import AccountIdentity  # noqa: E402
from jam_service.main import app, catalogue_client, manager, playlist_client  # noqa: E402


class FakeAuthVerifier:
    def account(self, token: str) -> AccountIdentity:
        user_id = UUID(token)
        return AccountIdentity(user_id=user_id, username=f"user_{str(user_id)[:8]}")


@pytest.fixture(autouse=True)
def clear_jams() -> Iterator[None]:
    manager._jams.clear()
    playlist_client.playlists.clear()
    catalogue_client.songs.clear()
    catalogue_client.plays.clear()
    yield


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as value:
        app.state.auth_verifier = FakeAuthVerifier()
        yield value


def pytest_sessionfinish() -> None:
    TEST_DATABASE_PATH.unlink(missing_ok=True)
