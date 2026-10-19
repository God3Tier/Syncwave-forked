import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from recommendation_service.catalogue import DEMO_SONGS
from recommendation_service.errors import WeatherUnavailable
from recommendation_service.models import Weather

from .conftest import FakeCatalogue, FakeWeather, song


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_with_a_location_the_weather_shapes_the_result(client: TestClient) -> None:
    response = client.get("/recommendations", params={"lat": 1.35, "lon": 103.82})

    assert response.status_code == 200
    body = response.json()
    assert body["weather_used"] is True
    assert body["weather"] == {"condition": "RAIN", "temperature_c": 28.0}
    # The stub weather is RAIN, so the mellow and calm demo songs come first.
    reasons = [item["reason"] for item in body["items"]]
    assert reasons[:4] == ["WEATHER_MATCH"] * 4
    assert set(reasons[4:]) == {"GENERAL"}
    assert {item["title"] for item in body["items"][:4]} == {
        "Rainy Window",
        "Slow Tide",
        "Soft Rain",
        "Long Way Home",
    }


def test_each_item_has_the_contract_fields(client: TestClient) -> None:
    (item, *_) = client.get("/recommendations", params={"limit": 1}).json()["items"]

    assert set(item) == {"song_id", "title", "artist", "duration_ms", "reason"}
    assert uuid.UUID(item["song_id"])
    assert isinstance(item["duration_ms"], int)


def test_without_a_location_there_is_no_weather(client: TestClient) -> None:
    body = client.get("/recommendations").json()

    assert body["weather_used"] is False
    assert body["weather"] is None  # present, and null, as the contract requires
    assert {item["reason"] for item in body["items"]} == {"GENERAL"}
    assert [item["title"] for item in body["items"]] == [song.title for song in DEMO_SONGS]


def test_the_default_limit_is_ten_and_limit_is_respected(client: TestClient) -> None:
    client.app.state.catalogue = FakeCatalogue([song(f"Song {n}") for n in range(30)])

    assert len(client.get("/recommendations").json()["items"]) == 10
    assert len(client.get("/recommendations", params={"limit": 3}).json()["items"]) == 3
    assert len(client.get("/recommendations", params={"limit": 50}).json()["items"]) == 30


def test_a_failing_weather_api_still_returns_200_without_weather(client: TestClient) -> None:
    client.app.state.weather = FakeWeather(error=WeatherUnavailable("down"))

    response = client.get("/recommendations", params={"lat": 1.35, "lon": 103.82})

    assert response.status_code == 200
    body = response.json()
    assert body["weather_used"] is False
    assert body["weather"] is None
    assert len(body["items"]) > 0


def test_weather_is_used_when_the_provider_works(client: TestClient) -> None:
    client.app.state.catalogue = FakeCatalogue([song("Sunny", "upbeat"), song("Rainy", "mellow")])
    client.app.state.weather = FakeWeather(Weather("CLEAR", 33.5))

    body = client.get("/recommendations", params={"lat": 1.35, "lon": 103.82}).json()

    assert body["weather"] == {"condition": "CLEAR", "temperature_c": 33.5}
    assert [item["title"] for item in body["items"]] == ["Sunny", "Rainy"]


def test_a_catalogue_outage_is_a_502(client: TestClient) -> None:
    client.app.state.catalogue = FakeCatalogue(down=True)

    response = client.get("/recommendations")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "CATALOGUE_UNAVAILABLE"


def test_no_ready_songs_is_an_empty_200(client: TestClient) -> None:
    client.app.state.catalogue = FakeCatalogue([])

    response = client.get("/recommendations", params={"lat": 1.35, "lon": 103.82})

    assert response.status_code == 200
    assert response.json() == {"items": [], "weather_used": False, "weather": None}


@pytest.mark.parametrize(
    "params",
    [
        {"lat": 1.35},  # lat without lon
        {"lon": 103.82},  # lon without lat
        {"lat": 91, "lon": 0},
        {"lat": -91, "lon": 0},
        {"lat": 0, "lon": 181},
        {"lat": "north", "lon": 0},
        {"limit": 0},
        {"limit": 51},
        {"limit": "many"},
    ],
)
def test_invalid_query_is_400(client: TestClient, params: dict[str, Any]) -> None:
    response = client.get("/recommendations", params=params)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_unknown_path_uses_the_shared_error_shape(client: TestClient) -> None:
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
