"""HttpCatalogue against a mock Catalogue Service (no network)."""

import uuid
from collections.abc import Callable

import httpx2
import pytest

from playlist_service.catalogue import HttpCatalogue
from playlist_service.errors import CatalogueUnavailable

pytestmark = pytest.mark.anyio

SONG_ID = uuid.UUID("0b6c2f4e-8d3a-4f7b-b1e2-9c5d7a3e1f20")


def catalogue_with(handler: Callable[[httpx2.Request], httpx2.Response]) -> HttpCatalogue:
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return HttpCatalogue("http://catalogue:8080/", client)


async def test_a_song_the_catalogue_has_exists() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"song_id": str(SONG_ID), "title": "T"})

    assert await catalogue_with(handler).exists(SONG_ID) is True
    (request,) = seen
    assert request.url.path == f"/songs/{SONG_ID}"  # the trailing slash in the base URL is ignored


async def test_a_song_still_being_processed_counts_as_existing() -> None:
    body = {"song_id": str(SONG_ID), "processing_status": "PROCESSING"}
    assert await catalogue_with(lambda r: httpx2.Response(200, json=body)).exists(SONG_ID)


async def test_a_404_means_no_such_song() -> None:
    body = {"error": {"code": "SONG_NOT_FOUND", "message": "No song"}}
    assert await catalogue_with(lambda r: httpx2.Response(404, json=body)).exists(SONG_ID) is False


@pytest.mark.parametrize("status", [400, 500, 502, 503])
async def test_any_other_status_is_unavailable(status: int) -> None:
    with pytest.raises(CatalogueUnavailable):
        await catalogue_with(lambda request: httpx2.Response(status)).exists(SONG_ID)


async def test_a_network_error_is_unavailable() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    with pytest.raises(CatalogueUnavailable):
        await catalogue_with(handler).exists(SONG_ID)


async def test_a_timeout_is_unavailable() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("too slow", request=request)

    with pytest.raises(CatalogueUnavailable):
        await catalogue_with(handler).exists(SONG_ID)
