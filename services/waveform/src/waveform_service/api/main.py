"""HTTP API (contracts/api/waveform.openapi.yaml).

    GET /health
    GET /songs/{song_id}/waveform?points=N
    GET /songs/{song_id}/waveform/bands

Read-only: waveforms are written by the worker. Served by uvicorn from the
image's default command; the gateway exposes it at /api/waveform/.
"""

import base64
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException

from waveform_service.config import configure_logging, get_settings
from waveform_service.shared.db import Database, Status, WaveformRecord, WaveformRepository
from waveform_service.shared.waveform import downsample


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


class Waveform(BaseModel):
    song_id: uuid.UUID
    status: Status
    points: int
    duration_ms: int | None
    peaks: list[float]
    error: ErrorDetail | None = Field(default=None, exclude_if=lambda error: error is None)
    updated_at: datetime

    @classmethod
    def from_record(cls, record: WaveformRecord, points: int | None) -> Waveform:
        ready = record.status == Status.READY
        peaks = (record.peaks or []) if ready else []
        if points is not None:
            peaks = downsample(peaks, points)
        return cls(
            song_id=record.song_id,
            status=Status(record.status),
            points=len(peaks),
            duration_ms=record.duration_ms if ready else None,
            peaks=peaks,
            error=_error(record),
            updated_at=_utc(record.updated_at),
        )


class WaveformBands(BaseModel):
    song_id: uuid.UUID
    status: Status
    frame_rate: float | None
    frame_count: int
    band_count: int
    band_edges_hz: list[float]
    levels: str
    error: ErrorDetail | None = Field(default=None, exclude_if=lambda error: error is None)
    updated_at: datetime

    @classmethod
    def from_record(cls, record: WaveformRecord) -> WaveformBands:
        ready = record.status == Status.READY
        edges = (record.band_edges_hz or []) if ready else []
        levels = (record.bands or b"") if ready else b""
        band_count = max(len(edges) - 1, 0)
        return cls(
            song_id=record.song_id,
            status=Status(record.status),
            frame_rate=record.band_frame_rate if ready else None,
            frame_count=len(levels) // band_count if band_count else 0,
            band_count=band_count,
            band_edges_hz=edges,
            levels=base64.b64encode(levels).decode(),
            error=_error(record),
            updated_at=_utc(record.updated_at),
        )


def _error(record: WaveformRecord) -> ErrorDetail | None:
    if record.status != Status.FAILED:
        return None
    return ErrorDetail(
        code=record.error_code or "PROCESSING_ERROR", message=record.error_message or ""
    )


def _utc(value: datetime) -> datetime:
    # SQLite (tests) drops the time zone; stored values are always UTC.
    return value.replace(tzinfo=value.tzinfo or UTC)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    database = Database(settings.database_url)
    app.state.repository = WaveformRepository(database.sessions)
    yield
    await database.dispose()


app = FastAPI(title="SyncWave Waveform Service", version="1.0.0", lifespan=lifespan)


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
    "/songs/{song_id}/waveform",
    responses={
        400: {"model": ErrorBody, "description": "song_id is not a UUID, or points is invalid"},
        404: {"model": ErrorBody, "description": "No waveform has been received for this song"},
    },
)
async def get_waveform(
    song_id: uuid.UUID,
    request: Request,
    points: Annotated[
        int | None,
        Query(ge=1, description="Return at most this many peaks, e.g. the display width"),
    ] = None,
) -> Waveform:
    return Waveform.from_record(await _find(request, song_id), points)


@app.get(
    "/songs/{song_id}/waveform/bands",
    responses={
        400: {"model": ErrorBody, "description": "song_id is not a UUID"},
        404: {"model": ErrorBody, "description": "No waveform has been received for this song"},
    },
)
async def get_waveform_bands(song_id: uuid.UUID, request: Request) -> WaveformBands:
    return WaveformBands.from_record(await _find(request, song_id, with_bands=True))


async def _find(
    request: Request, song_id: uuid.UUID, *, with_bands: bool = False
) -> WaveformRecord:
    repository: WaveformRepository = request.app.state.repository
    record = await repository.get(song_id, with_bands=with_bands)
    if record is None:
        raise ApiError(
            404, "WAVEFORM_NOT_FOUND", f"No waveform has been received for song {song_id}"
        )
    return record
