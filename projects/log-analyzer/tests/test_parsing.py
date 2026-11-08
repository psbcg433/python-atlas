"""Parsing one line, reading plain and gzip files, collecting malformed lines."""

import gzip
from pathlib import Path

import pytest

from log_analyzer.models import AccessRecord, LogAnalyzerError, LogFileError, MalformedLineError
from log_analyzer.parsing import (
    format_access_line,
    is_gzip_file,
    open_log,
    parse_access_line,
    parse_records,
    read_lines,
)
from tests.samples import GOOD_LINE, SAMPLE_LINES


def test_parse_good_line() -> None:
    assert parse_access_line(1, GOOD_LINE) == AccessRecord(
        "2026-11-06T09:00:00Z", "10.0.2.17", "GET", "/api/products/381", 200, 23
    )


@pytest.mark.parametrize(
    ("line", "reason"),
    [
        (SAMPLE_LINES[1], "unrecognized format"),
        (SAMPLE_LINES[2], "unrecognized format"),
        (SAMPLE_LINES[3], "unknown method"),
        (SAMPLE_LINES[4], "status out of range"),
        (GOOD_LINE.replace(" 200 ", " 000 "), "status out of range"),
        (GOOD_LINE + " trailing", "unrecognized format"),
    ],
)
def test_parse_rejects_with_reason(line: str, reason: str) -> None:
    with pytest.raises(MalformedLineError) as caught:
        parse_access_line(7, line)
    assert caught.value.reason == reason
    assert caught.value.line_number == 7
    assert caught.value.line == line
    assert str(caught.value) == f"line 7: {reason}"


def test_malformed_line_error_hierarchy() -> None:
    error = MalformedLineError(1, "x", "unrecognized format")
    assert isinstance(error, LogAnalyzerError)
    assert isinstance(error, ValueError)


def test_format_is_inverse_of_parse() -> None:
    assert format_access_line(parse_access_line(1, GOOD_LINE)) == GOOD_LINE


def test_read_lines_skips_blank_lines_and_keeps_numbers(sample_log: Path) -> None:
    numbered = list(read_lines(sample_log))
    assert [number for number, _ in numbered] == [1, 2, 3, 5, 6, 7]
    assert numbered[0] == (1, GOOD_LINE)


def test_read_lines_is_lazy(tmp_path: Path) -> None:
    lines = read_lines(tmp_path / "missing.log")  # nothing is opened yet
    with pytest.raises(FileNotFoundError):
        next(lines)


def test_gzip_is_detected_by_content_not_name(tmp_path: Path) -> None:
    disguised = tmp_path / "access.log"  # gzip data without a .gz suffix
    disguised.write_bytes(gzip.compress(f"{GOOD_LINE}\n".encode()))
    assert is_gzip_file(disguised)
    assert list(read_lines(disguised)) == [(1, GOOD_LINE)]


def test_plain_file_named_gz_is_read_as_text(tmp_path: Path) -> None:
    misnamed = tmp_path / "access.log.gz"
    misnamed.write_text(f"{GOOD_LINE}\n", encoding="utf-8")
    assert not is_gzip_file(misnamed)
    with open_log(misnamed) as log_file:
        assert log_file.read() == f"{GOOD_LINE}\n"


def test_invalid_utf8_becomes_a_malformed_line(tmp_path: Path) -> None:
    path = tmp_path / "binary.log"
    path.write_bytes(GOOD_LINE.encode() + b"\n\xff\xfe junk\n")
    malformed: list[MalformedLineError] = []
    records = list(parse_records(read_lines(path), malformed))
    assert len(records) == 1
    assert [error.line for error in malformed] == ["�� junk"]


def test_truncated_gzip_raises_log_file_error(tmp_path: Path) -> None:
    path = tmp_path / "cut.log.gz"
    path.write_bytes(gzip.compress((GOOD_LINE + "\n").encode() * 500)[:-20])
    with pytest.raises(LogFileError, match="truncated gzip"):
        list(read_lines(path))


def test_corrupt_gzip_raises_log_file_error(tmp_path: Path) -> None:
    data = bytearray(gzip.compress((GOOD_LINE + "\n").encode() * 50))
    data[20:30] = b"\x00" * 10  # damage the deflate stream
    path = tmp_path / "corrupt.log.gz"
    path.write_bytes(bytes(data))
    with pytest.raises(LogFileError, match="corrupt gzip"):
        list(read_lines(path))


def test_parse_records_collects_and_continues(sample_log: Path) -> None:
    malformed: list[MalformedLineError] = []
    records = list(parse_records(read_lines(sample_log), malformed))
    assert [record.status for record in records] == [200, 503]
    assert [error.line_number for error in malformed] == [2, 3, 5, 6]
