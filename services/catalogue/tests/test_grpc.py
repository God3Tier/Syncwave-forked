import uuid
from datetime import UTC, datetime

import grpc
import pytest

from catalogue_service.config import Settings
from catalogue_service.grpc_service import CatalogueQueryService, create_grpc_server
from catalogue_service.shared.db import (
    ProcessingStatus,
    SongRecord,
    StageStatus,
)
from syncwave.media.v1 import media_pb2


class _Abort(Exception):
    def __init__(self, code, details) -> None:
        self.code = code
        self.details = details


class _Meta:
    def __init__(self, key: str, value: str) -> None:
        self.key = key
        self.value = value


class FakeContext:
    def __init__(self, metadata: list[tuple[str, str]] | None = None) -> None:
        self.code = None
        self.details = None
        self._metadata = [_Meta(k, v) for k, v in (metadata or [])]

    async def abort(self, code, details) -> None:
        self.code = code
        self.details = details
        raise _Abort(code, details)

    def invocation_metadata(self) -> list[_Meta]:
        return list(self._metadata)


class FakeRepository:
    def __init__(self, songs: list[SongRecord]) -> None:
        self._songs = {song.song_id: song for song in songs}

    async def get(self, song_id: uuid.UUID) -> SongRecord | None:
        return self._songs.get(song_id)


def make_song(
    song_id: uuid.UUID,
    *,
    processing_status: ProcessingStatus = ProcessingStatus.READY,
    duration_ms: int | None = None,
    lyrics_status: StageStatus = StageStatus.READY,
    waveform_status: StageStatus = StageStatus.READY,
) -> SongRecord:
    now = datetime(2026, 10, 8, 12, 0, 1, tzinfo=UTC)
    return SongRecord(
        song_id=song_id,
        title="Demo",
        artist="Artist",
        duration_ms=duration_ms,
        audio_reference=f"audio/{song_id}.mp3",
        lyrics_status=lyrics_status.value,
        waveform_status=waveform_status.value,
        processing_status=processing_status.value,
        created_at=now,
        updated_at=now,
    )


def settings(token: str = "test-token") -> Settings:
    return Settings(
        service_name="catalogue",
        log_level="INFO",
        database_url="sqlite+aiosqlite:///:memory:",
        amqp_host="localhost",
        amqp_port=5672,
        amqp_user="syncwave",
        amqp_password="syncwave",
        amqp_prefetch=10,
        internal_service_token=token,
        grpc_port=50051,
    )


def request_for(song_id: uuid.UUID) -> media_pb2.GetSongRequest:
    return media_pb2.GetSongRequest(song_id=str(song_id))


@pytest.mark.asyncio
async def test_get_song_ready() -> None:
    song_id = uuid.uuid4()
    repository = FakeRepository([make_song(song_id, duration_ms=213000)])
    servicer = CatalogueQueryService(repository, settings())
    context = FakeContext([("x-internal-token", "test-token")])

    response = await servicer.GetSong(request_for(song_id), context)

    assert response.song_id == str(song_id)
    assert response.processing_status == media_pb2.PROCESSING_STATUS_READY
    assert response.duration_ms == 213000


@pytest.mark.asyncio
async def test_get_song_not_found() -> None:
    repository = FakeRepository([])
    servicer = CatalogueQueryService(repository, settings())
    context = FakeContext([("x-internal-token", "test-token")])

    with pytest.raises(_Abort) as exc:
        await servicer.GetSong(request_for(uuid.uuid4()), context)

    assert exc.value.code == grpc.StatusCode.NOT_FOUND


@pytest.mark.asyncio
async def test_get_song_invalid_uuid() -> None:
    repository = FakeRepository([])
    servicer = CatalogueQueryService(repository, settings())
    context = FakeContext([("x-internal-token", "test-token")])

    with pytest.raises(_Abort) as exc:
        await servicer.GetSong(media_pb2.GetSongRequest(song_id="not-a-uuid"), context)

    assert exc.value.code == grpc.StatusCode.INVALID_ARGUMENT


@pytest.mark.asyncio
async def test_get_song_unauthenticated() -> None:
    repository = FakeRepository([make_song(uuid.uuid4())])
    servicer = CatalogueQueryService(repository, settings())
    context = FakeContext([])  # no token

    with pytest.raises(_Abort) as exc:
        await servicer.GetSong(request_for(uuid.uuid4()), context)

    assert exc.value.code == grpc.StatusCode.UNAUTHENTICATED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,expected",
    [
        (ProcessingStatus.PROCESSING, media_pb2.PROCESSING_STATUS_PROCESSING),
        (ProcessingStatus.READY, media_pb2.PROCESSING_STATUS_READY),
        (ProcessingStatus.FAILED, media_pb2.PROCESSING_STATUS_FAILED),
        # media.proto has no PARTIAL; it maps to PROCESSING (not ready).
        (ProcessingStatus.PARTIAL, media_pb2.PROCESSING_STATUS_PROCESSING),
    ],
)
async def test_processing_status_mapping(status, expected) -> None:
    song_id = uuid.uuid4()
    repository = FakeRepository([make_song(song_id, processing_status=status)])
    servicer = CatalogueQueryService(repository, settings())
    context = FakeContext([("x-internal-token", "test-token")])

    response = await servicer.GetSong(request_for(song_id), context)

    assert response.processing_status == expected


@pytest.mark.asyncio
async def test_duration_ms_zero_when_unknown() -> None:
    song_id = uuid.uuid4()
    repository = FakeRepository([make_song(song_id, duration_ms=None)])
    servicer = CatalogueQueryService(repository, settings())
    context = FakeContext([("x-internal-token", "test-token")])

    response = await servicer.GetSong(request_for(song_id), context)

    assert response.duration_ms == 0


# Async so it runs in pytest-asyncio's event loop: a grpc.aio server needs one,
# and a synchronous test only finds one if an earlier test happened to leave it.
@pytest.mark.asyncio
async def test_create_grpc_server_binds() -> None:
    server, port = create_grpc_server(FakeRepository([]), settings(), "[::]:0")
    assert port > 0
