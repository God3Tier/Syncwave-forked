import os
from dataclasses import dataclass
from functools import lru_cache


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
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://jam:jam@localhost:5432/jam",
        ),
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
