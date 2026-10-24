"""gRPC read access to playlists for Jam and Sync (plan.md section 10).

Contract: contracts/grpc/syncwave/playlist/v1/playlist.proto. Read-only; the
REST API stays the only way to change a playlist. Callers prove who they are
with the `x-internal-token` metadata header, the same way Jam calls Sync.
"""

import logging
import uuid
from hmac import compare_digest

import grpc

from playlist_service.config import Settings
from playlist_service.db import PlaylistRepository
from syncwave.playlist.v1 import playlist_pb2, playlist_pb2_grpc

logger = logging.getLogger(__name__)


class PlaylistQueryService(playlist_pb2_grpc.PlaylistQueryServiceServicer):
    def __init__(self, repository: PlaylistRepository, internal_token: str) -> None:
        self._repository = repository
        self._internal_token = internal_token

    async def GetPlaylist(  # noqa: N802 (name fixed by the generated base class)
        self,
        request: playlist_pb2.GetPlaylistRequest,
        context: grpc.aio.ServicerContext,
    ) -> playlist_pb2.GetPlaylistResponse:
        await self._authorize(context)
        try:
            playlist_id = uuid.UUID(request.playlist_id)
        except ValueError:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "playlist_id is not a UUID")
        playlist = await self._repository.get(playlist_id)
        if playlist is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, f"No playlist with id {playlist_id}")
        return playlist_pb2.GetPlaylistResponse(
            playlist_id=str(playlist.playlist_id),
            owner_id=str(playlist.owner_id),
            name=playlist.name,
            songs=[
                playlist_pb2.PlaylistSong(song_id=str(song_id), position=position)
                for position, song_id in enumerate(playlist.songs)
            ],
        )

    async def _authorize(self, context: grpc.aio.ServicerContext) -> None:
        metadata = {item.key.lower(): item.value for item in context.invocation_metadata()}
        token = metadata.get("x-internal-token")
        if token is None or not compare_digest(token, self._internal_token):
            # The token itself is never logged.
            logger.warning("gRPC call refused: missing or invalid service token")
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "invalid service token")


def create_grpc_server(
    repository: PlaylistRepository, settings: Settings, bind: str
) -> tuple[grpc.aio.Server, int]:
    """Returns the (not yet started) server and the port it bound, so a test can
    pass port 0 and learn the real one."""
    if not settings.internal_service_token:
        raise ValueError("INTERNAL_SERVICE_TOKEN must be set when the gRPC server is enabled")
    server = grpc.aio.server(
        options=(
            ("grpc.max_receive_message_length", 64 * 1024),
            ("grpc.max_send_message_length", 4 * 1024 * 1024),
        )
    )
    playlist_pb2_grpc.add_PlaylistQueryServiceServicer_to_server(
        PlaylistQueryService(repository, settings.internal_service_token), server
    )
    port = server.add_insecure_port(bind)
    if port == 0:
        raise RuntimeError(f"could not bind gRPC server to {bind}")
    return server, port
