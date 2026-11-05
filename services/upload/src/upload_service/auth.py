"""Account-token verification for protected upload operations."""

from dataclasses import dataclass
from uuid import UUID

import jwt
from fastapi import HTTPException, Request
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError

ACCOUNT_COOKIE = "syncwave_session"
ACCOUNT_ISSUER = "syncwave-auth"
ACCOUNT_AUDIENCE = "syncwave"


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
        except (jwt.InvalidTokenError, KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=401, detail="Sign in to upload music") from exc
        except PyJWKClientError as exc:
            raise HTTPException(
                status_code=503, detail="Authentication service is unavailable"
            ) from exc


def require_account(request: Request) -> AccountIdentity:
    """Return the signed-in account or reject the protected request."""
    token = request.cookies.get(ACCOUNT_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Sign in to upload music")
    return request.app.state.auth_verifier.account(token)
