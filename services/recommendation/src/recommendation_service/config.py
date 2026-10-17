"""Settings, read from the environment (see .env.example)."""

import logging
import os
from dataclasses import dataclass
from functools import lru_cache

from recommendation_service.models import CONDITIONS

CATALOGUE_MODES = ("stub", "http")
WEATHER_MODES = ("stub", "off")


@dataclass(frozen=True, slots=True)
class Settings:
    service_name: str
    log_level: str
    catalogue_mode: str
    catalogue_url: str
    catalogue_timeout_seconds: float
    candidate_limit: int
    weather_mode: str
    weather_stub_condition: str
    weather_timeout_seconds: float


def _choice(name: str, default: str, allowed: tuple[str, ...], *, upper: bool = False) -> str:
    """The variable's value, which must be one of `allowed`. Failing at start-up
    beats silently running in the wrong mode."""
    value = os.getenv(name, default)
    value = value.upper() if upper else value.lower()
    if value not in allowed:
        raise ValueError(f"{name} must be one of {', '.join(allowed)}, not {value!r}")
    return value


@lru_cache
def get_settings() -> Settings:
    return Settings(
        service_name=os.getenv("SERVICE_NAME", "recommendation"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        catalogue_mode=_choice("CATALOGUE_MODE", "stub", CATALOGUE_MODES),
        catalogue_url=os.getenv("CATALOGUE_URL", "http://catalogue:8080").rstrip("/"),
        catalogue_timeout_seconds=float(os.getenv("CATALOGUE_TIMEOUT_SECONDS", "3")),
        candidate_limit=int(os.getenv("CANDIDATE_LIMIT", "100")),
        weather_mode=_choice("WEATHER_MODE", "stub", WEATHER_MODES),
        weather_stub_condition=_choice("WEATHER_STUB_CONDITION", "RAIN", CONDITIONS, upper=True),
        weather_timeout_seconds=float(os.getenv("WEATHER_TIMEOUT_SECONDS", "2")),
    )


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
