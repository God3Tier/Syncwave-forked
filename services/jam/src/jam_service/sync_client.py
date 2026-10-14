from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

import grpc

from jam_service.config import Settings
from jam_service.models import JamState, QueueItem, ReadinessDecision
from syncwave.sync.v1 import sync_pb2, sync_pb2_grpc


class SyncClientError(RuntimeError):
    pass


class SyncConflictError(SyncClientError):
    pass


@dataclass(frozen=True, slots=True)
class SyncSnapshot:
    generation: int
    state: JamState


@dataclass(frozen=True, slots=True)
class ReadinessStatus:
    generation: int
    prepare_deadline_ms: int
    timed_out: bool
    decision_required: bool
    ready_participant_ids: list[UUID]
    unready_participant_ids: list[UUID]


class Command(StrEnum):
    PAUSE = "pause"
    RESUME = "resume"


_PROTO_STATES = {
    sync_pb2.PLAYBACK_STATE_IDLE: JamState.IDLE,
    sync_pb2.PLAYBACK_STATE_PREPARING: JamState.PREPARING,
    sync_pb2.PLAYBACK_STATE_SCHEDULED: JamState.SCHEDULED,
    sync_pb2.PLAYBACK_STATE_PLAYING: JamState.PLAYING,
    sync_pb2.PLAYBACK_STATE_PAUSED: JamState.PAUSED,
    sync_pb2.PLAYBACK_STATE_ENDED: JamState.ENDED,
}


class SyncClient:
    async def start(
        self,
        request_id: UUID,
        jam_id: UUID,
        owner_id: UUID,
        selection: QueueItem,
        participant_ids: list[UUID],
    ) -> SyncSnapshot:
        raise NotImplementedError

    async def command(
        self, command: Command, request_id: UUID, jam_id: UUID, generation: int
    ) -> SyncSnapshot:
        raise NotImplementedError

    async def seek(
        self, request_id: UUID, jam_id: UUID, generation: int, position_ms: int
    ) -> SyncSnapshot:
        raise NotImplementedError

    async def skip(
        self, request_id: UUID, jam_id: UUID, generation: int, selection: QueueItem
    ) -> SyncSnapshot:
        raise NotImplementedError

    async def decide(
        self,
        request_id: UUID,
        jam_id: UUID,
        generation: int,
        decision: ReadinessDecision,
    ) -> SyncSnapshot:
        raise NotImplementedError

    async def readiness(self, jam_id: UUID) -> ReadinessStatus:
        raise NotImplementedError

    async def update_participants(
        self,
        request_id: UUID,
        jam_id: UUID,
        generation: int,
        participant_ids: list[UUID],
    ) -> SyncSnapshot:
        raise NotImplementedError

    async def close(self) -> None:
        return None


class FakeSyncClient(SyncClient):
    def __init__(self) -> None:
        self._snapshots: dict[UUID, SyncSnapshot] = {}

    async def start(self, request_id, jam_id, owner_id, selection, participant_ids):
        snapshot = SyncSnapshot(1, JamState.PREPARING)
        self._snapshots[jam_id] = snapshot
        return snapshot

    async def command(self, command, request_id, jam_id, generation):
        self._check(jam_id, generation)
        state = JamState.PAUSED if command is Command.PAUSE else JamState.SCHEDULED
        snapshot = SyncSnapshot(generation, state)
        self._snapshots[jam_id] = snapshot
        return snapshot

    async def seek(self, request_id, jam_id, generation, position_ms):
        return self._check(jam_id, generation)

    async def skip(self, request_id, jam_id, generation, selection):
        self._check(jam_id, generation)
        snapshot = SyncSnapshot(generation + 1, JamState.PREPARING)
        self._snapshots[jam_id] = snapshot
        return snapshot

    async def decide(self, request_id, jam_id, generation, decision):
        self._check(jam_id, generation)
        states = {
            ReadinessDecision.CONTINUE: JamState.SCHEDULED,
            ReadinessDecision.WAIT: JamState.PREPARING,
            ReadinessDecision.CANCEL: JamState.ENDED,
        }
        snapshot = SyncSnapshot(generation, states[decision])
        self._snapshots[jam_id] = snapshot
        return snapshot

    async def readiness(self, jam_id):
        snapshot = self._snapshots.get(jam_id)
        if snapshot is None:
            raise SyncClientError("playback session not found")
        return ReadinessStatus(snapshot.generation, 0, False, False, [], [])

    async def update_participants(self, request_id, jam_id, generation, participant_ids):
        return self._check(jam_id, generation)

    def _check(self, jam_id: UUID, generation: int) -> SyncSnapshot:
        snapshot = self._snapshots.get(jam_id)
        if snapshot is None:
            raise SyncClientError("playback session not found")
        if snapshot.generation != generation:
            raise SyncConflictError("stale Sync generation")
        return snapshot


class GrpcSyncClient(SyncClient):
    def __init__(self, settings: Settings) -> None:
        self._channel = grpc.aio.insecure_channel(settings.sync_grpc_target)
        self._stub = sync_pb2_grpc.SyncControlServiceStub(self._channel)
        self._timeout = settings.sync_timeout_ms / 1000
        self._metadata = (("x-internal-token", settings.internal_service_token),)

    async def _call(self, method, request) -> SyncSnapshot:
        try:
            response = await method(request, timeout=self._timeout, metadata=self._metadata)
        except grpc.aio.AioRpcError as error:
            if error.code() in {grpc.StatusCode.ABORTED, grpc.StatusCode.FAILED_PRECONDITION}:
                raise SyncConflictError(error.details() or "Sync rejected the command") from error
            raise SyncClientError(error.details() or "Sync is unavailable") from error
        playback = response.playback
        return SyncSnapshot(playback.generation, _PROTO_STATES[playback.state])

    async def start(self, request_id, jam_id, owner_id, selection, participant_ids):
        request = sync_pb2.StartPlaybackRequest(
            request_id=str(request_id),
            jam_id=str(jam_id),
            owner_id=str(owner_id),
            selection=sync_pb2.PlaybackSelection(
                queue_item_id=str(selection.queue_item_id), song_id=str(selection.song_id)
            ),
            participant_ids=[str(value) for value in participant_ids],
        )
        return await self._call(self._stub.StartPlayback, request)

    async def command(self, command, request_id, jam_id, generation):
        values = dict(request_id=str(request_id), jam_id=str(jam_id), generation=generation)
        if command is Command.PAUSE:
            return await self._call(
                self._stub.PausePlayback, sync_pb2.PausePlaybackRequest(**values)
            )
        return await self._call(self._stub.ResumePlayback, sync_pb2.ResumePlaybackRequest(**values))

    async def seek(self, request_id, jam_id, generation, position_ms):
        return await self._call(
            self._stub.SeekPlayback,
            sync_pb2.SeekPlaybackRequest(
                request_id=str(request_id),
                jam_id=str(jam_id),
                generation=generation,
                position_ms=position_ms,
            ),
        )

    async def skip(self, request_id, jam_id, generation, selection):
        return await self._call(
            self._stub.SkipPlayback,
            sync_pb2.SkipPlaybackRequest(
                request_id=str(request_id),
                jam_id=str(jam_id),
                generation=generation,
                next_selection=sync_pb2.PlaybackSelection(
                    queue_item_id=str(selection.queue_item_id), song_id=str(selection.song_id)
                ),
            ),
        )

    async def decide(self, request_id, jam_id, generation, decision):
        decisions = {
            ReadinessDecision.CONTINUE: sync_pb2.READINESS_DECISION_CONTINUE,
            ReadinessDecision.WAIT: sync_pb2.READINESS_DECISION_WAIT,
            ReadinessDecision.CANCEL: sync_pb2.READINESS_DECISION_CANCEL,
        }
        return await self._call(
            self._stub.SubmitReadinessDecision,
            sync_pb2.SubmitReadinessDecisionRequest(
                request_id=str(request_id),
                jam_id=str(jam_id),
                generation=generation,
                decision=decisions[decision],
            ),
        )

    async def readiness(self, jam_id):
        try:
            response = await self._stub.GetReadinessStatus(
                sync_pb2.GetReadinessStatusRequest(jam_id=str(jam_id)),
                timeout=self._timeout,
                metadata=self._metadata,
            )
        except grpc.aio.AioRpcError as error:
            raise SyncClientError(error.details() or "Sync is unavailable") from error
        return ReadinessStatus(
            generation=response.generation,
            prepare_deadline_ms=response.prepare_deadline_ms,
            timed_out=response.timed_out,
            decision_required=response.decision_required,
            ready_participant_ids=[UUID(value) for value in response.ready_participant_ids],
            unready_participant_ids=[UUID(value) for value in response.unready_participant_ids],
        )

    async def update_participants(self, request_id, jam_id, generation, participant_ids):
        return await self._call(
            self._stub.UpdateParticipants,
            sync_pb2.UpdateParticipantsRequest(
                request_id=str(request_id),
                jam_id=str(jam_id),
                generation=generation,
                participant_ids=[str(value) for value in participant_ids],
            ),
        )

    async def close(self) -> None:
        await self._channel.close()


def create_sync_client(settings: Settings) -> SyncClient:
    return GrpcSyncClient(settings) if settings.sync_grpc_target else FakeSyncClient()
