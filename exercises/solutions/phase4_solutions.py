"""Reference solutions for Phase 4 labs.

Run from the repository root:

    uv run python exercises/solutions/phase4_solutions.py

The helpers are copied from the unit setup cells and each check_lab_4_N() runs the notebook's own
check cells, so the notebook and this file test exactly the same things. The checks build and run
throwaway projects under notebooks/_scratch/ (git-ignored), like the notebook.
"""

import annotationlib
import base64
import email.parser
import functools
import hashlib
import inspect
import json
import linecache
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import textwrap
import time
import tomllib
import typing
import zipfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Annotated, Literal, get_type_hints, overload

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


if __name__ == "__main__":
    for lab_title, check_lab in [("Lab 4.1", check_lab_4_1), ("Lab 4.2", check_lab_4_2)]:
        print(f"===== {lab_title} =====")
        check_lab()
