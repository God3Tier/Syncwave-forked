"""HTTP API (contracts/api/search.openapi.yaml).

    GET /health
    GET /search?q=...&limit=&cursor=

Read-only-ish: the index is written by the worker from SongReady events.
Served by uvicorn from the image's default command; the gateway exposes it at
/api/search/.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from search_service.config import configure_logging, get_settings
from search_service.shared.db import Database, SearchRepository, decode_cursor


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


class SearchResult(BaseModel):
    song_id: uuid.UUID
    title: str
    artist: str


class SearchList(BaseModel):
    items: list[SearchResult]
    next_cursor: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    database = Database(settings.database_url)
    repository = SearchRepository(database.sessions)
    app.state.repository = repository
    app.state.database = database
    try:
        yield
    finally:
        await database.dispose()


app = FastAPI(title="SyncWave Search Service", version="0.1.0", lifespan=lifespan)


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
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


MAX_QUERY_LENGTH = 200
MAX_CURSOR_LENGTH = 512


@app.get("/search", response_model=SearchList)
async def search(
    request: Request,
    q: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> SearchList:
    if limit < 1 or limit > 100:
        raise ApiError(400, "INVALID_REQUEST", "limit must be between 1 and 100")
    if q is not None and len(q) > MAX_QUERY_LENGTH:
        raise ApiError(400, "INVALID_REQUEST", f"q must be at most {MAX_QUERY_LENGTH} characters")
    if cursor is not None:
        if len(cursor) > MAX_CURSOR_LENGTH:
            raise ApiError(400, "INVALID_CURSOR", "cursor is too long")
        try:
            decode_cursor(cursor)
        except ValueError as exc:
            raise ApiError(400, "INVALID_CURSOR", "cursor is not a valid paging token") from exc

    repository: SearchRepository = request.app.state.repository
    rows, next_cursor = await repository.search(q, limit, cursor)
    items = [SearchResult(song_id=row.song_id, title=row.title, artist=row.artist) for row in rows]
    return SearchList(items=items, next_cursor=next_cursor)
