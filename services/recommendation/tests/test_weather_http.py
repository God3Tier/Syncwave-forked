"""OpenMeteoWeather against a mock Open-Meteo (no network)."""

from collections.abc import Callable

import httpx2
import pytest

from recommendation_service.errors import WeatherUnavailable
from recommendation_service.models import CONDITIONS
from recommendation_service.weather import OpenMeteoWeather, condition_from_wmo_code

pytestmark = pytest.mark.anyio

URL = "https://api.open-meteo.com/v1/forecast"


def weather_with(handler: Callable[[httpx2.Request], httpx2.Response]) -> OpenMeteoWeather:
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return OpenMeteoWeather(URL, client)


def reply(code: int, temperature: float = 28.1) -> Callable[[httpx2.Request], httpx2.Response]:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "latitude": 1.35,
                "current": {
                    "time": "2026-10-20T09:00",
                    "temperature_2m": temperature,
                    "weather_code": code,
                },  # fields we do not use are ignored
            },
        )

    return handler


async def test_parses_the_current_weather() -> None:
    weather = await weather_with(reply(61, 24.5)).current(1.35, 103.82)

    assert (weather.condition, weather.temperature_c) == ("RAIN", 24.5)


async def test_asks_for_the_location_and_the_current_fields() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return reply(0)(request)

    await weather_with(handler).current(1.35, 103.82)

    (request,) = seen
    assert request.url.path == "/v1/forecast"
    assert dict(request.url.params) == {
        "latitude": "1.35",
        "longitude": "103.82",
        "current": "temperature_2m,weather_code",
    }


@pytest.mark.parametrize(
    ("code", "condition"),
    [
        (0, "CLEAR"),
        (1, "CLEAR"),
        (2, "CLOUDY"),
        (3, "CLOUDY"),
        (45, "FOG"),
        (48, "FOG"),
        (51, "RAIN"),
        (61, "RAIN"),
        (65, "RAIN"),
        (80, "RAIN"),
        (71, "SNOW"),
        (86, "SNOW"),
        (95, "STORM"),
        (96, "STORM"),
        (97, "STORM"),
        (99, "STORM"),
        (4, "OTHER"),  # not a defined WMO code
    ],
)
def test_wmo_codes_map_to_contract_conditions(code: int, condition: str) -> None:
    assert condition_from_wmo_code(code) == condition
    assert condition in CONDITIONS


@pytest.mark.parametrize("status", [400, 404, 429, 500, 503])
async def test_an_error_status_is_unavailable(status: int) -> None:
    with pytest.raises(WeatherUnavailable):
        await weather_with(lambda request: httpx2.Response(status)).current(1.0, 1.0)


async def test_an_error_status_message_has_the_status_and_no_coordinates() -> None:
    with pytest.raises(WeatherUnavailable) as raised:
        await weather_with(lambda request: httpx2.Response(503)).current(1.35, 103.82)

    message = str(raised.value)
    assert message == "Open-Meteo answered HTTP 503"
    assert "1.35" not in message
    assert "\n" not in message


async def test_a_network_error_is_unavailable() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    with pytest.raises(WeatherUnavailable):
        await weather_with(handler).current(1.0, 1.0)


async def test_a_timeout_is_unavailable() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("too slow", request=request)

    with pytest.raises(WeatherUnavailable):
        await weather_with(handler).current(1.0, 1.0)


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        {"unexpected": {}},
        {"current": {"temperature_2m": 28.0}},
        {"current": {"weather_code": 0}},
        {"current": {"temperature_2m": "hot", "weather_code": 0}},
        {"current": {"temperature_2m": 28.0, "weather_code": "rainy"}},
    ],
)
async def test_an_unreadable_body_is_unavailable(body: object) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if isinstance(body, str):
            return httpx2.Response(200, content=body)
        return httpx2.Response(200, json=body)

    with pytest.raises(WeatherUnavailable):
        await weather_with(handler).current(1.0, 1.0)
