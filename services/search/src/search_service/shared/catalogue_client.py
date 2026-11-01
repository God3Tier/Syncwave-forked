"""HTTP client for the Catalogue Service (metadata lookup during indexing)."""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx2 as httpx

from search_service.shared.errors import PermanentError, TransientError


@dataclass(frozen=True, slots=True)
class SongData:
    title: str
    artist: str


class CatalogueClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport  # the tests pass a MockTransport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout, transport=self._transport)

    async def ready_songs(
        self, *, page_size: int = 100
    ) -> AsyncIterator[tuple[uuid.UUID, SongData]]:
        """Every READY song in Catalogue, paging through GET /songs."""
        url = f"{self._base_url}/songs"
        params: dict[str, str | int] = {"processing_status": "READY", "limit": page_size}
        async with self._client() as client:
            while True:
                try:
                    response = await client.get(url, params=params)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    raise TransientError(f"Catalogue unreachable: {exc}") from exc
                if response.status_code != 200:
                    raise TransientError(
                        f"Catalogue returned {response.status_code}: {response.text[:200]}"
                    )
                try:
                    body = response.json()
                    page = [
                        (uuid.UUID(item["song_id"]), SongData(item["title"], item["artist"]))
                        for item in body["items"]
                    ]
                except (ValueError, KeyError, TypeError) as exc:
                    raise TransientError(f"Catalogue returned an invalid song list: {exc}") from exc
                for song in page:
                    yield song
                cursor = body.get("next_cursor")
                if not cursor:
                    return
                params["cursor"] = cursor

    async def get_song(self, song_id) -> SongData:
        url = f"{self._base_url}/songs/{song_id}"
        try:
            async with self._client() as client:
                response = await client.get(url)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientError(f"Catalogue unreachable: {exc}") from exc

        if response.status_code == 404:
            raise PermanentError("SONG_NOT_FOUND", f"No song {song_id} in Catalogue")
        if response.status_code >= 500:
            raise TransientError(
                f"Catalogue server error {response.status_code}: {response.text[:200]}"
            )
        if response.status_code != 200:
            raise PermanentError(
                "CATALOGUE_ERROR",
                f"Catalogue returned {response.status_code}: {response.text[:200]}",
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise TransientError(f"Catalogue returned invalid JSON: {exc}") from exc
        title = body.get("title")
        artist = body.get("artist")
        if not isinstance(title, str) or not title or not isinstance(artist, str) or not artist:
            raise TransientError("Catalogue response missing title/artist")
        return SongData(title=title, artist=artist)
