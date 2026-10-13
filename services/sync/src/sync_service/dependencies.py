import asyncio
import time
from collections.abc import Awaitable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, TypeVar
from uuid import UUID

from sync_service.config import Settings
from sync_service.observability import log_event, metrics

T = TypeVar("T")


class SongProcessingStatus(StrEnum):
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


class DependencyError(Exception):
    """Base class for stable dependency failures exposed by Sync."""


class SongNotFoundError(DependencyError):
    pass


class SongNotReadyError(DependencyError):
    pass


class StreamUnavailableError(DependencyError):
    pass


class DependencyTimeoutError(DependencyError):
    pass


@dataclass(frozen=True, slots=True)
class SongMetadata:
    song_id: UUID
    processing_status: SongProcessingStatus


@dataclass(frozen=True, slots=True)
class StreamSource:
    song_id: UUID
    stream_url: str


class CatalogueClient(Protocol):
    async def get_song(self, song_id: UUID) -> SongMetadata: ...


class StreamingClient(Protocol):
    async def get_stream(self, song_id: UUID) -> StreamSource: ...


@dataclass(slots=True)
class FakeCatalogueClient:
    statuses: dict[UUID, SongProcessingStatus | None] = field(default_factory=dict)
    delay_seconds: float = 0
    unavailable: bool = False

    async def get_song(self, song_id: UUID) -> SongMetadata:
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.unavailable:
            raise DependencyError("catalogue unavailable")
        status = self.statuses.get(song_id, SongProcessingStatus.READY)
        if status is None:
            raise SongNotFoundError("song not found")
        return SongMetadata(song_id=song_id, processing_status=status)


@dataclass(slots=True)
class FakeStreamingClient:
    unavailable_song_ids: set[UUID] = field(default_factory=set)
    delay_seconds: float = 0
    unavailable: bool = False

    async def get_stream(self, song_id: UUID) -> StreamSource:
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.unavailable or song_id in self.unavailable_song_ids:
            raise StreamUnavailableError("stream unavailable")
        return StreamSource(
            song_id=song_id,
            stream_url=f"/api/streaming/songs/{song_id}/audio",
        )


@dataclass(slots=True)
class PlaybackDependencies:
    catalogue: CatalogueClient
    streaming: StreamingClient
    timeout_seconds: float

    async def resolve(self, song_id: UUID) -> StreamSource:
        song = await self._with_timeout(self.catalogue.get_song(song_id), "catalogue")
        if song.processing_status is not SongProcessingStatus.READY:
            raise SongNotReadyError(
                f"song is not ready: processing_status={song.processing_status.value}"
            )
        return await self._with_timeout(self.streaming.get_stream(song_id), "streaming")

    async def _with_timeout(self, operation: Awaitable[T], dependency: str) -> T:
        started = time.perf_counter()
        outcome = "success"
        try:
            return await asyncio.wait_for(operation, timeout=self.timeout_seconds)
        except TimeoutError as error:
            outcome = "timeout"
            raise DependencyTimeoutError(f"{dependency} timed out") from error
        except DependencyError:
            outcome = "failure"
            raise
        finally:
            duration_ms = (time.perf_counter() - started) * 1_000
            metrics.dependency_duration_ms.labels(
                service=dependency,
                method="resolve",
                status=outcome,
            ).observe(duration_ms)
            log_event(
                "dependency_request",
                transport="internal",
                message_type=f"{dependency}.resolve",
                outcome=outcome,
                duration_ms=round(duration_ms, 3),
            )


def create_default_dependencies(settings: Settings) -> PlaybackDependencies:
    return PlaybackDependencies(
        catalogue=FakeCatalogueClient(),
        streaming=FakeStreamingClient(),
        timeout_seconds=settings.dependency_timeout_ms / 1_000,
    )
