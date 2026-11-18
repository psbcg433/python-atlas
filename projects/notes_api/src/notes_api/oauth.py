"""OpenID Connect login (Authorization Code flow with PKCE), written with httpx and PyJWT.

Authlib does this for you in production code; spelling it out shows every check:
state (CSRF on the callback), PKCE (a stolen code is useless without the verifier),
nonce (binds the ID token to this login), and the ID token's signature, issuer and audience.
"""

import base64
import hashlib
import json
import urllib.parse
from typing import Any

import httpx
import jwt
from redis.asyncio import Redis

from notes_api.core.config import Settings
from notes_api.exceptions import AuthenticationError
from notes_api.security import new_secret

STATE_TTL_SECONDS = 600
ALLOWED_ID_TOKEN_ALGORITHMS = ["RS256", "ES256", "EdDSA"]


def pkce_challenge(verifier: str) -> str:
    """S256 code challenge: base64url(SHA-256(verifier)) without padding (RFC 7636)."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


class OidcClient:
    """Talks to one OpenID provider; state lives in Redis for ten minutes."""

    def __init__(self, settings: Settings, http_client: httpx.AsyncClient, redis: Redis) -> None:
        """Keep the provider settings, the shared HTTP client and Redis."""
        self.settings = settings
        self.http = http_client
        self.redis = redis

    async def authorization_url(self) -> str:
        """Start a login: remember state, nonce and verifier; return the provider URL."""
        state, nonce, verifier = new_secret(), new_secret(), new_secret(48)
        payload = json.dumps({"nonce": nonce, "verifier": verifier})
        await self.redis.set(f"oauth-state:{state}", payload, ex=STATE_TTL_SECONDS)
        query = {
            "response_type": "code",
            "client_id": self.settings.oauth_client_id,
            "redirect_uri": self.settings.oauth_redirect_url,
            "scope": "openid email",
            "state": state,
            "nonce": nonce,
            "code_challenge": pkce_challenge(verifier),
            "code_challenge_method": "S256",
        }
        return f"{self.settings.oauth_authorize_url}?{urllib.parse.urlencode(query)}"

    async def finish(self, code: str, state: str) -> dict[str, Any]:
        """Exchange the code (with the verifier) and return the verified ID-token claims."""
        stored = await self.redis.getdel(f"oauth-state:{state}")  # one use only
        if stored is None:
            raise AuthenticationError("unknown or expired login state")
        remembered = json.loads(stored)
        secret = self.settings.oauth_client_secret
        response = await self.http.post(
            str(self.settings.oauth_token_url),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.settings.oauth_redirect_url,
                "client_id": self.settings.oauth_client_id,
                "client_secret": secret.get_secret_value() if secret else "",
                "code_verifier": remembered["verifier"],
            },
        )
        if response.status_code != 200 or "id_token" not in response.json():
            raise AuthenticationError("the identity provider refused the code")
        claims = await self.verify_id_token(response.json()["id_token"])
        if claims.get("nonce") != remembered["nonce"]:
            raise AuthenticationError("ID token nonce mismatch")
        if not claims.get("email") or claims.get("email_verified") is not True:
            raise AuthenticationError("the provider did not confirm an email address")
        return claims

    async def verify_id_token(self, id_token: str) -> dict[str, Any]:
        """Check the signature with the provider's published keys, then iss, aud and exp."""
        jwks = await self.http.get(str(self.settings.oauth_jwks_url))
        key_set = jwt.PyJWKSet.from_dict(jwks.json())
        kid = jwt.get_unverified_header(id_token).get("kid")
        keys = [key for key in key_set.keys if key.key_id == kid]
        if not keys:
            raise AuthenticationError("ID token signed with an unknown key")
        try:
            return jwt.decode(
                id_token,
                keys[0],
                algorithms=ALLOWED_ID_TOKEN_ALGORITHMS,
                audience=self.settings.oauth_client_id,
                issuer=self.settings.oauth_issuer,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
        except jwt.InvalidTokenError as error:
            raise AuthenticationError(f"invalid ID token: {error}") from error
