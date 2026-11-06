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
        assert {
            "alembic_version",
            "jams",
            "jam_members",
            "jam_queue_items",
        } <= set(inspect(engine).get_table_names())
        assert "last_listener_active_at" in {
            column["name"] for column in inspect(engine).get_columns("jams")
        }
        engine.dispose()

        command.downgrade(config, "base")
        engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        assert "jams" not in inspect(engine).get_table_names()
        engine.dispose()
    finally:
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url
