"""The current weather at a location: one supporting signal (plan.md §3.8).

Like the Catalogue, the Weather API sits behind a small interface so the
real provider can be added later without touching the ranking or the API:

- `StubWeather`: returns a fixed condition for every location (WEATHER_MODE=stub).
- `NoWeather`: always fails, like a Weather API that is down (WEATHER_MODE=off).
  It exists so the "no weather" fallback can be seen working locally.

A real provider is one more class with the same `current` method. It should
raise WeatherUnavailable on any failure; the caller also enforces a timeout.
"""

from typing import Protocol

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
