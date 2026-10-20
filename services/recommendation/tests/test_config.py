import pytest

from recommendation_service.config import get_settings


@pytest.fixture(autouse=True)
def fresh_settings() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("CATALOGUE_MODE", "WEATHER_MODE", "WEATHER_STUB_CONDITION", "CATALOGUE_URL"):
        monkeypatch.delenv(name, raising=False)

    settings = get_settings()

    assert settings.catalogue_mode == "stub"
    assert settings.weather_mode == "stub"
    assert settings.weather_stub_condition == "RAIN"
    assert settings.catalogue_url == "http://catalogue:8080"


def test_values_are_case_insensitive_and_the_url_loses_its_trailing_slash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CATALOGUE_MODE", "HTTP")
    monkeypatch.setenv("WEATHER_STUB_CONDITION", "clear")
    monkeypatch.setenv("CATALOGUE_URL", "http://catalogue:8080/")

    settings = get_settings()

    assert settings.catalogue_mode == "http"
    assert settings.weather_stub_condition == "CLEAR"
    assert settings.catalogue_url == "http://catalogue:8080"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("CATALOGUE_MODE", "nope"),
        ("WEATHER_MODE", "http"),  # the real provider's mode is `open-meteo`
        ("WEATHER_STUB_CONDITION", "HURRICANE"),
    ],
)
def test_an_unknown_choice_fails_at_start_up(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        get_settings()


def test_open_meteo_is_a_weather_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEATHER_MODE", "Open-Meteo")
    monkeypatch.delenv("WEATHER_URL", raising=False)

    settings = get_settings()

    assert settings.weather_mode == "open-meteo"
    assert settings.weather_url == "https://api.open-meteo.com/v1/forecast"
