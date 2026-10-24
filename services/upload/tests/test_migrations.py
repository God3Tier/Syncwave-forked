from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from upload_service.db import Base


def test_migrations_match_models_and_downgrade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = (tmp_path / "migrations.db").as_posix()
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    engine = create_engine(f"sqlite:///{path}")
    try:
        command.upgrade(config, "head")
        assert "uploads" in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        command.downgrade(config, "base")
        assert "uploads" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()
