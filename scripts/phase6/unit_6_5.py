"""Unit 6.5 — Authentication, Authorization and Security (with Lab 6.5 and Notes API v4)."""

from nbformat import NotebookNode
from unit_6_1 import SERVER_HELPERS_SOURCE, UNIT_SETUP_SOURCE_2  # one copy of the helpers
from unit_6_2 import NOTES_HELPERS_SOURCE
from unit_6_3 import NOTES_PROJECT_HELPERS_SOURCE, PRUNE_HELPER_SOURCE
from unit_6_4 import DATABASE_HELPERS_SOURCE

from nb_builder import code, md, predict_cells, writefile_cells

UNIT_SETUP_SOURCE = r"""
import ast
import asyncio
import atexit
import base64
import contextlib
import dataclasses
import hashlib
import hmac
import importlib
import importlib.util
import inspect
import io
import ipaddress
import json
import logging
import math  # noqa: F401  (for Lab 6.5, exercise 5)
import os
import re
import secrets
import shlex
import shutil
import socket
import sqlite3
import subprocess
import sys
import sysconfig
import textwrap
import time
import urllib.parse
import urllib.request
from collections.abc import AsyncIterator, Callable, Iterable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Annotated, Any

import alembic
import asyncpg
import fakeredis
import fastapi
import httpx
import jwt
import pwdlib
import pydantic
import pydantic_settings
import redis.asyncio as redis_asyncio
import respx
import sqlalchemy as sa
import starlette
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import (
    APIKeyHeader,
    HTTPAuthorizationCredentials,
    HTTPBearer,
    OAuth2PasswordBearer,
    OAuth2PasswordRequestForm,
    SecurityScopes,
)
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, ValidationError
from sqlalchemy import event, text
from sqlalchemy.dialects import sqlite as sqlite_dialect

REPO_ROOT = find_repo_root()
scratch_dir = REPO_ROOT / "notebooks" / "_scratch"  # git-ignored
PHASE6_DIR = scratch_dir / "phase6"
PHASE6_DIR.mkdir(parents=True, exist_ok=True)
os.chdir(REPO_ROOT / "notebooks")  # %%writefile cells use paths relative to notebooks/
if str(PHASE6_DIR) not in sys.path:
    sys.path.insert(0, str(PHASE6_DIR))
CHILD_ENV = {**os.environ, "PYTHON_COLORS": "0", "PYTHONUNBUFFERED": "1", "NO_COLOR": "1"}
CHILD_ENV.pop("FORCE_COLOR", None)
HAS_NODE = shutil.which("node") is not None
HAS_UV = shutil.which("uv") is not None

NOTES_API_DIR = REPO_ROOT / "projects" / "notes_api"  # the Notes API's own uv project
NOTES_SRC = NOTES_API_DIR / "src"
for folder in (NOTES_SRC / "notes_api", NOTES_API_DIR / "tests"):
    folder.mkdir(parents=True, exist_ok=True)  # %%writefile does not create folders
if str(NOTES_SRC) not in sys.path:
    sys.path.insert(0, str(NOTES_SRC))
"""

REDIS_HELPERS_SOURCE = r'''
redis_container: Any = None  # one Redis testcontainer per unit, started on first use


def stop_shared_redis() -> None:
    """Stop and remove the unit's Redis container (also registered with atexit)."""
    global redis_container
    if redis_container is not None:
        with contextlib.suppress(Exception):
            redis_container.stop()
        redis_container = None


def start_shared_redis() -> str | None:
    """Start the unit's Redis container once and return its URL (None without Docker)."""
    global redis_container
    if not HAS_DOCKER:
        return None
    if redis_container is None:
        from testcontainers.community.redis import RedisContainer

        redis_container = RedisContainer(REDIS_IMAGE).start()
        atexit.register(stop_shared_redis)  # testcontainers' Ryuk reaper only covers crashes
    host = redis_container.get_container_host_ip()
    return f"redis://{host}:{redis_container.get_exposed_port(6379)}/0"


def make_redis(url: str | None) -> Any:
    """A text Redis client on url, or an in-memory fakeredis client when url is None."""
    if url is None:
        return fakeredis.FakeAsyncRedis(decode_responses=True)
    return redis_asyncio.from_url(url, decode_responses=True)


def fast_hasher() -> PasswordHash:
    """Argon2id with deliberately cheap parameters, for demos that hash many passwords."""
    return PasswordHash((Argon2Hasher(time_cost=1, memory_cost=64, parallelism=1),))


print(f"{jwt.__version__=}  {pwdlib.__version__=}  {fakeredis.__version__=}  {respx.__version__=}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 6.5 — Authentication, Authorization and Security

            **Objectives**

            - Tell authentication (*who are you?*) from authorization (*may you do this?*),
              choose between server-side sessions and tokens, and threat-model an API.
            - Store passwords with Argon2id through `pwdlib`, rehash old hashes, and compare
              secrets in constant time.
            - Read, sign and verify JWTs with PyJWT (HS256, RS256, EdDSA) and recognise
              algorithm-confusion attacks.
            - Run a token lifecycle: short access tokens, rotating refresh tokens with reuse
              detection, revocation and logout.
            - Use FastAPI's security classes (`OAuth2PasswordBearer`, the login form,
              `HTTPBearer`, `APIKeyHeader`) and current-user dependencies.
            - Authorize with roles, OAuth2 scopes (`Security`, `SecurityScopes`) and ownership
              checks, and know when to answer 404 instead of 403.
            - Protect browsers: cookie flags, CSRF, CORS.
            - Log in with a third party: OAuth 2.0 Authorization Code + PKCE and OpenID Connect
              (against a mocked provider).
            - Issue hashed API keys and rate-limit with Redis (429 + `Retry-After`).
            - Map every OWASP API Security Top 10 (2023) risk to a FastAPI mitigation.
            - Prevent injection, send security headers, manage secrets, scan with `bandit` and
              `pip-audit`, and redact logs.
            - Move the **Notes API to v4**: users, ownership, JWT + refresh tokens, scopes,
              API keys, OIDC login, rate limits, CSRF-protected pages, security headers.

            **JS bridge**

            | JavaScript / TypeScript | Python | The difference that bites |
            | --- | --- | --- |
            | Passport strategies (`passport-local`, `passport-jwt`) | FastAPI security dependencies (`OAuth2PasswordBearer` + your `get_current_user`) | the security class only **extracts** the credential; verifying it is your dependency's job |
            | NestJS guards (`@UseGuards(RolesGuard)`) | `Depends(require_admin)` on a route or router, `Security(..., scopes=[...])` | scopes **accumulate** down the dependency tree and show up in OpenAPI |
            | `express-session` | a signed cookie or a server-side session store | FastAPI ships no session store; Starlette's `SessionMiddleware` keeps data **in** the signed cookie |
            | `jsonwebtoken` (`jwt.sign`, `jwt.verify`) | PyJWT (`jwt.encode`, `jwt.decode(..., algorithms=[...])`) | `algorithms` is **required** in PyJWT, which closes the `alg` confusion hole by default |
            | `bcrypt` / `argon2` npm packages | `pwdlib` (Argon2id) | `verify_and_update` also tells you when to **rehash** |
            | `cors` middleware, `csurf`, `helmet` | `CORSMiddleware`, a CSRF dependency, a security-headers middleware | no `helmet` equivalent built in: you write a tiny ASGI middleware |
            | `express-rate-limit` + `rate-limit-redis` | a Redis limiter dependency raising 429 | same algorithms (fixed / sliding window, token bucket) |
            | Jest + Supertest auth tests | pytest + `TestClient` with headers / cookies | `dependency_overrides` can swap the whole auth graph in tests |

            Run the setup cells first. Part 1: imports (pwdlib, PyJWT, cryptography, fakeredis,
            respx) and the project folders:
            """
        ),
        code(UNIT_SETUP_SOURCE),
        md("Part 2: helpers shared with Units 6.1–6.4:"),
        code(UNIT_SETUP_SOURCE_2),
        md(
            """
            Part 3: the server, Notes API and database helpers from Units 6.1–6.4, plus this
            unit's Redis helpers: `start_shared_redis()` starts **one** Redis testcontainer for
            the unit (stopped in the *Clean up* cell and by an `atexit` hook),
            `make_redis(url)` returns a client for it or an in-memory fakeredis when Docker is
            missing, and `fast_hasher()` is Argon2id with cheap parameters for demos:
            """
        ),
        code(
            SERVER_HELPERS_SOURCE
            + "\n"
            + NOTES_HELPERS_SOURCE
            + "\n"
            + PRUNE_HELPER_SOURCE
            + "\n"
            + NOTES_PROJECT_HELPERS_SOURCE
            + "\n"
            + DATABASE_HELPERS_SOURCE
            + "\n"
            + REDIS_HELPERS_SOURCE
        ),
    ]


def _authn_cells() -> list[NotebookNode]:
    """6.5.1 AuthN vs AuthZ."""
    return [
        md(
            """
            ### 6.5.1 AuthN vs AuthZ

            | | Authentication (AuthN) | Authorization (AuthZ) |
            | --- | --- | --- |
            | Question | *Who is calling?* | *May this caller do this, to this object?* |
            | Input | a credential: password, token, API key, cookie, client certificate | the authenticated identity + the request (route, object, fields) |
            | Failure | **401 Unauthorized** (+ `WWW-Authenticate`) | **403 Forbidden**, or **404** to hide that the object exists |
            | Where in FastAPI | a dependency that turns a credential into a principal | dependencies on routes/routers, and filters in queries |

            **Sessions vs tokens.** After a login the server must recognise the client on the
            next request. Two designs:

            | | Server-side session | Self-contained token (JWT) |
            | --- | --- | --- |
            | Client holds | a random session id (usually a cookie) | the signed claims themselves |
            | Server checks | a lookup in a session store (Redis, database) | the signature and the claims; no lookup |
            | Logout / revoke | delete the session: immediate | wait for expiry, or keep a **denylist** (a lookup again) |
            | Scaling | every instance needs the store | any instance with the key can verify |
            | Typical use | browser apps (cookie) | APIs, mobile apps, service-to-service |

            Most production systems mix them: short-lived JWT access tokens (no lookup on the
            hot path) plus **refresh tokens stored server-side** (revocable). The Notes API v4
            does exactly that. Both designs, side by side, in a few lines:
            """
        ),
        code(
            r'''
            SESSION_STORE: dict[str, dict[str, object]] = {}  # in production: Redis with a TTL
            SIGNING_KEY = secrets.token_bytes(32)


            def create_session(user_id: int) -> str:
                """Server-side session: a random id that means nothing without the store."""
                session_id = secrets.token_urlsafe(32)
                SESSION_STORE[session_id] = {"user_id": user_id, "created": time.time()}
                return session_id


            def create_signed_token(user_id: int) -> str:
                """Self-contained token: the claims plus an HMAC; verifiable without any lookup."""
                claims = base64.urlsafe_b64encode(json.dumps({"sub": user_id}).encode()).decode()
                signature = hmac.new(SIGNING_KEY, claims.encode(), hashlib.sha256).hexdigest()
                return f"{claims}.{signature}"


            def read_signed_token(token: str) -> dict[str, object] | None:
                """The claims if the signature matches (constant-time comparison), else None."""
                claims, _, signature = token.partition(".")
                expected = hmac.new(SIGNING_KEY, claims.encode(), hashlib.sha256).hexdigest()
                if not hmac.compare_digest(signature, expected):
                    return None
                return json.loads(base64.urlsafe_b64decode(claims))


            session_id, signed_token = create_session(7), create_signed_token(7)
            print("session lookup:", SESSION_STORE.get(session_id, {}).get("user_id"))
            print("token check   :", read_signed_token(signed_token))
            SESSION_STORE.pop(session_id)  # logout = delete the row
            print("after logout  :", SESSION_STORE.get(session_id), read_signed_token(signed_token))
            '''
        ),
        md(
            """
            After "logout" the session is gone, but the signed token **still verifies**: nothing
            on the server remembers it. That is why token designs need short lifetimes and a
            denylist (6.5.4).

            **Threat modelling** means listing what you protect, who attacks it, and where
            data crosses a trust boundary, *before* writing defences. STRIDE is a handy
            checklist; for the Notes API:

            | STRIDE threat | Example against the Notes API | Mitigation (section) |
            | --- | --- | --- |
            | **S**poofing | stolen password or token used by someone else | Argon2id, short access tokens, refresh rotation (6.5.2–6.5.4) |
            | **T**ampering | edit the `role` claim inside a token | signed JWT with a fixed algorithm (6.5.3) |
            | **R**epudiation | "I never deleted that note" | request ids in logs, audit events (6.7) |
            | **I**nformation disclosure | read another user's note by id; tokens in logs | ownership checks, 404 (6.5.6), log redaction (6.5.11) |
            | **D**enial of service | password-guessing floods, huge uploads | rate limits (6.5.9), size limits (6.3) |
            | **E**levation of privilege | a user calls an admin route or sends `"role": "admin"` | role + scope checks (6.5.6), strict schemas (6.5.10) |

            ```mermaid
            flowchart LR
                browser[Browser / client] -- "TLS boundary" --> api[Notes API]
                api -- "trusted network" --> db[(PostgreSQL)]
                api --> cache[(Redis)]
                api -- "outbound: SSRF risk" --> web[Third-party sites]
                idp[Identity provider] -. "OIDC redirect" .-> browser
            ```

            <details><summary>ASCII version</summary>

            ```text
            [client] ==TLS==> [Notes API] --> (PostgreSQL)
                                   |-------> (Redis)
                                   '--outbound--> [web sites]   (SSRF risk)
            [identity provider] <-redirect-> [client]
            ```

            </details>

            A practical first step is an **attack-surface inventory**: every route, and
            whether anything checks the caller. FastAPI keeps each route's dependency tree in
            `route.dependant`, so the inventory can be computed (under the hood: the same
            `Dependant` objects FastAPI walks for every request):
            """
        ),
        code(
            r'''
            def require_token(
                token: Annotated[str | None, Depends(APIKeyHeader(name="X-Token", auto_error=False))],
            ) -> str:
                """Demo credential check."""
                if token != "demo":
                    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
                return token


            threat_app = FastAPI()


            @threat_app.get("/health")
            def threat_health() -> dict[str, str]:
                """Public on purpose."""
                return {"status": "ok"}


            @threat_app.get("/reports/{report_id}")
            def threat_report(report_id: int) -> dict[str, int]:
                """Forgot the check: anyone can read any report."""
                return {"id": report_id}


            @threat_app.delete("/reports/{report_id}", dependencies=[Depends(require_token)])
            def threat_delete(report_id: int) -> dict[str, int]:
                """Protected."""
                return {"deleted": report_id}
            '''
        ),
        md("`attack_surface(app)` walks each route's dependency tree looking for the check:"),
        code(
            r'''
            def dependency_names(dependant: Any) -> set[str]:
                """Names of every callable in a route's dependency tree (recursively)."""
                names = set()
                for sub_dependant in dependant.dependencies:
                    if sub_dependant.call is not None:
                        names.add(getattr(sub_dependant.call, "__name__", type(sub_dependant.call).__name__))
                    names |= dependency_names(sub_dependant)
                return names


            def attack_surface(app: FastAPI, guards: set[str]) -> list[tuple[str, str, bool]]:
                """(methods, path, protected?) for every API route."""
                rows = []
                for route in app.routes:
                    if hasattr(route, "dependant") and route.path not in ("/openapi.json",):
                        protected = bool(dependency_names(route.dependant) & guards)
                        rows.append((",".join(sorted(route.methods)), route.path, protected))
                return rows


            for methods, path, protected in attack_surface(threat_app, {"require_token"}):
                print(f"{methods:7} {path:22} {'protected' if protected else 'OPEN'}")
            '''
        ),
        md(
            """
            `GET /reports/{report_id}` is open: exactly the kind of gap a threat model should
            catch. (The Notes API v4 makes every notes route depend on the principal, and
            `test_bola.py` checks it.)
            """
        ),
    ]


def _password_cells() -> list[NotebookNode]:
    """6.5.2 Password storage."""
    return [
        md(
            """
            ### 6.5.2 Password storage

            Never store passwords, and never store a plain fast hash of them: a stolen
            database plus a GPU tries billions of SHA-256 guesses per second. Store the output
            of a **slow, salted, memory-hard** password hash:

            | Algorithm | Status | Notes |
            | --- | --- | --- |
            | MD5 / SHA-1 / SHA-256 alone | **never** for passwords | fast by design |
            | PBKDF2-HMAC-SHA256 | acceptable (FIPS) | CPU-hard only; needs ≥ 600 000 iterations (OWASP 2023) |
            | bcrypt | acceptable | 72-byte input limit; CPU-hard |
            | scrypt | good | memory-hard |
            | **Argon2id** | **recommended** (RFC 9106, OWASP) | memory-hard; parameters: memory, iterations (time cost), parallelism |

            First, why speed matters: count how many SHA-256 guesses one CPU core makes in
            0.2 s, versus Argon2id with `pwdlib`'s recommended parameters:
            """
        ),
        code(
            r'''
            def guesses_per_second(hash_one: Callable[[bytes], object], budget: float = 0.2) -> float:
                """How many hashes of different inputs fit in budget seconds, per second."""
                count, started = 0, time.perf_counter()
                while time.perf_counter() - started < budget:
                    hash_one(b"guess-%d" % count)
                    count += 1
                return count / (time.perf_counter() - started)


            recommended = PasswordHash.recommended()  # Argon2id, 64 MiB, t=3, p=4
            fast_rate = guesses_per_second(lambda guess: hashlib.sha256(guess).digest())
            slow_rate = guesses_per_second(lambda guess: recommended.hash(guess.decode()), budget=0.5)
            print(f"SHA-256 : {fast_rate:12,.0f} guesses/s on one core")
            print(f"Argon2id: {slow_rate:12,.1f} guesses/s on one core")
            print(f"ratio   : ~{fast_rate / slow_rate:,.0f}x slower for the attacker (and 64 MiB each)")
            '''
        ),
        md(
            """
            The numbers vary by machine; the ratio is the point. A login costs the server a
            few tens of milliseconds once; an attacker pays that for **every guess**.

            **`pwdlib`** (from the FastAPI author) wraps `argon2-cffi`. `PasswordHash` holds a
            tuple of hashers: the **first** one hashes new passwords, all of them can verify.
            The hash string records the algorithm, version, parameters, the random **salt**
            and the digest, so it is self-describing:
            """
        ),
        code(
            r"""
            hasher = PasswordHash((Argon2Hasher(time_cost=2, memory_cost=19_456, parallelism=1),))
            first_hash = hasher.hash("correct horse battery staple")
            second_hash = hasher.hash("correct horse battery staple")
            print(first_hash)
            _, algorithm, version, parameters, salt, digest = first_hash.split("$")
            print(f"{algorithm=} {version=} {parameters=}")
            print(f"salt={salt!r} ({len(base64.b64decode(salt + '=='))} bytes), digest={len(digest)} chars")
            print("same password, same hash?", first_hash == second_hash)  # different salts
            print("verify right:", hasher.verify("correct horse battery staple", first_hash))
            print("verify wrong:", hasher.verify("Correct horse battery staple", first_hash))
            """
        ),
        md(
            """
            Same password, different hashes: the salt is random, so identical passwords never
            look identical in the database and precomputed (rainbow) tables are useless.
            `m=19456,t=2,p=1` is the OWASP minimum for Argon2id; `PasswordHash.recommended()`
            uses 64 MiB, `t=3`, `p=4`.

            **Rehashing.** Parameters should grow with hardware. You cannot rehash stored hashes
            (you do not know the passwords), but at login you briefly have the plain password:
            `verify_and_update` verifies and, when the stored hash used different parameters or
            another algorithm, returns a new hash to save:
            """
        ),
        code(
            r"""
            legacy_hasher = PasswordHash((Argon2Hasher(time_cost=1, memory_cost=8_192, parallelism=1),))
            stored_hash = legacy_hasher.hash("tea-and-biscuits-42")

            upgraded_hasher = PasswordHash(
                (Argon2Hasher(time_cost=2, memory_cost=19_456, parallelism=1),)  # new default
            )
            valid, new_hash = upgraded_hasher.verify_and_update("tea-and-biscuits-42", stored_hash)
            print(f"{valid=}  needs update: {new_hash is not None}")
            print("old parameters:", stored_hash.split("$")[3], "-> new:", new_hash.split("$")[3])
            valid_again, newer_hash = upgraded_hasher.verify_and_update("tea-and-biscuits-42", new_hash)
            print(f"{valid_again=}  needs update again: {newer_hash is not None}")
            print("wrong password:", upgraded_hasher.verify_and_update("guess", stored_hash))
            """
        ),
        md(
            """
            The Notes API's `AuthService.authenticate` does this on every successful login.
            `pwdlib` can also verify bcrypt hashes during a migration from another system (add
            a `BcryptHasher` **after** the Argon2 one); bcrypt support needs the optional
            `bcrypt` package:
            """
        ),
        code(
            r"""
            if importlib.util.find_spec("bcrypt"):
                from pwdlib.hashers.bcrypt import BcryptHasher

                migrating = PasswordHash((Argon2Hasher(), BcryptHasher()))
                old_bcrypt_hash = BcryptHasher().hash("from-the-old-system")
                print(migrating.verify_and_update("from-the-old-system", old_bcrypt_hash)[1][:10])
            else:
                print("SKIP bcrypt migration demo: the optional bcrypt package is not installed")
                print(
                    "pattern: PasswordHash((Argon2Hasher(), BcryptHasher()))"
                    " verifies both, rehashes to Argon2id"
                )
            """
        ),
        md(
            """
            **Constant-time comparison.** `==` on strings stops at the first different
            character, so the time it takes leaks how much of a secret an attacker guessed
            right. For any secret (tokens, API keys, HMACs) use `hmac.compare_digest`
            (`secrets.compare_digest` is the same function), which always looks at every byte.
            The leak is easiest to see with a deliberately slow, character-by-character
            comparison:
            """
        ),
        code(
            r'''
            SECRET_TOKEN = "f3a9c2e1d4b7a6c5e8f9a0b1c2d3e4f5"


            def leaky_equals(left: str, right: str) -> bool:
                """Like ==: returns at the first mismatch (slowed down so the effect is visible)."""
                for left_char, right_char in zip(left, right, strict=True):
                    time.sleep(0.0002)
                    if left_char != right_char:
                        return False
                return True


            def time_guess(compare: Callable[[str, str], bool], guess: str) -> float:
                """Milliseconds for one comparison."""
                started = time.perf_counter()
                compare(SECRET_TOKEN, guess)
                return (time.perf_counter() - started) * 1000


            wrong_first = "0" * 32
            right_half = SECRET_TOKEN[:16] + "0" * 16
            print(
                f"leaky : wrong first char {time_guess(leaky_equals, wrong_first):5.2f} ms, "
                f"first 16 right {time_guess(leaky_equals, right_half):5.2f} ms"
            )
            safe_compare = hmac.compare_digest
            print(
                f"compare_digest: {time_guess(safe_compare, wrong_first):.4f} ms vs "
                f"{time_guess(safe_compare, right_half):.4f} ms (no useful difference)"
            )
            '''
        ),
        md(
            """
            A related leak: answering faster for unknown e-mails (no hash to verify) tells an
            attacker which accounts exist. The Notes API verifies against a **dummy hash**
            when the e-mail is unknown, so both paths cost one Argon2 verification:
            """
        ),
        code(
            r'''
            demo_hasher = PasswordHash((Argon2Hasher(time_cost=2, memory_cost=19_456, parallelism=1),))
            DEMO_USERS = {"asha@example.com": demo_hasher.hash("a-long-passphrase")}
            DUMMY_HASH = demo_hasher.hash(secrets.token_urlsafe(16))  # computed once at startup


            def login_timing(email: str, *, equalize: bool) -> float:
                """Milliseconds to reject a wrong password for email."""
                started = time.perf_counter()
                stored = DEMO_USERS.get(email)
                if stored is not None:
                    demo_hasher.verify("wrong", stored)
                elif equalize:
                    demo_hasher.verify("wrong", DUMMY_HASH)  # same work for unknown e-mails
                return (time.perf_counter() - started) * 1000


            for equalize in (False, True):
                known = login_timing("asha@example.com", equalize=equalize)
                unknown = login_timing("nobody@example.com", equalize=equalize)
                print(f"{equalize=!s:5}  known e-mail {known:6.2f} ms   unknown e-mail {unknown:6.2f} ms")
            '''
        ),
    ]


def _jwt_cells() -> list[NotebookNode]:
    """6.5.3 JWT."""
    return [
        md(
            """
            ### 6.5.3 JWT

            A JSON Web Token (RFC 7519) is three base64url parts joined by dots:
            `header.payload.signature`. The header names the algorithm (`alg`) and often a key
            id (`kid`); the payload holds **claims**; the signature covers the first two parts.
            A JWT is **signed, not encrypted**: anyone can read the claims.

            | Registered claim | Meaning | PyJWT checks it when |
            | --- | --- | --- |
            | `iss` | issuer | you pass `issuer=` |
            | `sub` | subject (the user id, a **string**) | you pass `subject=` |
            | `aud` | audience (who may accept it) | always if present: you must pass `audience=` |
            | `exp` | expiry (Unix time) | always if present |
            | `nbf` | not before | always if present |
            | `iat` | issued at | always if present (must not be in the future) |
            | `jti` | unique token id (for denylists) | never (it is for you) |

            Build one with PyJWT, then take it apart by hand:
            """
        ),
        code(
            r'''
            JWT_SECRET = secrets.token_urlsafe(32)  # generated now; never a literal in code
            issued_at = datetime.now(UTC)
            demo_token = jwt.encode(
                {
                    "iss": "notes-api",
                    "sub": "42",
                    "aud": "notes-api",
                    "iat": issued_at,
                    "exp": issued_at + timedelta(minutes=15),
                    "jti": secrets.token_hex(8),
                    "scope": "notes:read notes:write",
                },
                JWT_SECRET,
                algorithm="HS256",
            )


            def b64url_json(part: str) -> dict[str, object]:
                """Decode one base64url JWT part (padding restored) as JSON."""
                return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


            header_part, payload_part, signature_part = demo_token.split(".")
            print("header :", b64url_json(header_part))
            print("payload:", b64url_json(payload_part))
            print("signature bytes:", len(base64.urlsafe_b64decode(signature_part + "==")))
            '''
        ),
        md(
            """
            `jwt.decode` verifies the signature **and** the claims. `algorithms` is a required
            allow-list (never derived from the token); `audience` and `issuer` must match;
            `leeway` tolerates small clock differences; `options={"require": [...]}` refuses
            tokens without the claims you depend on. Each failure is its own exception, all
            subclasses of `jwt.InvalidTokenError`:
            """
        ),
        code(
            r'''
            def try_decode(token: str, **options: Any) -> str:
                """Decode with sane defaults (overridable); return the claims' sub or the error."""
                arguments = {
                    "key": JWT_SECRET,
                    "algorithms": ["HS256"],
                    "audience": "notes-api",
                    "issuer": "notes-api",
                }
                try:
                    return "ok, sub=" + jwt.decode(token, **(arguments | options))["sub"]
                except jwt.InvalidTokenError as error:
                    return f"{type(error).__name__}: {error}"


            def make_token(**claims: Any) -> str:
                """An HS256 token with default claims, overridden by claims."""
                now = datetime.now(UTC)
                defaults = {
                    "iss": "notes-api",
                    "aud": "notes-api",
                    "sub": "42",
                    "iat": now,
                    "exp": now + timedelta(minutes=5),
                }
                return jwt.encode(defaults | claims, JWT_SECRET, algorithm="HS256")


            now = datetime.now(UTC)
            print("valid        ", try_decode(make_token()))
            print("expired      ", try_decode(make_token(exp=now - timedelta(seconds=10))))
            print("leeway 30 s  ", try_decode(make_token(exp=now - timedelta(seconds=10)), leeway=30))
            print("not yet valid", try_decode(make_token(nbf=now + timedelta(minutes=1))))
            print("wrong aud    ", try_decode(make_token(aud="billing-api")))
            print("wrong iss    ", try_decode(make_token(iss="evil.example")))
            print("wrong secret ", try_decode(make_token(), key="another-secret-of-32-bytes-or-more!!"))
            print("missing jti  ", try_decode(make_token(), options={"require": ["exp", "jti"]}))
            '''
        ),
        md(
            """
            **HS256 vs RS256 vs EdDSA**

            | | HS256 (HMAC-SHA256) | RS256 (RSA + SHA-256) | EdDSA (Ed25519) |
            | --- | --- | --- | --- |
            | Keys | one shared secret | private key signs, public key verifies | private key signs, public key verifies |
            | Who can verify | only holders of the secret (who could also **sign**) | anyone with the public key | anyone with the public key |
            | Size / speed | tiny, fastest | 256-byte signatures, slow signing | 64-byte signatures, fast |
            | Use when | one service issues and verifies (the Notes API) | identity providers, many verifiers (JWKS) | new systems that need public verification |

            Asymmetric keys are published as a **JWK Set** (JSON Web Key Set); the token's
            `kid` header picks the key. Here an RSA key signs, and a verifier that only has
            the public JWKS checks it (PyJWT's `PyJWKSet`), as the Notes API does for OIDC ID
            tokens:
            """
        ),
        code(
            r"""
            rsa_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(rsa_private_key.public_key()))
            public_jwk |= {"kid": "demo-2026", "use": "sig", "alg": "RS256"}
            published_jwks = {"keys": [public_jwk]}  # what GET /.well-known/jwks.json returns

            rs256_token = jwt.encode(
                {"sub": "42", "aud": "notes-api", "exp": datetime.now(UTC) + timedelta(minutes=5)},
                rsa_private_key,
                algorithm="RS256",
                headers={"kid": "demo-2026"},
            )
            unverified_header = jwt.get_unverified_header(rs256_token)  # only to pick the key
            signing_key = jwt.PyJWKSet.from_dict(published_jwks)[unverified_header["kid"]]
            claims = jwt.decode(rs256_token, signing_key, algorithms=["RS256"], audience="notes-api")
            print(f"{unverified_header=}")
            print(f"{claims['sub']=}  public key fields: {sorted(public_jwk)}")
            print("token length:", len(rs256_token), "(HS256 was", len(demo_token), ")")
            """
        ),
        md("EdDSA with an Ed25519 key: same API, much shorter signatures:"),
        code(
            r"""
            ed_private_key = ed25519.Ed25519PrivateKey.generate()
            ed_token = jwt.encode({"sub": "42"}, ed_private_key, algorithm="EdDSA")
            ed_public_pem = ed_private_key.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            print(jwt.get_unverified_header(ed_token))
            print(jwt.decode(ed_token, ed_public_pem, algorithms=["EdDSA"]))
            print("signature bytes:", len(base64.urlsafe_b64decode(ed_token.split(".")[2] + "==")))
            """
        ),
        md(
            """
            **Algorithm-confusion attacks.** The token's header says which algorithm was used,
            and a verifier that *believes* it can be fooled twice:

            1. **`alg: none`**: an unsigned token. A verifier that dispatches on the header
               accepts any claims.
            2. **RS256 → HS256**: the attacker signs with HMAC, using the server's **public**
               RSA key (which is public!) as the HMAC secret. A verifier that calls
               `verify(token, public_key)` with whatever `alg` the header names checks an HMAC
               with that same public key, and it matches.

            A naive verifier with both bugs, then the two forged tokens:
            """
        ),
        code(
            r'''
            rsa_public_pem = rsa_private_key.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )


            def b64url(data: bytes) -> str:
                """base64url without padding (the JWT alphabet)."""
                return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


            def naive_verify(token: str, key: bytes) -> dict[str, object] | None:
                """WRONG: trusts the header's alg."""
                header_part, payload_part, signature_part = token.split(".")
                algorithm = b64url_json(header_part)["alg"]
                signed = f"{header_part}.{payload_part}".encode()
                if algorithm == "none":
                    return b64url_json(payload_part)
                if algorithm == "HS256":
                    expected = b64url(hmac.new(key, signed, hashlib.sha256).digest())
                    return b64url_json(payload_part) if hmac.compare_digest(expected, signature_part) else None
                return None  # (RS256 verification omitted from the naive demo)


            forged_claims = b64url(json.dumps({"sub": "1", "role": "admin"}).encode())
            none_token = b64url(b'{"alg":"none","typ":"JWT"}') + "." + forged_claims + "."
            hs_header = b64url(b'{"alg":"HS256","typ":"JWT"}')
            hs_signature = b64url(
                hmac.new(rsa_public_pem, f"{hs_header}.{forged_claims}".encode(), hashlib.sha256).digest()
            )
            confused_token = f"{hs_header}.{forged_claims}.{hs_signature}"
            print("naive, alg=none :", naive_verify(none_token, rsa_public_pem))
            print("naive, RS->HS   :", naive_verify(confused_token, rsa_public_pem))
            '''
        ),
        md(
            """
            Both forgeries pass the naive verifier. PyJWT refuses both: `algorithms` is an
            allow-list you choose, `none` is never accepted with a key, and PyJWT will not use
            an asymmetric public key as an HMAC secret:
            """
        ),
        code(
            r"""
            for label, token in (("alg=none", none_token), ("RS->HS", confused_token)):
                for algorithms in (["RS256"], ["RS256", "HS256"]):
                    print(
                        f"{label:9} algorithms={algorithms!s:18}",
                        raised_error_name(
                            lambda token=token, algorithms=algorithms: jwt.decode(
                                token, rsa_public_pem, algorithms=algorithms
                            )
                        ),
                    )
            print(inspect.signature(jwt.decode).parameters["algorithms"])
            """
        ),
        md(
            """
            Rules that follow: fix the algorithm on the server (the Notes API uses
            `JWT_ALGORITHM = "HS256"` and never reads it from the token), use separate keys for
            separate algorithms, require the claims you rely on, and keep tokens short-lived.
            """
        ),
    ]


def _lifecycle_cells() -> list[NotebookNode]:
    """6.5.4 Token lifecycle."""
    return [
        md(
            """
            ### 6.5.4 Token lifecycle

            | Token | Lifetime | Stored by the server? | Sent | Revocable |
            | --- | --- | --- | --- | --- |
            | **Access** (JWT) | minutes (Notes API: 15) | no (only a denylist entry after logout) | on every request, `Authorization: Bearer` | by denylist until it expires |
            | **Refresh** (opaque random string) | days (Notes API: 14) | yes, **as a SHA-256 hash** | only to `/auth/refresh` | yes: delete / mark revoked |

            **Rotation**: every refresh returns a **new** refresh token and invalidates the old
            one. **Reuse detection**: a refresh token used twice means it was copied (the
            attacker or the user used it after the other did), so the whole **family** (all
            tokens descending from one login) is revoked and both parties must log in again.

            ```mermaid
            sequenceDiagram
                participant C as Client
                participant A as Auth API
                C->>A: POST /token (password)
                A-->>C: access A1, refresh R1 (family F)
                C->>A: POST /refresh R1
                A-->>C: access A2, refresh R2 (R1 marked used)
                Note over C,A: attacker replays the stolen R1
                C->>A: POST /refresh R1
                A-->>C: 401 reuse detected: family F revoked (R2 dies too)
            ```

            <details><summary>ASCII version</summary>

            ```text
            login            -> A1 + R1   (family F)
            refresh R1       -> A2 + R2   (R1 used)
            refresh R1 again -> 401, revoke every token of family F (R2 included)
            ```

            </details>

            An in-memory model of exactly these rules (the Notes API stores the same fields
            in the `refresh_tokens` table):
            """
        ),
        code(
            r'''
            @dataclasses.dataclass
            class RefreshRecord:
                """One stored refresh token: only its hash, its family and its state."""

                token_hash: str
                family_id: str
                user_id: int
                used: bool = False
                revoked: bool = False
            '''
        ),
        md("`RefreshTokenStore`: issue, rotate and revoke refresh tokens with reuse detection:"),
        code(
            r'''
            class RefreshTokenStore:
                """Issue, rotate and revoke refresh tokens with reuse detection."""

                def __init__(self) -> None:
                    """Index records by token hash."""
                    self.records: dict[str, RefreshRecord] = {}

                def issue(self, user_id: int, family_id: str | None = None) -> str:
                    """A new random token; only its SHA-256 is kept."""
                    raw_token = secrets.token_urlsafe(32)
                    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
                    family = family_id or secrets.token_hex(8)
                    self.records[token_hash] = RefreshRecord(token_hash, family, user_id)
                    return raw_token

                def rotate(self, raw_token: str) -> str:
                    """Exchange a token for a new one in the same family, or raise."""
                    record = self.records.get(hashlib.sha256(raw_token.encode()).hexdigest())
                    if record is None or record.revoked:
                        raise PermissionError("invalid refresh token")
                    if record.used:
                        self.revoke_family(record.family_id)
                        raise PermissionError("reuse detected: family revoked")
                    record.used = True
                    return self.issue(record.user_id, record.family_id)

                def revoke_family(self, family_id: str) -> int:
                    """Revoke every token of a family; return how many."""
                    family = [record for record in self.records.values() if record.family_id == family_id]
                    for record in family:
                        record.revoked = True
                    return len(family)
            '''
        ),
        md("Log in, refresh, then replay the old token:"),
        code(
            r"""
            store = RefreshTokenStore()
            first_refresh = store.issue(user_id=42)
            second_refresh = store.rotate(first_refresh)
            print("rotated ok; stored values look like:", next(iter(store.records))[:16], "...")
            print("replay old :", raised_message(lambda: store.rotate(first_refresh)))
            print("use newest :", raised_message(lambda: store.rotate(second_refresh)))
            print("family     :", [(record.used, record.revoked) for record in store.records.values()])
            """
        ),
        md(
            """
            The legitimate user's newest token died with the family: that is the point (we
            cannot tell who is who, so everyone logs in again).

            **Revoking access tokens.** A JWT stays valid until `exp`. For logout (or "log out
            everywhere" after a password change) the Notes API stores the token's `jti` in
            Redis with a TTL equal to the token's remaining lifetime, and checks that
            denylist on every request. The entry expires by itself when the token would have
            expired anyway, so the denylist stays small:
            """
        ),
        code(
            r'''
            async def denylist_demo() -> None:
                """Deny one access token's jti until its expiry; check before and after."""
                redis_client = fakeredis.FakeAsyncRedis(decode_responses=True)
                token = make_token(jti=secrets.token_hex(8), exp=datetime.now(UTC) + timedelta(minutes=15))
                claims = jwt.decode(token, JWT_SECRET, algorithms=["HS256"], audience="notes-api")
                print("denied before logout?", await redis_client.exists(f"revoked-jti:{claims['jti']}") == 1)
                remaining = int(claims["exp"] - time.time())
                await redis_client.set(f"revoked-jti:{claims['jti']}", "1", ex=remaining)  # logout
                print("denied after logout? ", await redis_client.exists(f"revoked-jti:{claims['jti']}") == 1)
                print("entry expires in", await redis_client.ttl(f"revoked-jti:{claims['jti']}"), "s")
                await redis_client.aclose()


            await denylist_demo()
            '''
        ),
        md(
            """
            Logout in the Notes API therefore does two things: revoke the refresh token's
            family (database) and deny the current access token's `jti` (Redis).
            `test_auth.py` checks both, plus rotation and reuse detection, through the HTTP
            API.

            > **Where do browsers keep tokens?** Not in `localStorage` (any XSS reads it). An
            > HttpOnly cookie is safer for web apps (6.5.7); native and server clients keep them
            > in memory or the OS keychain.
            """
        ),
    ]


def _fastapi_security_cells() -> list[NotebookNode]:
    """6.5.5 FastAPI security."""
    return [
        md(
            """
            ### 6.5.5 FastAPI security

            FastAPI's security classes are dependencies that **extract** a credential from the
            request and describe it in OpenAPI (so `/docs` gets an *Authorize* button). They do
            not verify anything; your dependency does.

            | Class | Reads | Missing credential (`auto_error=True`) | OpenAPI scheme |
            | --- | --- | --- | --- |
            | `OAuth2PasswordBearer(tokenUrl=...)` | `Authorization: Bearer <token>` | 401 + `WWW-Authenticate: Bearer` | `oauth2` (password flow) |
            | `OAuth2PasswordRequestForm` | form fields `username`, `password`, `scope` | 422 | — (a request body) |
            | `HTTPBearer()` | `Authorization: Bearer ...` → `HTTPAuthorizationCredentials` | 401 | `http` / `bearer` |
            | `HTTPBasic()` | `Authorization: Basic ...` → username/password | 401 + `WWW-Authenticate: Basic` | `http` / `basic` |
            | `APIKeyHeader(name=...)` / `APIKeyQuery` / `APIKeyCookie` | one header / query parameter / cookie | 401 | `apiKey` |

            With `auto_error=False` they return `None` instead, so one dependency can accept
            several credential types (the Notes API accepts a bearer token **or** an API key).

            A complete password login: the `/token` endpoint takes the OAuth2 password form
            (`application/x-www-form-urlencoded`, field names fixed by RFC 6749) and returns
            a token; `get_current_user` turns the bearer token back into a user:
            """
        ),
        code(
            r'''
            login_hasher = fast_hasher()
            LOGIN_USERS = {"asha@example.com": {"id": 1, "hash": login_hasher.hash("a-long-passphrase")}}
            LOGIN_SECRET = secrets.token_urlsafe(32)
            login_scheme = OAuth2PasswordBearer(tokenUrl="/token")
            login_app = FastAPI()


            @login_app.post("/token")
            def issue_token(form: Annotated[OAuth2PasswordRequestForm, Depends()]) -> dict[str, str]:
                """Exchange e-mail + password for an access token (RFC 6749 password grant)."""
                user = LOGIN_USERS.get(form.username)
                if user is None or not login_hasher.verify(form.password, user["hash"]):
                    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong e-mail or password")
                claims = {"sub": str(user["id"]), "exp": datetime.now(UTC) + timedelta(minutes=15)}
                return {
                    "access_token": jwt.encode(claims, LOGIN_SECRET, algorithm="HS256"),
                    "token_type": "bearer",
                }


            def get_current_user(token: Annotated[str, Depends(login_scheme)]) -> dict[str, object]:
                """The user a bearer token belongs to, or 401."""
                try:
                    claims = jwt.decode(
                        token, LOGIN_SECRET, algorithms=["HS256"], options={"require": ["exp", "sub"]}
                    )
                except jwt.InvalidTokenError as error:
                    raise HTTPException(
                        401, f"invalid token: {error}", headers={"WWW-Authenticate": "Bearer"}
                    ) from error
                return {"id": int(claims["sub"])}


            @login_app.get("/me")
            def read_me(user: Annotated[dict[str, object], Depends(get_current_user)]) -> dict[str, object]:
                """The caller."""
                return user
            '''
        ),
        md("Log in with the form, call `/me`, and see the three failures:"),
        code(
            r"""
            with TestClient(login_app) as client:
                token_response = client.post(
                    "/token", data={"username": "asha@example.com", "password": "a-long-passphrase"}
                )
                access_token = token_response.json()["access_token"]
                print(
                    "me        :", client.get("/me", headers={"Authorization": f"Bearer {access_token}"}).json()
                )
                no_token = client.get("/me")
                print(
                    "no token  :",
                    no_token.status_code,
                    no_token.json(),
                    no_token.headers.get("www-authenticate"),
                )
                bad_token = client.get("/me", headers={"Authorization": "Bearer not.a.jwt"})
                print("bad token :", bad_token.status_code, bad_token.json()["detail"][:40])
                wrong = client.post("/token", data={"username": "asha@example.com", "password": "nope"})
                print("bad login :", wrong.status_code, wrong.json())
                print("JSON body :", client.post("/token", json={"username": "a", "password": "b"}).status_code)
            """
        ),
        md(
            """
            The last line is a 422: the login form is a **form**, not JSON (the spec says so,
            and it is what `/docs`' *Authorize* dialog sends).

            `HTTPBearer` gives you the raw scheme and credentials; `APIKeyHeader` reads one
            header. Both with `auto_error=False`, combined in one dependency:
            """
        ),
        code(
            r'''
            bearer_scheme = HTTPBearer(auto_error=False)
            key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)
            DEMO_API_KEYS = {"nk_demo_key": "reporting-bot"}
            either_app = FastAPI()


            @either_app.get("/whoami")
            def whoami(
                bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
                api_key: Annotated[str | None, Depends(key_scheme)],
            ) -> dict[str, str]:
                """Accept a bearer token or an API key."""
                if bearer is not None:
                    return {
                        "method": "bearer",
                        "scheme": bearer.scheme,
                        "credentials": bearer.credentials[:8] + "...",
                    }
                if api_key is not None and api_key in DEMO_API_KEYS:
                    return {"method": "api-key", "client": DEMO_API_KEYS[api_key]}
                raise HTTPException(
                    401, "send a bearer token or X-API-Key", headers={"WWW-Authenticate": "Bearer"}
                )


            with TestClient(either_app) as client:
                print(client.get("/whoami", headers={"Authorization": "Bearer abc.def.ghi"}).json())
                print(client.get("/whoami", headers={"X-API-Key": "nk_demo_key"}).json())
                print(client.get("/whoami").status_code)
            '''
        ),
        md(
            """
            Under the hood: the schemes end up in the OpenAPI document as
            `components.securitySchemes`, and each operation lists the ones it accepts. That is
            what `/docs` reads to draw its *Authorize* dialog:
            """
        ),
        code(
            r"""
            for name, app in (("login_app", login_app), ("either_app", either_app)):
                document = app.openapi()
                print(name, json.dumps(document["components"]["securitySchemes"]))
                for path, operations in document["paths"].items():
                    for method, operation in operations.items():
                        print(f"   {method.upper()} {path}: security={operation.get('security')}")
            """
        ),
    ]


def _authz_cells() -> list[NotebookNode]:
    """6.5.6 Authorization."""
    return [
        md(
            """
            ### 6.5.6 Authorization

            | Model | Question | FastAPI tool | Notes API v4 |
            | --- | --- | --- | --- |
            | **Roles** (RBAC) | is the user an `admin`? | a dependency checking `user.role` | `require_admin` on the admin router |
            | **Scopes** (OAuth2) | did *this token* get `notes:write`? | `Security(dep, scopes=[...])` + `SecurityScopes` | `ReaderServiceDep` / `WriterServiceDep` |
            | **Ownership** (object level) | is this note *yours*? | a filter in the query, never only in the router | `NoteService(owner_id=...)` |

            Roles describe the **user**; scopes describe what a **token** may do (a read-only
            API key for a reporting bot has fewer scopes than its owner). A role check as a
            dependency factory:
            """
        ),
        code(
            r'''
            ROLE_USERS = {
                "tok-asha": {"name": "asha", "role": "admin"},
                "tok-ravi": {"name": "ravi", "role": "user"},
            }
            role_scheme = APIKeyHeader(name="X-Token")


            def current_role_user(token: Annotated[str, Depends(role_scheme)]) -> dict[str, str]:
                """Look up the caller (401 for unknown tokens)."""
                if token not in ROLE_USERS:
                    raise HTTPException(401, "unknown token")
                return ROLE_USERS[token]


            def require_role(role: str) -> Callable[..., dict[str, str]]:
                """A dependency that allows only users with this role (403 otherwise)."""

                def check_role(user: Annotated[dict[str, str], Depends(current_role_user)]) -> dict[str, str]:
                    """Compare the caller's role."""
                    if user["role"] != role:
                        raise HTTPException(status.HTTP_403_FORBIDDEN, f"{role} role required")
                    return user

                return check_role


            role_app = FastAPI()


            @role_app.delete("/admin/cache", dependencies=[Depends(require_role("admin"))])
            def clear_cache() -> dict[str, bool]:
                """Admins only."""
                return {"cleared": True}


            with TestClient(role_app) as client:
                for token in ("tok-asha", "tok-ravi", "tok-nobody"):
                    response = client.delete("/admin/cache", headers={"X-Token": token})
                    print(f"{token:10} -> {response.status_code} {response.json()}")
            '''
        ),
        md(
            """
            **Scopes with `Security`.** `Security(dependency, scopes=[...])` is `Depends` plus
            a list of scopes. FastAPI **accumulates** the scopes of every `Security` on the
            path from the route down to a dependency that declares a `SecurityScopes`
            parameter, and hands them to it. One `get_principal` can therefore check whatever
            each route needs:
            """
        ),
        code(
            r'''
            SCOPED_TOKENS = {
                "tok-reader": {"user": "bot", "scopes": {"notes:read"}},
                "tok-writer": {"user": "asha", "scopes": {"notes:read", "notes:write"}},
            }
            scoped_scheme = OAuth2PasswordBearer(
                tokenUrl="/token", scopes={"notes:read": "Read notes", "notes:write": "Change notes"}
            )


            def get_principal(
                security_scopes: SecurityScopes, token: Annotated[str, Depends(scoped_scheme)]
            ) -> dict[str, object]:
                """Authenticate (401), then check every scope the route chain asked for (403)."""
                authenticate_value = f'Bearer scope="{security_scopes.scope_str}"'
                principal = SCOPED_TOKENS.get(token)
                if principal is None:
                    raise HTTPException(401, "invalid token", headers={"WWW-Authenticate": authenticate_value})
                missing = set(security_scopes.scopes) - principal["scopes"]
                if missing:
                    raise HTTPException(
                        403,
                        f"missing scope(s): {' '.join(sorted(missing))}",
                        headers={"WWW-Authenticate": authenticate_value},
                    )
                return principal | {"checked": security_scopes.scopes}


            scoped_app = FastAPI()


            @scoped_app.get("/notes")
            def list_scoped(principal: Annotated[dict, Security(get_principal, scopes=["notes:read"])]) -> dict:
                """Needs notes:read."""
                return {"user": principal["user"], "checked": principal["checked"]}
            '''
        ),
        md("`create_scoped()`: needs notes:write:"),
        code(
            r'''
            @scoped_app.post("/notes")
            def create_scoped(
                principal: Annotated[dict, Security(get_principal, scopes=["notes:write"])],
            ) -> dict:
                """Needs notes:write."""
                return {"user": principal["user"], "checked": principal["checked"]}
            '''
        ),
        md("The reader may list but not create; no token is a 401 that names the scope:"),
        code(
            r"""
            with TestClient(scoped_app) as client:
                for token in ("tok-reader", "tok-writer"):
                    for method in ("GET", "POST"):
                        response = client.request(
                            method, "/notes", headers={"Authorization": f"Bearer {token}"}
                        )
                        print(f"{token:10} {method:4} -> {response.status_code} {response.json()}")
                anonymous = client.post("/notes")
                print("anonymous POST ->", anonymous.status_code, anonymous.headers.get("www-authenticate"))
                print(scoped_app.openapi()["paths"]["/notes"]["post"]["security"])
            """
        ),
        md(
            """
            The scopes also appear in OpenAPI per operation. Accumulation shows best with a
            chain: a service dependency asks for `notes:read`, the route adds `notes:write` on
            top, and `get_principal` receives both:
            """
        ),
        code(
            r'''
            def get_notes_service(
                principal: Annotated[dict, Security(get_principal, scopes=["notes:read"])],
            ) -> dict:
                """A service that always needs read access."""
                return {"for": principal["user"], "checked": principal["checked"]}


            @scoped_app.delete("/notes")
            def wipe_scoped(
                service: Annotated[dict, Security(get_notes_service, scopes=["notes:write"])],
            ) -> dict:
                """Needs notes:write here plus notes:read from the service."""
                return service


            with TestClient(scoped_app) as client:
                print(client.delete("/notes", headers={"Authorization": "Bearer tok-writer"}).json())
                print(client.delete("/notes", headers={"Authorization": "Bearer tok-reader"}).json())
            '''
        ),
        md(
            """
            **Ownership and 404 vs 403.** Scopes say *which kind* of action a token may take;
            they say nothing about *which objects*. The check "is this note yours?" must happen
            for every object, and the safest place is the query itself (`WHERE owner_id = :me`),
            so no route can forget it.

            | Answer for someone else's object | Pros | Cons |
            | --- | --- | --- |
            | **403 Forbidden** | honest; easier to debug | confirms the id **exists**: ids can be enumerated |
            | **404 Not Found** | reveals nothing; same as a missing id | support must check the owner to explain |

            The Notes API answers **404**. A store that filters by owner, and the two answers
            side by side:
            """
        ),
        code(
            r'''
            DOCUMENTS = {
                1: {"owner": "asha", "title": "Asha's plan"},
                2: {"owner": "ravi", "title": "Ravi's list"},
            }
            owner_app = FastAPI()


            def document_for(document_id: int, user: str) -> dict[str, str]:
                """The document if it exists AND belongs to user; one 404 for both failures."""
                document = DOCUMENTS.get(document_id)
                if document is None or document["owner"] != user:
                    raise HTTPException(404, f"document {document_id} not found")
                return document


            @owner_app.get("/documents/{document_id}")
            def read_document(
                document_id: int, user: Annotated[str, Depends(APIKeyHeader(name="X-User"))]
            ) -> dict:
                """404 for missing and for foreign documents."""
                return document_for(document_id, user)


            @owner_app.get("/leaky/{document_id}")
            def read_leaky(
                document_id: int, user: Annotated[str, Depends(APIKeyHeader(name="X-User"))]
            ) -> dict:
                """403 for foreign documents: tells the caller the id exists."""
                document = DOCUMENTS.get(document_id) or {}
                if document and document["owner"] != user:
                    raise HTTPException(403, "not your document")
                return document or {"detail": "not found"}


            with TestClient(owner_app) as client:
                for path in ("/documents/1", "/documents/2", "/documents/99", "/leaky/2", "/leaky/99"):
                    response = client.get(path, headers={"X-User": "asha"})
                    print(f"{path:14} {response.status_code} {response.json()}")
            '''
        ),
        md(
            """
            With the leaky route, asha learns that document 2 exists (403) while 99 does not.
            With the safe one, both are 404. Lab 6.5 exercise 4 builds a test that finds such
            leaks automatically.
            """
        ),
    ]


def _browser_cells() -> list[NotebookNode]:
    """6.5.7 Browser security."""
    return [
        md(
            """
            ### 6.5.7 Browser security

            Browsers attach cookies automatically, run any JavaScript a page includes, and
            enforce the same-origin policy. Three tools follow from that.

            **Cookie flags**

            | Flag | Effect | Notes API session cookie |
            | --- | --- | --- |
            | `HttpOnly` | JavaScript cannot read it (`document.cookie`): XSS cannot steal it | yes |
            | `Secure` | sent only over HTTPS | yes (setting `cookie_secure`, off only in tests) |
            | `SameSite=Lax` | not sent on cross-site sub-requests or cross-site `POST`s; sent on top-level `GET` navigation | yes |
            | `SameSite=Strict` | never sent cross-site (even following a link) | — |
            | `SameSite=None` | always sent (requires `Secure`) | — |
            | `Max-Age` / `Expires` | lifetime; without it: a session cookie (gone when the browser closes) | access-token lifetime |
            | `Path`, `Domain` | where it is sent; omit `Domain` to keep it on this host only | `Path=/` |
            | `__Host-` name prefix | browser enforces `Secure`, `Path=/`, no `Domain` | could be used in production |

            Starlette's `Response.set_cookie` writes the header:
            """
        ),
        code(
            r'''
            cookie_app = FastAPI()


            @cookie_app.post("/login-cookie")
            def login_cookie(response: Response) -> dict[str, bool]:
                """Set a session cookie with every protective flag."""
                response.set_cookie(
                    "__Host-session",
                    secrets.token_urlsafe(16),
                    max_age=900,
                    httponly=True,
                    secure=True,
                    samesite="lax",
                    path="/",
                )
                return {"ok": True}


            with TestClient(cookie_app, base_url="https://testserver") as client:
                set_cookie = client.post("/login-cookie").headers["set-cookie"]
                print(re.sub(r"session=[^;]+", "session=<random>", set_cookie))
            '''
        ),
        md(
            """
            **CSRF (cross-site request forgery).** Because the browser attaches cookies by
            itself, a malicious page can submit a form to your site and the request arrives
            **authenticated**. `SameSite=Lax` already blocks cross-site `POST`s in modern
            browsers; a CSRF token is the second layer (older browsers, same-site subdomains).

            The **double-submit** pattern (Notes API pages): the server sets a random token
            in a second, readable cookie; the page repeats it in a hidden form field or an
            `X-CSRF-Token` header; the server accepts a write only if both match. An attacker's
            page cannot read your cookies, so it cannot repeat the value:
            """
        ),
        code(
            r'''
            csrf_app = FastAPI()
            CSRF_COOKIE = "csrf"


            @csrf_app.get("/form", response_class=HTMLResponse)
            def show_form(request: Request, response: Response) -> str:
                """Render a form carrying the CSRF token; set the cookie if missing."""
                token = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(16)
                response.set_cookie(CSRF_COOKIE, token, samesite="lax", httponly=False)
                hidden_field = f'<input type="hidden" name="csrf_token" value="{token}">'
                return f'<form method="post" action="/transfer">{hidden_field}</form>'


            @csrf_app.post("/transfer")
            def transfer(request: Request, csrf_token: Annotated[str, Form()] = "") -> dict[str, str]:
                """Accept only when the form field repeats the cookie (constant-time comparison)."""
                cookie_token = request.cookies.get(CSRF_COOKIE, "")
                if not cookie_token or not hmac.compare_digest(cookie_token, csrf_token):
                    raise HTTPException(403, "CSRF token missing or wrong")
                return {"status": "transferred"}


            with TestClient(csrf_app) as browser:
                page = browser.get("/form").text
                form_token = re.search(r'value="([^"]+)"', page)[1]
                print("own form      :", browser.post("/transfer", data={"csrf_token": form_token}).json())
                print("forged (none) :", browser.post("/transfer", data={}).status_code)
                print("forged (guess):", browser.post("/transfer", data={"csrf_token": "guess"}).status_code)
            '''
        ),
        md(
            """
            The forged requests carry the cookie (the browser sends it) but cannot know its
            value. APIs that use `Authorization: Bearer` headers are not exposed to CSRF at
            all: browsers never add that header by themselves.

            **CORS (cross-origin resource sharing).** The same-origin policy stops a page on
            `https://app.example` from **reading** responses from `https://api.example`. CORS
            headers relax it for origins you list. For non-simple requests (JSON bodies,
            `Authorization`, `PUT`/`DELETE`) the browser first sends an `OPTIONS` **preflight**
            and only sends the real request if the answer allows it:
            """
        ),
        code(
            r'''
            cors_app = FastAPI()
            cors_app.add_middleware(
                CORSMiddleware,
                allow_origins=["https://app.example"],
                allow_methods=["GET", "POST", "DELETE"],
                allow_headers=["Authorization", "Content-Type"],
                allow_credentials=True,
                max_age=600,
            )


            @cors_app.delete("/notes/{note_id}")
            def cors_delete(note_id: int) -> dict[str, int]:
                """A route behind CORS."""
                return {"deleted": note_id}


            preflight = {
                "Access-Control-Request-Method": "DELETE",
                "Access-Control-Request-Headers": "authorization",
            }
            with TestClient(cors_app) as client:
                for origin in ("https://app.example", "https://evil.example"):
                    answer = client.options("/notes/1", headers={"Origin": origin, **preflight})
                    allowed = {
                        key: value for key, value in answer.headers.items() if key.startswith("access-control")
                    }
                    print(f"preflight from {origin}: {answer.status_code} {allowed}")
                actual = client.delete("/notes/1", headers={"Origin": "https://app.example"})
                print(
                    "actual request:",
                    actual.headers.get("access-control-allow-origin"),
                    actual.headers.get("vary"),
                )
            '''
        ),
        md(
            """
            The evil origin gets a 400 and no `Access-Control-Allow-Origin`, so its browser
            refuses to send the request. Remember what CORS is **not**: it is enforced by
            browsers only; `curl` and servers ignore it, so it never replaces authentication.
            With `allow_credentials=True` the origin list must be explicit (Starlette echoes a
            matching origin instead of `*`, and adds `Vary: Origin` so caches keep answers per
            origin).
            """
        ),
    ]


def _oauth_cells() -> list[NotebookNode]:
    """6.5.8 Third-party login."""
    return [
        md(
            """
            ### 6.5.8 Third-party login

            **OAuth 2.0** (RFC 6749) lets a user grant your app access at another service
            without giving you their password. **OpenID Connect** (OIDC) adds identity on top:
            besides the access token, the provider returns an **ID token**, a JWT signed by
            the provider saying who the user is (`iss`, `sub`, `aud` = your client id, `email`,
            `nonce`). "Log in with Google/GitHub/Microsoft" is OIDC (GitHub: plain OAuth).

            The **Authorization Code flow with PKCE** (RFC 7636) is the one to use, for web
            servers and for apps that cannot keep a secret:

            ```mermaid
            sequenceDiagram
                participant B as Browser
                participant A as Notes API
                participant P as Provider
                B->>A: GET /auth/oauth/login
                A->>A: state, nonce, code_verifier → Redis (10 min)
                A-->>B: 302 to P/authorize?client_id&redirect_uri&scope=openid email&state&nonce&code_challenge
                B->>P: log in, consent
                P-->>B: 302 to A/callback?code&state
                B->>A: GET /auth/oauth/callback?code&state
                A->>A: state known? (GETDEL: once only)
                A->>P: POST /token (code, code_verifier, client secret)
                P-->>A: id_token (+ access token)
                A->>P: GET /jwks (cached)
                A->>A: verify signature, iss, aud, exp, nonce, email_verified
                A-->>B: our own session (cookie / tokens)
            ```

            <details><summary>ASCII version</summary>

            ```text
            browser -> API /login            API stores state+nonce+verifier, redirects to provider
            browser -> provider /authorize   user logs in; provider redirects back with code+state
            browser -> API /callback         API checks state, exchanges code+verifier for id_token,
                                             verifies the id_token with the provider's JWKS
            ```

            </details>

            | Parameter | Protects against |
            | --- | --- |
            | `state` | CSRF on the callback (an attacker's code injected into your session) |
            | `nonce` (in the ID token) | ID-token replay |
            | `code_verifier` / `code_challenge` (PKCE) | a stolen authorization code being redeemed by someone else |

            PKCE in five lines: a random verifier, its SHA-256 as the challenge. The example
            values are the ones in RFC 7636 appendix B:
            """
        ),
        code(
            r'''
            def pkce_challenge(code_verifier: str) -> str:
                """S256: base64url(SHA-256(verifier)) without padding."""
                return b64url(hashlib.sha256(code_verifier.encode("ascii")).digest())


            rfc_verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
            print(
                pkce_challenge(rfc_verifier),
                pkce_challenge(rfc_verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            )
            fresh_verifier = secrets.token_urlsafe(64)  # 43-128 characters from the unreserved set
            print(len(fresh_verifier), pkce_challenge(fresh_verifier)[:20] + "...")
            '''
        ),
        md(
            """
            **A mocked provider.** No real identity provider is contacted: respx intercepts
            the HTTP calls to `https://id.example` and a small fake implements the token and
            JWKS endpoints. The fake checks PKCE and signs ID tokens with its own RSA key,
            exactly as a real provider would:
            """
        ),
        code(
            r'''
            PROVIDER = "https://id.example"
            CLIENT_ID, CLIENT_SECRET = "notes-demo", secrets.token_urlsafe(16)
            provider_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            provider_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(provider_key.public_key())) | {
                "kid": "idp-1"
            }
            PENDING_CODES: dict[str, dict[str, str]] = {}  # code -> challenge, nonce, user


            def provider_authorize(params: dict[str, str], user_email: str) -> str:
                """What happens in the browser at the provider: log in, get redirected with a code."""
                code = secrets.token_urlsafe(16)
                PENDING_CODES[code] = {
                    "challenge": params["code_challenge"],
                    "nonce": params["nonce"],
                    "email": user_email,
                }
                return f"{params['redirect_uri']}?" + urllib.parse.urlencode(
                    {"code": code, "state": params["state"]}
                )
            '''
        ),
        md(
            "`provider_token()`: the fake token endpoint: check client, code and PKCE; return a signed ID token:"
        ),
        code(
            r'''
            def provider_token(request: httpx.Request) -> httpx.Response:
                """The fake token endpoint: check client, code and PKCE; return a signed ID token."""
                form = dict(urllib.parse.parse_qsl(request.content.decode()))
                pending = PENDING_CODES.pop(form.get("code", ""), None)
                if form.get("client_secret") != CLIENT_SECRET or pending is None:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                if pkce_challenge(form.get("code_verifier", "")) != pending["challenge"]:
                    return httpx.Response(400, json={"error": "invalid_grant", "error_description": "PKCE"})
                now = datetime.now(UTC)
                claims = {
                    "iss": PROVIDER,
                    "aud": CLIENT_ID,
                    "sub": "idp-user-7",
                    "email": pending["email"],
                    "email_verified": True,
                    "nonce": pending["nonce"],
                    "iat": now,
                    "exp": now + timedelta(minutes=5),
                }
                id_token = jwt.encode(claims, provider_key, algorithm="RS256", headers={"kid": "idp-1"})
                return httpx.Response(
                    200, json={"id_token": id_token, "access_token": "opaque", "token_type": "Bearer"}
                )
            '''
        ),
        md(
            """
            The client side (what `notes_api/oauth.py` does): build the authorization URL and
            remember `state`, `nonce` and the verifier; on the callback, check `state` once,
            redeem the code with the verifier, fetch the JWKS and verify the ID token:
            """
        ),
        code(
            r'''
            LOGIN_STATES: dict[str, dict[str, str]] = {}  # the Notes API keeps these in Redis


            def start_login() -> tuple[str, dict[str, str]]:
                """The provider URL to redirect the browser to, and its parameters."""
                code_verifier, state, nonce = (
                    secrets.token_urlsafe(48),
                    secrets.token_urlsafe(16),
                    secrets.token_urlsafe(16),
                )
                LOGIN_STATES[state] = {"verifier": code_verifier, "nonce": nonce}
                params = {
                    "response_type": "code",
                    "client_id": CLIENT_ID,
                    "redirect_uri": "https://notes.example/callback",
                    "scope": "openid email",
                    "state": state,
                    "nonce": nonce,
                    "code_challenge": pkce_challenge(code_verifier),
                    "code_challenge_method": "S256",
                }
                return f"{PROVIDER}/authorize?{urllib.parse.urlencode(params)}", params
            '''
        ),
        md(
            "`finish_login()`: check state (once), redeem the code with the verifier, verify the ID token:"
        ),
        code(
            r'''
            async def finish_login(callback_url: str, http: httpx.AsyncClient) -> dict[str, object]:
                """Check state (once), redeem the code with the verifier, verify the ID token."""
                query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(callback_url).query))
                saved = LOGIN_STATES.pop(query["state"], None)
                if saved is None:
                    raise PermissionError("unknown or reused state")
                token_reply = await http.post(
                    f"{PROVIDER}/token",
                    data={
                        "grant_type": "authorization_code",
                        "code": query["code"],
                        "code_verifier": saved["verifier"],
                        "client_id": CLIENT_ID,
                        "client_secret": CLIENT_SECRET,
                        "redirect_uri": "https://notes.example/callback",
                    },
                )
                token_reply.raise_for_status()
                id_token = token_reply.json()["id_token"]
                jwks = jwt.PyJWKSet.from_dict((await http.get(f"{PROVIDER}/jwks")).json())
                key = jwks[jwt.get_unverified_header(id_token)["kid"]]
                claims = jwt.decode(id_token, key, algorithms=["RS256"], audience=CLIENT_ID, issuer=PROVIDER)
                if not hmac.compare_digest(claims["nonce"], saved["nonce"]):
                    raise PermissionError("nonce mismatch")
                return claims
            '''
        ),
        md(
            "Run the whole flow against the mocked provider, then replay the same callback (the state was consumed) and try a stolen code without the verifier:"
        ),
        code(
            r'''
            async def oauth_demo() -> None:
                """Login flow with respx serving the provider's endpoints."""
                with respx.mock(assert_all_called=False) as provider:
                    provider.post(f"{PROVIDER}/token").mock(side_effect=provider_token)
                    provider.get(f"{PROVIDER}/jwks").mock(
                        return_value=httpx.Response(200, json={"keys": [provider_jwk]})
                    )
                    async with httpx.AsyncClient() as http:
                        authorize_url, params = start_login()
                        print("redirect to:", authorize_url[:90] + "...")
                        callback = provider_authorize(params, "asha@example.com")
                        claims = await finish_login(callback, http)
                        print(
                            "verified:", {key: claims[key] for key in ("iss", "sub", "email", "email_verified")}
                        )
                        try:
                            await finish_login(callback, http)
                        except PermissionError as error:
                            print("replayed callback:", f"{type(error).__name__}: {error}")
                        _, params = start_login()
                        stolen = provider_authorize(params, "asha@example.com")
                        LOGIN_STATES[params["state"]]["verifier"] = "attacker-does-not-know-it"
                        reply = await http.post(
                            f"{PROVIDER}/token",
                            data={
                                "code": dict(urllib.parse.parse_qsl(stolen.split("?")[1]))["code"],
                                "code_verifier": "guess",
                                "client_secret": CLIENT_SECRET,
                            },
                        )
                        print("stolen code without verifier:", reply.status_code, reply.json())


            await oauth_demo()
            '''
        ),
        md(
            """
            In the Notes API the same steps live in `OidcClient` (state in Redis with `GETDEL`,
            so a state works exactly once) and `test_oauth.py` runs them against a respx fake.
            After a verified callback, `AuthService.oidc_login` finds the user by `sub`, or links
            an existing account **only if the provider says the e-mail is verified**, and
            issues the API's own tokens.

            **Authlib** is the usual library for the client side (`authlib.integrations.httpx_client`
            and Starlette integrations: discovery from `/.well-known/openid-configuration`,
            PKCE, ID-token validation). It is optional in this course:
            """
        ),
        code(
            r"""
            if importlib.util.find_spec("authlib"):
                from authlib.integrations.httpx_client import AsyncOAuth2Client

                authlib_client = AsyncOAuth2Client(
                    CLIENT_ID, CLIENT_SECRET, code_challenge_method="S256", scope="openid email"
                )
                authlib_url, authlib_state = authlib_client.create_authorization_url(f"{PROVIDER}/authorize")
                print(authlib_url[:80], authlib_state)
            else:
                print("SKIP Authlib demo: the authlib package is not installed (not a course dependency)")
                print(
                    "equivalent: AsyncOAuth2Client(client_id, secret, code_challenge_method='S256')"
                    ".create_authorization_url(...), then .fetch_token(token_url, authorization_response=...)"
                )
            """
        ),
    ]


def _api_key_cells() -> list[NotebookNode]:
    """6.5.9 API keys and rate limiting."""
    return [
        md(
            """
            ### 6.5.9 API keys and rate limiting

            API keys identify **programs** (scripts, bots, integrations), not people. Good
            practice, all used by the Notes API:

            | Rule | Why |
            | --- | --- |
            | random, ≥ 128 bits (`secrets.token_urlsafe(32)`) | unguessable |
            | a recognisable prefix (`nk_`) | secret scanners (GitHub, gitleaks) can spot leaked keys |
            | shown **once**, stored as **SHA-256** | a database leak does not leak usable keys |
            | a short display prefix (`nk_AbC123…`) kept in clear | users can tell their keys apart |
            | scopes, `last_used_at`, revocation | least privilege; spot and kill unused keys |

            Why SHA-256 here when passwords need Argon2? Slow hashing protects **low-entropy**
            secrets (human passwords) against guessing. A 256-bit random key cannot be guessed,
            and a fast hash lets the server look it up by hash on every request:
            """
        ),
        code(
            r'''
            KEY_TABLE: dict[str, dict[str, object]] = {}  # key_hash -> row (the database)


            def create_api_key(owner: str, scopes: set[str]) -> str:
                """Generate a key, store its hash and display prefix, return the full key once."""
                raw_key = "nk_" + secrets.token_urlsafe(32)
                key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
                KEY_TABLE[key_hash] = {
                    "owner": owner,
                    "prefix": raw_key[:10],
                    "scopes": scopes,
                    "revoked": False,
                }
                return raw_key


            def lookup_api_key(raw_key: str) -> dict[str, object] | None:
                """The row for a presented key (lookup by hash), unless revoked."""
                row = KEY_TABLE.get(hashlib.sha256(raw_key.encode()).hexdigest())
                return None if row is None or row["revoked"] else row


            reporting_key = create_api_key("asha", {"notes:read"})
            print("shown once :", reporting_key[:14] + "...", len(reporting_key), "characters")
            print("stored row :", next(iter(KEY_TABLE.values())), "(no secret)")
            print(
                "lookup     :",
                lookup_api_key(reporting_key)["owner"],
                "| wrong key:",
                lookup_api_key("nk_guess"),
            )
            '''
        ),
        md(
            """
            **Rate limiting** caps how often a client (address, user, key) may call an endpoint:
            it slows password guessing and credential stuffing (OWASP API2/API4/API6). With
            several API processes the counters must be shared, so they live in Redis.

            | Algorithm | Redis commands | Behaviour |
            | --- | --- | --- |
            | **Fixed window** | `INCR key:<window>` + `EXPIRE` | simple, cheap; allows a burst of 2× at a window edge |
            | **Sliding window log** | `ZADD` timestamp, `ZREMRANGEBYSCORE` old, `ZCARD` | exact; memory grows with the limit |
            | **Token bucket** | a hash (tokens, last refill), updated atomically (Lua or `WATCH`) | smooth rate with bursts up to the bucket size |

            This unit starts **one real Redis** (a testcontainer) now; it is reused by the
            limiter demos and the Notes API v4 server, and stopped in the *Clean up* cell.
            Without Docker the demos run on fakeredis:
            """
        ),
        code(
            r'''
            REDIS_URL = start_shared_redis()
            print(
                "Redis:",
                "testcontainer at " + re.sub(r"\d+/0$", "<port>/0", REDIS_URL)
                if REDIS_URL
                else "SKIP (no Docker): fakeredis",
            )


            async def fixed_window_hit(
                redis_client: Any, key: str, limit: int, window: int, now: float
            ) -> tuple[bool, int]:
                """Count a hit in the current window; return (allowed, seconds until the window resets)."""
                window_key = f"ratelimit:{key}:{int(now // window)}"
                async with redis_client.pipeline(transaction=True) as pipe:
                    pipe.incr(window_key)
                    pipe.expire(window_key, window + 1)
                    count, _ = await pipe.execute()
                retry_after = int(window - now % window) or 1
                return count <= limit, retry_after
            '''
        ),
        md(
            "`fixed_window_demo()`: seven attempts against a limit of 5 per 60 s, then the next window:"
        ),
        code(
            r'''
            async def fixed_window_demo() -> None:
                """Seven attempts against a limit of 5 per 60 s, then the next window."""
                redis_client = make_redis(REDIS_URL)
                await redis_client.delete(
                    *[key async for key in redis_client.scan_iter("ratelimit:*")] or ["none"]
                )
                start = 1_800_000_000.0  # a fixed clock, so the output is stable
                results = [
                    await fixed_window_hit(redis_client, "login:203.0.113.9", 5, 60, start + attempt)
                    for attempt in range(7)
                ]
                print("first window :", results)
                print(
                    "next window  :",
                    await fixed_window_hit(redis_client, "login:203.0.113.9", 5, 60, start + 60),
                )
                await redis_client.aclose()


            await fixed_window_demo()
            '''
        ),
        md(
            """
            Attempts 6 and 7 are refused with the seconds left in the window, exactly what goes
            into `Retry-After`. `INCR` and `EXPIRE` run in one `MULTI`/`EXEC` pipeline, so a
            crash cannot leave a counter without its expiry.

            The sliding window log keeps one sorted-set member per hit, scored by time, and
            counts only the last `window` seconds:
            """
        ),
        code(
            r'''
            async def sliding_window_hit(
                redis_client: Any, key: str, limit: int, window: float, now: float
            ) -> bool:
                """Allow at most limit hits in any window-second interval."""
                log_key = f"sliding:{key}"
                async with redis_client.pipeline(transaction=True) as pipe:
                    pipe.zremrangebyscore(log_key, 0, now - window)
                    pipe.zadd(log_key, {f"{now}-{secrets.token_hex(4)}": now})
                    pipe.zcard(log_key)
                    pipe.expire(log_key, int(window) + 1)
                    _, _, count, _ = await pipe.execute()
                return count <= limit


            async def sliding_window_demo() -> None:
                """Three per 10 s: a burst at t = 0-3, a retry at 10.5, then calm again from t = 25."""
                redis_client = make_redis(REDIS_URL)
                await redis_client.delete("sliding:api-key-1")
                timeline = [0, 1, 2, 3, 10.5, 25, 26, 27, 28]
                print(
                    [
                        (moment, await sliding_window_hit(redis_client, "api-key-1", 3, 10, moment))
                        for moment in timeline
                    ]
                )
                await redis_client.aclose()


            await sliding_window_demo()
            '''
        ),
        md(
            """
            The retry at 10.5 is still refused: this simple version also logs refused hits, so
            a client that keeps hammering stays blocked (often what you want for logins). After
            a calm period the window is empty again and three more hits pass. Unit 5.4's `AsyncTokenBucket` is the
            in-process token bucket; with Redis it needs a Lua script or `WATCH` to stay atomic.

            **429 with `Retry-After`** as a FastAPI dependency. The limiter runs before the
            endpoint; the client learns when to come back:
            """
        ),
        code(
            r'''
            limited_app = FastAPI()
            limiter_redis = fakeredis.FakeAsyncRedis(decode_responses=True)  # per demo app


            async def limit_by_client(request: Request) -> None:
                """5 requests per 60 s per client address, else 429 + Retry-After."""
                client_address = request.client.host if request.client else "unknown"
                allowed, retry_after = await fixed_window_hit(
                    limiter_redis, f"search:{client_address}", 5, 60, time.time()
                )
                if not allowed:
                    raise HTTPException(429, "too many requests", headers={"Retry-After": str(retry_after)})


            @limited_app.get("/search", dependencies=[Depends(limit_by_client)])
            async def limited_search(q: str) -> dict[str, str]:
                """A rate-limited endpoint."""
                return {"q": q}


            with TestClient(limited_app) as client:
                statuses = [client.get("/search", params={"q": "tea"}) for _ in range(7)]
                print([response.status_code for response in statuses])
                print("Retry-After:", statuses[-1].headers["retry-after"], "s;", statuses[-1].json())
            '''
        ),
        md(
            """
            The Notes API's `FixedWindowRateLimiter` (in `ratelimit.py`) is this function as a
            class, applied to `/auth/token` and `/auth/register` per client address; Lab 6.5
            exercise 5 builds the login version with a controllable clock.

            > **Note:** behind a proxy or load balancer, `request.client.host` is the proxy.
            > Run Uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy address>` so the
            > real client address comes from `X-Forwarded-For`, and never trust that header from
            > anyone else.
            """
        ),
    ]


def _owasp_cells() -> list[NotebookNode]:
    """6.5.10 OWASP API Security Top 10 (2023)."""
    return [
        md(
            """
            ### 6.5.10 OWASP API Security Top 10 (2023)

            The OWASP API Security Top 10 (2023 edition) lists the most common API flaws. Each
            row: the risk, the FastAPI mitigation, and **where the Notes API v4 handles it**
            (file / test). A short demo of each mitigation follows the table.

            | Risk | What goes wrong | FastAPI mitigation | Notes API v4 |
            | --- | --- | --- | --- |
            | **API1 Broken Object Level Authorization** (BOLA) | `GET /notes/7` returns someone else's note | filter by owner in the query; 404 for foreign ids | `NoteRepository` methods take `owner_id`; `NoteService.get` → 404; `tests/test_bola.py` |
            | **API2 Broken Authentication** | weak passwords, brute force, long-lived or unverified tokens | Argon2id, rate limits, short JWTs with fixed `algorithms`, refresh rotation | `auth.py` (dummy hash, rehash, reuse detection), `security.py` (`TokenService`), `ratelimit.py`; `test_auth.py`, `test_security.py` |
            | **API3 Broken Object Property Level Authorization** | mass assignment (`"role": "admin"` in a body) or responses leaking fields (`password_hash`) | separate input/output schemas, `extra="forbid"`, `response_model` | `UserCreate` (no `role`, `extra="forbid"`), `UserRead` (no hash), `ApiKeyRead` (no key) |
            | **API4 Unrestricted Resource Consumption** | huge pages, uploads, expensive queries, unlimited requests | `Query(le=...)`, body size limits, timeouts, rate limits | `limit ≤ 100`, `max_upload_bytes`, 64 KiB preview cap, HTTP timeouts, login limits |
            | **API5 Broken Function Level Authorization** | a normal user calls an admin endpoint | role/scope dependency on the router | `admin` router `Depends(require_admin)` (role **and** `admin` scope); `test_admin.py` |
            | **API6 Unrestricted Access to Sensitive Business Flows** | bots mass-creating accounts, scraping | per-flow limits, CAPTCHAs, anomaly detection | registration rate-limited per address; API keys cannot create API keys |
            | **API7 Server Side Request Forgery** (SSRF) | the server fetches `http://169.254.169.254/` for an attacker | allow only public addresses, no redirects, size/time limits | `LinkPreviewer.check_url` (`is_global`), `follow_redirects=False`, 64 KiB; `test_security.py` |
            | **API8 Security Misconfiguration** | debug on, permissive CORS, missing headers, verbose errors | settings validated at startup, security headers, generic 500s | production validator, `SecurityHeadersMiddleware`, docs off in production, RFC 9457 errors without internals |
            | **API9 Improper Inventory Management** | forgotten old versions and undocumented endpoints | versioned prefixes, generated OpenAPI, deprecation flags | everything under `/api/v1`, one OpenAPI document, README endpoint table |
            | **API10 Unsafe Consumption of APIs** | trusting third-party responses (OIDC, link previews) | validate responses, timeouts, TLS, no redirects | ID tokens verified (signature, `iss`, `aud`, `nonce`, `email_verified`); previews parse only `<title>` from ≤ 64 KiB |

            **API1 — BOLA.** Covered in 6.5.6: `owner_app` answers 404 for another user's
            document. One more request to recall it:
            """
        ),
        code(
            r"""
            with TestClient(owner_app) as client:
                print(
                    "ravi reads asha's document:",
                    client.get("/documents/1", headers={"X-User": "ravi"}).status_code,
                )
            """
        ),
        md(
            """
            **API2 — Broken authentication.** One generic message for every login failure
            (no account enumeration), slow hashing, limits. The login app of 6.5.5 already
            answers the same for an unknown e-mail and a wrong password:
            """
        ),
        code(
            r"""
            with TestClient(login_app) as client:
                for username in ("asha@example.com", "nobody@example.com"):
                    reply = client.post("/token", data={"username": username, "password": "wrong"})
                    print(f"{username:20} {reply.status_code} {reply.json()}")
            """
        ),
        md(
            """
            **API3 — Object property level.** The input schema forbids unknown fields (so
            `role` cannot be smuggled in) and the response model filters what goes out:
            """
        ),
        code(
            r'''
            class SignUp(BaseModel):
                """Input: what a client may set."""

                model_config = ConfigDict(extra="forbid")
                email: EmailStr
                password: str = Field(min_length=12)


            class PublicUser(BaseModel):
                """Output: what a client may see."""

                id: int
                email: str


            property_app = FastAPI()


            @property_app.post("/users", response_model=PublicUser, status_code=201)
            def sign_up(body: SignUp) -> dict[str, object]:
                """The returned dict has a hash and a role; the response model drops them."""
                return {"id": 1, "email": body.email, "password_hash": "$argon2id$...", "role": "user"}


            with TestClient(property_app) as client:
                print(client.post("/users", json={"email": "a@example.com", "password": "x" * 12}).json())
                smuggled = client.post(
                    "/users", json={"email": "a@example.com", "password": "x" * 12, "role": "admin"}
                )
                print(
                    smuggled.status_code,
                    smuggled.json()["detail"][0]["type"],
                    smuggled.json()["detail"][0]["loc"],
                )
            '''
        ),
        md("**API4 — Resource consumption.** Bounds on every client-controlled size:"),
        code(
            r'''
            bounded_app = FastAPI()


            @bounded_app.get("/items")
            def bounded_items(limit: Annotated[int, fastapi.Query(ge=1, le=100)] = 20) -> dict[str, int]:
                """Never more than 100 rows per page."""
                return {"limit": limit}


            with TestClient(bounded_app) as client:
                print(client.get("/items", params={"limit": 50}).json())
                print(client.get("/items", params={"limit": 1_000_000}).json()["detail"][0]["msg"])
            '''
        ),
        md(
            "**API5 — Function level.** `role_app` from 6.5.6: the same route, a user versus an admin:"
        ),
        code(
            r"""
            with TestClient(role_app) as client:
                print(
                    {
                        token: client.delete("/admin/cache", headers={"X-Token": token}).status_code
                        for token in ("tok-ravi", "tok-asha")
                    }
                )
            """
        ),
        md(
            """
            **API6 — Sensitive business flows.** Limit the *flow*, not only the endpoint: for
            example sign-ups per address per hour, with a key that names the flow:
            """
        ),
        code(
            r'''
            async def signup_flow_demo() -> None:
                """At most 3 sign-ups per address per hour."""
                redis_client = fakeredis.FakeAsyncRedis(decode_responses=True)
                moment = 1_800_000_000.0
                decisions = [
                    (
                        await fixed_window_hit(
                            redis_client, "flow:signup:198.51.100.4", 3, 3600, moment + attempt
                        )
                    )[0]
                    for attempt in range(5)
                ]
                print("sign-ups allowed:", decisions)
                await redis_client.aclose()


            await signup_flow_demo()
            '''
        ),
        md(
            """
            **API7 — SSRF.** Before fetching a user-supplied URL, resolve the host and refuse
            anything that is not a public address. `ipaddress` knows the special ranges
            (loopback, private, link-local cloud metadata, carrier-grade NAT, IPv6 equivalents):
            """
        ),
        code(
            r"""
            for address in [
                "93.184.216.34",
                "127.0.0.1",
                "10.0.0.5",
                "169.254.169.254",
                "100.64.0.1",
                "::1",
                "fd00::1",
                "2606:4700::1111",
            ]:
                parsed = ipaddress.ip_address(address)
                print(
                    f"{address:16} global={parsed.is_global!s:5}"
                    f" private={parsed.is_private!s:5} link_local={parsed.is_link_local}"
                )
            """
        ),
        md(
            """
            Checking the **resolved** addresses matters: `http://metadata.attacker.example/`
            can resolve to `169.254.169.254`. And redirects must not be followed (a public URL
            can redirect to a private one), which is why the Notes API's HTTP client has
            `follow_redirects=False`.

            **API8 — Misconfiguration.** Settings are validated at startup (the Notes API
            refuses to start in production with a placeholder JWT secret) and every response
            carries security headers (6.5.11). A misconfigured app in one line, caught:
            """
        ),
        code(
            r'''
            class DeploySettings(BaseModel):
                """A slice of production settings, validated before the app starts."""

                environment: str
                debug: bool
                jwt_secret: SecretStr

                @pydantic.model_validator(mode="after")
                def safe_in_production(self) -> DeploySettings:
                    """No debug and a real secret in production."""
                    if self.environment == "production" and (
                        self.debug or len(self.jwt_secret.get_secret_value()) < 32
                    ):
                        raise ValueError("production needs debug=False and a 32+ character JWT secret")
                    return self


            print(
                raised_message(
                    lambda: DeploySettings(environment="production", debug=True, jwt_secret="change-me")
                )
            )
            print(
                DeploySettings(
                    environment="production", debug=False, jwt_secret=secrets.token_urlsafe(32)
                ).jwt_secret
            )
            '''
        ),
        md(
            """
            **API9 — Inventory.** Know every endpoint you expose: versioned prefixes, one
            generated OpenAPI document, and `deprecated=True` on routes being retired (it shows
            in `/docs` and in the schema):
            """
        ),
        code(
            r'''
            inventory_app = FastAPI()
            inventory_app.include_router(fastapi.APIRouter(prefix="/api/v1"))


            @inventory_app.get("/api/v1/notes")
            def notes_v1() -> list[str]:
                """Current."""
                return []


            @inventory_app.get("/api/v0/notes", deprecated=True)
            def notes_v0() -> list[str]:
                """Old clients only; scheduled for removal."""
                return []


            for path, operations in inventory_app.openapi()["paths"].items():
                print(
                    path,
                    {method: operation.get("deprecated", False) for method, operation in operations.items()},
                )
            '''
        ),
        md(
            """
            **API10 — Unsafe consumption.** Treat third-party responses as untrusted input:
            set timeouts, validate the shape, and handle failure. Here a (mocked) partner API
            returns a wrong type; validation turns it into a clear error instead of bad data
            flowing into your system:
            """
        ),
        code(
            r'''
            class PartnerRate(BaseModel):
                """What we expect from the partner."""

                currency: str = Field(pattern=r"^[A-Z]{3}$")
                rate: float = Field(gt=0)


            async def fetch_rate(http: httpx.AsyncClient) -> PartnerRate | str:
                """Fetch and validate; never pass unvalidated data on."""
                try:
                    reply = await http.get("https://partner.example/rate", timeout=2.0)
                    reply.raise_for_status()
                    return PartnerRate.model_validate(reply.json())
                except (httpx.HTTPError, ValidationError) as error:
                    return f"rejected: {type(error).__name__}"


            async def partner_demo() -> None:
                """A good and a bad partner response."""
                with respx.mock() as partner:
                    route = partner.get("https://partner.example/rate")
                    async with httpx.AsyncClient() as http:
                        route.mock(return_value=httpx.Response(200, json={"currency": "EUR", "rate": 1.08}))
                        print(await fetch_rate(http))
                        route.mock(return_value=httpx.Response(200, json={"currency": "euro", "rate": -1}))
                        print(await fetch_rate(http))


            await partner_demo()
            '''
        ),
    ]


def _injection_cells() -> list[NotebookNode]:
    """6.5.11 Injection, headers and secrets."""
    return [
        md(
            """
            ### 6.5.11 Injection, headers and secrets

            **SQL injection** happens when input becomes part of the SQL text. The fix is
            always the same: send values as **parameters**. A vulnerable query and its fix on
            SQLite:
            """
        ),
        code(
            r'''
            injection_db = sqlite3.connect(":memory:")
            injection_db.executescript(
                "CREATE TABLE users (email TEXT, role TEXT);"
                "INSERT INTO users VALUES ('asha@example.com', 'admin'), ('ravi@example.com', 'user');"
            )
            attack = "nobody@example.com' OR '1'='1"


            def find_user_unsafe(email: str) -> list[tuple[str, str]]:
                """WRONG: the input is pasted into the SQL text."""
                return injection_db.execute(f"SELECT email, role FROM users WHERE email = '{email}'").fetchall()


            def find_user_safe(email: str) -> list[tuple[str, str]]:
                """Right: a placeholder; the driver sends the value separately."""
                return injection_db.execute(
                    "SELECT email, role FROM users WHERE email = ?", (email,)
                ).fetchall()


            print("unsafe:", find_user_unsafe(attack))
            print("safe  :", find_user_safe(attack))
            '''
        ),
        md(
            """
            SQLAlchemy Core and ORM statements are always parameterized. With `text()` you
            still must use bind parameters (`:name`), never f-strings; the compiled statement
            shows the placeholder:
            """
        ),
        code(
            r"""
            safe_statement = text("SELECT email FROM users WHERE email = :email").bindparams(email=attack)
            print(safe_statement.compile(dialect=sqlite_dialect.dialect()))
            print(
                sa.select(sa.column("email")).select_from(sa.table("users")).where(sa.column("email") == attack)
            )
            """
        ),
        md(
            """
            **Command injection** is the same mistake with a shell: `shell=True` plus a string
            built from input lets `;`, `&&` or `$(...)` run extra commands. Pass an argument
            **list** (no shell), or `shlex.quote` when a shell is unavoidable. A harmless
            demonstration with `echo`:
            """
        ),
        code(
            r"""
            file_name = "report.txt; echo INJECTED"
            unsafe_run = subprocess.run(f"echo listing {file_name}", shell=True, capture_output=True, text=True)
            safe_run = subprocess.run(["echo", "listing", file_name], capture_output=True, text=True)
            quoted_run = subprocess.run(
                f"echo listing {shlex.quote(file_name)}", shell=True, capture_output=True, text=True
            )
            print("shell=True :", unsafe_run.stdout.splitlines())
            print("list args  :", safe_run.stdout.splitlines())
            print("shlex.quote:", quoted_run.stdout.splitlines())
            """
        ),
        md(
            """
            **Security headers** tell the browser to be stricter. A pure ASGI middleware adds
            them to every response (the Notes API's `SecurityHeadersMiddleware` does the same,
            with a looser CSP for `/docs`):

            | Header | Value | Effect |
            | --- | --- | --- |
            | `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` | HSTS: the browser uses HTTPS only for a year |
            | `Content-Security-Policy` | `default-src 'none'; frame-ancestors 'none'` (API) | CSP: no scripts, styles or framing for JSON responses |
            | `X-Content-Type-Options` | `nosniff` | no MIME sniffing (a JSON file is never run as a script) |
            | `X-Frame-Options` | `DENY` | no framing (clickjacking), for older browsers |
            | `Referrer-Policy` | `no-referrer` | URLs (with ids) are not leaked to other sites |
            | `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` | turn off powerful browser features |
            """
        ),
        code(
            r'''
            DEMO_SECURITY_HEADERS = [
                (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
                (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
                (b"x-content-type-options", b"nosniff"),
                (b"x-frame-options", b"DENY"),
                (b"referrer-policy", b"no-referrer"),
                (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
            ]


            class HeadersMiddleware:
                """Pure ASGI: append the security headers to every HTTP response."""

                def __init__(self, app: Any) -> None:
                    """Wrap the inner ASGI app."""
                    self.app = app

                async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
                    """Add headers on http.response.start."""
                    if scope["type"] != "http":
                        await self.app(scope, receive, send)
                        return

                    async def send_with_headers(message: dict) -> None:
                        """Extend the header list of the response start message."""
                        if message["type"] == "http.response.start":
                            message["headers"] = [*message.get("headers", []), *DEMO_SECURITY_HEADERS]
                        await send(message)

                    await self.app(scope, receive, send_with_headers)
            '''
        ),
        md("Every response, including errors, gets them:"),
        code(
            r'''
            headers_app = FastAPI()
            headers_app.add_middleware(HeadersMiddleware)


            @headers_app.get("/ping")
            def headers_ping() -> dict[str, bool]:
                """Any route."""
                return {"pong": True}


            with TestClient(headers_app) as client:
                for path in ("/ping", "/missing"):
                    response = client.get(path)
                    print(
                        path,
                        response.status_code,
                        {
                            name.decode(): response.headers[name.decode()][:30]
                            for name, _ in DEMO_SECURITY_HEADERS[:3]
                        },
                    )
            '''
        ),
        md(
            """
            **Secret management**

            | Do | Don't |
            | --- | --- |
            | read secrets from the environment, a `.env` file that is **git-ignored**, or a secret manager / Docker secrets (`secrets_dir`) | commit keys, even "temporary" ones |
            | commit a `.env.example` with **placeholders** | put real values in examples, tests or notebooks |
            | type them as `SecretStr` (hidden in `repr`, logs and dumps) | log settings objects with plain `str` secrets |
            | generate demo keys at runtime (`secrets.token_urlsafe`) | reuse one key across environments |
            | rotate on leak; scan the repository (gitleaks, GitHub secret scanning) | rely on deleting a commit: it stays in history |
            """
        ),
        code(
            r'''
            class ServiceSettings(pydantic.BaseModel):
                """SecretStr keeps the value out of repr, str and JSON dumps."""

                database_url: SecretStr
                jwt_secret: SecretStr


            service_settings = ServiceSettings(
                database_url="postgresql+asyncpg://notes:p4ss@db/notes", jwt_secret=secrets.token_urlsafe(32)
            )
            print(service_settings)
            print(service_settings.model_dump_json())
            print("explicit access:", service_settings.database_url.get_secret_value().split("@")[1])
            print(
                ".env is ignored by git:",
                subprocess.run(["git", "check-ignore", "-q", str(NOTES_API_DIR / ".env")]).returncode == 0,
            )
            '''
        ),
        md(
            """
            **`bandit`** is a static analyser for common Python security mistakes (`shell=True`,
            `eval`, `pickle`, weak hashes, hard-coded passwords, `verify=False`). It is not
            installed in this course environment, so the cell prints a skip message; the cell
            after it shows the idea with a tiny AST-based checker (under the hood: `ast` walks
            the syntax tree the same way bandit does):
            """
        ),
        code(
            r"""
            if importlib.util.find_spec("bandit"):
                bandit_run = subprocess.run(
                    [sys.executable, "-m", "bandit", "-q", "-r", str(NOTES_SRC)], capture_output=True, text=True
                )
                print(bandit_run.stdout[-1500:] or "bandit: no issues")
            else:
                print(
                    "SKIP bandit: not installed"
                    " (run it with `uvx bandit -r projects/notes_api/src` where uvx can download it)"
                )
            """
        ),
        md("The mini checker on a deliberately risky snippet (the rule ids are bandit's):"),
        code(
            r'''
            RISKY_CALLS = {
                "eval": "B307 eval",
                "exec": "B102 exec",
                "loads": "B301 pickle/marshal loads",
                "md5": "B324 weak hash",
            }
            risky_source = """
            import hashlib, pickle, subprocess
            subprocess.run(command, shell=True)
            data = pickle.loads(blob)
            digest = hashlib.md5(password.encode()).hexdigest()
            API_PASSWORD = "hunter2"
            """


            def mini_bandit(source: str) -> list[str]:
                """Flag a few risky patterns, bandit style."""
                findings = []
                for node in ast.walk(ast.parse(textwrap.dedent(source))):
                    if isinstance(node, ast.Call):
                        name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                        if name in RISKY_CALLS:
                            findings.append(f"line {node.lineno}: {RISKY_CALLS[name]}")
                        if any(
                            keyword.arg == "shell" and getattr(keyword.value, "value", False)
                            for keyword in node.keywords
                        ):
                            findings.append(f"line {node.lineno}: B602 subprocess with shell=True")
                    if isinstance(node, ast.Assign) and any(
                        "PASSWORD" in getattr(target, "id", "") for target in node.targets
                    ):
                        findings.append(f"line {node.lineno}: B105 hard-coded password")
                return sorted(findings, key=lambda finding: int(finding.split()[1].rstrip(":")))


            print(*mini_bandit(risky_source), sep="\n")
            '''
        ),
        md(
            """
            **`pip-audit`** checks installed packages against known vulnerabilities (the PyPA
            advisory database / OSV). It is installed (Phase 4), but an audit downloads the
            advisory data from the internet, which this notebook never does. The cell shows the
            version and the command; run the command yourself when you are online (CI runs it
            on every push):
            """
        ),
        code(
            r"""
            audit_version = subprocess.run(
                [sys.executable, "-m", "pip_audit", "--version"], capture_output=True, text=True
            )
            print(audit_version.stdout.strip() or audit_version.stderr.strip())
            print(
                "SKIP the audit itself (needs the network)."
                " Run: uv export --frozen --no-hashes > req.txt && uv run pip-audit -r req.txt"
            )
            """
        ),
        md(
            """
            **Log redaction.** Logs travel further than databases (log aggregators, support
            tickets, screenshots). Tokens, passwords and keys must never reach them. Here a
            careless log line leaks a bearer token, and a small `logging.Filter` masks it.
            Lab 6.5 exercise 6 builds the complete filter (arguments, JSON fields, JWTs, API
            keys); the Notes API installs it in `core/logging.py`:
            """
        ),
        code(
            r'''
            class BearerFilter(logging.Filter):
                """Mask bearer tokens in the formatted message."""

                def filter(self, record: logging.LogRecord) -> bool:
                    """Rewrite the record in place; never drop it."""
                    record.msg = re.sub(r"(?i)(bearer\s+)\S+", r"\1[REDACTED]", record.getMessage())
                    record.args = None
                    return True


            demo_logger = logging.getLogger("demo.redaction")
            demo_logger.propagate = False
            log_stream = io.StringIO()
            demo_logger.handlers[:] = [logging.StreamHandler(log_stream)]
            demo_logger.warning("auth failed: header=%s", f"Bearer {demo_token}")
            demo_logger.addFilter(BearerFilter())
            demo_logger.warning("auth failed: header=%s", f"Bearer {demo_token}")
            print(log_stream.getvalue().replace(demo_token, demo_token[:12] + "...(full token)"))
            '''
        ),
    ]


def _predict_cells() -> list[NotebookNode]:
    """Three predict-the-output questions for Unit 6.5."""
    return [
        md(
            """
            ### Predict the output — Unit 6.5

            Three questions about hashing, JWT validation and scopes. Decide first, then run
            the proof.
            """
        ),
        *predict_cells(
            """
            hasher = fast_hasher()
            first, second = hasher.hash("swordfish"), hasher.hash("swordfish")
            print(first == second, hasher.verify("swordfish", second))
            """,
            """
            `False True`. Each hash gets a fresh random salt, so two hashes of the same
            password differ; `verify` reads the salt and parameters from the stored string and
            recomputes, so either hash verifies.
            """,
            r"""
            hasher = fast_hasher()
            first, second = hasher.hash("swordfish"), hasher.hash("swordfish")
            print(first == second, hasher.verify("swordfish", second))
            """,
        ),
        *predict_cells(
            """
            token = jwt.encode({"sub": "1", "aud": "notes-api"}, "k" * 32, algorithm="HS256")
            try:
                print(jwt.decode(token, "k" * 32, algorithms=["HS256"]))
            except jwt.InvalidTokenError as error:
                print(type(error).__name__)
            """,
            """
            `InvalidAudienceError`. When a token **has** an `aud` claim, PyJWT requires the
            caller to pass `audience=`; a verifier that does not say who it is must not accept
            tokens meant for a specific audience. (No `exp` is fine: PyJWT only checks the
            claims that are present unless you `require` them.)
            """,
            r"""
            token = jwt.encode({"sub": "1", "aud": "notes-api"}, "k" * 32, algorithm="HS256")
            try:
                print(jwt.decode(token, "k" * 32, algorithms=["HS256"]))
            except jwt.InvalidTokenError as error:
                print(type(error).__name__)
            """,
        ),
        *predict_cells(
            """
            # scoped_app from 6.5.6: DELETE /notes uses Security(get_notes_service, scopes=["notes:write"])
            # and get_notes_service uses Security(get_principal, scopes=["notes:read"]).
            with TestClient(scoped_app) as client:
                print(client.delete("/notes", headers={"Authorization": "Bearer tok-writer"}).json()["checked"])
            """,
            """
            `['notes:write', 'notes:read']`. FastAPI accumulates scopes from the route
            downwards: the outer `Security` (on the route parameter) contributes `notes:write`
            first, then the inner one adds `notes:read`. `get_principal` sees both and the
            writer token has both.
            """,
            r"""
            with TestClient(scoped_app) as client:
                print(client.delete("/notes", headers={"Authorization": "Bearer tok-writer"}).json()["checked"])
            """,
        ),
    ]


LAB65_GIVEN_SOURCE = r'''
LAB_SECRET = secrets.token_urlsafe(32)  # generated per run
lab_hasher = fast_hasher()
SCOPE_USERS = {"rita": "reader", "eddie": "editor", "ada": "admin"}
ROLE_SCOPES = {
    "reader": {"notes:read"},
    "editor": {"notes:read", "notes:write"},
    "admin": {"notes:read", "notes:write", "admin"},
}
LAB_LOGIN_USERS = {"asha@example.com": lab_hasher.hash("a-long-passphrase")}


def lab_scope_token(username: str, scopes: set[str]) -> str:
    """A 15-minute HS256 token for a SCOPE_USERS user with the requested scopes."""
    now = datetime.now(UTC)
    claims = {"sub": username, "role": SCOPE_USERS[username], "scope": " ".join(sorted(scopes))}
    return jwt.encode(
        claims | {"iat": now, "exp": now + timedelta(minutes=15)}, LAB_SECRET, algorithm="HS256"
    )
'''

LAB65_GIVEN_HELPERS_SOURCE = r'''
class SettableClock:
    """A clock for tests: call it for the time, advance() it by hand."""

    def __init__(self, start: float = 1_800_000_000.0) -> None:
        """Start at a fixed Unix time."""
        self.now = start

    def __call__(self) -> float:
        """The current (fake) time."""
        return self.now

    def advance(self, seconds: float) -> None:
        """Move time forward."""
        self.now += seconds


class LabListHandler(logging.Handler):
    """Keep formatted log lines in a list."""

    def __init__(self) -> None:
        """Start empty."""
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Store the formatted record."""
        self.lines.append(self.format(record))
'''

LAB65_GIVEN_DOCS_SOURCE = r'''
def make_owner_check(
    documents: dict[int, dict[str, object]], vulnerable_routes: frozenset[str]
) -> Callable[[int, str, str], dict[str, object]]:
    """owned(document_id, user, route): the document if user may use it through route, else 404."""

    def owned(document_id: int, user: str, route: str) -> dict[str, object]:
        """Look up and authorize (routes in vulnerable_routes forget the owner check)."""
        document = documents.get(document_id)
        if document is None or (document["owner"] != user and route not in vulnerable_routes):
            raise HTTPException(404, "document not found")
        return document

    return owned

'''

LAB65_GIVEN_DOCS_APP_SOURCE = r'''
def build_doc_api(vulnerable_routes: frozenset[str] = frozenset()) -> FastAPI:
    """Documents owned by users (X-User header); vulnerable_routes skip the owner check."""
    documents: dict[int, dict[str, object]] = {}
    owned, doc_app = make_owner_check(documents, vulnerable_routes), FastAPI()
    User = Annotated[str, Depends(APIKeyHeader(name="X-User"))]

    @doc_app.post("/documents", status_code=201)
    def create_doc(body: dict[str, str], user: User) -> dict[str, object]:
        """Create a document owned by the caller."""
        document = {"id": len(documents) + 1, "owner": user, "title": body.get("title", "")}
        documents[document["id"]] = document
        return document

    @doc_app.get("/documents")
    def list_docs(user: User) -> list[dict[str, object]]:
        """The caller's documents (everyone's when the list route is vulnerable)."""
        leaky = "GET /documents" in vulnerable_routes
        return [doc for doc in documents.values() if leaky or doc["owner"] == user]

    @doc_app.get("/documents/{document_id}")
    def read_doc(document_id: int, user: User) -> dict[str, object]:
        """One document."""
        return owned(document_id, user, "GET /documents/{id}")

    @doc_app.patch("/documents/{document_id}")
    def rename_doc(document_id: int, body: dict[str, str], user: User) -> dict[str, object]:
        """Change the title."""
        document = owned(document_id, user, "PATCH /documents/{id}")
        document["title"] = body.get("title", document["title"])
        return document

    @doc_app.delete("/documents/{document_id}", status_code=204)
    def delete_doc(document_id: int, user: User) -> None:
        """Delete a document."""
        documents.pop(owned(document_id, user, "DELETE /documents/{id}")["id"])

    return doc_app
'''


def _lab_setup_cells() -> list[NotebookNode]:
    """Lab 6.5 introduction and given code."""
    return [
        md(
            """
            ### Lab 6.5

            | Exercise | Syllabus item | You write |
            | --- | --- | --- |
            | 1 | A hand-built JWT, then the same with PyJWT | `b64url_encode`, `b64url_decode`, `hand_jwt_encode`, `hand_jwt_decode`, `pyjwt_encode`, `pyjwt_decode` |
            | 2 | Register / login / refresh / logout / me endpoints | `build_auth_app()` |
            | 3 | Roles and scopes with 401/403 tests | `get_lab_principal`, `build_scoped_lab_app()` |
            | 4 | A BOLA test | `find_bola(app)` |
            | 5 | Login rate limiting | `LoginRateLimiter`, `build_rate_limited_login(limiter)` |
            | 6 | A log redaction filter | `RedactingFilter` |

            The *Notes API v4* section after the lab puts the same pieces into the real
            project. The given code: a lab secret and a cheap hasher, users with roles and
            `lab_scope_token()` for exercise 3, a `SettableClock` for exercise 5 and a
            `LabListHandler` that collects log lines for exercise 6:
            """
        ),
        code(LAB65_GIVEN_SOURCE),
        md(
            "A controllable clock (exercise 5) and a handler that keeps log lines in a list (exercise 6):"
        ),
        code(LAB65_GIVEN_HELPERS_SOURCE),
        md(
            """
            For exercise 4: `build_doc_api(vulnerable_routes)` builds a small documents API
            (the caller is named by an `X-User` header). Routes named in `vulnerable_routes`
            (`"GET /documents"`, `"GET /documents/{id}"`, `"PATCH /documents/{id}"`, `"DELETE /documents/{id}"`)
            forget the owner check; with an empty set the API is safe:
            """
        ),
        code(LAB65_GIVEN_DOCS_SOURCE),
        md("The app factory itself:"),
        code(LAB65_GIVEN_DOCS_APP_SOURCE),
    ]


def _lab_exercise_1_cells() -> list[NotebookNode]:
    """Lab 6.5 exercise 1."""
    return [
        md(
            """
            #### Exercise 1 — A hand-built JWT, then the same with PyJWT

            With `json`, `base64`, `hmac` and `hashlib` only:

            - `b64url_encode(data: bytes) -> str`: URL-safe base64 **without** `=` padding;
              `b64url_decode(text: str) -> bytes` restores the padding and decodes.
            - `hand_jwt_encode(claims, secret) -> str`: header `{"alg": "HS256", "typ": "JWT"}`,
              the claims as compact JSON, signature = HMAC-SHA256 of `header.payload` with the
              secret (UTF-8), all three parts base64url-encoded.
            - `hand_jwt_decode(token, secret) -> dict`: raise `ValueError` unless the token has
              three parts, the header's `alg` is exactly `"HS256"`, the signature matches
              (`hmac.compare_digest`) and, if there is an `exp`, it is in the future. Return
              the claims.

            Then the same with PyJWT: `pyjwt_encode(claims, secret)` and
            `pyjwt_decode(token, secret)` (HS256 only; let PyJWT's exceptions propagate). The
            checks mix both: PyJWT must accept your tokens and your decoder must accept
            PyJWT's.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            def b64url_encode(data: bytes) -> str:
                """URL-safe base64 without padding."""
                raise NotImplementedError


            def b64url_decode(text: str) -> bytes:
                """Decode URL-safe base64, restoring the padding."""
                raise NotImplementedError


            def hand_jwt_encode(claims: dict[str, Any], secret: str) -> str:
                """An HS256 JWT built by hand."""
                raise NotImplementedError


            def hand_jwt_decode(token: str, secret: str) -> dict[str, Any]:
                """Verify an HS256 JWT by hand; ValueError when anything is wrong."""
                raise NotImplementedError


            def pyjwt_encode(claims: dict[str, Any], secret: str) -> str:
                """The same token with PyJWT."""
                raise NotImplementedError


            def pyjwt_decode(token: str, secret: str) -> dict[str, Any]:
                """Verify with PyJWT, HS256 only."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 1. Tokens for the checks (built when the cell runs):"),
        code(
            r'''
            def forged(header: dict[str, str], claims: dict[str, Any], signature: str = "") -> str:
                """A token with any header and claims and the given signature part."""
                return (
                    ".".join(
                        base64.urlsafe_b64encode(json.dumps(part).encode()).rstrip(b"=").decode()
                        for part in (header, claims)
                    )
                    + "."
                    + signature
                )


            def tampered_hand_token() -> str:
                """A valid hand-made token whose payload was swapped afterwards."""
                header, _, signature = hand_jwt_encode({"sub": "1", "role": "user"}, LAB_SECRET).split(".")
                evil_payload = (
                    base64.urlsafe_b64encode(json.dumps({"sub": "1", "role": "admin"}).encode())
                    .rstrip(b"=")
                    .decode()
                )
                return f"{header}.{evil_payload}.{signature}"


            LATER = int(time.time()) + 600
            '''
        ),
        md("The checks:"),
        code(
            r"""
            run_checks(
                [
                    ("b64url_encode drops padding", lambda: b64url_encode(b"\xfb\xff"), "-_8"),
                    ("b64url_decode restores it", lambda: b64url_decode("-_8"), b"\xfb\xff"),
                    (
                        "header of a hand token",
                        lambda: json.loads(
                            b64url_decode(hand_jwt_encode({"sub": "1"}, LAB_SECRET).split(".")[0])
                        ),
                        {"alg": "HS256", "typ": "JWT"},
                    ),
                    (
                        "PyJWT accepts a hand token",
                        lambda: jwt.decode(
                            hand_jwt_encode({"sub": "1", "exp": LATER}, LAB_SECRET),
                            LAB_SECRET,
                            algorithms=["HS256"],
                        ),
                        {"sub": "1", "exp": LATER},
                    ),
                    (
                        "hand decoder accepts a PyJWT token",
                        lambda: hand_jwt_decode(
                            jwt.encode({"sub": "2"}, LAB_SECRET, algorithm="HS256"), LAB_SECRET
                        ),
                        {"sub": "2"},
                    ),
                    (
                        "tampered payload",
                        lambda: raised_error_name(lambda: hand_jwt_decode(tampered_hand_token(), LAB_SECRET)),
                        "ValueError",
                    ),
                ]
            )
            """
        ),
        md("More checks:"),
        code(
            r"""
            run_checks(
                [
                    (
                        "alg none",
                        lambda: raised_error_name(
                            lambda: hand_jwt_decode(forged({"alg": "none"}, {"sub": "1"}), LAB_SECRET)
                        ),
                        "ValueError",
                    ),
                    (
                        "wrong secret",
                        lambda: raised_error_name(
                            lambda: hand_jwt_decode(hand_jwt_encode({"sub": "1"}, "other-secret"), LAB_SECRET)
                        ),
                        "ValueError",
                    ),
                    (
                        "expired",
                        lambda: raised_error_name(
                            lambda: hand_jwt_decode(hand_jwt_encode({"exp": 1_000}, LAB_SECRET), LAB_SECRET)
                        ),
                        "ValueError",
                    ),
                    (
                        "not three parts",
                        lambda: raised_error_name(lambda: hand_jwt_decode("abc.def", LAB_SECRET)),
                        "ValueError",
                    ),
                    (
                        "PyJWT round trip",
                        lambda: pyjwt_decode(pyjwt_encode({"sub": "3"}, LAB_SECRET), LAB_SECRET),
                        {"sub": "3"},
                    ),
                ]
            )
            """
        ),
        md("More checks:"),
        code(
            r"""
            run_checks(
                [
                    (
                        "PyJWT refuses HS512",
                        lambda: raised_error_name(
                            lambda: pyjwt_decode(
                                jwt.encode({"sub": "4"}, LAB_SECRET * 2, algorithm="HS512"), LAB_SECRET * 2
                            )
                        ),
                        "InvalidAlgorithmError",
                    ),
                    (
                        "hand token == PyJWT token for the same claims?",
                        lambda: (
                            hand_jwt_decode(pyjwt_encode({"a": 1}, LAB_SECRET), LAB_SECRET)
                            == jwt.decode(
                                hand_jwt_encode({"a": 1}, LAB_SECRET), LAB_SECRET, algorithms=["HS256"]
                            )
                        ),
                        True,
                    ),
                ]
            )
            """
        ),
    ]


def _lab_exercise_2_cells() -> list[NotebookNode]:
    """Lab 6.5 exercise 2."""
    return [
        md(
            """
            #### Exercise 2 — Register / login / refresh / logout / me

            Write `build_auth_app() -> FastAPI`, in memory (every call builds a fresh app with
            empty storage), using `lab_hasher` and `LAB_SECRET`:

            | Endpoint | Behaviour |
            | --- | --- |
            | `POST /register` JSON `{"email", "password"}` | password ≥ 12 characters (else 422); 201 `{"id", "email"}`; an e-mail already registered → 409 |
            | `POST /token` (OAuth2 password **form**) | 200 `{"access_token", "refresh_token", "token_type": "bearer"}`; wrong e-mail or password → 401 |
            | `GET /me` (`Authorization: Bearer`) | 200 `{"id", "email"}`; missing, invalid, expired or logged-out token → 401 |
            | `POST /refresh` JSON `{"refresh_token"}` | a **new** pair; the old refresh token is used up. Unknown, revoked or **reused** token → 401, and a reuse revokes the whole family |
            | `POST /logout` JSON `{"refresh_token"}` + bearer | 204; afterwards that access token and that refresh token are rejected (401) |

            Access tokens: HS256 JWTs with `sub`, `exp` (15 minutes) and a unique `jti`. Refresh
            tokens: random strings (`secrets.token_urlsafe`); store their SHA-256 only.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            def build_auth_app() -> FastAPI:
                """Register, token, me, refresh and logout, in memory."""
                raise NotImplementedError
            '''
        ),
        md(
            "Check exercise 2. `auth_scenario()` runs the whole lifecycle once and records each answer:"
        ),
        code(
            r'''
            def auth_scenario() -> dict[str, object]:
                """Every step of the lifecycle against a fresh app."""
                results: dict[str, object] = {}
                with TestClient(build_auth_app()) as client:
                    account = {"email": "asha@example.com", "password": "a-long-passphrase"}
                    registered = client.post("/register", json=account)
                    results["register"] = (registered.status_code, sorted(registered.json()))
                    results["duplicate"] = client.post("/register", json=account).status_code
                    results["short password"] = client.post(
                        "/register", json={"email": "b@example.com", "password": "short"}
                    ).status_code
                    results["wrong password"] = client.post(
                        "/token", data={"username": account["email"], "password": "nope"}
                    ).status_code
                    pair = client.post(
                        "/token", data={"username": account["email"], "password": account["password"]}
                    ).json()
                    results["pair keys"] = sorted(pair)
                    bearer = {"Authorization": f"Bearer {pair['access_token']}"}
                    results["me"] = client.get("/me", headers=bearer).json().get("email")
                    results["me without token"] = client.get("/me").status_code
                    results["jti claim"] = "jti" in jwt.decode(
                        pair["access_token"], LAB_SECRET, algorithms=["HS256"]
                    )
                    second = client.post("/refresh", json={"refresh_token": pair["refresh_token"]}).json()
                    results["refresh gives new tokens"] = second.get("refresh_token") not in (
                        None,
                        pair["refresh_token"],
                    )
                    results["reuse"] = client.post(
                        "/refresh", json={"refresh_token": pair["refresh_token"]}
                    ).status_code
                    results["newest after reuse"] = client.post(
                        "/refresh", json={"refresh_token": second.get("refresh_token")}
                    ).status_code
                    results.update(logout_steps(client, account))
                return results
            '''
        ),
        md("`logout_steps()`: log in again, log out, then try both tokens:"),
        code(
            r'''
            def logout_steps(client: TestClient, account: dict[str, str]) -> dict[str, object]:
                """Log in, log out, then use both tokens."""
                pair = client.post(
                    "/token", data={"username": account["email"], "password": account["password"]}
                ).json()
                bearer = {"Authorization": f"Bearer {pair['access_token']}"}
                return {
                    "logout": client.post(
                        "/logout", json={"refresh_token": pair["refresh_token"]}, headers=bearer
                    ).status_code,
                    "me after logout": client.get("/me", headers=bearer).status_code,
                    "refresh after logout": client.post(
                        "/refresh", json={"refresh_token": pair["refresh_token"]}
                    ).status_code,
                }


            def fresh_apps_are_independent() -> bool:
                """Two apps do not share users."""
                with TestClient(build_auth_app()) as first, TestClient(build_auth_app()) as second:
                    account = {"email": "solo@example.com", "password": "a-long-passphrase"}
                    return (
                        first.post("/register", json=account).status_code,
                        second.post("/register", json=account).status_code,
                    ) == (201, 201)
            '''
        ),
        md("The checks:"),
        code(
            r"""
            lab_auth_results: dict[str, object] = {}
            with contextlib.suppress(Exception):
                lab_auth_results = auth_scenario()
            run_checks(
                [
                    (
                        "register: 201 with id and email",
                        lambda: lab_auth_results["register"],
                        (201, ["email", "id"]),
                    ),
                    ("duplicate e-mail: 409", lambda: lab_auth_results["duplicate"], 409),
                    ("short password: 422", lambda: lab_auth_results["short password"], 422),
                    ("wrong password: 401", lambda: lab_auth_results["wrong password"], 401),
                    (
                        "token pair",
                        lambda: lab_auth_results["pair keys"],
                        ["access_token", "refresh_token", "token_type"],
                    ),
                    ("me", lambda: lab_auth_results["me"], "asha@example.com"),
                    ("me without a token: 401", lambda: lab_auth_results["me without token"], 401),
                    ("access token has a jti", lambda: lab_auth_results["jti claim"], True),
                    ("refresh rotates", lambda: lab_auth_results["refresh gives new tokens"], True),
                    ("reused refresh token: 401", lambda: lab_auth_results["reuse"], 401),
                    ("reuse revoked the family", lambda: lab_auth_results["newest after reuse"], 401),
                    ("logout: 204", lambda: lab_auth_results["logout"], 204),
                    ("access token dead after logout", lambda: lab_auth_results["me after logout"], 401),
                    ("refresh token dead after logout", lambda: lab_auth_results["refresh after logout"], 401),
                    ("each app has its own storage", fresh_apps_are_independent, True),
                ]
            )
            """
        ),
    ]


def _lab_exercise_3_cells() -> list[NotebookNode]:
    """Lab 6.5 exercise 3."""
    return [
        md(
            """
            #### Exercise 3 — Roles and scopes with 401/403 tests

            Tokens from `lab_scope_token(username, scopes)` carry `sub`, `role` and `scope`
            (space-separated). Write:

            - `get_lab_principal(security_scopes, token) -> dict` with `token` from
              `OAuth2PasswordBearer(tokenUrl="/token")`: decode with `LAB_SECRET` (HS256); an
              invalid token → **401** with `WWW-Authenticate: Bearer scope="<required scopes>"`.
              The effective scopes are the token's scopes **intersected** with
              `ROLE_SCOPES[role]` (a token cannot grant more than the role has). A required
              scope missing → **403**. Return `{"user": sub, "role": role, "scopes": set}`.
            - `build_scoped_lab_app() -> FastAPI` with `GET /notes` (needs `notes:read`,
              returns `{"user": ...}`), `POST /notes` (needs `notes:write`, status 201) and
              `DELETE /admin/notes`, which checks the **role first** (a route-level dependency
              on the principal: role not `admin` → 403 `{"detail": "admin role required"}`) and
              then the `admin` **scope** (403 if the token lacks it).

            The check cell is written the way you would write the pytest suite: a table of
            (who, which scopes, request) → expected status.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            lab_scope_scheme = OAuth2PasswordBearer(tokenUrl="/token")


            def get_lab_principal(
                security_scopes: SecurityScopes, token: Annotated[str, Depends(lab_scope_scheme)]
            ) -> dict[str, object]:
                """Authenticate (401), then check the required scopes (403)."""
                raise NotImplementedError


            def build_scoped_lab_app() -> FastAPI:
                """GET/POST /notes and DELETE /admin/notes with scopes and a role check."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 3. The status table:"),
        code(
            r'''
            SCOPE_TABLE = [
                # (user or None, token scopes, method, path, expected status)
                (None, set(), "GET", "/notes", 401),
                ("rita", {"notes:read"}, "GET", "/notes", 200),
                ("rita", {"notes:read"}, "POST", "/notes", 403),
                ("rita", {"notes:read", "notes:write"}, "POST", "/notes", 403),  # more than the role has
                ("eddie", {"notes:read", "notes:write"}, "POST", "/notes", 201),
                ("eddie", {"notes:read"}, "POST", "/notes", 403),  # the token was limited
                ("eddie", {"notes:read", "notes:write", "admin"}, "DELETE", "/admin/notes", 403),  # role
                ("ada", {"notes:read"}, "DELETE", "/admin/notes", 403),  # role ok, scope missing
                ("ada", {"admin"}, "DELETE", "/admin/notes", 200),
            ]


            def scope_statuses() -> list[int]:
                """The status of every row of SCOPE_TABLE."""
                statuses = []
                with TestClient(build_scoped_lab_app()) as client:
                    for user, scopes, method, path, _ in SCOPE_TABLE:
                        headers = {"Authorization": f"Bearer {lab_scope_token(user, scopes)}"} if user else {}
                        statuses.append(client.request(method, path, headers=headers).status_code)
                return statuses


            def scope_details() -> dict[str, object]:
                """The WWW-Authenticate header of a 401, a bad token, and the role message."""
                admin_claiming = lab_scope_token("eddie", {"notes:read", "notes:write", "admin"})
                with TestClient(build_scoped_lab_app()) as client:
                    bad = client.post("/notes", headers={"Authorization": "Bearer not-a-token"})
                    role = client.delete("/admin/notes", headers={"Authorization": f"Bearer {admin_claiming}"})
                    return {
                        "bad token": bad.status_code,
                        "header": bad.headers.get("www-authenticate"),
                        "role": role.json(),
                    }
            '''
        ),
        md("The checks:"),
        code(
            r"""
            run_checks(
                [
                    ("status table", scope_statuses, [row[-1] for row in SCOPE_TABLE]),
                    ("an invalid token is a 401", lambda: scope_details()["bad token"], 401),
                    (
                        "401 names the required scope",
                        lambda: scope_details()["header"],
                        'Bearer scope="notes:write"',
                    ),
                    ("role message", lambda: scope_details()["role"], {"detail": "admin role required"}),
                    (
                        "GET /notes names the user",
                        lambda: (
                            TestClient(build_scoped_lab_app())
                            .get(
                                "/notes",
                                headers={"Authorization": f"Bearer {lab_scope_token('rita', {'notes:read'})}"},
                            )
                            .json()
                        ),
                        {"user": "rita"},
                    ),
                ]
            )
            """
        ),
    ]


def _lab_exercise_4_cells() -> list[NotebookNode]:
    """Lab 6.5 exercise 4."""
    return [
        md(
            """
            #### Exercise 4 — A BOLA test

            Write `find_bola(app: FastAPI) -> list[str]`, a test that finds broken object level
            authorization in an app built by `build_doc_api`. With a `TestClient`:

            1. `alice` creates a document (`POST /documents`, header `X-User: alice`).
            2. `mallory` tries `GET /documents/{id}`, `PATCH /documents/{id}` (`{"title": "pwned"}`),
               `GET /documents` (does alice's document appear?) and, last, `DELETE /documents/{id}`.
            3. Return the sorted labels of the routes that leaked: `"GET /documents/{id}"`,
               `"PATCH /documents/{id}"`, `"GET /documents"`, `"DELETE /documents/{id}"`. A route leaks if
               mallory's request succeeded (2xx), or for the list, if alice's document is in it.

            A safe app must give `[]`.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            def find_bola(app: FastAPI) -> list[str]:
                """Routes through which one user reaches another user's document."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 4:"),
        code(
            r"""
            ALL_DOC_ROUTES = [
                "DELETE /documents/{id}",
                "GET /documents",
                "GET /documents/{id}",
                "PATCH /documents/{id}",
            ]
            run_checks(
                [
                    ("safe app: no findings", lambda: find_bola(build_doc_api()), []),
                    (
                        "leaky read",
                        lambda: find_bola(build_doc_api(frozenset({"GET /documents/{id}"}))),
                        ["GET /documents/{id}"],
                    ),
                    (
                        "leaky update",
                        lambda: find_bola(build_doc_api(frozenset({"PATCH /documents/{id}"}))),
                        ["PATCH /documents/{id}"],
                    ),
                    (
                        "leaky list",
                        lambda: find_bola(build_doc_api(frozenset({"GET /documents"}))),
                        ["GET /documents"],
                    ),
                    (
                        "leaky delete",
                        lambda: find_bola(build_doc_api(frozenset({"DELETE /documents/{id}"}))),
                        ["DELETE /documents/{id}"],
                    ),
                    (
                        "everything leaks",
                        lambda: find_bola(build_doc_api(frozenset(ALL_DOC_ROUTES))),
                        ALL_DOC_ROUTES,
                    ),
                ]
            )
            """
        ),
    ]


def _lab_exercise_5_cells() -> list[NotebookNode]:
    """Lab 6.5 exercise 5."""
    return [
        md(
            """
            #### Exercise 5 — Login rate limiting

            - `LoginRateLimiter(redis, limit, window_seconds, clock)` with
              `async hit(key) -> tuple[bool, int]`: a **fixed window** on Redis. The window
              number is `int(clock() // window_seconds)`; `INCR` a key that contains it and
              set an expiry. Return `(count <= limit, retry_after)` where `retry_after` is the
              whole seconds until the window ends (`math.ceil`, at least 1).
            - `build_rate_limited_login(limiter) -> FastAPI` with `POST /login` (OAuth2 password
              form) checking `LAB_LOGIN_USERS`. Count **every** attempt under the key
              `"<client address>:<lower-cased username>"` **before** checking the password;
              over the limit → 429 with a `Retry-After` header (even with the right password);
              otherwise 401 for a wrong password and 200 `{"ok": true}` for the right one.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            class LoginRateLimiter:
                """Fixed-window attempt counter in Redis."""

                def __init__(
                    self, redis_client: Any, limit: int, window_seconds: int, clock: Callable[[], float]
                ) -> None:
                    """Keep the settings."""
                    raise NotImplementedError

                async def hit(self, key: str) -> tuple[bool, int]:
                    """Count one attempt; return (allowed, retry_after seconds)."""
                    raise NotImplementedError


            def build_rate_limited_login(limiter: LoginRateLimiter) -> FastAPI:
                """POST /login with attempt limits."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 5. The limiter scenario (awaited here, because `hit` is async):"),
        code(
            r'''
            async def limiter_scenario() -> dict[str, object]:
                """Six hits, a second key, then the next window."""
                clock = SettableClock(1_800_000_010.0)  # 10 s into a 60 s window
                limiter = LoginRateLimiter(fakeredis.FakeAsyncRedis(decode_responses=True), 5, 60, clock)
                hits = [await limiter.hit("1.2.3.4:asha") for _ in range(6)]
                other_key = await limiter.hit("1.2.3.4:ravi")
                clock.advance(50)
                return {"hits": hits, "other key": other_key, "next window": await limiter.hit("1.2.3.4:asha")}


            lab_limiter_results: dict[str, object] = {}
            with contextlib.suppress(Exception):
                lab_limiter_results = await limiter_scenario()


            def login_statuses() -> dict[str, object]:
                """Five wrong passwords, then the right one, then another user."""
                limiter = LoginRateLimiter(
                    fakeredis.FakeAsyncRedis(decode_responses=True), 5, 60, SettableClock()
                )
                with TestClient(build_rate_limited_login(limiter)) as client:
                    wrong = [
                        client.post(
                            "/login", data={"username": "Asha@example.com", "password": "x"}
                        ).status_code
                        for _ in range(5)
                    ]
                    blocked = client.post(
                        "/login", data={"username": "asha@example.com", "password": "a-long-passphrase"}
                    )
                    other = client.post(
                        "/login", data={"username": "ravi@example.com", "password": "x"}
                    ).status_code
                    return {
                        "wrong": wrong,
                        "blocked": blocked.status_code,
                        "retry": blocked.headers.get("retry-after"),
                        "other": other,
                    }
            '''
        ),
        md("The checks:"),
        code(
            r"""
            run_checks(
                [
                    (
                        "five allowed, the sixth refused",
                        lambda: [allowed for allowed, _ in lab_limiter_results["hits"]],
                        [True] * 5 + [False],
                    ),
                    (
                        "retry_after counts down to the window end",
                        lambda: lab_limiter_results["hits"][-1][1],
                        50,
                    ),
                    ("keys are independent", lambda: lab_limiter_results["other key"], (True, 50)),
                    ("next window starts fresh", lambda: lab_limiter_results["next window"], (True, 60)),
                    ("wrong passwords: 401 five times", lambda: login_statuses()["wrong"], [401] * 5),
                    ("then 429, even with the right password", lambda: login_statuses()["blocked"], 429),
                    ("Retry-After header", lambda: login_statuses()["retry"], "60"),
                    ("another username is not blocked", lambda: login_statuses()["other"], 401),
                ]
            )
            """
        ),
    ]


def _lab_exercise_6_cells() -> list[NotebookNode]:
    """Lab 6.5 exercise 6."""
    return [
        md(
            """
            #### Exercise 6 — A log redaction filter

            Write `RedactingFilter(logging.Filter)`. Its `filter(record)` formats the message
            (`record.getMessage()`, so `%` arguments are included), redacts it, stores the
            result in `record.msg`, sets `record.args = None` and returns `True` (never drop a
            record). Redact, in this order:

            1. `Bearer <token>` (any case) → `Bearer [REDACTED]`.
            2. The value of the keys `password`, `secret`, `token`, `api_key`, `refresh_token`
               (any case) in the forms `key=value`, `key: value` and quoted `"key": "value"`
               (or with `'` quotes, as in a printed dict) → the value becomes `[REDACTED]`
               (quotes kept).
            3. JWT-shaped strings (`eyJ...` with three dot-separated base64url parts) →
               `[REDACTED]`.
            4. Notes API keys `nk_` + at least 20 characters from `[A-Za-z0-9_-]` →
               `nk_[REDACTED]`.

            A value ends at whitespace, `,`, `;`, `&` or (quoted form) the closing quote.
            """
        ),
        md("Your solution:"),
        code(
            r'''
            class RedactingFilter(logging.Filter):
                """Remove secrets from log records before any handler sees them."""

                def filter(self, record: logging.LogRecord) -> bool:
                    """Redact the formatted message in place; always keep the record."""
                    raise NotImplementedError
            '''
        ),
        md(
            "Check exercise 6. `redacted(message, *args)` logs through the filter and returns the line:"
        ),
        code(
            r'''
            def redacted(message: str, *args: object) -> str:
                """Log one record through RedactingFilter; return the formatted line."""
                logger = logging.getLogger("lab65.redaction")
                logger.propagate = False
                handler = LabListHandler()
                logger.handlers[:] = [handler]
                logger.filters[:] = [RedactingFilter()]
                logger.warning(message, *args)
                return handler.lines[-1] if handler.lines else "<record dropped>"


            SAMPLE_JWT = jwt.encode({"sub": "1"}, "k" * 32, algorithm="HS256")
            SAMPLE_KEY = "nk_" + "A1b2C3d4E5f6G7h8I9j0K_-z"
            '''
        ),
        md("The checks:"),
        code(
            r"""
            run_checks(
                [
                    (
                        "bearer token",
                        lambda: redacted("header Authorization: Bearer abc.def.ghi"),
                        "header Authorization: Bearer [REDACTED]",
                    ),
                    (
                        "bearer in an argument",
                        lambda: redacted("auth=%s", "bearer xyz"),
                        "auth=bearer [REDACTED]",
                    ),
                    (
                        "key=value",
                        lambda: redacted("login password=hunter2 user=asha"),
                        "login password=[REDACTED] user=asha",
                    ),
                    ("key: value", lambda: redacted("Secret: s3cr3t; ok"), "Secret: [REDACTED]; ok"),
                    (
                        "JSON field",
                        lambda: redacted('body {"email": "a@x.org", "password": "p w d"}'),
                        'body {"email": "a@x.org", "password": "[REDACTED]"}',
                    ),
                    (
                        "dict argument",
                        lambda: redacted("payload %s", {"refresh_token": "abc123"}),
                        "payload {'refresh_token': '[REDACTED]'}",
                    ),
                    (
                        "query string",
                        lambda: redacted("GET /cb?code=1&token=zzz&state=2"),
                        "GET /cb?code=1&token=[REDACTED]&state=2",
                    ),
                ]
            )
            """
        ),
        md("More checks:"),
        code(
            r"""
            run_checks(
                [
                    (
                        "bare JWT",
                        lambda: redacted("got %s from the client", SAMPLE_JWT),
                        "got [REDACTED] from the client",
                    ),
                    ("API key", lambda: redacted("key %s used", SAMPLE_KEY), "key nk_[REDACTED] used"),
                    ("short nk_ word kept", lambda: redacted("nk_short stays"), "nk_short stays"),
                    (
                        "innocent text unchanged",
                        lambda: redacted("user %s created note %d", "asha", 7),
                        "user asha created note 7",
                    ),
                ]
            )
            """
        ),
    ]


def _notes_v4_intro_cells() -> list[NotebookNode]:
    """Notes API v4: introduction and pruning."""
    return [
        md(
            """
            ### Notes API v4 — the project files

            Until now anyone with the URL could read and change every note. v4 adds users and
            everything this unit covered:

            | v3 (Unit 6.4) | v4 (this unit) |
            | --- | --- |
            | no users | `users` table; register with Argon2id hashes (`pwdlib`), rehash on login, dummy hash for unknown e-mails |
            | every note visible to everyone | `notes.owner_id`; every query filters by owner; another user's note is a **404** (BOLA) |
            | one shared admin API key | JWT access tokens (15 min, HS256 fixed) + rotating refresh tokens (hashed, families, reuse detection), logout with a Redis `jti` denylist |
            | — | OAuth2 scopes `notes:read` / `notes:write` / `admin` via `Security`; roles `user` / `admin`; personal **API keys** (hashed, scoped) |
            | — | OIDC login (Authorization Code + PKCE) when a provider is configured; tested against a respx fake |
            | — | Redis: login/registration **rate limits** (429 + `Retry-After`), the denylist, OAuth state |
            | HTML pages open to all | login page; session in an **HttpOnly, SameSite=Lax** cookie; **double-submit CSRF** on every form |
            | link previews follow redirects to anywhere | SSRF defences: public addresses only, no redirects, 64 KiB cap |
            | — | `SecurityHeadersMiddleware` (HSTS, CSP, nosniff, frame denial), log redaction, production checks for secrets |
            | migrations `0001`–`0003` | `0004` users + ownership (with a legacy owner for existing notes), `0005` refresh tokens + API keys |

            The cells write the 45 files that change or are new (of 63). First, remove files
            of other versions (nothing after a full run; the Unit 6.6 files when you re-run
            this section later):
            """
        ),
        code(
            r'''
            NOTES_V4_FILES = """
            .env.example README.md alembic.ini alembic/env.py alembic/script.py.mako
            alembic/versions/0001_create_notes.py alembic/versions/0002_tags_many_to_many.py
            alembic/versions/0003_version_and_search.py alembic/versions/0004_users_and_ownership.py
            alembic/versions/0005_refresh_tokens_and_api_keys.py compose.yaml pyproject.toml ruff.toml
            src/notes_api/__init__.py src/notes_api/auth.py src/notes_api/core/__init__.py
            src/notes_api/core/config.py src/notes_api/core/errors.py src/notes_api/core/lifespan.py
            src/notes_api/core/logging.py src/notes_api/core/middleware.py src/notes_api/db.py
            src/notes_api/dependencies.py src/notes_api/exceptions.py src/notes_api/main.py
            src/notes_api/models.py src/notes_api/oauth.py src/notes_api/pagination.py
            src/notes_api/ratelimit.py src/notes_api/repositories.py src/notes_api/routers/__init__.py
            src/notes_api/routers/admin.py src/notes_api/routers/auth.py src/notes_api/routers/health.py
            src/notes_api/routers/notes.py src/notes_api/routers/pages.py src/notes_api/routers/users.py
            src/notes_api/schemas.py src/notes_api/security.py src/notes_api/services.py
            src/notes_api/static/style.css src/notes_api/templates/_note.html
            src/notes_api/templates/_notes.html src/notes_api/templates/base.html
            src/notes_api/templates/index.html src/notes_api/templates/login.html tests/conftest.py
            tests/helpers.py tests/test_admin.py tests/test_auth.py tests/test_bola.py tests/test_errors.py
            tests/test_links.py tests/test_middleware.py tests/test_migrations.py tests/test_notes.py
            tests/test_oauth.py tests/test_pages.py tests/test_pagination.py tests/test_postgres.py
            tests/test_repository.py tests/test_security.py tests/test_settings.py
            """.split()
            print("removed:", prune_notes_project(NOTES_V4_FILES))
            print(f"{len(NOTES_V4_FILES)} files in v4")
            '''
        ),
    ]


def _notes_v4_try_cells() -> list[NotebookNode]:
    """Notes API v4: try it in the kernel."""
    return [
        md(
            """
            **Try it in the kernel.** Settings for a SQLite file with cheap Argon2 parameters
            and a generated JWT secret; Redis is replaced by fakeredis through
            `dependency_overrides` (the same override the test suite uses). Two users,
            ownership, an API key with only `notes:read`:
            """
        ),
        code(
            r"""
            notes_main = reload_notes_api()  # re-imports every notes_api module from disk
            NotesSettings = sys.modules["notes_api.core.config"].Settings
            notes_db = sys.modules["notes_api.db"]
            notes_dependencies = sys.modules["notes_api.dependencies"]

            demo_db = PHASE6_DIR / "notes_v4_demo.db"
            demo_db.unlink(missing_ok=True)
            notes_settings = NotesSettings(
                _env_file=None,
                environment="test",
                database_url=SecretStr(f"sqlite+aiosqlite:///{demo_db}"),
                jwt_secret=SecretStr(secrets.token_urlsafe(32)),
                password_time_cost=1,
                password_memory_kib=64,
                cookie_secure=False,
            )
            schema_engine = notes_db.create_engine_from_settings(notes_settings)
            async with schema_engine.begin() as connection:
                await connection.run_sync(notes_db.Base.metadata.create_all)
            await schema_engine.dispose()

            notes_app = notes_main.create_app(notes_settings)
            notes_logger = logging.getLogger("notes_api")
            notes_logger.handlers[:] = [logging.StreamHandler(sys.stdout)]  # show the app's security log here
            demo_redis = fakeredis.FakeAsyncRedis(decode_responses=True)
            notes_app.dependency_overrides[notes_dependencies.get_redis] = lambda: demo_redis
            print([route.path for route in notes_app.routes if "/auth/" in getattr(route, "path", "")])
            """
        ),
        md("`v4_login(client, email)` registers and logs in through the public endpoints:"),
        code(
            r'''
            def v4_login(client: TestClient, email: str, scope: str = "") -> dict[str, str]:
                """Register (ignoring 409) and log in with the password form; return the token pair."""
                client.post("/api/v1/auth/register", json={"email": email, "password": "a-long-passphrase"})
                form = {"username": email, "password": "a-long-passphrase", "scope": scope}
                return client.post("/api/v1/auth/token", data=form).json()


            with TestClient(notes_app) as client:
                asha, ravi = v4_login(client, "asha@example.com"), v4_login(client, "ravi@example.com")
                as_asha = {"Authorization": f"Bearer {asha['access_token']}"}
                as_ravi = {"Authorization": f"Bearer {ravi['access_token']}"}
                print("asha's token:", sorted(asha), "scope:", asha["scope"])
                note = client.post("/api/v1/notes", json={"title": "Asha's plan"}, headers=as_asha).json()
                print("asha reads :", client.get(f"/api/v1/notes/{note['id']}", headers=as_asha).status_code)
                print("ravi reads :", client.get(f"/api/v1/notes/{note['id']}", headers=as_ravi).status_code)
                print("ravi's list:", client.get("/api/v1/notes", headers=as_ravi).json()["total"])
                print("no token   :", client.get("/api/v1/notes").status_code)
                print("me         :", client.get("/api/v1/users/me", headers=as_asha).json())
            '''
        ),
        md(
            """
            A read-only API key, refresh rotation with reuse detection (the app logs it: the line
            appears in the output, with no token in it), and the security headers on a
            response:
            """
        ),
        code(
            r"""
            with TestClient(notes_app) as client:
                asha = v4_login(client, "asha@example.com")
                as_asha = {"Authorization": f"Bearer {asha['access_token']}"}
                created_key = client.post(
                    "/api/v1/users/me/api-keys",
                    json={"name": "report bot", "scopes": ["notes:read"]},
                    headers=as_asha,
                ).json()
                print("key shown once:", created_key["key"][:10] + "...", created_key["scopes"])
                as_bot = {"X-API-Key": created_key["key"]}
                print("bot lists  :", client.get("/api/v1/notes", headers=as_bot).status_code)
                print(
                    "bot writes :",
                    client.post("/api/v1/notes", json={"title": "x"}, headers=as_bot).json()["detail"],
                )
                rotated = client.post("/api/v1/auth/refresh", json={"refresh_token": asha["refresh_token"]})
                print("refresh    :", rotated.status_code)
                reused = client.post("/api/v1/auth/refresh", json={"refresh_token": asha["refresh_token"]})
                print("reuse      :", reused.status_code, reused.json()["detail"])
                newest = client.post(
                    "/api/v1/auth/refresh", json={"refresh_token": rotated.json()["refresh_token"]}
                )
                print("newest     :", newest.status_code, "(the family was revoked)")
                show_response(
                    client.get("/health"),
                    "strict-transport-security",
                    "content-security-policy",
                    "x-frame-options",
                )
            """
        ),
    ]


def _notes_v4_run_cells() -> list[NotebookNode]:
    """Notes API v4: migrations, a real server, the test suite, clean up."""
    return [
        md(
            """
            **The migrations on existing data.** A fresh SQLite file goes to `0003` (v3's
            schema), gets two notes the old way (no owner), then upgrades to `head`: migration
            `0004` creates the inactive legacy owner and assigns the notes to it before making
            `owner_id` required:
            """
        ),
        code(
            r'''
            migration_db = PHASE6_DIR / "notes_v4_alembic.db"
            migration_db.unlink(missing_ok=True)
            NOTES_DB_URL = f"sqlite+aiosqlite:///{migration_db}"
            NOTES_DB_ENV = {"NOTES_DATABASE_URL": NOTES_DB_URL}


            def notes_alembic(*arguments: str) -> str:
                """Run alembic in projects/notes_api against NOTES_DB_URL; return its log lines."""
                run = run_in_notes(sys.executable, "-m", "alembic", *arguments, extra_env=NOTES_DB_ENV)
                lines = [
                    re.sub(r"^INFO  \[alembic\.\S+\] ", "", line)
                    for line in (run.stdout + run.stderr).splitlines()
                ]
                noise = ("Context impl", "Will assume", "setting up autogenerate plugin")
                return (
                    "\n".join(line for line in lines if line and not line.startswith(noise))
                    or f"exit code {run.returncode}"
                )


            print(notes_alembic("upgrade", "0003"))
            with sqlite3.connect(migration_db) as legacy:
                legacy.execute("INSERT INTO notes (title) VALUES ('Old note'), ('Older note')")
            print(notes_alembic("upgrade", "head"))
            with sqlite3.connect(migration_db) as migrated:
                print(migrated.execute("SELECT id, email, is_active, password_hash FROM users").fetchall())
                print(migrated.execute("SELECT title, owner_id FROM notes ORDER BY id").fetchall())
            print("current:", notes_alembic("current"))
            '''
        ),
        md(
            """
            **Serve it for real**: Uvicorn in a child process on the migrated SQLite file and
            the unit's **real Redis** container, with a JWT secret generated now. The login rate
            limit (5 per minute per address by default) answers the sixth wrong password with
            429 and `Retry-After`, for every Uvicorn worker, because the counter lives in Redis.
            Without Docker the cell prints a skip message:
            """
        ),
        code(
            r'''
            def served_v4_demo(base_url: str) -> None:
                """Register, log in, hit the rate limit, use the session-less API."""
                with httpx.Client(base_url=base_url, trust_env=False) as client:
                    client.post(
                        "/api/v1/auth/register",
                        json={"email": "live@example.com", "password": "a-long-passphrase"},
                    )
                    form = {"username": "live@example.com", "password": "a-long-passphrase"}
                    tokens = client.post("/api/v1/auth/token", data=form).json()
                    bearer = {"Authorization": f"Bearer {tokens['access_token']}"}
                    print(
                        "note created:",
                        client.post("/api/v1/notes", json={"title": "Served"}, headers=bearer).status_code,
                    )
                    attempts = [
                        client.post("/api/v1/auth/token", data=form | {"password": "wrong"}) for _ in range(5)
                    ]
                    print("wrong logins:", [reply.status_code for reply in attempts])
                    print(
                        "Retry-After :", attempts[-1].headers.get("retry-after"), attempts[-1].json()["title"]
                    )


            if REDIS_URL:
                served_env = {
                    **NOTES_DB_ENV,
                    "NOTES_REDIS_URL": REDIS_URL,
                    "NOTES_JWT_SECRET": secrets.token_urlsafe(32),
                }
                with uvicorn_server("notes_api.main:app", app_dir=NOTES_SRC, extra_env=served_env) as base_url:
                    served_v4_demo(base_url)
            else:
                print("SKIP the served demo: the login limiter needs Redis and Docker is not available")
            '''
        ),
        md(
            """
            (The successful login was the first attempt for this address and e-mail, so the
            fifth wrong password is the sixth attempt and gets the 429.)

            **Run the suite.** With the kernel's environment, the fast tests only
            (`-m "not postgres"`: SQLite and fakeredis):
            """
        ),
        code(
            r"""
            pytest_run = run_in_notes(
                sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-m", "not postgres"
            )
            print(tidy_test_output(pytest_run.stdout + pytest_run.stderr).splitlines()[-1])
            print(f"{pytest_run.returncode=}")
            """
        ),
        md(
            """
            And the whole suite as its own uv project: `uv lock` adds `pwdlib`, `pyjwt` and
            `redis` to `projects/notes_api/uv.lock`, then `uv run --frozen pytest` runs every
            test, including the PostgreSQL tests in their own container:
            """
        ),
        code(
            r"""
            if HAS_UV:
                lock_run = run_in_notes("uv", "lock")
                print(lock_summary(lock_run.stderr))
                if lock_run.returncode == 0:
                    uv_pytest = run_in_notes("uv", "run", "--frozen", "pytest", "-p", "no:cacheprovider", "-rs")
                    summary = tidy_test_output(uv_pytest.stdout).splitlines()
                    print(summary[-1], f"(exit code {uv_pytest.returncode})")
                    print(*[line for line in summary if line.startswith("SKIPPED")], sep="\n")
                else:
                    print("SKIP uv run pytest: uv lock failed (offline with an empty cache?)")
            else:
                print("SKIP: the uv command is not on PATH")
            """
        ),
        md("The project after Unit 6.5:"),
        code(
            r"""
            print(notes_tree())
            """
        ),
        md(
            """
            **Clean up.** Stop and remove the Redis container this unit started (the
            `atexit` hook would also do it when the kernel exits):
            """
        ),
        code(
            r"""
            if redis_container is not None:
                container_id = redis_container.get_wrapped_container().id
                stop_shared_redis()
                still_there = subprocess.run(
                    ["docker", "ps", "-aq", "--filter", f"id={container_id}"], capture_output=True, text=True
                ).stdout.strip()
                print(f"Redis container stopped and removed: {not still_there}")
            else:
                print("no container to stop")
            """
        ),
        md(
            """
            What v4 leaves for later: e-mails and webhooks are not sent, nothing is cached,
            and clients must poll for changes (Unit 6.6: background jobs, an outbox, WebSockets,
            SSE, ETags and Redis caching); logs, metrics and traces (6.7); a container image and
            production deployment (6.8).
            """
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 6.5."""
    return [
        md(
            """
            ### Recap — Unit 6.5

            | Concept | One-line takeaway | JS / TS equivalent |
            | --- | --- | --- |
            | AuthN vs AuthZ | 401 = who are you, 403/404 = not allowed; threat-model before coding | same HTTP semantics |
            | Sessions vs tokens | sessions revoke instantly; JWTs verify without lookups: combine short JWTs + stored refresh tokens | `express-session` vs `jsonwebtoken` |
            | Password storage | Argon2id via `pwdlib`; `verify_and_update` rehashes; dummy hash against enumeration | `argon2` / `bcrypt` packages |
            | Constant time | `hmac.compare_digest` for every secret comparison | `crypto.timingSafeEqual` |
            | JWT | signed, not encrypted; fix `algorithms`, check `aud`/`iss`/`exp`, require claims | `jwt.verify(token, key, { algorithms })` |
            | HS256 / RS256 / EdDSA | shared secret vs public verification (JWKS, `kid`) | `jose` |
            | Algorithm confusion | never trust the header's `alg`; PyJWT refuses `none` and RSA-keys-as-HMAC | `alg: none` bugs in old libraries |
            | Token lifecycle | rotate refresh tokens, revoke the family on reuse, deny the `jti` on logout | Auth0 refresh-token rotation |
            | FastAPI security classes | they extract credentials and document them; your dependency verifies | Passport strategies |
            | Scopes | `Security(dep, scopes=[...])` accumulates; `SecurityScopes` checks | NestJS guards + custom decorators |
            | Ownership | filter by owner in the query; 404 for foreign objects | Prisma `where: { ownerId }` |
            | Browser security | HttpOnly + Secure + SameSite cookies, CSRF tokens, explicit CORS origins | `cookie` options, `csurf`, `cors` |
            | OAuth 2.0 / OIDC | Authorization Code + PKCE; verify the ID token with the JWKS; `state` and `nonce` once only | `openid-client`, NextAuth |
            | API keys | random, prefixed, shown once, stored as SHA-256, scoped | same |
            | Rate limiting | Redis counters shared by all workers; 429 + `Retry-After` | `express-rate-limit` + Redis store |
            | OWASP API Top 10 | BOLA, authN, property-level, resources, function-level, flows, SSRF, config, inventory, unsafe consumption | same list |
            | Injection, headers, secrets | parameters not strings; HSTS/CSP; `SecretStr` + `.env`; bandit, pip-audit, log redaction | `helmet`, `npm audit` |

            **Further reading**

            - [FastAPI security tutorial](https://fastapi.tiangolo.com/tutorial/security/),
              [OAuth2 scopes](https://fastapi.tiangolo.com/advanced/security/oauth2-scopes/)
            - [pwdlib](https://frankie567.github.io/pwdlib/),
              [PyJWT](https://pyjwt.readthedocs.io/),
              [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
            - RFCs: [6749 OAuth 2.0](https://www.rfc-editor.org/rfc/rfc6749),
              [7519 JWT](https://www.rfc-editor.org/rfc/rfc7519),
              [7636 PKCE](https://www.rfc-editor.org/rfc/rfc7636),
              [8725 JWT best practices](https://www.rfc-editor.org/rfc/rfc8725),
              [9106 Argon2](https://www.rfc-editor.org/rfc/rfc9106),
              [OpenID Connect Core](https://openid.net/specs/openid-connect-core-1_0.html)
            - [OWASP API Security Top 10 (2023)](https://owasp.org/API-Security/editions/2023/en/0x11-t10/),
              [OWASP cheat sheets: CSRF, Session Management, SSRF](https://cheatsheetseries.owasp.org/)
            - [MDN: Set-Cookie](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Set-Cookie),
              [CORS](https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS),
              [CSP](https://developer.mozilla.org/en-US/docs/Web/HTTP/CSP)
            - Python: [`secrets`](https://docs.python.org/3/library/secrets.html),
              [`hmac`](https://docs.python.org/3/library/hmac.html),
              [`hashlib`](https://docs.python.org/3/library/hashlib.html),
              [`ipaddress`](https://docs.python.org/3/library/ipaddress.html),
              [`shlex`](https://docs.python.org/3/library/shlex.html),
              [`logging` filters](https://docs.python.org/3/library/logging.html#filter-objects),
              [PEP 506 (`secrets`)](https://peps.python.org/pep-0506/)
            - Tools: [bandit](https://bandit.readthedocs.io/),
              [pip-audit](https://github.com/pypa/pip-audit),
              [Authlib](https://docs.authlib.org/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 6.5, Lab 6.5 and Notes API v4."""
    return [
        *_overview_cells(),
        *_authn_cells(),
        *_password_cells(),
        *_jwt_cells(),
        *_lifecycle_cells(),
        *_fastapi_security_cells(),
        *_authz_cells(),
        *_browser_cells(),
        *_oauth_cells(),
        *_api_key_cells(),
        *_owasp_cells(),
        *_injection_cells(),
        *_predict_cells(),
        *_lab_setup_cells(),
        *_lab_exercise_1_cells(),
        *_lab_exercise_2_cells(),
        *_lab_exercise_3_cells(),
        *_lab_exercise_4_cells(),
        *_lab_exercise_5_cells(),
        *_lab_exercise_6_cells(),
        *_notes_v4_intro_cells(),
        *_notes_v4_project_cells(),
        *_notes_v4_core_cells(),
        *_notes_v4_model_cells(),
        *_notes_v4_security_cells(),
        *_notes_v4_router_cells(),
        *_notes_v4_test_cells(),
        *_notes_v4_try_cells(),
        *_notes_v4_run_cells(),
        *_recap_cells(),
    ]


def _notes_v4_project_cells() -> list[NotebookNode]:
    """Notes API v4: project metadata, environment template, README, compose."""
    return [
        md(
            """
            **Project metadata.** Version 0.4.0. New runtime packages: `pwdlib[argon2]`
            (password hashing), `pyjwt[crypto]` (JWT; `cryptography` verifies the RS256 ID
            tokens of the OIDC provider) and `redis` (rate limits, the token denylist, OAuth
            state). `fakeredis` joins the test dependencies:
            """
        ),
        *writefile_cells(
            NOTES_V4_PYPROJECT_TOML,
            [
                ("", "Part 1 of `pyproject.toml`: from `[project]`."),
                ("[tool.pytest.ini_options]", "Part 2: from `[tool.pytest.ini_options]`."),
            ],
        ),
        md(
            """
            `.env.example` gains the security settings, all with **placeholder** values.
            `NOTES_JWT_SECRET=change-me` is treated as *unset* (the app then generates a
            random secret per process), so copying the template never signs tokens with a
            published key. `NOTES_API_KEY` is gone: users create their own keys now:
            """
        ),
        code(NOTES_V4_ENV_EXAMPLE),
        md(
            """
            The README documents v4: how to run it with Redis, the auth endpoints and the new
            layout. It is written in parts at its `##` headings:
            """
        ),
        *writefile_cells(
            NOTES_V4_README_MD,
            [
                ("", "Part 1 of `README.md`: Notes API."),
                ("## Endpoints", "Part 2: Endpoints."),
                ("## Layout", "Part 3: Layout."),
            ],
        ),
        md(
            "`compose.yaml` adds a Redis 7.4 service next to PostgreSQL (both bound to `127.0.0.1` only):"
        ),
        code(NOTES_V4_COMPOSE_YAML),
    ]


def _notes_v4_core_cells() -> list[NotebookNode]:
    """Notes API v4: version, settings, exceptions, errors, logging, middleware, lifespan."""
    return [
        md("Version 0.4.0:"),
        code(NOTES_V4_INIT_PY),
        md(
            """
            **Settings.** Redis, the JWT secret, issuer and audience, token lifetimes, Argon2
            cost parameters, admin e-mails, login rate limits, the cookie `Secure` flag and
            the optional OIDC provider. The production validator refuses a missing,
            placeholder or short JWT secret and insecure cookies:
            """
        ),
        *writefile_cells(
            NOTES_V4_CORE_CONFIG_PY,
            [
                (
                    "",
                    "Part 1 of `core/config.py`: the module docstring and imports, then `Settings`.",
                ),
                (
                    '    app_name: str = "Notes API"',
                    "Part 2 (continues `Settings`): `oauth_enabled()` — True when every OpenID Connect setting is present.",
                ),
                (
                    '    @model_validator(mode="after")',
                    "Part 3 (continues `Settings`): `require_real_secrets_in_production()`; then `get_settings()` — The process-wide settings, read from the environment once and then cached.",
                ),
            ],
        ),
        md(
            """
            **Domain exceptions** gain `headers` (sent with the problem response) and the
            security errors: `AuthenticationError` (401 with `WWW-Authenticate: Bearer`, plus
            the required scopes), `PermissionDeniedError` (403), `EmailTakenError` (409),
            `RateLimitedError` (429 with `Retry-After`) and `ApiKeyNotFoundError` (404):
            """
        ),
        *writefile_cells(
            NOTES_V4_EXCEPTIONS_PY,
            [
                (
                    "",
                    "Part 1 of `exceptions.py`: the module docstring and imports, then `DomainError`, `NoteNotFoundError`, `VersionConflictError`.",
                ),
                (
                    "    def __init__(\n        self, note_id: int, expected: int | None = None, actual: int | None = None",
                    "Part 2 (continues `VersionConflictError`): `__init__()`; then `InvalidCursorError`, `UploadRejectedError`, `AuthenticationError` — A pagination cursor that this API did not issue.",
                ),
                (
                    "    def __init__(self, detail: str, scopes: list[str] | None = None) -> None:",
                    "Part 3 (continues `AuthenticationError`): `__init__()`; then `PermissionDeniedError`, `EmailTakenError`, `RateLimitedError` — Authenticated, but not allowed to do this (403).",
                ),
                (
                    "    def __init__(self, retry_after: int) -> None:",
                    "Part 4 (continues `RateLimitedError`): `__init__()`; then `ApiKeyNotFoundError` — The caller has no API key with this id (someone else's key is 'not found' too).",
                ),
            ],
        ),
        md(
            "`core/errors.py` changes one line: the domain handler passes `error.headers` on to the response."
        ),
        *writefile_cells(
            NOTES_V4_CORE_ERRORS_PY,
            [
                (
                    "",
                    "Part 1 of `core/errors.py`: the module docstring and imports, then `ProblemDetail`.",
                ),
                (
                    "def problem_response(",
                    "Part 2: `problem_response()` — Build an application/problem+json response; the request id links it to the logs.",
                ),
                (
                    "async def domain_error_handler(request: Request, error: DomainError) -> JSONResponse:",
                    "Part 3: `domain_error_handler()`, `http_error_handler()`, `validation_error_handler()` — DomainError subclasses → their own status, type and title.",
                ),
                (
                    "async def integrity_error_handler(request: Request, error: IntegrityError) -> JSONResponse:",
                    "Part 4: `integrity_error_handler()`, `unhandled_error_handler()`, `install_error_handlers()` — A constraint the database enforced (unique, foreign key) → 409, without SQL details.",
                ),
            ],
        ),
        md(
            """
            **`core/logging.py`** (new): a logging filter that redacts bearer tokens,
            passwords, API keys, cookies and JWT-shaped strings from every record, including
            its arguments, before any handler formats it (the solution of Lab 6.5 exercise 6,
            in the app):
            """
        ),
        *writefile_cells(
            NOTES_V4_CORE_LOGGING_PY,
            [
                (
                    "",
                    "Part 1 of `core/logging.py`: the module docstring and imports, then `redact_text()`, `redact_value()`, `RedactingFilter`.",
                ),
                (
                    "    def filter(self, record: logging.LogRecord) -> bool:",
                    "Part 2 (continues `RedactingFilter`): `filter()`; then `install_redaction()` — Attach the filter to the app's loggers (idempotent).",
                ),
            ],
        ),
        md(
            """
            `core/middleware.py` adds `SecurityHeadersMiddleware` (pure ASGI): HSTS,
            `nosniff`, `X-Frame-Options: DENY`, a referrer policy and a strict CSP on API
            responses; `/docs` gets a CSP that allows the Swagger UI files from the CDN:
            """
        ),
        *writefile_cells(
            NOTES_V4_CORE_MIDDLEWARE_PY,
            [
                (
                    "",
                    "Part 1 of `core/middleware.py`: the module docstring and imports, then `RequestIdMiddleware`.",
                ),
                (
                    "    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:",
                    "Part 2 (continues `RequestIdMiddleware`): `__call__()`; then `TimingMiddleware` — Add Server-Timing: app;dur=<ms>, measured until the response starts.",
                ),
                (
                    '    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:\n        """Time the inner app and report it in a header (milliseconds, one decimal)."""',
                    "Part 3 (continues `TimingMiddleware`): `__call__()`; then `API_CSP`, `DOCS_CSP`, `SECURITY_HEADERS` — Time the inner app and report it in a header (milliseconds, one decimal).",
                ),
                (
                    "class SecurityHeadersMiddleware:",
                    "Part 4: `SecurityHeadersMiddleware` — Pure ASGI: HSTS, CSP and friends on every HTTP response (OWASP API8).",
                ),
            ],
        ),
        md(
            """
            The lifespan opens a Redis client (lazy: it connects on the first command) and
            the HTTP client stops following redirects, so a link preview cannot be redirected
            to a private address:
            """
        ),
        code(NOTES_V4_CORE_LIFESPAN_PY),
    ]


def _notes_v4_model_cells() -> list[NotebookNode]:
    """Notes API v4: models, migrations, schemas, repositories, services."""
    return [
        md(
            """
            **Models.** `User` (unique e-mail, nullable password hash for OIDC-only users,
            role, `is_active`, unique `oidc_subject`), `RefreshToken` (only the SHA-256 of the
            token, a `family_id` for rotation, `used_at` / `revoked_at`), `ApiKey` (a short
            display prefix plus the hash, scopes, `last_used_at`) and `Note.owner_id`
            (foreign key, cascade, indexed):
            """
        ),
        *writefile_cells(
            NOTES_V4_MODELS_PY,
            [
                (
                    "",
                    "Part 1 of `models.py`: the module docstring and imports, then `utc_now()`, `TimestampMixin`, `User`.",
                ),
                (
                    "    id: Mapped[int] = mapped_column(primary_key=True)",
                    "Part 2 (continues `User`): `__repr__()`; then `RefreshToken`, `ApiKey` — One opaque refresh token (only its SHA-256 is stored); a family shares one login.",
                ),
                (
                    '    id: Mapped[int] = mapped_column(primary_key=True)\n    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)',
                    "Part 3 (continues `ApiKey`): more fields; then `Tag`, `Note` — A tag name, stored once and shared by many notes.",
                ),
                (
                    '    __tablename__ = "notes"',
                    "Part 4 (continues `Note`): `__repr__()` — Short form for logs and notebooks.",
                ),
            ],
        ),
        md(
            """
            **Migration 0004**: create `users`, then give every note an owner. It is an
            expand → migrate → contract migration: add `owner_id` as nullable, assign existing
            notes to an inactive *legacy owner* (only if there are notes), then make the
            column `NOT NULL` with its foreign key and index (batch mode, so it runs on
            SQLite too):
            """
        ),
        *writefile_cells(
            NOTES_V4_ALEMBIC_VERSIONS_0004_USERS_AND_OWNERSHIP_PY,
            [
                (
                    "",
                    "Part 1 of `alembic/versions/0004_users_and_ownership.py`: the module docstring and imports.",
                ),
                (
                    "def upgrade() -> None:",
                    "Part 2: `upgrade()` — Create users, add notes.owner_id (nullable), backfill it, then make it required.",
                ),
                (
                    "def downgrade() -> None:",
                    "Part 3: `downgrade()` — Drop ownership and the users table (the legacy account goes with it).",
                ),
            ],
        ),
        md("**Migration 0005**: the `refresh_tokens` and `api_keys` tables:"),
        *writefile_cells(
            NOTES_V4_ALEMBIC_VERSIONS_0005_REFRESH_TOKENS_AND_API_KEYS_PY,
            [
                (
                    "",
                    "Part 1 of `alembic/versions/0005_refresh_tokens_and_api_keys.py`: the module docstring and imports, then `timestamp()`.",
                ),
                (
                    "def upgrade() -> None:",
                    "Part 2: `upgrade()` — Two tables, both owned by a user (deleted with the user).",
                ),
                (
                    '    op.create_table(\n        "api_keys",',
                    "Part 3 (continues `upgrade()`): the rest of it; then `downgrade()` — Drop both tables.",
                ),
            ],
        ),
        md(
            """
            `schemas.py` adds the user-facing schemas. `UserCreate` has no `role` field and
            forbids extra fields, so a client cannot make itself an admin (mass assignment,
            OWASP API3); `UserRead` never contains the hash; `TokenPair` is the RFC 6749
            token response; `ApiKeyCreated` is the only response that shows a full key:
            """
        ),
        *writefile_cells(
            NOTES_V4_SCHEMAS_PY,
            [
                (
                    "",
                    "Part 1 of `schemas.py`: the module docstring and imports, then `require_slug()`, `unique_in_order()`.",
                ),
                (
                    "Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]",
                    "Part 2: `Title`, `Body`, `Tag`, `Tags`, `SortOrder`, ... — Body of POST /notes and PUT /notes/{note_id}: every field a client may set.",
                ),
                (
                    '    model_config = ConfigDict(\n        extra="forbid", json_schema_extra={"examples": [{"pinned": True, "version": 1}]}',
                    "Part 3 (continues `NoteUpdate`): `drop_duplicate_tags()`, `reject_explicit_null()`; then `NoteRead` — A note as the API returns it.",
                ),
                (
                    "    id: int",
                    "Part 4 (continues `NoteRead`): `word_count()`; then `NoteFilters`, `FeedParams` — Query parameters of GET /notes: filtering, sorting and pagination.",
                ),
                (
                    "class LinkPreview(BaseModel):",
                    "Part 5: `LinkPreview`, `ImportReport`, `ScopeName`, `UserCreate`, `UserRead` — The title of one link found in a note's body (or why it could not be fetched).",
                ),
                (
                    "    id: int\n    email: str",
                    "Part 6 (continues `UserRead`): more fields; then `TokenPair`, `RefreshRequest`, `ApiKeyCreate`, `ApiKeyRead` — The OAuth 2.0 token response (RFC 6749 section 5.1) plus our refresh token.",
                ),
                (
                    "    id: int\n    name: str",
                    "Part 7 (continues `ApiKeyRead`): `split_scopes()`; then `ApiKeyCreated` — The response to creating a key: the only time the full key is shown.",
                ),
            ],
        ),
        md(
            """
            **Repositories.** Every `NoteRepository` method that reads or writes notes takes
            an `owner_id` (`None` only for the admin export), so the ownership filter is in
            the SQL `WHERE`, not in the router. `SqlUserRepository` stores users, refresh
            tokens (`revoke_family`) and API keys:
            """
        ),
        *writefile_cells(
            NOTES_V4_REPOSITORIES_PY,
            [
                (
                    "",
                    "Part 1 of `repositories.py`: the module docstring and imports, then `NoteRepository`.",
                ),
                (
                    "    async def feed(self, limit: int, after: CursorKey | None, owner_id: int) -> list[Note]:",
                    "Part 2 (continues `NoteRepository`): `feed()`, `update()`, `delete()`, `delete_all()`; then `SqlNoteRepository` — NoteRepository on an AsyncSession: SQL filters, sorts and pages; tags always eager.",
                ),
                (
                    "    async def _tags(self, names: list[str]) -> list[Tag]:",
                    "Part 3 (continues `SqlNoteRepository`): `_tags()`, `_flush()`, `add()` — Tag rows for these names (sorted), creating missing ones; a savepoint absorbs a race.",
                ),
                (
                    '    async def get(self, note_id: int) -> Note | None:\n        """One note with its tags."""',
                    "Part 4 (continues `SqlNoteRepository`): `get()`, `search()`, `feed()` — One note with its tags.",
                ),
                (
                    '    async def update(self, note: Note, changes: dict[str, Any], now: datetime) -> Note:\n        """Change attributes; the flush sends UPDATE ... WHERE id = ? AND version = ?."""',
                    "Part 5 (continues `SqlNoteRepository`): `update()`, `delete()`, `delete_all()`; then `UserRepository` — What the auth service needs from storage.",
                ),
                (
                    "    async def user_by_email(self, email: str) -> User | None:",
                    "Part 6 (continues `UserRepository`): `user_by_email()`; then `SqlUserRepository` — Users, refresh tokens and API keys on the request's session.",
                ),
                (
                    "    async def add_refresh_token(self, token: RefreshToken) -> None:",
                    "Part 7 (continues `SqlUserRepository`): `add_refresh_token()`, `refresh_token_by_hash()`, `revoke_family()`, `add_api_key()`, ... — Store a refresh token row.",
                ),
            ],
        ),
        md(
            """
            **Services.** `NoteService` takes the caller's `owner_id`; `get` answers 404 for
            another user's note (not 403: the API does not confirm that the id exists). The
            link previewer gains its SSRF defences: only `http(s)`, every resolved address
            must be public (`ipaddress.is_global`), no redirects, at most 64 KiB read:
            """
        ),
        *writefile_cells(
            NOTES_V4_SERVICES_PY,
            [
                (
                    "",
                    "Part 1 of `services.py`: the module docstring and imports, then `NoteService`.",
                ),
                (
                    "    def __init__(",
                    "Part 2 (continues `NoteService`): `__init__()`, `create()`, `get()`, `search()`, ... — Keep the collaborators; every operation is limited to owner_id's notes.",
                ),
                (
                    "    async def update(self, note_id: int, changes: NoteUpdate) -> Note:",
                    "Part 3 (continues `NoteService`): `update()`, `delete()`, `import_notes()`; then `parse_import()` — Notes from a .json list or a .csv file (title, body, tags separated by ';', pinned).",
                ),
                (
                    "type Resolver = Callable[[str], Awaitable[list[str]]]",
                    "Part 4: `resolve_host()`, `is_public_address()`, `LinkPreviewer` — Every IP address a host name resolves to (getaddrinfo runs in a worker thread).",
                ),
                (
                    "    async def check_url(self, url: str) -> str | None:",
                    "Part 5 (continues `LinkPreviewer`): `check_url()`, `preview()` — None if the URL may be fetched, else the reason it may not.",
                ),
                (
                    "    async def previews(self, body: str) -> list[LinkPreview]:",
                    "Part 6 (continues `LinkPreviewer`): `previews()` — The first MAX_LINKS distinct links of a body, fetched concurrently.",
                ),
            ],
        ),
    ]


def _notes_v4_security_cells() -> list[NotebookNode]:
    """Notes API v4: security primitives, rate limiting, the auth service, OIDC, dependencies, main."""
    return [
        md(
            """
            **`security.py`** (new): the scopes and which roles get them, the password hasher
            factory, SHA-256 and constant-time comparison helpers, the `Principal` (who is
            calling, how, with which scopes) and `TokenService`, which issues and verifies
            access tokens with the algorithm, issuer and audience fixed by the server:
            """
        ),
        *writefile_cells(
            NOTES_V4_SECURITY_PY,
            [
                (
                    "",
                    "Part 1 of `security.py`: the module docstring and imports, then `make_password_hasher()`, `sha256_hex()`.",
                ),
                (
                    "def same_secret(first: str, second: str) -> bool:",
                    "Part 2: `same_secret()`, `new_secret()`, `Principal`, `AccessClaims`, `TokenService` — Constant-time comparison (no early exit an attacker could time).",
                ),
                (
                    "    def __init__(",
                    "Part 3 (continues `TokenService`): `__init__()`, `create_access_token()` — Keep the signing secret, the expected issuer/audience and the clock.",
                ),
                (
                    "    def decode_access_token(self, token: str) -> AccessClaims:",
                    "Part 4 (continues `TokenService`): `decode_access_token()` — Verify signature, algorithm, issuer, audience, time claims and type.",
                ),
            ],
        ),
        md(
            """
            **`ratelimit.py`** (new): a fixed-window limiter on Redis (`INCR` + `EXPIRE` in
            one pipeline), shared by every worker process; it reports the seconds until the
            window resets for `Retry-After`:
            """
        ),
        *writefile_cells(
            NOTES_V4_RATELIMIT_PY,
            [
                (
                    "",
                    "Part 1 of `ratelimit.py`: the module docstring and imports, then `RateLimitResult`, `FixedWindowRateLimiter`.",
                ),
                (
                    "    async def hit(self, key: str) -> RateLimitResult:",
                    "Part 2 (continues `FixedWindowRateLimiter`): `hit()` — Count one attempt for key in the current window.",
                ),
            ],
        ),
        md(
            """
            **`auth.py`** (new): `AuthService`, the token lifecycle of 6.5.4 in one class:
            registration, password login with a dummy hash for unknown e-mails (equal timing)
            and transparent rehashing, scope granting, refresh-token rotation with reuse
            detection (the family is revoked in its own transaction, so the revocation
            survives the 401), logout with a Redis denylist for the access token, and API
            keys:
            """
        ),
        *writefile_cells(
            NOTES_V4_AUTH_PY,
            [
                ("", "Part 1 of `auth.py`: the module docstring and imports, then `AuthService`."),
                (
                    "    def __init__(",
                    "Part 2 (continues `AuthService`): `__init__()`, `now()`, `register()` — Keep the collaborators (built per request by dependencies.get_auth_service).",
                ),
                (
                    "    async def authenticate(self, email: str, password: str) -> User:",
                    "Part 3 (continues `AuthService`): `authenticate()`, `grant_scopes()` — The user if the password matches; upgrade the hash if its parameters are outdated.",
                ),
                (
                    "    async def issue_tokens(",
                    "Part 4 (continues `AuthService`): `issue_tokens()`, `oidc_login()` — A new access token and a new refresh token (a new family unless rotating).",
                ),
                (
                    "    async def revoke_family_now(self, family_id: str) -> None:",
                    "Part 5 (continues `AuthService`): `revoke_family_now()`, `refresh()`, `logout()`, `deny_access_token()` — Revoke a token family in its own transaction, so a following 401 cannot undo it.",
                ),
                (
                    "    async def principal_from_access_token(self, raw_token: str) -> Principal:",
                    "Part 6 (continues `AuthService`): `principal_from_access_token()`, `principal_from_api_key()` — Verify an access token, check the denylist and the account.",
                ),
                (
                    "    async def create_api_key(self, principal: Principal, data: ApiKeyCreate) -> tuple[ApiKey, str]:",
                    "Part 7 (continues `AuthService`): `create_api_key()`, `revoke_api_key()` — A new key (returned once, in full) limited to scopes the account has.",
                ),
            ],
        ),
        md(
            """
            **`oauth.py`** (new): OpenID Connect login with Authorization Code + PKCE (6.5.8).
            `authorization_url()` stores state, nonce and the PKCE verifier in Redis for ten
            minutes; `finish()` consumes them once (`GETDEL`), exchanges the code and verifies
            the ID token against the provider's JWKS:
            """
        ),
        *writefile_cells(
            NOTES_V4_OAUTH_PY,
            [
                (
                    "",
                    "Part 1 of `oauth.py`: the module docstring and imports, then `pkce_challenge()`, `OidcClient`.",
                ),
                (
                    "    def __init__(self, settings: Settings, http_client: httpx.AsyncClient, redis: Redis) -> None:",
                    "Part 2 (continues `OidcClient`): `__init__()`, `authorization_url()` — Keep the provider settings, the shared HTTP client and Redis.",
                ),
                (
                    "    async def finish(self, code: str, state: str) -> dict[str, Any]:",
                    "Part 3 (continues `OidcClient`): `finish()` — Exchange the code (with the verifier) and return the verified ID-token claims.",
                ),
                (
                    "    async def verify_id_token(self, id_token: str) -> dict[str, Any]:",
                    "Part 4 (continues `OidcClient`): `verify_id_token()` — Check the signature with the provider's published keys, then iss, aud and exp.",
                ),
            ],
        ),
        md(
            """
            **`dependencies.py`**: the auth graph. `get_current_principal` accepts a bearer
            token or an `X-API-Key` and checks the scopes accumulated by `Security(...)`;
            `ReaderServiceDep` / `WriterServiceDep` require `notes:read` / `notes:write` and
            build a `NoteService` limited to the caller's notes; `require_admin` adds the role
            check on top of the `admin` scope:
            """
        ),
        *writefile_cells(
            NOTES_V4_DEPENDENCIES_PY,
            [
                ("", "Part 1 of `dependencies.py`: the module docstring and imports."),
                (
                    "def get_app_settings(request: Request) -> Settings:",
                    "Part 2: `get_app_settings()`, `get_session()`, `SessionDep`, `get_redis()`, `get_clock()`, ... — The settings this app was created with (create_app stores them on app.state).",
                ),
                (
                    "SettingsDep = Annotated[Settings, Depends(get_app_settings)]",
                    "Part 3: `SettingsDep`, `RedisDep`, `ClockDep`, `HttpClientDep`, `get_note_repository()`, ... — The SQL repository on this request's session.",
                ),
                (
                    "AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]",
                    "Part 4: `AuthServiceDep`, `get_current_principal()`, `CurrentPrincipal`, `require_admin()`, `AdminPrincipal` — Authenticate with a bearer token or an API key, then check the required scopes.",
                ),
                (
                    "def get_note_service(",
                    "Part 5: `get_note_service()`, `ReaderServiceDep`, `WriterServiceDep`, `get_link_previewer()`, `LinkPreviewerDep`, ... — A NoteService limited to the caller's notes; route scopes flow down to the principal.",
                ),
                (
                    "OidcClientDep = Annotated[OidcClient, Depends(get_oidc_client)]",
                    "Part 6: `OidcClientDep`, `get_cookie_principal()`, `CookiePrincipalDep` — The user of an HTML page, from the HttpOnly session cookie (None if absent or invalid).",
                ),
            ],
        ),
        md(
            """
            `main.py`: `install_security` puts the password hasher, a dummy hash and the JWT
            secret (random when unset or a placeholder) on `app.state`; the security-headers
            middleware is added; CORS allows the `Authorization` header; the docs are off in
            production; the auth and users routers are included:
            """
        ),
        *writefile_cells(
            NOTES_V4_MAIN_PY,
            [
                ("", "Part 1 of `main.py`: the module docstring and imports."),
                (
                    "def operation_id(route: APIRoute) -> str:",
                    "Part 2: `operation_id()`, `install_middleware()`, `install_security()` — Use the function name as the OpenAPI operationId (clean names in generated clients).",
                ),
                (
                    "def create_app(settings: Settings | None = None) -> FastAPI:",
                    "Part 3: `create_app()` — Build a fully wired app; tests pass their own Settings, servers use the environment.",
                ),
                ("app = create_app()", "Part 4: `app`."),
            ],
        ),
    ]


def _notes_v4_router_cells() -> list[NotebookNode]:
    """Notes API v4: routers, templates and static files."""
    return [
        md(
            """
            **`routers/auth.py`** (new): register and the token endpoint (both rate limited
            per client address), refresh, logout, and the OIDC login/callback pair (404 when
            no provider is configured). `/token` takes the OAuth2 password form, so the
            *Authorize* button of `/docs` works:
            """
        ),
        *writefile_cells(
            NOTES_V4_ROUTERS_AUTH_PY,
            [
                (
                    "",
                    "Part 1 of `routers/auth.py`: the module docstring and imports, then `client_ip()`, `enforce_limit()`.",
                ),
                (
                    '@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)',
                    "Part 2: `register()`, `login()`, `refresh()` — Create an account (rate limited per client address).",
                ),
                (
                    '@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)',
                    "Part 3: `logout()`, `oauth_login()`, `oauth_callback()` — Revoke the refresh-token family; also deny the access token sent, if any.",
                ),
            ],
        ),
        md(
            """
            **`routers/users.py`** (new): `GET /users/me`, and API keys: create (shown once;
            an API key cannot create keys), list, revoke:
            """
        ),
        *writefile_cells(
            NOTES_V4_ROUTERS_USERS_PY,
            [
                (
                    "",
                    "Part 1 of `routers/users.py`: the module docstring and imports, then `me()`, `create_api_key()`.",
                ),
                (
                    '@router.get("/me/api-keys", response_model=list[ApiKeyRead])',
                    "Part 2: `list_api_keys()`, `revoke_api_key()` — The caller's keys, without their secrets.",
                ),
            ],
        ),
        md(
            """
            `routers/notes.py`: the handlers are unchanged except for their service
            dependency: reads use `ReaderServiceDep`, writes `WriterServiceDep`, so every
            route needs a user with the right scope:
            """
        ),
        *writefile_cells(
            NOTES_V4_ROUTERS_NOTES_PY,
            [
                (
                    "",
                    "Part 1 of `routers/notes.py`: the module docstring and imports, then `create_note()`.",
                ),
                (
                    '@router.get("", response_model=Page[NoteRead])',
                    "Part 2: `list_notes()`, `notes_feed()`, `get_note()`, `replace_note()`, `update_note()` — Search, filter, sort and paginate notes (offset pagination).",
                ),
                (
                    '@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND)',
                    "Part 3: `delete_note()`, `note_links()` — Delete a note.",
                ),
            ],
        ),
        md(
            "`routers/admin.py`: the router-level API key becomes `Depends(require_admin)` (scope **and** role):"
        ),
        *writefile_cells(
            NOTES_V4_ROUTERS_ADMIN_PY,
            [
                (
                    "",
                    "Part 1 of `routers/admin.py`: the module docstring and imports, then `read_upload()`.",
                ),
                (
                    '@router.post("/import", response_model=ImportReport, status_code=status.HTTP_201_CREATED)',
                    "Part 2: `import_notes()`, `export_notes()`, `delete_all_notes()` — Create notes (owned by the admin) from an uploaded .json list or .csv file.",
                ),
            ],
        ),
        md(
            """
            **`routers/pages.py`**: the HTML pages now need a login. `POST /login` sets the
            access token in an **HttpOnly, SameSite=Lax** cookie (`Secure` per setting), and
            every form `POST` checks a **double-submit CSRF token**: a random value in a
            second cookie that the page repeats in a hidden field or the `X-CSRF-Token`
            header:
            """
        ),
        *writefile_cells(
            NOTES_V4_ROUTERS_PAGES_PY,
            [
                ("", "Part 1 of `routers/pages.py`: the module docstring and imports."),
                (
                    "def csrf_token(request: Request) -> str:",
                    "Part 2: `csrf_token()`, `check_csrf()`, `render()`, `to_login()` — The browser's CSRF token (a new one if it has none yet).",
                ),
                (
                    '@router.get("/login", response_class=HTMLResponse)',
                    "Part 3: `login_page()` — The login form.",
                ),
                (
                    '@router.post("/login", response_class=HTMLResponse)',
                    "Part 4: `login_form()` — Check CSRF and the password, then set an HttpOnly session cookie and redirect.",
                ),
                (
                    '@router.post("/logout")',
                    "Part 5: `logout_form()`, `notes_page()` — Deny the session token and delete the cookie.",
                ),
                (
                    '@router.post("/notes", response_class=HTMLResponse)',
                    "Part 6: `create_from_form()` — Create a note from the form, then redirect (303) so a reload does not re-post.",
                ),
                (
                    '@router.post("/notes/{note_id}/pin", response_class=HTMLResponse)',
                    "Part 7: `toggle_pin()` — HTMX: flip the pinned flag and return just this note's fragment.",
                ),
            ],
        ),
        md("`base.html`: HTMX requests send the CSRF token in a header:"),
        code(NOTES_V4_TEMPLATES_BASE_HTML),
        md("`index.html`: a logout form and the hidden CSRF field in the new-note form:"),
        code(NOTES_V4_TEMPLATES_INDEX_HTML),
        md("`login.html` (new): the login form:"),
        code(NOTES_V4_TEMPLATES_LOGIN_HTML),
        md("`style.css`: one rule for the header bar:"),
        code(NOTES_V4_STATIC_STYLE_CSS),
    ]


def _notes_v4_test_cells() -> list[NotebookNode]:
    """Notes API v4: the test suite."""
    return [
        md(
            """
            **Tests.** `conftest.py`: cheap Argon2 parameters (tests hash many passwords), a
            generated JWT secret, an in-memory Redis (`fakeredis`), fake DNS for link
            previews, and a `client` that is **logged in** as a normal user, so the v3 tests
            run unchanged as that user; `anonymous` is a client without a token:
            """
        ),
        *writefile_cells(
            NOTES_V4_TESTS_CONFTEST_PY,
            [
                (
                    "",
                    "Part 1 of `tests/conftest.py`: the module docstring and imports, then `anyio_backend()`.",
                ),
                (
                    "@pytest.fixture\ndef settings(tmp_path: Path) -> Settings:",
                    "Part 2: `settings()`, `fake_redis()`, `app()` — Test settings: a fresh SQLite file, a generated JWT secret, cheap Argon2 parameters.",
                ),
                (
                    "@pytest.fixture\ndef anonymous(app: FastAPI) -> Iterator[TestClient]:",
                    "Part 3: `anonymous()`, `client()`, `admin_headers()` — A TestClient without credentials; entering it runs the lifespan.",
                ),
            ],
        ),
        md(
            "`helpers.py` adds registration and login helpers, the fake resolver and its DNS table:"
        ),
        *writefile_cells(
            NOTES_V4_TESTS_HELPERS_PY,
            [
                (
                    "",
                    "Part 1 of `tests/helpers.py`: the module docstring and imports, then `create()`, `ids()`.",
                ),
                (
                    "def register(client: TestClient, email: str, password: str = PASSWORD) -> Any:",
                    "Part 2: `register()`, `login()`, `auth_headers()`, `fake_resolver()`, `create_tables()` — POST /auth/register (without the client's default credentials).",
                ),
            ],
        ),
        md(
            """
            **`test_auth.py`** (new): the token lifecycle end to end: registration rules,
            login (form and errors), `/users/me`, expiry, refresh rotation, reuse detection
            revoking the whole family, logout revoking both tokens, rehashing, rate limits
            with `Retry-After`:
            """
        ),
        *writefile_cells(
            NOTES_V4_TESTS_TEST_AUTH_PY,
            [
                (
                    "",
                    "Part 1 of `tests/test_auth.py`: the module docstring and imports, then `bearer()`, `test_register_returns_the_user_without_secrets()`, `test_register_rejects_weak_passwords_and_role_fields()`.",
                ),
                (
                    "def test_login_and_me(anonymous: TestClient) -> None:",
                    "Part 2: `test_login_and_me()`, `test_wrong_password_and_unknown_user_look_the_same()` — The password grant returns a token pair; /users/me needs the access token.",
                ),
                (
                    "def test_refresh_rotates_and_detects_reuse(anonymous: TestClient) -> None:",
                    "Part 3: `test_refresh_rotates_and_detects_reuse()`, `test_logout_revokes_refresh_and_access_tokens()` — A refresh token works once; replaying an old one revokes the whole family.",
                ),
                (
                    "def test_login_is_rate_limited(anonymous: TestClient) -> None:",
                    "Part 4: `test_login_is_rate_limited()`, `test_scopes_limit_what_a_token_can_do()`, `test_tampered_token_is_rejected()` — After the window's budget (10 in tests) the API answers 429 with Retry-After.",
                ),
                (
                    "def test_api_keys_are_shown_once_hashed_and_scoped(client: TestClient) -> None:",
                    "Part 5: `test_api_keys_are_shown_once_hashed_and_scoped()`, `test_api_keys_cannot_create_api_keys()` — Create a read-only key, use it, list it without the secret, revoke it.",
                ),
            ],
        ),
        md(
            """
            **`test_bola.py`** (new): broken object level authorization. Two users; every
            route that takes a note id must answer **404** for the other user's note, and
            lists, feeds and searches must never include it:
            """
        ),
        *writefile_cells(
            NOTES_V4_TESTS_TEST_BOLA_PY,
            [
                (
                    "",
                    "Part 1 of `tests/test_bola.py`: the module docstring and imports, then `intruder()`, `test_someone_elses_note_is_not_found()`.",
                ),
                (
                    "def test_lists_feeds_and_links_are_per_user(client: TestClient, intruder: dict[str, str]) -> None:",
                    "Part 2: `test_lists_feeds_and_links_are_per_user()` — Search, the feed and link previews only ever touch the caller's notes.",
                ),
            ],
        ),
        md(
            """
            **`test_security.py`** (new): scopes and roles (401 vs 403), API keys (hashed,
            scoped, revocable), algorithm confusion (`alg: none`, HS256 signed with another
            secret), token tampering, SSRF blocking and log redaction:
            """
        ),
        *writefile_cells(
            NOTES_V4_TESTS_TEST_SECURITY_PY,
            [
                (
                    "",
                    "Part 1 of `tests/test_security.py`: the module docstring and imports, then `b64()`.",
                ),
                (
                    "def stored_hash(settings: Settings, email: str) -> str:",
                    "Part 2: `stored_hash()`, `test_login_rehashes_outdated_hashes()` — The password hash in the database.",
                ),
                (
                    '@pytest.mark.parametrize("header", [{"alg": "none", "typ": "JWT"}, {"alg": "RS256", "typ": "JWT"}])',
                    "Part 3: `test_tokens_with_another_algorithm_are_rejected()` — The server fixes the algorithm (HS256); 'none' and algorithm-confusion tokens fail.",
                ),
                (
                    "def test_expired_and_foreign_tokens_are_rejected(anonymous: TestClient, app: FastAPI) -> None:",
                    "Part 4: `test_expired_and_foreign_tokens_are_rejected()`, `test_redaction_of_logged_secrets()` — Expiry, issuer and audience are all checked.",
                ),
                (
                    "@respx.mock",
                    "Part 5: `test_link_previews_refuse_private_targets()`, `test_link_previews_do_not_follow_redirects()` — SSRF (OWASP API7): private, loopback, link-local and unresolvable hosts are never fetched.",
                ),
                (
                    "def test_anonymous_cannot_read_notes(client: TestClient) -> None:",
                    "Part 6: `test_anonymous_cannot_read_notes()`, `test_placeholder_jwt_secret_is_never_used()` — Every notes route needs credentials (401 + WWW-Authenticate with the scope).",
                ),
            ],
        ),
        md(
            """
            **`test_oauth.py`** (new): the OIDC flow against a **mocked provider** (respx):
            a real RSA key signs the ID token, the JWKS is served by the fake, and the tests
            check PKCE, state reuse, nonce mismatch and unverified e-mails:
            """
        ),
        *writefile_cells(
            NOTES_V4_TESTS_TEST_OAUTH_PY,
            [
                ("", "Part 1 of `tests/test_oauth.py`: the module docstring and imports."),
                (
                    "def id_token(nonce: str, overrides: dict[str, Any] | None = None) -> str:",
                    "Part 2: `id_token()`, `oidc_client()` — An ID token as the provider would sign it (overrides replace claims).",
                ),
                (
                    "def start_login(client: TestClient) -> dict[str, str]:",
                    "Part 3: `start_login()`, `mock_provider()`, `test_full_login_with_pkce()` — GET /oauth/login and return the query parameters of the provider redirect.",
                ),
                (
                    "@respx.mock\ndef test_state_is_single_use(oidc_client: TestClient) -> None:",
                    "Part 4: `test_state_is_single_use()`, `test_bad_id_tokens_are_refused()` — An unknown or replayed state is refused before any call to the provider.",
                ),
                (
                    "@respx.mock\ndef test_existing_account_is_linked_by_verified_email(oidc_client: TestClient) -> None:",
                    "Part 5: `test_existing_account_is_linked_by_verified_email()`, `test_login_is_404_when_not_configured()`, `test_pkce_challenge_is_unpadded_base64url_sha256()` — A user who registered with a password can also sign in with the provider.",
                ),
            ],
        ),
        md(
            """
            `test_pages.py`: the pages behind the login: cookie flags, the CSRF check on
            every form (missing, wrong and correct tokens), logout:
            """
        ),
        *writefile_cells(
            NOTES_V4_TESTS_TEST_PAGES_PY,
            [
                (
                    "",
                    "Part 1 of `tests/test_pages.py`: the module docstring and imports, then `page_login()`, `test_pages_redirect_to_login()`, `test_login_sets_an_httponly_samesite_cookie()`.",
                ),
                (
                    "def test_wrong_password_shows_the_form_again(anonymous: TestClient) -> None:",
                    "Part 2: `test_wrong_password_shows_the_form_again()`, `test_page_lists_only_my_notes_escaped()`, `test_form_post_needs_the_csrf_token()`, `test_form_post_redirects_with_303()` — A failed login re-renders the form with a 401 and keeps the email.",
                ),
                (
                    "def test_invalid_form_is_shown_again_with_errors(anonymous: TestClient) -> None:",
                    "Part 3: `test_invalid_form_is_shown_again_with_errors()`, `test_htmx_search_and_pin()`, `test_logout_ends_the_session()`, `test_static_css_is_served()` — An invalid form re-renders the page (422) with the message and the typed values.",
                ),
            ],
        ),
        md(
            "`test_admin.py`: admin routes need the admin role **and** scope; a normal user gets 403:"
        ),
        *writefile_cells(
            NOTES_V4_TESTS_TEST_ADMIN_PY,
            [
                (
                    "",
                    "Part 1 of `tests/test_admin.py`: the module docstring and imports, then `test_admin_routes_need_an_admin()`, `test_admin_token_without_the_admin_scope_is_refused()`.",
                ),
                (
                    "@pytest.mark.parametrize(",
                    "Part 2: `test_import_json_and_csv()` — Both formats create the same notes.",
                ),
                (
                    '@pytest.mark.parametrize(\n    ("filename", "content", "content_type", "status"),',
                    "Part 3: `test_import_rejects_bad_files()`, `test_export_and_delete_all()` — Wrong type → 415, too large → 413, invalid content → 422; nothing is imported.",
                ),
            ],
        ),
        md(
            "`test_settings.py`: the production checks for the JWT secret and cookies, and placeholder secrets:"
        ),
        *writefile_cells(
            NOTES_V4_TESTS_TEST_SETTINGS_PY,
            [
                (
                    "",
                    "Part 1 of `tests/test_settings.py`: the module docstring and imports, then `test_environment_variables_are_parsed()`.",
                ),
                (
                    "def test_env_file_is_read_and_variables_win(",
                    "Part 2: `test_env_file_is_read_and_variables_win()`, `test_secrets_are_hidden_in_repr_and_dumps()`, `test_production_needs_a_strong_jwt_secret()` — A .env file supplies values; a real environment variable overrides it.",
                ),
                (
                    "def test_production_needs_secure_cookies() -> None:",
                    "Part 3: `test_production_needs_secure_cookies()`, `test_oauth_is_enabled_only_when_fully_configured()`, `test_get_settings_is_cached()` — Session cookies must be HTTPS-only in production.",
                ),
            ],
        ),
        md("`test_middleware.py`: the new middleware order and the security headers:"),
        *writefile_cells(
            NOTES_V4_TESTS_TEST_MIDDLEWARE_PY,
            [
                (
                    "",
                    "Part 1 of `tests/test_middleware.py`: the module docstring and imports, then `test_request_id_is_generated_echoed_or_replaced()`, `test_problem_bodies_carry_the_request_id()`, `test_server_timing_header()`.",
                ),
                (
                    "def test_large_responses_are_gzipped(client: TestClient) -> None:",
                    "Part 2: `test_large_responses_are_gzipped()`, `test_cors_preflight_for_an_allowed_and_a_foreign_origin()`, `test_simple_cors_request_exposes_headers()` — Responses over 1000 bytes are compressed when the client accepts gzip.",
                ),
                (
                    "def test_middleware_order(app: FastAPI) -> None:",
                    "Part 3: `test_middleware_order()`, `test_security_headers()` — Outermost first: request id, security headers, CORS, GZip, timing.",
                ),
            ],
        ),
        md(
            "`test_migrations.py`: the new tables, and notes created at `0003` get the legacy owner at `0004`:"
        ),
        *writefile_cells(
            NOTES_V4_TESTS_TEST_MIGRATIONS_PY,
            [
                (
                    "",
                    "Part 1 of `tests/test_migrations.py`: the module docstring and imports, then `alembic_config()`, `test_upgrade_downgrade_round_trip()`.",
                ),
                (
                    "def test_data_migration_moves_tags_and_back(tmp_path: Path) -> None:",
                    "Part 2: `test_data_migration_moves_tags_and_back()` — 0002 turns 'shop,food' text into rows; downgrading writes the text back.",
                ),
                (
                    "def test_existing_notes_get_a_disabled_legacy_owner(tmp_path: Path) -> None:",
                    "Part 3: `test_existing_notes_get_a_disabled_legacy_owner()` — 0004 gives notes written before accounts existed to an owner that cannot log in.",
                ),
            ],
        ),
        md("`test_repository.py`: notes now need an owner:"),
        *writefile_cells(
            NOTES_V4_TESTS_TEST_REPOSITORY_PY,
            [
                (
                    "",
                    "Part 1 of `tests/test_repository.py`: the module docstring and imports, then `session_factory()`.",
                ),
                (
                    "async def add_note(factory: async_sessionmaker[AsyncSession], **fields: object) -> int:",
                    "Part 2: `add_note()`, `test_tag_rows_are_shared()`, `test_lazy_loading_is_switched_off()` — Create and commit one note (owned by a user created on first use); return its id.",
                ),
                (
                    "async def test_timestamps_come_back_in_utc(",
                    "Part 3: `test_timestamps_come_back_in_utc()`, `test_concurrent_update_raises_version_conflict()`, `test_delete_all_counts_rows()` — UTCDateTime attaches UTC to SQLite's naive values.",
                ),
            ],
        ),
        md(
            "`test_postgres.py`: the PostgreSQL round trip logs in first; the tag race runs with an owner:"
        ),
        *writefile_cells(
            NOTES_V4_TESTS_TEST_POSTGRES_PY,
            [
                ("", "Part 1 of `tests/test_postgres.py`: the module docstring and imports."),
                (
                    "def docker_available() -> bool:",
                    "Part 2: `docker_available()`, `alembic_config()`, `postgres_url()` — True if a Docker daemon answers.",
                ),
                (
                    "@pytest.fixture\ndef empty_url(postgres_url: str) -> str:",
                    "Part 3: `empty_url()`, `test_models_match_the_migrations()` — The database with every row removed and ids restarted.",
                ),
                (
                    "def test_api_round_trip_on_postgres(empty_url: str) -> None:",
                    "Part 4: `test_api_round_trip_on_postgres()` — Create, search (ILIKE), feed, PATCH with versions and the 409, on the real database.",
                ),
                (
                    "def test_trigram_index_serves_substring_search(empty_url: str) -> None:",
                    "Part 5: `test_trigram_index_serves_substring_search()` — EXPLAIN shows ILIKE '%tea%' using the GIN trigram index (sequential scans off).",
                ),
                (
                    "def test_concurrent_new_tag_is_absorbed_by_the_savepoint(empty_url: str) -> None:",
                    "Part 6: `test_concurrent_new_tag_is_absorbed_by_the_savepoint()` — Two transactions add one new tag; a SAVEPOINT absorbs the loser's unique violation.",
                ),
                (
                    "    async def race() -> list[list[str]]:",
                    "Part 7 (continues `test_concurrent_new_tag_is_absorbed_by_the_savepoint()`): `race()` — Run the two transactions concurrently and report each note's tags.",
                ),
            ],
        ),
    ]


NOTES_V4_PYPROJECT_TOML = r"""
%%writefile ../projects/notes_api/pyproject.toml
[project]
name = "notes-api"
version = "0.4.0"
description = "The Phase 6 Notes API: a FastAPI service built step by step from Unit 6.2 to 6.8."
readme = "README.md"
requires-python = ">=3.15"
dependencies = [
    "fastapi[standard]>=0.163.1",
    "alembic>=1.20.1",
    "asyncpg>=0.32.0",
    "pwdlib[argon2]>=0.4.2",
    "pydantic-settings>=2.16.2",
    "pyjwt[crypto]>=2.15.1",
    "redis>=8.1.0",
    "sqlalchemy[asyncio]>=2.1.9",
]

[dependency-groups]
dev = [
    "aiosqlite>=0.22.1",
    "fakeredis>=2.40.0",
    "pytest>=9.2.0",
    "respx>=0.23.1",
    "testcontainers>=4.15.0",
]

[build-system]
requires = ["uv_build>=0.13,<0.14"]
build-backend = "uv_build"


[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
addopts = "-q"
markers = [
    "postgres: needs Docker; runs against PostgreSQL in a testcontainer",
]
filterwarnings = [
    "ignore::DeprecationWarning:testcontainers.*",
]
"""

NOTES_V4_ENV_EXAMPLE = r"""
%%writefile ../projects/notes_api/.env.example
# Copy this file to .env and fill in real values. .env is git-ignored: never commit secrets.
# Every variable starts with NOTES_ (see src/notes_api/core/config.py).
NOTES_ENVIRONMENT=development
NOTES_DEBUG=false
# A JSON list of browser origins allowed by CORS.
NOTES_CORS_ORIGINS=["http://localhost:5173"]
NOTES_MAX_UPLOAD_BYTES=1048576
NOTES_HTTP_TIMEOUT_SECONDS=5
# PostgreSQL and Redis from compose.yaml (docker compose up -d --wait); SQLite also works:
# NOTES_DATABASE_URL=sqlite+aiosqlite:///./notes.db
NOTES_DATABASE_URL=postgresql+asyncpg://notes:notes@localhost:5432/notes
NOTES_DATABASE_ECHO=false
NOTES_REDIS_URL=redis://localhost:6379/0
# Access tokens are signed with this secret (HS256). Required in production, 32+ characters:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"
# Left empty in development, the app makes a random one at startup (tokens die on restart).
NOTES_JWT_SECRET=change-me
NOTES_ACCESS_TOKEN_MINUTES=15
NOTES_REFRESH_TOKEN_DAYS=14
# Accounts registered with these addresses become admins (JSON list).
NOTES_ADMIN_EMAILS=[]
NOTES_LOGIN_RATE_LIMIT=5
NOTES_LOGIN_RATE_WINDOW_SECONDS=60
# Set to false only for plain-HTTP local development (the session cookie needs HTTPS otherwise).
NOTES_COOKIE_SECURE=true
# Optional: sign in with an OpenID Connect provider (all six values, or leave them out).
# NOTES_OAUTH_CLIENT_ID=notes-web
# NOTES_OAUTH_CLIENT_SECRET=change-me
# NOTES_OAUTH_AUTHORIZE_URL=https://id.example/authorize
# NOTES_OAUTH_TOKEN_URL=https://id.example/token
# NOTES_OAUTH_JWKS_URL=https://id.example/.well-known/jwks.json
# NOTES_OAUTH_ISSUER=https://id.example
"""

NOTES_V4_README_MD = r"""
%%writefile ../projects/notes_api/README.md
# Notes API

A FastAPI service for creating, searching and organizing notes. It is built step by step in
Phase 6 of the course (`notebooks/phase6_web_fastapi.ipynb`); the notebook writes these files.

| Version | Unit | Adds |
| --- | --- | --- |
| v1 | 6.2 | CRUD path operations, Pydantic v2 schemas, filtering and pagination, OpenAPI |
| v2 | 6.3 | `create_app()` factory, routers under `/api/v1`, settings, dependency injection, middleware, CORS, Problem Details errors, lifespan HTTP client, uploads, cursor pagination, HTML pages |
| v3 | 6.4 | PostgreSQL with async SQLAlchemy 2.0 (typed models, many-to-many tags), a session per request, Alembic migrations, optimistic locking (409), trigram search, keyset pagination on an index |
| v4 | 6.5 | users (Argon2id), JWT access tokens with scopes and roles, rotating refresh tokens with reuse detection, logout and revocation, owner-only notes, hashed API keys, Redis login rate limiting, cookie login with CSRF for the pages, OpenID Connect login, SSRF-safe link previews, security headers, log redaction |

## Run

```bash
cd projects/notes_api
cp .env.example .env                          # then set NOTES_JWT_SECRET (and the rest) in .env
docker compose up -d --wait                   # PostgreSQL 18 and Redis 7.4 on 127.0.0.1
uv run alembic upgrade head                   # create the tables
uv run uvicorn notes_api.main:app --reload    # http://127.0.0.1:8000/ and /docs
uv run pytest                                 # fast tests + PostgreSQL tests (need Docker)
uv run pytest -m "not postgres"               # only the fast tests (SQLite, fakeredis)
docker compose down                           # add -v to delete the data volume
```

Local plain HTTP: set `NOTES_COOKIE_SECURE=false`, or the browser will not send the session
cookie. Register `NOTES_ADMIN_EMAILS` addresses to get admin accounts.


## Endpoints

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| `GET` | `/health`, `/health/ready` | none | liveness; readiness runs `SELECT 1` |
| `POST` | `/api/v1/auth/register` | none | 201; rate limited; never accepts a role |
| `POST` | `/api/v1/auth/token` | none | OAuth2 password form (`username` = email, optional `scope`); rate limited (429 + `Retry-After`) |
| `POST` | `/api/v1/auth/refresh` | refresh token | rotation: each refresh token works once; reuse revokes the family |
| `POST` | `/api/v1/auth/logout` | refresh token (+ bearer) | revokes the family and denies the access token |
| `GET` | `/api/v1/auth/oauth/login`, `/oauth/callback` | none | OpenID Connect (Authorization Code + PKCE); 404 unless configured |
| `GET` | `/api/v1/users/me` | bearer or key | the current user |
| `POST/GET/DELETE` | `/api/v1/users/me/api-keys[/{id}]` | bearer | keys are shown once, stored as SHA-256, limited to scopes |
| `POST/GET` | `/api/v1/notes` | `notes:write` / `notes:read` | only the caller's notes |
| `GET` | `/api/v1/notes/feed` | `notes:read` | keyset pagination |
| `GET/PUT/PATCH/DELETE` | `/api/v1/notes/{note_id}` | `notes:read` / `notes:write` | someone else's note is a 404; PATCH `version` → 409 if stale |
| `GET` | `/api/v1/notes/{note_id}/links` | `notes:read` | link titles; private addresses are never fetched |
| `POST/GET/DELETE` | `/api/v1/admin/import`, `/export`, `/notes` | admin role + `admin` scope | bulk operations |
| `GET/POST` | `/login`, `/logout`, `/`, `/notes`, `/notes/{id}/pin` | session cookie + CSRF token | HTML (Jinja2 + HTMX) |

Credentials: `Authorization: Bearer <access token>` or `X-API-Key: nk_...`. Errors are
`application/problem+json` (RFC 9457). Every response carries `X-Request-ID`,
`Server-Timing` and security headers (HSTS, CSP, `X-Content-Type-Options`, `X-Frame-Options`).


## Layout

```text
src/notes_api/
├── main.py           # create_app(): settings, security, handlers, middleware, routers
├── core/             # config.py, errors.py, middleware.py, lifespan.py, logging.py (redaction)
├── routers/          # health, auth, users, notes, admin, pages  (HTTP only)
├── dependencies.py   # principal / scopes / roles, sessions, Redis, services as Annotated aliases
├── auth.py           # AuthService: register, login, rotate, logout, API keys, OIDC accounts
├── oauth.py          # OidcClient: Authorization Code + PKCE, ID-token verification
├── security.py       # Argon2id hasher, TokenService (PyJWT), Principal, scopes
├── ratelimit.py      # FixedWindowRateLimiter on Redis
├── services.py       # NoteService (owner-scoped), parse_import, LinkPreviewer (SSRF-safe)
├── repositories.py   # NoteRepository / SqlNoteRepository, SqlUserRepository
├── models.py         # User, RefreshToken, ApiKey, Note, Tag, note_tags
├── db.py             # Base (naming convention), UTCDateTime, engine, session factory
├── exceptions.py     # DomainError and subclasses (no FastAPI)
├── schemas.py        # Pydantic request/response models
├── pagination.py     # Page[T], CursorPage[T], cursors
├── templates/        # Jinja2 templates (login, notes)
└── static/           # CSS
alembic/              # env.py (async) + versions/0001-0005
compose.yaml          # local PostgreSQL and Redis
tests/                # pytest: one app, SQLite file and fakeredis per test;
                      # test_postgres.py runs on PostgreSQL in a testcontainer
```

Dependencies point inwards: routers → services → repositories → models. Nothing in
`services.py`, `auth.py`, `security.py`, `repositories.py`, `models.py`, `db.py` or
`exceptions.py` imports FastAPI; `core/errors.py` maps domain exceptions to HTTP responses.
"""

NOTES_V4_COMPOSE_YAML = r"""
%%writefile ../projects/notes_api/compose.yaml
# Local PostgreSQL and Redis for the Notes API:  docker compose up -d --wait   (stop: docker compose down)
# The password is for local development only; real deployments read secrets from the platform.
services:
  db:
    image: postgres:18-alpine
    environment:
      POSTGRES_USER: notes
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-notes}
      POSTGRES_DB: notes
    ports:
      - "127.0.0.1:${POSTGRES_PORT:-5432}:5432"
    volumes:
      - notes-db:/var/lib/postgresql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U notes -d notes"]
      interval: 2s
      timeout: 3s
      retries: 15

  redis:
    image: redis:7.4
    ports:
      - "127.0.0.1:${REDIS_PORT:-6379}:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 2s
      timeout: 3s
      retries: 15

volumes:
  notes-db:
"""

NOTES_V4_INIT_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/__init__.py
"""Notes API: a FastAPI service built step by step in Phase 6 of the course."""

__version__ = "0.4.0"
'''

NOTES_V4_CORE_CONFIG_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/core/config.py
"""Application settings: environment variables (prefix NOTES_) and an optional .env file."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_SECRETS = {"", "change-me"}
MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    """Every configurable value of the Notes API, validated once at startup."""

    model_config = SettingsConfigDict(
        env_prefix="NOTES_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Notes API"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    cors_origins: list[str] = ["http://localhost:5173"]
    max_upload_bytes: int = Field(default=1_048_576, gt=0)
    http_timeout_seconds: float = Field(default=5.0, gt=0)
    database_url: SecretStr = SecretStr("postgresql+asyncpg://notes:notes@localhost:5432/notes")
    database_echo: bool = False  # log every SQL statement (development only)
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")
    # Authentication: an HS256 secret (required in production; a random one per process otherwise)
    jwt_secret: SecretStr | None = None
    jwt_issuer: str = "notes-api"
    jwt_audience: str = "notes-api"
    access_token_minutes: int = Field(default=15, ge=1)
    refresh_token_days: int = Field(default=14, ge=1)
    password_time_cost: int = Field(default=3, ge=1)  # Argon2id parameters (tests lower them)
    password_memory_kib: int = Field(default=65_536, ge=32)  # Argon2 needs 8 KiB per lane (4)
    admin_emails: list[str] = []  # these addresses get the admin role when they register
    login_rate_limit: int = Field(default=5, ge=1)  # attempts per window, per IP + email
    login_rate_window_seconds: int = Field(default=60, ge=1)
    cookie_secure: bool = True  # session cookie only over HTTPS (False for local HTTP)
    # Third-party login (OpenID Connect, Authorization Code + PKCE); disabled until configured
    oauth_client_id: str | None = None
    oauth_client_secret: SecretStr | None = None
    oauth_authorize_url: str | None = None
    oauth_token_url: str | None = None
    oauth_jwks_url: str | None = None
    oauth_issuer: str | None = None
    oauth_redirect_url: str = "http://localhost:8000/api/v1/auth/oauth/callback"

    @property
    def oauth_enabled(self) -> bool:
        """True when every OpenID Connect setting is present."""
        required = (self.oauth_client_id, self.oauth_authorize_url, self.oauth_token_url)
        return all(required) and bool(self.oauth_jwks_url and self.oauth_issuer)

    @model_validator(mode="after")
    def require_real_secrets_in_production(self) -> Settings:
        """Refuse to start in production with a missing or weak JWT secret or insecure cookies."""
        if self.environment != "production":
            return self
        secret = None if self.jwt_secret is None else self.jwt_secret.get_secret_value()
        if secret is None or secret in PLACEHOLDER_SECRETS or len(secret) < MIN_JWT_SECRET_LENGTH:
            raise ValueError(
                f"NOTES_JWT_SECRET must be a random secret of at least {MIN_JWT_SECRET_LENGTH} "
                "characters in production"
            )
        if not self.cookie_secure:
            raise ValueError("NOTES_COOKIE_SECURE must be true in production")
        return self


@lru_cache
def get_settings() -> Settings:
    """The process-wide settings, read from the environment once and then cached."""
    return Settings()
'''

NOTES_V4_EXCEPTIONS_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/exceptions.py
"""Domain exceptions: plain Python, no FastAPI (core/errors.py maps them to HTTP)."""

from http import HTTPStatus


class DomainError(Exception):
    """A business rule failed. Subclasses choose the status, a problem type and a title."""

    status_code: int = HTTPStatus.BAD_REQUEST
    problem_type: str = "domain-error"
    title: str = "Request breaks a business rule"
    headers: dict[str, str] = {}


class NoteNotFoundError(DomainError, LookupError):
    """No note has the requested id."""

    status_code = HTTPStatus.NOT_FOUND
    problem_type = "note-not-found"
    title = "Note not found"

    def __init__(self, note_id: int) -> None:
        """Remember the id; the message becomes the problem's detail."""
        super().__init__(f"note {note_id} not found")
        self.note_id = note_id


class VersionConflictError(DomainError):
    """Optimistic locking: the note changed since the client (or this request) read it."""

    status_code = HTTPStatus.CONFLICT
    problem_type = "version-conflict"
    title = "Version conflict"

    def __init__(
        self, note_id: int, expected: int | None = None, actual: int | None = None
    ) -> None:
        """Explain which versions clashed when they are known."""
        if expected is None or actual is None:
            message = f"note {note_id} was changed by another request; read it again"
        else:
            message = f"note {note_id} is at version {actual}, not {expected}; read it again"
        super().__init__(message)
        self.note_id = note_id


class InvalidCursorError(DomainError, ValueError):
    """A pagination cursor that this API did not issue."""

    problem_type = "invalid-cursor"
    title = "Invalid cursor"


class UploadRejectedError(DomainError):
    """An uploaded file was too large, of the wrong type, or unreadable."""

    problem_type = "upload-rejected"
    title = "Upload rejected"

    def __init__(self, detail: str, status_code: int) -> None:
        """Keep the reason and the status (413, 415 or 422)."""
        super().__init__(detail)
        self.status_code = status_code


class AuthenticationError(DomainError):
    """Missing, invalid, expired or revoked credentials (401)."""

    status_code = HTTPStatus.UNAUTHORIZED
    problem_type = "not-authenticated"
    title = "Authentication required"

    def __init__(self, detail: str, scopes: list[str] | None = None) -> None:
        """Keep the reason; the WWW-Authenticate header tells clients how to authenticate."""
        super().__init__(detail)
        challenge = "Bearer"
        if scopes:
            challenge += f' scope="{" ".join(scopes)}"'
        self.headers = {"WWW-Authenticate": challenge}


class PermissionDeniedError(DomainError):
    """Authenticated, but not allowed to do this (403)."""

    status_code = HTTPStatus.FORBIDDEN
    problem_type = "forbidden"
    title = "Not allowed"


class EmailTakenError(DomainError):
    """Registration with an email that already has an account (409)."""

    status_code = HTTPStatus.CONFLICT
    problem_type = "email-taken"
    title = "Email already registered"


class RateLimitedError(DomainError):
    """Too many attempts; Retry-After says when to try again (429)."""

    status_code = HTTPStatus.TOO_MANY_REQUESTS
    problem_type = "rate-limited"
    title = "Too many requests"

    def __init__(self, retry_after: int) -> None:
        """Remember how many seconds the client must wait."""
        super().__init__(f"too many attempts; retry in {retry_after} s")
        self.retry_after = retry_after
        self.headers = {"Retry-After": str(retry_after)}


class ApiKeyNotFoundError(DomainError, LookupError):
    """The caller has no API key with this id (someone else's key is 'not found' too)."""

    status_code = HTTPStatus.NOT_FOUND
    problem_type = "api-key-not-found"
    title = "API key not found"

    def __init__(self, key_id: int) -> None:
        """Remember the id."""
        super().__init__(f"API key {key_id} not found")
        self.key_id = key_id
'''

NOTES_V4_CORE_ERRORS_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/core/errors.py
"""Domain errors and RFC 9457 Problem Details responses for every error the API returns."""

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from notes_api.core.middleware import REQUEST_ID_HEADER
from notes_api.exceptions import DomainError

PROBLEM_JSON = "application/problem+json"


class ProblemDetail(BaseModel):
    """The RFC 9457 body (used for the OpenAPI docs; responses are built as dicts)."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    request_id: str | None = None
    errors: list[dict[str, Any]] | None = None


def problem_response(
    request: Request,
    status_code: int,
    detail: str | None = None,
    *,
    problem_type: str | None = None,
    title: str | None = None,
    headers: dict[str, str] | None = None,
    **extra: Any,
) -> JSONResponse:
    """Build an application/problem+json response; the request id links it to the logs."""
    request_id = getattr(request.state, "request_id", None)
    body = {
        "type": f"/problems/{problem_type}" if problem_type else "about:blank",
        "title": title or HTTPStatus(status_code).phrase,
        "status": status_code,
        "detail": detail,
        "instance": request.url.path,
        "request_id": request_id,
        **extra,
    }
    all_headers = {**(headers or {}), **({REQUEST_ID_HEADER: request_id} if request_id else {})}
    return JSONResponse(
        {key: value for key, value in body.items() if value is not None},
        status_code=status_code,
        media_type=PROBLEM_JSON,
        headers=all_headers,
    )


async def domain_error_handler(request: Request, error: DomainError) -> JSONResponse:
    """DomainError subclasses → their own status, type and title."""
    return problem_response(
        request,
        error.status_code,
        str(error),
        problem_type=error.problem_type,
        title=error.title,
        headers=error.headers or None,
    )


async def http_error_handler(request: Request, error: StarletteHTTPException) -> JSONResponse:
    """HTTPException (ours, and Starlette's 404/405) → Problem Details."""
    detail = error.detail if isinstance(error.detail, str) else None
    return problem_response(request, error.status_code, detail, headers=error.headers)


async def validation_error_handler(request: Request, error: RequestValidationError) -> JSONResponse:
    """422 with one entry per problem (location, message, type), without echoing input."""
    problems = [
        {"loc": list(problem["loc"]), "msg": problem["msg"], "type": problem["type"]}
        for problem in error.errors()
    ]
    return problem_response(
        request,
        HTTPStatus.UNPROCESSABLE_CONTENT,
        f"{len(problems)} validation error(s)",
        problem_type="validation-error",
        title="Invalid request",
        errors=problems,
    )


async def integrity_error_handler(request: Request, error: IntegrityError) -> JSONResponse:
    """A constraint the database enforced (unique, foreign key) → 409, without SQL details."""
    return problem_response(
        request,
        HTTPStatus.CONFLICT,
        "the change conflicts with existing data",
        problem_type="conflict",
        title="Conflict",
    )


async def unhandled_error_handler(request: Request, error: Exception) -> JSONResponse:
    """Any other exception → a generic 500; details stay in the server log."""
    return problem_response(request, HTTPStatus.INTERNAL_SERVER_ERROR, "unexpected error")


def install_error_handlers(app: FastAPI) -> None:
    """Register every handler on the app."""
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
'''

NOTES_V4_CORE_LOGGING_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/core/logging.py
"""Log redaction: secrets must never reach log files (OWASP API8, and plain good sense)."""

import logging
import re

SENSITIVE_KEYS = ("password", "token", "secret", "authorization", "api_key", "cookie")
REDACTED = "[REDACTED]"
PATTERNS = [
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),  # Authorization header values
    re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*"),  # anything shaped like a JWT
    re.compile(r"\bnk_[A-Za-z0-9_-]{16,}"),  # our API keys
    re.compile(  # key=value pairs (but leave "Bearer ..." to the first pattern)
        rf"(?i)\b((?:{'|'.join(SENSITIVE_KEYS)})\w*\s*[=:]\s*)(?!bearer\b|\[REDACTED\])[^\s,;&]+"
    ),
]


def redact_text(text: str) -> str:
    """Replace secrets in a string (prefixes such as 'Bearer ' or 'password=' are kept)."""
    for pattern in PATTERNS:
        replacement = rf"\g<1>{REDACTED}" if pattern.groups else REDACTED
        text = pattern.sub(replacement, text)
    return text


def redact_value(key: str, value: object) -> object:
    """Redact a mapping value whose key looks sensitive; recurse into nested mappings."""
    if isinstance(value, dict):
        return {inner: redact_value(inner, item) for inner, item in value.items()}
    if any(word in key.lower() for word in SENSITIVE_KEYS):
        return REDACTED
    return redact_text(value) if isinstance(value, str) else value


class RedactingFilter(logging.Filter):
    """Rewrite each record's message and arguments before any handler formats it."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact in place; never drop the record."""
        if isinstance(record.args, dict):
            record.args = {key: redact_value(key, value) for key, value in record.args.items()}
        message = record.getMessage() if record.args else str(record.msg)
        record.msg, record.args = redact_text(message), None
        return True


def install_redaction(logger_names: tuple[str, ...] = ("notes_api", "uvicorn.access")) -> None:
    """Attach the filter to the app's loggers (idempotent)."""
    for name in logger_names:
        logger = logging.getLogger(name)
        if not any(isinstance(existing, RedactingFilter) for existing in logger.filters):
            logger.addFilter(RedactingFilter())
'''

NOTES_V4_CORE_MIDDLEWARE_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/core/middleware.py
"""Pure ASGI middleware: request ids (kept in a ContextVar) and Server-Timing headers."""

import re
import time
import uuid
from collections.abc import Callable
from contextvars import ContextVar

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestIdMiddleware:
    """Reuse a safe incoming X-Request-ID or make one; expose it to code, logs and the client."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the next ASGI app."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Set the id for this request, add it to the response headers, then reset it."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = Headers(scope=scope).get(REQUEST_ID_HEADER, "")
        request_id = incoming if VALID_REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id  # request.state.request_id
        token = request_id_var.set(request_id)

        async def send_with_id(message: Message) -> None:
            """Add the header to the response start message."""
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_var.reset(token)


class TimingMiddleware:
    """Add Server-Timing: app;dur=<ms>, measured until the response starts."""

    def __init__(self, app: ASGIApp, clock: Callable[[], float] = time.perf_counter) -> None:
        """Wrap the next ASGI app; clock is injectable for tests."""
        self.app = app
        self.clock = clock

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Time the inner app and report it in a header (milliseconds, one decimal)."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = self.clock()

        async def send_with_timing(message: Message) -> None:
            """Add the header to the response start message."""
            if message["type"] == "http.response.start":
                elapsed_ms = (self.clock() - started) * 1000
                MutableHeaders(scope=message).append("Server-Timing", f"app;dur={elapsed_ms:.1f}")
            await send(message)

        await self.app(scope, receive, send_with_timing)


API_CSP = (
    "default-src 'self'; script-src 'self' https://unpkg.com; style-src 'self'; "
    "img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)
DOCS_CSP = (  # Swagger UI and ReDoc load their scripts and styles from a CDN
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "img-src 'self' data: https://fastapi.tiangolo.com; font-src https://fonts.gstatic.com; "
    "frame-ancestors 'none'"
)
SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",  # HTTPS from now on
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
}


class SecurityHeadersMiddleware:
    """Pure ASGI: HSTS, CSP and friends on every HTTP response (OWASP API8)."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the next ASGI app."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Add the headers when the response starts (unless the app set them itself)."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_docs = scope["path"].startswith(("/docs", "/redoc"))

        async def send_with_headers(message: Message) -> None:
            """Set the security headers on the response start message."""
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
                headers.setdefault("Content-Security-Policy", DOCS_CSP if is_docs else API_CSP)
            await send(message)

        await self.app(scope, receive, send_with_headers)
'''

NOTES_V4_CORE_LIFESPAN_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/core/lifespan.py
"""Startup and shutdown: create shared resources once and keep them on app.state."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as redis_asyncio
from fastapi import FastAPI

from notes_api import __version__
from notes_api.core.config import Settings
from notes_api.db import create_engine_from_settings, make_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the database pool, a Redis client and one HTTP client; close them on shutdown."""
    settings: Settings = app.state.settings
    engine = create_engine_from_settings(settings)  # connects lazily, on first use
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.redis = redis_asyncio.from_url(  # also lazy: no connection until the first command
        settings.redis_url.get_secret_value(), decode_responses=True
    )
    try:
        async with httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            follow_redirects=False,  # a redirect could lead a server-side fetch somewhere private
            headers={"User-Agent": f"notes-api/{__version__}"},
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        ) as http_client:
            app.state.http_client = http_client
            yield
    finally:
        await app.state.redis.aclose()
        await engine.dispose()  # close every pooled database connection
'''

NOTES_V4_MODELS_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/models.py
"""SQLAlchemy 2.0 typed models: users, their notes and tags, refresh tokens and API keys."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, ForeignKey, Index, String, Table, Text, false, func, text, true
from sqlalchemy.ext.associationproxy import AssociationProxy, association_proxy
from sqlalchemy.orm import Mapped, mapped_column, relationship

from notes_api.db import Base


def utc_now() -> datetime:
    """The current time in UTC (the default clock)."""
    return datetime.now(UTC)


class TimestampMixin:
    """created_at / updated_at for any model (the service sets them; the server has defaults)."""

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


note_tags = Table(
    "note_tags",
    Base.metadata,
    Column("note_id", ForeignKey("notes.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class User(TimestampMixin, Base):
    """An account. password_hash is None for users who only sign in with a third party."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), server_default="user")
    is_active: Mapped[bool] = mapped_column(server_default=true())
    oidc_subject: Mapped[str | None] = mapped_column(String(255), unique=True)  # "issuer|sub"

    def __repr__(self) -> str:
        """Never show the hash."""
        return f"User(id={self.id!r}, email={self.email!r}, role={self.role!r})"


class RefreshToken(Base):
    """One opaque refresh token (only its SHA-256 is stored); a family shares one login."""

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    scopes: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]  # set when it was exchanged (rotation)
    revoked_at: Mapped[datetime | None]  # set at logout or when reuse was detected


class ApiKey(TimestampMixin, Base):
    """A personal API key: shown once, stored as a SHA-256, limited to some scopes."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    prefix: Mapped[str] = mapped_column(String(16))  # shown in lists, so users can tell keys apart
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[str] = mapped_column(String(200))
    last_used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]


class Tag(Base):
    """A tag name, stored once and shared by many notes."""

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(30), unique=True)


class Note(TimestampMixin, Base):
    """A note; tags is a list of names backed by the many-to-many tag_objects relationship."""

    __tablename__ = "notes"
    __table_args__ = (
        Index("ix_notes_created_at_id", "created_at", "id"),  # keyset pagination
        Index(  # trigram indexes make ILIKE '%text%' searches fast on PostgreSQL
            "ix_notes_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index(
            "ix_notes_body_trgm",
            "body",
            postgresql_using="gin",
            postgresql_ops={"body": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, server_default="")
    pinned: Mapped[bool] = mapped_column(server_default=false())
    version: Mapped[int] = mapped_column(server_default=text("1"))
    tag_objects: Mapped[list[Tag]] = relationship(
        secondary=note_tags, order_by=Tag.name, lazy="raise"
    )
    tags: AssociationProxy[list[str]] = association_proxy("tag_objects", "name")

    __mapper_args__: dict[str, Any] = {"version_id_col": version}  # UPDATE ... WHERE version = ?

    def __repr__(self) -> str:
        """Short form for logs and notebooks."""
        return f"Note(id={self.id!r}, title={self.title!r}, version={self.version!r})"
'''

NOTES_V4_ALEMBIC_VERSIONS_0004_USERS_AND_OWNERSHIP_PY = r'''
%%writefile ../projects/notes_api/alembic/versions/0004_users_and_ownership.py
"""Add users; every note gets an owner (existing notes go to a disabled legacy account).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_OWNER = "legacy-owner@notes.invalid"  # cannot log in: no password, not active
users_table = sa.table(
    "users",
    sa.column("id", sa.Integer()),
    sa.column("email", sa.String()),
    sa.column("is_active", sa.Boolean()),
)
notes_table = sa.table("notes", sa.column("id", sa.Integer()), sa.column("owner_id", sa.Integer()))


def upgrade() -> None:
    """Create users, add notes.owner_id (nullable), backfill it, then make it required."""
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=20), server_default="user", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("oidc_subject", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("oidc_subject", name=op.f("uq_users_oidc_subject")),
    )
    with op.batch_alter_table("notes") as batch:
        batch.add_column(sa.Column("owner_id", sa.Integer(), nullable=True))
    connection = op.get_bind()
    if connection.execute(sa.select(sa.func.count()).select_from(notes_table)).scalar():
        connection.execute(users_table.insert().values(email=LEGACY_OWNER, is_active=False))
        legacy_id = connection.execute(
            sa.select(users_table.c.id).where(users_table.c.email == LEGACY_OWNER)
        ).scalar_one()
        connection.execute(notes_table.update().values(owner_id=legacy_id))
    with op.batch_alter_table("notes") as batch:
        batch.alter_column("owner_id", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key(
            op.f("fk_notes_owner_id_users"), "users", ["owner_id"], ["id"], ondelete="CASCADE"
        )
        batch.create_index(op.f("ix_notes_owner_id"), ["owner_id"])


def downgrade() -> None:
    """Drop ownership and the users table (the legacy account goes with it)."""
    with op.batch_alter_table("notes") as batch:
        batch.drop_index(op.f("ix_notes_owner_id"))
        batch.drop_constraint(op.f("fk_notes_owner_id_users"), type_="foreignkey")
        batch.drop_column("owner_id")
    op.drop_table("users")
'''

NOTES_V4_ALEMBIC_VERSIONS_0005_REFRESH_TOKENS_AND_API_KEYS_PY = r'''
%%writefile ../projects/notes_api/alembic/versions/0005_refresh_tokens_and_api_keys.py
"""Add refresh tokens (rotation families) and personal API keys (hashed).

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp(name: str, nullable: bool = False, default: bool = False) -> sa.Column:
    """A timezone-aware timestamp column."""
    server_default = sa.func.now() if default else None
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=server_default, nullable=nullable
    )


def upgrade() -> None:
    """Two tables, both owned by a user (deleted with the user)."""
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("family_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("scopes", sa.String(length=200), nullable=False),
        timestamp("created_at", default=True),
        timestamp("expires_at"),
        timestamp("used_at", nullable=True),
        timestamp("revoked_at", nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(op.f("ix_refresh_tokens_family_id"), "refresh_tokens", ["family_id"])
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"])

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", sa.String(length=200), nullable=False),
        timestamp("last_used_at", nullable=True),
        timestamp("revoked_at", nullable=True),
        timestamp("created_at", default=True),
        timestamp("updated_at", default=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_api_keys_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_keys")),
        sa.UniqueConstraint("key_hash", name=op.f("uq_api_keys_key_hash")),
    )
    op.create_index(op.f("ix_api_keys_user_id"), "api_keys", ["user_id"])


def downgrade() -> None:
    """Drop both tables."""
    op.drop_index(op.f("ix_api_keys_user_id"), table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_family_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
'''

NOTES_V4_SCHEMAS_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/schemas.py
"""Request and response schemas for the Notes API (Pydantic v2).

One schema per direction: NoteCreate (POST/PUT body), NoteUpdate (PATCH body, every field
optional), NoteRead (responses, with server-owned fields) and NoteFilters (query parameters).
Page envelopes live in pagination.py, error bodies in core/errors.py.
"""

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    computed_field,
    field_validator,
    model_validator,
)

MAX_TAGS = 10


def require_slug(value: str) -> str:
    """Allow lowercase letters, digits and dashes (checked after stripping and lower-casing)."""
    if not re.fullmatch(r"[a-z0-9-]+", value):
        raise ValueError("tags use lowercase letters, digits and dashes")
    return value


def unique_in_order(tags: list[str]) -> list[str]:
    """Drop repeated tags, keeping the first occurrence."""
    return list(dict.fromkeys(tags))


Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Body = Annotated[str, Field(max_length=10_000)]
Tag = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True, min_length=1, max_length=30),
    AfterValidator(require_slug),
]
Tags = Annotated[list[Tag], Field(max_length=MAX_TAGS)]
SortOrder = Literal["created_at", "-created_at", "updated_at", "-updated_at", "title", "-title"]


class NoteCreate(BaseModel):
    """Body of POST /notes and PUT /notes/{note_id}: every field a client may set."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [{"title": "Buy tea", "body": "Assam, 500 g", "tags": ["shopping"]}]
        },
    )

    title: Title
    body: Body = ""
    tags: Tags = []
    pinned: bool = False

    @field_validator("tags")
    @classmethod
    def drop_duplicate_tags(cls, tags: list[str]) -> list[str]:
        """Keep each tag once."""
        return unique_in_order(tags)


class NoteUpdate(BaseModel):
    """Body of PATCH /notes/{note_id}: only the fields being changed."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"pinned": True, "version": 1}]}
    )

    title: Title | None = None
    body: Body | None = None
    tags: Tags | None = None
    pinned: bool | None = None
    version: Annotated[
        int | None, Field(ge=1, description="The version you read; a mismatch is a 409.")
    ] = None

    @field_validator("tags")
    @classmethod
    def drop_duplicate_tags(cls, tags: list[str] | None) -> list[str] | None:
        """Keep each tag once."""
        return None if tags is None else unique_in_order(tags)

    @model_validator(mode="after")
    def reject_explicit_null(self) -> NoteUpdate:
        """None means "not sent"; an explicit null is an error (no field is nullable)."""
        nulled = sorted(name for name in self.model_fields_set if getattr(self, name) is None)
        if nulled:
            raise ValueError(f"fields cannot be null: {', '.join(nulled)}")
        return self


class NoteRead(BaseModel):
    """A note as the API returns it."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    body: str
    tags: list[str]
    pinned: bool
    version: int
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def word_count(self) -> int:
        """Words in the body (derived, never stored)."""
        return len(self.body.split())


class NoteFilters(BaseModel):
    """Query parameters of GET /notes: filtering, sorting and pagination."""

    model_config = ConfigDict(extra="forbid")

    q: Annotated[str | None, Field(max_length=100, description="Text in title or body.")] = None
    tag: Annotated[list[Tag], Field(description="Only notes that have all these tags.")] = []
    pinned: bool | None = None
    sort: SortOrder = "-created_at"
    limit: Annotated[int, Field(ge=1, le=100)] = 20
    offset: Annotated[int, Field(ge=0)] = 0


class FeedParams(BaseModel):
    """Query parameters of GET /notes/feed: keyset (cursor) pagination, newest first."""

    model_config = ConfigDict(extra="forbid")

    cursor: Annotated[str | None, Field(description="next_cursor from the previous page.")] = None
    limit: Annotated[int, Field(ge=1, le=100)] = 20


class LinkPreview(BaseModel):
    """The title of one link found in a note's body (or why it could not be fetched)."""

    url: str
    status_code: int | None = None
    title: str | None = None
    error: str | None = None


class ImportReport(BaseModel):
    """Result of POST /admin/import."""

    filename: str
    imported: int
    ids: list[int]


ScopeName = Literal["notes:read", "notes:write", "admin"]


class UserCreate(BaseModel):
    """Body of POST /auth/register. The role is never accepted from clients (OWASP API3)."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: Annotated[str, Field(min_length=12, max_length=128)]


class UserRead(BaseModel):
    """A user as the API shows it: no password hash, no internal flags."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: str
    created_at: datetime


class TokenPair(BaseModel):
    """The OAuth 2.0 token response (RFC 6749 section 5.1) plus our refresh token."""

    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    scope: str


class RefreshRequest(BaseModel):
    """Body of POST /auth/refresh and /auth/logout."""

    model_config = ConfigDict(extra="forbid")

    refresh_token: Annotated[str, Field(min_length=10, max_length=200)]


class ApiKeyCreate(BaseModel):
    """Body of POST /users/me/api-keys."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    scopes: Annotated[list[ScopeName], Field(min_length=1)] = ["notes:read"]


class ApiKeyRead(BaseModel):
    """An API key without its secret."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    prefix: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None

    @field_validator("scopes", mode="before")
    @classmethod
    def split_scopes(cls, value: object) -> object:
        """The database stores scopes space-separated."""
        return value.split() if isinstance(value, str) else value


class ApiKeyCreated(ApiKeyRead):
    """The response to creating a key: the only time the full key is shown."""

    key: str
'''

NOTES_V4_REPOSITORIES_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/repositories.py
"""Storage behind Protocols: services depend on NoteRepository / UserRepository, not on SQL.

Unit 6.3 shipped an in-memory note repository; Unit 6.4 replaced it with SqlNoteRepository;
Unit 6.5 scopes notes to their owner and adds SqlUserRepository (users, refresh tokens, keys).
"""

from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import Select, delete, func, or_, select, tuple_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.exc import StaleDataError

from notes_api.exceptions import VersionConflictError
from notes_api.models import ApiKey, Note, RefreshToken, Tag, User
from notes_api.pagination import CursorKey
from notes_api.schemas import NoteCreate, NoteFilters


class NoteRepository(Protocol):
    """What the service needs from storage."""

    async def add(self, data: NoteCreate, now: datetime, owner_id: int) -> Note:
        """Store a new note for owner_id and return it with its id."""
        ...

    async def get(self, note_id: int) -> Note | None:
        """The note with this id, or None."""
        ...

    async def search(self, filters: NoteFilters, owner_id: int | None) -> tuple[list[Note], int]:
        """One page of matching notes (of owner_id, or everyone's when None) and the total."""
        ...

    async def feed(self, limit: int, after: CursorKey | None, owner_id: int) -> list[Note]:
        """Up to limit of owner_id's notes, newest first, strictly older than the key after."""
        ...

    async def update(self, note: Note, changes: dict[str, Any], now: datetime) -> Note:
        """Apply field changes (tags as a list of names), stamp updated_at, return the note."""
        ...

    async def delete(self, note: Note) -> None:
        """Remove a note returned by this repository."""
        ...

    async def delete_all(self) -> int:
        """Remove every note; return how many there were."""
        ...


class SqlNoteRepository:
    """NoteRepository on an AsyncSession: SQL filters, sorts and pages; tags always eager."""

    def __init__(self, session: AsyncSession) -> None:
        """Work inside the request's session (and so its transaction)."""
        self.session = session

    @staticmethod
    def _select() -> Select[tuple[Note]]:
        """SELECT notes plus one extra query for all their tags (no N+1, no lazy loads)."""
        return select(Note).options(selectinload(Note.tag_objects))

    async def _tags(self, names: list[str]) -> list[Tag]:
        """Tag rows for these names (sorted), creating missing ones; a savepoint absorbs a race."""
        if not names:
            return []
        found = await self.session.scalars(select(Tag).where(Tag.name.in_(names)))
        by_name = {tag.name: tag for tag in found}
        for name in names:
            if name in by_name:
                continue
            try:
                async with self.session.begin_nested():  # SAVEPOINT
                    tag = Tag(name=name)
                    self.session.add(tag)
                by_name[name] = tag
            except IntegrityError:  # another transaction inserted it first: use theirs
                by_name[name] = await self.session.scalar(select(Tag).where(Tag.name == name))
        return sorted((by_name[name] for name in names), key=lambda tag: tag.name)

    async def _flush(self, note: Note) -> None:
        """Send pending changes; a version mismatch becomes a domain conflict."""
        note_id = note.id  # read it now: after a failed flush the session needs a rollback
        try:
            await self.session.flush()
        except StaleDataError as error:
            raise VersionConflictError(note_id) from error

    async def add(self, data: NoteCreate, now: datetime, owner_id: int) -> Note:
        """INSERT the note and its tag links; flush so the id is known."""
        fields = data.model_dump(exclude={"tags"})
        note = Note(**fields, owner_id=owner_id, created_at=now, updated_at=now)
        note.tag_objects = await self._tags(data.tags)
        self.session.add(note)
        await self.session.flush()
        return note

    async def get(self, note_id: int) -> Note | None:
        """One note with its tags."""
        return await self.session.scalar(self._select().where(Note.id == note_id))

    async def search(self, filters: NoteFilters, owner_id: int | None) -> tuple[list[Note], int]:
        """WHERE for the filters, COUNT for the total, ORDER BY + LIMIT/OFFSET for the page."""
        conditions = [Note.tag_objects.any(Tag.name == name) for name in filters.tag]
        if owner_id is not None:
            conditions.append(Note.owner_id == owner_id)
        if filters.pinned is not None:
            conditions.append(Note.pinned == filters.pinned)
        if filters.q:
            conditions.append(
                or_(
                    Note.title.icontains(filters.q, autoescape=True),
                    Note.body.icontains(filters.q, autoescape=True),
                )
            )
        total = await self.session.scalar(select(func.count(Note.id)).where(*conditions))
        field_name = filters.sort.removeprefix("-")
        column = func.lower(Note.title) if field_name == "title" else getattr(Note, field_name)
        if filters.sort.startswith("-"):
            order = [column.desc(), Note.id.desc()]
        else:
            order = [column.asc(), Note.id.asc()]
        page = self._select().where(*conditions).order_by(*order)
        notes = await self.session.scalars(page.offset(filters.offset).limit(filters.limit))
        return list(notes), total or 0

    async def feed(self, limit: int, after: CursorKey | None, owner_id: int) -> list[Note]:
        """Keyset page: WHERE (created_at, id) < (:created_at, :id) on an index, no OFFSET."""
        statement = self._select().where(Note.owner_id == owner_id)
        statement = statement.order_by(Note.created_at.desc(), Note.id.desc())
        if after is not None:
            statement = statement.where(tuple_(Note.created_at, Note.id) < tuple_(*after))
        return list(await self.session.scalars(statement.limit(limit)))

    async def update(self, note: Note, changes: dict[str, Any], now: datetime) -> Note:
        """Change attributes; the flush sends UPDATE ... WHERE id = ? AND version = ?."""
        changes = dict(changes)
        tag_names = changes.pop("tags", None)
        for name, value in changes.items():
            setattr(note, name, value)
        if tag_names is not None:
            note.tag_objects = await self._tags(tag_names)
        note.updated_at = now
        await self._flush(note)
        return note

    async def delete(self, note: Note) -> None:
        """DELETE the note (its tag links go by ON DELETE CASCADE)."""
        await self.session.delete(note)
        await self._flush(note)

    async def delete_all(self) -> int:
        """Bulk DELETE statements: every note, then every tag."""
        result = await self.session.execute(delete(Note))
        await self.session.execute(delete(Tag))
        return result.rowcount


class UserRepository(Protocol):
    """What the auth service needs from storage."""

    async def add_user(self, email: str, password_hash: str | None, role: str) -> User:
        """Store a new user (IntegrityError if the email exists)."""
        ...

    async def user_by_id(self, user_id: int) -> User | None:
        """The user, or None."""
        ...

    async def user_by_email(self, email: str) -> User | None:
        """The user with this email (case-insensitive), or None."""
        ...


class SqlUserRepository:
    """Users, refresh tokens and API keys on the request's session."""

    def __init__(self, session: AsyncSession) -> None:
        """Work inside the request's session."""
        self.session = session

    async def add_user(
        self, email: str, password_hash: str | None, role: str, oidc_subject: str | None = None
    ) -> User:
        """INSERT a user; a duplicate email raises IntegrityError at the flush."""
        user = User(email=email.lower(), password_hash=password_hash, role=role)
        user.oidc_subject = oidc_subject
        self.session.add(user)
        await self.session.flush()
        return user

    async def user_by_id(self, user_id: int) -> User | None:
        """Primary-key lookup (identity map first)."""
        return await self.session.get(User, user_id)

    async def user_by_email(self, email: str) -> User | None:
        """Emails are stored lower-cased."""
        return await self.session.scalar(select(User).where(User.email == email.lower()))

    async def user_by_oidc_subject(self, subject: str) -> User | None:
        """The user linked to a third-party identity."""
        return await self.session.scalar(select(User).where(User.oidc_subject == subject))

    async def add_refresh_token(self, token: RefreshToken) -> None:
        """Store a refresh token row."""
        self.session.add(token)
        await self.session.flush()

    async def refresh_token_by_hash(self, token_hash: str) -> RefreshToken | None:
        """Look a refresh token up by its SHA-256."""
        return await self.session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )

    async def revoke_family(self, family_id: str, now: datetime) -> int:
        """Revoke every token of one login; returns how many were still active."""
        result = await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        return result.rowcount

    async def add_api_key(self, key: ApiKey) -> ApiKey:
        """Store an API key row."""
        self.session.add(key)
        await self.session.flush()
        return key

    async def api_key_by_hash(self, key_hash: str) -> ApiKey | None:
        """An active (not revoked) key by its SHA-256."""
        return await self.session.scalar(
            select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
        )

    async def api_keys_of(self, user_id: int) -> list[ApiKey]:
        """A user's keys, newest first (revoked ones included)."""
        statement = select(ApiKey).where(ApiKey.user_id == user_id).order_by(ApiKey.id.desc())
        return list(await self.session.scalars(statement))
'''

NOTES_V4_SERVICES_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/services.py
"""Business logic: what the API does, independent of HTTP and of how notes are stored."""

import asyncio
import csv
import io
import ipaddress
import json
import re
import socket
import urllib.parse
from collections.abc import Awaitable, Callable
from datetime import datetime
from http import HTTPStatus

import httpx
from pydantic import TypeAdapter, ValidationError

from notes_api.exceptions import NoteNotFoundError, UploadRejectedError, VersionConflictError
from notes_api.models import Note
from notes_api.pagination import decode_cursor, encode_cursor
from notes_api.repositories import NoteRepository
from notes_api.schemas import LinkPreview, NoteCreate, NoteFilters, NoteUpdate

URL_PATTERN = re.compile(r"https?://[^\s<>\"')]+")
TITLE_PATTERN = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
MAX_LINKS = 5
MAX_PREVIEW_BYTES = 64 * 1024
IMPORT_ADAPTER = TypeAdapter(list[NoteCreate])


class NoteService:
    """Use cases for one user's notes; repository, clock and owner are injected."""

    def __init__(
        self, repository: NoteRepository, clock: Callable[[], datetime], owner_id: int
    ) -> None:
        """Keep the collaborators; every operation is limited to owner_id's notes."""
        self.repository = repository
        self.clock = clock
        self.owner_id = owner_id

    async def create(self, data: NoteCreate) -> Note:
        """Store a new note for the owner, stamped with the current time."""
        return await self.repository.add(data, self.clock(), self.owner_id)

    async def get(self, note_id: int) -> Note:
        """The owner's note, or NoteNotFoundError: someone else's note is 'not found' too,
        so ids cannot be probed (404, not 403)."""
        note = await self.repository.get(note_id)
        if note is None or note.owner_id != self.owner_id:
            raise NoteNotFoundError(note_id)
        return note

    async def search(self, filters: NoteFilters) -> tuple[list[Note], int]:
        """One page of the owner's matching notes and the total."""
        return await self.repository.search(filters, self.owner_id)

    async def feed(self, limit: int, cursor: str | None) -> tuple[list[Note], str | None]:
        """A keyset page, newest first, and the cursor of the next page (None at the end)."""
        after = decode_cursor(cursor) if cursor else None
        notes = await self.repository.feed(limit + 1, after, self.owner_id)  # one extra
        page = notes[:limit]
        has_more = len(notes) > limit
        next_cursor = encode_cursor((page[-1].created_at, page[-1].id)) if has_more else None
        return page, next_cursor

    async def replace(self, note_id: int, data: NoteCreate) -> Note:
        """PUT: every client-owned field gets the new value (or its default)."""
        note = await self.get(note_id)
        return await self.repository.update(note, data.model_dump(), self.clock())

    async def update(self, note_id: int, changes: NoteUpdate) -> Note:
        """PATCH: check the expected version, apply the fields sent, move updated_at on change."""
        note = await self.get(note_id)
        if changes.version is not None and changes.version != note.version:
            raise VersionConflictError(note_id, expected=changes.version, actual=note.version)
        sent = changes.model_dump(exclude_unset=True, exclude={"version"})
        if all(getattr(note, name) == value for name, value in sent.items()):
            return note
        return await self.repository.update(note, sent, self.clock())

    async def delete(self, note_id: int) -> None:
        """Delete a note, or NoteNotFoundError."""
        note = await self.get(note_id)
        await self.repository.delete(note)

    async def import_notes(self, notes: list[NoteCreate]) -> list[Note]:
        """Create every note of an import, in file order."""
        return [await self.create(note) for note in notes]


def parse_import(filename: str, content: bytes) -> list[NoteCreate]:
    """Notes from a .json list or a .csv file (title, body, tags separated by ';', pinned)."""
    try:
        text = content.decode("utf-8-sig")
        if filename.endswith(".json"):
            return IMPORT_ADAPTER.validate_python(json.loads(text))
        rows = [
            {**row, "tags": [tag for tag in (row.get("tags") or "").split(";") if tag]}
            for row in csv.DictReader(io.StringIO(text))
        ]
        return IMPORT_ADAPTER.validate_python(rows)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
        reason = f"{type(error).__name__}: {str(error).splitlines()[0]}"
        raise UploadRejectedError(reason, HTTPStatus.UNPROCESSABLE_CONTENT) from error


type Resolver = Callable[[str], Awaitable[list[str]]]


async def resolve_host(host: str) -> list[str]:
    """Every IP address a host name resolves to (getaddrinfo runs in a worker thread)."""
    infos = await asyncio.to_thread(socket.getaddrinfo, host, None, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def is_public_address(address: str) -> bool:
    """False for loopback, private, link-local, reserved, multicast and unspecified addresses."""
    ip = ipaddress.ip_address(address)
    return ip.is_global and not ip.is_multicast


class LinkPreviewer:
    """Fetch the <title> of links in a note, refusing anything that is not a public web URL.

    Server-side request forgery (OWASP API7): a note body is user input, so a link could point
    at 127.0.0.1, the cloud metadata service (169.254.169.254) or a private network. Each host
    is resolved first and every address must be public; redirects are not followed (a public
    URL could redirect to a private one); at most MAX_PREVIEW_BYTES of a page are read.
    """

    def __init__(self, client: httpx.AsyncClient, resolver: Resolver = resolve_host) -> None:
        """Use the pooled client created by the lifespan and an injectable DNS resolver."""
        self.client = client
        self.resolver = resolver

    async def check_url(self, url: str) -> str | None:
        """None if the URL may be fetched, else the reason it may not."""
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return "only public http(s) URLs are fetched"
        try:
            addresses = await self.resolver(parsed.hostname)
        except OSError:
            return "host does not resolve"
        if not addresses or not all(is_public_address(address) for address in addresses):
            return "blocked: not a public address"
        return None

    async def preview(self, url: str) -> LinkPreview:
        """One link: its status and title, or why it was not fetched (never raises)."""
        if reason := await self.check_url(url):
            return LinkPreview(url=url, error=reason)
        try:
            async with self.client.stream("GET", url, follow_redirects=False) as response:
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= MAX_PREVIEW_BYTES:
                        break
        except httpx.HTTPError as error:
            return LinkPreview(url=url, error=type(error).__name__)
        if response.is_redirect:
            return LinkPreview(
                url=url, status_code=response.status_code, error="redirect not followed"
            )
        text = b"".join(chunks)[:MAX_PREVIEW_BYTES].decode(response.encoding or "utf-8", "replace")
        match = TITLE_PATTERN.search(text)
        title = " ".join(match[1].split()) if match else None
        return LinkPreview(url=url, status_code=response.status_code, title=title)

    async def previews(self, body: str) -> list[LinkPreview]:
        """The first MAX_LINKS distinct links of a body, fetched concurrently."""
        urls = list(dict.fromkeys(URL_PATTERN.findall(body)))[:MAX_LINKS]
        return list(await asyncio.gather(*(self.preview(url) for url in urls)))
'''

NOTES_V4_SECURITY_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/security.py
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
'''

NOTES_V4_RATELIMIT_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/ratelimit.py
"""A fixed-window rate limiter on Redis: one INCR per attempt, keys expire by themselves."""

import dataclasses
import time
from collections.abc import Callable

from redis.asyncio import Redis


@dataclasses.dataclass(frozen=True, slots=True)
class RateLimitResult:
    """The outcome of one attempt."""

    allowed: bool
    remaining: int
    retry_after: int  # seconds until the current window ends


class FixedWindowRateLimiter:
    """At most `limit` hits per key per window of `window_seconds` (shared by every process)."""

    def __init__(
        self,
        redis: Redis,
        limit: int,
        window_seconds: int,
        prefix: str,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Keep the client and the limits; the clock is injectable for tests."""
        self.redis = redis
        self.limit = limit
        self.window_seconds = window_seconds
        self.prefix = prefix
        self.clock = clock

    async def hit(self, key: str) -> RateLimitResult:
        """Count one attempt for key in the current window."""
        now = self.clock()
        window = int(now // self.window_seconds)
        redis_key = f"ratelimit:{self.prefix}:{key}:{window}"
        async with self.redis.pipeline(transaction=True) as pipeline:
            pipeline.incr(redis_key)
            pipeline.expire(redis_key, self.window_seconds + 1)
            count, _ = await pipeline.execute()
        retry_after = max(1, int((window + 1) * self.window_seconds - now + 0.999))
        return RateLimitResult(count <= self.limit, max(0, self.limit - count), retry_after)
'''

NOTES_V4_AUTH_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/auth.py
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
'''

NOTES_V4_OAUTH_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/oauth.py
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
'''

NOTES_V4_DEPENDENCIES_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/dependencies.py
"""Dependencies shared by the routers, as Annotated aliases. A notes request resolves as:

ReaderServiceDep ── Security(get_note_service, ["notes:read"])
                      ├─ get_note_repository ─ get_session
                      ├─ get_clock
                      └─ get_current_principal (receives the accumulated scopes)
get_current_principal ─┬─ OAuth2PasswordBearer (Authorization: Bearer ...)
                       ├─ APIKeyHeader (X-API-Key)
                       └─ get_auth_service ─ get_session, get_redis, app.state
"""

from collections.abc import AsyncIterator, Callable
from datetime import datetime, timedelta
from typing import Annotated

import httpx
from fastapi import Depends, Request, Security
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer, SecurityScopes
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from notes_api.auth import AuthService
from notes_api.core.config import Settings
from notes_api.exceptions import AuthenticationError, PermissionDeniedError
from notes_api.models import utc_now
from notes_api.oauth import OidcClient
from notes_api.ratelimit import FixedWindowRateLimiter
from notes_api.repositories import NoteRepository, SqlNoteRepository, SqlUserRepository
from notes_api.security import ALL_SCOPES, Principal, TokenService
from notes_api.services import LinkPreviewer, NoteService, Resolver, resolve_host

SESSION_COOKIE = "notes_session"
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/token", scopes=ALL_SCOPES, auto_error=False
)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_app_settings(request: Request) -> Settings:
    """The settings this app was created with (create_app stores them on app.state)."""
    return request.app.state.settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session and one transaction per request: commit on success, roll back on error."""
    async with request.app.state.session_factory() as session, session.begin():
        yield session


# scope="function": commit before the response is sent, so a failed commit is a 500/409,
# never a 200 for data that was not saved (the default scope would commit after sending).
SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]


def get_redis(request: Request) -> Redis:
    """The Redis client the lifespan created (tests override this with fakeredis)."""
    return request.app.state.redis


def get_clock() -> Callable[[], datetime]:
    """The clock for timestamps (tests override it with dependency_overrides)."""
    return utc_now


def get_http_client(request: Request) -> httpx.AsyncClient:
    """The pooled HTTP client the lifespan created."""
    return request.app.state.http_client


def get_resolver() -> Resolver:
    """DNS resolution for link previews (tests override it: no real DNS in tests)."""
    return resolve_host


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
RedisDep = Annotated[Redis, Depends(get_redis)]
ClockDep = Annotated[Callable[[], datetime], Depends(get_clock)]
HttpClientDep = Annotated[httpx.AsyncClient, Depends(get_http_client)]


def get_note_repository(session: SessionDep) -> NoteRepository:
    """The SQL repository on this request's session."""
    return SqlNoteRepository(session)


RepositoryDep = Annotated[NoteRepository, Depends(get_note_repository)]


def get_auth_service(
    request: Request, session: SessionDep, redis: RedisDep, settings: SettingsDep, clock: ClockDep
) -> AuthService:
    """An AuthService on this request's session, with the app-wide hasher and secret."""
    tokens = TokenService(
        request.app.state.jwt_secret,
        settings.jwt_issuer,
        settings.jwt_audience,
        timedelta(minutes=settings.access_token_minutes),
        clock,
    )
    return AuthService(
        SqlUserRepository(session),
        tokens,
        request.app.state.password_hasher,
        request.app.state.dummy_hash,
        redis,
        request.app.state.session_factory,
        timedelta(days=settings.refresh_token_days),
        settings.admin_emails,
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_current_principal(
    security_scopes: SecurityScopes,
    auth: AuthServiceDep,
    token: Annotated[str | None, Depends(oauth2_scheme)],
    api_key: Annotated[str | None, Depends(api_key_header)],
) -> Principal:
    """Authenticate with a bearer token or an API key, then check the required scopes."""
    if token:
        principal = await auth.principal_from_access_token(token)
    elif api_key:
        principal = await auth.principal_from_api_key(api_key)
    else:
        raise AuthenticationError("not authenticated", security_scopes.scopes)
    missing = set(security_scopes.scopes) - principal.scopes
    if missing:
        raise PermissionDeniedError(f"missing scope(s): {' '.join(sorted(missing))}")
    return principal


CurrentPrincipal = Annotated[Principal, Security(get_current_principal)]


async def require_admin(
    principal: Annotated[Principal, Security(get_current_principal, scopes=["admin"])],
) -> Principal:
    """Role check on top of the scope check (OWASP API5: function-level authorization)."""
    if principal.role != "admin":
        raise PermissionDeniedError("admin role required")
    return principal


AdminPrincipal = Annotated[Principal, Depends(require_admin)]


def get_note_service(
    repository: RepositoryDep, clock: ClockDep, principal: CurrentPrincipal
) -> NoteService:
    """A NoteService limited to the caller's notes; route scopes flow down to the principal."""
    return NoteService(repository, clock, principal.user_id)


ReaderServiceDep = Annotated[NoteService, Security(get_note_service, scopes=["notes:read"])]
WriterServiceDep = Annotated[NoteService, Security(get_note_service, scopes=["notes:write"])]


def get_link_previewer(
    client: HttpClientDep, resolver: Annotated[Resolver, Depends(get_resolver)]
) -> LinkPreviewer:
    """A LinkPreviewer on the shared HTTP client, with SSRF checks."""
    return LinkPreviewer(client, resolver)


LinkPreviewerDep = Annotated[LinkPreviewer, Depends(get_link_previewer)]


def get_login_limiter(redis: RedisDep, settings: SettingsDep) -> FixedWindowRateLimiter:
    """The login/registration rate limiter (shared by every worker through Redis)."""
    return FixedWindowRateLimiter(
        redis, settings.login_rate_limit, settings.login_rate_window_seconds, "login"
    )


LoginLimiterDep = Annotated[FixedWindowRateLimiter, Depends(get_login_limiter)]


def get_oidc_client(settings: SettingsDep, client: HttpClientDep, redis: RedisDep) -> OidcClient:
    """The OpenID Connect client (the router checks settings.oauth_enabled first)."""
    return OidcClient(settings, client, redis)


OidcClientDep = Annotated[OidcClient, Depends(get_oidc_client)]


async def get_cookie_principal(request: Request, auth: AuthServiceDep) -> Principal | None:
    """The user of an HTML page, from the HttpOnly session cookie (None if absent or invalid)."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        return await auth.principal_from_access_token(token)
    except AuthenticationError:
        return None


CookiePrincipalDep = Annotated[Principal | None, Depends(get_cookie_principal)]
'''

NOTES_V4_MAIN_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/main.py
"""The Notes API application factory.

Unit 6.5 version: create_app() wires settings, password hashing and token secrets, error
handlers, middleware (now with security headers), log redaction, the lifespan (database,
Redis, HTTP client) and the routers, including authentication. Later units add background
jobs and caching (6.6), observability (6.7) and deployment (6.8).

Serve it with `uvicorn notes_api.main:app` (module-level app) or
`uvicorn --factory notes_api.main:create_app` (a fresh app per process).
"""

from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles

from notes_api import __version__
from notes_api.core.config import PLACEHOLDER_SECRETS, Settings, get_settings
from notes_api.core.errors import install_error_handlers
from notes_api.core.lifespan import lifespan
from notes_api.core.logging import install_redaction
from notes_api.core.middleware import (
    REQUEST_ID_HEADER,
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
    TimingMiddleware,
)
from notes_api.routers import admin, auth, health, notes, pages, users
from notes_api.security import make_password_hasher, new_secret

PACKAGE_DIR = Path(__file__).resolve().parent
API_PREFIX = "/api/v1"


def operation_id(route: APIRoute) -> str:
    """Use the function name as the OpenAPI operationId (clean names in generated clients)."""
    return route.name


def install_middleware(app: FastAPI, settings: Settings) -> None:
    """Add middleware; the last one added is the outermost (it sees the request first)."""
    app.add_middleware(TimingMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER, "Location", "Server-Timing"],
        max_age=600,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware)


def install_security(app: FastAPI, settings: Settings) -> None:
    """The password hasher, a dummy hash (equal timing for unknown users) and the JWT secret."""
    hasher = make_password_hasher(settings.password_time_cost, settings.password_memory_kib)
    app.state.password_hasher = hasher
    app.state.dummy_hash = hasher.hash(new_secret())
    secret = settings.jwt_secret.get_secret_value() if settings.jwt_secret else ""
    if secret in PLACEHOLDER_SECRETS:  # dev/test only (production refuses to start without one)
        secret = new_secret(32)  # a random secret per process: tokens die on restart
    app.state.jwt_secret = secret
    install_redaction()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a fully wired app; tests pass their own Settings, servers use the environment."""
    settings = settings or get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        summary="Create, search and organize notes.",
        description="Built step by step in Phase 6 of the course. Errors are RFC 9457 problems.",
        debug=settings.debug,
        lifespan=lifespan,
        docs_url=None if settings.environment == "production" else "/docs",
        redoc_url=None if settings.environment == "production" else "/redoc",
        generate_unique_id_function=operation_id,
        openapi_tags=[
            {"name": "auth", "description": "Register, log in, refresh and log out."},
            {"name": "users", "description": "The current user and personal API keys."},
            {"name": "notes", "description": "Your notes (scopes notes:read / notes:write)."},
            {"name": "admin", "description": "Bulk operations; admin role and scope."},
            {"name": "health", "description": "Liveness probe for load balancers and tests."},
        ],
    )
    app.state.settings = settings
    install_security(app, settings)
    install_error_handlers(app)
    install_middleware(app, settings)
    api_router = APIRouter(prefix=API_PREFIX)
    api_router.include_router(auth.router)
    api_router.include_router(users.router)
    api_router.include_router(notes.router)
    api_router.include_router(admin.router)
    app.include_router(health.router)
    app.include_router(api_router)
    app.include_router(pages.router)
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
    return app


app = create_app()
'''

NOTES_V4_ROUTERS_AUTH_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/routers/auth.py
"""/api/v1/auth: register, log in (OAuth2 password form), refresh, log out, OpenID Connect."""

import contextlib
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm

from notes_api.dependencies import (
    AuthServiceDep,
    LoginLimiterDep,
    OidcClientDep,
    SettingsDep,
    oauth2_scheme,
)
from notes_api.exceptions import AuthenticationError, RateLimitedError
from notes_api.models import User
from notes_api.ratelimit import FixedWindowRateLimiter
from notes_api.schemas import RefreshRequest, TokenPair, UserCreate, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


def client_ip(request: Request) -> str:
    """The peer address (behind a proxy, configure Uvicorn's --forwarded-allow-ips)."""
    return request.client.host if request.client else "unknown"


async def enforce_limit(limiter: FixedWindowRateLimiter, key: str) -> None:
    """Count one attempt; 429 with Retry-After once the window's budget is spent."""
    result = await limiter.hit(key)
    if not result.allowed:
        raise RateLimitedError(result.retry_after)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(
    data: UserCreate,
    request: Request,
    auth: AuthServiceDep,
    limiter: LoginLimiterDep,
) -> User:
    """Create an account (rate limited per client address)."""
    await enforce_limit(limiter, f"register:{client_ip(request)}")
    return await auth.register(data)


@router.post("/token", response_model=TokenPair)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    request: Request,
    auth: AuthServiceDep,
    limiter: LoginLimiterDep,
) -> TokenPair:
    """OAuth2 password grant: username = email; optional space-separated scope."""
    await enforce_limit(limiter, f"{client_ip(request)}:{form.username.lower()}")
    user = await auth.authenticate(form.username, form.password)
    return await auth.issue_tokens(user, auth.grant_scopes(user.role, form.scopes))


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, auth: AuthServiceDep) -> TokenPair:
    """Exchange a refresh token for a new pair (the old refresh token stops working)."""
    return await auth.refresh(body.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: RefreshRequest,
    auth: AuthServiceDep,
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> None:
    """Revoke the refresh-token family; also deny the access token sent, if any."""
    principal = None
    if token:
        with contextlib.suppress(AuthenticationError):
            principal = await auth.principal_from_access_token(token)
    await auth.logout(body.refresh_token, principal)


@router.get("/oauth/login", response_class=RedirectResponse, status_code=status.HTTP_302_FOUND)
async def oauth_login(settings: SettingsDep, oidc: OidcClientDep) -> RedirectResponse:
    """Start an OpenID Connect login: redirect to the provider (PKCE, state, nonce)."""
    if not settings.oauth_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "third-party login is not configured")
    return RedirectResponse(await oidc.authorization_url(), status_code=status.HTTP_302_FOUND)


@router.get("/oauth/callback", response_model=TokenPair)
async def oauth_callback(
    code: str, state: str, settings: SettingsDep, oidc: OidcClientDep, auth: AuthServiceDep
) -> TokenPair:
    """Finish the login: verify state, exchange the code, verify the ID token, issue tokens."""
    if not settings.oauth_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "third-party login is not configured")
    claims = await oidc.finish(code, state)
    return await auth.oidc_login(claims)
'''

NOTES_V4_ROUTERS_USERS_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/routers/users.py
"""/api/v1/users/me: the current user and their API keys."""

from typing import Annotated

from fastapi import APIRouter, Path, status

from notes_api.dependencies import AuthServiceDep, CurrentPrincipal
from notes_api.exceptions import AuthenticationError, PermissionDeniedError
from notes_api.models import ApiKey, User
from notes_api.schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyRead, UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
async def me(principal: CurrentPrincipal, auth: AuthServiceDep) -> User:
    """Who am I?"""
    user = await auth.users.user_by_id(principal.user_id)
    if user is None:
        raise AuthenticationError("account disabled")
    return user


@router.post("/me/api-keys", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    data: ApiKeyCreate, principal: CurrentPrincipal, auth: AuthServiceDep
) -> dict[str, object]:
    """Create a key; its full value appears in this response only."""
    if principal.method != "token":
        raise PermissionDeniedError("API keys cannot create API keys; log in first")
    key, raw_key = await auth.create_api_key(principal, data)
    return {**ApiKeyRead.model_validate(key).model_dump(), "key": raw_key}


@router.get("/me/api-keys", response_model=list[ApiKeyRead])
async def list_api_keys(principal: CurrentPrincipal, auth: AuthServiceDep) -> list[ApiKey]:
    """The caller's keys, without their secrets."""
    return await auth.users.api_keys_of(principal.user_id)


@router.delete("/me/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: Annotated[int, Path(ge=1)], principal: CurrentPrincipal, auth: AuthServiceDep
) -> None:
    """Revoke one of the caller's keys."""
    await auth.revoke_api_key(principal, key_id)
'''

NOTES_V4_ROUTERS_NOTES_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/routers/notes.py
"""/api/v1/notes: CRUD, search with offset pages, a keyset feed, and link previews."""

from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Request, Response, status

from notes_api.core.errors import PROBLEM_JSON, ProblemDetail
from notes_api.dependencies import LinkPreviewerDep, ReaderServiceDep, WriterServiceDep
from notes_api.models import Note
from notes_api.pagination import CursorPage, Page
from notes_api.schemas import FeedParams, LinkPreview, NoteCreate, NoteFilters, NoteRead, NoteUpdate

NoteId = Annotated[int, Path(ge=1, description="The note's id.")]
NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {
        "model": ProblemDetail,
        "description": "No note has this id.",
        "content": {PROBLEM_JSON: {}},
    }
}

router = APIRouter(prefix="/notes", tags=["notes"])  # every route needs a user (scopes below)


@router.post("", response_model=NoteRead, status_code=status.HTTP_201_CREATED)
async def create_note(
    note: NoteCreate, service: WriterServiceDep, request: Request, response: Response
) -> Note:
    """Create a note; the Location header points at it."""
    created = await service.create(note)
    response.headers["Location"] = request.app.url_path_for("get_note", note_id=str(created.id))
    return created


@router.get("", response_model=Page[NoteRead])
async def list_notes(
    filters: Annotated[NoteFilters, Query()], service: ReaderServiceDep
) -> dict[str, object]:
    """Search, filter, sort and paginate notes (offset pagination)."""
    notes, total = await service.search(filters)
    return {"items": notes, "total": total, "limit": filters.limit, "offset": filters.offset}


@router.get("/feed", response_model=CursorPage[NoteRead])
async def notes_feed(
    params: Annotated[FeedParams, Query()], service: ReaderServiceDep
) -> dict[str, object]:
    """Newest notes first, with keyset (cursor) pagination."""
    notes, next_cursor = await service.feed(params.limit, params.cursor)
    return {"items": notes, "limit": params.limit, "next_cursor": next_cursor}


@router.get("/{note_id}", response_model=NoteRead, responses=NOT_FOUND)
async def get_note(note_id: NoteId, service: ReaderServiceDep) -> Note:
    """Fetch one note."""
    return await service.get(note_id)


@router.put("/{note_id}", response_model=NoteRead, responses=NOT_FOUND)
async def replace_note(note_id: NoteId, note: NoteCreate, service: WriterServiceDep) -> Note:
    """Replace every field of a note (omitted fields get their defaults)."""
    return await service.replace(note_id, note)


@router.patch("/{note_id}", response_model=NoteRead, responses=NOT_FOUND)
async def update_note(note_id: NoteId, changes: NoteUpdate, service: WriterServiceDep) -> Note:
    """Change only the fields sent in the body."""
    return await service.update(note_id, changes)


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND)
async def delete_note(note_id: NoteId, service: WriterServiceDep) -> None:
    """Delete a note."""
    await service.delete(note_id)


@router.get("/{note_id}/links", response_model=list[LinkPreview], responses=NOT_FOUND)
async def note_links(
    note_id: NoteId, service: ReaderServiceDep, previewer: LinkPreviewerDep
) -> list[LinkPreview]:
    """Titles of the links in a note's body, fetched with the shared HTTP client."""
    note = await service.get(note_id)
    return await previewer.previews(note.body)
'''

NOTES_V4_ROUTERS_ADMIN_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/routers/admin.py
"""/api/v1/admin: bulk import (file upload), export and wipe. Admin role + admin scope."""

from http import HTTPStatus

from fastapi import APIRouter, Depends, UploadFile, status
from fastapi.responses import JSONResponse

from notes_api.dependencies import (
    RepositoryDep,
    SettingsDep,
    WriterServiceDep,
    require_admin,
)
from notes_api.exceptions import UploadRejectedError
from notes_api.schemas import ImportReport, NoteFilters, NoteRead
from notes_api.services import parse_import

ALLOWED_UPLOADS = {".json": {"application/json"}, ".csv": {"text/csv", "application/vnd.ms-excel"}}

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


async def read_upload(upload: UploadFile, max_bytes: int) -> bytes:
    """The file's bytes after checking its extension, content type and size."""
    filename = upload.filename or ""
    extension = filename[filename.rfind(".") :].lower() if "." in filename else ""
    content_type = (upload.content_type or "").split(";")[0].strip()
    if content_type not in ALLOWED_UPLOADS.get(extension, set()):
        detail = f"expected a .json or .csv file, got {filename!r} ({content_type or 'no type'})"
        raise UploadRejectedError(detail, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
    content = await upload.read(max_bytes + 1)  # one byte more tells us it is too large
    if len(content) > max_bytes:
        raise UploadRejectedError(
            f"file is larger than {max_bytes} bytes", HTTPStatus.CONTENT_TOO_LARGE
        )
    return content


@router.post("/import", response_model=ImportReport, status_code=status.HTTP_201_CREATED)
async def import_notes(
    file: UploadFile, service: WriterServiceDep, settings: SettingsDep
) -> ImportReport:
    """Create notes (owned by the admin) from an uploaded .json list or .csv file."""
    content = await read_upload(file, settings.max_upload_bytes)
    notes = parse_import(file.filename or "", content)
    created = await service.import_notes(notes)
    ids = [note.id for note in created]
    return ImportReport(filename=file.filename or "", imported=len(created), ids=ids)


@router.get("/export")
async def export_notes(repository: RepositoryDep) -> JSONResponse:
    """Every user's notes as a downloadable JSON file."""
    notes, _total = await repository.search(NoteFilters(limit=100, sort="created_at"), None)
    payload = [NoteRead.model_validate(note).model_dump(mode="json") for note in notes]
    headers = {"Content-Disposition": 'attachment; filename="notes.json"'}
    return JSONResponse(payload, headers=headers)


@router.delete("/notes")
async def delete_all_notes(repository: RepositoryDep) -> dict[str, int]:
    """Remove every note of every user."""
    return {"deleted": await repository.delete_all()}
'''

NOTES_V4_ROUTERS_PAGES_PY = r'''
%%writefile ../projects/notes_api/src/notes_api/routers/pages.py
"""Server-rendered pages: cookie login, CSRF protection, Jinja2 templates, HTMX partials.

Browsers send cookies automatically, so every state-changing form needs a CSRF defence. Two
layers: the session cookie is SameSite=Lax (not sent on cross-site POSTs), and every form or
HTMX request must echo a random token that is also stored in a cookie (double submit).
"""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, Header, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from notes_api.dependencies import (
    SESSION_COOKIE,
    AuthServiceDep,
    ClockDep,
    CookiePrincipalDep,
    LoginLimiterDep,
    RepositoryDep,
    SettingsDep,
)
from notes_api.exceptions import AuthenticationError, PermissionDeniedError, RateLimitedError
from notes_api.schemas import NoteCreate, NoteFilters, NoteUpdate
from notes_api.security import ROLE_SCOPES, new_secret, same_secret
from notes_api.services import NoteService

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)
CSRF_COOKIE = "notes_csrf"
CSRF_HEADER = "X-CSRF-Token"

router = APIRouter(include_in_schema=False)  # HTML for people, not part of the JSON API


def csrf_token(request: Request) -> str:
    """The browser's CSRF token (a new one if it has none yet)."""
    return request.cookies.get(CSRF_COOKIE) or new_secret(16)


def check_csrf(request: Request, sent: str | None) -> None:
    """The token in the form (or the X-CSRF-Token header) must match the cookie."""
    cookie = request.cookies.get(CSRF_COOKIE)
    sent = sent or request.headers.get(CSRF_HEADER)
    if not cookie or not sent or not same_secret(cookie, sent):
        raise PermissionDeniedError("CSRF token missing or invalid")


def render(
    request: Request,
    settings_secure: bool,
    template: str,
    context: dict[str, object],
    status_code: int = 200,
) -> Response:
    """Render a template and (re)set the CSRF cookie the page's forms will echo."""
    token = csrf_token(request)
    response = templates.TemplateResponse(
        request, template, {**context, "csrf_token": token}, status_code=status_code
    )
    response.set_cookie(
        CSRF_COOKIE, token, httponly=True, secure=settings_secure, samesite="strict"
    )
    return response


def to_login() -> RedirectResponse:
    """303 to the login page (after a POST the browser follows it with a GET)."""
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, settings: SettingsDep) -> Response:
    """The login form."""
    return render(request, settings.cookie_secure, "login.html", {"error": None, "email": ""})


@router.post("/login", response_class=HTMLResponse)
async def login_form(
    request: Request,
    settings: SettingsDep,
    auth: AuthServiceDep,
    limiter: LoginLimiterDep,
    email: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    csrf: Annotated[str | None, Form(alias="csrf_token")] = None,
) -> Response:
    """Check CSRF and the password, then set an HttpOnly session cookie and redirect."""
    check_csrf(request, csrf)
    host = request.client.host if request.client else "unknown"
    try:
        if not (await limiter.hit(f"{host}:{email.lower()}")).allowed:
            raise RateLimitedError(settings.login_rate_window_seconds)
        user = await auth.authenticate(email, password)
    except (AuthenticationError, RateLimitedError) as error:
        context = {"error": str(error), "email": email}
        return render(
            request, settings.cookie_secure, "login.html", context, status_code=error.status_code
        )
    token, lifetime = auth.tokens.create_access_token(user.id, user.role, ROLE_SCOPES[user.role])
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=lifetime,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    return response


@router.post("/logout")
async def logout_form(
    request: Request,
    principal: CookiePrincipalDep,
    auth: AuthServiceDep,
    csrf: Annotated[str | None, Form(alias="csrf_token")] = None,
) -> Response:
    """Deny the session token and delete the cookie."""
    check_csrf(request, csrf)
    if principal is not None:
        await auth.deny_access_token(principal)
    response = to_login()
    response.delete_cookie(SESSION_COOKIE)
    return response


@router.get("/", response_class=HTMLResponse)
async def notes_page(
    request: Request,
    settings: SettingsDep,
    principal: CookiePrincipalDep,
    repository: RepositoryDep,
    clock: ClockDep,
    q: str = "",
    hx_request: Annotated[str | None, Header()] = None,
) -> Response:
    """The signed-in user's notes; for an HTMX search request only the list fragment."""
    if principal is None:
        return to_login()
    service = NoteService(repository, clock, principal.user_id)
    notes, total = await service.search(NoteFilters(q=q or None, limit=50))
    context = {"notes": notes, "total": total, "q": q, "errors": [], "form": {}, "user": principal}
    template = "_notes.html" if hx_request == "true" else "index.html"
    return render(request, settings.cookie_secure, template, context)


@router.post("/notes", response_class=HTMLResponse)
async def create_from_form(
    request: Request,
    settings: SettingsDep,
    principal: CookiePrincipalDep,
    repository: RepositoryDep,
    clock: ClockDep,
    title: Annotated[str, Form()] = "",
    body: Annotated[str, Form()] = "",
    tags: Annotated[str, Form()] = "",
    csrf: Annotated[str | None, Form(alias="csrf_token")] = None,
) -> Response:
    """Create a note from the form, then redirect (303) so a reload does not re-post."""
    if principal is None:
        return to_login()
    check_csrf(request, csrf)
    service = NoteService(repository, clock, principal.user_id)
    form = {"title": title, "body": body, "tags": tags}
    try:
        data = NoteCreate(title=title, body=body, tags=tags.replace(",", " ").split())
    except ValidationError as error:
        notes, total = await service.search(NoteFilters(limit=50))
        errors = [f"{'.'.join(map(str, item['loc']))}: {item['msg']}" for item in error.errors()]
        context = {
            "notes": notes,
            "total": total,
            "q": "",
            "errors": errors,
            "form": form,
            "user": principal,
        }
        return render(request, settings.cookie_secure, "index.html", context, status_code=422)
    await service.create(data)
    return RedirectResponse(request.url_for("notes_page"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/notes/{note_id}/pin", response_class=HTMLResponse)
async def toggle_pin(
    request: Request,
    note_id: int,
    principal: CookiePrincipalDep,
    repository: RepositoryDep,
    clock: ClockDep,
) -> Response:
    """HTMX: flip the pinned flag and return just this note's fragment."""
    if principal is None:
        return to_login()
    check_csrf(request, None)  # HTMX sends the token in the X-CSRF-Token header
    service = NoteService(repository, clock, principal.user_id)
    note = await service.get(note_id)
    note = await service.update(note_id, NoteUpdate(pinned=not note.pinned))
    return templates.TemplateResponse(request, "_note.html", {"note": note})
'''

NOTES_V4_TEMPLATES_BASE_HTML = r"""
%%writefile ../projects/notes_api/src/notes_api/templates/base.html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Notes{% endblock %}</title>
  <link rel="stylesheet" href="{{ url_for('static', path='style.css') }}">
  {# HTMX is optional: without it the forms and links still work as plain HTML. #}
  <script src="https://unpkg.com/htmx.org@2.0.4" defer></script>
</head>
{# Every HTMX request sends the CSRF token in a header (double-submit check on the server). #}
<body hx-headers='{"X-CSRF-Token": "{{ csrf_token }}"}'>
  <main>{% block content %}{% endblock %}</main>
</body>
</html>
"""

NOTES_V4_TEMPLATES_INDEX_HTML = r"""
%%writefile ../projects/notes_api/src/notes_api/templates/index.html
{% extends "base.html" %}
{% block content %}
<header class="bar">
  <h1>Notes</h1>
  <form method="post" action="{{ url_for('logout_form') }}">
    <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
    <span>{{ user.email }}</span> <button type="submit">Log out</button>
  </form>
</header>
<form method="post" action="{{ url_for('create_from_form') }}" class="new-note">
  {% for error in errors %}<p class="error">{{ error }}</p>{% endfor %}
  <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
  <input name="title" placeholder="Title" value="{{ form.title or '' }}">
  <textarea name="body" placeholder="Body">{{ form.body or '' }}</textarea>
  <input name="tags" placeholder="tags, separated by spaces" value="{{ form.tags or '' }}">
  <button type="submit">Add note</button>
</form>
<input type="search" name="q" value="{{ q }}" placeholder="Search"
       hx-get="{{ url_for('notes_page') }}" hx-trigger="input changed delay:300ms"
       hx-target="#notes" hx-push-url="true">
<div id="notes">{% include "_notes.html" %}</div>
{% endblock %}
"""

NOTES_V4_TEMPLATES_LOGIN_HTML = r"""
%%writefile ../projects/notes_api/src/notes_api/templates/login.html
{% extends "base.html" %}
{% block title %}Log in{% endblock %}
{% block content %}
<h1>Log in</h1>
<form method="post" action="{{ url_for('login_form') }}" class="new-note">
  {% if error %}<p class="error">{{ error }}</p>{% endif %}
  <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
  <input name="email" type="email" placeholder="Email" value="{{ email }}" autocomplete="username">
  <input name="password" type="password" placeholder="Password" autocomplete="current-password">
  <button type="submit">Log in</button>
</form>
{% endblock %}
"""

NOTES_V4_STATIC_STYLE_CSS = r"""
%%writefile ../projects/notes_api/src/notes_api/static/style.css
body { font-family: system-ui, sans-serif; margin: 0 auto; max-width: 42rem; padding: 1rem; }
.new-note { display: grid; gap: 0.5rem; margin-bottom: 1rem; }
.notes { list-style: none; padding: 0; }
.note { border: 1px solid #ccc; border-radius: 0.5rem; margin: 0.5rem 0; padding: 0.5rem 1rem; }
.note.pinned { border-color: #c80; background: #fff8e8; }
.tag { background: #eef; border-radius: 0.25rem; font-size: 0.8rem; margin-left: 0.25rem; padding: 0 0.3rem; }
.error { color: #b00; margin: 0; }
.bar { align-items: center; display: flex; justify-content: space-between; }
"""

NOTES_V4_TESTS_CONFTEST_PY = r'''
%%writefile ../projects/notes_api/tests/conftest.py
"""Shared fixtures: each test gets its own app, SQLite file and fake Redis, and a logged-in user."""

import asyncio
import secrets
from collections.abc import Iterator
from pathlib import Path

import fakeredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from helpers import USER_EMAIL, auth_headers, create_tables, fake_resolver
from notes_api.core.config import Settings
from notes_api.dependencies import get_redis, get_resolver
from notes_api.main import create_app


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests on asyncio (the anyio pytest plugin ships with anyio)."""
    return "asyncio"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Test settings: a fresh SQLite file, a generated JWT secret, cheap Argon2 parameters."""
    return Settings(
        _env_file=None,
        environment="test",
        cors_origins=["http://localhost:5173"],
        max_upload_bytes=2048,
        database_url=SecretStr(f"sqlite+aiosqlite:///{tmp_path / 'notes.db'}"),
        jwt_secret=SecretStr(secrets.token_urlsafe(32)),
        password_time_cost=1,
        password_memory_kib=64,
        admin_emails=["admin@example.com"],
        login_rate_limit=10,
        cookie_secure=False,  # TestClient talks plain HTTP
    )


@pytest.fixture
def fake_redis() -> fakeredis.FakeAsyncRedis:
    """An in-memory Redis for one test."""
    return fakeredis.FakeAsyncRedis(decode_responses=True)


@pytest.fixture
def app(settings: Settings, fake_redis: fakeredis.FakeAsyncRedis) -> FastAPI:
    """A fresh app on an empty database, with fake Redis and fake DNS."""
    asyncio.run(create_tables(settings))
    application = create_app(settings)
    application.dependency_overrides[get_redis] = lambda: fake_redis
    application.dependency_overrides[get_resolver] = lambda: fake_resolver
    return application


@pytest.fixture
def anonymous(app: FastAPI) -> Iterator[TestClient]:
    """A TestClient without credentials; entering it runs the lifespan."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def client(anonymous: TestClient) -> TestClient:
    """The same client, logged in as an ordinary user (Authorization header on every call)."""
    anonymous.headers.update(auth_headers(anonymous, USER_EMAIL))
    return anonymous


@pytest.fixture
def admin_headers(anonymous: TestClient) -> dict[str, str]:
    """Bearer headers of an admin (admin@example.com is in admin_emails)."""
    return auth_headers(anonymous, "admin@example.com")
'''

NOTES_V4_TESTS_HELPERS_PY = r'''
%%writefile ../projects/notes_api/tests/helpers.py
"""Small helpers shared by the test modules."""

import ipaddress
from typing import Any

from fastapi.testclient import TestClient

from notes_api.core.config import Settings
from notes_api.db import Base, create_engine_from_settings

USER_EMAIL = "user@example.com"
PASSWORD = "correct horse battery staple"
ANONYMOUS = {"Authorization": ""}  # overrides the client's default header
FAKE_DNS = {
    "docs.example": ["93.184.216.34"],
    "slow.example": ["93.184.216.35"],
    "intranet.example": ["10.0.0.7"],
    "metadata.example": ["169.254.169.254"],
    "mixed.example": ["93.184.216.36", "127.0.0.1"],
}


def create(client: TestClient, **fields: Any) -> dict[str, Any]:
    """POST a note (title defaults to "Buy tea") and return the created note."""
    response = client.post("/api/v1/notes", json={"title": "Buy tea", **fields})
    assert response.status_code == 201, response.text
    return response.json()


def ids(response: Any) -> list[int]:
    """Ids of the notes on a page."""
    assert response.status_code == 200, response.text
    return [note["id"] for note in response.json()["items"]]


def register(client: TestClient, email: str, password: str = PASSWORD) -> Any:
    """POST /auth/register (without the client's default credentials)."""
    body = {"email": email, "password": password}
    return client.post("/api/v1/auth/register", json=body, headers=ANONYMOUS)


def login(client: TestClient, email: str, password: str = PASSWORD, scope: str = "") -> Any:
    """POST /auth/token with the OAuth2 password form."""
    form = {"username": email, "password": password, "scope": scope}
    return client.post("/api/v1/auth/token", data=form, headers=ANONYMOUS)


def auth_headers(client: TestClient, email: str, scope: str = "") -> dict[str, str]:
    """Register (if needed) and log in; return a Bearer header."""
    register(client, email)
    response = login(client, email, scope=scope)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def fake_resolver(host: str) -> list[str]:
    """DNS for tests: IP literals resolve to themselves, a few names to fixed addresses."""
    try:
        return [str(ipaddress.ip_address(host))]
    except ValueError:
        pass
    if host not in FAKE_DNS:
        raise OSError(f"cannot resolve {host}")
    return FAKE_DNS[host]


async def create_tables(settings: Settings) -> None:
    """CREATE TABLE for every model (fast; the PostgreSQL tests run the Alembic migrations)."""
    engine = create_engine_from_settings(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()
'''

NOTES_V4_TESTS_TEST_AUTH_PY = r'''
%%writefile ../projects/notes_api/tests/test_auth.py
"""Register, log in, refresh with rotation and reuse detection, log out, rate limits, API keys."""

import pytest
from fastapi.testclient import TestClient

from helpers import ANONYMOUS, PASSWORD, USER_EMAIL, login, register

ME = "/api/v1/users/me"


def bearer(token: str) -> dict[str, str]:
    """An Authorization header."""
    return {"Authorization": f"Bearer {token}"}


def test_register_returns_the_user_without_secrets(anonymous: TestClient) -> None:
    """201 with id, email and role; no hash; emails are case-insensitive and unique."""
    response = register(anonymous, "Asha@Example.com")
    assert response.status_code == 201
    assert set(response.json()) == {"id", "email", "role", "created_at"}
    assert response.json()["email"] == "asha@example.com"
    duplicate = register(anonymous, "asha@example.com")
    assert (duplicate.status_code, duplicate.json()["type"]) == (409, "/problems/email-taken")


@pytest.mark.parametrize(
    "body",
    [
        {"email": "x@example.com", "password": "short"},
        {"email": "x@example.com", "password": "long enough pass", "role": "admin"},
    ],
)
def test_register_rejects_weak_passwords_and_role_fields(
    anonymous: TestClient, body: dict[str, str]
) -> None:
    """Passwords need 12+ characters; clients cannot choose their role (mass assignment)."""
    assert anonymous.post("/api/v1/auth/register", json=body).status_code == 422


def test_login_and_me(anonymous: TestClient) -> None:
    """The password grant returns a token pair; /users/me needs the access token."""
    register(anonymous, USER_EMAIL)
    tokens = login(anonymous, USER_EMAIL).json()
    assert (tokens["token_type"], tokens["expires_in"], tokens["scope"]) == (
        "bearer",
        900,
        "notes:read notes:write",
    )
    assert anonymous.get(ME, headers=bearer(tokens["access_token"])).json()["email"] == USER_EMAIL
    missing = anonymous.get(ME)
    assert (missing.status_code, missing.headers["www-authenticate"]) == (401, "Bearer")


def test_wrong_password_and_unknown_user_look_the_same(anonymous: TestClient) -> None:
    """Same status and message, so the API does not reveal which emails exist."""
    register(anonymous, USER_EMAIL)
    wrong = login(anonymous, USER_EMAIL, password="not the password")
    unknown = login(anonymous, "nobody@example.com")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"] == "incorrect email or password"


def test_refresh_rotates_and_detects_reuse(anonymous: TestClient) -> None:
    """A refresh token works once; replaying an old one revokes the whole family."""
    register(anonymous, USER_EMAIL)
    first = login(anonymous, USER_EMAIL).json()
    second = anonymous.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert second.status_code == 200 and second.json()["refresh_token"] != first["refresh_token"]
    replay = anonymous.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert (replay.status_code, replay.json()["detail"]) == (
        401,
        "refresh token reuse detected; please log in again",
    )
    newest = anonymous.post(
        "/api/v1/auth/refresh", json={"refresh_token": second.json()["refresh_token"]}
    )
    assert newest.status_code == 401  # the thief's (or the user's) newer token is revoked too


def test_logout_revokes_refresh_and_access_tokens(anonymous: TestClient) -> None:
    """After logout neither the refresh token nor the access token works."""
    register(anonymous, USER_EMAIL)
    tokens = login(anonymous, USER_EMAIL).json()
    body = {"refresh_token": tokens["refresh_token"]}
    assert (
        anonymous.post(
            "/api/v1/auth/logout", json=body, headers=bearer(tokens["access_token"])
        ).status_code
        == 204
    )
    assert anonymous.post("/api/v1/auth/refresh", json=body).status_code == 401
    denied = anonymous.get(ME, headers=bearer(tokens["access_token"]))
    assert (denied.status_code, denied.json()["detail"]) == (401, "access token revoked")


def test_login_is_rate_limited(anonymous: TestClient) -> None:
    """After the window's budget (10 in tests) the API answers 429 with Retry-After."""
    register(anonymous, USER_EMAIL)
    statuses = [login(anonymous, USER_EMAIL, password="guess").status_code for _ in range(10)]
    blocked = login(anonymous, USER_EMAIL, password=PASSWORD)  # even the right password waits
    assert set(statuses) == {401}
    assert (blocked.status_code, blocked.json()["type"]) == (429, "/problems/rate-limited")
    assert 1 <= int(blocked.headers["retry-after"]) <= 60


def test_scopes_limit_what_a_token_can_do(anonymous: TestClient) -> None:
    """A read-only token can list notes but not create them (403 names the missing scope)."""
    register(anonymous, USER_EMAIL)
    read_only = login(anonymous, USER_EMAIL, scope="notes:read").json()
    headers = bearer(read_only["access_token"])
    assert anonymous.get("/api/v1/notes", headers=headers).status_code == 200
    refused = anonymous.post("/api/v1/notes", json={"title": "x"}, headers=headers)
    assert (refused.status_code, refused.json()["detail"]) == (403, "missing scope(s): notes:write")
    too_much = login(anonymous, USER_EMAIL, scope="admin")
    assert too_much.status_code == 403  # an ordinary user cannot even ask for the admin scope


def test_tampered_token_is_rejected(client: TestClient) -> None:
    """Changing one character of the signature invalidates the token."""
    token = client.headers["authorization"].removeprefix("Bearer ")
    tampered = token[:-2] + ("A" if token[-2] != "A" else "B") + token[-1]
    assert client.get(ME, headers=bearer(tampered)).status_code == 401


def test_api_keys_are_shown_once_hashed_and_scoped(client: TestClient) -> None:
    """Create a read-only key, use it, list it without the secret, revoke it."""
    created = client.post(
        "/api/v1/users/me/api-keys", json={"name": "cli", "scopes": ["notes:read"]}
    )
    assert created.status_code == 201
    key = created.json()["key"]
    assert key.startswith("nk_") and created.json()["prefix"] == key[:10]
    with_key = {"X-API-Key": key, **ANONYMOUS}
    assert client.get("/api/v1/notes", headers=with_key).status_code == 200
    assert client.post("/api/v1/notes", json={"title": "x"}, headers=with_key).status_code == 403
    listed = client.get("/api/v1/users/me/api-keys").json()
    assert "key" not in listed[0] and listed[0]["last_used_at"] is not None
    assert client.delete(f"/api/v1/users/me/api-keys/{listed[0]['id']}").status_code == 204
    assert client.get("/api/v1/notes", headers=with_key).status_code == 401
    assert client.delete("/api/v1/users/me/api-keys/999").status_code == 404


def test_api_keys_cannot_create_api_keys(client: TestClient) -> None:
    """A leaked key must not be able to mint more keys."""
    key = client.post("/api/v1/users/me/api-keys", json={"name": "ci"}).json()["key"]
    response = client.post(
        "/api/v1/users/me/api-keys", json={"name": "more"}, headers={"X-API-Key": key, **ANONYMOUS}
    )
    assert response.status_code == 403
'''

NOTES_V4_TESTS_TEST_BOLA_PY = r'''
%%writefile ../projects/notes_api/tests/test_bola.py
"""Broken Object Level Authorization (OWASP API1): users see and change only their own notes."""

import pytest
from fastapi.testclient import TestClient

from helpers import auth_headers, create

NOTES = "/api/v1/notes"


@pytest.fixture
def intruder(client: TestClient) -> dict[str, str]:
    """Bearer headers of a second, unrelated user."""
    return auth_headers(client, "intruder@example.com")


@pytest.mark.parametrize("method", ["GET", "PUT", "PATCH", "DELETE"])
def test_someone_elses_note_is_not_found(
    client: TestClient, intruder: dict[str, str], method: str
) -> None:
    """Every operation on another user's note is a 404, exactly like a missing note (no 403
    that would confirm the id exists)."""
    note = create(client, title="Mine")
    response = client.request(
        method, f"{NOTES}/{note['id']}", json={"title": "pwned"}, headers=intruder
    )
    missing = client.request(method, f"{NOTES}/9999", json={"title": "x"}, headers=intruder)
    assert response.status_code == missing.status_code == 404
    assert client.get(f"{NOTES}/{note['id']}").json()["title"] == "Mine"


def test_lists_feeds_and_links_are_per_user(client: TestClient, intruder: dict[str, str]) -> None:
    """Search, the feed and link previews only ever touch the caller's notes."""
    note = create(client, title="Mine")
    client.post(NOTES, json={"title": "Theirs"}, headers=intruder)
    assert [item["title"] for item in client.get(NOTES).json()["items"]] == ["Mine"]
    assert [
        item["title"] for item in client.get(f"{NOTES}/feed", headers=intruder).json()["items"]
    ] == ["Theirs"]
    assert client.get(f"{NOTES}/{note['id']}/links", headers=intruder).status_code == 404
'''

NOTES_V4_TESTS_TEST_SECURITY_PY = r'''
%%writefile ../projects/notes_api/tests/test_security.py
"""Password rehashing, forged and expired tokens, log redaction, SSRF protection."""

import asyncio
import base64
import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
import respx
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from helpers import ANONYMOUS, USER_EMAIL, create, login, register
from notes_api.core.config import Settings
from notes_api.core.logging import REDACTED, RedactingFilter, redact_text
from notes_api.db import create_engine_from_settings
from notes_api.main import create_app
from notes_api.security import TokenService, make_password_hasher

ME = "/api/v1/users/me"


def b64(data: dict[str, object]) -> str:
    """base64url(JSON) without padding, as in a JWT."""
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def stored_hash(settings: Settings, email: str) -> str:
    """The password hash in the database."""

    async def read() -> str:
        """One SELECT."""
        engine = create_engine_from_settings(settings)
        async with engine.connect() as connection:
            query = sa.text("SELECT password_hash FROM users WHERE email = :email")
            value = (await connection.execute(query, {"email": email})).scalar_one()
        await engine.dispose()
        return value

    return asyncio.run(read())


def test_login_rehashes_outdated_hashes(
    anonymous: TestClient, app: FastAPI, settings: Settings
) -> None:
    """Raising the Argon2 cost upgrades each user's hash at their next successful login."""
    register(anonymous, USER_EMAIL)
    assert ",t=1," in stored_hash(settings, USER_EMAIL)
    app.state.password_hasher = make_password_hasher(time_cost=2, memory_kib=64)
    assert login(anonymous, USER_EMAIL).status_code == 200
    assert ",t=2," in stored_hash(settings, USER_EMAIL)


@pytest.mark.parametrize("header", [{"alg": "none", "typ": "JWT"}, {"alg": "RS256", "typ": "JWT"}])
def test_tokens_with_another_algorithm_are_rejected(
    anonymous: TestClient, header: dict[str, str]
) -> None:
    """The server fixes the algorithm (HS256); 'none' and algorithm-confusion tokens fail."""
    register(anonymous, USER_EMAIL)
    claims = {
        "sub": "1",
        "iss": "notes-api",
        "aud": "notes-api",
        "exp": 4_102_444_800,
        "iat": 1,
        "jti": "x",
        "scope": "notes:read",
        "type": "access",
    }
    forged = f"{b64(header)}.{b64(claims)}.{'' if header['alg'] == 'none' else 'c2ln'}"
    assert anonymous.get(ME, headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_expired_and_foreign_tokens_are_rejected(anonymous: TestClient, app: FastAPI) -> None:
    """Expiry, issuer and audience are all checked."""
    register(anonymous, USER_EMAIL)
    secret = app.state.jwt_secret
    past = TokenService(
        secret,
        "notes-api",
        "notes-api",
        timedelta(minutes=5),
        lambda: datetime.now(UTC) - timedelta(hours=1),
    )
    other_audience = TokenService(
        secret, "notes-api", "another-api", timedelta(minutes=5), lambda: datetime.now(UTC)
    )
    expired, _ = past.create_access_token(1, "user", {"notes:read"})
    foreign, _ = other_audience.create_access_token(1, "user", {"notes:read"})
    response = anonymous.get(ME, headers={"Authorization": f"Bearer {expired}"})
    assert (response.status_code, response.json()["detail"]) == (401, "access token expired")
    assert anonymous.get(ME, headers={"Authorization": f"Bearer {foreign}"}).status_code == 401


def test_redaction_of_logged_secrets(caplog: pytest.LogCaptureFixture) -> None:
    """Bearer tokens, JWT-shaped strings, API keys and key=value secrets never reach a handler."""
    logger = logging.getLogger("notes_api.redaction-test")
    logger.addFilter(RedactingFilter())
    with caplog.at_level(logging.INFO, logger="notes_api.redaction-test"):
        logger.info("Authorization: Bearer abc.def.ghi password=hunter2 key=%s", "nk_" + "a" * 30)
        logger.info("payload %(user)s", {"user": "asha", "refresh_token": "r" * 20})
    text = caplog.text
    assert "hunter2" not in text and "abc.def.ghi" not in text and "nk_aaaa" not in text
    assert f"Bearer {REDACTED}" in text and f"password={REDACTED}" in text and "asha" in text
    assert redact_text("token: eyJhbGciOi.eyJzdWIi.c2ln") == f"token: {REDACTED}"


@respx.mock
@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://intranet.example/admin", "blocked: not a public address"),
        ("http://metadata.example/latest/meta-data", "blocked: not a public address"),
        ("http://mixed.example/", "blocked: not a public address"),
        ("http://127.0.0.1:8000/admin", "blocked: not a public address"),
        ("http://unknown.example/", "host does not resolve"),
    ],
)
def test_link_previews_refuse_private_targets(client: TestClient, url: str, reason: str) -> None:
    """SSRF (OWASP API7): private, loopback, link-local and unresolvable hosts are never fetched."""
    note = create(client, body=f"see {url}")
    assert client.get(f"/api/v1/notes/{note['id']}/links").json() == [
        {"url": url, "status_code": None, "title": None, "error": reason}
    ]
    assert respx.calls.call_count == 0


@respx.mock
def test_link_previews_do_not_follow_redirects(client: TestClient) -> None:
    """A public page that redirects (possibly to a private address) is not followed."""
    respx.get("https://docs.example/old").respond(302, headers={"Location": "http://10.0.0.7/"})
    note = create(client, body="https://docs.example/old")
    preview = client.get(f"/api/v1/notes/{note['id']}/links").json()[0]
    assert (preview["status_code"], preview["error"]) == (302, "redirect not followed")


def test_anonymous_cannot_read_notes(client: TestClient) -> None:
    """Every notes route needs credentials (401 + WWW-Authenticate with the scope)."""
    response = client.get("/api/v1/notes", headers=ANONYMOUS)
    assert (response.status_code, response.headers["www-authenticate"]) == (
        401,
        'Bearer scope="notes:read"',
    )


def test_placeholder_jwt_secret_is_never_used(settings: Settings) -> None:
    """Copying .env.example unchanged must not sign tokens with 'change-me'."""
    app = create_app(settings.model_copy(update={"jwt_secret": SecretStr("change-me")}))
    assert app.state.jwt_secret != "change-me" and len(app.state.jwt_secret) >= 40
'''

NOTES_V4_TESTS_TEST_OAUTH_PY = r'''
%%writefile ../projects/notes_api/tests/test_oauth.py
"""OpenID Connect login against a mocked provider (respx): PKCE, state, nonce, ID-token checks."""

import asyncio
import base64
import hashlib
import json
import time
import urllib.parse
from collections.abc import Iterator
from typing import Any

import fakeredis
import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from helpers import ANONYMOUS, create_tables, fake_resolver, register
from notes_api.core.config import Settings
from notes_api.dependencies import get_redis, get_resolver
from notes_api.main import create_app
from notes_api.oauth import pkce_challenge

ISSUER = "https://id.example"
PROVIDER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWK = {
    **json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(PROVIDER_KEY.public_key())),
    "kid": "key-1",
    "use": "sig",
    "alg": "RS256",
}


def id_token(nonce: str, overrides: dict[str, Any] | None = None) -> str:
    """An ID token as the provider would sign it (overrides replace claims)."""
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": "notes-web",
        "sub": "user-42",
        "email": "oidc@example.com",
        "email_verified": True,
        "nonce": nonce,
        "iat": now,
        "exp": now + 300,
    }
    claims |= overrides or {}
    return jwt.encode(claims, PROVIDER_KEY, algorithm="RS256", headers={"kid": "key-1"})


@pytest.fixture
def oidc_client(settings: Settings, fake_redis: fakeredis.FakeAsyncRedis) -> Iterator[TestClient]:
    """An app with OpenID Connect configured for the fake provider."""
    configured = settings.model_copy(
        update={
            "oauth_client_id": "notes-web",
            "oauth_authorize_url": f"{ISSUER}/authorize",
            "oauth_token_url": f"{ISSUER}/token",
            "oauth_jwks_url": f"{ISSUER}/jwks",
            "oauth_issuer": ISSUER,
        }
    )
    asyncio.run(create_tables(configured))
    application = create_app(configured)
    application.dependency_overrides[get_redis] = lambda: fake_redis
    application.dependency_overrides[get_resolver] = lambda: fake_resolver
    with TestClient(application) as test_client:
        yield test_client


def start_login(client: TestClient) -> dict[str, str]:
    """GET /oauth/login and return the query parameters of the provider redirect."""
    response = client.get("/api/v1/auth/oauth/login", follow_redirects=False)
    assert response.status_code == 302
    location = urllib.parse.urlsplit(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == f"{ISSUER}/authorize"
    return dict(urllib.parse.parse_qsl(location.query))


def mock_provider(token_response: dict[str, Any]) -> respx.Route:
    """The provider's token and JWKS endpoints."""
    respx.get(f"{ISSUER}/jwks").respond(json={"keys": [JWK]})
    return respx.post(f"{ISSUER}/token").respond(json=token_response)


@respx.mock
def test_full_login_with_pkce(oidc_client: TestClient) -> None:
    """The callback exchanges the code with the PKCE verifier and returns our own tokens."""
    query = start_login(oidc_client)
    assert (query["code_challenge_method"], query["response_type"], query["scope"]) == (
        "S256",
        "code",
        "openid email",
    )
    token_route = mock_provider({"id_token": id_token(query["nonce"]), "token_type": "Bearer"})
    response = oidc_client.get(
        "/api/v1/auth/oauth/callback", params={"code": "abc", "state": query["state"]}
    )
    assert response.status_code == 200, response.text
    sent = dict(urllib.parse.parse_qsl(token_route.calls.last.request.content.decode()))
    assert pkce_challenge(sent["code_verifier"]) == query["code_challenge"]
    me = oidc_client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {response.json()['access_token']}"}
    )
    assert me.json()["email"] == "oidc@example.com"


@respx.mock
def test_state_is_single_use(oidc_client: TestClient) -> None:
    """An unknown or replayed state is refused before any call to the provider."""
    query = start_login(oidc_client)
    mock_provider({"id_token": id_token(query["nonce"])})
    params = {"code": "abc", "state": query["state"]}
    assert oidc_client.get("/api/v1/auth/oauth/callback", params=params).status_code == 200
    replay = oidc_client.get("/api/v1/auth/oauth/callback", params=params)
    assert (replay.status_code, replay.json()["detail"]) == (401, "unknown or expired login state")


@respx.mock
@pytest.mark.parametrize(
    ("overrides", "detail"),
    [
        ({"nonce": "another-login"}, "ID token nonce mismatch"),
        ({"email_verified": False}, "the provider did not confirm an email address"),
        ({"aud": "someone-else"}, "invalid ID token: Audience doesn't match"),
        ({"iss": "https://evil.example"}, "invalid ID token: Invalid issuer"),
    ],
)
def test_bad_id_tokens_are_refused(
    oidc_client: TestClient, overrides: dict[str, Any], detail: str
) -> None:
    """Nonce, verified email, audience and issuer are all checked."""
    query = start_login(oidc_client)
    mock_provider({"id_token": id_token(query["nonce"], overrides)})
    response = oidc_client.get(
        "/api/v1/auth/oauth/callback", params={"code": "abc", "state": query["state"]}
    )
    assert (response.status_code, response.json()["detail"]) == (401, detail)


@respx.mock
def test_existing_account_is_linked_by_verified_email(oidc_client: TestClient) -> None:
    """A user who registered with a password can also sign in with the provider."""
    registered = register(oidc_client, "oidc@example.com").json()
    query = start_login(oidc_client)
    mock_provider({"id_token": id_token(query["nonce"])})
    tokens = oidc_client.get(
        "/api/v1/auth/oauth/callback", params={"code": "abc", "state": query["state"]}
    ).json()
    me = oidc_client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.json()["id"] == registered["id"]


def test_login_is_404_when_not_configured(anonymous: TestClient) -> None:
    """Without provider settings the routes do not exist for clients."""
    assert (
        anonymous.get(
            "/api/v1/auth/oauth/login", headers=ANONYMOUS, follow_redirects=False
        ).status_code
        == 404
    )


def test_pkce_challenge_is_unpadded_base64url_sha256() -> None:
    """S256 (RFC 7636): base64url(SHA-256(ASCII verifier)) with the '=' padding removed."""
    verifier = "a-verifier-of-at-least-43-characters-0123456789"
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode()
    assert pkce_challenge(verifier) == expected.rstrip("=") and len(pkce_challenge(verifier)) == 43
'''

NOTES_V4_TESTS_TEST_PAGES_PY = r'''
%%writefile ../projects/notes_api/tests/test_pages.py
"""Server-rendered pages: cookie login, CSRF, owner-only lists, HTMX fragments, static files."""

from fastapi.testclient import TestClient

from helpers import ANONYMOUS, PASSWORD, USER_EMAIL, auth_headers, register


def page_login(client: TestClient, email: str = USER_EMAIL) -> str:
    """Log in through the HTML form; return the CSRF token the pages use."""
    register(client, email)
    client.get("/login")
    csrf = client.cookies["notes_csrf"]
    form = {"email": email, "password": PASSWORD, "csrf_token": csrf}
    response = client.post("/login", data=form, follow_redirects=False)
    assert (response.status_code, response.headers["location"]) == (303, "/"), response.text
    return csrf


def test_pages_redirect_to_login(anonymous: TestClient) -> None:
    """Without a session cookie the page sends the browser to the login form."""
    response = anonymous.get("/", follow_redirects=False)
    assert (response.status_code, response.headers["location"]) == (303, "/login")


def test_login_sets_an_httponly_samesite_cookie(anonymous: TestClient) -> None:
    """The session cookie is invisible to JavaScript and not sent on cross-site POSTs."""
    register(anonymous, USER_EMAIL)
    anonymous.get("/login")
    form = {
        "email": USER_EMAIL,
        "password": PASSWORD,
        "csrf_token": anonymous.cookies["notes_csrf"],
    }
    cookie = anonymous.post("/login", data=form, follow_redirects=False).headers["set-cookie"]
    assert cookie.startswith("notes_session=") and "HttpOnly" in cookie and "SameSite=lax" in cookie


def test_wrong_password_shows_the_form_again(anonymous: TestClient) -> None:
    """A failed login re-renders the form with a 401 and keeps the email."""
    register(anonymous, USER_EMAIL)
    anonymous.get("/login")
    form = {"email": USER_EMAIL, "password": "nope", "csrf_token": anonymous.cookies["notes_csrf"]}
    response = anonymous.post("/login", data=form)
    assert response.status_code == 401 and "incorrect email or password" in response.text


def test_page_lists_only_my_notes_escaped(anonymous: TestClient) -> None:
    """The page shows the user's notes (escaped), never another user's."""
    mine = auth_headers(anonymous, USER_EMAIL)
    theirs = auth_headers(anonymous, "other@example.com")
    anonymous.post("/api/v1/notes", json={"title": "Buy <tea>"}, headers=mine)
    anonymous.post("/api/v1/notes", json={"title": "Secret plan"}, headers=theirs)
    page_login(anonymous)
    page = anonymous.get("/").text
    assert "Buy &lt;tea&gt;" in page and "Buy <tea>" not in page and "Secret plan" not in page


def test_form_post_needs_the_csrf_token(anonymous: TestClient) -> None:
    """A form post without (or with a wrong) CSRF token is refused with 403."""
    page_login(anonymous)
    assert anonymous.post("/notes", data={"title": "x"}).status_code == 403
    assert anonymous.post("/notes", data={"title": "x", "csrf_token": "forged"}).status_code == 403


def test_form_post_redirects_with_303(anonymous: TestClient) -> None:
    """A valid form creates the note and redirects back (Post/Redirect/Get)."""
    csrf = page_login(anonymous)
    form = {"title": "From the form", "tags": "home, todo", "csrf_token": csrf}
    response = anonymous.post("/notes", data=form, follow_redirects=False)
    assert response.status_code == 303
    assert "From the form" in anonymous.get("/").text


def test_invalid_form_is_shown_again_with_errors(anonymous: TestClient) -> None:
    """An invalid form re-renders the page (422) with the message and the typed values."""
    csrf = page_login(anonymous)
    response = anonymous.post("/notes", data={"title": "", "body": "keep me", "csrf_token": csrf})
    assert response.status_code == 422
    assert "title:" in response.text and "keep me" in response.text


def test_htmx_search_and_pin(anonymous: TestClient) -> None:
    """HX-Request returns the list fragment; the pin button needs the CSRF header."""
    csrf = page_login(anonymous)
    for title in ("Tea", "Rice"):
        anonymous.post("/notes", data={"title": title, "csrf_token": csrf})
    fragment = anonymous.get("/", params={"q": "tea"}, headers={"HX-Request": "true"}).text
    assert "<html" not in fragment and "Tea" in fragment and "Rice" not in fragment
    assert anonymous.post("/notes/1/pin").status_code == 403
    pinned = anonymous.post("/notes/1/pin", headers={"X-CSRF-Token": csrf}).text
    assert 'class="note pinned"' in pinned and "Unpin" in pinned


def test_logout_ends_the_session(anonymous: TestClient) -> None:
    """After logout the old cookie value no longer works (its token is denied)."""
    csrf = page_login(anonymous)
    session = anonymous.cookies["notes_session"]
    anonymous.post("/logout", data={"csrf_token": csrf}, follow_redirects=False)
    anonymous.cookies.set("notes_session", session)  # an attacker replaying the stolen cookie
    response = anonymous.get("/", follow_redirects=False)
    assert response.status_code == 303


def test_static_css_is_served(anonymous: TestClient) -> None:
    """StaticFiles serves the stylesheet."""
    response = anonymous.get("/static/style.css", headers=ANONYMOUS)
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/css")
'''

NOTES_V4_TESTS_TEST_ADMIN_PY = r'''
%%writefile ../projects/notes_api/tests/test_admin.py
"""The admin router: a router-level API key, uploads with validation, export and wipe."""

import json

import pytest
from fastapi.testclient import TestClient

from helpers import ANONYMOUS, auth_headers, create

IMPORT = "/api/v1/admin/import"
NOTES_JSON = json.dumps([{"title": "Tea", "tags": ["shop"]}, {"title": "Rice", "pinned": True}])
NOTES_CSV = "title,body,tags,pinned\nTea,Assam,shop;food,false\nRice,,shop,true\n"


def test_admin_routes_need_an_admin(client: TestClient, admin_headers: dict[str, str]) -> None:
    """Anonymous → 401, ordinary user → 403, admin → 200 on every admin route."""
    for method, path in [("GET", "/api/v1/admin/export"), ("DELETE", "/api/v1/admin/notes")]:
        assert client.request(method, path, headers=ANONYMOUS).status_code == 401
        forbidden = client.request(method, path)
        assert (forbidden.status_code, forbidden.json()["type"]) == (403, "/problems/forbidden")
        assert client.request(method, path, headers=admin_headers).status_code == 200


def test_admin_token_without_the_admin_scope_is_refused(anonymous: TestClient) -> None:
    """The role is not enough: a token issued without the admin scope cannot use admin routes."""
    narrow = auth_headers(anonymous, "admin@example.com", scope="notes:read notes:write")
    response = anonymous.get("/api/v1/admin/export", headers=narrow)
    assert (response.status_code, response.json()["detail"]) == (403, "missing scope(s): admin")


@pytest.mark.parametrize(
    ("filename", "content", "content_type"),
    [("notes.json", NOTES_JSON, "application/json"), ("notes.csv", NOTES_CSV, "text/csv")],
)
def test_import_json_and_csv(
    client: TestClient,
    admin_headers: dict[str, str],
    filename: str,
    content: str,
    content_type: str,
) -> None:
    """Both formats create the same notes."""
    files = {"file": (filename, content.encode(), content_type)}
    report = client.post(IMPORT, files=files, headers=admin_headers)
    assert report.status_code == 201, report.text
    assert report.json() == {"filename": filename, "imported": 2, "ids": [1, 2]}
    params = {"sort": "created_at"}
    notes = client.get("/api/v1/notes", params=params, headers=admin_headers).json()["items"]
    assert [(note["title"], note["pinned"]) for note in notes] == [("Tea", False), ("Rice", True)]


@pytest.mark.parametrize(
    ("filename", "content", "content_type", "status"),
    [
        ("notes.txt", b"hello", "text/plain", 415),
        ("notes.json", b"[]", "text/csv", 415),
        ("notes.json", b"[" + b" " * 4096 + b"]", "application/json", 413),
        ("notes.json", b'[{"title": ""}]', "application/json", 422),
        ("notes.json", b"not json", "application/json", 422),
    ],
)
def test_import_rejects_bad_files(
    client: TestClient,
    admin_headers: dict[str, str],
    filename: str,
    content: bytes,
    content_type: str,
    status: int,
) -> None:
    """Wrong type → 415, too large → 413, invalid content → 422; nothing is imported."""
    files = {"file": (filename, content, content_type)}
    response = client.post(IMPORT, files=files, headers=admin_headers)
    assert response.status_code == status, response.text
    assert response.json()["type"] == "/problems/upload-rejected"
    assert client.get("/api/v1/notes").json()["total"] == 0


def test_export_and_delete_all(client: TestClient, admin_headers: dict[str, str]) -> None:
    """Export downloads every note; delete removes them all."""
    create(client, title="Tea")
    create(client, title="Rice")
    export = client.get("/api/v1/admin/export", headers=admin_headers)
    assert export.headers["content-disposition"] == 'attachment; filename="notes.json"'
    assert [note["title"] for note in export.json()] == ["Tea", "Rice"]
    assert client.delete("/api/v1/admin/notes", headers=admin_headers).json() == {"deleted": 2}
    assert client.get("/api/v1/notes").json()["total"] == 0
'''

NOTES_V4_TESTS_TEST_SETTINGS_PY = r'''
%%writefile ../projects/notes_api/tests/test_settings.py
"""pydantic-settings: environment variables, .env files, secrets and production rules."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from notes_api.core.config import Settings, get_settings

STRONG_SECRET = "x" * 40


def test_environment_variables_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """NOTES_* variables are read and converted (JSON for lists)."""
    monkeypatch.setenv("NOTES_DEBUG", "true")
    monkeypatch.setenv("NOTES_CORS_ORIGINS", '["https://a.example", "https://b.example"]')
    monkeypatch.setenv("NOTES_ACCESS_TOKEN_MINUTES", "5")
    settings = Settings(_env_file=None)
    assert (settings.debug, settings.cors_origins, settings.access_token_minutes) == (
        True,
        ["https://a.example", "https://b.example"],
        5,
    )


def test_env_file_is_read_and_variables_win(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A .env file supplies values; a real environment variable overrides it."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "NOTES_APP_NAME=From file\nNOTES_JWT_SECRET=file-secret\n", encoding="utf-8"
    )
    monkeypatch.setenv("NOTES_JWT_SECRET", "env-secret")
    settings = Settings(_env_file=env_file)
    assert settings.app_name == "From file"
    assert (
        settings.jwt_secret is not None and settings.jwt_secret.get_secret_value() == "env-secret"
    )


def test_secrets_are_hidden_in_repr_and_dumps() -> None:
    """SecretStr never shows its value unless asked explicitly."""
    settings = Settings(_env_file=None, jwt_secret="s3cret-value")
    assert "s3cret-value" not in repr(settings)
    assert settings.model_dump(mode="json")["jwt_secret"] == "**********"
    assert "notes:notes@" not in repr(settings)  # the database password is a secret too


@pytest.mark.parametrize("secret", [None, "change-me", "too-short"])
def test_production_needs_a_strong_jwt_secret(secret: str | None) -> None:
    """Missing, placeholder or short secrets stop a production app from starting."""
    with pytest.raises(ValidationError, match="NOTES_JWT_SECRET"):
        Settings(_env_file=None, environment="production", jwt_secret=secret)


def test_production_needs_secure_cookies() -> None:
    """Session cookies must be HTTPS-only in production."""
    with pytest.raises(ValidationError, match="NOTES_COOKIE_SECURE"):
        Settings(
            _env_file=None, environment="production", jwt_secret=STRONG_SECRET, cookie_secure=False
        )


def test_oauth_is_enabled_only_when_fully_configured() -> None:
    """Every OpenID Connect setting must be present."""
    partial = Settings(_env_file=None, oauth_client_id="notes")
    assert partial.oauth_enabled is False
    full = partial.model_copy(
        update={
            "oauth_authorize_url": "https://id.example/authorize",
            "oauth_token_url": "https://id.example/token",
            "oauth_jwks_url": "https://id.example/jwks",
            "oauth_issuer": "https://id.example",
        }
    )
    assert full.oauth_enabled is True


def test_get_settings_is_cached() -> None:
    """The settings reader builds Settings once per process."""
    get_settings.cache_clear()
    assert get_settings() is get_settings()
    get_settings.cache_clear()
'''

NOTES_V4_TESTS_TEST_MIDDLEWARE_PY = r'''
%%writefile ../projects/notes_api/tests/test_middleware.py
"""Request ids, Server-Timing, GZip, CORS and the order of the middleware stack."""

import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from helpers import create
from notes_api.core.middleware import RequestIdMiddleware, TimingMiddleware


def test_request_id_is_generated_echoed_or_replaced(client: TestClient) -> None:
    """No header → a new hex id; a safe header is reused; an unsafe one is replaced."""
    generated = client.get("/health").headers["x-request-id"]
    assert re.fullmatch(r"[0-9a-f]{32}", generated)
    assert (
        client.get("/health", headers={"X-Request-ID": "abc-123"}).headers["x-request-id"]
        == "abc-123"
    )
    replaced = client.get("/health", headers={"X-Request-ID": "bad id\twith spaces"}).headers[
        "x-request-id"
    ]
    assert re.fullmatch(r"[0-9a-f]{32}", replaced)


def test_problem_bodies_carry_the_request_id(client: TestClient) -> None:
    """The id in the error body matches the header, so a client can quote it in a report."""
    response = client.get("/api/v1/notes/99", headers={"X-Request-ID": "trace-42"})
    assert response.json()["request_id"] == response.headers["x-request-id"] == "trace-42"


def test_server_timing_header(client: TestClient) -> None:
    """Every response says how long the app took, in milliseconds."""
    assert re.fullmatch(r"app;dur=\d+\.\d", client.get("/health").headers["server-timing"])


def test_large_responses_are_gzipped(client: TestClient) -> None:
    """Responses over 1000 bytes are compressed when the client accepts gzip."""
    for number in range(10):
        create(client, title=f"Note {number}", body="lorem ipsum " * 20)
    big = client.get("/api/v1/notes", headers={"Accept-Encoding": "gzip"})
    small = client.get("/health", headers={"Accept-Encoding": "gzip"})
    assert big.headers["content-encoding"] == "gzip"
    assert "content-encoding" not in small.headers


def test_cors_preflight_for_an_allowed_and_a_foreign_origin(client: TestClient) -> None:
    """The configured origin may send X-API-Key; other origins get no CORS headers."""
    preflight = {
        "Access-Control-Request-Method": "PATCH",
        "Access-Control-Request-Headers": "x-api-key",
    }
    allowed = client.options(
        "/api/v1/notes/1", headers={"Origin": "http://localhost:5173", **preflight}
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "PATCH" in allowed.headers["access-control-allow-methods"]
    foreign = client.options(
        "/api/v1/notes/1", headers={"Origin": "https://evil.example", **preflight}
    )
    assert foreign.status_code == 400
    assert "access-control-allow-origin" not in foreign.headers


def test_simple_cors_request_exposes_headers(client: TestClient) -> None:
    """A cross-origin GET may read X-Request-ID because the app exposes it."""
    response = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert "X-Request-ID" in response.headers["access-control-expose-headers"]


def test_middleware_order(app: FastAPI) -> None:
    """Outermost first: request id, security headers, CORS, GZip, timing."""
    names = [middleware.cls.__name__ for middleware in app.user_middleware]
    assert names == [
        "RequestIdMiddleware",
        "SecurityHeadersMiddleware",
        "CORSMiddleware",
        "GZipMiddleware",
        "TimingMiddleware",
    ]
    assert {RequestIdMiddleware, TimingMiddleware} <= {
        middleware.cls for middleware in app.user_middleware
    }


def test_security_headers(client: TestClient) -> None:
    """HSTS, nosniff, frame denial and a CSP on API responses; the docs get their own CSP."""
    headers = client.get("/health").headers
    assert headers["strict-transport-security"].startswith("max-age=31536000")
    assert (headers["x-content-type-options"], headers["x-frame-options"]) == ("nosniff", "DENY")
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert "cdn.jsdelivr.net" in client.get("/docs").headers["content-security-policy"]
'''

NOTES_V4_TESTS_TEST_MIGRATIONS_PY = r'''
%%writefile ../projects/notes_api/tests/test_migrations.py
"""The Alembic migrations run up and down on SQLite, and 0002 copies the tag data."""

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

PROJECT_DIR = Path(__file__).resolve().parent.parent


def alembic_config(database_file: Path) -> Config:
    """alembic.ini with the URL of a test database."""
    config = Config(PROJECT_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_file}")
    config.attributes["configure_logger"] = False
    return config


def test_upgrade_downgrade_round_trip(tmp_path: Path) -> None:
    """head creates every table; base removes them again."""
    database_file = tmp_path / "migrations.db"
    config = alembic_config(database_file)
    command.upgrade(config, "head")
    engine = sa.create_engine(f"sqlite:///{database_file}")
    assert set(sa.inspect(engine).get_table_names()) == {
        "alembic_version",
        "notes",
        "tags",
        "note_tags",
        "users",
        "refresh_tokens",
        "api_keys",
    }
    command.downgrade(config, "base")
    assert sa.inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()


def test_data_migration_moves_tags_and_back(tmp_path: Path) -> None:
    """0002 turns 'shop,food' text into rows; downgrading writes the text back."""
    database_file = tmp_path / "data.db"
    config = alembic_config(database_file)
    command.upgrade(config, "0001")
    engine = sa.create_engine(f"sqlite:///{database_file}")
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO notes (title, tags) VALUES ('Tea', 'shop,food')"))
        connection.execute(sa.text("INSERT INTO notes (title, tags) VALUES ('Rice', 'shop')"))
    command.upgrade(config, "0002")
    with engine.connect() as connection:
        links = connection.execute(
            sa.text(
                "SELECT notes.title, tags.name FROM note_tags JOIN notes ON notes.id = note_id"
                " JOIN tags ON tags.id = tag_id ORDER BY notes.title, tags.name"
            )
        ).all()
    assert [tuple(row) for row in links] == [("Rice", "shop"), ("Tea", "food"), ("Tea", "shop")]
    command.downgrade(config, "0001")
    with engine.connect() as connection:
        rows = connection.execute(sa.text("SELECT title, tags FROM notes ORDER BY id")).all()
    assert [tuple(row) for row in rows] == [("Tea", "food,shop"), ("Rice", "shop")]
    engine.dispose()


def test_existing_notes_get_a_disabled_legacy_owner(tmp_path: Path) -> None:
    """0004 gives notes written before accounts existed to an owner that cannot log in."""
    database_file = tmp_path / "owners.db"
    config = alembic_config(database_file)
    command.upgrade(config, "0003")
    engine = sa.create_engine(f"sqlite:///{database_file}")
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO notes (title) VALUES ('Old note')"))
    command.upgrade(config, "head")
    with engine.connect() as connection:
        owner = connection.execute(
            sa.text(
                "SELECT users.email, users.is_active, users.password_hash FROM notes"
                " JOIN users ON users.id = notes.owner_id"
            )
        ).one()
    assert tuple(owner) == ("legacy-owner@notes.invalid", 0, None)
    engine.dispose()
'''

NOTES_V4_TESTS_TEST_REPOSITORY_PY = r'''
%%writefile ../projects/notes_api/tests/test_repository.py
"""SqlNoteRepository on a real (SQLite) database: sessions, loading, locking, savepoints."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from helpers import create_tables
from notes_api.core.config import Settings
from notes_api.db import create_engine_from_settings, make_session_factory
from notes_api.exceptions import VersionConflictError
from notes_api.models import Note, Tag
from notes_api.repositories import SqlNoteRepository, SqlUserRepository
from notes_api.schemas import NoteCreate

pytestmark = pytest.mark.anyio
NOW = datetime(2026, 11, 17, 9, 30, tzinfo=UTC)


@pytest.fixture
async def session_factory(settings: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A session factory on a fresh database."""
    await create_tables(settings)
    engine = create_engine_from_settings(settings)
    yield make_session_factory(engine)
    await engine.dispose()


async def add_note(factory: async_sessionmaker[AsyncSession], **fields: object) -> int:
    """Create and commit one note (owned by a user created on first use); return its id."""
    async with factory() as session, session.begin():
        users = SqlUserRepository(session)
        owner = await users.user_by_email("owner@example.com")
        owner = owner or await users.add_user("owner@example.com", None, "user")
        note = await SqlNoteRepository(session).add(
            NoteCreate(title="Tea", **fields), NOW, owner.id
        )
        return note.id


async def test_tag_rows_are_shared(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Two notes tagged 'shop' share one Tag row."""
    await add_note(session_factory, tags=["shop", "food"])
    await add_note(session_factory, tags=["shop"])
    async with session_factory() as session:
        assert await session.scalar(select(func.count(Tag.id))) == 2


async def test_lazy_loading_is_switched_off(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """lazy='raise': touching tags without eager loading fails loudly instead of an N+1."""
    note_id = await add_note(session_factory, tags=["shop"])
    async with session_factory() as session:
        plain = await session.get(Note, note_id)
        assert plain is not None
        with pytest.raises(InvalidRequestError, match="lazy='raise'"):
            _ = plain.tags
        loaded = await SqlNoteRepository(session).get(note_id)
        assert loaded is not None and loaded.tags == ["shop"]


async def test_timestamps_come_back_in_utc(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """UTCDateTime attaches UTC to SQLite's naive values."""
    note_id = await add_note(session_factory)
    async with session_factory() as session:
        note = await SqlNoteRepository(session).get(note_id)
        assert note is not None and note.created_at == NOW and note.created_at.tzinfo is UTC


async def test_concurrent_update_raises_version_conflict(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Two sessions read version 1; the second UPDATE matches no row → VersionConflictError."""
    note_id = await add_note(session_factory)
    async with session_factory() as first, session_factory() as second:
        first_note = await SqlNoteRepository(first).get(note_id)
        second_note = await SqlNoteRepository(second).get(note_id)
        assert first_note is not None and second_note is not None
        await SqlNoteRepository(first).update(first_note, {"title": "First"}, NOW)
        await first.commit()
        with pytest.raises(VersionConflictError):
            await SqlNoteRepository(second).update(second_note, {"title": "Second"}, NOW)
    async with session_factory() as session:
        stored = await session.get(Note, note_id)
        assert stored is not None and (stored.title, stored.version) == ("First", 2)


async def test_delete_all_counts_rows(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Bulk DELETE removes notes, their links (cascade) and tags."""
    await add_note(session_factory, tags=["a"])
    await add_note(session_factory, tags=["b"])
    async with session_factory() as session, session.begin():
        assert await SqlNoteRepository(session).delete_all() == 2
    async with session_factory() as session:
        assert await session.scalar(select(func.count(Tag.id))) == 0
'''

NOTES_V4_TESTS_TEST_POSTGRES_PY = r'''
%%writefile ../projects/notes_api/tests/test_postgres.py
"""The same app on PostgreSQL in Docker: migrations, drift check, trigram search, races.

Skipped when Docker is not available. Run only these: `uv run pytest -m postgres`; skip them:
`uv run pytest -m "not postgres"`.
"""

import asyncio
import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import fakeredis
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from helpers import USER_EMAIL, auth_headers
from notes_api.core.config import Settings
from notes_api.dependencies import get_redis
from notes_api.main import create_app
from notes_api.repositories import SqlNoteRepository, SqlUserRepository
from notes_api.schemas import NoteCreate

pytestmark = pytest.mark.postgres
PROJECT_DIR = Path(__file__).resolve().parent.parent
POSTGRES_IMAGE = "postgres:18-alpine"


def docker_available() -> bool:
    """True if a Docker daemon answers."""
    try:
        import docker

        docker.from_env().ping()
    except Exception:
        return False
    return True


def alembic_config(url: str) -> Config:
    """alembic.ini pointed at the container."""
    config = Config(PROJECT_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="module")
def postgres_url() -> Iterator[str]:
    """Start PostgreSQL once for this module, migrate it to head, remove it afterwards."""
    if not docker_available():
        pytest.skip("Docker is not available")
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as container:
        url = container.get_connection_url()
        command.upgrade(alembic_config(url), "head")
        yield url


@pytest.fixture
def empty_url(postgres_url: str) -> str:
    """The database with every row removed and ids restarted."""

    async def truncate() -> None:
        """TRUNCATE all tables."""
        engine = create_async_engine(postgres_url)
        async with engine.begin() as connection:
            await connection.execute(
                sa.text("TRUNCATE notes, tags, users RESTART IDENTITY CASCADE")
            )
        await engine.dispose()

    asyncio.run(truncate())
    return postgres_url


def test_models_match_the_migrations(postgres_url: str) -> None:
    """alembic check: autogenerate finds no difference between the models and the schema."""
    command.check(alembic_config(postgres_url))


def test_api_round_trip_on_postgres(empty_url: str) -> None:
    """Create, search (ILIKE), feed, PATCH with versions and the 409, on the real database."""
    settings = Settings(
        _env_file=None,
        environment="test",
        jwt_secret=SecretStr(secrets.token_urlsafe(32)),
        password_time_cost=1,
        password_memory_kib=64,
        database_url=SecretStr(empty_url),
    )
    app = create_app(settings)
    app.dependency_overrides[get_redis] = lambda: fakeredis.FakeAsyncRedis(decode_responses=True)
    with TestClient(app) as client:
        client.headers.update(auth_headers(client, USER_EMAIL))
        for title in ("Buy Tea", "Steep the tea", "Call Ravi"):
            assert (
                client.post("/api/v1/notes", json={"title": title, "tags": ["x"]}).status_code
                == 201
            )
        found = client.get("/api/v1/notes", params={"q": "TEA", "sort": "title"}).json()
        assert [note["title"] for note in found["items"]] == ["Buy Tea", "Steep the tea"]
        feed = client.get("/api/v1/notes/feed", params={"limit": 2}).json()
        assert [note["id"] for note in feed["items"]] == [3, 2] and feed["next_cursor"]
        assert (
            client.patch("/api/v1/notes/1", json={"pinned": True, "version": 1}).json()["version"]
            == 2
        )
        assert (
            client.patch("/api/v1/notes/1", json={"pinned": False, "version": 1}).status_code == 409
        )
        assert client.get("/health/ready").json()["database"] == "ok"


def test_trigram_index_serves_substring_search(empty_url: str) -> None:
    """EXPLAIN shows ILIKE '%tea%' using the GIN trigram index (sequential scans off)."""

    async def plan() -> str:
        """The query plan of a title search."""
        async_engine = create_async_engine(empty_url)
        async with async_engine.begin() as connection:
            await connection.execute(sa.text("SET LOCAL enable_seqscan = off"))
            rows = await connection.execute(
                sa.text("EXPLAIN SELECT id FROM notes WHERE title ILIKE '%tea%'")
            )
            text = "\n".join(row[0] for row in rows)
        await async_engine.dispose()
        return text

    assert "ix_notes_title_trgm" in asyncio.run(plan())


def test_concurrent_new_tag_is_absorbed_by_the_savepoint(empty_url: str) -> None:
    """Two transactions add one new tag; a SAVEPOINT absorbs the loser's unique violation."""
    now = datetime(2026, 11, 17, tzinfo=UTC)

    async def race() -> list[list[str]]:
        """Run the two transactions concurrently and report each note's tags."""
        engine = create_async_engine(empty_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        first_flushed = asyncio.Event()
        async with factory() as session, session.begin():
            owner = await SqlUserRepository(session).add_user("racer@example.com", None, "user")

        async def first() -> list[str]:
            """Insert the tag, hold the transaction open for a moment, then commit."""
            async with factory() as session, session.begin():
                note = await SqlNoteRepository(session).add(
                    NoteCreate(title="A", tags=["race"]), now, owner.id
                )
                first_flushed.set()
                await asyncio.sleep(0.3)  # the second transaction blocks on the unique index
                return list(note.tags)

        async def second(session_factory: async_sessionmaker[AsyncSession]) -> list[str]:
            """Insert the same tag while the first transaction still holds it."""
            await first_flushed.wait()
            async with session_factory() as session, session.begin():
                note = await SqlNoteRepository(session).add(
                    NoteCreate(title="B", tags=["race"]), now, owner.id
                )
                return list(note.tags)

        results = await asyncio.gather(first(), second(factory))
        async with engine.connect() as connection:
            tag_count = await connection.scalar(sa.text("SELECT count(*) FROM tags"))
        await engine.dispose()
        assert tag_count == 1
        return list(results)

    assert asyncio.run(race()) == [["race"], ["race"]]
'''
