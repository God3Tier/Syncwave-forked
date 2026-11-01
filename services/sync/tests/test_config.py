import pytest
from sqlalchemy.engine import make_url

from sync_service.config import database_url

DB_VARIABLES = {
    "DB_HOST": "db.internal",
    "DB_PORT": "6543",
    "DB_NAME": "sync",
    "DB_USER": "sync",
    "DB_PASSWORD": "p@ss:w/rd%",
}


def test_database_url_wins_over_db_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in DB_VARIABLES.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///sync.db")

    assert database_url() == "sqlite+aiosqlite:///sync.db"


def test_url_is_built_from_db_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for name, value in DB_VARIABLES.items():
        monkeypatch.setenv(name, value)

    url = make_url(database_url())

    assert url.drivername == "postgresql+asyncpg"
    assert (url.host, url.port, url.database, url.username) == ("db.internal", 6543, "sync", "sync")
    # Special characters in the password survive the round trip
    assert url.password == "p@ss:w/rd%"
