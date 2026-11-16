"""Make the project's top-level modules importable and switch the simulated network off."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def no_network_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """The store API stub sleeps SALES_NETWORK_DELAY seconds per call; tests use 0."""
    monkeypatch.setenv("SALES_NETWORK_DELAY", "0")
