"""Command-line interface: ``log-analyzer {generate,report,export,validate}``."""

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from log_analyzer import __version__
from log_analyzer.analysis import analyze_access_log
from log_analyzer.export import EXPORT_FORMATS, export_log, infer_format
from log_analyzer.generate import write_synthetic_log
from log_analyzer.logging_config import configure_logging
from log_analyzer.models import LogAnalyzerError, MalformedLineError
from log_analyzer.report import render_report, summary_document

logger = logging.getLogger(__name__)

PROG = "log-analyzer"
EXIT_OK = 0
EXIT_MALFORMED = 1
EXIT_ERROR = 2


def non_negative_int(text: str) -> int:
    """argparse type: an integer >= 0."""
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {value}")
    return value


def positive_int(text: str) -> int:
    """argparse type: an integer >= 1."""
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {value}")
    return value


def rate(text: str) -> float:
    """argparse type: a float between 0 and 1."""
    value = float(text)
    if not 0 <= value <= 1:
        raise argparse.ArgumentTypeError(f"must be between 0 and 1, got {value}")
    return value


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with one subparser per command."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Analyze web-server access logs (plain text or gzip).",
        epilog="Exit status: 0 success, 1 malformed lines found (validate), 2 error.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-v", "--verbose", action="count", default=0, help="log more on stderr (-v, -vv)"
    )
    verbosity.add_argument("-q", "--quiet", action="store_true", help="log only errors")
    parser.add_argument("--log-file", type=Path, help="also write DEBUG logs to this file")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    generate = commands.add_parser("generate", help="write a seeded synthetic access log")
    generate.add_argument("output", type=Path, help="file to write (a .gz name compresses)")
    generate.add_argument("-n", "--lines", type=non_negative_int, default=10_000)
    generate.add_argument("--seed", type=int, default=42)
    generate.add_argument("--malformed-rate", type=rate, default=0.02)

    report = commands.add_parser("report", help="print a summary report")
    report.add_argument("log", type=Path, help="access log, plain text or gzip")
    report.add_argument("--top", type=positive_int, default=5, help="endpoints to list")
    report.add_argument("--format", choices=("text", "json"), default="text")

    export = commands.add_parser("export", help="export parsed records to CSV, JSON or SQLite")
    export.add_argument("log", type=Path, help="access log, plain text or gzip")
    export.add_argument("output", type=Path, help="file to write (replaced if it exists)")
    export.add_argument(
        "-f",
        "--format",
        choices=EXPORT_FORMATS,
        help="default: from the output extension (.csv, .json, .db, .sqlite, .sqlite3)",
    )

    validate = commands.add_parser("validate", help="exit 1 if any line is malformed")
    validate.add_argument("log", type=Path, help="access log, plain text or gzip")
    validate.add_argument(
        "--show", type=non_negative_int, default=10, help="malformed lines to list"
    )
    return parser


def run_generate(args: argparse.Namespace) -> int:
    """``generate``: write a synthetic log."""
    injected = write_synthetic_log(
        args.output, args.lines, seed=args.seed, malformed_rate=args.malformed_rate
    )
    kinds = ", ".join(f"{kind} {count}" for kind, count in sorted(injected.items()))
    detail = f"{injected.total():,} malformed: {kinds}" if injected else "no malformed lines"
    print(f"wrote {args.lines:,} lines to {args.output} ({detail})")
    return EXIT_OK


def run_report(args: argparse.Namespace) -> int:
    """``report``: print the text or JSON report."""
    summary, malformed = analyze_access_log(args.log)
    if args.format == "json":
        print(json.dumps(summary_document(summary, malformed, top=args.top), indent=2))
    else:
        print(render_report(summary, malformed, top=args.top))
    return EXIT_OK


def run_export(args: argparse.Namespace) -> int:
    """``export``: write the records to a CSV, JSON or SQLite file."""
    export_format = args.format or infer_format(args.output)
    written, malformed_count = export_log(args.log, args.output, export_format)
    where = "stored in table 'malformed'" if export_format == "sqlite" else "skipped"
    print(
        f"exported {written:,} records to {args.output} ({export_format}); "
        f"{malformed_count:,} malformed lines {where}"
    )
    return EXIT_OK


def run_validate(args: argparse.Namespace) -> int:
    """``validate``: strict mode; list malformed lines and exit 1 if there are any."""
    exit_code = EXIT_OK
    try:
        summary, _ = analyze_access_log(args.log, strict=True)
    except* MalformedLineError as group:
        problems = [error for error in group.exceptions if isinstance(error, MalformedLineError)]
        print(f"{args.log}: FAILED, {len(problems):,} malformed lines")
        for error in problems[: args.show]:
            print(f"  line {error.line_number}: {error.reason}: {error.line[:50]!r}")
        if len(problems) > args.show:
            print(f"  ... and {len(problems) - args.show:,} more")
        exit_code = EXIT_MALFORMED
    else:
        print(f"{args.log}: OK, {summary.record_count:,} records, no malformed lines")
    return exit_code


def run_command(args: argparse.Namespace) -> int:
    """Dispatch to the handler of the chosen subcommand."""
    match args.command:
        case "generate":
            return run_generate(args)
        case "report":
            return run_report(args)
        case "export":
            return run_export(args)
        case "validate":
            return run_validate(args)
        case _:
            raise AssertionError(f"unhandled command {args.command!r}")


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point of the ``log-analyzer`` console script; returns the exit status."""
    args = build_parser().parse_args(argv)
    configure_logging(-1 if args.quiet else args.verbose, log_file=args.log_file)
    logger.debug("arguments: %s", vars(args))
    try:
        return run_command(args)
    except (LogAnalyzerError, OSError) as error:
        logger.debug("command failed", exc_info=True)
        print(f"{PROG}: error: {error}", file=sys.stderr)
        return EXIT_ERROR
