"""Shared fixtures: a TestClient whose in-memory store starts empty for every test."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from notes_api.main import app, notes_store


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A TestClient for the app, on an empty store."""
    notes_store.clear()
    with TestClient(app) as test_client:
        yield test_client
