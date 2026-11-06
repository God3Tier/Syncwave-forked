from uuid import UUID

import httpx


class CatalogueClient:
    def __init__(self, base_url: str, timeout_seconds: float = 2.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._client = self._new_client()

    def _new_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout_seconds)

    def _active_client(self) -> httpx.AsyncClient:
        if self._client.is_closed:
            self._client = self._new_client()
        return self._client

    async def top_songs(self, excluded: set[UUID], limit: int = 5) -> list[UUID]:
        """Return the highest-ranked READY songs not already used by this Jam."""
        cursor: str | None = None
        selected: list[UUID] = []
        while len(selected) < limit:
            response = await self._active_client().get(
                "/songs",
                params={
                    "limit": 100,
                    "processing_status": "READY",
                    "sort": "top",
                    **({"cursor": cursor} if cursor else {}),
                },
            )
            response.raise_for_status()
            payload = response.json()
            for item in payload["items"]:
                song_id = UUID(item["song_id"])
                if song_id not in excluded:
                    selected.append(song_id)
                    if len(selected) == limit:
                        break
            cursor = payload.get("next_cursor")
            if not cursor:
                break
        return selected

    async def record_jam_play(self, song_id: UUID, playback_id: UUID) -> None:
        response = await self._active_client().post(
            f"/songs/{song_id}/plays",
            json={"playback_id": str(playback_id), "source": "JAM"},
        )
        response.raise_for_status()

    async def close(self) -> None:
        await self._client.aclose()


class FakeCatalogueClient:
    """In-memory Catalogue boundary used when Jam runs without service targets."""

    def __init__(self) -> None:
        self.songs: list[UUID] = []
        self.plays: list[tuple[UUID, UUID]] = []

    async def top_songs(self, excluded: set[UUID], limit: int = 5) -> list[UUID]:
        return [song_id for song_id in self.songs if song_id not in excluded][:limit]

    async def record_jam_play(self, song_id: UUID, playback_id: UUID) -> None:
        play = (song_id, playback_id)
        if play not in self.plays:
            self.plays.append(play)

    async def close(self) -> None:
        return None


def create_catalogue_client(base_url: str) -> CatalogueClient | FakeCatalogueClient:
    return CatalogueClient(base_url) if base_url else FakeCatalogueClient()
