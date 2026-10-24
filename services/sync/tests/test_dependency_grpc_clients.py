from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import grpc
import httpx
import pytest

from sync_service.config import Settings
from sync_service.dependencies import (
    GrpcCatalogueClient,
    GrpcStreamingClient,
    HttpStreamingClient,
    SongNotFoundError,
    SongProcessingStatus,
    StreamUnavailableError,
    create_default_dependencies,
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
async def test_http_streaming_client_resolves_audio_route() -> None:
    song_id = uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/tracks/{song_id}/stream-info"
        return httpx.Response(
            200,
            json={
                "song_id": str(song_id),
                "stream_url": f"/api/streaming/tracks/{song_id}/audio",
                "supports_ranges": False,
            },
        )

    streaming = HttpStreamingClient("http://streaming:8081/", 1)
    await streaming._client.aclose()
    streaming._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        stream = await streaming.get_stream(song_id)
    finally:
        await streaming.close()

    assert stream.stream_url == f"/api/streaming/tracks/{song_id}/audio"


@pytest.mark.anyio
async def test_http_streaming_client_rejects_malformed_metadata() -> None:
    streaming = HttpStreamingClient("http://streaming:8081", 1)
    await streaming._client.aclose()
    streaming._client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"song_id": None, "stream_url": "/api/streaming/tracks/bad/audio"},
            )
        )
    )
    try:
        with pytest.raises(StreamUnavailableError, match="invalid response"):
            await streaming.get_stream(uuid4())
    finally:
        await streaming.close()


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


@pytest.mark.anyio
async def test_default_clients_use_each_upstreams_own_token(media_target: str) -> None:
    dependencies = create_default_dependencies(
        Settings(
            catalogue_grpc_target=media_target,
            catalogue_internal_token="catalogue-token",
            streaming_grpc_target=media_target,
            streaming_internal_token="streaming-token",
        )
    )
    try:
        assert dependencies.catalogue.token == "catalogue-token"
        assert dependencies.streaming.token == "streaming-token"
    finally:
        await dependencies.close()
