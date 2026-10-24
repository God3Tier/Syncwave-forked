"""CATALOGUE_MODE decides whether adding a song asks the Catalogue."""

import uuid

import httpx2
import pytest

from playlist_service.api.main import build_catalogue
from playlist_service.catalogue import HttpCatalogue, NoCatalogue
from playlist_service.config import Settings, catalogue_mode

pytestmark = pytest.mark.anyio


def settings(mode: str) -> Settings:
    return Settings(
        service_name="playlist",
        log_level="INFO",
        database_url="sqlite+aiosqlite://",
        catalogue_mode=mode,
        catalogue_url="http://catalogue:8080",
        catalogue_timeout_seconds=3.0,
        grpc_port=0,
        internal_service_token="",
    )


def test_the_mode_defaults_to_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CATALOGUE_MODE", raising=False)
    assert catalogue_mode() == "http"


@pytest.mark.parametrize("value", ["http", "HTTP", "off"])
def test_the_mode_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("CATALOGUE_MODE", value)
    assert catalogue_mode() == value.lower()


def test_an_unknown_mode_is_refused_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CATALOGUE_MODE", "stub")
    with pytest.raises(ValueError, match="CATALOGUE_MODE"):
        catalogue_mode()


async def test_off_accepts_any_song_without_a_network() -> None:
    async with httpx2.AsyncClient() as client:
        catalogue = build_catalogue(settings("off"), client)
    assert isinstance(catalogue, NoCatalogue)
    assert await catalogue.exists(uuid.uuid4()) is True


async def test_http_asks_the_catalogue() -> None:
    async with httpx2.AsyncClient() as client:
        assert isinstance(build_catalogue(settings("http"), client), HttpCatalogue)
