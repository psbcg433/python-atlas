"""Contract tests: Schemathesis fuzzes the documented notes operations; the OpenAPI is snapshotted.

Schemathesis generates requests from the OpenAPI schema (valid and invalid ones) and checks
every response: no 5xx, documented status codes and content types, bodies matching the
response schemas. The snapshot test fails whenever the public API changes, so a change is
always deliberate: review the diff, then record it with UPDATE_SNAPSHOTS=1.
"""

import json
import os
from pathlib import Path

import pytest
import schemathesis
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import HealthCheck
from hypothesis import settings as hypothesis_settings

SNAPSHOT = Path(__file__).parent / "snapshots" / "openapi.json"


@pytest.fixture
def api_schema(app: FastAPI) -> schemathesis.BaseSchema:
    """The app's own OpenAPI document (the filter is applied to the lazy schema below)."""
    return schemathesis.openapi.from_dict(app.openapi())


schema = schemathesis.pytest.from_fixture("api_schema").include(path_regex=r"^/api/v1/notes")


@schema.parametrize()
@hypothesis_settings(
    max_examples=12,
    deadline=None,
    derandomize=True,  # the same examples on every run (and in CI)
    suppress_health_check=list(HealthCheck),
)
def test_notes_operations_honour_the_schema(case: schemathesis.Case, client: TestClient) -> None:
    """Call the app through the logged-in client; validate status, content type and body.

    Two checks are switched off, for reasons the schema cannot express:
    - ignored_auth (resend without credentials, expect 401): this client always sends
      credentials; test_security.py covers authentication.
    - positive_data_acceptance (schema-valid requests must succeed): opaque cursors, ids of
      notes that do not exist and version preconditions make valid requests fail legitimately.
    """
    kwargs = case.as_transport_kwargs(base_url=str(client.base_url), headers=dict(client.headers))
    if not kwargs.get("cookies"):
        kwargs.pop("cookies", None)  # per-request cookies are deprecated in the test client
    if isinstance(kwargs.get("data"), bytes | str):
        kwargs["content"] = kwargs.pop("data")  # httpx: raw bodies go in content=
    response = client.request(**kwargs)
    excluded = [schemathesis.checks.ignored_auth, schemathesis.checks.positive_data_acceptance]
    case.validate_response(response, excluded_checks=excluded)


def test_openapi_matches_the_snapshot(app: FastAPI) -> None:
    """The public contract changes only on purpose."""
    current = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    if os.environ.get("UPDATE_SNAPSHOTS"):
        SNAPSHOT.write_text(current, encoding="utf-8")
    assert SNAPSHOT.exists(), "no snapshot yet: run UPDATE_SNAPSHOTS=1 uv run pytest -k snapshot"
    recorded = SNAPSHOT.read_text(encoding="utf-8")
    assert recorded == current, (
        "the OpenAPI changed: review it, then re-run with UPDATE_SNAPSHOTS=1"
    )
