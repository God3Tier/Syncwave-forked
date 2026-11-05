import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_DATABASE_PATH = Path(tempfile.gettempdir()) / f"syncwave-sync-tests-{os.getpid()}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DATABASE_PATH.as_posix()}"
os.environ["GRPC_PORT"] = "0"

from sync_service.main import app, manager  # noqa: E402 - test DB must be set before app import


@pytest.fixture(autouse=True)
def clear_sessions() -> Iterator[None]:
    manager._sessions.clear()
    manager._request_results.clear()
    yield


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def pytest_sessionfinish() -> None:
    TEST_DATABASE_PATH.unlink(missing_ok=True)
