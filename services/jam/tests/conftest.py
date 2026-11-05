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

from jam_service.main import app, manager, playlist_client  # noqa: E402


class FakeAuthVerifier:
    def account(self, token: str) -> UUID:
        return UUID(token)


@pytest.fixture(autouse=True)
def clear_jams() -> Iterator[None]:
    manager._jams.clear()
    playlist_client.playlists.clear()
    yield


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as value:
        app.state.auth_verifier = FakeAuthVerifier()
        yield value


def pytest_sessionfinish() -> None:
    TEST_DATABASE_PATH.unlink(missing_ok=True)
