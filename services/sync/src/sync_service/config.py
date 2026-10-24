import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True, slots=True)
class Settings:
    service_name: str = "sync"
    log_level: str = "INFO"
    internal_service_token: str = "local-jam-to-sync-token"
    mock_sync_token: str = "local-sync-participant-token"
    database_url: str = "postgresql+asyncpg://sync:sync@localhost:5432/sync"
    grpc_port: int = 50_051
    dependency_timeout_ms: int = 750
    catalogue_grpc_target: str = ""
    catalogue_internal_token: str = "local-catalogue-internal-token"
    streaming_grpc_target: str = ""
    streaming_internal_token: str = "local-streaming-internal-token"
    start_lead_time_ms: int = 2_000
    prepare_timeout_ms: int = 10_000
    clock_sample_max_age_ms: int = 30_000
    target_sync_tolerance_ms: int = 100
    drift_ignore_threshold_ms: int = 80
    drift_seek_threshold_ms: int = 250
    rate_correction_percent: float = 0.02
    correction_lead_time_ms: int = 500
    correction_hysteresis_ms: int = 20
    correction_cooldown_ms: int = 3_000
    websocket_idle_timeout_ms: int = 45_000
    websocket_max_message_bytes: int = 64 * 1024
    websocket_rate_limit_messages: int = 30
    websocket_rate_limit_window_ms: int = 1_000


@lru_cache
def get_settings() -> Settings:
    return Settings(
        service_name=os.getenv("SERVICE_NAME", "sync"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        internal_service_token=os.getenv("INTERNAL_SERVICE_TOKEN", "local-jam-to-sync-token"),
        mock_sync_token=os.getenv("MOCK_SYNC_TOKEN", "local-sync-participant-token"),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://sync:sync@localhost:5432/sync",
        ),
        grpc_port=int(os.getenv("GRPC_PORT", "50051")),
        dependency_timeout_ms=int(os.getenv("DEPENDENCY_TIMEOUT_MS", "750")),
        catalogue_grpc_target=os.getenv("CATALOGUE_GRPC_TARGET", ""),
        catalogue_internal_token=os.getenv(
            "CATALOGUE_INTERNAL_TOKEN", "local-catalogue-internal-token"
        ),
        streaming_grpc_target=os.getenv("STREAMING_GRPC_TARGET", ""),
        streaming_internal_token=os.getenv(
            "STREAMING_INTERNAL_TOKEN", "local-streaming-internal-token"
        ),
        start_lead_time_ms=int(os.getenv("START_LEAD_TIME_MS", "2000")),
        prepare_timeout_ms=int(os.getenv("PREPARE_TIMEOUT_MS", "10000")),
        clock_sample_max_age_ms=int(os.getenv("CLOCK_SAMPLE_MAX_AGE_MS", "30000")),
        target_sync_tolerance_ms=int(os.getenv("TARGET_SYNC_TOLERANCE_MS", "100")),
        drift_ignore_threshold_ms=int(os.getenv("DRIFT_IGNORE_THRESHOLD_MS", "80")),
        drift_seek_threshold_ms=int(os.getenv("DRIFT_SEEK_THRESHOLD_MS", "250")),
        rate_correction_percent=float(os.getenv("RATE_CORRECTION_PERCENT", "0.02")),
        correction_lead_time_ms=int(os.getenv("CORRECTION_LEAD_TIME_MS", "500")),
        correction_hysteresis_ms=int(os.getenv("CORRECTION_HYSTERESIS_MS", "20")),
        correction_cooldown_ms=int(os.getenv("CORRECTION_COOLDOWN_MS", "3000")),
        websocket_idle_timeout_ms=int(os.getenv("WEBSOCKET_IDLE_TIMEOUT_MS", "45000")),
        websocket_max_message_bytes=int(os.getenv("WEBSOCKET_MAX_MESSAGE_BYTES", "65536")),
        websocket_rate_limit_messages=int(os.getenv("WEBSOCKET_RATE_LIMIT_MESSAGES", "30")),
        websocket_rate_limit_window_ms=int(os.getenv("WEBSOCKET_RATE_LIMIT_WINDOW_MS", "1000")),
    )
