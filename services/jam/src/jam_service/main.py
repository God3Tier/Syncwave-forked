from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse

from jam_service.auth import (
    AuthVerifier,
    actor_for_request,
    check_request_origin,
    issue_member_token,
    member_actor,
    optional_account,
    owner_for_request,
)
from jam_service.config import get_settings
from jam_service.manager import (
    JamConflictError,
    JamManager,
    JamNotFoundError,
    JamPermissionError,
)
from jam_service.models import (
    AddQueueItemRequest,
    CreateJamRequest,
    JamResponse,
    PlaybackCommandRequest,
    ReadinessDecisionRequest,
    ReadinessStatusResponse,
    ReorderQueueRequest,
    SeekRequest,
    StartPlaybackRequest,
    TransferOwnershipRequest,
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
manager = JamManager(repository, sync_client, playlist_client)
auth_verifier = AuthVerifier(settings.auth_jwks_url)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    app.state.auth_verifier = auth_verifier
    await repository.initialize()
    await manager.initialize()
    yield
    await manager.close()


app = FastAPI(title="SyncWave Jam Service", version="1.0.0", lifespan=lifespan)


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
async def create_jam(request: CreateJamRequest, http_request: Request) -> JamResponse:
    check_request_origin(http_request)
    owner = optional_account(http_request)
    if owner is None:
        raise HTTPException(status_code=401, detail="Sign in to host a Jam")
    jam = await manager.create(owner.user_id, owner.username, request.playlist_id)
    return jam.model_copy(update={"member_id": owner.user_id})


@app.get("/jams/{jam_id}", response_model=JamResponse)
async def get_jam(jam_id: UUID, request: Request) -> JamResponse:
    actor_for_request(request, jam_id, manager)
    return await manager.refresh(jam_id)


@app.post("/jams/{jam_id}/members", response_model=JamResponse)
async def join_jam(jam_id: UUID, request: Request) -> JamResponse:
    check_request_origin(request)
    account = optional_account(request)
    if account is not None:
        joined = await manager.join(jam_id, account.user_id, account.username)
        return joined.model_copy(update={"member_id": account.user_id, "member_token": None})

    participant_id = uuid4()
    joined = await manager.join(jam_id, participant_id, f"Guest {str(participant_id)[:8]}")
    return joined.model_copy(
        update={
            "member_id": participant_id,
            "member_token": issue_member_token(settings, jam_id, participant_id),
        }
    )


@app.post("/jams/by-code/{join_code}/members", response_model=JamResponse)
async def join_jam_by_code(join_code: str, request: Request) -> JamResponse:
    if len(join_code) != 8 or not join_code.isdigit():
        raise HTTPException(status_code=422, detail="Jam code must contain exactly 8 digits")
    return await join_jam(manager.find_by_code(join_code), request)


@app.delete("/jams/{jam_id}/members/{participant_id}", status_code=204)
async def leave_jam(jam_id: UUID, participant_id: UUID, request: Request) -> Response:
    check_request_origin(request)
    actor = actor_for_request(request, jam_id, manager)
    jam = manager.get(jam_id)
    if actor.user_id != participant_id and not (actor.account and actor.user_id == jam.owner_id):
        raise HTTPException(status_code=403, detail="You can only leave as yourself")
    await manager.leave(jam_id, actor.user_id)
    return Response(status_code=204)


@app.put("/jams/{jam_id}/owner", response_model=JamResponse)
async def transfer_ownership(
    jam_id: UUID, body: TransferOwnershipRequest, request: Request
) -> JamResponse:
    check_request_origin(request)
    owner_id = owner_for_request(request, jam_id, manager)
    return await manager.transfer(jam_id, owner_id, body.participant_id, leave=False)


@app.post("/jams/{jam_id}/owner/transfer-and-leave", response_model=JamResponse)
async def transfer_and_leave(
    jam_id: UUID, body: TransferOwnershipRequest, request: Request
) -> JamResponse:
    check_request_origin(request)
    owner_id = owner_for_request(request, jam_id, manager)
    return await manager.transfer(jam_id, owner_id, body.participant_id, leave=True)


@app.post("/jams/{jam_id}/end", response_model=JamResponse)
async def end_jam(jam_id: UUID, request: Request) -> JamResponse:
    check_request_origin(request)
    owner_id = owner_for_request(request, jam_id, manager)
    return await manager.end(jam_id, owner_id)


@app.post("/jams/{jam_id}/queue", response_model=JamResponse)
async def add_queue_item(
    jam_id: UUID, request: AddQueueItemRequest, http_request: Request
) -> JamResponse:
    check_request_origin(http_request)
    actor = actor_for_request(http_request, jam_id, manager)
    return await manager.add(jam_id, actor.user_id, request.song_id)


@app.delete("/jams/{jam_id}/queue/{queue_item_id}", response_model=JamResponse)
async def remove_queue_item(jam_id: UUID, queue_item_id: UUID, request: Request) -> JamResponse:
    check_request_origin(request)
    owner_id = owner_for_request(request, jam_id, manager)
    return await manager.remove(jam_id, owner_id, queue_item_id)


@app.put("/jams/{jam_id}/queue", response_model=JamResponse)
async def reorder_queue(jam_id: UUID, body: ReorderQueueRequest, request: Request) -> JamResponse:
    check_request_origin(request)
    owner_id = owner_for_request(request, jam_id, manager)
    return await manager.reorder(jam_id, owner_id, body.queue_item_ids)


@app.post("/jams/{jam_id}/playback/start", response_model=JamResponse)
async def start_playback(jam_id: UUID, body: StartPlaybackRequest, request: Request) -> JamResponse:
    check_request_origin(request)
    owner_id = owner_for_request(request, jam_id, manager)
    return await manager.start(jam_id, owner_id, body.request_id, body.queue_item_id)


@app.post("/jams/{jam_id}/playback/pause", response_model=JamResponse)
async def pause_playback(
    jam_id: UUID, body: PlaybackCommandRequest, request: Request
) -> JamResponse:
    check_request_origin(request)
    owner_id = owner_for_request(request, jam_id, manager)
    return await manager.command(jam_id, owner_id, body.request_id, Command.PAUSE)


@app.post("/jams/{jam_id}/playback/resume", response_model=JamResponse)
async def resume_playback(
    jam_id: UUID, body: PlaybackCommandRequest, request: Request
) -> JamResponse:
    check_request_origin(request)
    owner_id = owner_for_request(request, jam_id, manager)
    return await manager.command(jam_id, owner_id, body.request_id, Command.RESUME)


@app.post("/jams/{jam_id}/playback/seek", response_model=JamResponse)
async def seek_playback(jam_id: UUID, body: SeekRequest, request: Request) -> JamResponse:
    check_request_origin(request)
    owner_id = owner_for_request(request, jam_id, manager)
    return await manager.seek(jam_id, owner_id, body.request_id, body.position_ms)


@app.post("/jams/{jam_id}/playback/skip", response_model=JamResponse)
async def skip_playback(
    jam_id: UUID, body: PlaybackCommandRequest, request: Request
) -> JamResponse:
    check_request_origin(request)
    owner_id = owner_for_request(request, jam_id, manager)
    return await manager.skip(jam_id, owner_id, body.request_id)


@app.get("/jams/{jam_id}/playback/readiness", response_model=ReadinessStatusResponse)
async def readiness(jam_id: UUID, request: Request) -> ReadinessStatusResponse:
    owner_id = owner_for_request(request, jam_id, manager)
    status = await manager.readiness(jam_id, owner_id)
    return ReadinessStatusResponse(
        **{field: getattr(status, field) for field in ReadinessStatusResponse.model_fields}
    )


@app.post("/jams/{jam_id}/playback/readiness-decision", response_model=JamResponse)
async def readiness_decision(
    jam_id: UUID, body: ReadinessDecisionRequest, request: Request
) -> JamResponse:
    check_request_origin(request)
    owner_id = owner_for_request(request, jam_id, manager)
    return await manager.decide(jam_id, owner_id, body.request_id, body.decision)


@app.websocket("/jams/{jam_id}/ws")
async def jam_websocket(
    websocket: WebSocket,
    jam_id: UUID,
    participant_id: UUID | None = None,
    token: str | None = None,
) -> None:
    try:
        if token:
            actor_id = member_actor(token, jam_id, settings)
            jam = manager.get(jam_id)
            if actor_id == jam.owner_id or actor_id not in jam.participant_ids:
                raise HTTPException(status_code=403, detail="not a Jam member")
        else:
            account = optional_account(websocket)
            if account is None or account.user_id not in manager.get(jam_id).participant_ids:
                raise HTTPException(status_code=401, detail="sign in or join this Jam")
            actor_id = account.user_id
        if participant_id is not None and actor_id != participant_id:
            raise HTTPException(status_code=403, detail="participant identity does not match")
    except HTTPException as error:
        await websocket.close(
            code=4401 if error.status_code == 401 else 4403, reason=str(error.detail)
        )
        return
    try:
        await manager.connect(jam_id, actor_id, websocket)
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
