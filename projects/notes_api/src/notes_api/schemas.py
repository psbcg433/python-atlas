"""Request and response schemas for the Notes API (Pydantic v2).

One schema per direction: NoteCreate (POST/PUT body), NoteUpdate (PATCH body, every field
optional), NoteRead (responses, with server-owned fields) and NoteFilters (query parameters).
Page envelopes live in pagination.py, error bodies in core/errors.py.
"""

import re
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    HttpUrl,
    StringConstraints,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic.json_schema import SkipJsonSchema

MAX_TAGS = 10
MAX_DB_INT = 2**31 - 1  # PostgreSQL INTEGER: larger ids, offsets or versions cannot exist


def require_slug(value: str) -> str:
    """Allow lowercase letters, digits and dashes (checked after stripping and lower-casing)."""
    if not re.fullmatch(r"[a-z0-9-]+", value):
        raise ValueError("tags use lowercase letters, digits and dashes")
    return value


def unique_in_order(tags: list[str]) -> list[str]:
    """Drop repeated tags, keeping the first occurrence."""
    return list(dict.fromkeys(tags))


def at_most(limit: int) -> Callable[[object], object]:
    """A before-validator: the raw string (before stripping) obeys the documented maxLength."""

    def check(value: object) -> object:
        """Reject over-long raw strings."""
        if isinstance(value, str) and len(value) > limit:
            raise ValueError(f"at most {limit} characters")
        return value

    return check


# The patterns put the rules into the OpenAPI schema (clients and Schemathesis see them):
# a title has a non-space character; a tag is letters, digits and dashes (stored lower-case).
Title = Annotated[
    str,
    BeforeValidator(at_most(200)),
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200, pattern=r"\S"),
]
Body = Annotated[str, Field(max_length=10_000)]
Tag = Annotated[
    str,
    StringConstraints(to_lower=True, min_length=1, max_length=30, pattern=r"^[A-Za-z0-9-]+$"),
    AfterValidator(require_slug),
]
Tags = Annotated[list[Tag], Field(max_length=MAX_TAGS)]
SortOrder = Literal["created_at", "-created_at", "updated_at", "-updated_at", "title", "-title"]


class NoteCreate(BaseModel):
    """Body of POST /notes and PUT /notes/{note_id}: every field a client may set."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,  # JSON types as documented: "pinned": 0 is not a boolean
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
        extra="forbid",
        strict=True,
        json_schema_extra={"examples": [{"pinned": True, "version": 1}]},
    )

    # Optional but not nullable: SkipJsonSchema keeps None out of the documented schema, which
    # must match what the validator below accepts (Schemathesis found the mismatch).
    title: Title | SkipJsonSchema[None] = None
    body: Body | SkipJsonSchema[None] = None
    tags: Tags | SkipJsonSchema[None] = None
    pinned: bool | SkipJsonSchema[None] = None
    version: Annotated[
        Annotated[int, Field(ge=1, le=MAX_DB_INT)] | SkipJsonSchema[None],
        Field(description="The version you read; a mismatch is a 409."),
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

    @computed_field  # type: ignore[prop-decorator]  # mypy does not model this pydantic idiom
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
    offset: Annotated[int, Field(ge=0, le=MAX_DB_INT)] = 0


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


class WebhookSettings(BaseModel):
    """Body of PUT /users/me/webhook."""

    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
