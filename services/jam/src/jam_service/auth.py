from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from fastapi import HTTPException, Request
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError

from jam_service.config import Settings, get_settings

ACCOUNT_COOKIE = "syncwave_session"
ACCOUNT_ISSUER = "syncwave-auth"
ACCOUNT_AUDIENCE = "syncwave"
MEMBER_ISSUER = "syncwave-jam"
MEMBER_SECONDS = 30 * 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class Actor:
    user_id: UUID
    account: bool
    username: str


@dataclass(frozen=True, slots=True)
class AccountIdentity:
    user_id: UUID
    username: str


class AuthVerifier:
    def __init__(self, jwks_url: str) -> None:
        self._client = PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=3600)

    def account(self, token: str) -> AccountIdentity:
        try:
            key = self._client.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=ACCOUNT_AUDIENCE,
                issuer=ACCOUNT_ISSUER,
                options={"require": ["sub", "exp", "iat"]},
            )
            username = claims.get("username")
            if not isinstance(username, str) or not username:
                raise ValueError("username claim is missing")
            return AccountIdentity(UUID(claims["sub"]), username)
        except (jwt.InvalidTokenError, KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=401, detail="Sign in to continue") from error
        except PyJWKClientError as error:
            raise HTTPException(
                status_code=503, detail="Authentication service is unavailable"
            ) from error


def optional_account(request: Request) -> AccountIdentity | None:
    token = request.cookies.get(ACCOUNT_COOKIE)
    if not token:
        return None
    return request.app.state.auth_verifier.account(token)


def issue_member_token(settings: Settings, jam_id: UUID, participant_id: UUID) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": MEMBER_ISSUER,
            "aud": str(jam_id),
            "sub": str(participant_id),
            "iat": now,
            "exp": now + timedelta(seconds=MEMBER_SECONDS),
        },
        settings.jam_member_token_secret,
        algorithm="HS256",
    )


def member_actor(token: str, jam_id: UUID, settings: Settings) -> UUID:
    try:
        claims = jwt.decode(
            token,
            settings.jam_member_token_secret,
            algorithms=["HS256"],
            audience=str(jam_id),
            issuer=MEMBER_ISSUER,
            options={"require": ["sub", "exp", "iat"]},
        )
        return UUID(claims["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=401, detail="Invalid Jam membership token") from error


def actor_for_request(request: Request, jam_id: UUID, manager) -> Actor:
    token = request.headers.get("x-jam-token")
    settings = get_settings()
    if token:
        user_id = member_actor(token, jam_id, settings)
        jam = manager.get(jam_id)
        if user_id == jam.owner_id or user_id not in jam.participant_ids:
            raise HTTPException(status_code=403, detail="You are not a member of this Jam")
        username = next(
            (p.username for p in jam.participants if p.participant_id == user_id), "Guest"
        )
        return Actor(user_id=user_id, account=False, username=username)
    identity = optional_account(request)
    if identity is None:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    jam = manager.get(jam_id)
    if identity.user_id not in jam.participant_ids:
        raise HTTPException(status_code=403, detail="Join this Jam first")
    return Actor(user_id=identity.user_id, account=True, username=identity.username)


def owner_for_request(request: Request, jam_id: UUID, manager) -> UUID:
    identity = optional_account(request)
    if identity is None:
        raise HTTPException(status_code=401, detail="Sign in to host and control a Jam")
    jam = manager.get(jam_id)
    if jam.owner_id != identity.user_id:
        raise HTTPException(status_code=403, detail="Only the host can control this Jam")
    return identity.user_id


def check_request_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != get_settings().app_origin:
        raise HTTPException(status_code=403, detail="Request origin is not allowed")
