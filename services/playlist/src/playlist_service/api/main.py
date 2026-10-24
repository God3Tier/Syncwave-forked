"""HTTP API (contracts/api/playlist.openapi.yaml).

    GET    /health
    POST   /playlists                              create
    GET    /playlists?owner_id=                    list a user's playlists
    GET    /playlists/{playlist_id}                read, songs in order
    PATCH  /playlists/{playlist_id}                rename
    DELETE /playlists/{playlist_id}                delete
    POST   /playlists/{playlist_id}/songs          add a song
    PUT    /playlists/{playlist_id}/songs          reorder
    DELETE /playlists/{playlist_id}/songs/{song_id}  remove a song
    POST   /playlists/{playlist_id}/shuffle        shuffle and save

Served by uvicorn from the image's default command; the gateway exposes it
at /api/playlist/.
"""

import base64
import binascii
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Self

import httpx2
from fastapi import FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StringConstraints
from starlette.exceptions import HTTPException

from playlist_service.catalogue import CatalogueClient, HttpCatalogue, NoCatalogue
from playlist_service.config import Settings, configure_logging, get_settings
from playlist_service.db import (
    Database,
    PlaylistData,
    PlaylistRepository,
    PlaylistSummaryData,
)
from playlist_service.errors import (
    CatalogueUnavailable,
    InvalidRequest,
    PlaylistError,
    PlaylistNotFound,
    SongAlreadyInPlaylist,
    SongNotFound,
    SongNotInPlaylist,
)

# Business-rule failure -> HTTP status (error codes are in contracts/api/playlist.openapi.yaml)
STATUS_FOR_ERROR: dict[type[PlaylistError], int] = {
    PlaylistNotFound: 404,
    SongNotInPlaylist: 404,
    SongAlreadyInPlaylist: 409,
    InvalidRequest: 400,
    SongNotFound: 404,
    CatalogueUnavailable: 502,
}

PlaylistName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorBody(BaseModel):
    error: ErrorDetail


class CreatePlaylistRequest(BaseModel):
    owner_id: uuid.UUID
    name: PlaylistName


class RenamePlaylistRequest(BaseModel):
    name: PlaylistName


class AddSongRequest(BaseModel):
    song_id: uuid.UUID
    position: int | None = Field(default=None, ge=0)


class ReorderSongsRequest(BaseModel):
    song_ids: list[uuid.UUID]


class PlaylistSong(BaseModel):
    song_id: uuid.UUID
    position: int


class Playlist(BaseModel):
    playlist_id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    songs: list[PlaylistSong]
    song_count: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_data(cls, data: PlaylistData) -> Self:
        return cls(
            playlist_id=data.playlist_id,
            owner_id=data.owner_id,
            name=data.name,
            songs=[
                PlaylistSong(song_id=song_id, position=position)
                for position, song_id in enumerate(data.songs)
            ],
            song_count=len(data.songs),
            created_at=utc(data.created_at),
            updated_at=utc(data.updated_at),
        )


class PlaylistSummary(BaseModel):
    playlist_id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    song_count: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_data(cls, data: PlaylistSummaryData) -> Self:
        return cls(
            playlist_id=data.playlist_id,
            owner_id=data.owner_id,
            name=data.name,
            song_count=data.song_count,
            created_at=utc(data.created_at),
            updated_at=utc(data.updated_at),
        )


class PlaylistPage(BaseModel):
    items: list[PlaylistSummary]
    next_cursor: str | None


def utc(value: datetime) -> datetime:
    # SQLite (tests) drops the time zone; stored values are always UTC.
    return value.replace(tzinfo=value.tzinfo or UTC)


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode()).decode()


def decode_cursor(cursor: str) -> int:
    """The cursor is opaque to clients; it is the number of playlists to skip."""
    try:
        offset = int(base64.urlsafe_b64decode(cursor.encode()))
    except (ValueError, binascii.Error) as error:
        raise InvalidRequest("cursor is not valid") from error
    if offset < 0:
        raise InvalidRequest("cursor is not valid")
    return offset


def build_catalogue(settings: Settings, client: httpx2.AsyncClient) -> CatalogueClient:
    if settings.catalogue_mode == "http":
        return HttpCatalogue(settings.catalogue_url, client)
    return NoCatalogue()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    database = Database(settings.database_url)
    app.state.repository = PlaylistRepository(database.sessions)
    grpc_server = None
    if settings.grpc_port > 0:
        from playlist_service.grpc_service import create_grpc_server

        grpc_server, _ = create_grpc_server(
            app.state.repository, settings, f"[::]:{settings.grpc_port}"
        )
        await grpc_server.start()
    try:
        async with httpx2.AsyncClient(timeout=settings.catalogue_timeout_seconds) as client:
            app.state.catalogue = build_catalogue(settings, client)
            yield
    finally:
        if grpc_server is not None:
            await grpc_server.stop(grace=2)
        await database.dispose()


app = FastAPI(title="SyncWave Playlist Service", version="1.0.0", lifespan=lifespan)


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    """The shared error shape (contracts/README.md)."""
    return JSONResponse(
        status_code=status_code, content={"error": {"code": code, "message": message}}
    )


@app.exception_handler(PlaylistError)
async def playlist_error(_: Request, exc: PlaylistError) -> JSONResponse:
    return error_response(STATUS_FOR_ERROR.get(type(exc), 400), exc.code, exc.message)


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


def repository(request: Request) -> PlaylistRepository:
    return request.app.state.repository


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/playlists",
    status_code=201,
    responses={400: {"model": ErrorBody, "description": "Invalid body"}},
)
async def create_playlist(body: CreatePlaylistRequest, request: Request) -> Playlist:
    return Playlist.from_data(await repository(request).create(body.owner_id, body.name))


@app.get("/playlists", responses={400: {"model": ErrorBody}})
async def list_playlists(
    request: Request,
    owner_id: uuid.UUID,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
) -> PlaylistPage:
    offset = decode_cursor(cursor) if cursor else 0
    summaries, has_more = await repository(request).list_for_owner(owner_id, limit, offset)
    return PlaylistPage(
        items=[PlaylistSummary.from_data(summary) for summary in summaries],
        next_cursor=encode_cursor(offset + limit) if has_more else None,
    )


@app.get(
    "/playlists/{playlist_id}",
    responses={400: {"model": ErrorBody}, 404: {"model": ErrorBody}},
)
async def get_playlist(playlist_id: uuid.UUID, request: Request) -> Playlist:
    data = await repository(request).get(playlist_id)
    if data is None:
        raise PlaylistNotFound(f"No playlist with id {playlist_id}")
    return Playlist.from_data(data)


@app.patch(
    "/playlists/{playlist_id}",
    responses={400: {"model": ErrorBody}, 404: {"model": ErrorBody}},
)
async def rename_playlist(
    playlist_id: uuid.UUID, body: RenamePlaylistRequest, request: Request
) -> Playlist:
    return Playlist.from_data(await repository(request).rename(playlist_id, body.name))


@app.delete(
    "/playlists/{playlist_id}",
    status_code=204,
    responses={400: {"model": ErrorBody}, 404: {"model": ErrorBody}},
)
async def delete_playlist(playlist_id: uuid.UUID, request: Request) -> Response:
    await repository(request).delete(playlist_id)
    return Response(status_code=204)


@app.post(
    "/playlists/{playlist_id}/songs",
    responses={
        400: {"model": ErrorBody},
        404: {"model": ErrorBody, "description": "No such playlist, or no such song"},
        409: {"model": ErrorBody, "description": "The song is already in the playlist"},
        502: {"model": ErrorBody, "description": "The Catalogue could not be asked"},
    },
)
async def add_song(playlist_id: uuid.UUID, body: AddSongRequest, request: Request) -> Playlist:
    # Only adding a song needs the Catalogue; every other endpoint works without it.
    # The playlist is looked up first so an unknown playlist is always PLAYLIST_NOT_FOUND.
    if await repository(request).get(playlist_id) is None:
        raise PlaylistNotFound(f"No playlist with id {playlist_id}")
    if not await request.app.state.catalogue.exists(body.song_id):
        raise SongNotFound(f"No song with ID {body.song_id} in the Catalogue")
    data = await repository(request).add_song(playlist_id, body.song_id, body.position)
    return Playlist.from_data(data)


@app.put(
    "/playlists/{playlist_id}/songs",
    responses={400: {"model": ErrorBody}, 404: {"model": ErrorBody}},
)
async def reorder_songs(
    playlist_id: uuid.UUID, body: ReorderSongsRequest, request: Request
) -> Playlist:
    return Playlist.from_data(await repository(request).reorder(playlist_id, body.song_ids))


@app.delete(
    "/playlists/{playlist_id}/songs/{song_id}",
    responses={400: {"model": ErrorBody}, 404: {"model": ErrorBody}},
)
async def remove_song(playlist_id: uuid.UUID, song_id: uuid.UUID, request: Request) -> Playlist:
    return Playlist.from_data(await repository(request).remove_song(playlist_id, song_id))


@app.post(
    "/playlists/{playlist_id}/shuffle",
    responses={400: {"model": ErrorBody}, 404: {"model": ErrorBody}},
)
async def shuffle_playlist(playlist_id: uuid.UUID, request: Request) -> Playlist:
    return Playlist.from_data(await repository(request).shuffle(playlist_id))
