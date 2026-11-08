"""The seeded synthetic log generator."""

import gzip
import random
from collections import Counter
from pathlib import Path

import pytest

from log_analyzer.analysis import analyze_access_log
from log_analyzer.generate import break_line, write_synthetic_log
from tests.samples import GOOD_LINE

EXPECTED_REASON = {
    "truncated": "unrecognized format",
    "garbage": "unrecognized format",
    "unknown method": "unknown method",
    "status out of range": "status out of range",
}


def test_same_seed_same_bytes_even_gzip(tmp_path: Path) -> None:
    first, second, other = tmp_path / "a.log.gz", tmp_path / "b.log.gz", tmp_path / "c.log.gz"
    write_synthetic_log(first, 300, seed=42)
    write_synthetic_log(second, 300, seed=42)
    write_synthetic_log(other, 300, seed=7)
    assert first.read_bytes() == second.read_bytes()  # mtime=0, no file name in the header
    assert first.read_bytes() != other.read_bytes()


def test_gzip_and_plain_hold_the_same_text(tmp_path: Path) -> None:
    write_synthetic_log(tmp_path / "x.log", 100)
    write_synthetic_log(tmp_path / "x.log.gz", 100)
    assert (
        gzip.decompress((tmp_path / "x.log.gz").read_bytes()) == (tmp_path / "x.log").read_bytes()
    )


def test_every_line_is_accounted_for(generated_log: tuple[Path, Counter[str]]) -> None:
    log_path, injected = generated_log
    summary, malformed = analyze_access_log(log_path)
    assert summary.record_count + len(malformed) == 2_000
    expected: Counter[str] = Counter()
    for kind, count in injected.items():
        expected[EXPECTED_REASON[kind]] += count
    assert Counter(error.reason for error in malformed) == expected


def test_zero_rate_and_zero_lines(tmp_path: Path) -> None:
    assert write_synthetic_log(tmp_path / "clean.log", 50, malformed_rate=0) == Counter()
    assert write_synthetic_log(tmp_path / "empty.log", 0) == Counter()
    assert (tmp_path / "empty.log").read_text(encoding="utf-8") == ""


@pytest.mark.parametrize(
    ("line_count", "malformed_rate", "message"),
    [(-1, 0.02, "line_count"), (10, 1.5, "malformed_rate"), (10, -0.1, "malformed_rate")],
)
def test_invalid_arguments(
    tmp_path: Path, line_count: int, malformed_rate: float, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        write_synthetic_log(tmp_path / "x.log", line_count, malformed_rate=malformed_rate)


def test_break_line_kinds() -> None:
    rng = random.Random(0)
    assert len(break_line(rng, GOOD_LINE, "truncated")) < len(GOOD_LINE)
    assert '"FETCH ' in break_line(random.Random(1), GOOD_LINE, "unknown method") or (
        '"BREW ' in break_line(random.Random(1), GOOD_LINE, "unknown method")
    )
    damaged_status = break_line(rng, GOOD_LINE, "status out of range")
    assert '" 000 ' in damaged_status or '" 999 ' in damaged_status
    with pytest.raises(ValueError, match="unknown kind"):
        break_line(rng, GOOD_LINE, "melted")
