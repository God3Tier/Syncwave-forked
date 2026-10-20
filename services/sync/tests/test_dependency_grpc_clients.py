from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import grpc
import pytest

from sync_service.dependencies import (
    GrpcCatalogueClient,
    GrpcStreamingClient,
    SongNotFoundError,
    SongProcessingStatus,
    StreamUnavailableError,
)
from syncwave.media.v1 import media_pb2, media_pb2_grpc


class MediaService(
    media_pb2_grpc.CatalogueQueryServiceServicer,
    media_pb2_grpc.StreamingQueryServiceServicer,
):
    async def GetSong(self, request: object, context: grpc.aio.ServicerContext) -> object:
        if request.song_id.endswith("0000"):
            await context.abort(grpc.StatusCode.NOT_FOUND, "missing")
        return media_pb2.GetSongResponse(
            song_id=request.song_id,
            processing_status=media_pb2.PROCESSING_STATUS_READY,
            duration_ms=180_000,
        )

    async def GetStreamInfo(
        self,
        request: object,
        context: grpc.aio.ServicerContext,
    ) -> object:
        if request.song_id.endswith("0000"):
            await context.abort(grpc.StatusCode.NOT_FOUND, "missing")
        return media_pb2.GetStreamInfoResponse(
            song_id=request.song_id,
            stream_url=f"/api/streaming/tracks/{request.song_id}/audio",
            supports_ranges=True,
        )


@pytest.fixture
async def media_target() -> AsyncIterator[str]:
    server = grpc.aio.server()
    service = MediaService()
    media_pb2_grpc.add_CatalogueQueryServiceServicer_to_server(service, server)
    media_pb2_grpc.add_StreamingQueryServiceServicer_to_server(service, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        yield f"127.0.0.1:{port}"
    finally:
        await server.stop(grace=0)


@pytest.mark.anyio
async def test_media_grpc_clients_resolve_ready_stream(media_target: str) -> None:
    song_id = uuid4()
    catalogue = GrpcCatalogueClient(media_target, "token", 1)
    streaming = GrpcStreamingClient(media_target, "token", 1)
    try:
        song = await catalogue.get_song(song_id)
        stream = await streaming.get_stream(song_id)
    finally:
        await catalogue.close()
        await streaming.close()

    assert song.processing_status is SongProcessingStatus.READY
    assert stream.stream_url == f"/api/streaming/tracks/{song_id}/audio"


@pytest.mark.anyio
async def test_media_grpc_clients_map_not_found(media_target: str) -> None:
    missing_id = UUID(int=0)
    catalogue = GrpcCatalogueClient(media_target, "token", 1)
    streaming = GrpcStreamingClient(media_target, "token", 1)
    try:
        with pytest.raises(SongNotFoundError):
            await catalogue.get_song(missing_id)
        with pytest.raises(StreamUnavailableError):
            await streaming.get_stream(missing_id)
    finally:
        await catalogue.close()
        await streaming.close()
