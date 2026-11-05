import uuid

import httpx2 as httpx
import pytest

from search_service.shared.catalogue_client import CatalogueClient
from search_service.shared.errors import TransientError
from search_service.worker.rebuild import rebuild_index

SONGS = [(str(uuid.uuid4()), f"Song {n}", f"Artist {n}") for n in range(3)]


def paged_catalogue(requests: list[httpx.Request]) -> CatalogueClient:
    """A Catalogue serving SONGS two per page, like GET /songs."""

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        start = int(request.url.params.get("cursor", "0"))
        page = SONGS[start : start + 2]
        more = start + 2 < len(SONGS)
        return httpx.Response(
            200,
            json={
                "items": [{"song_id": i, "title": t, "artist": a} for i, t, a in page],
                "next_cursor": str(start + 2) if more else None,
            },
        )

    return CatalogueClient("http://catalogue:8080", transport=httpx.MockTransport(respond))


@pytest.mark.anyio
async def test_rebuild_indexes_every_ready_song_across_pages(repository) -> None:
    requests: list[httpx.Request] = []

    assert await rebuild_index(paged_catalogue(requests), repository) == 3

    assert [r.url.params.get("processing_status") for r in requests] == ["READY", "READY"]
    assert [r.url.params.get("cursor") for r in requests] == [None, "2"]
    for song_id, title, artist in SONGS:
        record = await repository.get(uuid.UUID(song_id))
        assert record is not None
        assert (record.title, record.artist) == (title, artist)


@pytest.mark.anyio
async def test_rebuild_is_repeatable_and_keeps_indexing_order(repository) -> None:
    catalogue = paged_catalogue([])
    await rebuild_index(catalogue, repository)
    first = await repository.get(uuid.UUID(SONGS[0][0]))

    assert await rebuild_index(catalogue, repository) == 3

    again = await repository.get(uuid.UUID(SONGS[0][0]))
    assert again is not None and first is not None
    assert again.indexed_at == first.indexed_at


@pytest.mark.anyio
@pytest.mark.parametrize(
    "response",
    [httpx.Response(503, text="down"), httpx.Response(200, json={"songs": []})],
)
async def test_catalogue_errors_are_transient(repository, response: httpx.Response) -> None:
    catalogue = CatalogueClient(
        "http://catalogue:8080", transport=httpx.MockTransport(lambda _: response)
    )

    with pytest.raises(TransientError):
        await rebuild_index(catalogue, repository)
