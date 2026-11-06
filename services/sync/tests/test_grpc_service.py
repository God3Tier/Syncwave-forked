import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import grpc
import pytest

from sync_service.config import Settings
from sync_service.dependencies import (
    FakeCatalogueClient,
    FakeStreamingClient,
    PlaybackDependencies,
    SongProcessingStatus,
)
from sync_service.grpc_service import create_grpc_server
from sync_service.manager import SessionManager, SyncSession
from sync_service.models import PlaybackState, StartSessionRequest
from sync_service.repository import SessionRepository
from syncwave.sync.v1 import sync_pb2, sync_pb2_grpc

AUTH_METADATA = (("x-internal-token", "local-jam-to-sync-token"),)
GrpcStack = tuple[
    SessionManager,
    sync_pb2_grpc.SyncControlServiceStub,
    FakeCatalogueClient,
    FakeStreamingClient,
    PlaybackDependencies,
]


class CapturingConnection:
    def __init__(self) -> None:
        self.frames: list[dict[str, object]] = []

    async def send_json(self, frame: dict[str, object]) -> None:
        self.frames.append(frame)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def grpc_stack(
    tmp_path: Path,
) -> AsyncIterator[GrpcStack]:
    database_path = tmp_path / "grpc.db"
    repository = SessionRepository(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    manager = SessionManager(repository)
    await manager.initialize()
    settings = Settings(database_url=f"sqlite+aiosqlite:///{database_path.as_posix()}", grpc_port=0)
    catalogue = FakeCatalogueClient()
    streaming = FakeStreamingClient()
    dependencies = PlaybackDependencies(catalogue, streaming, timeout_seconds=0.75)
    server, port = create_grpc_server(manager, settings, dependencies, "127.0.0.1:0")
    await server.start()
    channel = grpc.aio.insecure_channel(f"127.0.0.1:{port}")
    try:
        yield (
            manager,
            sync_pb2_grpc.SyncControlServiceStub(channel),
            catalogue,
            streaming,
            dependencies,
        )
    finally:
        await channel.close()
        await server.stop(grace=0)
        await manager.close()


def start_request() -> sync_pb2.StartPlaybackRequest:
    participant_id = str(uuid4())
    return sync_pb2.StartPlaybackRequest(
        request_id=str(uuid4()),
        jam_id=str(uuid4()),
        owner_id=participant_id,
        selection=sync_pb2.PlaybackSelection(
            queue_item_id=str(uuid4()),
            song_id=str(uuid4()),
        ),
        participant_ids=[participant_id],
    )


@pytest.mark.anyio
async def test_generated_grpc_service_runs_full_control_flow(
    grpc_stack: GrpcStack,
) -> None:
    manager, stub, _, _, _ = grpc_stack
    request = start_request()

    with pytest.raises(grpc.aio.AioRpcError) as unauthorized:
        await stub.GetPlaybackState(
            sync_pb2.GetPlaybackStateRequest(jam_id=request.jam_id),
            timeout=2,
        )
    assert unauthorized.value.code() is grpc.StatusCode.UNAUTHENTICATED

    started = await stub.StartPlayback(request, metadata=AUTH_METADATA, timeout=2)
    assert started.playback.state == sync_pb2.PLAYBACK_STATE_PREPARING
    readiness = await stub.GetReadinessStatus(
        sync_pb2.GetReadinessStatusRequest(jam_id=request.jam_id),
        metadata=AUTH_METADATA,
        timeout=2,
    )
    # Persisted membership is not the same as an open Sync connection. Only
    # connected listeners participate in the readiness barrier.
    assert readiness.unready_participant_ids == []

    late_participant_id = str(uuid4())
    updated = await stub.UpdateParticipants(
        sync_pb2.UpdateParticipantsRequest(
            request_id=str(uuid4()),
            jam_id=request.jam_id,
            generation=1,
            participant_ids=[request.owner_id, late_participant_id],
        ),
        metadata=AUTH_METADATA,
        timeout=2,
    )
    assert updated.playback.generation == 1
    readiness = await stub.GetReadinessStatus(
        sync_pb2.GetReadinessStatusRequest(jam_id=request.jam_id),
        metadata=AUTH_METADATA,
        timeout=2,
    )
    assert readiness.unready_participant_ids == []

    session = manager.get(UUID(request.jam_id))
    assert session is not None
    session.state = PlaybackState.PLAYING
    session.anchor_server_time_ms = time.time_ns() // 1_000_000 - 1_000

    paused = await stub.PausePlayback(
        sync_pb2.PausePlaybackRequest(
            request_id=str(uuid4()),
            jam_id=request.jam_id,
            generation=1,
        ),
        metadata=AUTH_METADATA,
        timeout=2,
    )
    assert paused.playback.state == sync_pb2.PLAYBACK_STATE_PAUSED

    resumed = await stub.ResumePlayback(
        sync_pb2.ResumePlaybackRequest(
            request_id=str(uuid4()),
            jam_id=request.jam_id,
            generation=1,
        ),
        metadata=AUTH_METADATA,
        timeout=2,
    )
    assert resumed.playback.state == sync_pb2.PLAYBACK_STATE_SCHEDULED

    sought = await stub.SeekPlayback(
        sync_pb2.SeekPlaybackRequest(
            request_id=str(uuid4()),
            jam_id=request.jam_id,
            generation=1,
            position_ms=42_000,
        ),
        metadata=AUTH_METADATA,
        timeout=2,
    )
    assert sought.playback.anchor_position_ms == 42_000

    skipped = await stub.SkipPlayback(
        sync_pb2.SkipPlaybackRequest(
            request_id=str(uuid4()),
            jam_id=request.jam_id,
            generation=1,
            next_selection=sync_pb2.PlaybackSelection(
                queue_item_id=str(uuid4()),
                song_id=str(uuid4()),
            ),
        ),
        metadata=AUTH_METADATA,
        timeout=2,
    )
    assert skipped.playback.generation == 2
    assert skipped.playback.state == sync_pb2.PLAYBACK_STATE_PREPARING

    with pytest.raises(grpc.aio.AioRpcError) as stale:
        await stub.PausePlayback(
            sync_pb2.PausePlaybackRequest(
                request_id=str(uuid4()),
                jam_id=request.jam_id,
                generation=1,
            ),
            metadata=AUTH_METADATA,
            timeout=2,
        )
    assert stale.value.code() is grpc.StatusCode.ABORTED


@pytest.mark.anyio
async def test_preloaded_transition_is_retimed_after_pause_and_resume(
    grpc_stack: GrpcStack,
) -> None:
    manager, stub, _, _, _ = grpc_stack
    request = start_request()
    await stub.StartPlayback(request, metadata=AUTH_METADATA, timeout=2)
    session = manager.get(UUID(request.jam_id))
    assert session is not None
    connection = CapturingConnection()
    participant_id = UUID(request.owner_id)
    session.participants[participant_id].connection = connection  # type: ignore[assignment]
    session.participants[participant_id].ready = True
    session.state = PlaybackState.PLAYING
    session.anchor_server_time_ms = time.time_ns() // 1_000_000 - 1_000

    next_queue_item_id = uuid4()
    next_song_id = uuid4()
    queue_request_id = str(uuid4())
    updated = await stub.UpdateQueue(
        sync_pb2.UpdateQueueRequest(
            request_id=queue_request_id,
            jam_id=request.jam_id,
            generation=1,
            selections=[
                request.selection,
                sync_pb2.PlaybackSelection(
                    queue_item_id=str(next_queue_item_id),
                    song_id=str(next_song_id),
                ),
            ],
        ),
        metadata=AUTH_METADATA,
        timeout=2,
    )
    assert updated.playback.pending_queue_item_id == str(next_queue_item_id)
    assert connection.frames[-1]["type"] == "PRELOAD"
    frame_count = len(connection.frames)
    repeated = await stub.UpdateQueue(
        sync_pb2.UpdateQueueRequest(
            request_id=queue_request_id,
            jam_id=request.jam_id,
            generation=1,
            selections=[
                request.selection,
                sync_pb2.PlaybackSelection(
                    queue_item_id=str(next_queue_item_id),
                    song_id=str(next_song_id),
                ),
            ],
        ),
        metadata=AUTH_METADATA,
        timeout=2,
    )
    assert repeated.playback.pending_queue_item_id == str(next_queue_item_id)
    assert len(connection.frames) == frame_count

    target = await manager.mark_pending_ready(session, participant_id)
    assert target is not None
    original_target = target

    await stub.PausePlayback(
        sync_pb2.PausePlaybackRequest(request_id=str(uuid4()), jam_id=request.jam_id, generation=1),
        metadata=AUTH_METADATA,
        timeout=2,
    )
    assert session.pending is not None
    assert session.pending.transition_server_time_ms is None

    await stub.ResumePlayback(
        sync_pb2.ResumePlaybackRequest(
            request_id=str(uuid4()), jam_id=request.jam_id, generation=1
        ),
        metadata=AUTH_METADATA,
        timeout=2,
    )
    assert session.pending.transition_server_time_ms is not None
    assert session.pending.transition_server_time_ms > original_target
    assert connection.frames[-1]["type"] == "TRANSITION_AT"


@pytest.mark.anyio
async def test_grpc_maps_invalid_input_and_honors_deadline(
    grpc_stack: GrpcStack,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, stub, _, _, _ = grpc_stack
    invalid = start_request()
    invalid.jam_id = "not-a-uuid"
    with pytest.raises(grpc.aio.AioRpcError) as invalid_error:
        await stub.StartPlayback(invalid, metadata=AUTH_METADATA, timeout=2)
    assert invalid_error.value.code() is grpc.StatusCode.INVALID_ARGUMENT

    original_start = manager.start

    async def delayed_start(
        request: StartSessionRequest,
        prepare_deadline_ms: int,
        stream_url: str | None = None,
        duration_ms: int | None = None,
    ) -> SyncSession:
        await asyncio.sleep(0.1)
        return await original_start(request, prepare_deadline_ms, stream_url, duration_ms)

    monkeypatch.setattr(manager, "start", delayed_start)
    with pytest.raises(grpc.aio.AioRpcError) as deadline:
        await stub.StartPlayback(start_request(), metadata=AUTH_METADATA, timeout=0.01)
    assert deadline.value.code() is grpc.StatusCode.DEADLINE_EXCEEDED


@pytest.mark.anyio
async def test_grpc_maps_catalogue_and_streaming_failures(grpc_stack: GrpcStack) -> None:
    _, stub, catalogue, streaming, dependencies = grpc_stack

    not_ready = start_request()
    catalogue.statuses[UUID(not_ready.selection.song_id)] = SongProcessingStatus.PROCESSING
    with pytest.raises(grpc.aio.AioRpcError) as not_ready_error:
        await stub.StartPlayback(not_ready, metadata=AUTH_METADATA, timeout=2)
    assert not_ready_error.value.code() is grpc.StatusCode.FAILED_PRECONDITION

    unavailable = start_request()
    streaming.unavailable_song_ids.add(UUID(unavailable.selection.song_id))
    with pytest.raises(grpc.aio.AioRpcError) as unavailable_error:
        await stub.StartPlayback(unavailable, metadata=AUTH_METADATA, timeout=2)
    assert unavailable_error.value.code() is grpc.StatusCode.UNAVAILABLE

    timed_out = start_request()
    catalogue.delay_seconds = 0.1
    dependencies.timeout_seconds = 0.01
    with pytest.raises(grpc.aio.AioRpcError) as timeout_error:
        await stub.StartPlayback(timed_out, metadata=AUTH_METADATA, timeout=2)
    assert timeout_error.value.code() is grpc.StatusCode.DEADLINE_EXCEEDED


@pytest.mark.anyio
async def test_grpc_correlation_id_is_propagated(grpc_stack: GrpcStack) -> None:
    _, stub, _, _, _ = grpc_stack
    call = stub.StartPlayback(
        start_request(),
        metadata=AUTH_METADATA + (("x-correlation-id", "grpc-jam-42"),),
        timeout=2,
    )

    await call
    metadata = await call.initial_metadata()

    assert metadata["x-correlation-id"] == "grpc-jam-42"
