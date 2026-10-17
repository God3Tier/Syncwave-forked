"""Shared fixtures: fake Catalogue and Weather clients, so no test needs a network."""

import asyncio
import os
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

# Read by the API's lifespan through get_settings(); set before the app is used.
os.environ["CATALOGUE_MODE"] = "stub"
os.environ["WEATHER_MODE"] = "stub"

from recommendation_service.api.main import app  # noqa: E402
from recommendation_service.errors import CatalogueUnavailable, WeatherUnavailable  # noqa: E402
from recommendation_service.models import Song, Weather  # noqa: E402


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def song(title: str = "Song", mood: str | None = None) -> Song:
    return Song(song_id=uuid.uuid4(), title=title, artist="Artist", duration_ms=180_000, mood=mood)


class FakeCatalogue:
    def __init__(self, songs: list[Song] | None = None, *, down: bool = False) -> None:
        self.songs = songs or []
        self.down = down
        self.asked_for: list[int] = []

    async def list_ready_songs(self, limit: int) -> list[Song]:
        self.asked_for.append(limit)
        if self.down:
            raise CatalogueUnavailable("the Catalogue is down")
        return self.songs[:limit]


class FakeWeather:
    """Returns `weather`, or fails the way a broken provider would."""

    def __init__(
        self,
        weather: Weather | None = None,
        *,
        error: Exception | None = None,
        delay: float = 0,
    ) -> None:
        self.weather = weather or Weather("RAIN", 24.0)
        self.error = error
        self.delay = delay
        self.calls: list[tuple[float, float]] = []

    async def current(self, lat: float, lon: float) -> Weather:
        self.calls.append((lat, lon))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.weather


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


__all__ = ["FakeCatalogue", "FakeWeather", "WeatherUnavailable", "song"]
