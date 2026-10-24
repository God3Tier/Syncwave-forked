"""Asking the Catalogue Service whether a song exists (plan.md §3.1).

Playlist only needs a yes or no when a song is added, so the interface is one
method. Any trouble reaching the Catalogue is `CatalogueUnavailable`, which is
different from a clear "no such song": the caller cannot tell whether the song
exists, so the add is refused and nothing is stored.
"""

import uuid
from typing import Protocol

import httpx2

from playlist_service.errors import CatalogueUnavailable


class CatalogueClient(Protocol):
    async def exists(self, song_id: uuid.UUID) -> bool:
        """True if the Catalogue knows the song, False if it does not. Raises
        CatalogueUnavailable if it cannot say."""
        ...


class NoCatalogue:
    """CATALOGUE_MODE=off: every song id is accepted without asking anyone."""

    async def exists(self, song_id: uuid.UUID) -> bool:
        return True


class HttpCatalogue:
    """Calls the Catalogue Service over HTTP.

        GET {CATALOGUE_URL}/songs/{song_id}
        200 -> the song exists        404 -> no such song (SONG_NOT_FOUND)

    Only the status is used, not the body. A song that exists but is still
    being processed counts as existing: it can be queued and played once ready.
    Any other status, a network error or a timeout becomes CatalogueUnavailable.
    """

    def __init__(self, base_url: str, client: httpx2.AsyncClient) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client

    async def exists(self, song_id: uuid.UUID) -> bool:
        try:
            response = await self._client.get(f"{self._base_url}/songs/{song_id}")
        except httpx2.HTTPError as error:
            raise CatalogueUnavailable(f"The Catalogue Service failed: {error!r}") from error
        if response.status_code == 200:
            return True
        if response.status_code == 404:
            return False
        raise CatalogueUnavailable(
            f"The Catalogue Service answered with status {response.status_code}"
        )
