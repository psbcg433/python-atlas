"""Command-line interface: ``python -m pyinspect {memory,scan,imports} ...``."""

import argparse
import importlib
import sys
from collections.abc import Callable, Sequence

import pyinspect

EXIT_OK, EXIT_FINDINGS, EXIT_USAGE = 0, 1, 2


def resolve_target(target: str) -> Callable[[], object]:
    """``package.module:function`` (or ``module:Class.method``) -> the callable."""
    module_name, separator, attribute_path = target.partition(":")
    if not separator or not module_name or not attribute_path:
        raise ValueError(f"target must look like module:function, got {target!r}")
    resolved: object = importlib.import_module(module_name)
    for attribute in attribute_path.split("."):
        resolved = getattr(resolved, attribute)
    if not callable(resolved):
        raise TypeError(f"{target} is not callable")
    return resolved


def build_parser() -> argparse.ArgumentParser:
    """The argument parser with one subcommand per tool."""
    parser = argparse.ArgumentParser(prog="pyinspect", description="CPython internals toolkit")
    parser.add_argument("--version", action="version", version=f"pyinspect {pyinspect.__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    memory = commands.add_parser("memory", help="top allocating lines of a callable")
    memory.add_argument("target", help="module:function, called with no arguments")
    memory.add_argument("--top", type=int, default=5, help="lines to show (default 5)")

    scan = commands.add_parser("scan", help="AST-based code scanner")
    scan.add_argument("paths", nargs="+", help="files or folders")
    scan.add_argument("--json", action="store_true", help="print findings as JSON")

    imports = commands.add_parser("imports", help="import-time report for a module")
    imports.add_argument("module", help="module to import in a fresh interpreter")
    imports.add_argument("--top", type=int, default=5, help="modules to show (default 5)")
    return parser


def run_memory(target: str, top: int) -> int:
    """The memory subcommand."""
    report = pyinspect.profile_allocations(resolve_target(target), top=top)
    print(pyinspect.format_memory_report(report))
    return EXIT_OK


def run_scan(paths: list[str], as_json: bool) -> int:
    """The scan subcommand: exit status 1 when anything was found."""
    findings = pyinspect.scan_paths(paths)
    print(pyinspect.format_findings(findings, as_json=as_json))
    return EXIT_FINDINGS if findings else EXIT_OK


def run_imports(module_name: str, top: int) -> int:
    """The imports subcommand."""
    timings = pyinspect.measure_import(module_name)
    print(pyinspect.format_import_report(module_name, timings, top=top))
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, run one subcommand, return the exit status."""
    arguments = build_parser().parse_args(argv)
    try:
        match arguments.command:
            case "memory":
                return run_memory(arguments.target, arguments.top)
            case "scan":
                return run_scan(arguments.paths, arguments.json)
            case "imports":
                return run_imports(arguments.module, arguments.top)
    except (ValueError, TypeError, LookupError, AttributeError, OSError, RuntimeError) as error:
        print(f"pyinspect: error: {error}", file=sys.stderr)
        return EXIT_USAGE
    return EXIT_USAGE  # unreachable: argparse requires a command
