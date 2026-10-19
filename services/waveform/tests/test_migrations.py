from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from waveform_service.shared.db import Base

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
        assert "waveforms" in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []

        command.downgrade(config, "base")
        assert "waveforms" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()
