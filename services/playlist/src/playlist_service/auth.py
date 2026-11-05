from dataclasses import dataclass
from uuid import UUID

import jwt
from fastapi import HTTPException, Request
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError

from playlist_service.config import get_settings

COOKIE_NAME = "syncwave_session"
ISSUER = "syncwave-auth"
AUDIENCE = "syncwave"


@dataclass(frozen=True, slots=True)
class Account:
    user_id: UUID


class AuthVerifier:
    def __init__(self, jwks_url: str) -> None:
        self._client = PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=3600)

    def verify(self, token: str) -> Account:
        try:
            key = self._client.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=AUDIENCE,
                issuer=ISSUER,
                options={"require": ["sub", "exp", "iat"]},
            )
            return Account(UUID(claims["sub"]))
        except (jwt.InvalidTokenError, KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=401, detail="Sign in to continue") from error
        except PyJWKClientError as error:
            raise HTTPException(
                status_code=503, detail="Authentication service is unavailable"
            ) from error


def current_account(request: Request) -> Account:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    return request.app.state.auth_verifier.verify(token)


def check_request_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != get_settings().app_origin:
        raise HTTPException(status_code=403, detail="Request origin is not allowed")
