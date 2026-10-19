"""The data the service works with."""

import uuid
from dataclasses import dataclass

# Matches the `condition` enum in contracts/api/recommendation.openapi.yaml.
CONDITIONS = ("CLEAR", "CLOUDY", "RAIN", "STORM", "SNOW", "FOG", "OTHER")


@dataclass(frozen=True, slots=True)
class Song:
    """A candidate song from the Catalogue (a subset of the Song contract).

    `mood` is optional and **not** part of the shared Song contract yet. Without
    it a song can never be a weather match, so it only ever ranks as GENERAL.
    """

    song_id: uuid.UUID
    title: str
    artist: str
    duration_ms: int
    mood: str | None = None


@dataclass(frozen=True, slots=True)
class Weather:
    condition: str  # one of CONDITIONS
    temperature_c: float


@dataclass(frozen=True, slots=True)
class Recommendation:
    song: Song
    reason: str  # WEATHER_MATCH or GENERAL
