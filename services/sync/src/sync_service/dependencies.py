import asyncio
import time
from collections.abc import Awaitable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, TypeVar
from uuid import UUID

import grpc

from sync_service.config import Settings
from sync_service.observability import log_event, metrics
from syncwave.media.v1 import media_pb2, media_pb2_grpc

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
class GrpcCatalogueClient:
    target: str
    token: str
    timeout_seconds: float
    _channel: Any = field(init=False, repr=False)
    _stub: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._channel = grpc.aio.insecure_channel(self.target)
        self._stub = media_pb2_grpc.CatalogueQueryServiceStub(self._channel)

    async def get_song(self, song_id: UUID) -> SongMetadata:
        try:
            response = await self._stub.GetSong(
                media_pb2.GetSongRequest(song_id=str(song_id)),
                metadata=(("x-internal-token", self.token),),
                timeout=self.timeout_seconds,
            )
        except grpc.aio.AioRpcError as error:
            if error.code() is grpc.StatusCode.NOT_FOUND:
                raise SongNotFoundError("song not found") from error
            if error.code() is grpc.StatusCode.DEADLINE_EXCEEDED:
                raise DependencyTimeoutError("catalogue timed out") from error
            raise DependencyError("catalogue unavailable") from error

        statuses = {
            media_pb2.PROCESSING_STATUS_PROCESSING: SongProcessingStatus.PROCESSING,
            media_pb2.PROCESSING_STATUS_READY: SongProcessingStatus.READY,
            media_pb2.PROCESSING_STATUS_FAILED: SongProcessingStatus.FAILED,
        }
        processing_status = statuses.get(response.processing_status)
        if response.song_id != str(song_id) or processing_status is None:
            raise DependencyError("catalogue returned an invalid song response")
        return SongMetadata(song_id=song_id, processing_status=processing_status)

    async def close(self) -> None:
        await self._channel.close()


@dataclass(slots=True)
class GrpcStreamingClient:
    target: str
    token: str
    timeout_seconds: float
    _channel: Any = field(init=False, repr=False)
    _stub: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._channel = grpc.aio.insecure_channel(self.target)
        self._stub = media_pb2_grpc.StreamingQueryServiceStub(self._channel)

    async def get_stream(self, song_id: UUID) -> StreamSource:
        try:
            response = await self._stub.GetStreamInfo(
                media_pb2.GetStreamInfoRequest(song_id=str(song_id)),
                metadata=(("x-internal-token", self.token),),
                timeout=self.timeout_seconds,
            )
        except grpc.aio.AioRpcError as error:
            if error.code() is grpc.StatusCode.NOT_FOUND:
                raise StreamUnavailableError("stream not found") from error
            if error.code() is grpc.StatusCode.DEADLINE_EXCEEDED:
                raise DependencyTimeoutError("streaming timed out") from error
            raise StreamUnavailableError("streaming unavailable") from error

        if response.song_id != str(song_id) or not response.stream_url:
            raise StreamUnavailableError("streaming returned an invalid stream response")
        return StreamSource(song_id=song_id, stream_url=response.stream_url)

    async def close(self) -> None:
        await self._channel.close()


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
    stream_urls: dict[UUID, str] = field(default_factory=dict)
    delay_seconds: float = 0
    unavailable: bool = False

    async def get_stream(self, song_id: UUID) -> StreamSource:
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.unavailable or song_id in self.unavailable_song_ids:
            raise StreamUnavailableError("stream unavailable")
        return StreamSource(
            song_id=song_id,
            stream_url=self.stream_urls.get(
                song_id,
                f"/api/streaming/songs/{song_id}/audio",
            ),
        )


@dataclass(slots=True)
class PlaybackDependencies:
    catalogue: CatalogueClient
    streaming: StreamingClient
    timeout_seconds: float

    async def close(self) -> None:
        for client in (self.catalogue, self.streaming):
            close = getattr(client, "close", None)
            if close is not None:
                await close()

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
    timeout_seconds = settings.dependency_timeout_ms / 1_000
    catalogue: CatalogueClient = (
        GrpcCatalogueClient(
            settings.catalogue_grpc_target,
            settings.internal_service_token,
            timeout_seconds,
        )
        if settings.catalogue_grpc_target
        else FakeCatalogueClient()
    )
    streaming: StreamingClient = (
        GrpcStreamingClient(
            settings.streaming_grpc_target,
            settings.internal_service_token,
            timeout_seconds,
        )
        if settings.streaming_grpc_target
        else FakeStreamingClient()
    )
    return PlaybackDependencies(
        catalogue=catalogue,
        streaming=streaming,
        timeout_seconds=timeout_seconds,
    )
