"""Authentication use cases: register, log in, rotate refresh tokens, log out, API keys."""

import logging
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timedelta

from pwdlib import PasswordHash
from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from notes_api.exceptions import (
    ApiKeyNotFoundError,
    AuthenticationError,
    EmailTakenError,
    PermissionDeniedError,
)
from notes_api.models import ApiKey, RefreshToken, User
from notes_api.repositories import SqlUserRepository
from notes_api.schemas import ApiKeyCreate, TokenPair, UserCreate
from notes_api.security import (
    ROLE_SCOPES,
    Principal,
    TokenService,
    new_secret,
    same_secret,
    sha256_hex,
)

logger = logging.getLogger("notes_api.auth")
type SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
API_KEY_PREFIX = "nk_"


class AuthService:
    """Everything about credentials; the routers only translate HTTP."""

    def __init__(
        self,
        users: SqlUserRepository,
        tokens: TokenService,
        hasher: PasswordHash,
        dummy_hash: str,
        redis: Redis,
        session_factory: SessionFactory,
        refresh_lifetime: timedelta,
        admin_emails: list[str],
    ) -> None:
        """Keep the collaborators (built per request by dependencies.get_auth_service)."""
        self.users = users
        self.tokens = tokens
        self.hasher = hasher
        self.dummy_hash = dummy_hash
        self.redis = redis
        self.session_factory = session_factory
        self.refresh_lifetime = refresh_lifetime
        self.admin_emails = {email.lower() for email in admin_emails}

    def now(self) -> datetime:
        """The token service's clock (one clock for every timestamp)."""
        return self.tokens.clock()

    async def register(self, data: UserCreate) -> User:
        """Create an account; admin only for configured addresses, never from the request."""
        role = "admin" if data.email.lower() in self.admin_emails else "user"
        password_hash = self.hasher.hash(data.password)
        try:
            async with self.users.session.begin_nested():
                return await self.users.add_user(data.email, password_hash, role)
        except IntegrityError as error:
            raise EmailTakenError(f"{data.email} is already registered") from error

    async def authenticate(self, email: str, password: str) -> User:
        """The user if the password matches; upgrade the hash if its parameters are outdated."""
        user = await self.users.user_by_email(email)
        if user is None or user.password_hash is None or not user.is_active:
            self.hasher.verify(password, self.dummy_hash)  # same work, so timing reveals nothing
            logger.info("login failed for email=%s", email)
            raise AuthenticationError("incorrect email or password")
        valid, new_hash = self.hasher.verify_and_update(password, user.password_hash)
        if not valid:
            logger.info("login failed for email=%s", email)
            raise AuthenticationError("incorrect email or password")
        if new_hash is not None:  # parameters changed since this hash was made
            user.password_hash = new_hash
        return user

    def grant_scopes(self, role: str, requested: list[str]) -> set[str]:
        """The scopes a token gets: what was asked for (default: everything the role allows)."""
        allowed = ROLE_SCOPES.get(role, set())
        wanted = set(requested) or allowed
        if not wanted <= allowed:
            raise PermissionDeniedError(
                f"scopes not allowed for this account: {sorted(wanted - allowed)}"
            )
        return wanted

    async def issue_tokens(
        self, user: User, scopes: set[str], family_id: str | None = None
    ) -> TokenPair:
        """A new access token and a new refresh token (a new family unless rotating)."""
        access_token, expires_in = self.tokens.create_access_token(user.id, user.role, scopes)
        raw_refresh = new_secret()
        await self.users.add_refresh_token(
            RefreshToken(
                token_hash=sha256_hex(raw_refresh),
                family_id=family_id or uuid.uuid4().hex,
                user_id=user.id,
                scopes=" ".join(sorted(scopes)),
                expires_at=self.now() + self.refresh_lifetime,
            )
        )
        return TokenPair(
            access_token=access_token,
            refresh_token=raw_refresh,
            expires_in=expires_in,
            scope=" ".join(sorted(scopes)),
        )

    async def oidc_login(self, claims: dict[str, object]) -> TokenPair:
        """Sign in with verified ID-token claims: known subject, else link by email, else create."""
        subject = f"{claims['iss']}|{claims['sub']}"
        email = str(claims["email"]).lower()
        user = await self.users.user_by_oidc_subject(subject)
        if user is None:
            user = await self.users.user_by_email(email)
            if user is not None:
                user.oidc_subject = subject  # the provider verified this address
            else:
                role = "admin" if email in self.admin_emails else "user"
                user = await self.users.add_user(email, None, role, oidc_subject=subject)
        if not user.is_active:
            raise AuthenticationError("account disabled")
        return await self.issue_tokens(user, ROLE_SCOPES.get(user.role, set()))

    async def revoke_family_now(self, family_id: str) -> None:
        """Revoke a token family in its own transaction, so a following 401 cannot undo it."""
        async with self.session_factory() as side_session, side_session.begin():
            await SqlUserRepository(side_session).revoke_family(family_id, self.now())

    async def refresh(self, raw_refresh: str) -> TokenPair:
        """Rotate: a refresh token works once. Presenting a used one revokes the whole family."""
        token = await self.users.refresh_token_by_hash(sha256_hex(raw_refresh))
        if token is None:
            raise AuthenticationError("unknown refresh token")
        if token.used_at is not None or token.revoked_at is not None:
            await self.revoke_family_now(token.family_id)
            logger.warning("refresh token reuse detected for user_id=%s", token.user_id)
            raise AuthenticationError("refresh token reuse detected; please log in again")
        if token.expires_at <= self.now():
            raise AuthenticationError("refresh token expired")
        user = await self.users.user_by_id(token.user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("account disabled")
        token.used_at = self.now()
        scopes = set(token.scopes.split()) & ROLE_SCOPES.get(user.role, set())
        return await self.issue_tokens(user, scopes, family_id=token.family_id)

    async def logout(self, raw_refresh: str, principal: Principal | None) -> None:
        """Revoke the login's refresh tokens; deny the current access token until it expires."""
        token = await self.users.refresh_token_by_hash(sha256_hex(raw_refresh))
        if token is not None:
            await self.users.revoke_family(token.family_id, self.now())
        if principal is not None:
            await self.deny_access_token(principal)

    async def deny_access_token(self, principal: Principal) -> None:
        """Put the access token's jti on the Redis denylist until the token would expire."""
        if principal.token_id and principal.token_expires_at:
            seconds_left = int((principal.token_expires_at - self.now()).total_seconds()) + 1
            if seconds_left > 0:
                await self.redis.set(f"revoked-jti:{principal.token_id}", "1", ex=seconds_left)

    async def principal_from_access_token(self, raw_token: str) -> Principal:
        """Verify an access token, check the denylist and the account."""
        claims = self.tokens.decode_access_token(raw_token)
        if await self.redis.exists(f"revoked-jti:{claims.token_id}"):
            raise AuthenticationError("access token revoked")
        user = await self.users.user_by_id(claims.user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("account disabled")
        scopes = claims.scopes & ROLE_SCOPES.get(user.role, set())  # a demoted user loses rights
        return Principal(
            user.id,
            user.email,
            user.role,
            frozenset(scopes),
            "token",
            claims.token_id,
            claims.expires_at,
        )

    async def principal_from_api_key(self, raw_key: str) -> Principal:
        """Look a key up by its hash; keys carry their own scopes."""
        key = await self.users.api_key_by_hash(sha256_hex(raw_key))
        if key is None or not same_secret(key.key_hash, sha256_hex(raw_key)):
            raise AuthenticationError("invalid API key")
        user = await self.users.user_by_id(key.user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("account disabled")
        key.last_used_at = self.now()
        scopes = set(key.scopes.split()) & ROLE_SCOPES.get(user.role, set())
        return Principal(user.id, user.email, user.role, frozenset(scopes), "api_key")

    async def create_api_key(self, principal: Principal, data: ApiKeyCreate) -> tuple[ApiKey, str]:
        """A new key (returned once, in full) limited to scopes the account has."""
        scopes = self.grant_scopes(principal.role, list(data.scopes))
        secret = new_secret(24)
        raw_key = f"{API_KEY_PREFIX}{secret}"
        key = ApiKey(
            user_id=principal.user_id,
            name=data.name,
            prefix=raw_key[:10],
            key_hash=sha256_hex(raw_key),
            scopes=" ".join(sorted(scopes)),
        )
        return await self.users.add_api_key(key), raw_key

    async def revoke_api_key(self, principal: Principal, key_id: int) -> None:
        """Revoke one of the caller's keys (someone else's key is 'not found')."""
        for key in await self.users.api_keys_of(principal.user_id):
            if key.id == key_id:
                key.revoked_at = key.revoked_at or self.now()
                return
        raise ApiKeyNotFoundError(key_id)
