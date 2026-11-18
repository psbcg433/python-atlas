"""Security primitives: password hashing, access tokens, opaque secrets. No FastAPI here."""

import dataclasses
import hashlib
import hmac
import secrets
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from notes_api.exceptions import AuthenticationError

ALL_SCOPES = {
    "notes:read": "Read your notes.",
    "notes:write": "Create, change and delete your notes.",
    "admin": "Bulk import, export and wipe (admins only).",
}
ROLE_SCOPES = {"user": {"notes:read", "notes:write"}, "admin": set(ALL_SCOPES)}
JWT_ALGORITHM = "HS256"  # one algorithm, fixed by the server, never taken from the token


def make_password_hasher(time_cost: int = 3, memory_kib: int = 65_536) -> PasswordHash:
    """An Argon2id hasher; changing the parameters makes old hashes 'need rehashing'."""
    return PasswordHash((Argon2Hasher(time_cost=time_cost, memory_cost=memory_kib),))


def sha256_hex(value: str) -> str:
    """SHA-256 of a high-entropy secret (API keys, refresh tokens): fast lookup, safe to store."""
    return hashlib.sha256(value.encode()).hexdigest()


def same_secret(first: str, second: str) -> bool:
    """Constant-time comparison (no early exit an attacker could time)."""
    return hmac.compare_digest(first.encode(), second.encode())


def new_secret(nbytes: int = 32) -> str:
    """A URL-safe random secret from the OS's CSPRNG."""
    return secrets.token_urlsafe(nbytes)


@dataclasses.dataclass(frozen=True, slots=True)
class Principal:
    """Who is calling, with what rights; the result of authentication."""

    user_id: int
    email: str
    role: str
    scopes: frozenset[str]
    method: str  # "token", "api_key" or "cookie"
    token_id: str | None = None  # the access token's jti (for revocation at logout)
    token_expires_at: datetime | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class AccessClaims:
    """The verified claims of an access token."""

    user_id: int
    role: str
    scopes: frozenset[str]
    token_id: str
    expires_at: datetime


class TokenService:
    """Create and verify short-lived HS256 access tokens."""

    def __init__(
        self,
        secret: str,
        issuer: str,
        audience: str,
        lifetime: timedelta,
        clock: Callable[[], datetime],
    ) -> None:
        """Keep the signing secret, the expected issuer/audience and the clock."""
        self._secret = secret
        self.issuer = issuer
        self.audience = audience
        self.lifetime = lifetime
        self.clock = clock

    def create_access_token(self, user_id: int, role: str, scopes: set[str]) -> tuple[str, int]:
        """A signed token and its lifetime in seconds."""
        now = self.clock()
        claims = {
            "iss": self.issuer,
            "aud": self.audience,
            "sub": str(user_id),
            "iat": now,
            "nbf": now,
            "exp": now + self.lifetime,
            "jti": uuid.uuid4().hex,
            "role": role,
            "scope": " ".join(sorted(scopes)),
            "type": "access",
        }
        return jwt.encode(claims, self._secret, algorithm=JWT_ALGORITHM), int(
            self.lifetime.total_seconds()
        )

    def decode_access_token(self, token: str) -> AccessClaims:
        """Verify signature, algorithm, issuer, audience, time claims and type."""
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=[JWT_ALGORITHM],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "sub", "jti", "aud", "iss"]},
            )
        except jwt.ExpiredSignatureError as error:
            raise AuthenticationError("access token expired") from error
        except jwt.InvalidTokenError as error:
            raise AuthenticationError(f"invalid access token: {error}") from error
        if claims.get("type") != "access":
            raise AuthenticationError("not an access token")
        return AccessClaims(
            user_id=int(claims["sub"]),
            role=str(claims.get("role", "user")),
            scopes=frozenset(str(claims.get("scope", "")).split()),
            token_id=str(claims["jti"]),
            expires_at=datetime.fromtimestamp(claims["exp"], tz=self.clock().tzinfo),
        )
