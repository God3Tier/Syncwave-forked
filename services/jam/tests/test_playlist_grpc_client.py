from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import grpc
import pytest

from jam_service.config import Settings
from jam_service.playlist_client import GrpcPlaylistClient, PlaylistNotFoundError
from syncwave.playlist.v1 import playlist_pb2, playlist_pb2_grpc


class PlaylistService(playlist_pb2_grpc.PlaylistQueryServiceServicer):
    def __init__(self, playlist_id: str, song_ids: list[str]) -> None:
        self.playlist_id = playlist_id
        self.song_ids = song_ids

    async def GetPlaylist(self, request, context):
        metadata = dict(context.invocation_metadata())
        if metadata.get("x-internal-token") != "playlist-token":
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "bad token")
        if request.playlist_id != self.playlist_id:
            await context.abort(grpc.StatusCode.NOT_FOUND, "missing")
        return playlist_pb2.GetPlaylistResponse(
            playlist_id=self.playlist_id,
            owner_id=str(uuid4()),
            name="Road trip",
            songs=[
                playlist_pb2.PlaylistSong(song_id=song_id, position=position)
                for position, song_id in reversed(list(enumerate(self.song_ids)))
            ],
        )


@pytest.fixture
async def playlist_server() -> AsyncIterator[tuple[str, UUID, list[UUID]]]:
    playlist_id = uuid4()
    song_ids = [uuid4(), uuid4(), uuid4()]
    server = grpc.aio.server()
    playlist_pb2_grpc.add_PlaylistQueryServiceServicer_to_server(
        PlaylistService(str(playlist_id), [str(song_id) for song_id in song_ids]), server
    )
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        yield f"127.0.0.1:{port}", playlist_id, song_ids
    finally:
        await server.stop(grace=0)


@pytest.mark.anyio
async def test_playlist_client_authenticates_and_preserves_position_order(playlist_server) -> None:
    target, playlist_id, song_ids = playlist_server
    client = GrpcPlaylistClient(
        Settings(
            playlist_grpc_target=target,
            playlist_internal_token="playlist-token",
            playlist_timeout_ms=1_000,
        )
    )
    try:
        assert await client.get_song_ids(playlist_id) == song_ids
        with pytest.raises(PlaylistNotFoundError):
            await client.get_song_ids(uuid4())
    finally:
        await client.close()
