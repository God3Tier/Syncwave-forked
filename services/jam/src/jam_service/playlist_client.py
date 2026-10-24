from dataclasses import dataclass, field
from uuid import UUID

import grpc

from jam_service.config import Settings
from syncwave.playlist.v1 import playlist_pb2, playlist_pb2_grpc


class PlaylistClientError(RuntimeError):
    pass


class PlaylistNotFoundError(PlaylistClientError):
    pass


class PlaylistClient:
    async def get_song_ids(self, playlist_id: UUID) -> list[UUID]:
        raise NotImplementedError

    async def close(self) -> None:
        return None


@dataclass(slots=True)
class FakePlaylistClient(PlaylistClient):
    playlists: dict[UUID, list[UUID]] = field(default_factory=dict)

    async def get_song_ids(self, playlist_id: UUID) -> list[UUID]:
        try:
            return list(self.playlists[playlist_id])
        except KeyError as error:
            raise PlaylistNotFoundError("playlist not found") from error


class GrpcPlaylistClient(PlaylistClient):
    def __init__(self, settings: Settings) -> None:
        self._channel = grpc.aio.insecure_channel(settings.playlist_grpc_target)
        self._stub = playlist_pb2_grpc.PlaylistQueryServiceStub(self._channel)
        self._timeout = settings.playlist_timeout_ms / 1_000
        self._metadata = (("x-internal-token", settings.playlist_internal_token),)

    async def get_song_ids(self, playlist_id: UUID) -> list[UUID]:
        try:
            response = await self._stub.GetPlaylist(
                playlist_pb2.GetPlaylistRequest(playlist_id=str(playlist_id)),
                metadata=self._metadata,
                timeout=self._timeout,
            )
        except grpc.aio.AioRpcError as error:
            if error.code() is grpc.StatusCode.NOT_FOUND:
                raise PlaylistNotFoundError("playlist not found") from error
            raise PlaylistClientError(error.details() or "Playlist is unavailable") from error

        if response.playlist_id != str(playlist_id):
            raise PlaylistClientError("Playlist returned an invalid playlist response")
        ordered = sorted(response.songs, key=lambda song: song.position)
        if [song.position for song in ordered] != list(range(len(ordered))):
            raise PlaylistClientError("Playlist returned invalid song positions")
        try:
            return [UUID(song.song_id) for song in ordered]
        except ValueError as error:
            raise PlaylistClientError("Playlist returned an invalid song ID") from error

    async def close(self) -> None:
        await self._channel.close()


def create_playlist_client(settings: Settings) -> PlaylistClient:
    if settings.playlist_grpc_target:
        return GrpcPlaylistClient(settings)
    return FakePlaylistClient()
