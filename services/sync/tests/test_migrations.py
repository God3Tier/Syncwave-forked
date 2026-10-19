import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_initial_migration_upgrades_and_downgrades(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    config = Config("alembic.ini")
    try:
        command.upgrade(config, "head")
        engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        assert {"alembic_version", "sync_commands", "sync_sessions"} <= set(
            inspect(engine).get_table_names()
        )
        engine.dispose()

        command.downgrade(config, "base")
        engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        assert "sync_sessions" not in inspect(engine).get_table_names()
        engine.dispose()
    finally:
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url
