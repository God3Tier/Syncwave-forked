"""Environment configuration; local credentials are supplied by Compose."""

import os
from dataclasses import dataclass

from sqlalchemy.engine import URL


def database_url() -> str:
    return os.getenv("DATABASE_URL") or URL.create(
        "postgresql+asyncpg",
        username=os.getenv("DB_USER", "upload"),
        password=os.getenv("DB_PASSWORD", "upload"),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME", "upload"),
    ).render_as_string(hide_password=False)


def positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


@dataclass(frozen=True)
class Settings:
    database_url: str
    bucket: str
    endpoint_url: str | None
    region: str
    path_style: bool
    audio_max_bytes: int
    lyrics_max_bytes: int
    poll_seconds: int

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database_url=database_url(),
            bucket=os.getenv("S3_BUCKET", "syncwave-audio"),
            endpoint_url=os.getenv("S3_ENDPOINT_URL") or None,
            region=os.getenv("AWS_REGION", "us-east-1"),
            path_style=os.getenv("S3_FORCE_PATH_STYLE", "false").lower() == "true",
            audio_max_bytes=positive_int("UPLOAD_MAX_AUDIO_BYTES", 190 * 1024 * 1024),
            lyrics_max_bytes=positive_int("UPLOAD_MAX_LYRICS_BYTES", 262144),
            poll_seconds=positive_int("UPLOAD_PUBLISH_POLL_SECONDS", 2),
        )
