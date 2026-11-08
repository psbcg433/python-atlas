"""CSV, JSON and SQLite export."""

import csv
import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from log_analyzer.export import (
    EXPORT_FORMATS,
    RECORD_COLUMNS,
    ExportFormat,
    export_log,
    infer_format,
    record_row,
    write_csv,
    write_json,
    write_sqlite,
)
from log_analyzer.models import AccessRecord, UnsupportedFormatError
from log_analyzer.parsing import parse_access_line
from tests.samples import GOOD_LINE

RECORD = parse_access_line(1, GOOD_LINE)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("out.csv", "csv"),
        ("out.JSON", "json"),
        ("out.db", "sqlite"),
        ("out.sqlite", "sqlite"),
        ("out.sqlite3", "sqlite"),
    ],
)
def test_infer_format(name: str, expected: str) -> None:
    assert infer_format(Path(name)) == expected


def test_infer_format_rejects_unknown_extension() -> None:
    with pytest.raises(UnsupportedFormatError, match=r"cannot infer .*'out\.txt'"):
        infer_format(Path("out.txt"))


def test_record_row_adds_the_endpoint() -> None:
    assert record_row(RECORD) == (
        "2026-11-06T09:00:00Z",
        "10.0.2.17",
        "GET",
        "/api/products/381",
        "GET /api/products/{id}",
        200,
        23,
    )


def test_write_csv(tmp_path: Path) -> None:
    output = tmp_path / "records.csv"
    tricky = RECORD._replace(path="/search?q=a,b")  # a comma forces CSV quoting
    assert write_csv([RECORD, tricky], output) == 2
    raw = output.read_bytes()
    assert raw.startswith(b"timestamp,client_ip,method,path,endpoint,status,latency_ms\r\n")
    assert b'"/search?q=a,b"' in raw
    with output.open(encoding="utf-8", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert rows[1]["path"] == "/search?q=a,b"
    assert rows[0]["status"] == "200"  # CSV has no types: everything comes back as str


def test_write_json(tmp_path: Path) -> None:
    output = tmp_path / "records.json"
    assert write_json([RECORD, RECORD], output) == 2
    loaded = json.loads(output.read_text(encoding="utf-8"))
    assert loaded == [dict(zip(RECORD_COLUMNS, record_row(RECORD), strict=True))] * 2
    assert output.read_text(encoding="utf-8").count("\n") == 4  # "[", 2 records, "]"


def test_write_json_empty(tmp_path: Path) -> None:
    output = tmp_path / "empty.json"
    assert write_json([], output) == 0
    assert output.read_text(encoding="utf-8") == "[]\n"


def test_write_sqlite_replaces_existing_file(tmp_path: Path) -> None:
    output = tmp_path / "records.db"
    output.write_text("not a database", encoding="utf-8")
    assert write_sqlite([RECORD, RECORD._replace(status=500)], output) == 2
    with closing(sqlite3.connect(output)) as connection:
        rows = connection.execute(
            "SELECT status, COUNT(*) FROM records GROUP BY status ORDER BY status"
        ).fetchall()
        malformed_count = connection.execute("SELECT COUNT(*) FROM malformed").fetchone()
    assert rows == [(200, 1), (500, 1)]
    assert malformed_count == (0,)


@pytest.mark.parametrize("export_format", EXPORT_FORMATS)
def test_export_log_counts(sample_log: Path, tmp_path: Path, export_format: ExportFormat) -> None:
    output = tmp_path / f"out.{export_format}"
    assert export_log(sample_log, output, export_format) == (2, 4)
    assert output.stat().st_size > 0


def test_export_sqlite_stores_malformed_lines(sample_log: Path, tmp_path: Path) -> None:
    output = tmp_path / "out.db"
    export_log(sample_log, output, "sqlite")
    with closing(sqlite3.connect(output)) as connection:
        malformed = connection.execute(
            "SELECT line_number, reason FROM malformed ORDER BY line_number"
        ).fetchall()
        endpoints = connection.execute("SELECT endpoint FROM records ORDER BY id").fetchall()
    assert malformed == [
        (2, "unrecognized format"),
        (3, "unrecognized format"),
        (5, "unknown method"),
        (6, "status out of range"),
    ]
    assert endpoints == [("GET /api/products/{id}",), ("POST /api/checkout",)]


def test_records_are_streamed(tmp_path: Path) -> None:
    """The writers accept a one-shot generator; they never need a list."""

    def one_shot() -> Iterator[AccessRecord]:
        yield from [RECORD] * 3

    assert write_csv(one_shot(), tmp_path / "s.csv") == 3
