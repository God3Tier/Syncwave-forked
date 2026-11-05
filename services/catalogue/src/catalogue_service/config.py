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
    internal_service_token: str
    grpc_port: int


def database_url() -> str:
    """DATABASE_URL if set (the tests use SQLite), otherwise built from DB_*.

    The DB_* variables are kept separate so that in production the password
    can be injected on its own from AWS Secrets Manager.
    """
    if url := os.getenv("DATABASE_URL"):
        return url
    return URL.create(
        "postgresql+asyncpg",
        username=os.getenv("DB_USER", "catalogue"),
        password=os.getenv("DB_PASSWORD", "catalogue"),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME", "catalogue"),
    ).render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    return Settings(
        service_name=os.getenv("SERVICE_NAME", "catalogue"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        database_url=database_url(),
        amqp_host=os.getenv("AMQP_HOST", "localhost"),
        amqp_port=int(os.getenv("AMQP_PORT", "5672")),
        amqp_user=os.getenv("AMQP_USER", "syncwave"),
        amqp_password=os.getenv("AMQP_PASSWORD", "syncwave"),
        amqp_prefetch=int(os.getenv("AMQP_PREFETCH", "10")),
        internal_service_token=os.getenv(
            "INTERNAL_SERVICE_TOKEN", "local-catalogue-internal-token"
        ),
        grpc_port=int(os.getenv("GRPC_PORT", "50051")),
    )


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
