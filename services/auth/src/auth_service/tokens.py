import base64
import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "syncwave-auth"
AUDIENCE = "syncwave"
SESSION_SECONDS = 12 * 60 * 60


def _b64url(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class TokenSigner:
    def __init__(self, private_key_path: str) -> None:
        self.path = Path(private_key_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.private_key = self._load_or_create()
        public_der = self.private_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self.kid = hashlib.sha256(public_der).hexdigest()[:16]

    def _load_or_create(self):
        if self.path.exists():
            return serialization.load_pem_private_key(self.path.read_bytes(), password=None)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        try:
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return serialization.load_pem_private_key(self.path.read_bytes(), password=None)
        with os.fdopen(descriptor, "wb") as output:
            output.write(pem)
        return key

    def issue(self, user_id: str) -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "sub": user_id,
                "iss": ISSUER,
                "aud": AUDIENCE,
                "iat": now,
                "exp": now + timedelta(seconds=SESSION_SECONDS),
                "jti": str(uuid4()),
            },
            self.private_key,
            algorithm="RS256",
            headers={"kid": self.kid},
        )

    def jwks(self) -> dict[str, list[dict[str, str]]]:
        numbers = self.private_key.public_key().public_numbers()
        return {
            "keys": [
                {
                    "kty": "RSA",
                    "use": "sig",
                    "alg": "RS256",
                    "kid": self.kid,
                    "n": _b64url(numbers.n),
                    "e": _b64url(numbers.e),
                }
            ]
        }


def public_claims(token: str, public_key) -> dict[str, object]:
    return jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        audience=AUDIENCE,
        issuer=ISSUER,
        options={"require": ["sub", "exp", "iat"]},
    )
