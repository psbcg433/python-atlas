"""Read access logs (plain text or gzip) lazily and parse each line into an ``AccessRecord``."""

import gzip
import logging
import re
import zlib
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import TextIO

from log_analyzer.models import AccessRecord, LogFileError, MalformedLineError

logger = logging.getLogger(__name__)

ACCESS_LINE_PATTERN = re.compile(
    r"(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)"
    r" (?P<client_ip>\d{1,3}(?:\.\d{1,3}){3})"
    r' "(?P<method>[A-Z]+) (?P<path>/\S*) HTTP/1\.1"'
    r" (?P<status>\d{3})"
    r" (?P<latency_ms>\d+)ms"
)
HTTP_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
GZIP_MAGIC = b"\x1f\x8b"


def format_access_line(record: AccessRecord) -> str:
    """Render a record as one log line (the inverse of ``parse_access_line``)."""
    return (
        f'{record.timestamp} {record.client_ip} "{record.method} {record.path} HTTP/1.1"'
        f" {record.status} {record.latency_ms}ms"
    )


def parse_access_line(line_number: int, line: str) -> AccessRecord:
    """Parse one line, or raise ``MalformedLineError`` with the reason."""
    found = ACCESS_LINE_PATTERN.fullmatch(line)
    if found is None:
        raise MalformedLineError(line_number, line, "unrecognized format")
    match (found["method"], int(found["status"])):
        case (method, _) if method not in HTTP_METHODS:
            raise MalformedLineError(line_number, line, "unknown method")
        case (_, status) if not 100 <= status <= 599:
            raise MalformedLineError(line_number, line, "status out of range")
        case (method, status):
            return AccessRecord(
                found["timestamp"],
                found["client_ip"],
                method,
                found["path"],
                status,
                int(found["latency_ms"]),
            )


def is_gzip_file(path: Path) -> bool:
    """True if the file starts with the gzip magic bytes (the extension is not trusted)."""
    with path.open("rb") as raw_file:
        return raw_file.read(len(GZIP_MAGIC)) == GZIP_MAGIC


def open_log(path: Path) -> TextIO:
    """Open a log for reading as text, decompressing gzip transparently.

    Bytes that are not valid UTF-8 become U+FFFD instead of raising, so one bad byte turns
    one line into a malformed line rather than stopping the whole run.
    """
    if is_gzip_file(path):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open(encoding="utf-8", errors="replace")


def read_lines(path: Path) -> Iterator[tuple[int, str]]:
    """Yield ``(line_number, line)`` for each non-blank line, without the newline.

    Raises:
        LogFileError: The file is gzip-compressed but truncated or corrupt.
    """
    logger.debug("reading %s (%s)", path, "gzip" if is_gzip_file(path) else "plain text")
    try:
        with open_log(path) as log_file:
            for line_number, raw_line in enumerate(log_file, start=1):
                line = raw_line.rstrip("\n")
                if line.strip():
                    yield line_number, line
    except EOFError as error:
        raise LogFileError(f"{path}: compressed file ended early (truncated gzip)") from error
    except (gzip.BadGzipFile, zlib.error) as error:
        raise LogFileError(f"{path}: corrupt gzip data ({error})") from error


def parse_records(
    numbered_lines: Iterable[tuple[int, str]], malformed: list[MalformedLineError]
) -> Iterator[AccessRecord]:
    """Yield parsed records; append every malformed line to ``malformed`` and keep going."""
    for line_number, line in numbered_lines:
        try:
            record = parse_access_line(line_number, line)
        except MalformedLineError as error:
            logger.debug("skipping %s", error)
            malformed.append(error)
        else:
            yield record
