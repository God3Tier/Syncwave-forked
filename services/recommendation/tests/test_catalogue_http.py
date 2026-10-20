"""HttpCatalogue against a mock Catalogue Service (no network)."""

import uuid
from collections.abc import Callable

import httpx2
import pytest

from recommendation_service.catalogue import HttpCatalogue
from recommendation_service.errors import CatalogueUnavailable

pytestmark = pytest.mark.anyio

SONG_ID = "0b6c2f4e-8d3a-4f7b-b1e2-9c5d7a3e1f20"


def catalogue_with(handler: Callable[[httpx2.Request], httpx2.Response]) -> HttpCatalogue:
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return HttpCatalogue("http://catalogue:8080/", client)


async def test_parses_the_songs() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "items": [
                    {
                        "song_id": SONG_ID,
                        "title": "Rainy Window",
                        "artist": "Example Artist",
                        "duration_ms": 214000,
                        "mood": "mellow",
                        "processing_status": "READY",  # fields we do not use are ignored
                    },
                    {"song_id": str(uuid.uuid4()), "title": "B", "artist": "C", "duration_ms": 1},
                ],
                "next_cursor": None,
            },
        )

    songs = await catalogue_with(handler).list_ready_songs(10)

    assert songs[0].song_id == uuid.UUID(SONG_ID)
    assert (songs[0].title, songs[0].artist, songs[0].duration_ms) == (
        "Rainy Window",
        "Example Artist",
        214000,
    )
    assert songs[0].mood == "mellow"
    assert songs[1].mood is None  # mood is optional


async def test_asks_only_for_ready_songs_with_the_limit() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"items": [], "next_cursor": None})

    await catalogue_with(handler).list_ready_songs(25)

    (request,) = seen
    assert request.url.path == "/songs"  # the trailing slash in the base URL is ignored
    assert dict(request.url.params) == {"processing_status": "READY", "limit": "25"}


@pytest.mark.parametrize("status", [404, 500, 503])
async def test_an_error_status_is_unavailable(status: int) -> None:
    with pytest.raises(CatalogueUnavailable):
        await catalogue_with(lambda request: httpx2.Response(status)).list_ready_songs(10)


async def test_a_network_error_is_unavailable() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    with pytest.raises(CatalogueUnavailable):
        await catalogue_with(handler).list_ready_songs(10)


async def test_a_timeout_is_unavailable() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("too slow", request=request)

    with pytest.raises(CatalogueUnavailable):
        await catalogue_with(handler).list_ready_songs(10)


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        {"unexpected": []},
        {"items": [{"title": "no id"}]},
        {"items": [{"song_id": "not-a-uuid", "title": "T", "artist": "A", "duration_ms": 1}]},
        {"items": [{"song_id": SONG_ID, "title": "T", "artist": "A", "duration_ms": "long"}]},
    ],
)
async def test_an_unreadable_body_is_unavailable(body: object) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if isinstance(body, str):
            return httpx2.Response(200, content=body)
        return httpx2.Response(200, json=body)

    with pytest.raises(CatalogueUnavailable):
        await catalogue_with(handler).list_ready_songs(10)
