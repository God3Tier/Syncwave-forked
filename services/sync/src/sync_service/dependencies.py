import asyncio
import time
from collections.abc import Awaitable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, TypeVar
from uuid import UUID

import grpc
import httpx

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
    duration_ms: int | None = None


@dataclass(frozen=True, slots=True)
class StreamSource:
    song_id: UUID
    stream_url: str
    duration_ms: int | None = None


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
        return SongMetadata(
            song_id=song_id,
            processing_status=processing_status,
            duration_ms=response.duration_ms if response.duration_ms > 0 else None,
        )

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
class HttpStreamingClient:
    base_url: str
    timeout_seconds: float
    _client: httpx.AsyncClient = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=self.timeout_seconds)

    async def get_stream(self, song_id: UUID) -> StreamSource:
        try:
            response = await self._client.get(f"{self.base_url}/tracks/{song_id}/stream-info")
        except httpx.TimeoutException as error:
            raise DependencyTimeoutError("streaming timed out") from error
        except httpx.HTTPError as error:
            raise StreamUnavailableError("streaming unavailable") from error

        if response.status_code == 404:
            raise StreamUnavailableError("stream not found")
        if response.status_code == 409:
            raise SongNotReadyError("song is not ready for streaming")
        if response.status_code != 200:
            raise StreamUnavailableError("streaming unavailable")

        try:
            payload = response.json()
            raw_song_id = payload["song_id"]
            stream_url = payload["stream_url"]
        except (KeyError, TypeError, ValueError) as error:
            raise StreamUnavailableError("streaming returned an invalid response") from error
        if not isinstance(raw_song_id, str) or not isinstance(stream_url, str) or not stream_url:
            raise StreamUnavailableError("streaming returned an invalid response")
        try:
            response_song_id = UUID(raw_song_id)
        except ValueError as error:
            raise StreamUnavailableError("streaming returned an invalid response") from error
        if response_song_id != song_id:
            raise StreamUnavailableError("streaming returned an invalid response")
        return StreamSource(song_id=song_id, stream_url=stream_url)

    async def close(self) -> None:
        await self._client.aclose()


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
        return SongMetadata(song_id=song_id, processing_status=status, duration_ms=180_000)


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
        stream = await self._with_timeout(self.streaming.get_stream(song_id), "streaming")
        if song.duration_ms is None:
            raise SongNotReadyError("song duration is not ready")
        return StreamSource(
            song_id=stream.song_id,
            stream_url=stream.stream_url,
            duration_ms=song.duration_ms,
        )

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
            settings.catalogue_internal_token,
            timeout_seconds,
        )
        if settings.catalogue_grpc_target
        else FakeCatalogueClient()
    )
    if settings.streaming_grpc_target:
        streaming: StreamingClient = GrpcStreamingClient(
            settings.streaming_grpc_target,
            settings.streaming_internal_token,
            timeout_seconds,
        )
    elif settings.streaming_http_url:
        streaming = HttpStreamingClient(settings.streaming_http_url, timeout_seconds)
    else:
        streaming = FakeStreamingClient()
    return PlaybackDependencies(
        catalogue=catalogue,
        streaming=streaming,
        timeout_seconds=timeout_seconds,
    )
