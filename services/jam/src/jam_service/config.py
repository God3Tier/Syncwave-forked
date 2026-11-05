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
    auth_jwks_url: str = "http://auth:8080/.well-known/jwks.json"
    jam_member_token_secret: str = "local-room-token-secret-replace-before-deploy"
    app_origin: str = "http://localhost:8080"
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
        auth_jwks_url=os.getenv("AUTH_JWKS_URL", "http://auth:8080/.well-known/jwks.json"),
        jam_member_token_secret=os.getenv(
            "JAM_MEMBER_TOKEN_SECRET", "local-room-token-secret-replace-before-deploy"
        ),
        app_origin=os.getenv("APP_ORIGIN", "http://localhost:8080").rstrip("/"),
        sync_timeout_ms=int(os.getenv("SYNC_TIMEOUT_MS", "1000")),
        playlist_timeout_ms=int(os.getenv("PLAYLIST_TIMEOUT_MS", "750")),
    )
