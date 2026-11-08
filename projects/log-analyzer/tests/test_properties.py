"""Property-based tests with Hypothesis: rules that hold for every input, not just examples."""

import csv
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from log_analyzer.analysis import aggregate, analyze_access_log, normalize_endpoint, percentile
from log_analyzer.export import RECORD_COLUMNS, record_row, write_csv, write_sqlite
from log_analyzer.generate import write_synthetic_log
from log_analyzer.models import AccessRecord, MalformedLineError
from log_analyzer.parsing import HTTP_METHODS, format_access_line, parse_access_line, parse_records

# isoformat() always writes a 4-digit year; strftime("%Y") gives "999" for year 999 on
# Python 3.12-3.13 (glibc), which Hypothesis found in the CI matrix.
timestamps = st.datetimes().map(lambda moment: moment.isoformat(timespec="seconds") + "Z")
ip_addresses = st.tuples(*[st.integers(0, 255)] * 4).map(lambda parts: ".".join(map(str, parts)))
paths = st.from_regex(r"/[A-Za-z0-9/._~?=&%-]{0,40}", fullmatch=True)
records = st.builds(
    AccessRecord,
    timestamp=timestamps,
    client_ip=ip_addresses,
    method=st.sampled_from(sorted(HTTP_METHODS)),
    path=paths,
    status=st.integers(100, 599),
    latency_ms=st.integers(0, 10**6),
)
latency_lists = st.lists(st.integers(0, 10**6), min_size=1)
log_lines = st.text(alphabet=st.characters(exclude_characters="\r\n\x0b\x0c\x1c\x1d\x1e\x85"))


@given(records)
def test_format_then_parse_round_trips(record: AccessRecord) -> None:
    assert parse_access_line(1, format_access_line(record)) == record


@given(log_lines)
def test_parser_only_ever_raises_malformed_line_error(line: str) -> None:
    try:
        parse_access_line(1, line)
    except MalformedLineError as error:
        assert error.reason in {"unrecognized format", "unknown method", "status out of range"}


@given(st.lists(st.one_of(records.map(format_access_line), log_lines), max_size=30))
def test_every_line_is_a_record_or_malformed(lines: list[str]) -> None:
    malformed: list[MalformedLineError] = []
    parsed = list(parse_records(enumerate(lines, start=1), malformed))
    assert len(parsed) + len(malformed) == len(lines)


@given(latency_lists, st.floats(0, 100))
def test_percentile_is_one_of_the_values_within_bounds(values: list[int], percent: float) -> None:
    result = percentile(values, percent)
    assert result in values
    assert min(values) <= result <= max(values)


@given(latency_lists, st.floats(0, 100), st.floats(0, 100))
def test_percentile_is_monotonic(values: list[int], first: float, second: float) -> None:
    low, high = sorted((first, second))
    assert percentile(values, low) <= percentile(values, high)


@given(latency_lists)
def test_percentile_100_is_the_maximum(values: list[int]) -> None:
    assert percentile(values, 100) == max(values)


@given(st.sampled_from(sorted(HTTP_METHODS)), paths)
def test_normalize_endpoint_is_idempotent(method: str, path: str) -> None:
    endpoint = normalize_endpoint(method, path)
    route = endpoint.split(" ", 1)[1]
    assert normalize_endpoint(method, route) == endpoint
    assert "?" not in route
    assert not any(segment.isdigit() for segment in route.split("/"))


@given(st.lists(records, max_size=20))
def test_aggregate_counts_add_up(batch: list[AccessRecord]) -> None:
    summary = aggregate(batch)
    assert summary.record_count == len(batch)
    assert summary.status_counts.total() == len(batch)
    assert summary.endpoint_counts.total() == len(batch)
    assert sorted(summary.all_latencies) == sorted(record.latency_ms for record in batch)


@given(st.lists(records, max_size=20))
def test_csv_round_trip(batch: list[AccessRecord]) -> None:
    with tempfile.TemporaryDirectory() as folder:
        output = Path(folder) / "records.csv"
        write_csv(batch, output)
        with output.open(encoding="utf-8", newline="") as csv_file:
            rows = [tuple(row.values()) for row in csv.DictReader(csv_file)]
    expected = [tuple(map(str, record_row(record))) for record in batch]
    assert rows == expected


@given(st.lists(records, max_size=20))
def test_sqlite_round_trip(batch: list[AccessRecord]) -> None:
    with tempfile.TemporaryDirectory() as folder:
        output = Path(folder) / "records.db"
        write_sqlite(batch, output)
        with closing(sqlite3.connect(output)) as connection:
            rows = connection.execute(
                f"SELECT {', '.join(RECORD_COLUMNS)} FROM records ORDER BY id"
            ).fetchall()
    assert rows == [record_row(record) for record in batch]


@pytest.mark.parametrize("suffix", [".log", ".log.gz"])
@given(seed=st.integers(0, 2**32), line_count=st.integers(0, 60))
def test_generated_logs_are_fully_accounted_for(suffix: str, seed: int, line_count: int) -> None:
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / f"access{suffix}"
        injected = write_synthetic_log(path, line_count, seed=seed, malformed_rate=0.2)
        summary, malformed = analyze_access_log(path)
    assert summary.record_count + len(malformed) == line_count
    assert len(malformed) == injected.total()
