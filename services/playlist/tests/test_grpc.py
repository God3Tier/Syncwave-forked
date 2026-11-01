"""The gRPC GetPlaylist call, through a real generated client and a real server."""

import uuid
from collections.abc import AsyncIterator

import grpc
import pytest
from sqlalchemy import Engine

from playlist_service.config import Settings
from playlist_service.db import Database, PlaylistRepository
from playlist_service.grpc_service import create_grpc_server
from syncwave.playlist.v1 import playlist_pb2, playlist_pb2_grpc

from .conftest import API_DATABASE, OWNER_ID

pytestmark = pytest.mark.anyio

TOKEN = "test-internal-token"


def settings(token: str = TOKEN) -> Settings:
    return Settings(
        service_name="playlist",
        log_level="INFO",
        database_url=f"sqlite+aiosqlite:///{API_DATABASE.as_posix()}",
        catalogue_mode="off",
        catalogue_url="http://catalogue:8080",
        catalogue_timeout_seconds=3.0,
        grpc_port=0,
        internal_service_token=token,
    )


@pytest.fixture
async def repository(api_db: Engine) -> AsyncIterator[PlaylistRepository]:
    database = Database(settings().database_url)
    yield PlaylistRepository(database.sessions)
    await database.dispose()


@pytest.fixture
async def stub(
    repository: PlaylistRepository,
) -> AsyncIterator[playlist_pb2_grpc.PlaylistQueryServiceStub]:
    server, port = create_grpc_server(repository, settings(), "127.0.0.1:0")
    await server.start()
    async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
        yield playlist_pb2_grpc.PlaylistQueryServiceStub(channel)
    await server.stop(grace=None)


AUTH = (("x-internal-token", TOKEN),)


async def make_playlist(repository: PlaylistRepository, songs: list[uuid.UUID]) -> uuid.UUID:
    playlist = await repository.create(uuid.UUID(OWNER_ID), "Rainy day")
    for song in songs:
        await repository.add_song(playlist.playlist_id, song, None)
    return playlist.playlist_id


async def test_returns_the_playlist_with_songs_in_order(
    stub: playlist_pb2_grpc.PlaylistQueryServiceStub, repository: PlaylistRepository
) -> None:
    songs = [uuid.uuid4() for _ in range(3)]
    playlist_id = await make_playlist(repository, songs)

    reply = await stub.GetPlaylist(
        playlist_pb2.GetPlaylistRequest(playlist_id=str(playlist_id)), metadata=AUTH
    )

    assert (reply.playlist_id, reply.owner_id, reply.name) == (
        str(playlist_id),
        OWNER_ID,
        "Rainy day",
    )
    assert [(song.song_id, song.position) for song in reply.songs] == [
        (str(song), index) for index, song in enumerate(songs)
    ]


async def test_follows_a_reorder_and_a_shuffle(
    stub: playlist_pb2_grpc.PlaylistQueryServiceStub, repository: PlaylistRepository
) -> None:
    songs = [uuid.uuid4() for _ in range(4)]
    playlist_id = await make_playlist(repository, songs)
    request = playlist_pb2.GetPlaylistRequest(playlist_id=str(playlist_id))

    await repository.reorder(playlist_id, songs[::-1])
    reply = await stub.GetPlaylist(request, metadata=AUTH)
    assert [song.song_id for song in reply.songs] == [str(song) for song in songs[::-1]]

    shuffled = await repository.shuffle(playlist_id)
    reply = await stub.GetPlaylist(request, metadata=AUTH)
    assert [song.song_id for song in reply.songs] == [str(song) for song in shuffled.songs]


async def test_an_empty_playlist_has_no_songs(
    stub: playlist_pb2_grpc.PlaylistQueryServiceStub, repository: PlaylistRepository
) -> None:
    playlist_id = await make_playlist(repository, [])
    reply = await stub.GetPlaylist(
        playlist_pb2.GetPlaylistRequest(playlist_id=str(playlist_id)), metadata=AUTH
    )
    assert list(reply.songs) == []


async def test_an_unknown_playlist_is_not_found(
    stub: playlist_pb2_grpc.PlaylistQueryServiceStub,
) -> None:
    with pytest.raises(grpc.aio.AioRpcError) as error:
        await stub.GetPlaylist(
            playlist_pb2.GetPlaylistRequest(playlist_id=str(uuid.uuid4())), metadata=AUTH
        )
    assert error.value.code() == grpc.StatusCode.NOT_FOUND


@pytest.mark.parametrize("playlist_id", ["", "abc", "123"])
async def test_a_playlist_id_that_is_not_a_uuid_is_invalid(
    stub: playlist_pb2_grpc.PlaylistQueryServiceStub, playlist_id: str
) -> None:
    with pytest.raises(grpc.aio.AioRpcError) as error:
        await stub.GetPlaylist(
            playlist_pb2.GetPlaylistRequest(playlist_id=playlist_id), metadata=AUTH
        )
    assert error.value.code() == grpc.StatusCode.INVALID_ARGUMENT


@pytest.mark.parametrize("metadata", [(), (("x-internal-token", "wrong"),)])
async def test_a_missing_or_wrong_token_is_unauthenticated(
    stub: playlist_pb2_grpc.PlaylistQueryServiceStub,
    repository: PlaylistRepository,
    metadata: tuple[tuple[str, str], ...],
) -> None:
    playlist_id = await make_playlist(repository, [uuid.uuid4()])
    with pytest.raises(grpc.aio.AioRpcError) as error:
        await stub.GetPlaylist(
            playlist_pb2.GetPlaylistRequest(playlist_id=str(playlist_id)), metadata=metadata
        )
    assert error.value.code() == grpc.StatusCode.UNAUTHENTICATED


async def test_the_server_refuses_to_start_without_a_token(
    repository: PlaylistRepository,
) -> None:
    with pytest.raises(ValueError, match="INTERNAL_SERVICE_TOKEN"):
        create_grpc_server(repository, settings(token=""), "127.0.0.1:0")
