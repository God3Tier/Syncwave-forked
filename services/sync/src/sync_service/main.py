import asyncio
import json
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from hmac import compare_digest
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import (
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from sync_service.config import Settings, get_settings
from sync_service.demo import DEMO_HTML, test_tone_wav
from sync_service.dependencies import (
    DependencyError,
    DependencyTimeoutError,
    SongNotFoundError,
    SongNotReadyError,
    StreamSource,
    create_default_dependencies,
)
from sync_service.manager import SessionManager
from sync_service.models import (
    PlaybackCommandRequest,
    PlaybackSnapshotResponse,
    PlaybackState,
    PlaybackStatusFrame,
    ReadinessDecisionRequest,
    ReadinessDecisionResponse,
    ReadinessStatusResponse,
    ReadyFrame,
    SeekPlaybackRequest,
    SkipPlaybackRequest,
    StartSessionRequest,
    StartSessionResponse,
    TimePingFrame,
)
from sync_service.observability import (
    OperationTimer,
    bind_correlation_id,
    configure_logging,
    log_event,
    metrics,
    reset_correlation_id,
)
from sync_service.repository import SessionRepository
from sync_service.timing import choose_correction, expected_position_ms

settings = get_settings()
configure_logging(settings.log_level)
repository = SessionRepository(settings.database_url)
manager = SessionManager(repository)
dependencies = create_default_dependencies(settings)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await manager.initialize()
    grpc_server = None
    if settings.grpc_port > 0:
        from sync_service.grpc_service import create_grpc_server

        grpc_server, _ = create_grpc_server(
            manager,
            settings,
            dependencies,
            f"[::]:{settings.grpc_port}",
        )
        await grpc_server.start()
    try:
        yield
    finally:
        await manager.shutdown_connections()
        await dependencies.close()
        if grpc_server is not None:
            await grpc_server.stop(grace=2)
        await manager.close()


app = FastAPI(title="SyncWave Sync Service", version="0.2.0", lifespan=lifespan)


@app.middleware("http")
async def observe_http(request: Request, call_next: Any) -> Response:
    request_correlation_id, context_token = bind_correlation_id(
        request.headers.get("x-correlation-id")
    )
    timer = OperationTimer()
    outcome = "success"
    try:
        response = await call_next(request)
        if response.status_code >= 400:
            outcome = "rejected" if response.status_code < 500 else "failure"
        response.headers["X-Correlation-ID"] = request_correlation_id
        return response
    except Exception:
        outcome = "failure"
        raise
    finally:
        log_event(
            "http_request",
            transport="http",
            message_type=f"{request.method} {request.url.path}",
            outcome=outcome,
            duration_ms=timer.elapsed_ms(),
        )
        reset_correlation_id(context_token)


def epoch_ms() -> int:
    return time.time_ns() // 1_000_000


def server_frame(
    *, session: Any, message_type: str, payload: dict[str, object]
) -> dict[str, object]:
    return {
        "type": message_type,
        "jam_id": str(session.jam_id),
        "seq": session.next_server_seq(),
        "sent_at_ms": epoch_ms(),
        "payload": payload,
    }


def prepare_payload(session: Any) -> dict[str, object]:
    return {
        "generation": session.generation,
        "queue_item_id": str(session.queue_item_id),
        "song_id": str(session.song_id),
        "stream_url": session.stream_url,
        "start_position_ms": 0,
    }


def play_at_payload(
    session: Any,
    *,
    target_server_time_ms: int,
    start_position_ms: int,
) -> dict[str, object]:
    return {
        "generation": session.generation,
        "target_server_time_ms": target_server_time_ms,
        "start_position_ms": start_position_ms,
        "playback_rate": session.playback_rate,
    }


def playback_snapshot(session: Any) -> PlaybackSnapshotResponse:
    return PlaybackSnapshotResponse(
        jam_id=session.jam_id,
        generation=session.generation,
        state=session.state,
        song_id=session.song_id,
        anchor_server_time_ms=session.anchor_server_time_ms,
        anchor_position_ms=session.anchor_position_ms,
        playback_rate=session.playback_rate,
    )


def require_internal_session(
    jam_id: UUID,
    x_internal_token: str | None,
) -> Any:
    settings = get_settings()
    if x_internal_token is None or not compare_digest(
        x_internal_token, settings.internal_service_token
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid service token",
        )
    session = manager.get(jam_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return session


async def resolve_playback_dependencies(song_id: UUID) -> StreamSource:
    try:
        return await dependencies.resolve(song_id)
    except SongNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except SongNotReadyError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except DependencyTimeoutError as error:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(error),
        ) from error
    except DependencyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict[str, str]:
    try:
        await manager.ping()
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from error
    return {"status": "ready"}


@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> Response:
    return Response(content=metrics.render(), media_type="text/plain; version=0.0.4")


@app.get("/demo", response_class=HTMLResponse, include_in_schema=False)
async def demo() -> str:
    return DEMO_HTML


@app.get("/demo/test-tone.wav", include_in_schema=False)
async def demo_test_tone() -> Response:
    return Response(content=test_tone_wav(), media_type="audio/wav")


@app.post(
    "/internal/v1/sessions",
    response_model=StartSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_session(
    request: StartSessionRequest,
    x_internal_token: Annotated[str | None, Header()] = None,
) -> StartSessionResponse:
    settings: Settings = get_settings()
    if x_internal_token is None or not compare_digest(
        x_internal_token, settings.internal_service_token
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid service token",
        )

    stream = None
    if not manager.has_request(request.request_id):
        stream = await resolve_playback_dependencies(request.song_id)
    session = await manager.start(
        request,
        prepare_deadline_ms=epoch_ms() + settings.prepare_timeout_ms,
        stream_url=None if stream is None else stream.stream_url,
    )
    log_event(
        "session_started",
        transport="http",
        jam_id=str(session.jam_id),
        generation=session.generation,
        request_id=str(request.request_id),
        message_type="START_PLAYBACK",
        outcome="accepted",
    )
    return StartSessionResponse(
        jam_id=session.jam_id,
        generation=session.generation,
        state=session.state,
        websocket_path=f"/ws?jam_id={session.jam_id}",
        mock_participant_token=settings.mock_sync_token,
    )


@app.get("/internal/v1/sessions/{jam_id}", response_model=PlaybackSnapshotResponse)
async def get_session(
    jam_id: UUID,
    x_internal_token: Annotated[str | None, Header()] = None,
) -> PlaybackSnapshotResponse:
    settings = get_settings()
    if x_internal_token is None or not compare_digest(
        x_internal_token, settings.internal_service_token
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid service token",
        )

    session = manager.get(jam_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return playback_snapshot(session)


@app.get(
    "/internal/v1/sessions/{jam_id}/readiness",
    response_model=ReadinessStatusResponse,
)
async def get_readiness(
    jam_id: UUID,
    x_internal_token: Annotated[str | None, Header()] = None,
) -> ReadinessStatusResponse:
    settings = get_settings()
    if x_internal_token is None or not compare_digest(
        x_internal_token, settings.internal_service_token
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid service token",
        )

    session = manager.get(jam_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    now_ms = epoch_ms()
    ready_ids, unready_ids, decision_required = manager.readiness_status(session, now_ms)
    return ReadinessStatusResponse(
        jam_id=jam_id,
        generation=session.generation,
        prepare_deadline_ms=session.prepare_deadline_ms,
        timed_out=now_ms >= session.prepare_deadline_ms,
        decision_required=decision_required,
        ready_participant_ids=ready_ids,
        unready_participant_ids=unready_ids,
    )


@app.post(
    "/internal/v1/sessions/{jam_id}/readiness-decision",
    response_model=ReadinessDecisionResponse,
)
async def submit_readiness_decision(
    jam_id: UUID,
    request: ReadinessDecisionRequest,
    x_internal_token: Annotated[str | None, Header()] = None,
) -> ReadinessDecisionResponse:
    settings = get_settings()
    if x_internal_token is None or not compare_digest(
        x_internal_token, settings.internal_service_token
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid service token",
        )

    session = manager.get(jam_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    if request.generation != session.generation:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="stale generation")

    now_ms = epoch_ms()
    _, _, decision_required = manager.readiness_status(session, now_ms)
    if not decision_required and not manager.has_request(request.request_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="readiness decision is not required",
        )
    try:
        session, scheduled = await manager.apply_readiness_decision(
            session=session,
            request_id=request.request_id,
            decision=request.decision,
            now_ms=now_ms,
            prepare_timeout_ms=settings.prepare_timeout_ms,
            start_lead_time_ms=settings.start_lead_time_ms,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    if scheduled:
        metrics.prepare_duration_ms.observe(
            max(0, now_ms - (session.prepare_deadline_ms - settings.prepare_timeout_ms))
        )
        await manager.broadcast(
            session,
            server_frame(
                session=session,
                message_type="PLAY_AT",
                payload=play_at_payload(
                    session,
                    target_server_time_ms=session.anchor_server_time_ms,
                    start_position_ms=session.anchor_position_ms,
                ),
            ),
            ready_only=True,
        )
    return ReadinessDecisionResponse(
        jam_id=jam_id,
        generation=session.generation,
        state=session.state,
        decision=request.decision,
        target_server_time_ms=session.anchor_server_time_ms,
    )


@app.post(
    "/internal/v1/sessions/{jam_id}/pause",
    response_model=PlaybackSnapshotResponse,
)
async def pause_playback(
    jam_id: UUID,
    request: PlaybackCommandRequest,
    x_internal_token: Annotated[str | None, Header()] = None,
) -> PlaybackSnapshotResponse:
    settings = get_settings()
    session = require_internal_session(jam_id, x_internal_token)
    try:
        session, applied = await manager.pause(
            session,
            request.request_id,
            request.generation,
            epoch_ms() + settings.correction_lead_time_ms,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    if applied:
        await manager.broadcast(
            session,
            server_frame(
                session=session,
                message_type="PAUSE_AT",
                payload={
                    "generation": session.generation,
                    "target_server_time_ms": session.anchor_server_time_ms,
                    "position_ms": session.anchor_position_ms,
                },
            ),
            ready_only=True,
        )
    return playback_snapshot(session)


@app.post(
    "/internal/v1/sessions/{jam_id}/resume",
    response_model=PlaybackSnapshotResponse,
)
async def resume_playback(
    jam_id: UUID,
    request: PlaybackCommandRequest,
    x_internal_token: Annotated[str | None, Header()] = None,
) -> PlaybackSnapshotResponse:
    settings = get_settings()
    session = require_internal_session(jam_id, x_internal_token)
    try:
        session, applied = await manager.resume(
            session,
            request.request_id,
            request.generation,
            epoch_ms() + settings.start_lead_time_ms,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    if applied:
        await manager.broadcast(
            session,
            server_frame(
                session=session,
                message_type="RESUME_AT",
                payload=play_at_payload(
                    session,
                    target_server_time_ms=session.anchor_server_time_ms,
                    start_position_ms=session.anchor_position_ms,
                ),
            ),
            ready_only=True,
        )
    return playback_snapshot(session)


@app.post(
    "/internal/v1/sessions/{jam_id}/seek",
    response_model=PlaybackSnapshotResponse,
)
async def seek_playback(
    jam_id: UUID,
    request: SeekPlaybackRequest,
    x_internal_token: Annotated[str | None, Header()] = None,
) -> PlaybackSnapshotResponse:
    settings = get_settings()
    session = require_internal_session(jam_id, x_internal_token)
    try:
        session, applied, previous_state = await manager.seek(
            session,
            request.request_id,
            request.generation,
            request.position_ms,
            epoch_ms() + settings.correction_lead_time_ms,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    if applied:
        await manager.broadcast(
            session,
            server_frame(
                session=session,
                message_type="SEEK_TO",
                payload={
                    "generation": session.generation,
                    "target_server_time_ms": session.anchor_server_time_ms,
                    "position_ms": session.anchor_position_ms,
                    "resume_playback": previous_state is not PlaybackState.PAUSED,
                },
            ),
            ready_only=True,
        )
    return playback_snapshot(session)


@app.post(
    "/internal/v1/sessions/{jam_id}/skip",
    response_model=PlaybackSnapshotResponse,
)
async def skip_playback(
    jam_id: UUID,
    request: SkipPlaybackRequest,
    x_internal_token: Annotated[str | None, Header()] = None,
) -> PlaybackSnapshotResponse:
    settings = get_settings()
    session = require_internal_session(jam_id, x_internal_token)
    stream = None
    if not manager.has_request(request.request_id):
        stream = await resolve_playback_dependencies(request.song_id)
    try:
        session, applied = await manager.skip(
            session,
            request.request_id,
            request.generation,
            request.queue_item_id,
            request.song_id,
            epoch_ms() + settings.prepare_timeout_ms,
            stream_url=None if stream is None else stream.stream_url,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    if applied:
        await manager.broadcast(
            session,
            server_frame(
                session=session,
                message_type="PREPARE",
                payload=prepare_payload(session),
            ),
        )
    return playback_snapshot(session)


async def send_error(websocket: WebSocket, session: Any, code: str, message: str) -> None:
    metrics.protocol_errors_total.labels(code=code).inc()
    log_event(
        "protocol_error",
        transport="websocket",
        jam_id=str(session.jam_id),
        generation=session.generation,
        message_type="ERROR",
        error_code=code,
        outcome="rejected",
    )
    await websocket.send_json(
        server_frame(
            session=session,
            message_type="ERROR",
            payload={"code": code, "message": message},
        )
    )


@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    jam_id: UUID,
    participant_id: UUID,
    token: str,
    correlation_id: str | None = None,
) -> None:
    settings = get_settings()
    _, context_token = bind_correlation_id(
        websocket.headers.get("x-correlation-id") or correlation_id
    )
    connection_id = uuid4().hex
    session = manager.get(jam_id)
    participant = None if session is None else session.participants.get(participant_id)

    if (
        session is None
        or participant is None
        or not compare_digest(token, settings.mock_sync_token)
    ):
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="unauthorized participant",
        )
        log_event(
            "websocket_rejected",
            transport="websocket",
            jam_id=str(jam_id),
            participant_id=str(participant_id),
            connection_id=connection_id,
            outcome="unauthorized",
        )
        reset_correlation_id(context_token)
        return

    await websocket.accept()
    if participant.connection is not None:
        await participant.connection.close(code=4001, reason="new connection replaced this client")
    participant.connection = websocket
    participant.last_seq = -1
    participant.correction_gate.reset()
    metrics.websocket_connections.inc()
    log_event(
        "participant_joined",
        transport="websocket",
        jam_id=str(jam_id),
        participant_id=str(participant_id),
        connection_id=connection_id,
        generation=session.generation,
        message_type="JOINED",
        outcome="accepted",
    )
    await websocket.send_json(
        server_frame(
            session=session,
            message_type="JOINED",
            payload={
                "participant_id": str(participant_id),
                "generation": session.generation,
                "state": session.state,
                "song_id": str(session.song_id),
            },
        )
    )
    now_ms = epoch_ms()
    await manager.mark_playing_if_due(session, now_ms)
    if session.state is PlaybackState.PREPARING:
        await websocket.send_json(
            server_frame(
                session=session,
                message_type="PREPARE",
                payload=prepare_payload(session),
            )
        )
    elif session.state is PlaybackState.SCHEDULED and session.anchor_server_time_ms is not None:
        await websocket.send_json(
            server_frame(
                session=session,
                message_type="PLAY_AT",
                payload=play_at_payload(
                    session,
                    target_server_time_ms=session.anchor_server_time_ms,
                    start_position_ms=session.anchor_position_ms,
                ),
            )
        )
    elif session.state is PlaybackState.PLAYING and session.anchor_server_time_ms is not None:
        catch_up_at_ms = now_ms + settings.start_lead_time_ms
        catch_up_position_ms = expected_position_ms(
            anchor_server_time_ms=session.anchor_server_time_ms,
            anchor_position_ms=session.anchor_position_ms,
            playback_rate=session.playback_rate,
            measured_server_time_ms=catch_up_at_ms,
        )
        await websocket.send_json(
            server_frame(
                session=session,
                message_type="PLAY_AT",
                payload=play_at_payload(
                    session,
                    target_server_time_ms=catch_up_at_ms,
                    start_position_ms=catch_up_position_ms,
                ),
            )
        )

    try:
        message_times: deque[int] = deque()
        while True:
            try:
                raw_message = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=settings.websocket_idle_timeout_ms / 1_000,
                )
            except TimeoutError:
                await websocket.close(code=1001, reason="heartbeat timeout")
                break
            received_at_ms = epoch_ms()
            if len(raw_message.encode("utf-8")) > settings.websocket_max_message_bytes:
                metrics.protocol_errors_total.labels(code="MESSAGE_TOO_LARGE").inc()
                await websocket.close(code=1009, reason="message too large")
                break
            window_start_ms = received_at_ms - settings.websocket_rate_limit_window_ms
            while message_times and message_times[0] <= window_start_ms:
                message_times.popleft()
            if len(message_times) >= settings.websocket_rate_limit_messages:
                metrics.protocol_errors_total.labels(code="RATE_LIMITED").inc()
                await websocket.close(code=1013, reason="message rate exceeded")
                break
            message_times.append(received_at_ms)
            try:
                data = json.loads(raw_message)
            except json.JSONDecodeError:
                await send_error(
                    websocket, session, "INVALID_MESSAGE", "message must be valid JSON"
                )
                continue
            if not isinstance(data, dict):
                await send_error(websocket, session, "INVALID_MESSAGE", "message must be an object")
                continue

            if data.get("jam_id") != str(jam_id):
                await send_error(websocket, session, "UNKNOWN_JAM", "message jam_id does not match")
                continue

            seq = data.get("seq")
            if not isinstance(seq, int) or isinstance(seq, bool) or seq <= participant.last_seq:
                await send_error(websocket, session, "STALE_SEQUENCE", "seq must increase")
                continue
            participant.last_seq = seq

            try:
                if data.get("type") == "TIME_PING":
                    frame = TimePingFrame.model_validate(data)
                    await websocket.send_json(
                        server_frame(
                            session=session,
                            message_type="TIME_PONG",
                            payload={
                                "sample_id": str(frame.payload.sample_id),
                                "client_sent_ms": frame.payload.client_sent_ms,
                                "server_received_ms": received_at_ms,
                                "server_sent_ms": epoch_ms(),
                            },
                        )
                    )
                elif data.get("type") == "READY":
                    frame = ReadyFrame.model_validate(data)
                    if frame.payload.generation != session.generation:
                        await send_error(
                            websocket,
                            session,
                            "STALE_GENERATION",
                            "READY generation is not active",
                        )
                        continue
                    scheduled = await manager.mark_ready(
                        session,
                        participant_id,
                        epoch_ms() + settings.start_lead_time_ms,
                    )
                    log_event(
                        "participant_ready",
                        transport="websocket",
                        jam_id=str(jam_id),
                        participant_id=str(participant_id),
                        connection_id=connection_id,
                        generation=session.generation,
                        message_type="READY",
                        outcome="scheduled" if scheduled else "waiting",
                    )
                    await manager.broadcast(
                        session,
                        server_frame(
                            session=session,
                            message_type="PARTICIPANT_STATE",
                            payload={
                                "participant_id": str(participant_id),
                                "generation": session.generation,
                                "connected": True,
                                "ready": True,
                            },
                        ),
                    )
                    if scheduled:
                        metrics.prepare_duration_ms.observe(
                            max(
                                0,
                                received_at_ms
                                - (session.prepare_deadline_ms - settings.prepare_timeout_ms),
                            )
                        )
                        await manager.broadcast(
                            session,
                            server_frame(
                                session=session,
                                message_type="PLAY_AT",
                            payload=play_at_payload(
                                session,
                                target_server_time_ms=session.anchor_server_time_ms,
                                start_position_ms=session.anchor_position_ms,
                            ),
                            ),
                        )
                elif data.get("type") == "PLAYBACK_STATUS":
                    frame = PlaybackStatusFrame.model_validate(data)
                    if frame.payload.generation != session.generation:
                        await send_error(
                            websocket,
                            session,
                            "STALE_GENERATION",
                            "PLAYBACK_STATUS generation is not active",
                        )
                        continue
                    if session.anchor_server_time_ms is None:
                        await send_error(
                            websocket,
                            session,
                            "INVALID_STATE",
                            "playback has not been scheduled",
                        )
                        continue
                    await manager.mark_playing_if_due(
                        session,
                        frame.payload.measured_server_time_ms,
                    )
                    if frame.payload.clock_offset_ms is not None:
                        metrics.clock_offset_ms.observe(frame.payload.clock_offset_ms)
                    if frame.payload.round_trip_delay_ms is not None:
                        metrics.round_trip_delay_ms.observe(frame.payload.round_trip_delay_ms)
                    if frame.payload.start_error_ms is not None:
                        metrics.start_error_ms.observe(abs(frame.payload.start_error_ms))
                    if frame.payload.buffering:
                        continue

                    expected_at_measurement = expected_position_ms(
                        anchor_server_time_ms=session.anchor_server_time_ms,
                        anchor_position_ms=session.anchor_position_ms,
                        playback_rate=session.playback_rate,
                        measured_server_time_ms=frame.payload.measured_server_time_ms,
                    )
                    drift_ms = frame.payload.position_ms - expected_at_measurement
                    metrics.drift_ms.observe(abs(drift_ms))
                    apply_at_ms = epoch_ms() + settings.correction_lead_time_ms
                    expected_at_apply = expected_position_ms(
                        anchor_server_time_ms=session.anchor_server_time_ms,
                        anchor_position_ms=session.anchor_position_ms,
                        playback_rate=session.playback_rate,
                        measured_server_time_ms=apply_at_ms,
                    )
                    correction = choose_correction(
                        drift_ms=drift_ms,
                        expected_position_at_apply_ms=expected_at_apply,
                        apply_at_server_time_ms=apply_at_ms,
                        ignore_threshold_ms=settings.drift_ignore_threshold_ms,
                        seek_threshold_ms=settings.drift_seek_threshold_ms,
                        rate_correction_percent=settings.rate_correction_percent,
                    )
                    if participant.correction_gate.should_issue(
                        correction,
                        drift_ms=drift_ms,
                        now_ms=received_at_ms,
                        ignore_threshold_ms=settings.drift_ignore_threshold_ms,
                        hysteresis_ms=settings.correction_hysteresis_ms,
                        cooldown_ms=settings.correction_cooldown_ms,
                    ):
                        assert correction is not None
                        metrics.corrections_total.labels(
                            method=correction.method,
                            reason="drift",
                        ).inc()
                        log_event(
                            "correction_issued",
                            transport="websocket",
                            jam_id=str(jam_id),
                            participant_id=str(participant_id),
                            connection_id=connection_id,
                            generation=session.generation,
                            message_type="SYNC_CORRECTION",
                            outcome=correction.method,
                            drift_ms=correction.drift_ms,
                            method=correction.method,
                        )
                        await websocket.send_json(
                            server_frame(
                                session=session,
                                message_type="SYNC_CORRECTION",
                                payload={
                                    "generation": session.generation,
                                    "method": correction.method,
                                    "drift_ms": correction.drift_ms,
                                    "target_position_ms": correction.target_position_ms,
                                    "playback_rate": correction.playback_rate,
                                    "apply_at_server_time_ms": correction.apply_at_server_time_ms,
                                    "duration_ms": correction.duration_ms,
                                },
                            )
                        )
                else:
                    await send_error(
                        websocket,
                        session,
                        "INVALID_MESSAGE",
                        "unsupported message type",
                    )
            except ValidationError as error:
                await send_error(
                    websocket,
                    session,
                    "INVALID_MESSAGE",
                    str(error.errors()[0]["msg"]),
                )
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(jam_id, participant_id, websocket)
        metrics.websocket_connections.dec()
        log_event(
            "participant_disconnected",
            transport="websocket",
            jam_id=str(jam_id),
            participant_id=str(participant_id),
            connection_id=connection_id,
            generation=session.generation,
            outcome="closed",
        )
        reset_correlation_id(context_token)
