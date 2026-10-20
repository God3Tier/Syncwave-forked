"""The weather fallback: every way the weather can fail still gives recommendations."""

import pytest

from recommendation_service.errors import CatalogueUnavailable, WeatherUnavailable
from recommendation_service.models import Weather
from recommendation_service.ranking import GENERAL, WEATHER_MATCH
from recommendation_service.service import Result, recommend

from .conftest import FakeCatalogue, FakeWeather, song

pytestmark = pytest.mark.anyio

SONGS = [song("Upbeat", "upbeat"), song("Mellow", "mellow")]


async def run(
    weather: FakeWeather,
    *,
    lat: float | None = 1.35,
    lon: float | None = 103.8,
    weather_timeout: float = 1.0,
    catalogue: FakeCatalogue | None = None,
    limit: int = 10,
    candidate_limit: int = 100,
) -> Result:
    return await recommend(
        catalogue or FakeCatalogue(SONGS),
        weather,
        lat=lat,
        lon=lon,
        limit=limit,
        candidate_limit=candidate_limit,
        weather_timeout_seconds=weather_timeout,
    )


async def test_weather_that_matches_changes_the_result() -> None:
    result = await run(FakeWeather(Weather("RAIN", 24.0)))

    assert [item.song.title for item in result.items] == ["Mellow", "Upbeat"]
    assert [item.reason for item in result.items] == [WEATHER_MATCH, GENERAL]
    assert result.weather_used is True
    assert result.weather == Weather("RAIN", 24.0)


async def test_no_location_means_the_weather_is_never_asked() -> None:
    weather = FakeWeather()

    result = await run(weather, lat=None, lon=None)

    assert weather.calls == []
    assert result.weather_used is False
    assert {item.reason for item in result.items} == {GENERAL}


async def test_weather_provider_failure_falls_back() -> None:
    result = await run(FakeWeather(error=WeatherUnavailable("provider down")))

    assert result.weather_used is False
    assert result.weather is None
    assert [item.song.title for item in result.items] == ["Upbeat", "Mellow"]


async def test_a_bug_in_the_weather_provider_also_falls_back() -> None:
    result = await run(FakeWeather(error=RuntimeError("unexpected response shape")))

    assert result.weather_used is False
    assert len(result.items) == 2


async def test_a_slow_weather_provider_is_abandoned() -> None:
    result = await run(FakeWeather(delay=5), weather_timeout=0.05)

    assert result.weather_used is False
    assert len(result.items) == 2


async def test_weather_that_matches_no_song_is_not_reported_as_used() -> None:
    result = await run(FakeWeather(Weather("OTHER", 20.0)))

    assert result.weather_used is False
    assert result.weather is None


async def test_the_catalogue_is_asked_for_at_least_the_limit() -> None:
    catalogue = FakeCatalogue(SONGS)

    await run(FakeWeather(), catalogue=catalogue, limit=50, candidate_limit=10)

    assert catalogue.asked_for == [50]


async def test_a_catalogue_failure_is_an_error_not_a_fallback() -> None:
    with pytest.raises(CatalogueUnavailable):
        await run(FakeWeather(), catalogue=FakeCatalogue(down=True))


async def test_no_ready_songs_gives_an_empty_list() -> None:
    result = await run(FakeWeather(), catalogue=FakeCatalogue([]))

    assert result.items == []
    assert result.weather_used is False
