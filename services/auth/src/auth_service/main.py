import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text

from auth_service.config import get_settings
from auth_service.db import Database, UsernameTaken, UserRepository
from auth_service.tokens import SESSION_SECONDS, TokenSigner, public_claims

COOKIE_NAME = "syncwave_session"
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,24}$")


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=24)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not USERNAME_PATTERN.fullmatch(value.strip()):
            raise ValueError("Use 3–24 letters, numbers, or underscores")
        return normalized


class SessionUser(BaseModel):
    id: UUID
    username: str


def user_response(record) -> SessionUser:
    return SessionUser(id=record.user_id, username=record.username)


def account_from_cookie(request: Request) -> dict[str, object]:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    try:
        claims = public_claims(token, request.app.state.signer.private_key.public_key())
        claims["sub"] = str(UUID(str(claims["sub"])))
        return claims
    except (jwt.InvalidTokenError, ValueError, TypeError) as error:
        raise HTTPException(status_code=401, detail="Your session has expired") from error


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    database = Database(settings.database_url)
    app.state.users = UserRepository(database.sessions)
    app.state.hasher = PasswordHasher()
    app.state.signer = TokenSigner(settings.jwt_private_key_path)
    try:
        async with database.engine.begin() as connection:
            await connection.execute(text("SELECT 1"))
        yield
    finally:
        await database.dispose()


app = FastAPI(title="SyncWave Auth Service", version="1.0.0", lifespan=lifespan)


def set_session(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=get_settings().session_cookie_secure,
        samesite="lax",
        path="/",
    )


def check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != get_settings().app_origin:
        raise HTTPException(status_code=403, detail="Request origin is not allowed")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": get_settings().service_name}


@app.get("/.well-known/jwks.json")
async def jwks(request: Request) -> dict[str, list[dict[str, str]]]:
    return request.app.state.signer.jwks()


@app.post("/signup", response_model=SessionUser, status_code=201)
async def signup(body: Credentials, request: Request) -> SessionUser:
    check_origin(request)
    try:
        user = await request.app.state.users.create(
            body.username, request.app.state.hasher.hash(body.password)
        )
    except UsernameTaken as error:
        raise HTTPException(status_code=409, detail="That username is already taken") from error
    return user_response(user)


@app.post("/login", response_model=SessionUser)
async def login(body: Credentials, request: Request, response: Response) -> SessionUser:
    check_origin(request)
    user = await request.app.state.users.get_by_username(body.username)
    if user is None:
        raise HTTPException(status_code=401, detail="Username or password is incorrect")
    try:
        request.app.state.hasher.verify(user.password_hash, body.password)
    except (VerifyMismatchError, VerificationError, InvalidHashError) as error:
        raise HTTPException(status_code=401, detail="Username or password is incorrect") from error
    set_session(response, request.app.state.signer.issue(str(user.user_id), user.username))
    return user_response(user)


@app.post("/logout", status_code=204)
async def logout(request: Request, response: Response) -> Response:
    check_origin(request)
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        secure=get_settings().session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.status_code = 204
    return response


@app.get("/me", response_model=SessionUser)
async def me(request: Request) -> SessionUser:
    claims = account_from_cookie(request)
    user = await request.app.state.users.get_by_id(UUID(str(claims["sub"])))
    if user is None:
        raise HTTPException(status_code=401, detail="Account no longer exists")
    return user_response(user)
