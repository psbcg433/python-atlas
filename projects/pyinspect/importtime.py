"""Import-time report: run ``python -X importtime`` in a child and summarize it."""

import os
import re
import subprocess
import sys
from dataclasses import dataclass

_MODULE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*")


class ImportReportError(RuntimeError):
    """The module could not be imported in the child interpreter."""


@dataclass(frozen=True, slots=True)
class ImportTiming:
    """One line of ``-X importtime`` output."""

    module: str
    self_us: int
    cumulative_us: int
    depth: int


def parse_importtime(stderr_text: str) -> list[ImportTiming]:
    """Parse ``-X importtime`` lines (other lines, and the header, are ignored).

    ``depth`` comes from the indentation: CPython indents nested imports by two spaces.
    """
    timings: list[ImportTiming] = []
    for line in stderr_text.splitlines():
        if not line.startswith("import time:"):
            continue
        fields = line.removeprefix("import time:").split("|")
        if len(fields) != 3 or not fields[0].strip().isdigit():
            continue
        name_field = fields[2].removeprefix(" ")
        depth = (len(name_field) - len(name_field.lstrip(" "))) // 2
        timings.append(ImportTiming(name_field.strip(), int(fields[0]), int(fields[1]), depth))
    return timings


def measure_import(module_name: str, *, python: str = sys.executable) -> list[ImportTiming]:
    """Import module_name in a fresh interpreter with ``-X importtime``; return the timings.

    The child gets the caller's ``sys.path`` (through ``PYTHONPATH``), so it can import
    whatever the caller can.
    """
    if not _MODULE_NAME.fullmatch(module_name):
        raise ValueError(f"not a module name: {module_name!r}")
    completed = subprocess.run(
        [python, "-X", "importtime", "-c", f"import {module_name}"],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHON_COLORS": "0",
            "PYTHONPATH": os.pathsep.join(entry for entry in sys.path if entry),
        },
        timeout=120,
    )
    if completed.returncode != 0:
        last_line = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else ""
        raise ImportReportError(f"cannot import {module_name}: {last_line}")
    return parse_importtime(completed.stderr)


def import_subtree(timings: list[ImportTiming], module_name: str) -> list[ImportTiming]:
    """The target's line plus the nested imports it triggered.

    ``-X importtime`` prints a module after its dependencies, indented deeper, so the subtree
    is the target line and the run of deeper lines just above it. Interpreter start-up imports
    (``site``, ``codecs``, ...) are not part of it. Returns [] if the module was already loaded.
    """
    for index in range(len(timings) - 1, -1, -1):
        if timings[index].module == module_name and timings[index].depth == 0:
            first = index
            while first > 0 and timings[first - 1].depth > 0:
                first -= 1
            return timings[first : index + 1]
    return []


def format_import_report(module_name: str, timings: list[ImportTiming], *, top: int = 10) -> str:
    """Cost of importing module_name and its slowest dependencies (start-up imports excluded)."""
    subtree = import_subtree(timings, module_name)
    if not subtree:
        return f"import report for {module_name}: already loaded at interpreter start-up"
    slowest = sorted(subtree, key=lambda timing: (-timing.self_us, timing.module))[:top]
    lines = [
        f"import report for {module_name}",
        f"  modules imported:   {len(subtree)}",
        f"  total (cumulative): {subtree[-1].cumulative_us / 1000:.1f} ms",
        f"  top {len(slowest)} by self time:",
    ]
    lines.extend(
        f"    {timing.self_us / 1000:7.2f} ms  {timing.module} (depth {timing.depth})"
        for timing in slowest
    )
    return "\n".join(lines)
