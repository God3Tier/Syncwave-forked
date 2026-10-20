"""The current weather at a location: one supporting signal (plan.md §3.8).

Like the Catalogue, the Weather API sits behind a small interface so the
real provider can be added later without touching the ranking or the API:

- `StubWeather`: returns a fixed condition for every location (WEATHER_MODE=stub).
- `NoWeather`: always fails, like a Weather API that is down (WEATHER_MODE=off).
  It exists so the "no weather" fallback can be seen working locally.
- `OpenMeteoWeather`: the real provider, Open-Meteo (WEATHER_MODE=open-meteo).
  It needs no API key.

A provider is a class with the same `current` method. It should raise
WeatherUnavailable on any failure; the caller also enforces a timeout.
"""

from typing import Any, Protocol

import httpx2

from recommendation_service.errors import WeatherUnavailable
from recommendation_service.models import Weather


class WeatherClient(Protocol):
    async def current(self, lat: float, lon: float) -> Weather:
        """The weather at the location. Raises WeatherUnavailable if it cannot."""
        ...


class StubWeather:
    def __init__(self, condition: str, temperature_c: float = 28.0) -> None:
        self._weather = Weather(condition=condition, temperature_c=temperature_c)

    async def current(self, lat: float, lon: float) -> Weather:
        return self._weather


class NoWeather:
    async def current(self, lat: float, lon: float) -> Weather:
        raise WeatherUnavailable("weather is switched off (WEATHER_MODE=off)")


def condition_from_wmo_code(code: int) -> str:
    """Map a WMO weather code (what Open-Meteo returns) to a contract condition."""
    if code in (0, 1):
        return "CLEAR"
    if code in (2, 3):
        return "CLOUDY"
    if code in (45, 48):
        return "FOG"
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return "RAIN"
    if code in (71, 73, 75, 77, 85, 86):
        return "SNOW"
    if code in (95, 96, 99):
        return "STORM"
    return "OTHER"


class OpenMeteoWeather:
    """The current weather from Open-Meteo (https://open-meteo.com), no API key.

        GET {base_url}?latitude=&longitude=&current=temperature_2m,weather_code
        200 {"current": {"temperature_2m": 28.1, "weather_code": 61, ...}, ...}

    Any failure, whether a network error, a timeout, a non-200 status or a body
    that is not what we expect, becomes WeatherUnavailable.
    """

    def __init__(self, base_url: str, client: httpx2.AsyncClient) -> None:
        self._base_url = base_url
        self._client = client

    async def current(self, lat: float, lon: float) -> Weather:
        try:
            response = await self._client.get(
                self._base_url,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,weather_code",
                },
            )
            response.raise_for_status()
            return _parse_open_meteo(response.json())
        except (httpx2.HTTPError, ValueError, KeyError, TypeError) as error:
            # ValueError covers bad JSON and non-numeric values, KeyError/TypeError a
            # body of the wrong shape.
            raise WeatherUnavailable(f"Open-Meteo failed: {error!r}") from error


def _parse_open_meteo(body: dict[str, Any]) -> Weather:
    current = body["current"]
    return Weather(
        condition=condition_from_wmo_code(int(current["weather_code"])),
        temperature_c=float(current["temperature_2m"]),
    )
