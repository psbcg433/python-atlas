"""Record types and exceptions shared by every module of the package."""

from collections import Counter
from typing import NamedTuple


class LogAnalyzerError(Exception):
    """Base class for every error the log analyzer raises on purpose."""


class LogFileError(LogAnalyzerError):
    """A log file that exists but cannot be read (for example a truncated gzip file)."""


class UnsupportedFormatError(LogAnalyzerError, ValueError):
    """An export format that the package does not know."""


class MalformedLineError(LogAnalyzerError, ValueError):
    """A log line that could not be parsed.

    Attributes:
        line_number: 1-based line number in the file.
        line: The raw line, without its newline.
        reason: Short machine-friendly reason: ``"unrecognized format"``,
            ``"unknown method"`` or ``"status out of range"``.
    """

    def __init__(self, line_number: int, line: str, reason: str) -> None:
        super().__init__(f"line {line_number}: {reason}")
        self.line_number = line_number
        self.line = line
        self.reason = reason


class AccessRecord(NamedTuple):
    """One parsed access-log line."""

    timestamp: str
    client_ip: str
    method: str
    path: str
    status: int
    latency_ms: int


class AccessSummary(NamedTuple):
    """Aggregated view of the parsed records (built in one pass by ``aggregate``)."""

    record_count: int
    status_counts: Counter[int]
    endpoint_counts: Counter[str]
    latencies_by_endpoint: dict[str, list[int]]
    all_latencies: list[int]
