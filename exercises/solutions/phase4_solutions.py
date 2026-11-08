"""Reference solutions for Phase 4 labs.

Run from the repository root:

    uv run python exercises/solutions/phase4_solutions.py

The helpers are copied from the unit setup cells and each check_lab_4_N() runs the notebook's own
check cells, so the notebook and this file test exactly the same things. The checks build and run
throwaway projects under notebooks/_scratch/ (git-ignored), like the notebook.
"""

import annotationlib
import argparse
import base64
import contextlib
import csv
import dataclasses
import email.parser
import functools
import graphlib
import hashlib
import heapq
import hmac
import http.server
import importlib.util
import inspect
import io
import json
import linecache
import logging
import logging.config
import os
import random
import re
import shlex
import shutil
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import tomllib
import typing
import urllib.parse
import uuid
import wave
import xml.etree.ElementTree as ElementTree
import zipfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import IO, TYPE_CHECKING, Annotated, Literal, get_type_hints, overload
from unittest import mock
from zoneinfo import ZoneInfo

import httpx
import polars as pl
import pytest
import tenacity
import typer
from hypothesis import given
from hypothesis import strategies as st
from jinja2 import Environment, select_autoescape
from pydantic import AwareDatetime, BaseModel, Field, PositiveInt, ValidationError
from rich.console import Console
from rich.table import Table

type TestCase = tuple[str, Callable[[], object], object]


def run_checks(test_cases: list[TestCase]) -> None:
    """Run (label, thunk, expected) cases and print PASS/FAIL for each. Never raises."""
    passed_count = 0
    for label, thunk, expected in test_cases:
        try:
            actual = thunk()
        except Exception as error:  # a check must never stop the script
            print(f"FAIL  {label}: raised {type(error).__name__}: {error}")
            continue
        if actual == expected:
            passed_count += 1
            print(f"PASS  {label}")
        else:
            print(f"FAIL  {label}: expected {expected!r}, got {actual!r}")
    print(f"{passed_count}/{len(test_cases)} checks passed")


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from start (default: the working directory) to the folder holding pyproject.toml."""
    current = (start or Path.cwd()).resolve()
    for folder in (current, *current.parents):
        if (folder / "pyproject.toml").exists():
            return folder
    raise FileNotFoundError("pyproject.toml not found above the working directory")


# Lab 4.1 helpers (Unit 4.1 setup cell) --------------------------------------------------------

REPO_ROOT = find_repo_root()
scratch_dir = REPO_ROOT / "notebooks" / "_scratch"  # git-ignored
UNIT41_DIR = scratch_dir / "unit41"
WHEELHOUSE = UNIT41_DIR / "wheelhouse"
UNIT41_DIR.mkdir(parents=True, exist_ok=True)
VENV_BIN = Path(sys.executable).parent
COURSE_FILES = ("pyproject.toml", "uv.lock")


def file_digest(path: Path) -> str:
    """SHA-256 of a file's bytes, as hex."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


COURSE_DIGESTS_AT_START = {name: file_digest(REPO_ROOT / name) for name in COURSE_FILES}


def tool_env(**overrides: str) -> dict[str, str]:
    """Environment for child tools: plain output, scratch caches, nothing pointing at the course."""
    inherited = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("UV_", "PIP_", "VIRTUAL_ENV", "CONDA_", "PYTHONPATH"))
    }
    return {
        **inherited,
        "NO_COLOR": "1",
        "PYTHON_COLORS": "0",
        "UV_NO_PROGRESS": "1",
        "UV_PYTHON": "3.15",
        "UV_PYTHON_DOWNLOADS": "never",
        "UV_CACHE_DIR": str(UNIT41_DIR / "uv-cache"),
        "UV_TOOL_DIR": str(UNIT41_DIR / "uv-tools"),
        "UV_TOOL_BIN_DIR": str(UNIT41_DIR / "uv-tools-bin"),
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_COLOR": "1",
        "PIP_PROGRESS_BAR": "off",
        "PIP_CACHE_DIR": str(UNIT41_DIR / "pip-cache"),
        "GIT_CEILING_DIRECTORIES": str(scratch_dir),
        **overrides,
    }


TIMING = re.compile(r"\b(in|after) \d+(\.\d+)?(ms|s|µs)\b")
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def tidy(text: str) -> str:
    """Show absolute paths as <scratch>, <repo> or ~ and timings as <time>; drop colour codes."""
    for folder, label in ((UNIT41_DIR, "<scratch>"), (REPO_ROOT, "<repo>"), (Path.home(), "~")):
        text = text.replace(f"file://{folder}", label).replace(str(folder), label)
    return ANSI_ESCAPE.sub("", TIMING.sub(r"\1 <time>", text))


def executable(name: str) -> str | None:
    """A path as given, the kernel's python, a tool from the course venv, or one on PATH."""
    if "/" in name:
        return name if Path(name).exists() else None
    if name == "python":
        return sys.executable
    local_tool = VENV_BIN / name
    return str(local_tool) if local_tool.exists() else shutil.which(name)


def run_tool(
    *command: str, cwd: Path = UNIT41_DIR, env: dict[str, str] | None = None, timeout: int = 300
) -> tuple[int, str]:
    """Run a CLI tool in a child process; return (exit code, tidied stdout + stderr)."""
    found = executable(command[0])
    if found is None:
        return 127, f"SKIP: {command[0]} is not installed on this machine"
    completed = subprocess.run(
        [found, *command[1:]],
        cwd=cwd,
        env=env or tool_env(),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return completed.returncode, tidy((completed.stdout + completed.stderr).rstrip())


def shell(
    *command: str,
    cwd: Path = UNIT41_DIR,
    env: dict[str, str] | None = None,
    keep: str | None = None,
    max_lines: int | None = None,
) -> int:
    """Print `[folder]$ command` and the tool's real output (only lines matching keep, if given)."""
    exit_code, output = run_tool(*command, cwd=cwd, env=env)
    shown = [Path(command[0]).name if "/" in command[0] else command[0], *command[1:]]
    print(f"[{tidy(str(cwd))}]$ {tidy(shlex.join(shown))}")
    lines = output.splitlines()
    if keep is not None:
        lines = [line for line in lines if re.search(keep, line)]
    if max_lines is not None and len(lines) > max_lines:
        lines = [*lines[:max_lines], f"... ({len(lines) - max_lines} more lines)"]
    if lines:
        print(textwrap.indent("\n".join(lines), "  "))
    if exit_code:
        print(f"  (exit code {exit_code})")
    return exit_code


def fresh_dir(name: str) -> Path:
    """An empty folder <scratch>/<name>, recreated on every run."""
    folder = UNIT41_DIR / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    return folder


def write_files(root: Path, files: dict[str, str]) -> Path:
    """Write relative path -> text (dedented) under root; return root."""
    for relative_path, text in files.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(text).lstrip("\n"))
    return root


SKIPPED_PARTS = {".venv", "__pycache__", ".pytest_cache", ".mypy_cache"}


def show_tree(root: Path) -> None:
    """Print every file under root (skipping virtual environments and caches)."""
    print(f"{tidy(str(root))}/")
    for path in sorted(root.rglob("*")):
        if path.is_file() and not SKIPPED_PARTS & set(path.relative_to(root).parts):
            print(f"  {path.relative_to(root).as_posix()}")


def show_file(path: Path, *, after: str | None = None) -> None:
    """Print a text file (optionally only from the first line containing after)."""
    text = path.read_text()
    if after is not None and after in text:
        text = text[text.index(after) :]
    print(f"--- {path.name} ---\n{tidy(text.rstrip())}")


@dataclass(frozen=True)
class DemoPackage:
    """A tiny package for the local wheelhouse (never published anywhere)."""

    name: str
    version: str
    source: str
    dependencies: tuple[str, ...] = ()
    extras: dict[str, list[str]] = field(default_factory=dict)
    scripts: dict[str, str] = field(default_factory=dict)

    @property
    def module(self) -> str:
        return self.name.replace("-", "_")

    def files(self) -> dict[str, str]:
        """pyproject.toml and src/<module>/__init__.py for this package."""
        lines = [
            "[project]",
            f'name = "{self.name}"',
            f'version = "{self.version}"',
            'description = "Course demo package (never published)"',
            'requires-python = ">=3.12"',
            'license = "MIT"',
            f"dependencies = {json.dumps(list(self.dependencies))}",
        ]
        if self.extras:
            lines += ["", "[project.optional-dependencies]"]
            lines += [f"{extra} = {json.dumps(reqs)}" for extra, reqs in self.extras.items()]
        if self.scripts:
            lines += ["", "[project.scripts]"]
            lines += [f'{command} = "{target}"' for command, target in self.scripts.items()]
        lines += ["", "[build-system]", 'requires = ["uv_build>=0.13,<0.14"]']
        lines += ['build-backend = "uv_build"']
        return {
            "pyproject.toml": "\n".join(lines) + "\n",
            f"src/{self.module}/__init__.py": textwrap.dedent(self.source).lstrip("\n"),
        }

    def wheel_name(self) -> str:
        return f"{self.module}-{self.version}-py3-none-any.whl"


RUPEE_V1 = """
    def fmt(amount: float) -> str:
        return f"INR {amount:,.2f}"
"""
RUPEE_V2 = """
    def fmt(amount: float, symbol: str = "\u20b9") -> str:
        return f"{symbol}{amount:,.2f}"
"""
GST_SOURCE = """
    import sys

    from rupee_fmt import fmt


    def with_gst(amount: float, rate: float = 0.18) -> float:
        return round(amount * (1 + rate), 2)


    def main() -> None:
        print(fmt(with_gst(float(sys.argv[1]))))
"""
WHEELHOUSE_PACKAGES = [
    *(DemoPackage("rupee-fmt", version, RUPEE_V1) for version in ("1.0.0", "1.1.0", "1.2.0")),
    *(DemoPackage("rupee-fmt", version, RUPEE_V2) for version in ("2.0.0", "2.1.0rc1")),
    DemoPackage(
        "table-print", "0.1.0", "def table(rows):\n    return '\\n'.join(map(str, rows))\n"
    ),
    DemoPackage("win-colors", "1.0.0", "RED = '\\x1b[31m'\n"),
    DemoPackage(
        "gst-calc",
        "1.0.0",
        GST_SOURCE,
        dependencies=("rupee-fmt>=1.0,<2", "win-colors>=1.0; sys_platform == 'win32'"),
        extras={"report": ["table-print>=0.1"]},
        scripts={"gst": "gst_calc:main"},
    ),
    DemoPackage(
        "gst-calc",
        "2.0.0",
        GST_SOURCE,
        dependencies=("rupee-fmt>=2",),
        extras={"report": ["table-print>=0.1"]},
        scripts={"gst": "gst_calc:main"},
    ),
    DemoPackage("legacy-invoice", "1.0.0", "TEMPLATE = 'plain'\n", dependencies=("rupee-fmt<1.1",)),
]


def publish_to_wheelhouse(package: DemoPackage) -> None:
    """Build one demo package (sdist + wheel) into the local wheelhouse with `uv build`."""
    source_root = write_files(
        fresh_dir(f"sources/{package.name}-{package.version}"), package.files()
    )
    exit_code, output = run_tool(
        "uv", "build", "--offline", "--out-dir", str(WHEELHOUSE), cwd=source_root
    )
    if exit_code:
        raise RuntimeError(f"uv build failed for {package.name} {package.version}:\n{output}")


def remove_from_wheelhouse(name: str, version: str) -> None:
    """Delete one release (wheel and sdist) from the local wheelhouse."""
    for path in WHEELHOUSE.glob(f"{name.replace('-', '_')}-{version}[-.]*"):
        path.unlink()


def build_wheelhouse() -> Path:
    """Build every demo package that is missing from the wheelhouse; return its folder."""
    WHEELHOUSE.mkdir(parents=True, exist_ok=True)
    for package in WHEELHOUSE_PACKAGES:
        if not (WHEELHOUSE / package.wheel_name()).exists():
            publish_to_wheelhouse(package)
    return WHEELHOUSE


def network_available(host: str = "pypi.org", port: int = 443, timeout: float = 3.0) -> bool:
    """Can we open a TCP connection to host? (Only two cells in this unit need the network.)"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"


# Lab 4.1 solutions ----------------------------------------------------------------------------

PLAIN_PYPROJECT = """
[build-system]
requires = ["uv_build>=0.13,<0.14"]
build-backend = "uv_build"

[project]
name = "shipping-rates"
version = "0.3.0"
requires-python = ">=3.12"
dependencies = ["rupee-fmt~=1.1", "win-colors; sys_platform == 'win32'"]

[project.optional-dependencies]
report = ["table-print>=0.1"]

[project.scripts]
ship-quote = "shipping_rates.cli:main"

[dependency-groups]
dev = ["gst-calc>=1,<2"]

[tool.ruff]
line-length = 100
"""


def annotated_pyproject() -> str:
    """PLAIN_PYPROJECT with a comment for every non-blank line."""
    return """
    # How build frontends (pip, uv) turn this source tree into a wheel (PEP 518)
    [build-system]
    requires = ["uv_build>=0.13,<0.14"]  # packages installed into the isolated build environment
    build-backend = "uv_build"  # the module whose PEP 517 hooks build the wheel

    # The package metadata standardised by PEP 621
    [project]
    name = "shipping-rates"  # the distribution name used on PyPI and by installers
    version = "0.3.0"  # PEP 440 version of this release
    requires-python = ">=3.12"  # resolvers skip this release on older Pythons
    # runtime requirements; the second only applies on Windows
    dependencies = ["rupee-fmt~=1.1", "win-colors; sys_platform == 'win32'"]

    # Extras: optional feature sets installed with shipping-rates[report]
    [project.optional-dependencies]
    report = ["table-print>=0.1"]  # what the report extra adds

    # Console scripts generated by the installer
    [project.scripts]
    ship-quote = "shipping_rates.cli:main"  # command name mapped to module:function

    # Local-only dependency groups (PEP 735), never published
    [dependency-groups]
    dev = ["gst-calc>=1,<2"]  # tools needed while developing this project

    # Settings for the ruff linter and formatter
    [tool.ruff]
    line-length = 100  # maximum line length ruff allows
    """


def library_files() -> dict[str, str]:
    """Relative path -> file content for the invoice-tools project."""
    return {
        "pyproject.toml": """
            [build-system]
            requires = ["uv_build>=0.13,<0.14"]
            build-backend = "uv_build"

            [project]
            name = "invoice-tools"
            version = "0.1.0"
            requires-python = ">=3.12"
            dependencies = []

            [project.optional-dependencies]
            report = ["table-print>=0.1"]

            [project.scripts]
            invoice-total = "invoice_tools.cli:main"

            [dependency-groups]
            dev = ["rupee-fmt>=1"]
        """,
        "src/invoice_tools/__init__.py": """
            from importlib.metadata import version

            __version__ = version("invoice-tools")
        """,
        "src/invoice_tools/cli.py": """
            import sys
            from decimal import Decimal


            def main() -> None:
                total = sum((Decimal(amount) for amount in sys.argv[1:]), Decimal(0))
                print(f"total: {total:.2f}")
        """,
        "src/invoice_tools/py.typed": "",
    }


def pep723_script() -> str:
    """Source of a self-describing script for `uv run`."""
    return """
        # /// script
        # requires-python = ">=3.12"
        # dependencies = ["rupee-fmt>=2"]
        # ///
        import importlib.metadata

        from rupee_fmt import fmt

        print(fmt(1234.5))
        print("rupee-fmt", importlib.metadata.version("rupee-fmt"))
    """


def wheel_summary(wheel_path: Path) -> dict[str, object]:
    """Facts about a wheel, read from its files."""
    with zipfile.ZipFile(wheel_path) as wheel:
        names = wheel.namelist()
        dist_info = next(name.split("/")[0] for name in names if ".dist-info/" in name)
        metadata = email.parser.Parser().parsestr(wheel.read(f"{dist_info}/METADATA").decode())
        wheel_file = email.parser.Parser().parsestr(wheel.read(f"{dist_info}/WHEEL").decode())
        console_scripts: dict[str, str] = {}
        if f"{dist_info}/entry_points.txt" in names:
            in_section = False
            for line in wheel.read(f"{dist_info}/entry_points.txt").decode().splitlines():
                if line.startswith("["):
                    in_section = line.strip() == "[console_scripts]"
                elif in_section and "=" in line:
                    command, target = (part.strip() for part in line.split("=", 1))
                    console_scripts[command] = target
        record_ok = True
        for line in wheel.read(f"{dist_info}/RECORD").decode().splitlines():
            path, digest, _size = line.rsplit(",", 2)
            if digest:
                algorithm, expected = digest.split("=", 1)
                actual = base64.urlsafe_b64encode(hashlib.new(algorithm, wheel.read(path)).digest())
                record_ok = record_ok and actual.rstrip(b"=").decode() == expected
    packages = sorted(
        {name.split("/")[0].removesuffix(".py") for name in names if ".dist-info/" not in name}
    )
    return {
        "name": metadata["Name"],
        "version": metadata["Version"],
        "tags": wheel_file.get_all("Tag") or [],
        "packages": packages,
        "console_scripts": console_scripts,
        "requires_dist": metadata.get_all("Requires-Dist") or [],
        "record_ok": record_ok,
    }


def check_lab_4_1() -> None:
    """Run the notebook's Lab 4.1 check cells against the solutions above."""

    def annotation_problems(plain: str, annotated: str) -> list[str]:
        """Lines of plain that have no 3-word comment (inline or on the line above) in annotated."""
        problems: list[str] = []
        comment_above = False
        content_lines = [
            line.strip() for line in textwrap.dedent(plain).splitlines() if line.strip()
        ]
        seen = 0
        for line in textwrap.dedent(annotated).splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                comment_above = len(stripped.lstrip("# ").split()) >= 3
                continue
            if not stripped:
                comment_above = False
                continue
            content, _, inline = stripped.partition(" # ")
            if len(inline.split()) < 3 and not comment_above:
                problems.append(content.strip())
            seen += 1
            comment_above = False
        if seen != len(content_lines):
            problems.append(f"expected {len(content_lines)} TOML lines, found {seen}")
        return problems

    run_checks(
        [
            (
                "parses to the same data",
                lambda: (
                    tomllib.loads(textwrap.dedent(annotated_pyproject()))
                    == tomllib.loads(textwrap.dedent(PLAIN_PYPROJECT))
                ),
                True,
            ),
            (
                "every line annotated",
                lambda: annotation_problems(PLAIN_PYPROJECT, annotated_pyproject()),
                [],
            ),
            (
                "still a build-system table",
                lambda: tomllib.loads(textwrap.dedent(annotated_pyproject()))["build-system"][
                    "build-backend"
                ],
                "uv_build",
            ),
        ]
    )

    LAB_DIR = UNIT41_DIR / "lab"

    _learner_builds: dict[str, tuple[Path, dict[str, str]]] = {}

    def build_learner_library() -> tuple[Path, dict[str, str]]:
        """Build library_files() with uv (once per distinct content); return (wheel, file texts)."""
        key = json.dumps(library_files(), sort_keys=True)
        if key not in _learner_builds:
            _learner_builds[key] = _build_library()
        return _learner_builds[key]

    def _build_library() -> tuple[Path, dict[str, str]]:
        """Write library_files() under lab/, build with uv, read METADATA and entry points."""
        root = write_files(fresh_dir("lab/invoice-tools"), library_files())
        exit_code, output = run_tool("uv", "build", "--offline", cwd=root)
        if exit_code:
            raise RuntimeError(output.splitlines()[-1])
        wheel_path = next((root / "dist").glob("*.whl"))
        with zipfile.ZipFile(wheel_path) as wheel:
            names = wheel.namelist()
            dist_info = next(name.split("/")[0] for name in names if ".dist-info/" in name)
            report = {
                "names": "\n".join(names),
                "metadata": wheel.read(f"{dist_info}/METADATA").decode(),
                "entry_points": wheel.read(f"{dist_info}/entry_points.txt").decode(),
            }
        return wheel_path, report

    def run_learner_cli(*arguments: str) -> str:
        """Run invoice-total from the built wheel with uvx."""
        wheel_path, _ = build_learner_library()
        return run_tool(
            "uvx", "--quiet", "--offline", "--from", str(wheel_path), "invoice-total", *arguments
        )[1]

    def learner_version() -> str:
        wheel_path, _ = build_learner_library()
        return run_tool(
            "uv",
            "run",
            "--quiet",
            "--offline",
            "--no-project",
            "--with",
            str(wheel_path),
            "python",
            "-c",
            "import invoice_tools; print(invoice_tools.__version__)",
            cwd=LAB_DIR,
        )[1]

    run_checks(
        [
            (
                "src layout",
                lambda: sorted(p for p in library_files() if p.startswith("src/invoice_tools/")),
                [
                    "src/invoice_tools/__init__.py",
                    "src/invoice_tools/cli.py",
                    "src/invoice_tools/py.typed",
                ],
            ),
            (
                "nothing importable at the root",
                lambda: [p for p in library_files() if p.endswith(".py") and "/" not in p],
                [],
            ),
            (
                "console script in entry_points.txt",
                lambda: (
                    "invoice-total = invoice_tools.cli:main"
                    in build_learner_library()[1]["entry_points"]
                ),
                True,
            ),
            (
                "extra published",
                lambda: "Provides-Extra: report" in build_learner_library()[1]["metadata"],
                True,
            ),
            (
                "extra requirement",
                lambda: (
                    re.search(
                        r"Requires-Dist: table-print>=0\.1 ?; extra == .report.",
                        build_learner_library()[1]["metadata"],
                    )
                    is not None
                ),
                True,
            ),
            (
                "dev group not published",
                lambda: "rupee-fmt" in build_learner_library()[1]["metadata"],
                False,
            ),
            (
                "py.typed in the wheel",
                lambda: "invoice_tools/py.typed" in build_learner_library()[1]["names"],
                True,
            ),
            ("invoice-total 10 20.5", lambda: run_learner_cli("10", "20.5"), "total: 30.50"),
            ("__version__ from metadata", learner_version, "0.1.0"),
        ]
    )

    PEP723_BLOCK = re.compile(
        r"(?m)^# /// (?P<type>[a-zA-Z0-9-]+)$\s(?P<content>(^#(| .*)$\s)+)^# ///$"
    )

    def read_script_metadata(script: str) -> dict[str, object]:
        """Parse the `# /// script` block of a PEP 723 script."""
        script = textwrap.dedent(script)
        match = next((m for m in PEP723_BLOCK.finditer(script) if m["type"] == "script"), None)
        if match is None:
            raise ValueError("no `# /// script` block")
        toml_text = "".join(
            line[2:] if line.startswith("# ") else line[1:]
            for line in match["content"].splitlines(keepends=True)
        )
        return tomllib.loads(toml_text)

    def run_learner_script() -> list[str]:
        root = fresh_dir("lab/script")
        (root / "quote.py").write_text(textwrap.dedent(pep723_script()))
        output = run_tool(
            "uv",
            "run",
            "--quiet",
            "--offline",
            "--no-index",
            "--find-links",
            str(WHEELHOUSE),
            "quote.py",
            cwd=root,
        )[1]
        return output.splitlines()[-2:]

    run_checks(
        [
            (
                "requires-python",
                lambda: read_script_metadata(pep723_script())["requires-python"],
                ">=3.12",
            ),
            (
                "dependencies",
                lambda: [
                    d.replace(" ", "")
                    for d in read_script_metadata(pep723_script())["dependencies"]
                ],
                ["rupee-fmt>=2"],
            ),
            ("output", run_learner_script, ["\u20b91,234.50", "rupee-fmt 2.0.0"]),
        ]
    )

    GST_WHEEL = build_wheelhouse() / "gst_calc-1.0.0-py3-none-any.whl"

    def tampered_wheel() -> Path:
        """A copy of GST_WHEEL whose gst_calc/__init__.py was edited after building."""
        LAB_DIR.mkdir(parents=True, exist_ok=True)
        target = LAB_DIR / GST_WHEEL.name
        with zipfile.ZipFile(GST_WHEEL) as source, zipfile.ZipFile(target, "w") as copy:
            for item in source.infolist():
                data = source.read(item)
                if item.filename == "gst_calc/__init__.py":
                    data += b"\nprint('surprise')\n"
                copy.writestr(item, data)
        return target

    run_checks(
        [
            ("name", lambda: wheel_summary(GST_WHEEL)["name"], "gst-calc"),
            ("version", lambda: wheel_summary(GST_WHEEL)["version"], "1.0.0"),
            ("tags", lambda: wheel_summary(GST_WHEEL)["tags"], ["py3-none-any"]),
            ("packages", lambda: wheel_summary(GST_WHEEL)["packages"], ["gst_calc"]),
            (
                "console scripts",
                lambda: wheel_summary(GST_WHEEL)["console_scripts"],
                {"gst": "gst_calc:main"},
            ),
            ("three requirements", lambda: len(wheel_summary(GST_WHEEL)["requires_dist"]), 3),
            (
                "one extra requirement",
                lambda: sum("extra ==" in r for r in wheel_summary(GST_WHEEL)["requires_dist"]),
                1,
            ),
            ("RECORD verifies", lambda: wheel_summary(GST_WHEEL)["record_ok"], True),
            ("tampering detected", lambda: wheel_summary(tampered_wheel())["record_ok"], False),
        ]
    )


# Lab 4.2 helpers (Unit 4.2 setup cell) --------------------------------------------------------

UNIT42_DIR = scratch_dir / "unit42"
UNIT42_DIR.mkdir(parents=True, exist_ok=True)
CHECKER_ENV = {
    **os.environ,
    "NO_COLOR": "1",
    "FORCE_COLOR": "0",
    "MYPY_FORCE_COLOR": "0",
    "PYTHON_COLORS": "0",
}
PAISE = Decimal("0.01")


def write_demo(source: str, name: str, header: str = "") -> Path:
    """Write dedented source to <scratch>/<name>.py and return the path."""
    path = UNIT42_DIR / f"{name}.py"
    path.write_text(header + textwrap.dedent(source).lstrip("\n"))
    return path


def run_mypy(
    source: str, *, name: str = "demo", strict: bool = False, options: tuple[str, ...] = ()
) -> list[str]:
    """Type-check source with mypy in a child process; return its diagnostics, one per line."""
    mypy = VENV_BIN / "mypy"
    if not mypy.exists():
        return ["SKIP: mypy is not installed (uv add --dev mypy)"]
    path = write_demo(source, name)
    command = [
        str(mypy),
        "--no-error-summary",
        "--no-color-output",
        "--no-pretty",
        "--cache-dir",
        str(UNIT42_DIR / ".mypy_cache"),
        *(["--strict"] if strict else []),
        *options,
        path.name,
    ]
    completed = subprocess.run(
        command, cwd=UNIT42_DIR, capture_output=True, text=True, env=CHECKER_ENV, timeout=300
    )
    return (completed.stdout + completed.stderr).strip().splitlines()


def run_pyright(source: str, *, name: str = "demo", strict: bool = False) -> list[str]:
    """Type-check source with pyright (JSON output) in a child process; one line per finding."""
    pyright = VENV_BIN / "pyright"
    if not pyright.exists():
        return ["SKIP: pyright is not installed (uv add --dev pyright)"]
    path = write_demo(source, name, "# pyright: strict\n" if strict else "")
    completed = subprocess.run(
        [str(pyright), "--outputjson", "--pythonpath", sys.executable, path.name],
        cwd=UNIT42_DIR,
        capture_output=True,
        text=True,
        env=CHECKER_ENV,
        timeout=300,
    )
    try:
        report = json.loads(completed.stdout)
    except ValueError:
        return [
            f"SKIP: pyright did not run: {(completed.stderr or completed.stdout).strip()[:120]}"
        ]
    findings = []
    for diagnostic in report["generalDiagnostics"]:
        line_number = diagnostic["range"]["start"]["line"] + 1 - (1 if strict else 0)
        message = " ".join(part.strip() for part in diagnostic["message"].splitlines()[:2])
        rule = f"  [{diagnostic['rule']}]" if diagnostic.get("rule") else ""
        findings.append(f"{path.name}:{line_number}: {diagnostic['severity']}: {message}{rule}")
    return findings


def check(
    source: str,
    *,
    name: str = "demo",
    strict: bool = False,
    checkers: tuple[str, ...] = ("mypy", "pyright"),
) -> None:
    """Print what each checker reports for source (line numbers count from its first line)."""
    for checker in checkers:
        runner = run_mypy if checker == "mypy" else run_pyright
        findings = runner(source, name=name, strict=strict)
        print(f"{checker}{' (strict)' if strict else ''}:")
        print(textwrap.indent("\n".join(findings) or "no issues", "  "))


def source_of(obj: object) -> str:
    """Source code of a function or class, also for classes defined in a notebook cell."""
    try:
        return textwrap.dedent(inspect.getsource(obj))
    except OSError, TypeError:
        if not isinstance(obj, type):
            raise
    # inspect cannot find the file of a notebook class; use the file of one of its functions
    for member in vars(obj).values():
        member = getattr(member, "__func__", None) or getattr(member, "fget", None) or member
        code_object = getattr(inspect.unwrap(member), "__code__", None)
        lines = linecache.getlines(code_object.co_filename) if code_object else []
        if lines:
            start = obj.__firstlineno__ - 1
            while start > 0 and lines[start - 1].lstrip().startswith("@"):
                start -= 1
            return textwrap.dedent("".join(inspect.getblock(lines[start:])))
    # no functions (e.g. an exception class with only a docstring): search the cached cell sources
    header = re.compile(rf"\s*class\s+{obj.__name__}\b")
    for _size, _mtime, lines, _name in reversed(list(linecache.cache.values())):
        if len(lines) >= obj.__firstlineno__ and header.match(lines[obj.__firstlineno__ - 1]):
            return textwrap.dedent("".join(inspect.getblock(lines[obj.__firstlineno__ - 1 :])))
    raise OSError(f"source of {obj.__name__} not found")


LAB_PRELUDE = """
import functools
import typing
import re
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any, Literal, Self, cast, get_type_hints, overload, reveal_type

PAISE = Decimal("0.01")
"""


@functools.cache
def mypy_report(source: str, strict: bool = True) -> tuple[str, ...]:
    """mypy's lines for LAB_PRELUDE + source (cached: identical source is checked once)."""
    return tuple(run_mypy(LAB_PRELUDE + "\n\n" + source, name="lab_check", strict=strict))


def mypy_errors(*objects: object, strict: bool = True, extra: str = "") -> list[str]:
    """Error lines (no notes) mypy reports for the source of objects, plus extra code."""
    source = "\n\n".join([*(source_of(obj) for obj in objects), textwrap.dedent(extra)])
    return [
        line.split(": error: ", 1)[1] for line in mypy_report(source, strict) if ": error: " in line
    ]


def revealed_types(*objects: object, extra: str = "") -> list[str]:
    """The types mypy reveals for reveal_type(...) calls in extra (after the objects' source)."""
    source = "\n\n".join([*(source_of(obj) for obj in objects), textwrap.dedent(extra)])
    return re.findall(r'Revealed type is "([^"]+)"', "\n".join(mypy_report(source, True)))


def raised_message(thunk: Callable[[], object]) -> str:
    """Call thunk and return "ErrorName: message" for the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return f"{type(error).__name__}: {error}"
    return "no error"


# Lab 4.2 solutions ----------------------------------------------------------------------------

# Exercise 1 ------------------------------------------------------------------------------------


def count_words(text: str) -> dict[str, int]:
    words = text.lower().split()
    counts = dict.fromkeys(words, 0)
    for word in words:
        counts[word] += 1
    return counts


def average(values: Iterable[float]) -> float:
    total = 0.0
    count = 0
    for value in values:
        total += value
        count += 1
    return total / count if count else 0.0


def find_user(users: Mapping[int, str], user_id: int) -> str | None:
    return users.get(user_id)


def pair_up(names: Sequence[str], scores: Sequence[int]) -> list[tuple[str, int]]:
    return list(zip(names, scores, strict=True))


def parse_point(text: str) -> tuple[float, float]:
    x_text, y_text = text.split(",")
    return float(x_text), float(y_text)


def chunk[T](items: Sequence[T], size: int) -> list[list[T]]:
    return [list(items[start : start + size]) for start in range(0, len(items), size)]


def merge_settings(
    defaults: Mapping[str, object], overrides: Mapping[str, object]
) -> dict[str, object]:
    return {**defaults, **overrides}


def first_or_default[T](items: Iterable[T], default: T) -> T:
    for item in items:
        return item
    return default


def apply_twice[T](func: Callable[[T], T], value: T) -> T:
    return func(func(value))


def status_text(code: int) -> Literal["ok", "client error", "server error", "unknown"]:
    if 200 <= code < 300:
        return "ok"
    if 400 <= code < 500:
        return "client error"
    if 500 <= code < 600:
        return "server error"
    return "unknown"


# Exercise 2 ------------------------------------------------------------------------------------


class Stack[T]:
    """A last-in, first-out stack."""

    def __init__(self) -> None:
        self._items: list[T] = []

    def push(self, item: T) -> None:
        self._items.append(item)

    def pop(self) -> T:
        if not self._items:
            raise IndexError("pop from empty stack")
        return self._items.pop()

    def peek(self) -> T | None:
        return self._items[-1] if self._items else None

    def __len__(self) -> int:
        return len(self._items)

    def is_empty(self) -> bool:
        return not self._items


@dataclass(frozen=True)
class Ok[T]:
    value: T

    def is_ok(self) -> bool:
        return True

    def unwrap(self) -> T:
        return self.value


@dataclass(frozen=True)
class Err[E]:
    error: E

    def is_ok(self) -> bool:
        return False

    def unwrap(self) -> typing.Never:
        raise ValueError(f"unwrap on Err: {self.error!r}")


type Result[T, E] = Ok[T] | Err[E]


def safe_divide(a: float, b: float) -> Result[float, str]:
    """Ok(a / b), or Err("division by zero")."""
    if b == 0:
        return Err("division by zero")
    return Ok(a / b)


# Exercise 3 ------------------------------------------------------------------------------------


def retry[**P, R](
    times: int = 3,
    *,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    delay: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Retry the decorated function up to `times` times on the given exceptions."""

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            for attempt in range(1, times + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions:
                    if attempt == times:
                        raise
                    sleep(delay)
            raise AssertionError("unreachable: times must be at least 1")

        return wrapper

    return decorator


# Exercise 4 ------------------------------------------------------------------------------------


@overload
def parse_value(text: str, kind: Literal["int"]) -> int: ...
@overload
def parse_value(text: str, kind: Literal["float"]) -> float: ...
@overload
def parse_value(text: str, kind: Literal["bool"]) -> bool: ...
@overload
def parse_value(text: str, kind: Literal["str"] = "str") -> str: ...
def parse_value(
    text: str, kind: Literal["int", "float", "bool", "str"] = "str"
) -> int | float | bool | str:
    """Convert text to str, int, float or bool according to kind."""
    match kind:
        case "int":
            return int(text)
        case "float":
            return float(text)
        case "bool":
            word = text.strip().lower()
            if word in {"true", "yes", "1", "false", "no", "0"}:
                return word in {"true", "yes", "1"}
            raise ValueError(f"not a boolean: {text!r}")
        case "str":
            return text.strip()


# Exercise 5 ------------------------------------------------------------------------------------


@dataclass
class LineItem:
    sku: str
    quantity: int
    unit_price: Decimal

    def total(self) -> Decimal:
        return self.quantity * self.unit_price


def parse_line(raw: str) -> LineItem:
    sku, quantity, price = raw.split(",")
    return LineItem(sku, int(quantity), Decimal(price))


def find_item(items: list[LineItem], sku: str) -> LineItem | None:
    for item in items:
        if item.sku == sku:
            return item
    return None


def quantity_of(items: list[LineItem], sku: str) -> int:
    item = find_item(items, sku)
    return item.quantity if item is not None else 0


def order_total(items: list[LineItem]) -> Decimal:
    total = Decimal(0)
    for item in items:
        total += item.total()
    return total


def describe(item: LineItem) -> str:
    return f"{item.sku} x {item.quantity}"


def totals_by_sku(items: list[LineItem]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for item in items:
        totals[item.sku] = item.total()
    return totals


def sample_item() -> LineItem:
    return LineItem(sku="RICE", quantity=1, unit_price=Decimal("80"))


def cheapest(items: list[LineItem]) -> str:
    return min(items, key=lambda item: item.unit_price).sku


ORDER_REPORT = [
    LineItem,
    parse_line,
    find_item,
    quantity_of,
    order_total,
    describe,
    totals_by_sku,
    sample_item,
    cheapest,
]


# Exercise 6 ------------------------------------------------------------------------------------


class CurrencyMismatchError(ValueError):
    """Two Money values in different currencies were combined."""


class Money:
    __slots__ = ("_amount", "_currency")

    def __init__(self, amount: Decimal | int | str, currency: str = "INR") -> None:
        if isinstance(amount, float):
            raise TypeError("amount must be Decimal, int or str, not float")
        self._amount = Decimal(amount).quantize(PAISE, rounding=ROUND_HALF_UP)
        self._currency = currency

    @property
    def amount(self) -> Decimal:
        return self._amount

    @property
    def currency(self) -> str:
        return self._currency

    def __repr__(self) -> str:
        return f"Money({str(self._amount)!r}, {self._currency!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return (self._amount, self._currency) == (other._amount, other._currency)

    def __hash__(self) -> int:
        return hash((self._amount, self._currency))

    def __add__(self, other: object) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        if other._currency != self._currency:
            raise CurrencyMismatchError(f"{self._currency} vs {other._currency}")
        return Money(self._amount + other._amount, self._currency)

    def __mul__(self, factor: object) -> Money:
        if isinstance(factor, bool) or not isinstance(factor, (int, Decimal)):
            return NotImplemented
        return Money(self._amount * factor, self._currency)


class InsufficientStockError(Exception):
    def __init__(self, sku: str, available: int, requested: int) -> None:
        super().__init__(f"not enough {sku}: {available} available, {requested} requested")
        self.sku, self.available, self.requested = sku, available, requested


class Product:
    def __init__(self, sku: str, name: str, unit_price: Money) -> None:
        self.sku, self.name, self.unit_price = sku, name, unit_price

    def __repr__(self) -> str:
        return f"Product({self.sku!r}, {self.name!r}, {self.unit_price!r})"


class Warehouse:
    def __init__(self, code: str) -> None:
        self.code = code
        self._products: dict[str, Product] = {}
        self._quantities: dict[str, int] = {}

    def add_product(self, product: Product) -> None:
        self._products[product.sku] = product
        self._quantities[product.sku] = 0

    def receive(self, sku: str, quantity: int) -> int:
        self._quantities[sku] += quantity
        return self._quantities[sku]

    def ship(self, sku: str, quantity: int) -> int:
        available = self._quantities[sku]
        if quantity > available:
            raise InsufficientStockError(sku, available, quantity)
        self._quantities[sku] = available - quantity
        return self._quantities[sku]

    def stock_value(self) -> Money:
        return sum(
            (product.unit_price * self._quantities[sku] for sku, product in self._products.items()),
            Money(0),
        )


# Exercise 7 ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Range:
    minimum: int
    maximum: int


@dataclass(frozen=True)
class MaxLength:
    limit: int


@dataclass(frozen=True)
class Pattern:
    regex: str


def _constraint_error(name: str, value: object, constraint: object) -> str | None:
    """The message for one violated constraint, or None."""
    match constraint:
        case Range(minimum, maximum) if not minimum <= value <= maximum:
            return f"{name}: {value} is not between {minimum} and {maximum}"
        case MaxLength(limit) if len(value) > limit:
            return f"{name}: longer than {limit} characters"
        case Pattern(regex) if re.fullmatch(regex, str(value)) is None:
            return f"{name}: does not match {regex}"
    return None


def validate(instance: object) -> list[str]:
    """Error messages for a dataclass instance, driven by Annotated metadata."""
    errors: list[str] = []
    for name, hint in get_type_hints(type(instance), include_extras=True).items():
        value = getattr(instance, name)
        base, metadata = hint, ()
        if typing.get_origin(hint) is Annotated:
            base, *rest = typing.get_args(hint)
            metadata = tuple(rest)
        if not isinstance(base, type):
            continue  # list[str], str | None, ...: not checked here
        if not isinstance(value, base) or (base is int and isinstance(value, bool)):
            errors.append(f"{name}: expected {base.__name__}, got {type(value).__name__}")
            continue
        for constraint in metadata:
            if message := _constraint_error(name, value, constraint):
                errors.append(message)
    return errors


def check_lab_4_2() -> None:
    """Run the notebook's Lab 4.2 check cells against the solutions above."""
    HINT_FUNCTIONS = [
        count_words,
        average,
        find_user,
        pair_up,
        parse_point,
        chunk,
        merge_settings,
        first_or_default,
        apply_twice,
        status_text,
    ]
    EXPECTED_HINTS = {
        "count_words": {"text": "str", "return": "dict[str, int]"},
        "average": {"values": "Iterable[float]", "return": "float"},
        "find_user": {"users": "Mapping[int, str]", "user_id": "int", "return": "str | None"},
        "pair_up": {
            "names": "Sequence[str]",
            "scores": "Sequence[int]",
            "return": "list[tuple[str, int]]",
        },
        "parse_point": {"text": "str", "return": "tuple[float, float]"},
        "chunk": {"items": "Sequence[T]", "size": "int", "return": "list[list[T]]"},
        "merge_settings": {
            "defaults": "Mapping[str, object]",
            "overrides": "Mapping[str, object]",
            "return": "dict[str, object]",
        },
        "first_or_default": {"items": "Iterable[T]", "default": "T", "return": "T"},
        "apply_twice": {"func": "Callable[[T], T]", "value": "T", "return": "T"},
        "status_text": {
            "code": "int",
            "return": 'Literal["ok", "client error", "server error", "unknown"]',
        },
    }

    def hint_strings(function: Callable[..., object]) -> dict[str, str]:
        """The annotations as written in the source, without spaces."""
        written = annotationlib.get_annotations(function, format=annotationlib.Format.STRING)
        return {name: text.replace(" ", "").replace("'", '"') for name, text in written.items()}

    run_checks(
        [
            *(
                (
                    f"hints of {function.__name__}",
                    lambda function=function: hint_strings(function),
                    {
                        name: text.replace(" ", "")
                        for name, text in EXPECTED_HINTS[function.__name__].items()
                    },
                )
                for function in HINT_FUNCTIONS
            ),
            ("mypy --strict is clean", lambda: mypy_errors(*HINT_FUNCTIONS), []),
            (
                "behaviour unchanged",
                lambda: (
                    count_words("a b a"),
                    chunk([1, 2, 3], 2),
                    status_text(404),
                    first_or_default([], 7),
                    apply_twice(lambda n: n * 3, 2),
                ),
                ({"a": 2, "b": 1}, [[1, 2], [3]], "client error", 7, 18),
            ),
        ]
    )

    GENERIC_USAGE = """
    type Result[T, E] = Ok[T] | Err[E]

    reveal_type(Stack[int]().pop())
    reveal_type(safe_divide(1, 2))
    Stack[int]().push("tea")
    """

    def stack_trace() -> list[object]:
        stack = Stack[str]()
        stack.push("tea")
        stack.push("rice")
        return [len(stack), stack.peek(), stack.pop(), stack.pop(), stack.is_empty(), stack.peek()]

    def generic_errors() -> list[str]:
        errors = mypy_errors(Stack, Ok, Err, safe_divide, extra=GENERIC_USAGE)
        return [error.split("  [")[-1] for error in errors]

    run_checks(
        [
            ("Stack behaviour", stack_trace, [2, "rice", "rice", "tea", True, None]),
            (
                "pop on empty",
                lambda: raised_message(lambda: Stack[int]().pop()),
                "IndexError: pop from empty stack",
            ),
            ("Ok", lambda: (Ok(5).is_ok(), Ok(5).unwrap()), (True, 5)),
            (
                "Err",
                lambda: (Err("boom").is_ok(), raised_message(lambda: Err("boom").unwrap())),
                (False, "ValueError: unwrap on Err: 'boom'"),
            ),
            (
                "safe_divide",
                lambda: (safe_divide(1, 4), safe_divide(1, 0)),
                (Ok(0.25), Err("division by zero")),
            ),
            (
                "PEP 695 parameters",
                lambda: (
                    [p.__name__ for p in Stack.__type_params__],
                    [p.__name__ for p in Result.__type_params__],
                ),
                (["T"], ["T", "E"]),
            ),
            (
                "mypy: types revealed",
                lambda: revealed_types(Stack, Ok, Err, safe_divide, extra=GENERIC_USAGE)[:2],
                ["int", "lab_check.Ok[float] | lab_check.Err[str]"],
            ),
            ("mypy: only the push('tea') error", generic_errors, ["arg-type]"]),
        ]
    )

    SERVICE_DOWN = ConnectionError("down")

    def flaky(failures: int, error: Exception = SERVICE_DOWN) -> Callable[[str], str]:
        """A function that raises `error` for its first `failures` calls."""
        calls = {"count": 0}

        def fetch(sku: str) -> str:
            calls["count"] += 1
            if calls["count"] <= failures:
                raise error
            return f"{sku} after {calls['count']} calls"

        return fetch

    def retry_run(
        failures: int, times: int, error: Exception = SERVICE_DOWN
    ) -> tuple[str, list[float]]:
        """Decorate flaky(failures, error); return (result or "Error: message", recorded sleeps)."""
        sleeps: list[float] = []
        decorate = retry(times, exceptions=(ConnectionError,), delay=0.5, sleep=sleeps.append)
        decorated = decorate(flaky(failures, error))
        try:
            outcome = decorated("TEA")
        except Exception as caught:
            outcome = f"{type(caught).__name__}: {caught}"
        return outcome, sleeps

    RETRY_USAGE = """
    @retry(3, exceptions=(ConnectionError,))
    def fetch_price(sku: str, quantity: int = 1) -> Decimal:
        return Decimal("10") * quantity

    reveal_type(fetch_price)
    fetch_price("TEA", 2)
    fetch_price(42)
    """

    run_checks(
        [
            (
                "succeeds on the 3rd call",
                lambda: retry_run(2, 3),
                ("TEA after 3 calls", [0.5, 0.5]),
            ),
            (
                "gives up after times",
                lambda: retry_run(5, 3),
                ("ConnectionError: down", [0.5, 0.5]),
            ),
            (
                "other errors propagate",
                lambda: retry_run(5, 3, KeyError("x")),
                ("KeyError: 'x'", []),
            ),
            ("keeps metadata", lambda: retry()(flaky(0)).__name__, "fetch"),
            (
                "mypy: signature kept",
                lambda: revealed_types(retry, extra=RETRY_USAGE),
                ["def (sku: str, quantity: int =) -> decimal.Decimal"],
            ),
            (
                "mypy: bad call rejected, nothing else",
                lambda: [e.split("  [")[-1] for e in mypy_errors(retry, extra=RETRY_USAGE)],
                ["arg-type]"],
            ),
        ]
    )

    OVERLOAD_USAGE = """
    reveal_type(parse_value("42", "int"))
    reveal_type(parse_value("2.5", "float"))
    reveal_type(parse_value("yes", "bool"))
    reveal_type(parse_value(" tea "))
    parse_value("2026-11-07", "date")
    """

    def overload_source() -> str:
        """The overloads and the implementation: source of the whole cell block."""
        return (
            "\n".join(source_of(f) for f in typing.get_overloads(parse_value))
            + "\n"
            + source_of(parse_value)
        )

    run_checks(
        [
            ("int", lambda: parse_value("42", "int"), 42),
            ("float", lambda: parse_value("2.5", "float"), 2.5),
            (
                "bool",
                lambda: [parse_value(t, "bool") for t in ("Yes", "TRUE", "1", "no", "False", "0")],
                [True, True, True, False, False, False],
            ),
            (
                "bad bool",
                lambda: raised_error_name(lambda: parse_value("maybe", "bool")),
                "ValueError",
            ),
            ("str (default)", lambda: parse_value(" tea "), "tea"),
            ("four overloads", lambda: len(typing.get_overloads(parse_value)), 4),
            (
                "mypy: types",
                lambda: re.findall(
                    r'Revealed type is "([^"]+)"',
                    "\n".join(mypy_report(overload_source() + textwrap.dedent(OVERLOAD_USAGE))),
                ),
                ["int", "float", "bool", "str"],
            ),
            (
                "mypy: unknown kind rejected",
                lambda: [
                    line.split("  [")[-1]
                    for line in mypy_report(overload_source() + textwrap.dedent(OVERLOAD_USAGE))
                    if ": error:" in line
                ],
                ["call-overload]"],
            ),
        ]
    )

    SAMPLE_LINES = [parse_line("TEA,2,120.50"), parse_line("RICE,1,80")]

    run_checks(
        [
            ("mypy is clean", lambda: mypy_errors(*ORDER_REPORT, strict=False), []),
            (
                "parse_line",
                lambda: parse_line("TEA,2,120.50"),
                LineItem("TEA", 2, Decimal("120.50")),
            ),
            ("find_item missing", lambda: find_item(SAMPLE_LINES, "SALT"), None),
            (
                "quantity_of",
                lambda: (quantity_of(SAMPLE_LINES, "TEA"), quantity_of(SAMPLE_LINES, "SALT")),
                (2, 0),
            ),
            ("order_total", lambda: order_total(SAMPLE_LINES), Decimal("321.00")),
            ("order_total type", lambda: type(order_total([])).__name__, "Decimal"),
            ("describe", lambda: describe(SAMPLE_LINES[0]), "TEA x 2"),
            (
                "totals_by_sku",
                lambda: totals_by_sku(SAMPLE_LINES),
                {"TEA": Decimal("241.00"), "RICE": Decimal("80")},
            ),
            ("sample_item", sample_item, LineItem("RICE", 1, Decimal("80"))),
            ("cheapest", lambda: cheapest(SAMPLE_LINES), "RICE"),
        ]
    )

    INVENTORY_MODEL = [CurrencyMismatchError, Money, InsufficientStockError, Product, Warehouse]

    def warehouse_story() -> tuple[object, ...]:
        pune = Warehouse("PNQ")
        pune.add_product(Product("TEA-500", "Assam tea", Money("120.50")))
        pune.add_product(Product("RICE-1K", "Basmati", Money(80)))
        received = pune.receive("TEA-500", 10)
        pune.receive("RICE-1K", 5)
        left = pune.ship("TEA-500", 4)
        shortage = raised_message(lambda: pune.ship("RICE-1K", 9))
        return received, left, shortage, pune.stock_value()

    run_checks(
        [
            ("mypy --strict is clean", lambda: mypy_errors(*INVENTORY_MODEL), []),
            (
                "Money arithmetic",
                lambda: (Money("10.005") + Money(5), Money(3) * 2),
                (Money("15.01"), Money("6.00")),
            ),
            (
                "currency mismatch",
                lambda: raised_error_name(lambda: Money(1) + Money(1, "USD")),
                "CurrencyMismatchError",
            ),
            ("float rejected", lambda: raised_error_name(lambda: Money(1.5)), "TypeError"),
            ("NotImplemented path", lambda: raised_error_name(lambda: Money(1) + 1), "TypeError"),
            (
                "warehouse story",
                warehouse_story,
                (
                    10,
                    6,
                    "InsufficientStockError: not enough RICE-1K: 5 available, 9 requested",
                    Money("1123.00"),
                ),
            ),
        ]
    )

    @dataclass
    class CustomerForm:
        name: Annotated[str, MaxLength(20)]
        age: Annotated[int, Range(0, 150)]
        email: Annotated[str, Pattern(r"[^@]+@[^@]+"), MaxLength(40)]
        city: str
        tags: list[str] = field(default_factory=list)

    run_checks(
        [
            ("valid", lambda: validate(CustomerForm("Asha", 31, "asha@example.com", "Pune")), []),
            (
                "range",
                lambda: validate(CustomerForm("Asha", 200, "asha@example.com", "Pune")),
                ["age: 200 is not between 0 and 150"],
            ),
            (
                "length and pattern",
                lambda: validate(CustomerForm("A" * 21, 31, "not-an-email", "Pune")),
                ["name: longer than 20 characters", "email: does not match [^@]+@[^@]+"],
            ),
            (
                "wrong types",
                lambda: validate(CustomerForm("Asha", "31", "a@b", 42)),
                ["age: expected int, got str", "city: expected str, got int"],
            ),
            (
                "bool is not int",
                lambda: validate(CustomerForm("Asha", True, "a@b", "Pune")),
                ["age: expected int, got bool"],
            ),
            (
                "several constraints",
                lambda: validate(CustomerForm("Asha", 31, "x" * 41 + "@b", "Pune")),
                ["email: longer than 40 characters"],
            ),
            (
                "generic hints skipped",
                lambda: validate(CustomerForm("Asha", 31, "a@b", "Pune", tags="oops")),
                [],
            ),
        ]
    )


# ===============================================================================================
# Lab 4.3 — helpers copied from the notebook's lab cells
# ===============================================================================================

if TYPE_CHECKING:  # the lab tests run in a child process whose prelude imports these names
    from shop.billing import split_bill
    from shop.inventory import (
        DuplicateProductError,
        EventBus,
        InMemoryInventoryRepository,
        InventoryRepository,
        InventoryService,
        LowStockAlert,
        MovementType,
        StockChanged,
        StockMovement,
        UnknownProductError,
        UnknownWarehouseError,
    )
    from shop.rates import ExchangeRateClient, RateLookupError

MONEY_MODULE = """
    \"\"\"The shared Money value type (Lab 2.4, exercise 1; Phase 2 Project, Step 1).\"\"\"

    from __future__ import annotations

    import functools
    from decimal import ROUND_HALF_UP, Decimal

    PAISE = Decimal("0.01")


    class CurrencyMismatchError(ValueError):
        \"\"\"Two Money values in different currencies were combined or compared.\"\"\"


    @functools.total_ordering
    class Money:
        __slots__ = ("_amount", "_currency")

        def __init__(self, amount: Decimal | int | str, currency: str = "INR") -> None:
            if isinstance(amount, float):
                raise TypeError("amount must be Decimal, int or str, not float")
            if not (len(currency) == 3 and currency.isalpha() and currency.isupper()):
                raise ValueError(f"invalid currency code: {currency!r}")
            self._amount = Decimal(amount).quantize(PAISE, rounding=ROUND_HALF_UP)
            self._currency = currency

        @property
        def amount(self) -> Decimal:
            return self._amount

        @property
        def currency(self) -> str:
            return self._currency

        def __repr__(self) -> str:
            return f"Money({str(self._amount)!r}, {self._currency!r})"

        def __str__(self) -> str:
            return f"{self._currency} {self._amount:,.2f}"

        def _same_currency(self, other: Money) -> None:
            if other._currency != self._currency:
                raise CurrencyMismatchError(
                    f"currency mismatch: {self._currency} vs {other._currency}"
                )

        def __eq__(self, other: object) -> bool:
            if not isinstance(other, Money):
                return NotImplemented
            return (self._amount, self._currency) == (other._amount, other._currency)

        def __hash__(self) -> int:
            return hash((self._amount, self._currency))

        def __lt__(self, other: object) -> bool:
            if not isinstance(other, Money):
                return NotImplemented
            self._same_currency(other)
            return self._amount < other._amount

        def __add__(self, other: object) -> Money:
            if not isinstance(other, Money):
                return NotImplemented
            self._same_currency(other)
            return Money(self._amount + other._amount, self._currency)

        def __radd__(self, other: object) -> Money:
            if isinstance(other, int) and not isinstance(other, bool) and other == 0:
                return self  # sum() starts from 0
            return NotImplemented

        def __sub__(self, other: object) -> Money:
            if not isinstance(other, Money):
                return NotImplemented
            self._same_currency(other)
            return Money(self._amount - other._amount, self._currency)

        def __mul__(self, factor: object) -> Money:
            if isinstance(factor, bool) or not isinstance(factor, (int, Decimal)):
                return NotImplemented
            return Money(self._amount * factor, self._currency)

        __rmul__ = __mul__

        def __neg__(self) -> Money:
            return Money(-self._amount, self._currency)

        def __bool__(self) -> bool:
            return bool(self._amount)
"""

BILLING_MODULE = """
    \"\"\"split_bill from Lab 1.3.\"\"\"

    from decimal import ROUND_HALF_UP, Decimal

    PAISE = Decimal("0.01")


    def split_bill(total_amount: str, people_count: int) -> list[Decimal]:
        \"\"\"Split a rupee amount into people_count parts, exact to the paisa.\"\"\"
        if people_count < 1:
            raise ValueError(f"people_count must be at least 1, got {people_count}")
        total_in_paise = int(Decimal(total_amount).quantize(PAISE, rounding=ROUND_HALF_UP) * 100)
        base_share_in_paise, leftover_paise = divmod(total_in_paise, people_count)
        return [
            (Decimal(base_share_in_paise + (1 if index < leftover_paise else 0)) / 100).quantize(
                PAISE
            )
            for index in range(people_count)
        ]
"""

RATES_MODULE = """
    \"\"\"Exchange rates from an HTTP service; the HTTP client is injected.\"\"\"

    from decimal import Decimal


    class RateLookupError(Exception):
        \"\"\"The rate service failed or returned something unusable.\"\"\"


    class ExchangeRateClient:
        def __init__(self, http, base_url: str = "https://rates.example.com/v1") -> None:
            self.http = http  # anything with .get(url, *, params, timeout) -> response
            self.base_url = base_url.rstrip("/")

        def rate(self, base: str, quote: str) -> Decimal:
            \"\"\"How many units of quote one unit of base buys.\"\"\"
            response = self.http.get(
                f"{self.base_url}/latest", params={"base": base, "symbols": quote}, timeout=5.0
            )
            if response.status_code != 200:
                raise RateLookupError(f"rate service returned HTTP {response.status_code}")
            try:
                return Decimal(str(response.json()["rates"][quote]))
            except (KeyError, TypeError) as error:
                raise RateLookupError(f"no {quote} rate in the response") from error

        def convert(self, amount: Decimal, base: str, quote: str) -> Decimal:
            \"\"\"amount in base currency -> quote currency, rounded to 2 places.\"\"\"
            if base == quote:
                return amount
            return (amount * self.rate(base, quote)).quantize(Decimal("0.01"))
"""

INVENTORY_MODULE = """
    \"\"\"The Phase 2 inventory domain model (Phase 2 Project, Steps 2-8).\"\"\"

    from __future__ import annotations

    import re
    from collections import defaultdict
    from collections.abc import Callable, Iterator
    from dataclasses import dataclass
    from datetime import datetime
    from enum import StrEnum, auto
    from typing import Any, Protocol, runtime_checkable

    from shop.money import Money

    SKU_PATTERN = re.compile(r"[A-Z]{2,5}-\\d{2,4}")


    @dataclass(frozen=True, slots=True)
    class Product:
        sku: str
        name: str
        unit_price: Money
        reorder_level: int = 5

        def __post_init__(self) -> None:
            if not SKU_PATTERN.fullmatch(self.sku):
                raise ValueError(f"invalid SKU {self.sku!r}: expected e.g. 'TEA-500'")
            if not self.name.strip():
                raise ValueError("product name is required")
            if not isinstance(self.unit_price, Money) or self.unit_price.amount <= 0:
                raise ValueError("unit_price must be a positive Money")
            if self.reorder_level < 0:
                raise ValueError("reorder_level must be >= 0")


    class MovementType(StrEnum):
        RECEIVED = auto()
        SHIPPED = auto()
        RETURNED = auto()
        ADJUSTED = auto()

        @property
        def direction(self) -> int:
            match self:
                case MovementType.RECEIVED | MovementType.RETURNED:
                    return 1
                case MovementType.SHIPPED:
                    return -1
                case _:
                    return 0


    @dataclass(frozen=True, slots=True)
    class StockMovement:
        warehouse_code: str
        sku: str
        movement_type: MovementType
        quantity: int
        occurred_at: datetime
        note: str = ""

        def __post_init__(self) -> None:
            if self.movement_type is MovementType.ADJUSTED:
                if self.quantity == 0:
                    raise ValueError("an adjustment must change the quantity")
            elif self.quantity <= 0:
                raise ValueError(f"{self.movement_type} quantity must be positive")

        @property
        def delta(self) -> int:
            if self.movement_type is MovementType.ADJUSTED:
                return self.quantity
            return self.quantity * self.movement_type.direction


    class InventoryError(Exception):
        error_code = "inventory_error"

        def to_dict(self) -> dict[str, str]:
            return {"error": self.error_code, "message": str(self)}


    class UnknownWarehouseError(InventoryError, LookupError):
        error_code = "unknown_warehouse"

        def __init__(self, warehouse_code: str) -> None:
            super().__init__(f"no warehouse with code {warehouse_code!r}")
            self.warehouse_code = warehouse_code


    class UnknownProductError(InventoryError, LookupError):
        error_code = "unknown_product"

        def __init__(self, sku: str, warehouse_code: str) -> None:
            super().__init__(f"{sku} is not stocked in {warehouse_code}")
            self.sku, self.warehouse_code = sku, warehouse_code


    class DuplicateProductError(InventoryError, ValueError):
        error_code = "duplicate_product"

        def __init__(self, sku: str, warehouse_code: str) -> None:
            super().__init__(f"{sku} is already stocked in {warehouse_code}")
            self.sku, self.warehouse_code = sku, warehouse_code


    class InsufficientStockError(InventoryError):
        error_code = "insufficient_stock"

        def __init__(self, sku: str, available: int, requested: int) -> None:
            super().__init__(f"not enough {sku}: {available} available, {requested} requested")
            self.sku, self.available, self.requested = sku, available, requested


    class Warehouse:
        def __init__(self, code: str, city: str) -> None:
            self.code, self.city = code, city
            self._products: dict[str, Product] = {}
            self._quantities: dict[str, int] = {}

        def __repr__(self) -> str:
            return f"Warehouse({self.code!r}, {self.city!r}, products={len(self)})"

        def __eq__(self, other: object) -> bool:
            return self.code == other.code if isinstance(other, Warehouse) else NotImplemented

        def __hash__(self) -> int:
            return hash(self.code)

        def __len__(self) -> int:
            return len(self._products)

        def __contains__(self, item: object) -> bool:
            sku = item.sku if isinstance(item, Product) else item
            return sku in self._products

        def __getitem__(self, sku: str) -> int:
            if sku not in self._products:
                raise UnknownProductError(sku, self.code)
            return self._quantities[sku]

        def __iter__(self) -> Iterator[Product]:
            return iter(sorted(self._products.values(), key=lambda product: product.sku))

        def __bool__(self) -> bool:
            return any(self._quantities.values())

        def product(self, sku: str) -> Product:
            if sku not in self._products:
                raise UnknownProductError(sku, self.code)
            return self._products[sku]

        def add_product(self, product: Product) -> None:
            if product.sku in self._products:
                raise DuplicateProductError(product.sku, self.code)
            self._products[product.sku] = product
            self._quantities[product.sku] = 0

        def apply(self, movement: StockMovement) -> int:
            available = self[movement.sku]
            if available + movement.delta < 0:
                raise InsufficientStockError(movement.sku, available, -movement.delta)
            self._quantities[movement.sku] = available + movement.delta
            return self._quantities[movement.sku]

        def stock_value(self) -> Money:
            return sum((product.unit_price * self[product.sku] for product in self), Money(0))

        def low_stock(self) -> list[Product]:
            return [product for product in self if self[product.sku] <= product.reorder_level]


    @runtime_checkable
    class InventoryRepository(Protocol):
        def get_warehouse(self, code: str) -> Warehouse: ...
        def save_warehouse(self, warehouse: Warehouse) -> None: ...
        def list_warehouses(self) -> list[Warehouse]: ...
        def record_movement(self, movement: StockMovement) -> None: ...
        def movements(self, *, sku: str | None = None) -> list[StockMovement]: ...


    class InMemoryInventoryRepository:
        def __init__(self) -> None:
            self._warehouses: dict[str, Warehouse] = {}
            self._movements: list[StockMovement] = []

        def get_warehouse(self, code: str) -> Warehouse:
            try:
                return self._warehouses[code]
            except KeyError:
                raise UnknownWarehouseError(code) from None

        def save_warehouse(self, warehouse: Warehouse) -> None:
            self._warehouses[warehouse.code] = warehouse

        def list_warehouses(self) -> list[Warehouse]:
            return sorted(self._warehouses.values(), key=lambda warehouse: warehouse.code)

        def record_movement(self, movement: StockMovement) -> None:
            self._movements.append(movement)

        def movements(self, *, sku: str | None = None) -> list[StockMovement]:
            return [movement for movement in self._movements if sku is None or movement.sku == sku]


    @dataclass(frozen=True)
    class StockChanged:
        warehouse_code: str
        sku: str
        old_quantity: int
        new_quantity: int
        movement_type: MovementType


    @dataclass(frozen=True)
    class LowStockAlert:
        warehouse_code: str
        sku: str
        quantity: int
        reorder_level: int


    class EventBus:
        def __init__(self) -> None:
            self._handlers: defaultdict[type, list[Callable[[Any], None]]] = defaultdict(list)

        def subscribe(self, event_type: type, handler: Callable[[Any], None]) -> None:
            self._handlers[event_type].append(handler)

        def publish(self, event: object) -> int:
            handlers = self._handlers.get(type(event), [])
            for handler in handlers:
                handler(event)
            return len(handlers)


    class InventoryService:
        def __init__(
            self,
            repository: InventoryRepository,
            events: EventBus,
            clock: Callable[[], datetime] = datetime.now,
        ) -> None:
            self.repository, self.events, self.clock = repository, events, clock

        def open_warehouse(self, code: str, city: str) -> Warehouse:
            warehouse = Warehouse(code, city)
            self.repository.save_warehouse(warehouse)
            return warehouse

        def register_product(self, warehouse_code: str, product: Product) -> None:
            warehouse = self.repository.get_warehouse(warehouse_code)
            warehouse.add_product(product)
            self.repository.save_warehouse(warehouse)

        def receive(self, warehouse_code: str, sku: str, quantity: int, note: str = "") -> int:
            return self._record(warehouse_code, sku, MovementType.RECEIVED, quantity, note)

        def ship(self, warehouse_code: str, sku: str, quantity: int, note: str = "") -> int:
            return self._record(warehouse_code, sku, MovementType.SHIPPED, quantity, note)

        def accept_return(
            self, warehouse_code: str, sku: str, quantity: int, note: str = ""
        ) -> int:
            return self._record(warehouse_code, sku, MovementType.RETURNED, quantity, note)

        def adjust(self, warehouse_code: str, sku: str, change: int, note: str) -> int:
            return self._record(warehouse_code, sku, MovementType.ADJUSTED, change, note)

        def transfer(self, from_code: str, to_code: str, sku: str, quantity: int) -> None:
            source = self.repository.get_warehouse(from_code)
            destination = self.repository.get_warehouse(to_code)
            if source[sku] < quantity:
                raise InsufficientStockError(sku, source[sku], quantity)
            if sku not in destination:
                self.register_product(to_code, source.product(sku))
            self.ship(from_code, sku, quantity, note=f"transfer to {to_code}")
            self.receive(to_code, sku, quantity, note=f"transfer from {from_code}")

        def total_value(self) -> Money:
            return sum(
                (warehouse.stock_value() for warehouse in self.repository.list_warehouses()),
                Money(0),
            )

        def stock_report(self, warehouse_code: str) -> list[str]:
            warehouse = self.repository.get_warehouse(warehouse_code)
            lines = [f"{warehouse.code} ({warehouse.city})"]
            for product in warehouse:
                flag = "  LOW" if product in warehouse.low_stock() else ""
                lines.append(f"{product.sku:<9}{warehouse[product.sku]:>5}{flag}")
            lines.append(f"total {warehouse.stock_value()}")
            return lines

        def _record(
            self,
            warehouse_code: str,
            sku: str,
            movement_type: MovementType,
            quantity: int,
            note: str,
        ) -> int:
            warehouse = self.repository.get_warehouse(warehouse_code)
            old_quantity = warehouse[sku]
            movement = StockMovement(
                warehouse_code, sku, movement_type, quantity, self.clock(), note
            )
            new_quantity = warehouse.apply(movement)
            self.repository.record_movement(movement)
            self.repository.save_warehouse(warehouse)
            self.events.publish(
                StockChanged(warehouse_code, sku, old_quantity, new_quantity, movement_type)
            )
            reorder_level = warehouse.product(sku).reorder_level
            if old_quantity > reorder_level >= new_quantity:
                self.events.publish(LowStockAlert(warehouse_code, sku, new_quantity, reorder_level))
            return new_quantity
"""

LAB_MODULES = {
    "shop/__init__.py": "",
    "shop/money.py": MONEY_MODULE,
    "shop/billing.py": BILLING_MODULE,
    "shop/rates.py": RATES_MODULE,
    "shop/inventory.py": INVENTORY_MODULE,
}
LAB43_DIR = find_repo_root() / "notebooks" / "_scratch" / "unit43" / "lab"

LAB_TEST_PRELUDE = """
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from unittest import mock

import pytest
from hypothesis import assume, example, given, settings
from hypothesis import strategies as st

from shop.billing import split_bill
from shop.inventory import (
    DuplicateProductError, EventBus, InMemoryInventoryRepository, InsufficientStockError,
    InventoryError, InventoryRepository, InventoryService, LowStockAlert, MovementType, Product,
    StockChanged, StockMovement, UnknownProductError, UnknownWarehouseError, Warehouse,
)
from shop.money import CurrencyMismatchError, Money
from shop.rates import ExchangeRateClient, RateLookupError
"""
LAB_CONFTEST = """
from hypothesis import settings

settings.register_profile("lab", derandomize=True, database=None, deadline=None)
settings.load_profile("lab")
"""
LAB_PYPROJECT = """
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
"""


@dataclass(frozen=True)
class LabRun:
    """Outcome of one pytest run: test name -> "passed" / "failed" / "skipped", plus coverage."""

    outcomes: dict[str, str]
    coverage_percent: float | None
    output: str

    @property
    def green(self) -> bool:
        """At least one test ran and nothing failed or errored."""
        return bool(self.outcomes) and set(self.outcomes.values()) <= {"passed"}


def lab_test_source(objects: list[object]) -> str:
    """The prelude followed by the source of each test or fixture function (never raises)."""
    try:
        return LAB_TEST_PRELUDE + "\n\n" + "\n\n".join(source_of(obj) for obj in objects)
    except (OSError, TypeError) as error:
        return (
            LAB_TEST_PRELUDE
            + f"\n\ndef test_source_unavailable():\n    raise RuntimeError({str(error)!r})\n"
        )


def run_lab_tests(
    test_source: str,
    conftest_source: str = "",
    mutation: tuple[str, str, str] | None = None,
    coverage_target: str | None = None,
) -> LabRun:
    """Run test_source with pytest in a child process against the shop package (or a mutant)."""
    return _cached_lab_run(test_source, conftest_source, mutation, coverage_target)


@functools.cache
def _cached_lab_run(
    test_source: str,
    conftest_source: str,
    mutation: tuple[str, str, str] | None,
    coverage_target: str | None,
) -> LabRun:
    """The run behind run_lab_tests; identical runs are done once."""
    modules = dict(LAB_MODULES)
    if mutation is not None:
        path, old, new = mutation
        if old not in modules[path]:
            raise ValueError(f"mutation target not found in {path}: {old!r}")
        modules[path] = modules[path].replace(old, new)
    root = LAB43_DIR / "run"
    shutil.rmtree(root, ignore_errors=True)
    files = {**modules, "pyproject.toml": LAB_PYPROJECT, "tests/test_lab.py": test_source}
    files["tests/conftest.py"] = LAB_CONFTEST + "\n" + conftest_source
    for relative_path, text in files.items():
        (root / relative_path).parent.mkdir(parents=True, exist_ok=True)
        (root / relative_path).write_text(
            textwrap.dedent(text).lstrip("\n") if relative_path.startswith("shop") else text
        )
    command = [
        str(Path(sys.executable).parent / "pytest"),
        "-q",
        "-p",
        "no:cacheprovider",
        "--junit-xml=report.xml",
    ]
    if coverage_target:
        command += [f"--cov={coverage_target}", "--cov-branch", "--cov-report=json:coverage.json"]
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("PYTEST_", "PYTHONPATH", "COV"))
    }
    completed = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        timeout=600,
        env={**environment, "NO_COLOR": "1", "PY_COLORS": "0", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    outcomes: dict[str, str] = {}
    if (root / "report.xml").exists():
        for case in ElementTree.parse(root / "report.xml").getroot().iter("testcase"):
            failed = case.find("failure") is not None or case.find("error") is not None
            skipped = case.find("skipped") is not None
            outcomes[case.get("name", "?")] = (
                "failed" if failed else "skipped" if skipped else "passed"
            )
    coverage_percent = None
    if coverage_target and (root / "coverage.json").exists():
        report = json.loads((root / "coverage.json").read_text())
        coverage_percent = round(report["totals"]["percent_covered"], 1)
    return LabRun(outcomes, coverage_percent, completed.stdout + completed.stderr)


def catches(test_source: str, mutation: tuple[str, str, str], conftest_source: str = "") -> bool:
    """True if the tests pass on the real shop package and fail on the mutant."""
    return (
        run_lab_tests(test_source, conftest_source).green
        and not run_lab_tests(test_source, conftest_source, mutation).green
    )


COUPON_SCRIPT = """
COUPONS = {"DIWALI10": 10, "FLAT5": 5}


def apply_coupon(total_paise, coupon):
    percent = COUPONS.get(coupon, 0)
    discount = total_paise * percent // 10
    return total_paise - discount


def checkout(cart, coupon):
    total = sum(price * quantity for price, quantity in cart)
    return apply_coupon(total, coupon)


print(checkout([(24000, 2), (19900, 1)], "DIWALI10"))
"""
COUPON_DIR = LAB43_DIR / "coupon"
COUPON_DIR.mkdir(parents=True, exist_ok=True)
(COUPON_DIR / "coupon.py").write_text(textwrap.dedent(COUPON_SCRIPT).lstrip("\n"))


# Lab 4.3 solutions -----------------------------------------------------------------------------

# Exercise 1 ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw_amount", "expected"),
    [("0.125", "0.13"), ("0.124", "0.12"), ("-0.125", "-0.13"), ("19", "19.00")],
    ids=["half-up", "below-half", "negative-half", "whole-rupees"],
)
def test_money_rounding(raw_amount: str, expected: str) -> None:
    """Amounts are rounded half-up to the paisa."""
    assert Money(raw_amount).amount == Decimal(expected)


@pytest.mark.parametrize(
    ("left", "operator", "right", "expected"),
    [
        pytest.param(Money("240"), "+", Money("199"), Money("439"), id="add"),
        pytest.param(Money("0.10"), "+", Money("0.20"), Money("0.30"), id="add-paise"),
        pytest.param(Money("240"), "-", Money("199"), Money("41"), id="subtract"),
        pytest.param(Money("1"), "-", Money("2.50"), Money("-1.50"), id="subtract-below-zero"),
    ],
)
def test_money_arithmetic(left: Money, operator: str, right: Money, expected: Money) -> None:
    """+ and - keep exact paise and the currency."""
    result = left + right if operator == "+" else left - right
    assert result == expected


def test_money_rejects_bad_input() -> None:
    """Floats and mixed currencies are refused."""
    with pytest.raises(TypeError, match="float"):
        Money(0.1)  # type: ignore[arg-type]
    with pytest.raises(CurrencyMismatchError, match="INR vs USD"):
        Money(1) + Money(1, "USD")


MONEY_TESTS = [test_money_rounding, test_money_arithmetic, test_money_rejects_bad_input]


# Exercise 2 ------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def catalogue() -> dict[str, Product]:
    """TEA-500 (240, reorder 10), MUG-02 (199, reorder 5), JAR-750 (350, reorder 3)."""
    products = [
        Product("TEA-500", "Masala tea 500 g", Money("240"), reorder_level=10),
        Product("MUG-02", "Steel mug", Money("199"), reorder_level=5),
        Product("JAR-750", "Pickle jar 750 ml", Money("350"), reorder_level=3),
    ]
    return {product.sku: product for product in products}


@pytest.fixture
def repository(catalogue: dict[str, Product]) -> InMemoryInventoryRepository:
    """PNQ1 (Pune) and BLR1 (Bengaluru), each carrying every product, zero stock."""
    fresh_repository = InMemoryInventoryRepository()
    for code, city in (("PNQ1", "Pune"), ("BLR1", "Bengaluru")):
        warehouse = Warehouse(code, city)
        for product in catalogue.values():
            warehouse.add_product(product)
        fresh_repository.save_warehouse(warehouse)
    return fresh_repository


@pytest.fixture
def clock() -> Callable[[], datetime]:
    """Always returns datetime(2026, 11, 7, 9, 30)."""
    return lambda: datetime(2026, 11, 7, 9, 30)


@pytest.fixture
def make_service(
    repository: InMemoryInventoryRepository, clock: Callable[[], datetime]
) -> Callable[..., InventoryService]:
    """Factory: make_service(stock=None) -> InventoryService, stock received into PNQ1."""

    def build(stock: dict[str, int] | None = None) -> InventoryService:
        service = InventoryService(repository, EventBus(), clock)
        for sku, quantity in (stock or {}).items():
            service.receive("PNQ1", sku, quantity)
        return service

    return build


INVENTORY_FIXTURES = [catalogue, repository, clock, make_service]


# Exercise 3 ------------------------------------------------------------------------------------


def fake_http(status_code: int = 200, payload: object = None) -> mock.Mock:
    """A stub HTTP client whose get() returns one canned response."""
    response = mock.Mock(status_code=status_code)
    response.json.return_value = payload if payload is not None else {"rates": {"USD": 0.012}}
    http = mock.Mock()
    http.get.return_value = response
    return http


def test_rate_is_parsed_exactly() -> None:
    """A JSON number becomes the exact Decimal it was written as."""
    client = ExchangeRateClient(fake_http(payload={"rates": {"USD": 0.012}}))
    assert client.rate("INR", "USD") == Decimal("0.012")


def test_rate_request_is_well_formed() -> None:
    """URL, query parameters and timeout are exactly as the service expects."""
    http = fake_http()
    ExchangeRateClient(http, base_url="https://rates.test/v1/").rate("INR", "USD")
    http.get.assert_called_once_with(
        "https://rates.test/v1/latest", params={"base": "INR", "symbols": "USD"}, timeout=5.0
    )


def test_http_error_is_rejected_before_reading_the_body() -> None:
    """A 503 raises RateLookupError and the body is never parsed."""
    http = fake_http(status_code=503)
    with pytest.raises(RateLookupError, match="503"):
        ExchangeRateClient(http).rate("INR", "USD")
    http.get.return_value.json.assert_not_called()


def test_same_currency_conversion_skips_the_service() -> None:
    """INR -> INR needs no HTTP call."""
    http = fake_http()
    assert ExchangeRateClient(http).convert(Decimal("100"), "INR", "INR") == Decimal("100")
    http.get.assert_not_called()


RATE_TESTS = [
    fake_http,
    test_rate_is_parsed_exactly,
    test_rate_request_is_well_formed,
    test_http_error_is_rejected_before_reading_the_body,
    test_same_currency_conversion_skips_the_service,
]


# Exercise 4 ------------------------------------------------------------------------------------


@given(
    st.decimals(min_value=0, max_value=100_000, places=2).map(str),
    st.integers(min_value=1, max_value=50),
)
def test_share_count(total_amount: str, people_count: int) -> None:
    """One share per person."""
    assert len(split_bill(total_amount, people_count)) == people_count


@given(
    st.decimals(min_value=0, max_value=100_000, places=2).map(str),
    st.integers(min_value=1, max_value=50),
)
def test_shares_add_up_exactly(total_amount: str, people_count: int) -> None:
    """Nothing is lost or invented."""
    assert sum(split_bill(total_amount, people_count)) == Decimal(total_amount)


@given(
    st.decimals(min_value=0, max_value=100_000, places=2).map(str),
    st.integers(min_value=1, max_value=50),
)
def test_shares_differ_by_at_most_one_paisa(total_amount: str, people_count: int) -> None:
    """The split is as fair as paise allow."""
    shares = split_bill(total_amount, people_count)
    assert max(shares) - min(shares) <= Decimal("0.01")


@given(
    st.decimals(min_value=0, max_value=100_000, places=2).map(str),
    st.integers(min_value=1, max_value=50),
)
def test_shares_never_increase(total_amount: str, people_count: int) -> None:
    """The leftover paise go to the first people."""
    shares = split_bill(total_amount, people_count)
    assert all(earlier >= later for earlier, later in zip(shares, shares[1:], strict=False))


@given(st.integers(max_value=0))
def test_invalid_people_count_is_rejected(people_count: int) -> None:
    """Zero or negative people is an error."""
    with pytest.raises(ValueError):
        split_bill("100.00", people_count)


SPLIT_BILL_TESTS = [
    test_share_count,
    test_shares_add_up_exactly,
    test_shares_differ_by_at_most_one_paisa,
    test_shares_never_increase,
    test_invalid_people_count_is_rejected,
]


# Exercise 5 ------------------------------------------------------------------------------------


class JsonFormatter(logging.Formatter):
    """Format each record as one line of JSON."""

    STANDARD_ATTRIBUTES = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload |= {
            key: value for key, value in vars(record).items() if key not in self.STANDARD_ATTRIBUTES
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class HealthCheckFilter(logging.Filter):
    """Drop health-check noise."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "/health" not in record.getMessage()


def build_logging_config(stream: IO[str]) -> dict[str, object]:
    """A dictConfig dict: JSON lines to stream for the shop loggers."""
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"json": {"()": JsonFormatter}},
        "filters": {"no_health": {"()": HealthCheckFilter}},
        "handlers": {
            "json_stream": {
                "class": "logging.StreamHandler",
                "stream": stream,
                "formatter": "json",
                "level": "INFO",
                "filters": ["no_health"],
            },
        },
        "loggers": {
            "shop": {"handlers": ["json_stream"], "level": "DEBUG", "propagate": False},
            "shop.payments": {"level": "WARNING"},
        },
    }


# Exercise 6 ------------------------------------------------------------------------------------


def coupon_debug_commands() -> list[str]:
    """The pdb commands of the session, in order."""
    return ["b apply_coupon", "c", "n", "p percent", "n", "p discount", "w", "c"]


def coupon_bug_report() -> tuple[int, str]:
    """(line number of the bug, the corrected line)."""
    return 6, "discount = total_paise * percent // 100"


# Exercise 7 ------------------------------------------------------------------------------------


@pytest.fixture
def stocked() -> InventoryService:
    """Two warehouses; PNQ1 carries tea (40 units, reorder 10) and mugs (none, reorder 5)."""
    service = InventoryService(
        InMemoryInventoryRepository(), EventBus(), lambda: datetime(2026, 11, 7, 9, 30)
    )
    service.open_warehouse("PNQ1", "Pune")
    service.open_warehouse("BLR1", "Bengaluru")
    service.register_product("PNQ1", Product("TEA-500", "Masala tea", Money("240"), 10))
    service.register_product("PNQ1", Product("MUG-02", "Steel mug", Money("199"), 5))
    service.receive("PNQ1", "TEA-500", 40)
    return service


@pytest.mark.parametrize(
    ("sku", "name", "price", "reorder_level", "message"),
    [
        ("tea", "Tea", "1", 5, "invalid SKU"),
        ("TEA-500", "  ", "1", 5, "name is required"),
        ("TEA-500", "Tea", "0", 5, "positive Money"),
        ("TEA-500", "Tea", "1", -1, "reorder_level"),
    ],
    ids=["sku", "name", "price", "reorder-level"],
)
def test_product_validation(
    sku: str, name: str, price: str, reorder_level: int, message: str
) -> None:
    """Every rule in Product.__post_init__ rejects bad data."""
    with pytest.raises(ValueError, match=message):
        Product(sku, name, Money(price), reorder_level)


def test_product_requires_money() -> None:
    """A plain number is not a price."""
    with pytest.raises(ValueError, match="positive Money"):
        Product("TEA-500", "Tea", 240)


def test_movement_directions_and_deltas() -> None:
    """Each movement type has the right sign; adjustments carry their own."""
    moment = datetime(2026, 11, 7, 9, 30)
    assert [movement_type.direction for movement_type in MovementType] == [1, -1, 1, 0]
    shipped = StockMovement("PNQ1", "TEA-500", MovementType.SHIPPED, 3, moment)
    adjusted = StockMovement("PNQ1", "TEA-500", MovementType.ADJUSTED, -2, moment, "damaged")
    assert (shipped.delta, adjusted.delta) == (-3, -2)


def test_movement_validation() -> None:
    """Zero adjustments and non-positive quantities are refused."""
    moment = datetime(2026, 11, 7, 9, 30)
    with pytest.raises(ValueError, match="adjustment"):
        StockMovement("PNQ1", "TEA-500", MovementType.ADJUSTED, 0, moment)
    with pytest.raises(ValueError, match="positive"):
        StockMovement("PNQ1", "TEA-500", MovementType.RECEIVED, 0, moment)


def test_error_payloads() -> None:
    """Errors expose a code, a message and structured attributes."""
    shortage = InsufficientStockError("TEA-500", 2, 5)
    assert shortage.to_dict() == {
        "error": "insufficient_stock",
        "message": "not enough TEA-500: 2 available, 5 requested",
    }
    assert UnknownWarehouseError("NOPE").to_dict()["error"] == "unknown_warehouse"
    assert isinstance(DuplicateProductError("TEA-500", "PNQ1"), ValueError)


def test_warehouse_container_protocol(stocked: InventoryService) -> None:
    """len, in, [], iteration, bool, equality, hashing and repr."""
    pune = stocked.repository.get_warehouse("PNQ1")
    bengaluru = stocked.repository.get_warehouse("BLR1")
    assert (len(pune), "TEA-500" in pune, pune.product("TEA-500") in pune) == (2, True, True)
    assert [product.sku for product in pune] == ["MUG-02", "TEA-500"]
    assert (bool(pune), bool(bengaluru), pune["TEA-500"]) == (True, False, 40)
    assert pune == Warehouse("PNQ1", "Mumbai") and pune != "PNQ1"
    assert len({pune, Warehouse("PNQ1", "Mumbai")}) == 1
    assert repr(pune) == "Warehouse('PNQ1', 'Pune', products=2)"


def test_warehouse_errors(stocked: InventoryService) -> None:
    """Unknown products, duplicates and overselling raise domain errors."""
    pune = stocked.repository.get_warehouse("PNQ1")
    with pytest.raises(UnknownProductError):
        pune["JAR-750"]
    with pytest.raises(UnknownProductError):
        pune.product("JAR-750")
    with pytest.raises(DuplicateProductError):
        pune.add_product(pune.product("TEA-500"))
    with pytest.raises(InsufficientStockError):
        stocked.ship("PNQ1", "TEA-500", 41)


def test_values_and_low_stock(stocked: InventoryService) -> None:
    """Stock value and the low-stock list."""
    pune = stocked.repository.get_warehouse("PNQ1")
    assert pune.stock_value() == Money("9600")
    assert [product.sku for product in pune.low_stock()] == ["MUG-02"]
    assert stocked.total_value() == Money("9600")


def test_repository_queries(stocked: InventoryService) -> None:
    """Listing, lookup errors and movement filtering."""
    repository = stocked.repository
    assert [warehouse.code for warehouse in repository.list_warehouses()] == ["BLR1", "PNQ1"]
    with pytest.raises(UnknownWarehouseError):
        repository.get_warehouse("NOPE")
    stocked.receive("PNQ1", "MUG-02", 3)
    assert len(repository.movements()) == 2
    assert [movement.sku for movement in repository.movements(sku="MUG-02")] == ["MUG-02"]


def test_event_bus_dispatch() -> None:
    """Handlers run for their exact event class only."""
    bus = EventBus()
    received: list[object] = []
    bus.subscribe(LowStockAlert, received.append)
    alert = LowStockAlert("PNQ1", "TEA-500", 3, 10)
    assert bus.publish(alert) == 1 and received == [alert]
    assert bus.publish(StockChanged("PNQ1", "TEA-500", 5, 3, MovementType.SHIPPED)) == 0


def test_service_movements(stocked: InventoryService) -> None:
    """Receive, ship, return and adjust all update stock and are recorded."""
    assert stocked.ship("PNQ1", "TEA-500", 5) == 35
    assert stocked.accept_return("PNQ1", "TEA-500", 2) == 37
    assert stocked.adjust("PNQ1", "TEA-500", -4, "damaged") == 33
    assert stocked.adjust("PNQ1", "TEA-500", 1, "recount") == 34
    times = {movement.occurred_at for movement in stocked.repository.movements()}
    assert times == {datetime(2026, 11, 7, 9, 30)}


def test_low_stock_alert_only_when_crossing(stocked: InventoryService) -> None:
    """One alert when the level is crossed, none for later sales."""
    alerts: list[LowStockAlert] = []
    changes: list[StockChanged] = []
    stocked.events.subscribe(LowStockAlert, alerts.append)
    stocked.events.subscribe(StockChanged, changes.append)
    stocked.ship("PNQ1", "TEA-500", 25)  # 15 left: above the level
    stocked.ship("PNQ1", "TEA-500", 6)  # 9 left: crosses 10
    stocked.ship("PNQ1", "TEA-500", 1)  # 8 left: already low
    assert [(alert.sku, alert.quantity) for alert in alerts] == [("TEA-500", 9)]
    assert [change.new_quantity for change in changes] == [15, 9, 8]


def test_transfer(stocked: InventoryService) -> None:
    """Transfers check stock first and register the product at the destination."""
    with pytest.raises(InsufficientStockError):
        stocked.transfer("PNQ1", "BLR1", "TEA-500", 50)
    assert "TEA-500" not in stocked.repository.get_warehouse("BLR1")
    stocked.transfer("PNQ1", "BLR1", "TEA-500", 10)
    stocked.transfer("PNQ1", "BLR1", "TEA-500", 5)  # destination already carries it
    pune = stocked.repository.get_warehouse("PNQ1")
    bengaluru = stocked.repository.get_warehouse("BLR1")
    assert (pune["TEA-500"], bengaluru["TEA-500"]) == (25, 15)


def test_stock_report(stocked: InventoryService) -> None:
    """The report lists each product, flags low stock and ends with the total."""
    assert stocked.stock_report("PNQ1") == [
        "PNQ1 (Pune)",
        "MUG-02       0  LOW",
        "TEA-500     40",
        "total INR 9,600.00",
    ]


def test_repository_protocol() -> None:
    """The in-memory repository satisfies the Protocol structurally."""
    assert isinstance(InMemoryInventoryRepository(), InventoryRepository)


INVENTORY_TESTS = [
    stocked,
    test_product_validation,
    test_product_requires_money,
    test_movement_directions_and_deltas,
    test_movement_validation,
    test_error_payloads,
    test_warehouse_container_protocol,
    test_warehouse_errors,
    test_values_and_low_stock,
    test_repository_queries,
    test_event_bus_dispatch,
    test_service_movements,
    test_low_stock_alert_only_when_crossing,
    test_transfer,
    test_stock_report,
    test_repository_protocol,
]


def check_lab_4_3() -> None:
    """The notebook's Lab 4.3 check cells, verbatim."""

    def parametrized_with_ids(test: object, minimum_cases: int = 4) -> bool:
        """Does test carry a parametrize mark with enough cases, each with a readable id?"""
        for mark in getattr(test, "pytestmark", []):
            if mark.name != "parametrize" or len(mark.args) < 2:
                continue
            cases = list(mark.args[1])
            explicit_ids = "ids" in mark.kwargs or all(getattr(case, "id", None) for case in cases)
            if len(cases) >= minimum_cases and explicit_ids:
                return True
        return False

    MONEY_MUTANTS = {
        "half-even rounding": (
            "shop/money.py",
            "rounding=ROUND_HALF_UP",
            'rounding="ROUND_HALF_EVEN"',
        ),
        "no currency check": (
            "shop/money.py",
            "if other._currency != self._currency:",
            "if False:",
        ),
        "floats accepted": ("shop/money.py", "if isinstance(amount, float):", "if False:"),
        "reversed subtraction": (
            "shop/money.py",
            "Money(self._amount - other._amount",
            "Money(other._amount - self._amount",
        ),
    }
    money_source = lab_test_source(MONEY_TESTS)
    run_checks(
        [
            ("tests pass on the real Money", lambda: run_lab_tests(money_source).green, True),
            (
                "test_money_rounding: 4+ cases with ids",
                lambda: parametrized_with_ids(MONEY_TESTS[0]),
                True,
            ),
            (
                "test_money_arithmetic: 4+ cases with ids",
                lambda: parametrized_with_ids(MONEY_TESTS[1]),
                True,
            ),
            *[
                (
                    f"catches: {name}",
                    lambda mutation=mutation: catches(money_source, mutation),
                    True,
                )
                for name, mutation in MONEY_MUTANTS.items()
            ],
        ]
    )

    FIXTURE_CHECKS = textwrap.dedent("""
    SEEN_CATALOGUES = []


    def test_catalogue_contents(catalogue):
        assert sorted(catalogue) == ["JAR-750", "MUG-02", "TEA-500"]
        tea = catalogue["TEA-500"]
        assert (tea.unit_price, tea.reorder_level) == (Money("240"), 10)
        mug, jar = catalogue["MUG-02"], catalogue["JAR-750"]
        assert (mug.unit_price, jar.reorder_level) == (Money("199"), 3)
        SEEN_CATALOGUES.append(catalogue)


    def test_catalogue_is_session_scoped(catalogue):
        assert SEEN_CATALOGUES and SEEN_CATALOGUES[0] is catalogue


    def test_repository_warehouses(repository):
        places = [(w.code, w.city) for w in repository.list_warehouses()]
        assert places == [("BLR1", "Bengaluru"), ("PNQ1", "Pune")]
        assert all(len(w) == 3 and not w for w in repository.list_warehouses())


    def test_clock_is_fixed(clock):
        assert clock() == datetime(2026, 11, 7, 9, 30) == clock()


    def test_make_service_receives_stock(make_service, clock):
        service = make_service({"TEA-500": 40, "MUG-02": 6})
        pune = service.repository.get_warehouse("PNQ1")
        assert (pune["TEA-500"], pune["MUG-02"], pune["JAR-750"]) == (40, 6, 0)
        assert {movement.occurred_at for movement in service.repository.movements()} == {clock()}


    def test_isolation_part_1(make_service):
        service = make_service({"TEA-500": 5})
        service.ship("PNQ1", "TEA-500", 2)
        assert service.repository.get_warehouse("PNQ1")["TEA-500"] == 3


    def test_isolation_part_2(repository):
        assert repository.get_warehouse("PNQ1")["TEA-500"] == 0 and repository.movements() == []


    def test_factory_shares_the_repository(make_service, repository):
        first, second = make_service({"TEA-500": 40}), make_service({"TEA-500": 2})
        assert first.repository is repository is second.repository
        assert repository.get_warehouse("PNQ1")["TEA-500"] == 42


    def test_each_service_has_its_own_event_bus(make_service):
        first, second = make_service(), make_service()
        alerts = []
        first.events.subscribe(LowStockAlert, alerts.append)
        first.receive("PNQ1", "MUG-02", 6)
        first.ship("PNQ1", "MUG-02", 2)
        assert first.events is not second.events
        assert [(alert.sku, alert.quantity) for alert in alerts] == [("MUG-02", 4)]
    """)  # dedent: the solutions file runs this cell inside a function

    def fixture_outcome(test_name: str) -> str | None:
        """Outcome of one hidden test run against the learner's fixtures."""
        return run_lab_tests(
            LAB_TEST_PRELUDE + FIXTURE_CHECKS, lab_test_source(INVENTORY_FIXTURES)
        ).outcomes.get(test_name)

    run_checks(
        [
            (
                name.removeprefix("test_").replace("_", " "),
                lambda name=name: fixture_outcome(name),
                "passed",
            )
            for name in re.findall(r"^def (test_\w+)", FIXTURE_CHECKS, re.MULTILINE)
        ]
    )

    RATE_MUTANTS = {
        "missing timeout": ("shop/rates.py", ", timeout=5.0\n", "\n"),
        "wrong query parameter": ("shop/rates.py", '"symbols": quote', '"symbol": quote'),
        "Decimal(float)": (
            "shop/rates.py",
            'Decimal(str(response.json()["rates"][quote]))',
            'Decimal(response.json()["rates"][quote])',
        ),
        "no status check": ("shop/rates.py", "if response.status_code != 200:", "if False:"),
        "service called for same currency": ("shop/rates.py", "if base == quote:", "if False:"),
    }
    rate_source = lab_test_source(RATE_TESTS)
    run_checks(
        [
            ("tests pass on the real client", lambda: run_lab_tests(rate_source).green, True),
            (
                "tests use unittest.mock",
                lambda: bool(
                    re.search(r"\bmock\.|Mock\(|patch", "".join(map(source_of, RATE_TESTS)))
                ),
                True,
            ),
            *[
                (f"catches: {name}", lambda mutation=mutation: catches(rate_source, mutation), True)
                for name, mutation in RATE_MUTANTS.items()
            ],
        ]
    )

    BILL_MUTANTS = {
        "leftover to the last people": (
            "shop/billing.py",
            "(1 if index < leftover_paise else 0)",
            "(1 if index >= people_count - leftover_paise else 0)",
        ),
        "leftover dropped": ("shop/billing.py", "(1 if index < leftover_paise else 0)", "0"),
        "zero people accepted": ("shop/billing.py", "if people_count < 1:", "if people_count < 0:"),
        "float conversion": (
            "shop/billing.py",
            "int(Decimal(total_amount).quantize(PAISE, rounding=ROUND_HALF_UP) * 100)",
            "int(float(total_amount) * 100)",
        ),
    }
    bill_source = lab_test_source(SPLIT_BILL_TESTS)
    hypothesis_ready = importlib.util.find_spec("hypothesis") is not None
    if not hypothesis_ready:
        print("SKIP: hypothesis is not installed (uv add --dev hypothesis)")
    run_checks(
        [
            (
                "every test uses @given",
                lambda: all(
                    getattr(test, "is_hypothesis_test", False) for test in SPLIT_BILL_TESTS
                ),
                True,
            ),
            ("tests pass on the real split_bill", lambda: run_lab_tests(bill_source).green, True),
            *[
                (f"catches: {name}", lambda mutation=mutation: catches(bill_source, mutation), True)
                for name, mutation in BILL_MUTANTS.items()
            ],
        ]
    )

    def json_log_lines() -> list[dict[str, object]]:
        """Apply the learner's config, emit six records, return the parsed JSON lines."""
        stream = io.StringIO()
        logging.config.dictConfig(build_logging_config(stream))
        orders, payments = logging.getLogger("shop.orders"), logging.getLogger("shop.payments")
        try:
            orders.debug("cart recalculated")
            orders.info("order %s placed", 7, extra={"order_id": 7, "customer": "Asha"})
            orders.info("GET /health 200")
            payments.info("payment authorised")
            payments.warning("payment retry %d/3", 2)
            try:
                _ = 1 / 0
            except ZeroDivisionError:
                orders.exception("charging order %s failed", 8)
        finally:
            for name in ("shop", "shop.orders", "shop.payments"):
                logger = logging.getLogger(name)
                for handler in logger.handlers[:]:
                    logger.removeHandler(handler)
                logger.setLevel(logging.NOTSET)
                logger.propagate = True
        return [json.loads(line) for line in stream.getvalue().splitlines()]

    STANDARD_KEYS = set(vars(logging.makeLogRecord({}))) - {"message"}
    UTC_ISO = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?\+00:00"
    run_checks(
        [
            (
                "three lines (DEBUG, /health and payments INFO dropped)",
                lambda: len(json_log_lines()),
                3,
            ),
            (
                "line 1 fields",
                lambda: {
                    key: json_log_lines()[0].get(key) for key in ("level", "logger", "message")
                },
                {"level": "INFO", "logger": "shop.orders", "message": "order 7 placed"},
            ),
            (
                "line 1 extras",
                lambda: (json_log_lines()[0].get("order_id"), json_log_lines()[0].get("customer")),
                (7, "Asha"),
            ),
            (
                "time is UTC ISO 8601",
                lambda: all(
                    re.fullmatch(UTC_ISO, str(line.get("time"))) is not None
                    for line in json_log_lines()
                ),
                True,
            ),
            (
                "no standard attributes leak",
                lambda: sorted(STANDARD_KEYS & set(json_log_lines()[0])),
                [],
            ),
            (
                "no exception key without exc_info",
                lambda: "exception" in json_log_lines()[0],
                False,
            ),
            (
                "line 2 from shop.payments",
                lambda: (
                    json_log_lines()[1].get("logger"),
                    json_log_lines()[1].get("message"),
                    json_log_lines()[1].get("level"),
                ),
                ("shop.payments", "payment retry 2/3", "WARNING"),
            ),
            (
                "line 3 has the traceback",
                lambda: (
                    json_log_lines()[2].get("level"),
                    "ZeroDivisionError" in str(json_log_lines()[2].get("exception")),
                ),
                ("ERROR", True),
            ),
        ]
    )

    def lab_pdb_session(commands: list[str]) -> list[tuple[str, str]]:
        """Run `python -m pdb coupon.py` with commands; return (command, its output) pairs."""
        completed = subprocess.run(
            [sys.executable, "-m", "pdb", "coupon.py"],
            cwd=COUPON_DIR,
            input="\n".join(commands) + "\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=60,
            env={**os.environ, "PYTHON_COLORS": "0", "NO_COLOR": "1"},
        )
        transcript = completed.stdout.replace(str(COUPON_DIR), "<lab>").replace(
            sys.base_prefix, "<python>"
        )
        pieces = transcript.split("(Pdb) ")
        return [
            (command, pieces[index + 1] if index + 1 < len(pieces) else "")
            for index, command in enumerate(commands)
        ]

    def run_fixed_coupon(line_number: int, fixed_line: str) -> str:
        """Replace one line of coupon.py (keeping its indentation) and run the result."""
        lines = (COUPON_DIR / "coupon.py").read_text().splitlines()
        original = lines[line_number - 1]
        lines[line_number - 1] = (
            original[: len(original) - len(original.lstrip())] + fixed_line.strip()
        )
        (COUPON_DIR / "coupon_fixed.py").write_text("\n".join(lines) + "\n")
        completed = subprocess.run(
            [sys.executable, "coupon_fixed.py"],
            cwd=COUPON_DIR,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return (completed.stdout + completed.stderr).strip()

    def printed(session: list[tuple[str, str]], name: str, value: str) -> bool:
        """Did a p/pp/display command mentioning name print value?"""
        return any(
            re.match(rf"(p|pp|print|display)\b.*\b{name}\b", command.strip())
            and re.search(rf"\b{value}\b", output)
            for command, output in session
        )

    run_checks(
        [
            (
                "stopped inside apply_coupon",
                lambda: any(
                    "apply_coupon()" in output
                    for _, output in lab_pdb_session(coupon_debug_commands())
                ),
                True,
            ),
            (
                "printed percent (10)",
                lambda: printed(lab_pdb_session(coupon_debug_commands()), "percent", "10"),
                True,
            ),
            (
                "printed discount (67900)",
                lambda: printed(lab_pdb_session(coupon_debug_commands()), "discount", "67900"),
                True,
            ),
            (
                "showed the call stack",
                lambda: any(
                    command.strip() in {"w", "where", "bt"} and "checkout()" in output
                    for command, output in lab_pdb_session(coupon_debug_commands())
                ),
                True,
            ),
            ("bug line", lambda: coupon_bug_report()[0], 6),
            ("fixed script prints 61110", lambda: run_fixed_coupon(*coupon_bug_report()), "61110"),
        ]
    )
    try:
        for command, output in lab_pdb_session(coupon_debug_commands()):
            print(
                f"(Pdb) {command}\n{textwrap.indent(output.rstrip(), '      ')}"
                if output.strip()
                else f"(Pdb) {command}"
            )
    except Exception as error:  # the transcript must never stop Run All
        print(f"(no session yet: {type(error).__name__})")

    INVENTORY_MUTANTS = {
        "alert on every low sale": (
            "shop/inventory.py",
            "if old_quantity > reorder_level >= new_quantity:",
            "if reorder_level >= new_quantity:",
        ),
        "adjustment sign ignored": (
            "shop/inventory.py",
            "if self.movement_type is MovementType.ADJUSTED:\n                return self.quantity",
            "if self.movement_type is MovementType.ADJUSTED:\n"
            "                return abs(self.quantity)",
        ),
    }
    inventory_source = lab_test_source(INVENTORY_TESTS)

    def inventory_coverage_run() -> LabRun:
        return run_lab_tests(inventory_source, coverage_target="shop.inventory")

    run_checks(
        [
            (
                "at least 8 tests",
                lambda: (
                    len(
                        [
                            test
                            for test in INVENTORY_TESTS
                            if getattr(test, "__name__", "").startswith("test_")
                        ]
                    )
                    >= 8
                ),
                True,
            ),
            ("all tests pass", lambda: inventory_coverage_run().green, True),
            (
                "branch coverage >= 90%",
                lambda: (inventory_coverage_run().coverage_percent or 0) >= 90,
                True,
            ),
            *[
                (
                    f"catches: {name}",
                    lambda mutation=mutation: catches(inventory_source, mutation),
                    True,
                )
                for name, mutation in INVENTORY_MUTANTS.items()
            ],
        ]
    )
    try:
        print(f"branch coverage of shop/inventory.py: {inventory_coverage_run().coverage_percent}%")
    except Exception as error:  # never stop Run All
        print(f"coverage not measured: {type(error).__name__}")


# ===============================================================================================
# Lab 4.4 — helpers copied from the notebook's lab setup cell
# ===============================================================================================

LAB44_DIR = find_repo_root() / "notebooks" / "_scratch" / "unit44" / "lab"
LAB44_DIR.mkdir(parents=True, exist_ok=True)
MIB = 1024 * 1024


# Lab 4.4 solutions -----------------------------------------------------------------------------

# Exercise 1 ------------------------------------------------------------------------------------


def find_large_files(root: Path, min_size_mb: float) -> list[tuple[str, int]]:
    """Files of at least min_size_mb MiB under root, largest first."""
    if not root.is_dir():
        raise NotADirectoryError(f"{root} is not a directory")
    threshold = min_size_mb * 1024 * 1024
    found = [
        (path.relative_to(root).as_posix(), size)
        for path in root.rglob("*")
        if not path.is_symlink() and path.is_file() and (size := path.stat().st_size) >= threshold
    ]
    return sorted(found, key=lambda item: (-item[1], item[0]))


# Exercise 2 ------------------------------------------------------------------------------------

NGINX_LOG_PATTERN = re.compile(
    r"""
    ^(?P<ip>\S+)                         # client address
    \ \S+                                # identd (always '-')
    \ (?P<user>\S+)                      # authenticated user or '-'
    \ \[(?P<time>[^\]]+)\]               # [07/Nov/2026:09:30:00 +0530]
    \ "(?P<method>[A-Z]+)                # "GET
    \ (?P<path>\S+)                      #  /products/TEA-500?ref=home
    \ (?P<protocol>HTTP/[\d.]+)"         #  HTTP/1.1"
    \ (?P<status>\d{3})                  # 200
    \ (?P<size>\d+|-)                    # bytes sent or '-'
    \ "(?P<referrer>[^"]*)"              # "https://..." or "-"
    \ "(?P<user_agent>[^"]*)"$           # "Mozilla/5.0 ..."
    """,
    re.VERBOSE,
)


def parse_access_line(line: str) -> dict[str, str | int | None] | None:
    """One combined-format log line -> dict of fields, or None."""
    log_match = NGINX_LOG_PATTERN.match(line)
    if log_match is None:
        return None
    fields: dict[str, str | int | None] = dict(log_match.groupdict())
    fields["status"] = int(log_match["status"])
    fields["size"] = 0 if log_match["size"] == "-" else int(log_match["size"])
    for key in ("user", "referrer"):
        if fields[key] == "-":
            fields[key] = None
    return fields


# Exercise 3 ------------------------------------------------------------------------------------


def ist_to_utc(local_text: str) -> str:
    """'YYYY-MM-DD HH:MM' in IST -> ISO 8601 in UTC."""
    local = datetime.strptime(local_text, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("Asia/Kolkata"))
    return local.astimezone(UTC).isoformat()


def utc_to_zone(utc_text: str, zone_name: str) -> str:
    """ISO 8601 with offset -> ISO 8601 in zone_name."""
    moment = datetime.fromisoformat(utc_text)
    if moment.tzinfo is None:
        raise ValueError(f"{utc_text!r} has no UTC offset")
    return moment.astimezone(ZoneInfo(zone_name)).isoformat()


def local_to_utc(local_text: str, zone_name: str) -> str:
    """'YYYY-MM-DD HH:MM' wall-clock time in zone_name -> ISO 8601 in UTC."""
    zone = ZoneInfo(zone_name)
    wall_clock = datetime.strptime(local_text, "%Y-%m-%d %H:%M")
    local = wall_clock.replace(tzinfo=zone, fold=0)  # fold=0: the earlier of two ambiguous times
    round_trip = local.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
    if round_trip != wall_clock:
        raise ValueError(f"{local_text} does not exist in {zone_name} (skipped by a DST change)")
    return local.astimezone(UTC).isoformat()


# Exercise 4 ------------------------------------------------------------------------------------


def sign_webhook(secret: bytes, timestamp: int, body: bytes) -> str:
    """'sha256=<hex>' signature of timestamp + '.' + body."""
    digest = hmac.new(secret, f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_webhook(
    secret: bytes,
    timestamp: int,
    body: bytes,
    signature: str,
    now: int,
    tolerance_seconds: int = 300,
) -> bool:
    """True if the signature is valid and the timestamp is fresh."""
    if abs(now - timestamp) > tolerance_seconds:
        return False
    return hmac.compare_digest(sign_webhook(secret, timestamp, body), signature)


# Exercise 5 ------------------------------------------------------------------------------------


def top_k(scores: Iterable[tuple[str, int]], k: int) -> list[tuple[str, int]]:
    """The k highest (name, score) pairs, highest first, ties by name."""
    if k <= 0:
        return []
    # nsmallest keeps a heap of only k items: (-score, name) puts high scores, then A-Z, first.
    return heapq.nsmallest(k, scores, key=lambda pair: (-pair[1], pair[0]))


# Exercise 6 ------------------------------------------------------------------------------------


def build_batches(steps: Mapping[str, Iterable[str]]) -> list[list[str]]:
    """Parallel batches of steps, each sorted alphabetically."""
    sorter = graphlib.TopologicalSorter({step: list(needs) for step, needs in steps.items()})
    try:
        sorter.prepare()
    except graphlib.CycleError as error:
        raise ValueError(f"cycle: {' -> '.join(error.args[1])}") from error
    batches = []
    while sorter.is_active():
        ready = sorted(sorter.get_ready())
        batches.append(ready)
        sorter.done(*ready)
    return batches


def build_order(steps: Mapping[str, Iterable[str]]) -> list[str]:
    """All steps in a valid order (the batches, concatenated)."""
    return [step for batch in build_batches(steps) for step in batch]


# Exercise 7 ------------------------------------------------------------------------------------


def _organizer_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="organize-files", exit_on_error=False)
    commands = parser.add_subparsers(dest="command", required=True)
    organize = commands.add_parser("organize", help="move files into subfolders")
    organize.add_argument("folder", type=Path)
    organize.add_argument("--by", choices=["extension", "month"], default="extension")
    organize.add_argument("--dry-run", action="store_true")
    summary = commands.add_parser("summary", help="count files per extension")
    summary.add_argument("folder", type=Path)
    return parser


def _extension_of(path: Path) -> str:
    return path.suffix.lower().removeprefix(".") or "no_extension"


def _month_of(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).strftime("%Y-%m")


def organizer_main(argv: list[str]) -> int:
    """The file-organizer CLI; returns the exit code."""
    try:
        arguments = _organizer_parser().parse_args(argv)
    except argparse.ArgumentError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except SystemExit as exit_request:  # errors argparse still reports by exiting
        return exit_request.code if isinstance(exit_request.code, int) else 2
    folder: Path = arguments.folder
    if not folder.is_dir():
        print(f"error: {folder} is not a directory", file=sys.stderr)
        return 2
    files = sorted(
        (path for path in folder.iterdir() if path.is_file() and not path.name.startswith(".")),
        key=lambda path: path.name,
    )
    if arguments.command == "summary":
        counts: dict[str, int] = {}
        for path in files:
            counts[_extension_of(path)] = counts.get(_extension_of(path), 0) + 1
        for extension in sorted(counts):
            print(f"{extension}: {counts[extension]}")
        return 0
    group_of = _month_of if arguments.by == "month" else _extension_of
    verb = "would move" if arguments.dry_run else "moved"
    for path in files:
        target = folder / group_of(path) / path.name
        if not arguments.dry_run:
            target.parent.mkdir(exist_ok=True)
            path.rename(target)
        print(f"{verb} {path.name} -> {target.relative_to(folder).as_posix()}")
    print(f"{len(files)} files {'would be moved' if arguments.dry_run else 'moved'}")
    return 0


def check_lab_4_4() -> None:
    """The notebook's Lab 4.4 check cells, verbatim."""

    def make_large_file_tree() -> Path:
        """big.iso 5 MiB, two 2.5 MiB logs, edge.bin exactly 1 MiB, small files, a symlink."""
        root = LAB44_DIR / "large_files"
        shutil.rmtree(root, ignore_errors=True)
        sizes = {
            "big.iso": 5 * MIB,
            "logs/app.log": 5 * MIB // 2,
            "logs/old/app.1.log": 5 * MIB // 2,
            "edge.bin": MIB,
            "notes.txt": 10,
            "logs/old/tiny.gz": 2048,
        }
        for relative_path, size in sizes.items():
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as handle:
                handle.truncate(size)
        (root / "big-link.iso").symlink_to("big.iso")
        return root

    large_root = make_large_file_tree()
    run_checks(
        [
            (
                "at least 1 MiB",
                lambda: find_large_files(large_root, 1),
                [
                    ("big.iso", 5 * MIB),
                    ("logs/app.log", 5 * MIB // 2),
                    ("logs/old/app.1.log", 5 * MIB // 2),
                    ("edge.bin", MIB),
                ],
            ),
            ("at least 3 MiB", lambda: find_large_files(large_root, 3), [("big.iso", 5 * MIB)]),
            (
                "float threshold",
                lambda: [path for path, _ in find_large_files(large_root, 2.5)],
                ["big.iso", "logs/app.log", "logs/old/app.1.log"],
            ),
            ("nothing that large", lambda: find_large_files(large_root, 10), []),
            (
                "symlink skipped",
                lambda: "big-link.iso" in [path for path, _ in find_large_files(large_root, 0)],
                False,
            ),
            (
                "root is a file",
                lambda: raised_message(lambda: find_large_files(large_root / "notes.txt", 1)).split(
                    ":"
                )[0],
                "NotADirectoryError",
            ),
        ]
    )

    GET_LINE = (
        '203.0.113.7 - - [07/Nov/2026:09:30:00 +0530] "GET /products/TEA-500?ref=home HTTP/1.1" '
        '200 5120 "https://shop.example.com/" "Mozilla/5.0 (X11; Linux x86_64)"'
    )
    POST_LINE = (
        '198.51.100.23 - asha [07/Nov/2026:09:31:12 +0530] "POST /api/orders HTTP/2.0" '
        '201 - "-" "curl/8.10.1"'
    )
    LOG_GROUPS = {
        "ip",
        "user",
        "time",
        "method",
        "path",
        "protocol",
        "status",
        "size",
        "referrer",
        "user_agent",
    }
    run_checks(
        [
            ("compiled with re.VERBOSE", lambda: bool(NGINX_LOG_PATTERN.flags & re.VERBOSE), True),
            ("named groups", lambda: set(NGINX_LOG_PATTERN.groupindex), LOG_GROUPS),
            (
                "GET line",
                lambda: parse_access_line(GET_LINE),
                {
                    "ip": "203.0.113.7",
                    "user": None,
                    "time": "07/Nov/2026:09:30:00 +0530",
                    "method": "GET",
                    "path": "/products/TEA-500?ref=home",
                    "protocol": "HTTP/1.1",
                    "status": 200,
                    "size": 5120,
                    "referrer": "https://shop.example.com/",
                    "user_agent": "Mozilla/5.0 (X11; Linux x86_64)",
                },
            ),
            (
                "POST line: user, size '-', referrer '-'",
                lambda: {
                    key: parse_access_line(POST_LINE)[key]
                    for key in ("user", "method", "status", "size", "referrer", "user_agent")
                },
                {
                    "user": "asha",
                    "method": "POST",
                    "status": 201,
                    "size": 0,
                    "referrer": None,
                    "user_agent": "curl/8.10.1",
                },
            ),
            ("malformed line", lambda: parse_access_line("GET /index.html 200"), None),
            (
                "status must be 3 digits",
                lambda: parse_access_line(GET_LINE.replace(" 200 ", " 20 ")),
                None,
            ),
        ]
    )

    run_checks(
        [
            ("IST afternoon", lambda: ist_to_utc("2026-11-07 15:00"), "2026-11-07T09:30:00+00:00"),
            (
                "IST crosses midnight",
                lambda: ist_to_utc("2026-01-01 03:00"),
                "2025-12-31T21:30:00+00:00",
            ),
            (
                "UTC -> IST",
                lambda: utc_to_zone("2026-11-07T09:30:00+00:00", "Asia/Kolkata"),
                "2026-11-07T15:00:00+05:30",
            ),
            (
                "UTC -> New York before DST",
                lambda: utc_to_zone("2026-03-06T14:00:00+00:00", "America/New_York"),
                "2026-03-06T09:00:00-05:00",
            ),
            (
                "UTC -> New York after DST",
                lambda: utc_to_zone("2026-03-09T14:00:00+00:00", "America/New_York"),
                "2026-03-09T10:00:00-04:00",
            ),
            (
                "IST input -> London",
                lambda: utc_to_zone("2026-07-01T19:30:00+05:30", "Europe/London"),
                "2026-07-01T15:00:00+01:00",
            ),
            (
                "naive input rejected",
                lambda: raised_message(
                    lambda: utc_to_zone("2026-11-07T09:30:00", "Asia/Kolkata")
                ).split(":")[0],
                "ValueError",
            ),
            (
                "non-existent New York time",
                lambda: raised_message(
                    lambda: local_to_utc("2026-03-08 02:30", "America/New_York")
                ).split(":")[0],
                "ValueError",
            ),
            (
                "ambiguous New York time: earlier",
                lambda: local_to_utc("2026-11-01 01:30", "America/New_York"),
                "2026-11-01T05:30:00+00:00",
            ),
            (
                "London summer time",
                lambda: local_to_utc("2026-07-01 09:00", "Europe/London"),
                "2026-07-01T08:00:00+00:00",
            ),
        ]
    )

    SECRET, OTHER_SECRET = b"whsec_lab_secret", b"whsec_attacker_guess"
    BODY = b'{"event": "payment.captured", "order_id": 7}'
    SENT_AT = int(datetime(2026, 11, 7, 9, 30, tzinfo=UTC).timestamp())
    EXPECTED_SIGNATURE = (
        "sha256=" + hmac.new(SECRET, f"{SENT_AT}.".encode() + BODY, hashlib.sha256).hexdigest()
    )
    run_checks(
        [
            (
                "signature format and value",
                lambda: sign_webhook(SECRET, SENT_AT, BODY),
                EXPECTED_SIGNATURE,
            ),
            (
                "valid webhook",
                lambda: verify_webhook(SECRET, SENT_AT, BODY, EXPECTED_SIGNATURE, SENT_AT + 30),
                True,
            ),
            (
                "tampered body",
                lambda: verify_webhook(
                    SECRET, SENT_AT, BODY.replace(b"7", b"8"), EXPECTED_SIGNATURE, SENT_AT
                ),
                False,
            ),
            (
                "wrong secret",
                lambda: verify_webhook(OTHER_SECRET, SENT_AT, BODY, EXPECTED_SIGNATURE, SENT_AT),
                False,
            ),
            (
                "timestamp is signed too",
                lambda: verify_webhook(SECRET, SENT_AT + 1, BODY, EXPECTED_SIGNATURE, SENT_AT),
                False,
            ),
            (
                "stale (replayed) webhook",
                lambda: verify_webhook(SECRET, SENT_AT, BODY, EXPECTED_SIGNATURE, SENT_AT + 301),
                False,
            ),
            (
                "from the future",
                lambda: verify_webhook(SECRET, SENT_AT, BODY, EXPECTED_SIGNATURE, SENT_AT - 301),
                False,
            ),
            (
                "custom tolerance",
                lambda: verify_webhook(
                    SECRET, SENT_AT, BODY, EXPECTED_SIGNATURE, SENT_AT + 600, tolerance_seconds=900
                ),
                True,
            ),
            (
                "uses hmac.compare_digest",
                lambda: "compare_digest" in inspect.getsource(verify_webhook),
                True,
            ),
        ]
    )

    LEADERBOARD = [("ravi", 75), ("meera", 90), ("john", 60), ("asha", 90), ("fatima", 82)]

    def big_stream(count: int = 100_000):
        """A seeded generator of (name, score) pairs; never materialized as a list."""
        generator = random.Random(44)
        for number in range(count):
            yield f"customer-{number:06d}", generator.randint(0, 1_000_000)

    def expected_top(pairs: list[tuple[str, int]], k: int) -> list[tuple[str, int]]:
        return sorted(pairs, key=lambda pair: (-pair[1], pair[0]))[:k]

    run_checks(
        [
            (
                "top 3 with a tie",
                lambda: top_k(LEADERBOARD, 3),
                [("asha", 90), ("meera", 90), ("fatima", 82)],
            ),
            ("k = 1", lambda: top_k(LEADERBOARD, 1), [("asha", 90)]),
            (
                "k larger than the input",
                lambda: top_k(LEADERBOARD, 10),
                expected_top(LEADERBOARD, 10),
            ),
            ("k = 0", lambda: top_k(LEADERBOARD, 0), []),
            ("generator input", lambda: top_k(iter(LEADERBOARD), 2), [("asha", 90), ("meera", 90)]),
            (
                "100,000-item stream",
                lambda: top_k(big_stream(), 5),
                expected_top(list(big_stream()), 5),
            ),
            ("uses heapq", lambda: "heapq" in inspect.getsource(top_k), True),
        ]
    )

    PIPELINE = {
        "package": ["test", "lint", "docs"],
        "test": ["compile"],
        "lint": [],
        "docs": ["fetch"],
        "compile": ["fetch"],
    }
    run_checks(
        [
            (
                "batches",
                lambda: build_batches(PIPELINE),
                [["fetch", "lint"], ["compile", "docs"], ["test"], ["package"]],
            ),
            (
                "order",
                lambda: build_order(PIPELINE),
                ["fetch", "lint", "compile", "docs", "test", "package"],
            ),
            ("implicit leaf step", lambda: build_order({"deploy": ["build"]}), ["build", "deploy"]),
            (
                "independent steps sorted",
                lambda: build_batches({"b": [], "c": [], "a": []}),
                [["a", "b", "c"]],
            ),
            ("empty", lambda: build_order({}), []),
            (
                "cycle message",
                lambda: (
                    re.fullmatch(
                        r"ValueError: cycle: \w+( -> \w+)+",
                        raised_message(
                            lambda: build_order({"migrate": ["seed"], "seed": ["migrate"]})
                        ),
                    )
                    is not None
                ),
                True,
            ),
            (
                "cycle in batches too",
                lambda: raised_message(
                    lambda: build_batches({"a": ["b"], "b": ["c"], "c": ["a"]})
                ).split(":")[0],
                "ValueError",
            ),
        ]
    )

    ORGANIZER_FILES = {
        "Invoice.PDF": (2026, 10, 30),
        "photo.jpg": (2026, 11, 2),
        "notes.txt": (2026, 11, 5),
        "README": (2026, 9, 1),
        "data.csv": (2026, 11, 6),
        ".hidden": (2026, 11, 7),
    }

    def make_messy_folder() -> Path:
        """Six files (one hidden) with fixed modification times, plus a subfolder."""
        folder = LAB44_DIR / "messy"
        shutil.rmtree(folder, ignore_errors=True)
        (folder / "existing").mkdir(parents=True)
        (folder / "existing" / "keep.txt").write_text("untouched", encoding="utf-8")
        for name, (year, month, day) in ORGANIZER_FILES.items():
            (folder / name).write_text(name, encoding="utf-8")
            stamp = datetime(year, month, day, 12, tzinfo=UTC).timestamp()
            os.utime(folder / name, (stamp, stamp))
        return folder

    def run_organizer(*arguments: str) -> tuple[int, list[str], str]:
        """(exit code, stdout lines, stderr); "messy"/"missing" are folders in the lab folder."""
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = organizer_main(
                [
                    str(LAB44_DIR / argument) if argument in ("messy", "missing") else argument
                    for argument in arguments
                ]
            )
        return exit_code, stdout.getvalue().splitlines(), stderr.getvalue()

    def folder_listing() -> list[str]:
        folder = LAB44_DIR / "messy"
        return sorted(
            path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()
        )

    def dry_run_then_listing() -> tuple[tuple[int, list[str], str], list[str]]:
        make_messy_folder()
        return run_organizer("organize", "messy", "--dry-run"), folder_listing()

    def organize_then_listing(*options: str) -> tuple[list[str], list[str]]:
        make_messy_folder()
        return run_organizer("organize", "messy", *options)[1], folder_listing()

    BY_EXTENSION = [
        "Invoice.PDF -> pdf/Invoice.PDF",
        "README -> no_extension/README",
        "data.csv -> csv/data.csv",
        "notes.txt -> txt/notes.txt",
        "photo.jpg -> jpg/photo.jpg",
    ]
    run_checks(
        [
            (
                "summary",
                lambda: (make_messy_folder(), run_organizer("summary", "messy"))[1],
                (0, ["csv: 1", "jpg: 1", "no_extension: 1", "pdf: 1", "txt: 1"], ""),
            ),
            (
                "dry run output",
                lambda: dry_run_then_listing()[0],
                (
                    0,
                    [f"would move {line}" for line in BY_EXTENSION] + ["5 files would be moved"],
                    "",
                ),
            ),
            (
                "dry run changes nothing",
                lambda: dry_run_then_listing()[1],
                sorted([*ORGANIZER_FILES, "existing/keep.txt"]),
            ),
            (
                "organize by extension",
                lambda: organize_then_listing()[0],
                [f"moved {line}" for line in BY_EXTENSION] + ["5 files moved"],
            ),
            (
                "files really moved",
                lambda: organize_then_listing()[1],
                [
                    ".hidden",
                    "csv/data.csv",
                    "existing/keep.txt",
                    "jpg/photo.jpg",
                    "no_extension/README",
                    "pdf/Invoice.PDF",
                    "txt/notes.txt",
                ],
            ),
            (
                "organize by month",
                lambda: organize_then_listing("--by", "month")[0],
                [
                    "moved Invoice.PDF -> 2026-10/Invoice.PDF",
                    "moved README -> 2026-09/README",
                    "moved data.csv -> 2026-11/data.csv",
                    "moved notes.txt -> 2026-11/notes.txt",
                    "moved photo.jpg -> 2026-11/photo.jpg",
                    "5 files moved",
                ],
            ),
            (
                "missing folder",
                lambda: run_organizer("organize", "missing"),
                (2, [], f"error: {LAB44_DIR / 'missing'} is not a directory\n"),
            ),
            ("bad --by value", lambda: run_organizer("organize", "messy", "--by", "size")[0], 2),
        ]
    )


# ===============================================================================================
# Lab 4.5 — helpers copied from the notebook's lab setup cell
# ===============================================================================================

LAB45_DIR = find_repo_root() / "notebooks" / "_scratch" / "unit45" / "lab"
LAB45_DIR.mkdir(parents=True, exist_ok=True)


# Lab 4.5 solutions -------------------------------------------------------------------------

# Exercise 1 ------------------------------------------------------------------------------------


def tail(path: Path, n: int, chunk_size: int = 4096) -> list[str]:
    """The last n lines of a UTF-8 file, read backwards in binary chunks."""
    if n <= 0:
        return []
    with path.open("rb") as binary_file:
        position = binary_file.seek(0, os.SEEK_END)
        blocks: list[bytes] = []
        newlines = 0
        while position > 0 and newlines <= n:
            step = min(chunk_size, position)
            position -= step
            binary_file.seek(position)
            block = binary_file.read(step)
            blocks.append(block)
            newlines += block.count(b"\n")
    text = b"".join(reversed(blocks)).decode("utf-8")
    return text.splitlines()[-n:]


# Exercise 2 ------------------------------------------------------------------------------------


def write_json(path: Path, data: object) -> None:
    """Atomically replace path with data as pretty-printed JSON."""
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"  # fails before touching disk
    handle, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as temporary_file:
            temporary_file.write(text)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        os.unlink(temporary_name)
        raise


# Exercise 3 ------------------------------------------------------------------------------------


def import_orders(csv_path: Path, connection: sqlite3.Connection) -> int:
    """Import a CSV of orders in one transaction; return the number of rows."""
    connection.execute(
        "CREATE TABLE IF NOT EXISTS orders (order_id INTEGER PRIMARY KEY, customer TEXT,"
        " sku TEXT, quantity INTEGER, unit_price TEXT)"
    )
    rows = []
    with csv_path.open(newline="", encoding="utf-8") as csv_file:
        for record in csv.DictReader(csv_file):
            quantity_text = record["quantity"]
            if not quantity_text.isdigit() or int(quantity_text) < 1:
                raise ValueError(f"order {record['order_id']}: bad quantity {quantity_text!r}")
            rows.append(
                (
                    int(record["order_id"]),
                    record["customer"],
                    record["sku"],
                    int(quantity_text),
                    str(Decimal(record["unit_price"])),
                )
            )
    try:
        with connection:  # one transaction: all rows or none
            connection.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", rows)
    except sqlite3.IntegrityError as error:
        raise ValueError(f"{csv_path.name}: {error}") from error
    return len(rows)


# Exercise 4 ------------------------------------------------------------------------------------


def parse_wav_header(data: bytes) -> dict[str, int | float]:
    """Fields of a canonical 44-byte PCM WAV header."""
    wav_header = struct.Struct("<4sI4s4sIHHIIHH4sI")
    if len(data) < wav_header.size:
        raise ValueError(f"need {wav_header.size} bytes, got {len(data)}")
    (riff, _, wave_id, fmt, _, _, channels, sample_rate, byte_rate, _, bits, data_id, data_size) = (
        wav_header.unpack_from(data)
    )
    if (riff, wave_id, fmt, data_id) != (b"RIFF", b"WAVE", b"fmt ", b"data"):
        raise ValueError("not a canonical PCM WAV header")
    return {
        "channels": channels,
        "sample_rate": sample_rate,
        "bits_per_sample": bits,
        "data_size": data_size,
        "duration_seconds": round(data_size / byte_rate, 3),
    }


# Exercise 5 ------------------------------------------------------------------------------------


class RichJSONEncoder(json.JSONEncoder):
    """JSON for Decimal, datetime/date, UUID and dataclasses."""

    def default(self, value: object) -> object:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, datetime | date):
            return value.isoformat()
        if isinstance(value, uuid.UUID):
            return str(value)
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return {field.name: getattr(value, field.name) for field in dataclasses.fields(value)}
        return super().default(value)


# Exercise 6 ------------------------------------------------------------------------------------


def safe_extract_zip(archive: Path, destination: Path) -> list[str]:
    """Extract archive into destination, refusing any member that escapes it."""
    base = destination.resolve()
    with zipfile.ZipFile(archive) as zip_file:
        members = zip_file.infolist()
        for member in members:
            name = member.filename
            parts = Path(name).parts
            target = (base / name).resolve()
            if Path(name).is_absolute() or ".." in parts or not target.is_relative_to(base):
                raise ValueError(f"unsafe member {name!r}")
        destination.mkdir(parents=True, exist_ok=True)
        zip_file.extractall(destination)
    return sorted(member.filename for member in members if not member.is_dir())


def check_lab_4_5() -> None:
    """The notebook's Lab 4.5 check cells, verbatim."""
    big_log = LAB45_DIR / "big.log"
    big_log.write_text(
        "".join(f"line {number} ₹{number * 10}\n" for number in range(1, 20_001)), encoding="utf-8"
    )
    no_newline = LAB45_DIR / "no_newline.txt"
    no_newline.write_text("first\nsecond\nthird", encoding="utf-8")
    (LAB45_DIR / "empty.txt").write_text("", encoding="utf-8")
    expected_tail = big_log.read_text(encoding="utf-8").splitlines()[-5:]
    run_checks(
        [
            ("last 5 lines", lambda: tail(big_log, 5), expected_tail),
            (
                "tiny chunks (multi-byte split)",
                lambda: tail(big_log, 5, chunk_size=7),
                expected_tail,
            ),
            ("no trailing newline", lambda: tail(no_newline, 2), ["second", "third"]),
            ("n larger than the file", lambda: tail(no_newline, 10), ["first", "second", "third"]),
            ("empty file", lambda: tail(LAB45_DIR / "empty.txt", 3), []),
            ("n = 0", lambda: tail(big_log, 0), []),
            (
                "uses seek, not read_text",
                lambda: (
                    "seek" in inspect.getsource(tail) and "read_text" not in inspect.getsource(tail)
                ),
                True,
            ),
        ]
    )

    json_dir = LAB45_DIR / "json_out"
    shutil.rmtree(json_dir, ignore_errors=True)
    json_dir.mkdir()
    settings_target = json_dir / "settings.json"

    def write_then_read(data: object) -> str:
        write_json(settings_target, data)
        return settings_target.read_text(encoding="utf-8")

    def failed_write_keeps_old() -> tuple[str, str, list[str]]:
        write_json(settings_target, {"currency": "₹"})
        error = raised_message(lambda: write_json(settings_target, {"bad": {1, 2}}))
        leftovers = sorted(path.name for path in json_dir.iterdir() if path.name != "settings.json")
        return error.split(":")[0], settings_target.read_text(encoding="utf-8"), leftovers

    run_checks(
        [
            (
                "writes pretty JSON",
                lambda: write_then_read({"gst": 18, "city": "Pune"}),
                '{\n  "gst": 18,\n  "city": "Pune"\n}\n',
            ),
            ("keeps non-ASCII", lambda: write_then_read(["₹"]), '[\n  "₹"\n]\n'),
            (
                "overwrites",
                lambda: (write_then_read({"v": 1}), write_then_read({"v": 2}))[1],
                '{\n  "v": 2\n}\n',
            ),
            (
                "failure leaves old file, no temp files",
                failed_write_keeps_old,
                ("TypeError", '{\n  "currency": "₹"\n}\n', []),
            ),
            (
                "uses os.replace and fsync",
                lambda: all(
                    word in inspect.getsource(write_json) for word in ("os.replace", "fsync")
                ),
                True,
            ),
        ]
    )

    HEADER = "order_id,customer,sku,quantity,unit_price\n"
    good_csv, bad_csv, duplicate_csv = (
        LAB45_DIR / name for name in ("orders_good.csv", "orders_bad.csv", "orders_dup.csv")
    )
    good_csv.write_text(
        HEADER
        + '1,Asha,TEA-500,2,240.00\n2,O\'Brien,MUG-02,1,199.00\n3,"Rao, Ravi",JAR-750,3,350.50\n',
        encoding="utf-8",
    )
    bad_csv.write_text(
        HEADER + "4,Meera,TEA-500,1,240.00\n5,John,MUG-02,two,199.00\n", encoding="utf-8"
    )
    duplicate_csv.write_text(
        HEADER + "6,Fatima,TEA-500,1,240.00\n1,Asha,TEA-500,9,240.00\n", encoding="utf-8"
    )

    def import_story() -> dict[str, object]:
        database = sqlite3.connect(":memory:")
        story: dict[str, object] = {"good": import_orders(good_csv, database)}
        story["bad"] = raised_message(lambda: import_orders(bad_csv, database)).split(":")[0]
        story["duplicate"] = raised_message(lambda: import_orders(duplicate_csv, database)).split(
            ":"
        )[0]
        story["rows"] = database.execute(
            "SELECT order_id, customer, quantity, unit_price FROM orders ORDER BY order_id"
        ).fetchall()
        database.close()
        return story

    run_checks(
        [
            ("rows inserted", lambda: import_story()["good"], 3),
            (
                "quotes and commas stored as data",
                lambda: [row[1] for row in import_story()["rows"]],
                ["Asha", "O'Brien", "Rao, Ravi"],
            ),
            ("types", lambda: import_story()["rows"][2], (3, "Rao, Ravi", 3, "350.50")),
            ("invalid quantity -> ValueError", lambda: import_story()["bad"], "ValueError"),
            ("duplicate id -> ValueError", lambda: import_story()["duplicate"], "ValueError"),
            ("failed files insert nothing", lambda: len(import_story()["rows"]), 3),
            (
                "uses executemany with placeholders",
                lambda: (
                    "executemany" in inspect.getsource(import_orders)
                    and "?" in inspect.getsource(import_orders)
                ),
                True,
            ),
        ]
    )

    def make_wav(channels: int, sample_rate: int, sample_width: int, frames: int) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(sample_width)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(bytes(frames * channels * sample_width))
        return buffer.getvalue()

    run_checks(
        [
            (
                "mono 8 kHz 16-bit",
                lambda: parse_wav_header(make_wav(1, 8000, 2, 4000)),
                {
                    "channels": 1,
                    "sample_rate": 8000,
                    "bits_per_sample": 16,
                    "data_size": 8000,
                    "duration_seconds": 0.5,
                },
            ),
            (
                "stereo 44.1 kHz 16-bit",
                lambda: parse_wav_header(make_wav(2, 44_100, 2, 44_100)),
                {
                    "channels": 2,
                    "sample_rate": 44_100,
                    "bits_per_sample": 16,
                    "data_size": 176_400,
                    "duration_seconds": 1.0,
                },
            ),
            (
                "8-bit",
                lambda: parse_wav_header(make_wav(1, 22_050, 1, 11_025))["bits_per_sample"],
                8,
            ),
            (
                "not RIFF",
                lambda: raised_message(
                    lambda: parse_wav_header(b"RIFX" + make_wav(1, 8000, 2, 10)[4:])
                ).split(":")[0],
                "ValueError",
            ),
            (
                "not WAVE",
                lambda: raised_message(
                    lambda: parse_wav_header(make_wav(1, 8000, 2, 10).replace(b"WAVE", b"AVI "))
                ).split(":")[0],
                "ValueError",
            ),
            (
                "too short",
                lambda: raised_message(lambda: parse_wav_header(b"RIFF")).split(":")[0],
                "ValueError",
            ),
            ("uses struct", lambda: "struct" in inspect.getsource(parse_wav_header), True),
        ]
    )

    @dataclasses.dataclass
    class LabLine:
        sku: str
        price: Decimal

    @dataclasses.dataclass
    class LabOrder:
        order_id: uuid.UUID
        placed_at: datetime
        lines: list[LabLine]

    LAB_MOMENT = datetime(2026, 11, 7, 9, 30, tzinfo=UTC)
    ORDER_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
    sample_order = LabOrder(ORDER_ID, LAB_MOMENT, [LabLine("TEA-500", Decimal("240.00"))])
    run_checks(
        [
            (
                "Decimal",
                lambda: json.dumps({"total": Decimal("679.00")}, cls=RichJSONEncoder),
                '{"total": "679.00"}',
            ),
            (
                "datetime and date",
                lambda: json.dumps([LAB_MOMENT, date(2026, 11, 7)], cls=RichJSONEncoder),
                '["2026-11-07T09:30:00+00:00", "2026-11-07"]',
            ),
            (
                "UUID",
                lambda: json.dumps(ORDER_ID, cls=RichJSONEncoder),
                '"12345678-1234-5678-1234-567812345678"',
            ),
            (
                "nested dataclasses",
                lambda: json.loads(json.dumps(sample_order, cls=RichJSONEncoder)),
                {
                    "order_id": str(ORDER_ID),
                    "placed_at": "2026-11-07T09:30:00+00:00",
                    "lines": [{"sku": "TEA-500", "price": "240.00"}],
                },
            ),
            (
                "dataclass class itself is not encoded",
                lambda: raised_message(lambda: json.dumps(LabLine, cls=RichJSONEncoder)).split(":")[
                    0
                ],
                "TypeError",
            ),
            (
                "other types still fail",
                lambda: raised_message(lambda: json.dumps({1, 2}, cls=RichJSONEncoder)).split(":")[
                    0
                ],
                "TypeError",
            ),
        ]
    )

    def make_zip(name: str, members: dict[str, str]) -> Path:
        path = LAB45_DIR / name
        with zipfile.ZipFile(path, "w") as archive:
            for member_name, text in members.items():
                archive.writestr(member_name, text)
        return path

    def extract_into(archive: Path, folder_name: str) -> tuple[str, list[str]]:
        destination = LAB45_DIR / folder_name
        shutil.rmtree(destination, ignore_errors=True)
        outcome = raised_message(lambda: safe_extract_zip(archive, destination))
        written = (
            sorted(
                path.relative_to(destination).as_posix()
                for path in destination.rglob("*")
                if path.is_file()
            )
            if destination.exists()
            else []
        )
        return outcome.split(":")[0], written

    def read_if_exists(path: Path) -> str | None:
        return path.read_text() if path.exists() else None

    shutil.rmtree(LAB45_DIR / "extract_good", ignore_errors=True)  # start clean on every run
    good_zip = make_zip(
        "good.zip",
        {"invoices/7.txt": "679.00", "invoices/8.txt": "240.00", "readme.txt": "hi", "empty/": ""},
    )
    run_checks(
        [
            (
                "good archive",
                lambda: safe_extract_zip(good_zip, LAB45_DIR / "extract_good"),
                ["invoices/7.txt", "invoices/8.txt", "readme.txt"],
            ),
            (
                "contents",
                lambda: read_if_exists(LAB45_DIR / "extract_good" / "invoices" / "7.txt"),
                "679.00",
            ),
            (
                "'..' member",
                lambda: extract_into(
                    make_zip("dotdot.zip", {"ok.txt": "1", "../evil.txt": "x"}), "extract_dotdot"
                ),
                ("ValueError", []),
            ),
            (
                "nested '..'",
                lambda: extract_into(
                    make_zip("nested.zip", {"a/../../evil.txt": "x"}), "extract_nested"
                ),
                ("ValueError", []),
            ),
            (
                "absolute member",
                lambda: extract_into(
                    make_zip("absolute.zip", {"ok.txt": "1", "/tmp/evil.txt": "x"}),
                    "extract_absolute",
                ),
                ("ValueError", []),
            ),
            ("nothing escaped", lambda: (LAB45_DIR.parent / "evil.txt").exists(), False),
        ]
    )


# ===============================================================================================
# Lab 4.6 — helpers copied from the notebook's lab setup cell
# ===============================================================================================

SHOP_API_PORT = 18046  # fixed so outputs (URLs in messages) are stable; falls back to any free port


def demo_orders() -> list[dict[str, object]]:
    """40 seeded orders as an API would return them, with 3 invalid records planted."""
    generator = random.Random(46)
    cities = ["Pune", "Mumbai", "Bengaluru", "Hubli & Dharwad"]
    prices = {"TEA-500": "240.00", "MUG-02": "199.00", "JAR-750": "350.50", "KETTLE-9": "899.00"}
    orders: list[dict[str, object]] = []
    for order_id in range(1, 41):
        sku = generator.choice(sorted(prices))
        orders.append(
            {
                "order_id": order_id,
                "customer": f"customer-{order_id:03d}",
                "city": generator.choice(cities),
                "sku": sku,
                "quantity": generator.randint(1, 5),
                "unit_price": prices[sku],
                "placed_at": f"2026-11-{generator.randint(1, 7):02d}"
                f"T{generator.randint(9, 20):02d}:00:00+05:30",
            }
        )
    orders[6]["quantity"] = -2  # invalid: not positive
    del orders[17]["city"]  # invalid: missing field
    orders[29]["unit_price"] = "two hundred"  # invalid: not a number
    return orders


PRODUCTS_HTML = """<!doctype html>
<html><head><title>Chai Corner - Products</title></head>
<body>
  <h1>Products</h1>
  <ul id="catalogue">
    <li class="product" data-sku="TEA-500">
      <a href="/products/tea-500">Masala tea 500 g</a> <span class="price">₹240.00</span>
    </li>
    <li class="product" data-sku="MUG-02">
      <a href="/products/mug-02">Steel mug</a> <span class="price">₹199.00</span>
    </li>
    <li class="product sold-out" data-sku="JAR-750">
      <a href="/products/jar-750">Pickle jar 750 ml</a> <span class="price">₹350.50</span>
    </li>
  </ul>
  <p class="note">Prices include GST &amp; free delivery above ₹500.</p>
</body></html>
"""
ROBOTS_TXT = "User-agent: *\nDisallow: /admin/\nCrawl-delay: 1\n\nUser-agent: BadBot\nDisallow: /\n"


class ShopAPIHandler(http.server.BaseHTTPRequestHandler):
    """A tiny local HTTP API used by every HTTP demo (no external network)."""

    protocol_version = "HTTP/1.1"  # keep-alive, so clients can reuse connections
    hits: dict[str, int] = {}
    connections = 0

    def setup(self) -> None:
        type(self).connections += 1  # one per TCP connection, not per request
        super().setup()

    def log_message(self, format: str, *args: object) -> None:  # keep the notebook quiet
        pass

    def _send(self, status: int, body: object, content_type: str = "application/json") -> None:
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except BrokenPipeError, ConnectionResetError:  # the client gave up (a timeout demo)
            self.close_connection = True

    def _count(self, key: str) -> int:
        self.hits[key] = self.hits.get(key, 0) + 1
        return self.hits[key]

    def do_GET(self) -> None:
        url = urllib.parse.urlsplit(self.path)
        query = dict(urllib.parse.parse_qsl(url.query))
        parts = url.path.strip("/").split("/")
        fail_first = int(query.get("fail", 0))
        if url.path == "/rates":
            base = query.get("base", "INR")
            self._send(
                200,
                {
                    "base": base,
                    "date": "2026-11-07",
                    "rates": {"USD": 0.012, "EUR": 0.011, "GBP": 0.0094},
                },
            )
        elif url.path == "/orders":
            if "key" in query and self._count(query["key"]) <= fail_first:
                self._send(503, {"error": "service busy, try again"})
            else:
                self._send(200, demo_orders())
        elif parts[0] == "flaky" and len(parts) == 2:
            attempt = self._count(parts[1])
            if attempt <= fail_first:
                self._send(503, {"error": "busy", "attempt": attempt})
            else:
                self._send(200, {"ok": True, "attempt": attempt})
        elif url.path == "/hits":
            self._send(
                200, {"key": query.get("key"), "hits": self.hits.get(query.get("key", ""), 0)}
            )
        elif url.path == "/connections":
            self._send(200, {"connections": type(self).connections})
        elif url.path == "/reset":
            self.hits.clear()
            self._send(200, {"reset": True})
        elif url.path == "/slow":
            time.sleep(float(query.get("seconds", "2")))
            self._send(200, {"slow": True})
        elif parts[0] == "status" and len(parts) == 2:
            self._send(int(parts[1]), {"status": int(parts[1])})
        elif url.path == "/headers":
            self._send(
                200,
                {
                    name.lower(): value
                    for name, value in self.headers.items()
                    if name.lower() in ("user-agent", "x-request-id", "authorization")
                },
            )
        elif url.path == "/products.html":
            self._send(200, PRODUCTS_HTML, "text/html")
        elif url.path == "/robots.txt":
            self._send(200, ROBOTS_TXT, "text/plain")
        else:
            self._send(404, {"error": f"no route {url.path}"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"null")
        self._send(201 if self.path == "/orders" else 200, {"received": payload})


def start_shop_api() -> str:
    """Start the local API once (in a daemon thread) and return its base URL."""
    server = globals().get("_SHOP_API_SERVER")
    if server is None:
        try:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", SHOP_API_PORT), ShopAPIHandler)
        except OSError:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ShopAPIHandler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        globals()["_SHOP_API_SERVER"] = server
    return f"http://127.0.0.1:{server.server_address[1]}"


LAB46_DIR = find_repo_root() / "notebooks" / "_scratch" / "unit46" / "lab"
LAB46_DIR.mkdir(parents=True, exist_ok=True)
LAB_API = start_shop_api()


# Lab 4.6 solutions -------------------------------------------------------------------------

# Exercise 1 ------------------------------------------------------------------------------------


def _is_transient(error: BaseException) -> bool:
    """Retry 5xx responses and transport errors (timeouts, refused connections); never 4xx."""
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code >= 500
    return isinstance(error, httpx.TransportError)


@tenacity.retry(
    retry=tenacity.retry_if_exception(_is_transient),
    stop=tenacity.stop_after_attempt(4),
    wait=tenacity.wait_exponential(multiplier=0.01, max=0.05),
    reraise=True,
)
def fetch_orders(client: httpx.Client, path: str = "/orders") -> list[dict[str, object]]:
    """GET path and return the JSON list (retried by tenacity)."""
    response = client.get(path)
    response.raise_for_status()
    return response.json()


class OrderRecord(BaseModel):
    """One validated order."""

    order_id: PositiveInt
    customer: str
    city: str
    sku: str
    quantity: PositiveInt
    unit_price: Annotated[Decimal, Field(gt=0)]
    placed_at: AwareDatetime


def validate_orders(raw: list[dict[str, object]]) -> tuple[list[OrderRecord], list[str]]:
    """(valid records, one 'record {index}: ...' message per invalid record)."""
    valid: list[OrderRecord] = []
    problems: list[str] = []
    for index, record in enumerate(raw):
        try:
            valid.append(OrderRecord.model_validate(record))
        except ValidationError as error:
            fields = ", ".join(".".join(map(str, issue["loc"])) for issue in error.errors())
            problems.append(f"record {index}: invalid {fields}")
    return valid, problems


def summarize(records: list[OrderRecord]) -> pl.DataFrame:
    """city, orders, units, revenue; sorted by revenue, highest first."""
    frame = pl.DataFrame(
        {
            "city": [record.city for record in records],
            "quantity": [record.quantity for record in records],
            "revenue": [float(record.quantity * record.unit_price) for record in records],
        }
    )
    return (
        frame.group_by("city")
        .agg(
            pl.len().alias("orders"),
            pl.col("quantity").sum().alias("units"),
            pl.col("revenue").sum().round(2).alias("revenue"),
        )
        .sort(["revenue", "city"], descending=[True, False])
    )


def build_table(summary: pl.DataFrame) -> Table:
    """A rich table titled 'Revenue by city'."""
    table = Table(title="Revenue by city")
    table.add_column("City")
    for header in ("Orders", "Units", "Revenue (INR)"):
        table.add_column(header, justify="right")
    for row in summary.iter_rows(named=True):
        table.add_row(row["city"], str(row["orders"]), str(row["units"]), f"{row['revenue']:,.2f}")
    return table


REPORT_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Revenue by city</title></head>
<body>
<h1>Revenue by city</h1>
<table>
  <tr><th>City</th><th>Orders</th><th>Units</th><th>Revenue (INR)</th></tr>
{%- for row in rows %}
  <tr>
    <td>{{ row.city }}</td><td>{{ row.orders }}</td><td>{{ row.units }}</td>
    <td>{{ "{:,.2f}".format(row.revenue) }}</td>
  </tr>
{%- endfor %}
</table>
<p>Generated {{ generated_at.strftime("%Y-%m-%d %H:%M %Z") }}</p>
</body></html>
"""


def render_report(summary: pl.DataFrame, generated_at: datetime) -> str:
    """An autoescaped Jinja2 HTML report."""
    environment = Environment(autoescape=select_autoescape(default_for_string=True, default=True))
    template = environment.from_string(REPORT_TEMPLATE)
    return template.render(rows=list(summary.iter_rows(named=True)), generated_at=generated_at)


app = typer.Typer(add_completion=False)


@app.command()
def report(
    base_url: Annotated[str, typer.Option(help="Base URL of the shop API.")],
    path: Annotated[str, typer.Option(help="Orders endpoint.")] = "/orders",
    output: Annotated[Path, typer.Option(help="Where to write the HTML report.")] = Path(
        "report.html"
    ),
) -> None:
    """Fetch orders, validate them, summarize by city, print a table and write a report."""
    try:
        with httpx.Client(base_url=base_url, timeout=5) as client:
            raw = fetch_orders(client, path)
    except httpx.HTTPError as error:
        typer.echo(f"error: {error}")
        raise typer.Exit(code=1) from error
    valid, problems = validate_orders(raw)
    summary = summarize(valid)
    Console().print(build_table(summary))
    output.write_text(render_report(summary, datetime.now(UTC)), encoding="utf-8")
    typer.echo(
        f"{len(valid)} valid orders, {len(problems)} rejected; report written to {output.name}"
    )


def check_lab_4_6() -> None:
    """The notebook's Lab 4.6 check cells, verbatim."""
    from typer.testing import CliRunner

    def hits(key: str) -> int:
        return httpx.get(f"{LAB_API}/hits", params={"key": key}, timeout=5).json()["hits"]

    def fetch_story(key: str, fail: int) -> tuple[str, int]:
        with httpx.Client(base_url=LAB_API, timeout=5) as client:
            client.get("/reset")
            try:
                outcome = str(len(fetch_orders(client, f"/orders?key={key}&fail={fail}")))
            except httpx.HTTPStatusError as error:
                outcome = f"HTTPStatusError {error.response.status_code}"
        return outcome, hits(key)

    def not_found_story() -> str:
        with httpx.Client(base_url=LAB_API, timeout=5) as client:
            started = time.monotonic()
            try:
                fetch_orders(client, "/status/404")
            except httpx.HTTPStatusError as error:
                return f"{error.response.status_code} fast={time.monotonic() - started < 0.5}"
        return "no error"

    LAB_RAW = demo_orders()
    VALID_RAW = [record for index, record in enumerate(LAB_RAW) if index not in (6, 17, 29)]
    EXPECTED_REVENUE = {}
    for record in VALID_RAW:
        EXPECTED_REVENUE[record["city"]] = EXPECTED_REVENUE.get(
            record["city"], Decimal(0)
        ) + record["quantity"] * Decimal(record["unit_price"])
    EXPECTED_ORDER = sorted(EXPECTED_REVENUE, key=lambda city: -EXPECTED_REVENUE[city])

    def lab_summary() -> pl.DataFrame:
        return summarize(validate_orders(LAB_RAW)[0])

    def table_facts() -> tuple[object, ...]:
        table = build_table(lab_summary())
        return table.title, [str(column.header) for column in table.columns], table.row_count

    def report_facts() -> tuple[object, ...]:
        html = render_report(lab_summary(), datetime(2026, 11, 7, 9, 30, tzinfo=UTC))
        return (
            html.count("<tr"),
            "Hubli &amp; Dharwad" in html,
            "Hubli & Dharwad" in html,
            "Generated 2026-11-07 09:30 UTC" in html,
        )

    def cli_story(path: str) -> tuple[int, bool, bool, bool]:
        output = LAB46_DIR / "report.html"
        output.unlink(missing_ok=True)
        httpx.get(f"{LAB_API}/reset", timeout=5)
        result = CliRunner().invoke(
            app,
            ["--base-url", LAB_API, "--path", path, "--output", str(output)],
            env={"COLUMNS": "100", "NO_COLOR": "1"},
        )
        text = result.output
        return (
            result.exit_code,
            "Revenue by city" in text,
            "37 valid orders, 3 rejected; report written to report.html" in text,
            output.exists(),
        )

    run_checks(
        [
            ("fetch: 2 failures then success", lambda: fetch_story("lab-ok", 2), ("40", 3)),
            (
                "fetch: gives up after 4 attempts",
                lambda: fetch_story("lab-down", 9),
                ("HTTPStatusError 503", 4),
            ),
            ("fetch: 404 is not retried", not_found_story, "404 fast=True"),
            ("validate: 37 valid", lambda: len(validate_orders(LAB_RAW)[0]), 37),
            (
                "validate: problems name records 6, 17, 29",
                lambda: [problem.split(":")[0] for problem in validate_orders(LAB_RAW)[1]],
                ["record 6", "record 17", "record 29"],
            ),
            (
                "OrderRecord types",
                lambda: (
                    type(validate_orders(LAB_RAW)[0][0].unit_price).__name__,
                    validate_orders(LAB_RAW)[0][0].placed_at.utcoffset() is not None,
                ),
                ("Decimal", True),
            ),
            (
                "summary columns",
                lambda: lab_summary().columns,
                ["city", "orders", "units", "revenue"],
            ),
            (
                "summary order and revenue",
                lambda: [
                    (row["city"], row["revenue"]) for row in lab_summary().iter_rows(named=True)
                ],
                [(city, float(round(EXPECTED_REVENUE[city], 2))) for city in EXPECTED_ORDER],
            ),
            (
                "summary counts",
                lambda: (lab_summary()["orders"].sum(), lab_summary()["units"].sum()),
                (37, sum(record["quantity"] for record in VALID_RAW)),
            ),
            (
                "rich table",
                table_facts,
                (
                    "Revenue by city",
                    ["City", "Orders", "Units", "Revenue (INR)"],
                    len(EXPECTED_ORDER),
                ),
            ),
            (
                "report: rows, escaping, timestamp",
                report_facts,
                (len(EXPECTED_ORDER) + 1, True, False, True),
            ),
            ("CLI success", lambda: cli_story("/orders"), (0, True, True, True)),
            ("CLI HTTP error -> exit 1", lambda: cli_story("/status/404")[0], 1),
        ]
    )


if __name__ == "__main__":
    selected = set(sys.argv[1:])
    for lab_title, check_lab in [
        ("Lab 4.1", check_lab_4_1),
        ("Lab 4.2", check_lab_4_2),
        ("Lab 4.3", check_lab_4_3),
        ("Lab 4.4", check_lab_4_4),
        ("Lab 4.5", check_lab_4_5),
        ("Lab 4.6", check_lab_4_6),
    ]:
        if selected and lab_title not in selected:
            continue
        print(f"===== {lab_title} =====")
        check_lab()
