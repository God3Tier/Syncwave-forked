from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from playlist_service.db import Base

SERVICE_DIR = Path(__file__).resolve().parents[1]


def test_migrations_upgrade_match_the_models_and_downgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "migrations.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database.as_posix()}")
    config = Config(str(SERVICE_DIR / "alembic.ini"))
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    try:
        command.upgrade(config, "head")
        assert {"playlists", "playlist_songs"} <= set(inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []

        command.downgrade(config, "base")
        assert "playlists" not in inspect(engine).get_table_names()
        assert "playlist_songs" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()
