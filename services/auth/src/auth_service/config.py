import os
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy.engine import URL


def database_url() -> str:
    """DATABASE_URL if set (Compose and the tests), otherwise built from DB_*.

    The DB_* variables are kept separate so that in production the password
    can be injected on its own from AWS Secrets Manager.
    """
    if url := os.getenv("DATABASE_URL"):
        return url
    return URL.create(
        "postgresql+asyncpg",
        username=os.getenv("DB_USER", "auth"),
        password=os.getenv("DB_PASSWORD", "auth"),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME", "auth"),
    ).render_as_string(hide_password=False)


@dataclass(frozen=True, slots=True)
class Settings:
    service_name: str = "auth"
    database_url: str = "postgresql+asyncpg://auth:auth@localhost:5432/auth"
    jwt_private_key_path: str = "/var/lib/auth/private.pem"
    session_cookie_secure: bool = True
    app_origin: str = "http://localhost:8080"


@lru_cache
def get_settings() -> Settings:
    return Settings(
        service_name=os.getenv("SERVICE_NAME", "auth"),
        database_url=database_url(),
        jwt_private_key_path=os.getenv("JWT_PRIVATE_KEY_PATH", "/var/lib/auth/private.pem"),
        session_cookie_secure=os.getenv("SESSION_COOKIE_SECURE", "true").lower() == "true",
        app_origin=os.getenv("APP_ORIGIN", "http://localhost:8080").rstrip("/"),
    )
