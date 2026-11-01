from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from hmac import compare_digest
from typing import Annotated
from uuid import UUID

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse

from jam_service.config import get_settings
from jam_service.manager import (
    JamConflictError,
    JamManager,
    JamNotFoundError,
    JamPermissionError,
)
from jam_service.models import (
    ActorRequest,
    AddQueueItemRequest,
    CreateJamRequest,
    JamResponse,
    MemberRequest,
    PlaybackCommandRequest,
    ReadinessDecisionRequest,
    ReadinessStatusResponse,
    ReorderQueueRequest,
    SeekRequest,
    StartPlaybackRequest,
)
from jam_service.playlist_client import (
    PlaylistClientError,
    PlaylistNotFoundError,
    create_playlist_client,
)
from jam_service.repository import JamRepository
from jam_service.sync_client import Command, SyncClientError, SyncConflictError, create_sync_client

settings = get_settings()
repository = JamRepository(settings.database_url)
sync_client = create_sync_client(settings)
playlist_client = create_playlist_client(settings)
manager = JamManager(repository, sync_client, playlist_client, settings.mock_jam_token)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await repository.initialize()
    await manager.initialize()
    yield
    await manager.close()


app = FastAPI(title="SyncWave Jam Service", version="1.0.0", lifespan=lifespan)


def require_token(x_jam_token: Annotated[str | None, Header()] = None) -> None:
    if x_jam_token is None or not compare_digest(x_jam_token, settings.mock_jam_token):
        raise HTTPException(status_code=401, detail="invalid Jam token")


Authenticated = Annotated[None, Depends(require_token)]


@app.exception_handler(JamNotFoundError)
@app.exception_handler(PlaylistNotFoundError)
async def not_found_handler(_, error: JamNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(error)})


@app.exception_handler(JamPermissionError)
async def permission_handler(_, error: JamPermissionError) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": str(error)})


@app.exception_handler(JamConflictError)
@app.exception_handler(SyncConflictError)
async def conflict_handler(_, error: JamConflictError | SyncConflictError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(error)})


@app.exception_handler(SyncClientError)
async def sync_handler(_, error: SyncClientError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(error)})


@app.exception_handler(PlaylistClientError)
async def playlist_handler(_, error: PlaylistClientError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(error)})


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.service_name}


@app.get("/ready")
async def ready() -> dict[str, str]:
    await repository.ping()
    return {"status": "ready"}


@app.post("/jams", response_model=JamResponse, status_code=201)
async def create_jam(request: CreateJamRequest, _: Authenticated) -> JamResponse:
    return await manager.create(request.owner_id, request.playlist_id)


@app.get("/jams/{jam_id}", response_model=JamResponse)
async def get_jam(jam_id: UUID, _: Authenticated) -> JamResponse:
    return await manager.refresh(jam_id)


@app.post("/jams/{jam_id}/members", response_model=JamResponse)
async def join_jam(jam_id: UUID, request: MemberRequest, _: Authenticated) -> JamResponse:
    return await manager.join(jam_id, request.participant_id)


@app.delete("/jams/{jam_id}/members/{participant_id}", status_code=204)
async def leave_jam(jam_id: UUID, participant_id: UUID, _: Authenticated) -> Response:
    await manager.leave(jam_id, participant_id)
    return Response(status_code=204)


@app.post("/jams/{jam_id}/queue", response_model=JamResponse)
async def add_queue_item(
    jam_id: UUID, request: AddQueueItemRequest, _: Authenticated
) -> JamResponse:
    return await manager.add(jam_id, request.actor_id, request.song_id)


@app.delete("/jams/{jam_id}/queue/{queue_item_id}", response_model=JamResponse)
async def remove_queue_item(
    jam_id: UUID, queue_item_id: UUID, request: ActorRequest, _: Authenticated
) -> JamResponse:
    return await manager.remove(jam_id, request.actor_id, queue_item_id)


@app.put("/jams/{jam_id}/queue", response_model=JamResponse)
async def reorder_queue(
    jam_id: UUID, request: ReorderQueueRequest, _: Authenticated
) -> JamResponse:
    return await manager.reorder(jam_id, request.actor_id, request.queue_item_ids)


@app.post("/jams/{jam_id}/playback/start", response_model=JamResponse)
async def start_playback(
    jam_id: UUID, request: StartPlaybackRequest, _: Authenticated
) -> JamResponse:
    return await manager.start(jam_id, request.actor_id, request.request_id, request.queue_item_id)


@app.post("/jams/{jam_id}/playback/pause", response_model=JamResponse)
async def pause_playback(
    jam_id: UUID, request: PlaybackCommandRequest, _: Authenticated
) -> JamResponse:
    return await manager.command(jam_id, request.actor_id, request.request_id, Command.PAUSE)


@app.post("/jams/{jam_id}/playback/resume", response_model=JamResponse)
async def resume_playback(
    jam_id: UUID, request: PlaybackCommandRequest, _: Authenticated
) -> JamResponse:
    return await manager.command(jam_id, request.actor_id, request.request_id, Command.RESUME)


@app.post("/jams/{jam_id}/playback/seek", response_model=JamResponse)
async def seek_playback(jam_id: UUID, request: SeekRequest, _: Authenticated) -> JamResponse:
    return await manager.seek(jam_id, request.actor_id, request.request_id, request.position_ms)


@app.post("/jams/{jam_id}/playback/skip", response_model=JamResponse)
async def skip_playback(
    jam_id: UUID, request: PlaybackCommandRequest, _: Authenticated
) -> JamResponse:
    return await manager.skip(jam_id, request.actor_id, request.request_id)


@app.get("/jams/{jam_id}/playback/readiness", response_model=ReadinessStatusResponse)
async def readiness(jam_id: UUID, actor_id: UUID, _: Authenticated) -> ReadinessStatusResponse:
    status = await manager.readiness(jam_id, actor_id)
    return ReadinessStatusResponse(
        **{field: getattr(status, field) for field in ReadinessStatusResponse.model_fields}
    )


@app.post("/jams/{jam_id}/playback/readiness-decision", response_model=JamResponse)
async def readiness_decision(
    jam_id: UUID, request: ReadinessDecisionRequest, _: Authenticated
) -> JamResponse:
    return await manager.decide(jam_id, request.actor_id, request.request_id, request.decision)


@app.websocket("/jams/{jam_id}/ws")
async def jam_websocket(
    websocket: WebSocket, jam_id: UUID, participant_id: UUID, token: str
) -> None:
    if not compare_digest(token, settings.mock_jam_token):
        await websocket.close(code=4401, reason="invalid Jam token")
        return
    try:
        await manager.connect(jam_id, participant_id, websocket)
    except JamNotFoundError:
        await websocket.close(code=4404, reason="Jam not found")
        return
    except JamPermissionError:
        await websocket.close(code=4403, reason="not a Jam member")
        return
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(jam_id, websocket)
