"""Analyze web-server access logs, plain text or gzip, and export them to CSV, JSON or SQLite.

Library use::

    from pathlib import Path
    from log_analyzer import analyze_access_log, render_report

    summary, malformed = analyze_access_log(Path("access.log.gz"))
    print(render_report(summary, malformed))

Command-line use: ``log-analyzer --help``.
"""

import logging
from importlib.metadata import PackageNotFoundError, version

from log_analyzer.analysis import (
    aggregate,
    analyze_access_log,
    normalize_endpoint,
    percentile,
    status_class,
    top_endpoints,
)
from log_analyzer.export import EXPORT_FORMATS, export_log, write_csv, write_json, write_sqlite
from log_analyzer.generate import write_synthetic_log
from log_analyzer.models import (
    AccessRecord,
    AccessSummary,
    LogAnalyzerError,
    LogFileError,
    MalformedLineError,
    UnsupportedFormatError,
)
from log_analyzer.parsing import (
    format_access_line,
    open_log,
    parse_access_line,
    parse_records,
    read_lines,
)
from log_analyzer.report import render_report, summary_document

DIST_NAME = "log-analyzer-psbcg433"

try:
    __version__ = version(DIST_NAME)
except PackageNotFoundError:  # pragma: no cover - only when run from an uninstalled checkout
    __version__ = "0.0.0+unknown"

# A library never configures logging; this keeps it silent until the application does.
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "DIST_NAME",
    "EXPORT_FORMATS",
    "AccessRecord",
    "AccessSummary",
    "LogAnalyzerError",
    "LogFileError",
    "MalformedLineError",
    "UnsupportedFormatError",
    "__version__",
    "aggregate",
    "analyze_access_log",
    "export_log",
    "format_access_line",
    "normalize_endpoint",
    "open_log",
    "parse_access_line",
    "parse_records",
    "percentile",
    "read_lines",
    "render_report",
    "status_class",
    "summary_document",
    "top_endpoints",
    "write_csv",
    "write_json",
    "write_sqlite",
    "write_synthetic_log",
]
