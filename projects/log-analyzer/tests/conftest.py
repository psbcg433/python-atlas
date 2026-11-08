"""Shared fixtures and the Hypothesis profiles."""

import logging
import os
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import pytest
from hypothesis import settings

from log_analyzer.generate import write_synthetic_log
from log_analyzer.logging_config import LOGGER_NAME
from tests.samples import SAMPLE_LINES

# "dev" (default): random examples, a fresh search every run.
# "ci": derandomized, so a CI run (and the course notebook) is reproducible.
settings.register_profile("dev", deadline=None)
settings.register_profile("ci", deadline=None, derandomize=True, print_blob=True)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


@pytest.fixture(autouse=True)
def reset_package_logger() -> Iterator[None]:
    """Undo any ``dictConfig`` a test applied, so later tests see the library default."""
    yield
    package_logger = logging.getLogger(LOGGER_NAME)
    for handler in package_logger.handlers[:]:
        package_logger.removeHandler(handler)
        handler.close()
    package_logger.addHandler(logging.NullHandler())
    package_logger.setLevel(logging.NOTSET)
    package_logger.propagate = True


@pytest.fixture
def sample_log(tmp_path: Path) -> Path:
    """A plain-text log with one line of each kind (2 good, 4 malformed) and a blank line."""
    path = tmp_path / "sample.log"
    path.write_text("\n".join([*SAMPLE_LINES[:3], "", *SAMPLE_LINES[3:]]) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def clean_log(tmp_path: Path) -> Path:
    """A synthetic log with no malformed lines."""
    path = tmp_path / "clean.log"
    write_synthetic_log(path, 200, seed=1, malformed_rate=0)
    return path


@pytest.fixture
def generated_log(tmp_path: Path) -> tuple[Path, Counter[str]]:
    """A 2 000-line gzip log (seed 42) and the damage the generator injected."""
    path = tmp_path / "access.log.gz"
    return path, write_synthetic_log(path, 2_000, seed=42)
