import os
from dataclasses import dataclass
from functools import lru_cache


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
        database_url=os.getenv(
            "DATABASE_URL", "postgresql+asyncpg://auth:auth@localhost:5432/auth"
        ),
        jwt_private_key_path=os.getenv("JWT_PRIVATE_KEY_PATH", "/var/lib/auth/private.pem"),
        session_cookie_secure=os.getenv("SESSION_COOKIE_SECURE", "true").lower() == "true",
        app_origin=os.getenv("APP_ORIGIN", "http://localhost:8080").rstrip("/"),
    )
