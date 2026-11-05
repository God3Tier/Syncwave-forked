"""Where candidate songs come from: the Catalogue Service (plan.md §3.1).

The service talks to the Catalogue through the small `CatalogueClient`
interface. Two implementations exist:

- `StubCatalogue`: a fixed demo list, used until the Catalogue Service exists.
- `HttpCatalogue`: calls the Catalogue over HTTP, see the class docstring.
"""

import uuid
from typing import Any, Protocol

import httpx2

from recommendation_service.errors import CatalogueUnavailable
from recommendation_service.models import Song


class CatalogueClient(Protocol):
    async def list_ready_songs(self, limit: int) -> list[Song]:
        """Up to `limit` songs whose Catalogue `processing_status` is READY, so
        every one can be streamed. Raises CatalogueUnavailable if it cannot."""
        ...


def _demo_song(number: int, title: str, artist: str, minutes: float, mood: str) -> Song:
    # Fixed ids, so the stub returns the same songs on every start.
    return Song(
        song_id=uuid.uuid5(uuid.NAMESPACE_URL, f"syncwave-demo-song-{number}"),
        title=title,
        artist=artist,
        duration_ms=int(minutes * 60_000),
        mood=mood,
    )


DEMO_SONGS = [
    _demo_song(1, "Upbeat Morning", "Demo Artist", 3.2, "upbeat"),
    _demo_song(2, "Rainy Window", "Demo Artist", 3.6, "mellow"),
    _demo_song(3, "Night Drive", "Another Artist", 4.1, "energetic"),
    _demo_song(4, "Slow Tide", "Another Artist", 2.9, "calm"),
    _demo_song(5, "City Lights", "Third Artist", 3.4, "upbeat"),
    _demo_song(6, "Soft Rain", "Third Artist", 3.8, "mellow"),
    _demo_song(7, "Long Way Home", "Demo Artist", 4.4, "calm"),
    _demo_song(8, "Sprint", "Fourth Artist", 2.7, "energetic"),
]


class StubCatalogue:
    """Serves DEMO_SONGS. The ids do not exist in the real Catalogue or Streaming
    Service, so a browser cannot play them; this is for developing the endpoint."""

    async def list_ready_songs(self, limit: int) -> list[Song]:
        return DEMO_SONGS[:limit]


class HttpCatalogue:
    """Asks the Catalogue Service for its READY songs.

    Contract (matches the Catalogue's `GET /songs`; it also returns fields we ignore):

        GET {CATALOGUE_URL}/songs?processing_status=READY&limit=N
        200 {"items": [{"song_id", "title", "artist", "duration_ms", "mood"?}, ...],
             "next_cursor": ...}

    It follows the list shape in contracts/api/README.md. Only the first page is
    read: that is the candidate pool. `mood` is optional in the Catalogue
    Song contract. Any failure, whether a network error, a timeout, a non-200
    status or an unreadable body, becomes CatalogueUnavailable.
    """

    def __init__(self, base_url: str, client: httpx2.AsyncClient) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client

    async def list_ready_songs(self, limit: int) -> list[Song]:
        try:
            response = await self._client.get(
                f"{self._base_url}/songs",
                params={"processing_status": "READY", "limit": limit},
            )
            response.raise_for_status()
            # The Catalogue leaves duration_ms null until Waveform has measured it.
            # Such a song cannot be shown with a length, so skip it instead of
            # failing the whole request.
            return [
                _parse_song(item)
                for item in response.json()["items"]
                if not _has_null_duration(item)
            ]
        except (httpx2.HTTPError, ValueError, KeyError, TypeError) as error:
            # ValueError covers bad JSON and bad UUIDs, KeyError/TypeError a body
            # of the wrong shape.
            raise CatalogueUnavailable(f"The Catalogue Service failed: {error!r}") from error


def _has_null_duration(item: dict[str, Any]) -> bool:
    # Only an explicit null; a missing key is a malformed item and still an error.
    return "duration_ms" in item and item["duration_ms"] is None


def _parse_song(item: dict[str, Any]) -> Song:
    return Song(
        song_id=uuid.UUID(item["song_id"]),
        title=item["title"],
        artist=item["artist"],
        duration_ms=int(item["duration_ms"]),
        mood=item.get("mood"),
    )
