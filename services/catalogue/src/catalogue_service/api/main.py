"""HTTP API (contracts/api/catalogue.openapi.yaml).

    GET /health
    GET /songs/{song_id}
    GET /songs        paginated, filterable by processing_status

Read-only: songs are written by the worker from upload/processing events.
Served by uvicorn from the image's default command; the gateway exposes it at
/api/catalogue/.
"""

import base64
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException

from catalogue_service.config import configure_logging, get_settings
from catalogue_service.shared.db import (
    CatalogueRepository,
    Database,
    ProcessingStatus,
    SongRecord,
    StageStatus,
)


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorBody(BaseModel):
    error: ErrorDetail


class Song(BaseModel):
    song_id: uuid.UUID
    title: str
    artist: str
    duration_ms: int | None = Field(default=None, description="null until Waveform has measured it")
    audio_reference: str
    lyrics_status: StageStatus
    waveform_status: StageStatus
    processing_status: ProcessingStatus
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: SongRecord) -> "Song":
        def as_utc(value: datetime) -> datetime:
            return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

        return cls(
            song_id=record.song_id,
            title=record.title,
            artist=record.artist,
            duration_ms=record.duration_ms,
            audio_reference=record.audio_reference,
            lyrics_status=StageStatus(record.lyrics_status),
            waveform_status=StageStatus(record.waveform_status),
            processing_status=ProcessingStatus(record.processing_status),
            created_at=as_utc(record.created_at),
            updated_at=as_utc(record.updated_at),
        )


class SongList(BaseModel):
    items: list[Song]
    next_cursor: str | None = None


def _encode_cursor(created_at: datetime, song_id: uuid.UUID) -> str:
    payload = json.dumps({"created_at": created_at.isoformat(), "song_id": str(song_id)}).encode()
    return base64.urlsafe_b64encode(payload).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return datetime.fromisoformat(payload["created_at"]), uuid.UUID(payload["song_id"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ApiError(400, "INVALID_CURSOR", "cursor is not a valid paging token") from exc


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    database = Database(settings.database_url)
    repository = CatalogueRepository(database.sessions)
    app.state.repository = repository
    grpc_server = None
    if settings.grpc_port > 0:
        from catalogue_service.grpc_service import create_grpc_server

        grpc_server, _ = create_grpc_server(repository, settings, f"[::]:{settings.grpc_port}")
        await grpc_server.start()
    try:
        yield
    finally:
        if grpc_server is not None:
            await grpc_server.stop(grace=2)
        await database.dispose()


app = FastAPI(title="SyncWave Catalogue Service", version="0.1.0", lifespan=lifespan)


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    """The shared error shape (contracts/README.md)."""
    return JSONResponse(
        status_code=status_code, content={"error": {"code": code, "message": message}}
    )


@app.exception_handler(ApiError)
async def api_error(_: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
    problems = "; ".join(
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()
    )
    return error_response(400, "INVALID_REQUEST", problems)


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
    return error_response(exc.status_code, code, str(exc.detail))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get(
    "/songs/{song_id}",
    responses={
        400: {"model": ErrorBody, "description": "song_id is not a UUID"},
        404: {"model": ErrorBody, "description": "No song with this ID exists"},
    },
)
async def get_song(song_id: uuid.UUID, request: Request) -> Song:
    repository: CatalogueRepository = request.app.state.repository
    record = await repository.get(song_id)
    if record is None:
        raise ApiError(404, "SONG_NOT_FOUND", f"No song with ID {song_id}")
    return Song.from_record(record)


@app.get(
    "/songs",
    response_model=SongList,
    responses={
        400: {"model": ErrorBody, "description": "Invalid cursor or processing_status"},
    },
)
async def list_songs(
    request: Request,
    limit: int = 20,
    cursor: str | None = None,
    processing_status: ProcessingStatus | None = None,
) -> SongList:
    if limit < 1 or limit > 100:
        raise ApiError(400, "INVALID_REQUEST", "limit must be between 1 and 100")

    repository: CatalogueRepository = request.app.state.repository
    async with repository._sessions() as session:
        from sqlalchemy import and_, or_, select

        stmt = select(SongRecord)
        if processing_status is not None:
            stmt = stmt.where(SongRecord.processing_status == processing_status.value)
        if cursor is not None:
            created_at, song_id = _decode_cursor(cursor)
            stmt = stmt.where(
                or_(
                    SongRecord.created_at < created_at,
                    and_(
                        SongRecord.created_at == created_at,
                        SongRecord.song_id < song_id,
                    ),
                )
            )
        stmt = stmt.order_by(SongRecord.created_at.desc(), SongRecord.song_id.desc()).limit(
            limit + 1
        )
        rows = (await session.scalars(stmt)).all()

    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [Song.from_record(row) for row in rows]
    next_cursor: str | None = None
    if has_more and rows:
        next_cursor = _encode_cursor(rows[-1].created_at, rows[-1].song_id)
    return SongList(items=items, next_cursor=next_cursor)
