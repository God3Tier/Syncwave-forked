import asyncio
from dataclasses import dataclass, field
from uuid import UUID

from fastapi import WebSocket

from sync_service.models import PlaybackState, ReadinessDecision, StartSessionRequest
from sync_service.observability import log_event, metrics
from sync_service.repository import PersistedSession, SessionRepository
from sync_service.timing import CorrectionGate, expected_position_ms


@dataclass(slots=True)
class Participant:
    participant_id: UUID
    last_seq: int = -1
    ready: bool = False
    connection: WebSocket | None = None
    correction_gate: CorrectionGate = field(default_factory=CorrectionGate)


@dataclass(slots=True)
class SyncSession:
    jam_id: UUID
    queue_item_id: UUID
    song_id: UUID
    owner_id: UUID
    generation: int = 1
    state: PlaybackState = PlaybackState.PREPARING
    anchor_server_time_ms: int | None = None
    anchor_position_ms: int = 0
    playback_rate: float = 1.0
    prepare_deadline_ms: int = 0
    participants: dict[UUID, Participant] = field(default_factory=dict)
    server_seq: int = 0

    def next_server_seq(self) -> int:
        value = self.server_seq
        self.server_seq += 1
        return value


class SessionManager:
    def __init__(self, repository: SessionRepository) -> None:
        self._repository = repository
        self._sessions: dict[UUID, SyncSession] = {}
        self._request_results: dict[UUID, SyncSession] = {}
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        await self._repository.initialize()
        persisted_sessions, commands = await self._repository.load()
        self._sessions = {value.jam_id: self._from_persisted(value) for value in persisted_sessions}
        self._request_results = {
            request_id: self._sessions[jam_id]
            for request_id, jam_id in commands.items()
            if jam_id in self._sessions
        }

    async def close(self) -> None:
        await self._repository.close()

    async def shutdown_connections(self) -> None:
        connections = [
            participant.connection
            for session in self._sessions.values()
            for participant in session.participants.values()
            if participant.connection is not None
        ]
        for connection in connections:
            await connection.close(code=1012, reason="sync service restarting")

    async def ping(self) -> None:
        await self._repository.ping()

    async def start(self, request: StartSessionRequest, prepare_deadline_ms: int) -> SyncSession:
        async with self._lock:
            previous = self._request_results.get(request.request_id)
            if previous is not None:
                return previous

            current = self._sessions.get(request.jam_id)
            generation = 1 if current is None else current.generation + 1
            session = SyncSession(
                jam_id=request.jam_id,
                queue_item_id=request.queue_item_id,
                song_id=request.song_id,
                owner_id=request.owner_id,
                generation=generation,
                prepare_deadline_ms=prepare_deadline_ms,
                participants={
                    participant_id: Participant(participant_id)
                    for participant_id in set(request.participant_ids)
                },
            )
            self._sessions[request.jam_id] = session
            self._request_results[request.request_id] = session
            await self._repository.save_start(request.request_id, self._to_persisted(session))
            metrics.ready_participants.set(self.ready_participant_count())
            log_event(
                "generation_started",
                jam_id=str(session.jam_id),
                generation=session.generation,
                request_id=str(request.request_id),
                message_type="START_PLAYBACK",
                outcome="preparing",
            )
            return session

    def get(self, jam_id: UUID) -> SyncSession | None:
        return self._sessions.get(jam_id)

    def has_request(self, request_id: UUID) -> bool:
        return request_id in self._request_results

    @staticmethod
    def readiness_status(
        session: SyncSession,
        now_ms: int,
    ) -> tuple[list[UUID], list[UUID], bool]:
        ready = [
            participant_id
            for participant_id, participant in session.participants.items()
            if participant.ready
        ]
        unready = [
            participant_id
            for participant_id, participant in session.participants.items()
            if not participant.ready
        ]
        decision_required = (
            session.state is PlaybackState.PREPARING
            and now_ms >= session.prepare_deadline_ms
            and bool(unready)
        )
        return ready, unready, decision_required

    async def apply_readiness_decision(
        self,
        *,
        session: SyncSession,
        request_id: UUID,
        decision: ReadinessDecision,
        now_ms: int,
        prepare_timeout_ms: int,
        start_lead_time_ms: int,
    ) -> tuple[SyncSession, bool]:
        async with self._lock:
            previous = self._request_results.get(request_id)
            if previous is not None:
                return previous, False

            if decision is ReadinessDecision.CONTINUE:
                if not any(participant.ready for participant in session.participants.values()):
                    raise ValueError("at least one participant must be ready")
                session.state = PlaybackState.SCHEDULED
                session.anchor_server_time_ms = now_ms + start_lead_time_ms
                session.anchor_position_ms = 0
                scheduled = True
            elif decision is ReadinessDecision.WAIT:
                session.prepare_deadline_ms = now_ms + prepare_timeout_ms
                scheduled = False
            else:
                session.state = PlaybackState.ENDED
                scheduled = False

            self._request_results[request_id] = session
            await self._repository.save_start(request_id, self._to_persisted(session))
            log_event(
                "readiness_decision_applied",
                jam_id=str(session.jam_id),
                generation=session.generation,
                request_id=str(request_id),
                message_type=decision.value,
                outcome=session.state.value,
            )
            return session, scheduled

    async def mark_ready(
        self,
        session: SyncSession,
        participant_id: UUID,
        target_server_time_ms: int,
    ) -> bool:
        """Mark one participant ready and atomically schedule when all are ready."""
        async with self._lock:
            active_session = self._sessions.get(session.jam_id)
            if active_session is not session or session.state is not PlaybackState.PREPARING:
                return False

            session.participants[participant_id].ready = True
            metrics.ready_participants.set(self.ready_participant_count())
            if not all(participant.ready for participant in session.participants.values()):
                return False

            session.state = PlaybackState.SCHEDULED
            session.anchor_server_time_ms = target_server_time_ms
            session.anchor_position_ms = 0
            await self._repository.save_session(self._to_persisted(session))
            return True

    async def mark_playing_if_due(
        self,
        session: SyncSession,
        measured_server_time_ms: int,
    ) -> None:
        async with self._lock:
            if (
                self._sessions.get(session.jam_id) is session
                and session.state is PlaybackState.SCHEDULED
                and session.anchor_server_time_ms is not None
                and measured_server_time_ms >= session.anchor_server_time_ms
            ):
                session.state = PlaybackState.PLAYING
                await self._repository.save_session(self._to_persisted(session))

    async def pause(
        self,
        session: SyncSession,
        request_id: UUID,
        generation: int,
        apply_at_ms: int,
    ) -> tuple[SyncSession, bool]:
        async with self._lock:
            previous = self._request_results.get(request_id)
            if previous is not None:
                self._validate_request_jam(previous, session)
                return previous, False
            self._validate_control(
                session,
                generation,
                {PlaybackState.SCHEDULED, PlaybackState.PLAYING},
            )
            if session.anchor_server_time_ms is None:
                raise ValueError("playback timeline is unavailable")
            session.anchor_position_ms = expected_position_ms(
                anchor_server_time_ms=session.anchor_server_time_ms,
                anchor_position_ms=session.anchor_position_ms,
                playback_rate=session.playback_rate,
                measured_server_time_ms=apply_at_ms,
            )
            session.anchor_server_time_ms = apply_at_ms
            session.playback_rate = 1.0
            session.state = PlaybackState.PAUSED
            await self._save_command(request_id, session)
            self._log_control(session, request_id, "PAUSE", "applied")
            return session, True

    async def resume(
        self,
        session: SyncSession,
        request_id: UUID,
        generation: int,
        apply_at_ms: int,
    ) -> tuple[SyncSession, bool]:
        async with self._lock:
            previous = self._request_results.get(request_id)
            if previous is not None:
                self._validate_request_jam(previous, session)
                return previous, False
            self._validate_control(session, generation, {PlaybackState.PAUSED})
            session.anchor_server_time_ms = apply_at_ms
            session.playback_rate = 1.0
            session.state = PlaybackState.SCHEDULED
            await self._save_command(request_id, session)
            self._log_control(session, request_id, "RESUME", "applied")
            return session, True

    async def seek(
        self,
        session: SyncSession,
        request_id: UUID,
        generation: int,
        position_ms: int,
        apply_at_ms: int,
    ) -> tuple[SyncSession, bool, PlaybackState]:
        async with self._lock:
            previous = self._request_results.get(request_id)
            if previous is not None:
                self._validate_request_jam(previous, session)
                return previous, False, previous.state
            self._validate_control(
                session,
                generation,
                {PlaybackState.SCHEDULED, PlaybackState.PLAYING, PlaybackState.PAUSED},
            )
            resulting_state = session.state
            session.anchor_server_time_ms = apply_at_ms
            session.anchor_position_ms = position_ms
            session.playback_rate = 1.0
            if resulting_state is not PlaybackState.PAUSED:
                session.state = PlaybackState.SCHEDULED
            await self._save_command(request_id, session)
            self._log_control(session, request_id, "SEEK", "applied")
            return session, True, resulting_state

    async def skip(
        self,
        session: SyncSession,
        request_id: UUID,
        generation: int,
        queue_item_id: UUID,
        song_id: UUID,
        prepare_deadline_ms: int,
    ) -> tuple[SyncSession, bool]:
        async with self._lock:
            previous = self._request_results.get(request_id)
            if previous is not None:
                self._validate_request_jam(previous, session)
                return previous, False
            self._validate_control(
                session,
                generation,
                {
                    PlaybackState.SCHEDULED,
                    PlaybackState.PLAYING,
                    PlaybackState.PAUSED,
                    PlaybackState.ENDED,
                },
            )
            session.generation += 1
            session.queue_item_id = queue_item_id
            session.song_id = song_id
            session.state = PlaybackState.PREPARING
            session.anchor_server_time_ms = None
            session.anchor_position_ms = 0
            session.playback_rate = 1.0
            session.prepare_deadline_ms = prepare_deadline_ms
            for participant in session.participants.values():
                participant.ready = False
                participant.correction_gate.reset()
            metrics.ready_participants.set(self.ready_participant_count())
            await self._save_command(request_id, session)
            self._log_control(session, request_id, "SKIP", "preparing")
            return session, True

    @staticmethod
    def _log_control(
        session: SyncSession,
        request_id: UUID,
        message_type: str,
        outcome: str,
    ) -> None:
        log_event(
            "playback_control_applied",
            jam_id=str(session.jam_id),
            generation=session.generation,
            request_id=str(request_id),
            message_type=message_type,
            outcome=outcome,
        )

    def _validate_control(
        self,
        session: SyncSession,
        generation: int,
        allowed_states: set[PlaybackState],
    ) -> None:
        if self._sessions.get(session.jam_id) is not session:
            raise ValueError("session is no longer active")
        if generation != session.generation:
            raise ValueError("stale generation")
        if session.state not in allowed_states:
            raise ValueError(f"command is invalid while playback is {session.state.value}")

    def ready_participant_count(self) -> int:
        return sum(
            participant.ready
            for active_session in self._sessions.values()
            for participant in active_session.participants.values()
        )

    @staticmethod
    def _validate_request_jam(previous: SyncSession, session: SyncSession) -> None:
        if previous.jam_id != session.jam_id:
            raise ValueError("request_id belongs to another Jam")

    async def _save_command(self, request_id: UUID, session: SyncSession) -> None:
        self._request_results[request_id] = session
        await self._repository.save_start(request_id, self._to_persisted(session))

    async def disconnect(self, jam_id: UUID, participant_id: UUID, websocket: WebSocket) -> None:
        async with self._lock:
            session = self._sessions.get(jam_id)
            if session is None:
                return
            participant = session.participants.get(participant_id)
            if participant is not None and participant.connection is websocket:
                participant.connection = None

    async def broadcast(
        self,
        session: SyncSession,
        message: dict[str, object],
        *,
        ready_only: bool = False,
    ) -> None:
        dead: list[Participant] = []
        for participant in session.participants.values():
            if participant.connection is None:
                continue
            if ready_only and not participant.ready:
                continue
            try:
                await participant.connection.send_json(message)
            except RuntimeError:
                dead.append(participant)
        for participant in dead:
            participant.connection = None

    @staticmethod
    def _to_persisted(session: SyncSession) -> PersistedSession:
        return PersistedSession(
            jam_id=session.jam_id,
            generation=session.generation,
            state=session.state.value,
            queue_item_id=session.queue_item_id,
            song_id=session.song_id,
            owner_id=session.owner_id,
            participant_ids=tuple(session.participants),
            anchor_server_time_ms=session.anchor_server_time_ms,
            anchor_position_ms=session.anchor_position_ms,
            playback_rate=session.playback_rate,
            prepare_deadline_ms=session.prepare_deadline_ms,
        )

    @staticmethod
    def _from_persisted(value: PersistedSession) -> SyncSession:
        return SyncSession(
            jam_id=value.jam_id,
            queue_item_id=value.queue_item_id,
            song_id=value.song_id,
            owner_id=value.owner_id,
            generation=value.generation,
            state=PlaybackState(value.state),
            anchor_server_time_ms=value.anchor_server_time_ms,
            anchor_position_ms=value.anchor_position_ms,
            playback_rate=value.playback_rate,
            prepare_deadline_ms=value.prepare_deadline_ms,
            participants={
                participant_id: Participant(participant_id)
                for participant_id in value.participant_ids
            },
        )
