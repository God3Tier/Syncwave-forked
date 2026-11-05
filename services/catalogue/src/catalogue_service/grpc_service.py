"""gRPC query service: CatalogueQueryService.GetSong (contracts/grpc/syncwave/media/v1/media.proto).

Run beside FastAPI on the internal port (50051). Sync and other internal
callers authenticate with x-internal-token. Catalogue does not expose write
paths over gRPC: songs are created and updated through AMQP events only.
"""

from hmac import compare_digest
from uuid import UUID

import grpc

from catalogue_service.config import Settings
from catalogue_service.shared.db import CatalogueRepository, ProcessingStatus
from syncwave.media.v1 import media_pb2, media_pb2_grpc


def _processing_status_to_grpc(status: str) -> media_pb2.ProcessingStatus:
    """Maps the canonical processing status to the protobuf enum.

    media.proto has no PARTIAL value, so PARTIAL is reported as PROCESSING:
    both mean "not yet fully ready", which is all Sync's GetSong gate needs.
    """
    return {
        ProcessingStatus.PROCESSING: media_pb2.PROCESSING_STATUS_PROCESSING,
        ProcessingStatus.PARTIAL: media_pb2.PROCESSING_STATUS_PROCESSING,
        ProcessingStatus.READY: media_pb2.PROCESSING_STATUS_READY,
        ProcessingStatus.FAILED: media_pb2.PROCESSING_STATUS_FAILED,
    }[status]


class CatalogueQueryService(media_pb2_grpc.CatalogueQueryServiceServicer):
    def __init__(self, repository: CatalogueRepository, settings: Settings) -> None:
        self._repository = repository
        self._settings = settings

    async def GetSong(
        self, request: media_pb2.GetSongRequest, context: grpc.aio.ServicerContext
    ) -> media_pb2.GetSongResponse:
        metadata = {item.key.lower(): item.value for item in context.invocation_metadata()}
        token = metadata.get("x-internal-token")
        if token is None or not compare_digest(token, self._settings.internal_service_token):
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "invalid service token")
            raise AssertionError("context.abort must terminate the RPC")

        try:
            song_id = UUID(request.song_id)
        except (ValueError, AttributeError, TypeError) as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "song_id must be a UUID")
            raise AssertionError("context.abort must terminate the RPC") from exc

        record = await self._repository.get(song_id)
        if record is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, "song not found")
            raise AssertionError("context.abort must terminate the RPC")

        return media_pb2.GetSongResponse(
            song_id=str(record.song_id),
            processing_status=_processing_status_to_grpc(record.processing_status),
            duration_ms=record.duration_ms or 0,
        )


def create_grpc_server(
    repository: CatalogueRepository,
    settings: Settings,
    bind: str,
) -> tuple[grpc.aio.Server, int]:
    server = grpc.aio.server(
        options=(
            ("grpc.max_receive_message_length", 64 * 1024),
            ("grpc.max_send_message_length", 64 * 1024),
        )
    )
    media_pb2_grpc.add_CatalogueQueryServiceServicer_to_server(
        CatalogueQueryService(repository, settings), server
    )
    port = server.add_insecure_port(bind)
    if port == 0:
        raise RuntimeError(f"could not bind gRPC server to {bind}")
    return server, port
