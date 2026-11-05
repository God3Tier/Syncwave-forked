"""One recommendation request: get songs, try the weather, rank.

The weather is optional by design. Whatever goes wrong with it (no location
sent, the provider is down, it is too slow, it returns garbage) the caller
still gets recommendations, just without weather. Only a Catalogue failure is
an error, because without songs there is nothing to recommend.
"""

import asyncio
import logging
from dataclasses import dataclass

from recommendation_service.catalogue import CatalogueClient
from recommendation_service.errors import WeatherUnavailable
from recommendation_service.models import Recommendation, Weather
from recommendation_service.ranking import WEATHER_MATCH, rank
from recommendation_service.weather import WeatherClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Result:
    items: list[Recommendation]
    # Only set when the weather really changed the result (some item is a
    # WEATHER_MATCH); otherwise None, matching `weather_used: false` in the API.
    weather: Weather | None

    @property
    def weather_used(self) -> bool:
        return self.weather is not None


async def recommend(
    catalogue: CatalogueClient,
    weather_client: WeatherClient,
    *,
    lat: float | None,
    lon: float | None,
    limit: int,
    candidate_limit: int,
    weather_timeout_seconds: float,
) -> Result:
    songs = await catalogue.list_ready_songs(max(candidate_limit, limit))
    weather = await _weather_or_none(weather_client, lat, lon, weather_timeout_seconds)
    items = rank(songs, weather, limit)
    influenced = any(item.reason == WEATHER_MATCH for item in items)
    return Result(items=items, weather=weather if influenced else None)


async def _weather_or_none(
    weather_client: WeatherClient, lat: float | None, lon: float | None, timeout_seconds: float
) -> Weather | None:
    if lat is None or lon is None:
        return None
    try:
        return await asyncio.wait_for(weather_client.current(lat, lon), timeout_seconds)
    except TimeoutError:
        logger.warning(
            "weather unavailable, recommending without it: no answer within %ss", timeout_seconds
        )
        return None
    except WeatherUnavailable as error:
        # Expected (provider down, error status, unreadable answer): one line,
        # the error already says what went wrong.
        logger.warning("weather unavailable, recommending without it: %s", error)
        return None
    except Exception:
        # Deliberately broad: weather is a supporting signal, so *any* failure in
        # it, including a bug in a provider, must never break listening. A bug is
        # not expected, so this one keeps its stack trace.
        logger.exception("weather lookup failed unexpectedly, recommending without it")
        return None
