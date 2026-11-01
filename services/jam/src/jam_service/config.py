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
        username=os.getenv("DB_USER", "jam"),
        password=os.getenv("DB_PASSWORD", "jam"),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME", "jam"),
    ).render_as_string(hide_password=False)


@dataclass(frozen=True, slots=True)
class Settings:
    service_name: str = "jam"
    database_url: str = "postgresql+asyncpg://jam:jam@localhost:5432/jam"
    sync_grpc_target: str = ""
    internal_service_token: str = "local-jam-to-sync-token"
    playlist_grpc_target: str = ""
    playlist_internal_token: str = "local-playlist-internal-token"
    mock_jam_token: str = "local-jam-member-token"
    sync_timeout_ms: int = 1_000
    playlist_timeout_ms: int = 750


@lru_cache
def get_settings() -> Settings:
    return Settings(
        service_name=os.getenv("SERVICE_NAME", "jam"),
        database_url=database_url(),
        sync_grpc_target=os.getenv("SYNC_GRPC_TARGET", ""),
        internal_service_token=os.getenv("INTERNAL_SERVICE_TOKEN", "local-jam-to-sync-token"),
        playlist_grpc_target=os.getenv("PLAYLIST_GRPC_TARGET", ""),
        playlist_internal_token=os.getenv(
            "PLAYLIST_INTERNAL_TOKEN", "local-playlist-internal-token"
        ),
        mock_jam_token=os.getenv("MOCK_JAM_TOKEN", "local-jam-member-token"),
        sync_timeout_ms=int(os.getenv("SYNC_TIMEOUT_MS", "1000")),
        playlist_timeout_ms=int(os.getenv("PLAYLIST_TIMEOUT_MS", "750")),
    )
