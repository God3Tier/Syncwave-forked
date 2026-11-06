"""Multipart upload API, served behind /api/upload by the gateway."""

import asyncio
import logging
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated

from fastapi import FastAPI, File, Form, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from upload_service.auth import AuthVerifier, require_account
from upload_service.config import Settings
from upload_service.db import Database, Status, UploadRecord
from upload_service.service import UploadError, UploadService
from upload_service.storage import S3Storage


class Receipt(BaseModel):
    song_id: uuid.UUID
    event_id: uuid.UUID
    status: Status
    title: str
    artist: str
    mood: str | None
    uploader_id: uuid.UUID | None
    content_sha256: str | None
    duplicate: bool = False
    duration_ms: int | None
    audio_reference: str
    lyrics_reference: str | None
    publish_attempts: int
    last_error_code: str | None
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None

    @classmethod
    def from_record(cls, record: UploadRecord, *, duplicate: bool = False) -> Receipt:
        values = {name: getattr(record, name) for name in cls.model_fields if name != "duplicate"}
        values["duplicate"] = duplicate
        for field in ("created_at", "updated_at", "published_at"):
            if values[field] is not None and values[field].tzinfo is None:
                values[field] = values[field].replace(tzinfo=UTC)
        return cls(**values)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings.from_env()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    database = Database(settings.database_url)
    storage = S3Storage(settings)
    app.state.database = database
    app.state.storage = storage
    app.state.auth_verifier = AuthVerifier(settings.auth_jwks_url)
    app.state.service = UploadService(database.sessions, storage, settings)
    try:
        yield
    finally:
        storage.close()
        await database.dispose()


app = FastAPI(
    title="SyncWave Upload Service",
    version="0.1.0",
    lifespan=lifespan,
    root_path="/api/upload",
    redoc_url=None,
)


def error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


@app.exception_handler(UploadError)
async def upload_error(_: Request, exc: UploadError) -> JSONResponse:
    return error(exc.status, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
    problems = "; ".join(
        f"{'.'.join(str(part) for part in problem['loc'])}: {problem['msg']}"
        for problem in exc.errors()
    )
    return error(400, "INVALID_REQUEST", problems)


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    return error(exc.status_code, "HTTP_ERROR", str(exc.detail))


@app.exception_handler(SQLAlchemyError)
async def database_error(_: Request, exc: SQLAlchemyError) -> JSONResponse:
    logging.getLogger(__name__).warning("upload_database_unavailable")
    return error(503, "DATABASE_UNAVAILABLE", "Upload storage is temporarily unavailable")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready(request: Request) -> dict[str, str]:
    try:
        async with asyncio.timeout(5):
            async with request.app.state.database.sessions() as session:
                await session.execute(text("SELECT song_id FROM uploads LIMIT 1"))
            await asyncio.to_thread(request.app.state.storage.ready)
    except Exception as exc:
        raise UploadError(503, "NOT_READY", "Upload dependencies are unavailable") from exc
    return {"status": "ok"}


@app.post("/uploads", status_code=202, response_model=Receipt)
async def create_upload(
    request: Request,
    response: Response,
    title: Annotated[str, Form(min_length=1, max_length=200)],
    artist: Annotated[str, Form(min_length=1, max_length=200)],
    audio: Annotated[UploadFile, File()],
    lyrics: Annotated[UploadFile | None, File()] = None,
    duration_ms: Annotated[int | None, Form(gt=0, le=2147483647)] = None,
    mood: Annotated[str | None, Form(max_length=64)] = None,
) -> Receipt:
    """Store media and queue its event. A 202 response does not mean processing is complete."""
    account = require_account(request)
    service: UploadService = request.app.state.service
    record, duplicate = await service.create(
        title,
        artist,
        duration_ms,
        audio,
        lyrics,
        uploader_id=account.user_id,
        mood=mood,
    )
    if duplicate:
        response.status_code = 200
    # Relative to the public gateway, without reflecting untrusted headers.
    response.headers["Location"] = f"/api/upload/uploads/{record.song_id}"
    return Receipt.from_record(record, duplicate=duplicate)


@app.get("/uploads/{song_id}", response_model=Receipt)
async def get_upload(song_id: uuid.UUID, request: Request) -> Receipt:
    """Read upload/event delivery state; Catalogue owns lyrics/waveform readiness."""
    async with request.app.state.database.sessions() as session:
        record = await session.get(UploadRecord, song_id)
    if record is None:
        raise UploadError(404, "UPLOAD_NOT_FOUND", f"No upload with ID {song_id}")
    return Receipt.from_record(record)
