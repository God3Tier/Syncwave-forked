import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

TEST_DB = Path(tempfile.gettempdir()) / f"syncwave-auth-tests-{os.getpid()}.db"
TEST_KEY = Path(tempfile.gettempdir()) / f"syncwave-auth-tests-{os.getpid()}.pem"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB.as_posix()}"
os.environ["JWT_PRIVATE_KEY_PATH"] = str(TEST_KEY)
os.environ["SESSION_COOKIE_SECURE"] = "false"
os.environ["APP_ORIGIN"] = "http://localhost:8080"

from auth_service.config import get_settings  # noqa: E402
from auth_service.db import Base  # noqa: E402
from auth_service.main import app  # noqa: E402


@pytest.fixture
def client() -> Iterator[TestClient]:
    engine = create_engine(f"sqlite:///{TEST_DB.as_posix()}")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    engine.dispose()
    get_settings.cache_clear()
    with TestClient(app) as value:
        yield value
    TEST_KEY.unlink(missing_ok=True)
