import pytest

from auth_service.config import database_url


def test_database_url_prefers_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///local.db")
    monkeypatch.setenv("DB_HOST", "ignored")
    assert database_url() == "sqlite+aiosqlite:///local.db"


def test_database_url_built_from_db_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    # Production (ECS): the password arrives on its own from Secrets Manager
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_HOST", "syncwave.example.rds.amazonaws.com")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "auth")
    monkeypatch.setenv("DB_USER", "auth")
    monkeypatch.setenv("DB_PASSWORD", "p@ss:word/%")
    assert database_url() == (
        "postgresql+asyncpg://auth:p%40ss%3Aword%2F%25@syncwave.example.rds.amazonaws.com:5432/auth"
    )
