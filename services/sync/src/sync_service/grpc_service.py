import time
from hmac import compare_digest
from uuid import UUID

import grpc
from pydantic import ValidationError

from sync_service.config import Settings
from sync_service.dependencies import (
    DependencyError,
    DependencyTimeoutError,
    PlaybackDependencies,
    SongNotFoundError,
    SongNotReadyError,
    StreamSource,
)
from sync_service.manager import SessionManager, SyncSession
from sync_service.models import PlaybackState, ReadinessDecision, StartSessionRequest
from sync_service.observability import bind_correlation_id, log_event, metrics
from syncwave.sync.v1 import sync_pb2, sync_pb2_grpc


def epoch_ms() -> int:
    return time.time_ns() // 1_000_000


def server_frame(
    session: SyncSession,
    message_type: str,
    payload: dict[str, object],
) -> dict[str, object]:
    return {
        "type": message_type,
        "jam_id": str(session.jam_id),
        "seq": session.next_server_seq(),
        "sent_at_ms": epoch_ms(),
        "payload": payload,
    }


def prepare_payload(session: SyncSession) -> dict[str, object]:
    return {
        "generation": session.generation,
        "queue_item_id": str(session.queue_item_id),
        "song_id": str(session.song_id),
        "stream_url": session.stream_url,
        "start_position_ms": 0,
    }


_PLAYBACK_STATES = {
    PlaybackState.PREPARING: sync_pb2.PLAYBACK_STATE_PREPARING,
    PlaybackState.SCHEDULED: sync_pb2.PLAYBACK_STATE_SCHEDULED,
    PlaybackState.PLAYING: sync_pb2.PLAYBACK_STATE_PLAYING,
    PlaybackState.PAUSED: sync_pb2.PLAYBACK_STATE_PAUSED,
    PlaybackState.ENDED: sync_pb2.PLAYBACK_STATE_ENDED,
}

_READINESS_DECISIONS = {
    sync_pb2.READINESS_DECISION_CONTINUE: ReadinessDecision.CONTINUE,
    sync_pb2.READINESS_DECISION_WAIT: ReadinessDecision.WAIT,
    sync_pb2.READINESS_DECISION_CANCEL: ReadinessDecision.CANCEL,
}


def playback_snapshot(session: SyncSession) -> sync_pb2.PlaybackSnapshot:
    return sync_pb2.PlaybackSnapshot(
        jam_id=str(session.jam_id),
        generation=session.generation,
        state=_PLAYBACK_STATES[session.state],
        song_id=str(session.song_id),
        anchor_server_time_ms=session.anchor_server_time_ms or 0,
        anchor_position_ms=session.anchor_position_ms,
        playback_rate=session.playback_rate,
        prepare_deadline_ms=session.prepare_deadline_ms,
    )


class SyncControlService(sync_pb2_grpc.SyncControlServiceServicer):
    def __init__(
        self,
        manager: SessionManager,
        settings: Settings,
        dependencies: PlaybackDependencies,
    ) -> None:
        self._manager = manager
        self._settings = settings
        self._dependencies = dependencies

    async def _authorize(self, context: grpc.aio.ServicerContext) -> None:
        metadata = {item.key.lower(): item.value for item in context.invocation_metadata()}
        request_correlation_id, _ = bind_correlation_id(metadata.get("x-correlation-id"))
        await context.send_initial_metadata((("x-correlation-id", request_correlation_id),))
        token = metadata.get("x-internal-token")
        if token is None or not compare_digest(token, self._settings.internal_service_token):
            log_event(
                "grpc_request",
                transport="grpc",
                outcome="unauthenticated",
            )
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "invalid service token")

    async def _session(
        self,
        jam_id: str,
        context: grpc.aio.ServicerContext,
    ) -> SyncSession:
        try:
            parsed_jam_id = UUID(jam_id)
        except ValueError as error:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "jam_id must be a UUID")
            raise AssertionError("context.abort must terminate the RPC") from error
        session = self._manager.get(parsed_jam_id)
        if session is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, "session not found")
            raise AssertionError("context.abort must terminate the RPC")
        return session

    @staticmethod
    async def _uuid(
        value: str,
        field: str,
        context: grpc.aio.ServicerContext,
    ) -> UUID:
        try:
            return UUID(value)
        except ValueError as error:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"{field} must be a UUID")
            raise AssertionError("context.abort must terminate the RPC") from error

    @staticmethod
    async def _abort_validation(
        context: grpc.aio.ServicerContext,
        error: ValueError | ValidationError,
    ) -> None:
        detail = str(error)
        code = (
            grpc.StatusCode.ABORTED
            if detail == "stale generation"
            else grpc.StatusCode.FAILED_PRECONDITION
        )
        await context.abort(code, detail)

    async def _resolve_dependencies(
        self,
        song_id: UUID,
        context: grpc.aio.ServicerContext,
    ) -> StreamSource:
        try:
            return await self._dependencies.resolve(song_id)
        except SongNotFoundError as error:
            await context.abort(grpc.StatusCode.NOT_FOUND, str(error))
        except SongNotReadyError as error:
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(error))
        except DependencyTimeoutError as error:
            await context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, str(error))
        except DependencyError as error:
            await context.abort(grpc.StatusCode.UNAVAILABLE, str(error))

    async def StartPlayback(
        self,
        request: sync_pb2.StartPlaybackRequest,
        context: grpc.aio.ServicerContext,
    ) -> sync_pb2.StartPlaybackResponse:
        await self._authorize(context)
        try:
            command = StartSessionRequest(
                request_id=UUID(request.request_id),
                jam_id=UUID(request.jam_id),
                queue_item_id=UUID(request.selection.queue_item_id),
                song_id=UUID(request.selection.song_id),
                owner_id=UUID(request.owner_id),
                participant_ids=[UUID(value) for value in request.participant_ids],
            )
        except (ValueError, ValidationError) as error:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(error))
            raise AssertionError("context.abort must terminate the RPC") from error
        stream = None
        if not self._manager.has_request(command.request_id):
            stream = await self._resolve_dependencies(command.song_id, context)
        session = await self._manager.start(
            command,
            prepare_deadline_ms=epoch_ms() + self._settings.prepare_timeout_ms,
            stream_url=None if stream is None else stream.stream_url,
        )
        log_event(
            "session_started",
            transport="grpc",
            jam_id=str(session.jam_id),
            generation=session.generation,
            request_id=str(command.request_id),
            message_type="StartPlayback",
            outcome="accepted",
        )
        return sync_pb2.StartPlaybackResponse(playback=playback_snapshot(session))

    async def PausePlayback(
        self,
        request: sync_pb2.PausePlaybackRequest,
        context: grpc.aio.ServicerContext,
    ) -> sync_pb2.PausePlaybackResponse:
        await self._authorize(context)
        session = await self._session(request.jam_id, context)
        request_id = await self._uuid(request.request_id, "request_id", context)
        try:
            session, applied = await self._manager.pause(
                session,
                request_id,
                request.generation,
                epoch_ms() + self._settings.correction_lead_time_ms,
            )
        except ValueError as error:
            await self._abort_validation(context, error)
            raise AssertionError("context.abort must terminate the RPC") from error
        if applied:
            await self._manager.broadcast(
                session,
                server_frame(
                    session,
                    "PAUSE_AT",
                    {
                        "generation": session.generation,
                        "target_server_time_ms": session.anchor_server_time_ms,
                        "position_ms": session.anchor_position_ms,
                    },
                ),
                ready_only=True,
            )
        return sync_pb2.PausePlaybackResponse(playback=playback_snapshot(session))

    async def ResumePlayback(
        self,
        request: sync_pb2.ResumePlaybackRequest,
        context: grpc.aio.ServicerContext,
    ) -> sync_pb2.ResumePlaybackResponse:
        await self._authorize(context)
        session = await self._session(request.jam_id, context)
        request_id = await self._uuid(request.request_id, "request_id", context)
        try:
            session, applied = await self._manager.resume(
                session,
                request_id,
                request.generation,
                epoch_ms() + self._settings.start_lead_time_ms,
            )
        except ValueError as error:
            await self._abort_validation(context, error)
            raise AssertionError("context.abort must terminate the RPC") from error
        if applied:
            await self._manager.broadcast(
                session,
                server_frame(
                    session,
                    "RESUME_AT",
                    {
                        "generation": session.generation,
                        "target_server_time_ms": session.anchor_server_time_ms,
                        "start_position_ms": session.anchor_position_ms,
                        "playback_rate": session.playback_rate,
                    },
                ),
                ready_only=True,
            )
        return sync_pb2.ResumePlaybackResponse(playback=playback_snapshot(session))

    async def SeekPlayback(
        self,
        request: sync_pb2.SeekPlaybackRequest,
        context: grpc.aio.ServicerContext,
    ) -> sync_pb2.SeekPlaybackResponse:
        await self._authorize(context)
        session = await self._session(request.jam_id, context)
        request_id = await self._uuid(request.request_id, "request_id", context)
        try:
            session, applied, previous_state = await self._manager.seek(
                session,
                request_id,
                request.generation,
                request.position_ms,
                epoch_ms() + self._settings.correction_lead_time_ms,
            )
        except ValueError as error:
            await self._abort_validation(context, error)
            raise AssertionError("context.abort must terminate the RPC") from error
        if applied:
            await self._manager.broadcast(
                session,
                server_frame(
                    session,
                    "SEEK_TO",
                    {
                        "generation": session.generation,
                        "target_server_time_ms": session.anchor_server_time_ms,
                        "position_ms": session.anchor_position_ms,
                        "resume_playback": previous_state is not PlaybackState.PAUSED,
                    },
                ),
                ready_only=True,
            )
        return sync_pb2.SeekPlaybackResponse(playback=playback_snapshot(session))

    async def SkipPlayback(
        self,
        request: sync_pb2.SkipPlaybackRequest,
        context: grpc.aio.ServicerContext,
    ) -> sync_pb2.SkipPlaybackResponse:
        await self._authorize(context)
        session = await self._session(request.jam_id, context)
        request_id = await self._uuid(request.request_id, "request_id", context)
        queue_item_id = await self._uuid(
            request.next_selection.queue_item_id,
            "next_selection.queue_item_id",
            context,
        )
        song_id = await self._uuid(
            request.next_selection.song_id,
            "next_selection.song_id",
            context,
        )
        stream = None
        if not self._manager.has_request(request_id):
            stream = await self._resolve_dependencies(song_id, context)
        try:
            session, applied = await self._manager.skip(
                session,
                request_id,
                request.generation,
                queue_item_id,
                song_id,
                epoch_ms() + self._settings.prepare_timeout_ms,
                stream_url=None if stream is None else stream.stream_url,
            )
        except ValueError as error:
            await self._abort_validation(context, error)
            raise AssertionError("context.abort must terminate the RPC") from error
        if applied:
            await self._manager.broadcast(
                session,
                server_frame(session, "PREPARE", prepare_payload(session)),
            )
        return sync_pb2.SkipPlaybackResponse(playback=playback_snapshot(session))

    async def SubmitReadinessDecision(
        self,
        request: sync_pb2.SubmitReadinessDecisionRequest,
        context: grpc.aio.ServicerContext,
    ) -> sync_pb2.SubmitReadinessDecisionResponse:
        await self._authorize(context)
        session = await self._session(request.jam_id, context)
        decision = _READINESS_DECISIONS.get(request.decision)
        if decision is None:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "decision must be specified")
            raise AssertionError("context.abort must terminate the RPC")
        now_ms = epoch_ms()
        _, _, required = self._manager.readiness_status(session, now_ms)
        request_id = await self._uuid(request.request_id, "request_id", context)
        try:
            if request.generation != session.generation:
                raise ValueError("stale generation")
            if not required and not self._manager.has_request(request_id):
                raise ValueError("readiness decision is not required")
            session, scheduled = await self._manager.apply_readiness_decision(
                session=session,
                request_id=request_id,
                decision=decision,
                now_ms=now_ms,
                prepare_timeout_ms=self._settings.prepare_timeout_ms,
                start_lead_time_ms=self._settings.start_lead_time_ms,
            )
        except ValueError as error:
            await self._abort_validation(context, error)
            raise AssertionError("context.abort must terminate the RPC") from error
        if scheduled:
            metrics.prepare_duration_ms.observe(
                max(
                    0,
                    now_ms
                    - (session.prepare_deadline_ms - self._settings.prepare_timeout_ms),
                )
            )
            await self._manager.broadcast(
                session,
                server_frame(
                    session,
                    "PLAY_AT",
                    {
                        "generation": session.generation,
                        "target_server_time_ms": session.anchor_server_time_ms,
                        "start_position_ms": session.anchor_position_ms,
                        "playback_rate": session.playback_rate,
                    },
                ),
                ready_only=True,
            )
        return sync_pb2.SubmitReadinessDecisionResponse(playback=playback_snapshot(session))

    async def GetReadinessStatus(
        self,
        request: sync_pb2.GetReadinessStatusRequest,
        context: grpc.aio.ServicerContext,
    ) -> sync_pb2.GetReadinessStatusResponse:
        await self._authorize(context)
        session = await self._session(request.jam_id, context)
        now_ms = epoch_ms()
        ready, unready, required = self._manager.readiness_status(session, now_ms)
        return sync_pb2.GetReadinessStatusResponse(
            jam_id=str(session.jam_id),
            generation=session.generation,
            prepare_deadline_ms=session.prepare_deadline_ms,
            timed_out=now_ms >= session.prepare_deadline_ms,
            decision_required=required,
            ready_participant_ids=[str(value) for value in ready],
            unready_participant_ids=[str(value) for value in unready],
        )

    async def GetPlaybackState(
        self,
        request: sync_pb2.GetPlaybackStateRequest,
        context: grpc.aio.ServicerContext,
    ) -> sync_pb2.GetPlaybackStateResponse:
        await self._authorize(context)
        session = await self._session(request.jam_id, context)
        return sync_pb2.GetPlaybackStateResponse(playback=playback_snapshot(session))


def create_grpc_server(
    manager: SessionManager,
    settings: Settings,
    dependencies: PlaybackDependencies,
    bind: str,
) -> tuple[grpc.aio.Server, int]:
    server = grpc.aio.server(
        options=(
            ("grpc.max_receive_message_length", 64 * 1024),
            ("grpc.max_send_message_length", 64 * 1024),
        )
    )
    sync_pb2_grpc.add_SyncControlServiceServicer_to_server(
        SyncControlService(manager, settings, dependencies),
        server,
    )
    port = server.add_insecure_port(bind)
    if port == 0:
        raise RuntimeError(f"could not bind gRPC server to {bind}")
    return server, port
