"""HTTP API (contracts/api/lyrics.openapi.yaml).

    GET /health
    GET /songs/{song_id}/lyrics

Read-only: lyrics are written by the worker. Served by uvicorn from the
image's default command; the gateway exposes it at /api/lyrics/.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from lyrics_service.config import configure_logging, get_settings
from lyrics_service.shared.db import Database, LyricsRecord, LyricsRepository, Status


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


class LyricLine(BaseModel):
    time_ms: int
    text: str


class Lyrics(BaseModel):
    song_id: uuid.UUID
    status: Status
    line_count: int
    lines: list[LyricLine]
    error: ErrorDetail | None = None
    updated_at: datetime

    @classmethod
    def from_record(cls, record: LyricsRecord) -> Lyrics:
        ready = record.status == Status.READY
        error = None
        if record.status == Status.FAILED:
            error = ErrorDetail(
                code=record.error_code or "PROCESSING_ERROR",
                message=record.error_message or "",
            )
        return cls(
            song_id=record.song_id,
            status=Status(record.status),
            line_count=record.line_count if ready else 0,
            lines=(record.lines or []) if ready else [],
            error=error,
            # SQLite (tests) drops the time zone; stored values are always UTC.
            updated_at=record.updated_at.replace(tzinfo=record.updated_at.tzinfo or UTC),
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    database = Database(settings.database_url)
    app.state.repository = LyricsRepository(database.sessions)
    yield
    await database.dispose()


app = FastAPI(title="SyncWave Lyrics Service", version="1.0.0", lifespan=lifespan)


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
    "/songs/{song_id}/lyrics",
    response_model_exclude_none=True,
    responses={
        400: {"model": ErrorBody, "description": "song_id is not a UUID"},
        404: {"model": ErrorBody, "description": "No lyrics have been received for this song"},
    },
)
async def get_lyrics(song_id: uuid.UUID, request: Request) -> Lyrics:
    repository: LyricsRepository = request.app.state.repository
    record = await repository.get(song_id)
    if record is None:
        raise ApiError(404, "LYRICS_NOT_FOUND", f"No lyrics have been received for song {song_id}")
    return Lyrics.from_record(record)
