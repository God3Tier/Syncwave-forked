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
    s3_endpoint_url: str | None
    s3_force_path_style: bool
    s3_bucket: str
    aws_region: str
    waveform_points: int
    waveform_sample_rate: int
    waveform_frame_rate: float
    waveform_bands: int
    waveform_max_audio_bytes: int
    waveform_decode_timeout_s: float


def database_url() -> str:
    """DATABASE_URL if set (the tests use SQLite), otherwise built from DB_*.

    The DB_* variables are kept separate so that in production the password
    can be injected on its own from AWS Secrets Manager.
    """
    if url := os.getenv("DATABASE_URL"):
        return url
    return URL.create(
        "postgresql+asyncpg",
        username=os.getenv("DB_USER", "waveform"),
        password=os.getenv("DB_PASSWORD", "waveform"),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME", "waveform"),
    ).render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    return Settings(
        service_name=os.getenv("SERVICE_NAME", "waveform"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        database_url=database_url(),
        amqp_host=os.getenv("AMQP_HOST", "localhost"),
        amqp_port=int(os.getenv("AMQP_PORT", "5672")),
        amqp_user=os.getenv("AMQP_USER", "syncwave"),
        amqp_password=os.getenv("AMQP_PASSWORD", "syncwave"),
        amqp_prefetch=int(os.getenv("AMQP_PREFETCH", "2")),
        s3_endpoint_url=os.getenv("S3_ENDPOINT_URL") or None,
        s3_force_path_style=os.getenv("S3_FORCE_PATH_STYLE", "false").lower() == "true",
        s3_bucket=os.getenv("S3_BUCKET", "syncwave-audio"),
        aws_region=os.getenv("AWS_REGION", "us-east-1"),
        waveform_points=int(os.getenv("WAVEFORM_POINTS", "1000")),
        waveform_sample_rate=int(os.getenv("WAVEFORM_SAMPLE_RATE", "22050")),
        waveform_frame_rate=float(os.getenv("WAVEFORM_FRAME_RATE", "25")),
        waveform_bands=int(os.getenv("WAVEFORM_BANDS", "50")),
        waveform_max_audio_bytes=int(os.getenv("WAVEFORM_MAX_AUDIO_BYTES", "209715200")),
        waveform_decode_timeout_s=float(os.getenv("WAVEFORM_DECODE_TIMEOUT_S", "120")),
    )


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
