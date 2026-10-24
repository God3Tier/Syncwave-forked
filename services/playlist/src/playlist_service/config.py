"""Settings, read from the environment (see .env.example)."""

import logging
import os
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy.engine import URL


@dataclass(frozen=True, slots=True)
class Settings:
    service_name: str
    log_level: str
    database_url: str
    catalogue_url: str
    catalogue_timeout_seconds: float


def database_url() -> str:
    """DATABASE_URL if set (the tests use SQLite), otherwise built from DB_*.

    The DB_* variables are kept separate so that in production the password
    can be injected on its own from AWS Secrets Manager.
    """
    if url := os.getenv("DATABASE_URL"):
        return url
    return URL.create(
        "postgresql+asyncpg",
        username=os.getenv("DB_USER", "playlist"),
        password=os.getenv("DB_PASSWORD", "playlist"),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME", "playlist"),
    ).render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    return Settings(
        service_name=os.getenv("SERVICE_NAME", "playlist"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        database_url=database_url(),
        catalogue_url=os.getenv("CATALOGUE_URL", "http://catalogue:8080"),
        catalogue_timeout_seconds=float(os.getenv("CATALOGUE_TIMEOUT_SECONDS", "3")),
    )


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
