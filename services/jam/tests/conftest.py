import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_DATABASE_PATH = Path(tempfile.gettempdir()) / f"syncwave-jam-tests-{os.getpid()}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DATABASE_PATH.as_posix()}"
os.environ["SYNC_GRPC_TARGET"] = ""

from jam_service.main import app, manager  # noqa: E402


@pytest.fixture(autouse=True)
def clear_jams() -> Iterator[None]:
    manager._jams.clear()
    yield


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app, headers={"x-jam-token": "local-jam-member-token"}) as value:
        yield value


def pytest_sessionfinish() -> None:
    TEST_DATABASE_PATH.unlink(missing_ok=True)
