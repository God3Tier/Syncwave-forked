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
    amqp_host: str
    amqp_port: int
    amqp_user: str
    amqp_password: str
    amqp_prefetch: int
    catalogue_url: str


def database_url() -> str:
    """DATABASE_URL if set (the tests use SQLite), otherwise built from DB_*."""
    if url := os.getenv("DATABASE_URL"):
        return url
    return URL.create(
        "postgresql+asyncpg",
        username=os.getenv("DB_USER", "search"),
        password=os.getenv("DB_PASSWORD", "search"),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME", "search"),
    ).render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    return Settings(
        service_name=os.getenv("SERVICE_NAME", "search"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        database_url=database_url(),
        amqp_host=os.getenv("AMQP_HOST", "localhost"),
        amqp_port=int(os.getenv("AMQP_PORT", "5672")),
        amqp_user=os.getenv("AMQP_USER", "syncwave"),
        amqp_password=os.getenv("AMQP_PASSWORD", "syncwave"),
        amqp_prefetch=int(os.getenv("AMQP_PREFETCH", "10")),
        catalogue_url=os.getenv("CATALOGUE_URL", "http://catalogue:8080"),
    )


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
