"""HTTP API (contracts/api/recommendation.openapi.yaml).

    GET /health
    GET /recommendations?lat=&lon=&limit=

Served by uvicorn from the image's default command; the gateway exposes it
at /api/recommendation/.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Self

import httpx2
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from recommendation_service.catalogue import CatalogueClient, HttpCatalogue, StubCatalogue
from recommendation_service.config import Settings, configure_logging, get_settings
from recommendation_service.errors import InvalidRequest, RecommendationError
from recommendation_service.models import Recommendation, Weather
from recommendation_service.service import Result, recommend
from recommendation_service.weather import NoWeather, OpenMeteoWeather, StubWeather, WeatherClient


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorBody(BaseModel):
    error: ErrorDetail


class RecommendedSong(BaseModel):
    song_id: uuid.UUID
    title: str
    artist: str
    duration_ms: int
    reason: str

    @classmethod
    def from_recommendation(cls, item: Recommendation) -> Self:
        return cls(
            song_id=item.song.song_id,
            title=item.song.title,
            artist=item.song.artist,
            duration_ms=item.song.duration_ms,
            reason=item.reason,
        )


class WeatherBody(BaseModel):
    condition: str
    temperature_c: float

    @classmethod
    def from_weather(cls, weather: Weather) -> Self:
        return cls(condition=weather.condition, temperature_c=weather.temperature_c)


class Recommendations(BaseModel):
    items: list[RecommendedSong]
    weather_used: bool
    weather: WeatherBody | None

    @classmethod
    def from_result(cls, result: Result) -> Self:
        return cls(
            items=[RecommendedSong.from_recommendation(item) for item in result.items],
            weather_used=result.weather_used,
            weather=WeatherBody.from_weather(result.weather) if result.weather else None,
        )


def build_catalogue(settings: Settings, client: httpx2.AsyncClient) -> CatalogueClient:
    if settings.catalogue_mode == "http":
        return HttpCatalogue(settings.catalogue_url, client)
    return StubCatalogue()


def build_weather(settings: Settings, client: httpx2.AsyncClient) -> WeatherClient:
    if settings.weather_mode == "off":
        return NoWeather()
    if settings.weather_mode == "open-meteo":
        return OpenMeteoWeather(settings.weather_url, client)
    return StubWeather(settings.weather_stub_condition)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    async with httpx2.AsyncClient(timeout=settings.catalogue_timeout_seconds) as client:
        app.state.settings = settings
        app.state.catalogue = build_catalogue(settings, client)
        app.state.weather = build_weather(settings, client)
        yield


app = FastAPI(title="SyncWave Recommendation Service", version="1.0.0", lifespan=lifespan)


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    """The shared error shape (contracts/README.md)."""
    return JSONResponse(
        status_code=status_code, content={"error": {"code": code, "message": message}}
    )


@app.exception_handler(RecommendationError)
async def recommendation_error(_: Request, exc: RecommendationError) -> JSONResponse:
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
    "/recommendations",
    responses={
        400: {"model": ErrorBody, "description": "Invalid lat, lon or limit"},
        502: {"model": ErrorBody, "description": "The Catalogue Service could not be reached"},
    },
)
async def get_recommendations(
    request: Request,
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> Recommendations:
    if (lat is None) != (lon is None):
        raise InvalidRequest("lat and lon must be sent together, or both left out")
    state = request.app.state
    result = await recommend(
        state.catalogue,
        state.weather,
        lat=lat,
        lon=lon,
        limit=limit,
        candidate_limit=state.settings.candidate_limit,
        weather_timeout_seconds=state.settings.weather_timeout_seconds,
    )
    return Recommendations.from_result(result)
