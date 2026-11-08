"""Export parsed records to CSV, JSON or SQLite, streaming (one record in memory at a time)."""

import csv
import json
import logging
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path
from typing import Literal, assert_never

from log_analyzer.analysis import normalize_endpoint
from log_analyzer.models import AccessRecord, MalformedLineError, UnsupportedFormatError
from log_analyzer.parsing import parse_records, read_lines

logger = logging.getLogger(__name__)

type ExportFormat = Literal["csv", "json", "sqlite"]
type RecordRow = tuple[str, str, str, str, str, int, int]

EXPORT_FORMATS: tuple[ExportFormat, ...] = ("csv", "json", "sqlite")
FORMAT_BY_SUFFIX: dict[str, ExportFormat] = {
    ".csv": "csv",
    ".json": "json",
    ".db": "sqlite",
    ".sqlite": "sqlite",
    ".sqlite3": "sqlite",
}
RECORD_COLUMNS = ("timestamp", "client_ip", "method", "path", "endpoint", "status", "latency_ms")
SQLITE_SCHEMA = """
CREATE TABLE records (
    id         INTEGER PRIMARY KEY,
    timestamp  TEXT    NOT NULL,
    client_ip  TEXT    NOT NULL,
    method     TEXT    NOT NULL,
    path       TEXT    NOT NULL,
    endpoint   TEXT    NOT NULL,
    status     INTEGER NOT NULL,
    latency_ms INTEGER NOT NULL
);
CREATE INDEX records_endpoint ON records (endpoint);
CREATE INDEX records_status ON records (status);
CREATE TABLE malformed (
    line_number INTEGER PRIMARY KEY,
    reason      TEXT NOT NULL,
    line        TEXT NOT NULL
);
"""


def infer_format(output: Path) -> ExportFormat:
    """Pick the export format from the output file's extension."""
    try:
        return FORMAT_BY_SUFFIX[output.suffix.lower()]
    except KeyError:
        known = ", ".join(FORMAT_BY_SUFFIX)
        raise UnsupportedFormatError(
            f"cannot infer the export format from {output.name!r}; "
            f"use --format or one of the extensions {known}"
        ) from None


def record_row(record: AccessRecord) -> RecordRow:
    """The record's fields in ``RECORD_COLUMNS`` order (adds the normalized endpoint)."""
    return (
        record.timestamp,
        record.client_ip,
        record.method,
        record.path,
        normalize_endpoint(record.method, record.path),
        record.status,
        record.latency_ms,
    )


def write_csv(records: Iterable[AccessRecord], output: Path) -> int:
    """Write a header and one row per record; return the number of records written."""
    written = 0
    with output.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(RECORD_COLUMNS)
        for record in records:
            writer.writerow(record_row(record))
            written += 1
    return written


def write_json(records: Iterable[AccessRecord], output: Path) -> int:
    """Write a JSON array of record objects, one per line; return the number written."""
    written = 0
    with output.open("w", encoding="utf-8") as json_file:
        json_file.write("[")
        for record in records:
            json_file.write(",\n  " if written else "\n  ")
            json.dump(dict(zip(RECORD_COLUMNS, record_row(record), strict=True)), json_file)
            written += 1
        json_file.write("\n]\n" if written else "]\n")
    return written


def write_sqlite(
    records: Iterable[AccessRecord],
    output: Path,
    malformed: list[MalformedLineError] | None = None,
) -> int:
    """Replace ``output`` with a database holding ``records`` (and ``malformed``) tables.

    ``malformed`` is read after every record has been inserted, so it can be the list that
    ``parse_records`` fills while ``records`` is consumed.
    """
    output.unlink(missing_ok=True)
    placeholders = ", ".join("?" * len(RECORD_COLUMNS))
    with closing(sqlite3.connect(output)) as connection, connection:
        connection.executescript(SQLITE_SCHEMA)
        connection.executemany(
            f"INSERT INTO records ({', '.join(RECORD_COLUMNS)}) VALUES ({placeholders})",
            (record_row(record) for record in records),
        )
        connection.executemany(
            "INSERT INTO malformed (line_number, reason, line) VALUES (?, ?, ?)",
            ((error.line_number, error.reason, error.line) for error in malformed or []),
        )
        (written,) = connection.execute("SELECT COUNT(*) FROM records").fetchone()
    return int(written)


def export_log(log_path: Path, output: Path, export_format: ExportFormat) -> tuple[int, int]:
    """Parse ``log_path`` and export its records; return ``(records written, malformed lines)``."""
    malformed: list[MalformedLineError] = []
    records = parse_records(read_lines(log_path), malformed)
    match export_format:
        case "csv":
            written = write_csv(records, output)
        case "json":
            written = write_json(records, output)
        case "sqlite":
            written = write_sqlite(records, output, malformed)
        case _:
            assert_never(export_format)
    logger.info(
        "exported %d records from %s to %s (%s)", written, log_path.name, output, export_format
    )
    return written, len(malformed)
