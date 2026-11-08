"""Phase 4 Project — Publish the Log Analyzer, closing with 20 predict-the-output questions."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

PROJECT_SETUP_SOURCE = """
import argparse
import csv
import datetime as dt
import gzip
import inspect
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import textwrap
import tomllib
import zipfile
from collections import Counter
from contextlib import closing
from pathlib import Path

REPO_ROOT = find_repo_root()
PACKAGE_DIR = REPO_ROOT / "projects" / "log-analyzer"  # the package, with its own pyproject.toml
PACKAGE_BIN = PACKAGE_DIR / ".venv" / "bin"  # the package's own environment (Step 3)
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "log-analyzer.yml"
scratch_dir = REPO_ROOT / "notebooks" / "_scratch"  # git-ignored
PROJECT_DIR = scratch_dir / "phase4_project"  # where the CLI demos write their files
shutil.rmtree(PROJECT_DIR, ignore_errors=True)
PROJECT_DIR.mkdir(parents=True)
UV = shutil.which("uv")
if str(PACKAGE_DIR / "src") not in sys.path:
    sys.path.insert(0, str(PACKAGE_DIR / "src"))  # so the kernel can import log_analyzer
print(f"{sys.version_info[:2]=}, uv found: {UV is not None}")
"""

RUNNER_SOURCE = r'''
TIMING = re.compile(r"\b(in|after) \d+(?:\.\d+)? ?(?:ms|s|µs)\b")
LOG_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4}")
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")  # mypy colours its output even when piped
SKIPPED_NAMES = {".venv", "__pycache__", "dist", ".pytest_cache", ".mypy_cache", ".ruff_cache",
                 ".hypothesis", ".coverage"}  # fmt: skip


def package_env() -> dict[str, str]:
    """Child environment: not the course venv, no colours, unbuffered, reproducible Hypothesis."""
    dropped = ("UV_", "VIRTUAL_ENV", "PYTHONPATH", "PYTEST_", "COV", "HYPOTHESIS")
    inherited = {key: value for key, value in os.environ.items() if not key.startswith(dropped)}
    return {**inherited, "NO_COLOR": "1", "PY_COLORS": "0", "TERM": "dumb", "COLUMNS": "100",
            "UV_NO_PROGRESS": "1", "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
            "HYPOTHESIS_PROFILE": "ci"}  # fmt: skip


def tidy(text: str) -> str:
    """Show paths as <scratch>, <package>, <repo> or ~; timings and log times as placeholders."""
    for folder, label in ((PROJECT_DIR, "<scratch>"), (PACKAGE_DIR, "<package>"),
                          (REPO_ROOT, "<repo>"), (Path.home(), "~")):  # fmt: skip
        text = text.replace(str(folder), label)
    return ANSI_ESCAPE.sub("", LOG_STAMP.sub("<timestamp>", TIMING.sub(r"\1 <time>", text)))


def run(*command: str, cwd: Path = PROJECT_DIR) -> tuple[int, str]:
    """Run a command in a child process; return (exit code, tidied stdout + stderr in order)."""
    name = command[0]
    known = {"log-analyzer": PACKAGE_BIN / "log-analyzer", "python": PACKAGE_BIN / "python"}
    executable = Path(UV) if name == "uv" and UV else known.get(name, Path(name))
    if not executable.exists():
        return 127, f"SKIP: {name} is not available (needs uv and the Step 3 environment)"
    completed = subprocess.run(
        [str(executable), *command[1:]], cwd=cwd, env=package_env(), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600,
    )  # fmt: skip
    return completed.returncode, tidy(completed.stdout.rstrip())
'''

SHELL_SOURCE = r'''
def shell(*command: str, cwd: Path = PROJECT_DIR, keep: str | None = None,
          max_lines: int | None = None) -> None:  # fmt: skip
    """Print `[folder]$ command` and the real output (only lines matching keep, if given)."""
    exit_code, output = run(*command, cwd=cwd)
    print(f"[{tidy(str(cwd))}]$ {tidy(shlex.join(command))}")
    lines = output.splitlines()
    if keep is not None:
        lines = [line for line in lines if re.search(keep, line)]
    if max_lines is not None and len(lines) > max_lines:
        lines = [*lines[:max_lines], f"... ({len(lines) - max_lines} more lines)"]
    if lines:
        print(textwrap.indent("\n".join(lines), "  ", lambda line: True))
    if exit_code:
        print(f"  (exit code {exit_code})")


def show_tree(root: Path, prefix: str = "") -> None:
    """Print a folder tree, skipping environments, caches and build output."""
    entries = sorted((entry for entry in root.iterdir() if entry.name not in SKIPPED_NAMES),
                     key=lambda entry: (entry.is_file(), entry.name))  # fmt: skip
    for index, entry in enumerate(entries):
        last = index == len(entries) - 1
        print(f"{prefix}{'└── ' if last else '├── '}{entry.name}{'/' if entry.is_dir() else ''}")
        if entry.is_dir():
            show_tree(entry, prefix + ("    " if last else "│   "))


def show_lines(path: Path, first: int | None = None) -> None:
    """Print a text file (or its first lines), paths tidied."""
    lines = path.read_text(encoding="utf-8").splitlines()
    print("\n".join(tidy(line) for line in lines[:first]))
'''


def _overview_cells() -> list[NotebookNode]:
    """Project opener and setup."""
    return [
        md(
            """
            ## Phase 4 Project — Publish the Log Analyzer

            The Phase 1 Project built a log analyzer inside a notebook. This project turns the
            same code into a **package**: something anyone can install with one command, that
            checks its own types, tests itself on four Python versions, and publishes itself to
            TestPyPI when you push a release tag.

            | Requirement (syllabus) | Where it lives | Unit |
            | --- | --- | --- |
            | Turn the Phase 1 log analyzer into a package published to TestPyPI | `projects/log-analyzer/`, distribution `log-analyzer-psbcg433` | 4.1 |
            | `src/` layout | `projects/log-analyzer/src/log_analyzer/` | 4.1.7 |
            | `mypy --strict` clean | `[tool.mypy] strict = true`, `py.typed` | 4.2 |
            | pytest + Hypothesis at 90%+ coverage | `tests/`, `--cov-fail-under=90` | 4.3 |
            | `dictConfig` logging | `log_analyzer/logging_config.py` | 4.3.9 |
            | An `argparse` CLI with subcommands | `log_analyzer/cli.py` | 4.4.8 |
            | `.gz` input support | `log_analyzer/parsing.py` (`open_log`) | 4.5.8 |
            | CSV / JSON / SQLite export | `log_analyzer/export.py` | 4.5.6, 4.5.9 |
            | A GitHub Actions workflow with trusted publishing | `.github/workflows/log-analyzer.yml` | 4.1.8, 4.3.10 |

            ```mermaid
            graph LR
                A[push or pull request] --> T[test: ruff, mypy --strict, pytest on 3.12-3.15]
                G[push tag log-analyzer-v0.1.0] --> T
                T --> B[build: tag = version?, uv build, smoke test]
                B -->|tag or manual run only| P[publish: OIDC token, upload to TestPyPI]
            ```

            <details><summary>ASCII fallback</summary>

            ```text
            push / pull request ----+
                                    +--> test (ruff, mypy --strict, pytest x 4 Pythons)
            push tag log-analyzer-v* +          |
                                               v
                                    build (tag = version?, uv build, smoke test)
                                               |  only for a tag or a manual run
                                               v
                                    publish (OIDC token -> TestPyPI)
            ```

            </details>

            **How this section works**

            - The package has its **own** `pyproject.toml`, `uv.lock` and `.venv`, separate from
              the course environment. Step 3 creates that environment; the CLI and the dev tools
              run from it in child processes, and the cells print their real output.
            - CLI demos write their files to `notebooks/_scratch/phase4_project/`. Paths are shown
              as `<scratch>`, `<package>` (`projects/log-analyzer`), `<repo>` or `~`, timings as
              `<time>`.
            - **Nothing is published from this notebook.** Publishing happens on GitHub when you
              push a tag; *How to publish* at the end lists the steps you do yourself.
            """
        ),
        md(
            """
            The setup cell defines the paths and puts `projects/log-analyzer/src` on `sys.path`,
            so the kernel can import the package for the code tour (the kernel's environment
            does not have the package *installed*; Step 4 shows what that changes).
            """
        ),
        code(PROJECT_SETUP_SOURCE),
        md(
            """
            Two helpers in the style of Units 4.1 and 4.3: `run` executes a command in a child
            process with a clean environment (not the course venv, no colours, unbuffered so
            stderr and stdout keep their order, `HYPOTHESIS_PROFILE=ci`) and returns its exit
            code and tidied output. `log-analyzer` and `python` resolve to the package's own
            `.venv/bin/`.
            """
        ),
        code(RUNNER_SOURCE),
        md(
            """
            `shell` prints a command and its output like a terminal session; `show_tree` and
            `show_lines` display files.
            """
        ),
        code(SHELL_SOURCE),
    ]


def _decision_cells() -> list[NotebookNode]:
    """Step 1: packaging decisions and the layout."""
    return [
        md(
            """
            ### Step 1 — Packaging decisions

            Every line of the package's configuration is a decision. These are the ones that
            matter, with the unit that taught the trade-off:

            | Decision | Choice | Why | Unit |
            | --- | --- | --- | --- |
            | Names | distribution `log-analyzer-psbcg433`, import `log_analyzer`, command `log-analyzer` | Index names are global and first-come; a GitHub-username suffix makes the name unique on TestPyPI. The import name stays short. The index normalizes `-`, `_` and `.` (PEP 503) | 4.1.4 |
            | Layout | `src/` | Tests import the *installed* package, never the folder next to them, so a file missing from the wheel fails the tests | 4.1.7 |
            | Build backend | `uv_build` (pinned `<0.14`) | The backend Unit 4.1 used; zero configuration for a pure-Python `src/` layout | 4.1.8 |
            | Runtime dependencies | none | `gzip`, `csv`, `json`, `sqlite3`, `argparse`, `logging.config` are standard library: nothing to audit, nothing to break | 4.1.9 |
            | Python versions | `requires-python = ">=3.12"`, CI on 3.12–3.15 | Nothing needs 3.15; 3.12 brings the `type` statement used for aliases. A wider range means more users can install it | 4.1.5 |
            | Version | `version = "0.1.0"` only in `pyproject.toml`; `__version__` read with `importlib.metadata` | One source of truth; CI refuses a tag that does not match it | 4.1.4 |
            | Typing | `py.typed`, `mypy --strict` on `src` and `tests` | Users' type checkers read the package's hints (PEP 561) | 4.2.12 |
            | Environment | own `pyproject.toml` + `uv.lock` | The package does not inherit the course's 160 packages; CI installs exactly the lock | 4.1.6 |
            | Logging | library: `getLogger(__name__)` + `NullHandler`; CLI: `dictConfig` to stderr | Libraries never configure logging; stdout stays clean for pipes | 4.3.9 |
            | Exit codes | 0 success, 1 malformed lines (`validate`), 2 error | Scripts and CI can branch on them; argparse already uses 2 for usage errors | 4.4.8 |
            | sdist contents | `src/`, `tests/`, README | Anyone building from source (a Linux distribution, say) can run the tests | 4.1.8 |
            | Publishing | trusted publishing (OIDC) to TestPyPI, `testpypi` environment | No long-lived API token stored in GitHub | 4.1.8 |
            | Licence | none declared yet | Choosing a licence is the author's decision; add `license = "..."` (PEP 639) before a real PyPI release | 4.1.9 |
            """
        ),
        md(
            """
            The package folder. The modules are the Phase 1 project's steps, split by
            responsibility; the tests mirror them:
            """
        ),
        code(
            """
            print("projects/log-analyzer/")
            show_tree(PACKAGE_DIR)
            """
        ),
        md(
            """
            | Module | Responsibility | Phase 1 Project step |
            | --- | --- | --- |
            | `models.py` | `AccessRecord`, `AccessSummary`, the exception hierarchy | Steps 3–5 |
            | `parsing.py` | regex + `match` parser, lazy `read_lines`, **gzip detection** | Steps 2–4 |
            | `analysis.py` | `aggregate`, `percentile`, `top_endpoints`, strict mode | Steps 5, 7 |
            | `report.py` | 60-column text report, JSON document (`TypedDict`) | Step 6 |
            | `export.py` | streaming CSV / JSON / SQLite writers | new |
            | `generate.py` | seeded synthetic logs, reproducible `.gz` output | Step 1 |
            | `logging_config.py` | the `dictConfig` dictionary | new (replaces `@timer` / `Timer` prints) |
            | `cli.py` | `argparse` subcommands, exit codes | new |
            | `__init__.py` / `__main__.py` | public API, `__version__`, `python -m log_analyzer` | new |

            The algorithms are unchanged, so Step 5 can prove that the package prints exactly
            the report the Phase 1 notebook printed.
            """
        ),
    ]


def _pyproject_cells() -> list[NotebookNode]:
    """Step 2: pyproject.toml."""
    return [
        md(
            """
            ### Step 2 — `pyproject.toml`

            One file holds the metadata (`[project]`), the console script
            (`[project.scripts]`), the dev tools (`[dependency-groups]`, PEP 735: installed for
            development, never shipped), the build backend (`[build-system]`) and every tool's
            configuration (`[tool.*]`). Note `addopts`: plain `pytest` always measures coverage
            and **fails under 90%**, locally and in CI alike.
            """
        ),
        code(
            """
            show_lines(PACKAGE_DIR / "pyproject.toml")
            """
        ),
        md(
            """
            **Under the hood.** Tools read this file with `tomllib` (standard library since
            3.11), exactly as the next cell does. `dependencies = []` is what makes the wheel
            installable offline from a single file.
            """
        ),
        code(
            """
            config = tomllib.loads((PACKAGE_DIR / "pyproject.toml").read_text(encoding="utf-8"))
            project = config["project"]
            print(f"{project['name']=}, {project['version']=}")
            print(f"{project['requires-python']=}, {project['dependencies']=}")
            print(f"{project['scripts']=}")
            print(f"{config['build-system']['build-backend']=}")
            print(f"dev tools: {[spec.split('>=')[0] for spec in config['dependency-groups']['dev']]}")
            print(f"{config['tool']['mypy']=}")
            """
        ),
    ]


def _environment_cells() -> list[NotebookNode]:
    """Step 3: the package's own environment."""
    return [
        md(
            """
            ### Step 3 — The package's own environment

            uv finds the project by walking up from the working directory to the nearest
            `pyproject.toml`. Run inside `projects/log-analyzer/`, it therefore manages the
            *package* (its own `uv.lock` and `.venv`), not the course. `uv sync --locked`
            installs the package in editable mode plus the `dev` group, and **fails** instead of
            silently re-locking if `uv.lock` no longer matches `pyproject.toml`; CI runs the
            same command. (`.venv/` is git-ignored at every depth by the repository's
            `.gitignore`.)

            The first run lists what it installed, later runs only audit, so the cell prints just
            the exit code, then the dependency tree, which comes from the lockfile and is the
            same every time.
            """
        ),
        code(
            """
            sync_exit_code, _ = run("uv", "sync", "--locked", cwd=PACKAGE_DIR)
            print(f"uv sync --locked -> exit code {sync_exit_code}")
            shell("uv", "tree", "--locked", "--depth", "1", cwd=PACKAGE_DIR)
            """
        ),
        md(
            """
            **Under the hood: an editable install.** The environment holds no copy of the code.
            The package's `.dist-info` folder records where the source lives
            (`direct_url.json`, PEP 610) and which console scripts to create
            (`entry_points.txt`); `.venv/bin/log-analyzer` is a tiny generated script that
            imports `log_analyzer.cli` and calls `main()`.
            """
        ),
        code(
            """
            site_packages = next((PACKAGE_DIR / ".venv" / "lib").glob("python3.*/site-packages"))
            dist_info = next(site_packages.glob("log_analyzer_psbcg433-*.dist-info"))
            print(dist_info.name)
            print("direct_url.json:", tidy((dist_info / "direct_url.json").read_text()))
            print("entry_points.txt:", (dist_info / "entry_points.txt").read_text().strip())
            console_script = (PACKAGE_BIN / "log-analyzer").read_text().splitlines()
            print("bin/log-analyzer:", *console_script[1:], sep="\\n  ")
            """
        ),
    ]


def _code_tour_cells() -> list[NotebookNode]:
    """Step 4: key code."""
    return [
        md(
            """
            ### Step 4 — A tour of the key code

            The kernel imports the package from `src/` (the setup cell put it on `sys.path`).
            Look at `__version__`: the code asks `importlib.metadata` for the *installed*
            distribution's version, and the kernel's environment has no such distribution, so
            the fallback `0.0.0+unknown` appears. Installed (Step 3, Step 8) it says `0.1.0`.
            This is the price of a single-sourced version, and the reason the fallback branch
            is excluded from coverage.
            """
        ),
        code(
            """
            import log_analyzer
            from log_analyzer import analysis, cli, export, logging_config, parsing, report

            print(f"{log_analyzer.__version__=}")
            print(f"imported from: {tidy(log_analyzer.__file__ or '')}")
            print(f"public API: {len(log_analyzer.__all__)} names, e.g. {log_analyzer.__all__[-3:]}")
            """
        ),
        md(
            """
            #### `.gz` input

            Compression is detected from the first two bytes (`1f 8b`), not from the file name,
            so a gzip file named `access.log` works and a plain file named `.gz` does too.
            `errors="replace"` turns undecodable bytes into U+FFFD, so one corrupt byte makes
            one malformed line instead of a crash. A truncated or corrupt gzip file becomes a
            `LogFileError` (exit code 2 in the CLI) instead of a raw `EOFError` or
            `zlib.error`.
            """
        ),
        code(
            """
            for function in (parsing.is_gzip_file, parsing.open_log, parsing.read_lines):
                print(inspect.getsource(function))
            """
        ),
        md(
            """
            #### Analysis, logging and strict mode

            `analyze_access_log` is the Phase 1 pipeline plus logging: one INFO record with the
            counts and the time taken, one WARNING if any line was malformed. The library only
            *emits* records; whether anyone sees them is the application's decision.
            """
        ),
        code(
            """
            print(inspect.getsource(analysis.analyze_access_log))
            """
        ),
        md(
            """
            #### The `dictConfig` dictionary

            The CLI configures logging with one dictionary (Unit 4.3.9): a stderr handler at the
            level chosen by `-q` / `-v` / `-vv`, and with `--log-file` a second handler that
            records everything from DEBUG up. The package logger's own level is the *lowest*
            any handler needs; each handler then filters by its own level. `propagate: False`
            keeps records away from the root logger, so they are not printed twice.
            """
        ),
        code(
            """
            logging_dict = logging_config.build_logging_config("WARNING", log_file=Path("run.log"))
            print(json.dumps(logging_dict, indent=2))
            """
        ),
        md(
            """
            #### The CLI: strict mode with `except*`

            `validate` uses the library's strict mode, which raises every malformed line at once
            as an `ExceptionGroup` (Phase 1 Project, Step 8). Python does not allow `return`
            inside an `except*` clause, so the handler records the exit code and returns after
            the `try`. `main` turns expected failures (`LogAnalyzerError`, `OSError`) into a
            one-line message on stderr and exit code 2; anything else is a bug and keeps its
            traceback.
            """
        ),
        code(
            """
            print(inspect.getsource(cli.run_validate))
            print(inspect.getsource(cli.main))
            """
        ),
        md(
            """
            #### Streaming export to SQLite

            `executemany` accepts a generator, so records flow from the gzip file into SQLite one
            at a time. The `malformed` list is filled *while* the records are consumed, which is
            why it is inserted afterwards. `closing(...)` closes the connection;
            `with connection:` only commits (predict question 17 comes back to this).
            """
        ),
        code(
            """
            print(inspect.getsource(export.write_sqlite))
            """
        ),
        md(
            """
            The same functions are a library API. One line through the pipeline: parsed into a
            record, normalized to an endpoint, flattened into an export row:
            """
        ),
        code(
            """
            sample_line = '2026-11-06T09:00:00Z 10.0.2.17 "GET /api/orders/42?expand=items HTTP/1.1" 200 23ms'
            sample_record = parsing.parse_access_line(1, sample_line)
            print(sample_record)
            print(analysis.normalize_endpoint(sample_record.method, sample_record.path))
            print(export.record_row(sample_record))
            print(f"{parsing.format_access_line(sample_record) == sample_line=}")
            """
        ),
    ]


def _cli_cells() -> list[NotebookNode]:
    """Step 5: the CLI in action."""
    return [
        md(
            """
            ### Step 5 — Run the CLI

            From here on, `log-analyzer` is the console script installed in the package's
            environment: exactly what a user gets after `pip install`. Global options (`-v`,
            `-q`, `--log-file`) come before the subcommand.
            """
        ),
        code(
            """
            shell("log-analyzer", "--help")
            """
        ),
        md(
            """
            #### `generate`

            The Phase 1 generator, now a subcommand. A `.gz` name writes compressed output, and
            the output is **byte-for-byte reproducible**: gzip headers normally store the file
            name and the current time, so `generate.py` writes through
            `GzipFile(filename="", mtime=0)`. The cell writes the same 20 000 lines plain and
            compressed and compares them.
            """
        ),
        code(
            """
            shell("log-analyzer", "generate", "access.log.gz", "-n", "20000")
            shell("log-analyzer", "generate", "access.log", "-n", "20000")
            for name in ("access.log", "access.log.gz"):
                path = PROJECT_DIR / name
                print(f"{name:<14}{path.stat().st_size:>10,} bytes, starts with {path.read_bytes()[:2]!r}")
            compressed_text = gzip.decompress((PROJECT_DIR / "access.log.gz").read_bytes())
            print(f"same text inside: {compressed_text == (PROJECT_DIR / 'access.log').read_bytes()}")
            """
        ),
        md(
            """
            #### `report`

            The WARNING line comes from the library's logger through the CLI's `dictConfig`, on
            stderr; the report itself is on stdout.
            """
        ),
        code(
            """
            shell("log-analyzer", "report", "access.log.gz")
            """
        ),
        md(
            """
            **Same algorithm, same answer.** The package's test data holds the report the Phase 1
            notebook printed for the same seed and line count. Reading the gzip file instead of
            plain text changes nothing:
            """
        ),
        code(
            """
            _, package_report = run("log-analyzer", "-q", "report", "access.log.gz")
            phase1_report = (PACKAGE_DIR / "tests" / "data" / "phase1_report_seed42_20000.txt").read_text(
                encoding="utf-8"
            )
            print(f"identical to the Phase 1 notebook's report: {package_report + chr(10) == phase1_report}")
            """
        ),
        md(
            """
            `--format json` prints the same facts as data, for scripts. Status codes become
            string keys, because JSON object keys are always strings (predict question 14);
            `summary_document` converts them explicitly so the `TypedDict` says so too.
            """
        ),
        code(
            """
            shell("log-analyzer", "-q", "report", "access.log.gz", "--top", "2", "--format", "json")
            """
        ),
        md(
            """
            #### `export`: CSV, JSON and SQLite

            The format comes from the extension (or `--format`). CSV and JSON hold the records;
            SQLite also stores the malformed lines in their own table. All three stream: one
            record in memory at a time.
            """
        ),
        code(
            """
            shell("log-analyzer", "-q", "export", "access.log.gz", "records.csv")
            show_lines(PROJECT_DIR / "records.csv", first=3)
            """
        ),
        md(
            """
            The JSON export is one array, written incrementally (`json.dump` per record), so it
            never builds a 20 000-element list in memory:
            """
        ),
        code(
            """
            shell("log-analyzer", "-q", "export", "access.log.gz", "records.json")
            show_lines(PROJECT_DIR / "records.json", first=3)
            exported_records = json.loads((PROJECT_DIR / "records.json").read_text(encoding="utf-8"))
            print(f"{len(exported_records)=}, keys: {list(exported_records[0])}")
            """
        ),
        md(
            """
            SQLite turns the log into something you can query. Which endpoints fail with 5xx
            most often, and how slow were the failures? (`p95` has no SQL function, which is
            one reason the report computes it in Python.)
            """
        ),
        code(
            """
            shell("log-analyzer", "-q", "export", "access.log.gz", "records.db")
            with closing(sqlite3.connect(PROJECT_DIR / "records.db")) as connection:
                table_rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
                print(f"tables: {sorted(name for (name,) in table_rows)}")
                failures = connection.execute(
                    "SELECT endpoint, COUNT(*), MAX(latency_ms) FROM records WHERE status >= 500"
                    " GROUP BY endpoint ORDER BY 2 DESC LIMIT 3"
                )
                for endpoint, failure_count, slowest_ms in failures:
                    print(f"  {endpoint:<26}{failure_count:>5} failures, slowest {slowest_ms:>5} ms")
                reasons = connection.execute("SELECT reason, COUNT(*) FROM malformed GROUP BY reason")
                print(f"malformed by reason: {sorted(reasons)}")
            """
        ),
        md(
            """
            #### `validate` and exit codes

            `validate` is the strict mode: it lists the first malformed lines and exits with 1.
            A clean log exits with 0. A CI step or a shell `&&` chain can rely on that.
            """
        ),
        code(
            """
            shell("log-analyzer", "-q", "validate", "access.log.gz", "--show", "3")
            shell("log-analyzer", "-q", "generate", "clean.log", "-n", "1000", "--malformed-rate", "0")
            shell("log-analyzer", "validate", "clean.log")
            """
        ),
        md(
            """
            #### Logging levels and the log file

            `-vv` lowers the stderr handler to DEBUG (every skipped line is logged), and
            `--log-file` adds a file handler with timestamps and line numbers. The timestamps
            depend on when the cell runs, so they are shown as `<timestamp>`.
            """
        ),
        code(
            """
            shell("log-analyzer", "-vv", "--log-file", "run.log", "validate", "access.log.gz", "--show", "1",
                  max_lines=6)  # fmt: skip
            log_file_lines = (PROJECT_DIR / "run.log").read_text(encoding="utf-8").splitlines()
            level_counts = Counter(line.split()[1] for line in log_file_lines)
            print(f"run.log: {len(log_file_lines)} lines, by level {dict(level_counts)}")
            print(tidy(log_file_lines[1]))
            """
        ),
        md(
            """
            #### Errors

            Expected failures give one line on stderr and exit code 2, never a traceback: a
            truncated gzip file (the first 50 000 bytes of the real one), a missing file, and an
            export format that cannot be inferred. `python -m log_analyzer` runs the same CLI
            through `__main__.py`.
            """
        ),
        code(
            """
            (PROJECT_DIR / "cut.log.gz").write_bytes((PROJECT_DIR / "access.log.gz").read_bytes()[:50_000])
            shell("log-analyzer", "-q", "report", "cut.log.gz")
            shell("log-analyzer", "report", "missing.log")
            shell("log-analyzer", "export", "access.log.gz", "records.txt")
            shell("python", "-m", "log_analyzer", "--version")
            """
        ),
    ]


def _test_cells() -> list[NotebookNode]:
    """Step 6: pytest, Hypothesis and coverage."""
    return [
        md(
            """
            ### Step 6 — Tests: pytest, Hypothesis and coverage

            | File | What it covers |
            | --- | --- |
            | `conftest.py` | fixtures (`sample_log`, `clean_log`, `generated_log`), Hypothesis profiles, an autouse fixture that undoes `dictConfig` after each test |
            | `test_parsing.py` | every malformed reason (parametrized), gzip by content, invalid UTF-8, truncated and corrupt gzip |
            | `test_analysis.py` | helpers, one-pass aggregation, log records with `caplog`, the strict `ExceptionGroup` |
            | `test_report.py` | alignment, empty logs, the JSON document, the Phase 1 golden report |
            | `test_export.py` | CSV quoting, JSON, SQLite tables, format inference, streaming |
            | `test_generate.py` | reproducible bytes (also gzip), every injected line accounted for |
            | `test_logging_config.py` | the dictionary, level routing to stderr and file (`capsys`), library silence |
            | `test_cli.py` | every subcommand and exit code through `main(argv)`, `--version`, `python -m` |
            | `test_properties.py` | Hypothesis: round trips, invariants, export round trips |

            Example tests check one input each. **Properties** state a rule for every input and
            let Hypothesis search for a counter-example (Unit 4.3.7). Here are the strategies and
            the first two properties: formatting a record and parsing it back gives the same
            record, and the parser never raises anything but `MalformedLineError`, whatever
            text it gets.
            """
        ),
        code(
            """
            property_source = (PACKAGE_DIR / "tests" / "test_properties.py").read_text(encoding="utf-8")
            start = property_source.index("# isoformat()")
            stop = property_source.index("@given(st.lists(st.one_of")
            print(property_source[start:stop].rstrip())
            """
        ),
        md(
            """
            > **Note: what the CI matrix caught.** The first version of the `timestamps`
            > strategy used `moment.strftime("%Y-...")`. It passed on 3.14 and 3.15, but on
            > 3.12 and 3.13 Hypothesis found `datetime(999, 1, 1)`: those versions print the
            > year as `999` on Linux (glibc), the regex wants four digits, and the round trip
            > failed. The package itself only ever formats 2026 timestamps; the *test* was wrong.
            > `isoformat()` always pads the year. This is exactly what a version matrix plus
            > property-based testing is for.
            """
        ),
        code(
            """
            year_999 = dt.datetime(999, 1, 1)
            print(f"Python {sys.version_info[:2]}: strftime -> {year_999.strftime('%Y-%m-%d')!r}, "
                  f"isoformat -> {year_999.isoformat()!r}")  # fmt: skip
            """
        ),
        md(
            """
            The whole suite, with the configuration from `pyproject.toml`: coverage measured
            with branches, missing lines listed, and the run **fails under 90%**.
            `HYPOTHESIS_PROFILE=ci` makes Hypothesis derandomized, so this output (and a CI
            failure) is reproducible. The only partial branch, `44->exit` in `parsing.py`, is the
            `match` statement: coverage.py counts "no `case` matched" as a possible exit, even
            though the last case always matches.
            """
        ),
        code(
            """
            shell("uv", "run", "--locked", "pytest", cwd=PACKAGE_DIR)
            """
        ),
        md(
            """
            **The gate works.** Running only one test file leaves most of the CLI and the
            exporters unexecuted, the total drops below 90%, and pytest exits with 1 even though
            every selected test passed:
            """
        ),
        code(
            """
            shell("uv", "run", "--locked", "pytest", "tests/test_report.py", cwd=PACKAGE_DIR,
                  keep=r"TOTAL|Required|passed|failed")  # fmt: skip
            """
        ),
    ]


def _typing_cells() -> list[NotebookNode]:
    """Step 7: mypy --strict, ruff and py.typed."""
    return [
        md(
            """
            ### Step 7 — `mypy --strict`, ruff and `py.typed`

            `[tool.mypy] strict = true` with `files = ["src", "tests"]`, so plain `mypy` is
            already strict; the cell (and CI) pass `--strict` anyway, to make the gate visible.
            The tests are typed too (`pytest.CaptureFixture[str]`, `pytest.LogCaptureFixture`,
            typed Hypothesis strategies). Then the linter and the formatter, as CI runs them.
            """
        ),
        code(
            """
            shell("uv", "run", "--locked", "mypy", "--strict", cwd=PACKAGE_DIR)
            shell("uv", "run", "--locked", "ruff", "check", ".", cwd=PACKAGE_DIR)
            shell("uv", "run", "--locked", "ruff", "format", "--check", ".", cwd=PACKAGE_DIR)
            """
        ),
        md(
            """
            **`py.typed` in action (PEP 561).** Without the marker file, mypy treats an installed
            package as untyped and checks nothing about how you call it. With it, a *user's*
            code is checked against the package's hints. A small consumer script, outside the
            package, checked by the mypy in the package's environment:
            """
        ),
        code(
            '''
            (PROJECT_DIR / "consumer.py").write_text(
                textwrap.dedent("""
                    from pathlib import Path

                    from log_analyzer import analyze_access_log, percentile

                    summary, malformed = analyze_access_log(Path("access.log.gz"))
                    reveal_type(summary.status_counts)
                    percentile(["120", "15"], 95)
                    analyze_access_log("access.log.gz")
                """).lstrip()
            )
            shell("uv", "run", "--project", str(PACKAGE_DIR), "--locked", "mypy", "--strict", "consumer.py")
            '''
        ),
    ]


def _build_cells() -> list[NotebookNode]:
    """Step 8: uv build and a clean install."""
    return [
        md(
            """
            ### Step 8 — Build the sdist and the wheel

            `uv build` builds the sdist first, then the wheel *from the sdist*, which proves the
            sdist is complete. The build runs `uv_build` in an isolated environment (PEP 517).
            """
        ),
        code(
            """
            shutil.rmtree(PACKAGE_DIR / "dist", ignore_errors=True)
            shell("uv", "build", cwd=PACKAGE_DIR)
            wheel_path = next((PACKAGE_DIR / "dist").glob("*.whl"))
            sdist_path = next((PACKAGE_DIR / "dist").glob("*.tar.gz"))
            print(f"{wheel_path.name=}\\n{sdist_path.name=}")
            """
        ),
        md(
            """
            **Under the hood: a wheel is a zip file** (Unit 4.1.8). It holds the package
            (including `py.typed`) and a `.dist-info` folder: `METADATA` (the core metadata the
            index displays), `entry_points.txt` (the console script), `WHEEL` (the tag) and
            `RECORD` (a hash per file). No tests, no `pyproject.toml`.
            """
        ),
        code(
            """
            dist_info_name = "log_analyzer_psbcg433-0.1.0.dist-info"
            with zipfile.ZipFile(wheel_path) as wheel:
                wheel_names = wheel.namelist()
                metadata_text = wheel.read(f"{dist_info_name}/METADATA").decode()
                entry_points_text = wheel.read(f"{dist_info_name}/entry_points.txt").decode()
            print(*wheel_names, sep="\\n")
            print("--- entry_points.txt\\n" + entry_points_text.strip())
            """
        ),
        md(
            """
            The `METADATA` headers (the README follows them as the long description). The
            classifiers are summarized to keep the output short:
            """
        ),
        code(
            """
            metadata_headers = metadata_text.split("\\n\\n", 1)[0].splitlines()
            print(*(line for line in metadata_headers if not line.startswith("Classifier")), sep="\\n")
            classifier_count = sum(line.startswith("Classifier") for line in metadata_headers)
            print(f"... and {classifier_count} Classifier lines")
            with tarfile.open(sdist_path) as sdist:
                sdist_names = sdist.getnames()
            tests_in_sdist = any(name.endswith("/tests/test_cli.py") for name in sdist_names)
            print(f"sdist: {len(sdist_names)} entries, tests included: {tests_in_sdist}")
            """
        ),
        md(
            """
            **The user's view.** A brand-new virtual environment, the wheel installed into it
            (no index needed: there are no dependencies), and the console script run from there.
            This is what `pip install log-analyzer-psbcg433` will do once the package is on
            TestPyPI.
            """
        ),
        code(
            """
            consumer_venv = PROJECT_DIR / "consumer-venv"
            shell("uv", "venv", "--quiet", "--python", "3.15", str(consumer_venv))
            shell("uv", "pip", "install", "--python", str(consumer_venv), str(wheel_path), keep=r"^ \\+")
            shell(str(consumer_venv / "bin" / "log-analyzer"), "--version")
            shell(str(consumer_venv / "bin" / "log-analyzer"), "-q", "validate", "clean.log")
            """
        ),
    ]


def _workflow_cells() -> list[NotebookNode]:
    """Step 9: the GitHub Actions workflow."""
    return [
        md(
            """
            ### Step 9 — The GitHub Actions workflow and trusted publishing

            `.github/workflows/log-analyzer.yml` lives at the repository root (GitHub only reads
            workflows there) and sets `working-directory: projects/log-analyzer` for every
            `run` step.

            | Event | test | build | publish |
            | --- | --- | --- | --- |
            | push or pull request touching `projects/log-analyzer/**` or the workflow | ✓ (3.12–3.15) | ✓ | — |
            | push of a tag `log-analyzer-v*` (path filters do not apply to tags) | ✓ | ✓ + tag = version check | ✓ |
            | manual *Run workflow* (`workflow_dispatch`) | ✓ | ✓ | ✓ |
            | push of any other tag (for example `phase-4`) | — | — | — |

            **Trusted publishing** replaces the API token. TestPyPI is told in advance: "trust
            uploads for `log-analyzer-psbcg433` from repository `psbcg433/python-atlas`,
            workflow `log-analyzer.yml`, environment `testpypi`". At run time:

            ```mermaid
            sequenceDiagram
                participant J as publish job
                participant G as GitHub OIDC provider
                participant T as TestPyPI
                J->>G: request an ID token (needs permissions: id-token: write)
                G-->>J: signed token: repo, workflow, environment, ref
                J->>T: exchange the token
                T-->>J: short-lived upload token, if the claims match the trusted publisher
                J->>T: upload sdist + wheel
            ```

            <details><summary>ASCII fallback</summary>

            ```text
            publish job --(id-token: write)--> GitHub OIDC: "give me an ID token"
            publish job <-- signed token (repo, workflow file, environment, ref)
            publish job --> TestPyPI: exchange token
            publish job <-- upload token valid for minutes, only if the claims match
            publish job --> TestPyPI: upload dist/*
            ```

            </details>

            Nothing secret is stored in the repository, and a token leaked from a log expires
            within minutes. Other design points: the publish job gets `id-token: write` and
            nothing else; it downloads the artifact the build job made, so what was tested is
            what is uploaded; `--locked` everywhere means CI installs exactly `uv.lock`.
            """
        ),
        code(
            """
            show_lines(WORKFLOW_PATH)
            """
        ),
        md(
            """
            > **Warning: YAML 1.1's `on`.** PyYAML implements YAML 1.1, where a bare `on`, `yes`
            > or `off` is a **boolean**. The workflow's `on:` key loads as `True`, so
            > `workflow["on"]` raises `KeyError`. GitHub's own parser does not have this
            > problem; scripts that read workflows do.
            """
        ),
        code(
            """
            import yaml  # PyYAML, in the course environment since Unit 4.5

            workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
            print(f"top-level keys: {[repr(key) for key in workflow]}")
            triggers = workflow[True]
            print(f"events: {list(triggers)}, tags: {triggers['push']['tags']}")
            publish_job = workflow["jobs"]["publish"]
            print(f"publish: needs={publish_job['needs']!r}, permissions={publish_job['permissions']}")
            print(f"publish: environment={publish_job['environment']['name']!r}")
            print(f"publish: if={publish_job['if']!r}")
            print(f"publish steps: {[step['uses'] for step in publish_job['steps']]}")
            """
        ),
        md(
            """
            The build job's tag check, in Python: the shell expression
            `${GITHUB_REF_NAME#log-analyzer-v}` strips the prefix, like `str.removeprefix`. A
            tag that does not match `pyproject.toml` stops the release before anything is
            uploaded.
            """
        ),
        code(
            """
            def tag_matches_version(ref_name: str, version: str) -> bool:
                \"\"\"The build job's check: tag log-analyzer-vX.Y.Z must equal the package version.\"\"\"
                return ref_name.removeprefix("log-analyzer-v") == version


            for ref_name in ("log-analyzer-v0.1.0", "log-analyzer-v0.2.0"):
                print(f"{ref_name}: {tag_matches_version(ref_name, project['version'])}")
            """
        ),
    ]


def _self_check_cells() -> list[NotebookNode]:
    """Step 10: the self-check."""
    return [
        md(
            """
            ### Step 10 — Self-check

            Each syllabus requirement, checked against the real artefacts: the tool runs, the
            wheel, the exports and the workflow file. All checks should pass.
            """
        ),
        code(
            """
            _, mypy_output = run("uv", "run", "--locked", "mypy", "--strict", cwd=PACKAGE_DIR)
            _, pytest_output = run("uv", "run", "--locked", "pytest", "-q", cwd=PACKAGE_DIR)
            coverage_match = re.search(r"Total coverage: ([\\d.]+)%", pytest_output)
            total_coverage = float(coverage_match[1]) if coverage_match else 0.0
            with (PROJECT_DIR / "records.csv").open(encoding="utf-8", newline="") as csv_file:
                csv_row_count = sum(1 for _ in csv.DictReader(csv_file))
            with closing(sqlite3.connect(PROJECT_DIR / "records.db")) as connection:
                (sqlite_row_count,) = connection.execute("SELECT COUNT(*) FROM records").fetchone()
            commands = (["generate", "x"], ["report", "x"], ["export", "x", "y"], ["validate", "x"])
            exit_code_cases = (
                ["validate", "clean.log"],
                ["validate", "access.log.gz"],
                ["report", "missing.log"],
            )
            pytest_addopts = config["tool"]["pytest"]["ini_options"]["addopts"]
            publish_condition = (
                "startsWith(github.ref, 'refs/tags/log-analyzer-v') || github.event_name == 'workflow_dispatch'"
            )
            print(f"{total_coverage=}, {csv_row_count=}, {sqlite_row_count=}")
            """
        ),
        md("**Package checks:** layout, typing, tests, logging, CLI and exports."),
        code(
            """
            run_checks(
                [
                    ("src/ layout", lambda: (PACKAGE_DIR / "src" / "log_analyzer").is_dir(), True),
                    ("no package next to the tests", lambda: (PACKAGE_DIR / "log_analyzer").exists(), False),
                    ("py.typed is in the wheel", lambda: "log_analyzer/py.typed" in wheel_names, True),
                    ("mypy strict configured", lambda: config["tool"]["mypy"]["strict"], True),
                    ("mypy --strict clean", lambda: mypy_output.startswith("Success: no issues"), True),
                    ("coverage >= 90%", lambda: total_coverage >= 90, True),
                    ("coverage gate configured", lambda: "--cov-fail-under=90" in pytest_addopts, True),
                    ("Hypothesis properties exist", lambda: property_source.count("@given("), 11),
                    ("dictConfig logging", lambda: "dictConfig" in inspect.getsource(logging_config), True),
                    (
                        "argparse subcommands",
                        lambda: [cli.build_parser().parse_args(argv).command for argv in commands],
                        ["generate", "report", "export", "validate"],
                    ),
                    (
                        ".gz gives the same report as plain text",
                        lambda: (
                            run("log-analyzer", "-q", "report", "access.log.gz")
                            == run("log-analyzer", "-q", "report", "access.log")
                        ),
                        True,
                    ),
                    (
                        "CSV / JSON / SQLite hold every record",
                        lambda: (csv_row_count, len(exported_records), sqlite_row_count),
                        (19_569, 19_569, 19_569),
                    ),
                    (
                        "exit codes 0 / 1 / 2",
                        lambda: [run("log-analyzer", "-q", *argv)[0] for argv in exit_code_cases],
                        [0, 1, 2],
                    ),
                ]
            )
            """
        ),
        md("**Workflow checks:** where it runs and how it publishes."),
        code(
            """
            run_checks(
                [
                    (
                        "workflow working directory",
                        lambda: workflow["defaults"]["run"]["working-directory"],
                        "projects/log-analyzer",
                    ),
                    ("publish job permissions", lambda: publish_job["permissions"], {"id-token": "write"}),
                    ("publish environment", lambda: publish_job["environment"]["name"], "testpypi"),
                    (
                        "trusted-publishing action",
                        lambda: publish_job["steps"][-1]["uses"],
                        "pypa/gh-action-pypi-publish@release/v1",
                    ),
                    ("publish only on tags or manual runs", lambda: publish_job["if"], publish_condition),
                ]
            )
            """
        ),
    ]


def _publish_cells() -> list[NotebookNode]:
    """How to publish: the steps the learner does on TestPyPI and GitHub."""
    return [
        md(
            """
            ### How to publish

            The notebook built and checked everything; the upload itself happens on GitHub.
            These are the steps you do yourself, once:

            1. **Create a TestPyPI account** at <https://test.pypi.org/account/register/>. It is
               separate from a PyPI account. Verify the email address and turn on two-factor
               authentication.
            2. **Add a pending trusted publisher.** On TestPyPI: *Your account → Publishing →
               Add a new pending publisher → GitHub*, with:

               | Field | Value |
               | --- | --- |
               | PyPI project name | `log-analyzer-psbcg433` |
               | Owner | `psbcg433` |
               | Repository name | `python-atlas` |
               | Workflow name | `log-analyzer.yml` |
               | Environment name | `testpypi` |

               "Pending" because the project does not exist yet: the first successful upload
               creates it and turns the pending publisher into a normal one.
            3. **Create the `testpypi` environment** on GitHub: *repository Settings →
               Environments → New environment → `testpypi`*. GitHub would create it on first use,
               but creating it yourself lets you add protection, for example *Deployment
               branches and tags → Selected → tag rule `log-analyzer-v*`*, or a required
               reviewer.
            4. **Push the commits:** `git push origin main`. The workflow's test and build jobs
               run (publish is skipped); check that the *Actions* tab is green.
            5. **Push the release tag.** Annotated tags are pushed explicitly:

               ```bash
               git tag -a log-analyzer-v0.1.0 -m "log-analyzer 0.1.0"
               git push origin log-analyzer-v0.1.0
               ```

               test → build (the tag must equal `version = "0.1.0"`) → publish.
            6. **Check the result** at <https://test.pypi.org/project/log-analyzer-psbcg433/>,
               then install it from there:

               ```bash
               uvx --index-url https://test.pypi.org/simple/ --from log-analyzer-psbcg433 log-analyzer --version
               ```

            > **Note:** a version can be uploaded only once, even if you delete it later. For the
            > next release, bump the version (`uv version --bump patch` in
            > `projects/log-analyzer/`), commit, and tag `log-analyzer-v0.1.1`. Pushing the
            > course's own `phase-4` tag never publishes: it does not match `log-analyzer-v*`.
            """
        ),
    ]


QUESTIONS: list[tuple[str, str, str, str]] = [
    (
        "4.1",
        """
        import re


        def normalize(name: str) -> str:
            return re.sub(r"[-_.]+", "-", name).lower()


        print(normalize("Log_Analyzer.psbcg433"), normalize("log--analyzer__PSBCG433"))
        """,
        """
        `log-analyzer-psbcg433 log-analyzer-psbcg433`. This is the PEP 503 normalization the
        index applies: runs of `-`, `_` and `.` become one `-`, and case is ignored. Both
        spellings name **the same project**, so nobody can register a look-alike that differs
        only in separators. File names use the other spelling: the wheel is
        `log_analyzer_psbcg433-0.1.0-py3-none-any.whl`.
        """,
        "",
    ),
    (
        "4.1",
        """
        from packaging.version import Version

        releases = ["0.1.0", "0.1.0rc1", "0.1.0.post1", "0.1.0.dev2", "0.1.0a1"]
        print(sorted(releases, key=Version))
        """,
        """
        `['0.1.0.dev2', '0.1.0a1', '0.1.0rc1', '0.1.0', '0.1.0.post1']`. PEP 440 order:
        development releases, then pre-releases (alpha, beta, release candidate), then the
        final release, then post-releases. A plain string sort would put `0.1.0` first.
        `>=0.1.0` excludes the dev and pre-releases unless you opt in.
        """,
        "",
    ),
    (
        "4.1",
        """
        from importlib.metadata import PackageNotFoundError, version

        for name in ("pytest", "log-analyzer-psbcg433"):
            try:
                version(name)
                print(f"{name}: installed here")
            except PackageNotFoundError as error:
                print(f"{name}: {type(error).__name__}")
        """,
        """
        ```text
        pytest: installed here
        log-analyzer-psbcg433: PackageNotFoundError
        ```

        `importlib.metadata` reads the `.dist-info` folders of the **running** environment.
        The kernel runs in the course's `.venv`; the package is installed only in its own
        `projects/log-analyzer/.venv`. Being importable (the setup cell put `src/` on
        `sys.path`) is not the same as being installed, which is why `log_analyzer.__version__`
        showed `0.0.0+unknown` in Step 4.
        """,
        "",
    ),
    (
        "4.1",
        """
        wheel_name = "log_analyzer_psbcg433-0.1.0-py3-none-any.whl"
        print(wheel_name.removesuffix(".whl").split("-"))
        """,
        """
        `['log_analyzer_psbcg433', '0.1.0', 'py3', 'none', 'any']`: name, version, then the
        three-part tag. `py3` = any Python 3, `none` = no compiled ABI, `any` = any platform. A
        pure-Python wheel installs everywhere, which is why one wheel is enough here, while a
        package with C extensions publishes one wheel per platform. Dashes inside the name
        become underscores precisely so this split works.
        """,
        "",
    ),
    (
        "4.2",
        """
        from log_analyzer.models import AccessRecord

        record = AccessRecord("2026-11-06T09:00:00Z", "10.0.0.1", "GET", "/", "200", 5)
        print(repr(record.status), record.status == 200)
        """,
        """
        `'200' False`. Annotations are **not enforced at runtime**: `NamedTuple` stores
        whatever it gets. `mypy --strict` would reject this call
        (`Argument 5 has incompatible type "str"; expected "int"`), which is exactly why the
        package runs mypy in CI. Runtime validation is a different tool (question 18).
        """,
        "",
    ),
    (
        "4.2",
        """
        from log_analyzer.report import EndpointStats

        row = {"endpoint": "GET /health", "requests": 2, "p95_ms": 6}
        try:
            print(isinstance(row, EndpointStats))
        except TypeError as error:
            print(f"{type(error).__name__}: {error}")
        """,
        """
        `TypeError: TypedDict does not support instance and class checks`. A `TypedDict`
        describes the *shape* of a plain `dict` for the type checker; at runtime the row is just
        a `dict` and there is no class to check against. Narrow with a `TypeGuard`/`TypeIs`
        function or validate with Pydantic instead.
        """,
        "",
    ),
    (
        "4.2",
        """
        from log_analyzer.export import ExportFormat

        print(type(ExportFormat).__name__, ExportFormat.__value__)
        """,
        """
        `TypeAliasType typing.Literal['csv', 'json', 'sqlite']`. The `type` statement
        (*New in 3.12*, PEP 695) creates a `TypeAliasType` object, and its value is evaluated
        **lazily**, when `__value__` is first read. That is why `requires-python` is `>=3.12`:
        on 3.11 `export.py` would be a `SyntaxError`.
        """,
        "",
    ),
    (
        "4.3",
        """
        import logging.config

        from log_analyzer.logging_config import build_logging_config

        logging.config.dictConfig(build_logging_config("INFO"))
        child = logging.getLogger("log_analyzer.export")
        print(child.level, child.getEffectiveLevel(), child.isEnabledFor(logging.DEBUG))
        """,
        """
        `0 20 False`. `dictConfig` set the level on `log_analyzer` only; the child's own level
        stays `NOTSET` (0), so its **effective** level is inherited from the nearest ancestor
        with a level: INFO (20). DEBUG is below that, so `logger.debug(...)` calls in
        `export.py` return almost immediately. This is why each module only needs
        `getLogger(__name__)`.
        """,
        """
        import logging
        import logging.config

        from log_analyzer.logging_config import LOGGER_NAME, build_logging_config

        logging.config.dictConfig(build_logging_config("INFO"))
        child = logging.getLogger("log_analyzer.export")
        print(child.level, child.getEffectiveLevel(), child.isEnabledFor(logging.DEBUG))

        package_logger = logging.getLogger(LOGGER_NAME)  # restore the library default
        for handler in package_logger.handlers[:]:
            package_logger.removeHandler(handler)
        package_logger.addHandler(logging.NullHandler())
        package_logger.setLevel(logging.NOTSET)
        package_logger.propagate = True
        """,
    ),
    (
        "4.3",
        """
        import logging

        # The root logger has no handlers (a script that never configured logging).
        library_logger = logging.getLogger("demo.library")
        library_logger.addHandler(logging.NullHandler())
        library_logger.warning("disk almost full (library)")
        logging.getLogger("demo.script").warning("disk almost full (script)")
        """,
        """
        Only `disk almost full (script)` appears (on stderr). When no handler at all is found
        on the way up to the root, `logging` falls back to `logging.lastResort`, which prints
        WARNING and above to stderr. The library logger *has* a handler, a `NullHandler` that
        discards everything, so the fallback never kicks in. That is the recommended set-up for
        a library: silent until the application configures logging. The proof cell empties the
        root logger's handlers first (and restores them), because earlier cells in this
        notebook may have added some.
        """,
        """
        import logging

        root_logger = logging.getLogger()
        saved_handlers = root_logger.handlers[:]
        root_logger.handlers.clear()  # as in a script that never configured logging
        try:
            library_logger = logging.getLogger("demo.library")
            library_logger.addHandler(logging.NullHandler())
            library_logger.warning("disk almost full (library)")
            logging.getLogger("demo.script").warning("disk almost full (script)")
        finally:
            root_logger.handlers[:] = saved_handlers
        """,
    ),
    (
        "4.3",
        """
        from hypothesis import given, settings
        from hypothesis import strategies as st

        calls: list[bool] = []


        @settings(max_examples=100, database=None)
        @given(st.booleans())
        def test_flag(flag: bool) -> None:
            calls.append(flag)


        test_flag()
        print(len(calls), sorted(set(calls)))
        """,
        """
        `2 [False, True]`, not 100. `max_examples` is an upper bound: Hypothesis notices that
        `st.booleans()` has only two possible values, tries both, and stops because the search
        space is exhausted. Calling a `@given` test directly runs the whole search, as pytest
        does.
        """,
        "",
    ),
    (
        "4.4",
        """
        from log_analyzer.cli import build_parser

        args = build_parser().parse_args(["-vv", "report", "access.log", "--top", "3"])
        print(args.verbose, args.quiet, args.command, args.top, type(args.log).__name__)
        """,
        """
        `2 False report 3 PosixPath`. `action="count"` counts repeated flags (`-vv` → 2),
        `store_true` defaults to `False`, `dest="command"` records which subparser ran, and
        `type=` converts the strings (`positive_int`, `Path`). The class is `WindowsPath` on
        Windows.
        """,
        "",
    ),
    (
        "4.4",
        """
        from log_analyzer.analysis import ID_SEGMENT

        print(ID_SEGMENT.sub("/{id}", "/api/v2/orders/42/items/7"))
        print(ID_SEGMENT.sub("/{id}", "/reports/2026.csv"))
        """,
        """
        ```text
        /api/v2/orders/{id}/items/{id}
        /reports/2026.csv
        ```

        The pattern is `/\\d+(?=/|$)`: a slash, digits, then a **lookahead** for another slash
        or the end of the string. `v2` does not start with a digit after the slash, and
        `2026.csv` has `.` after the digits, so neither is an id. The lookahead checks the next
        character without consuming it, so `/42/items` keeps its slash for the next match.
        """,
        "",
    ),
    (
        "4.4",
        """
        import datetime as dt

        moment = dt.datetime(999, 12, 31, 23, 59)
        print(moment.strftime("%Y-%m-%d"), moment.isoformat(timespec="seconds"))
        """,
        """
        On 3.15: `0999-12-31 0999-12-31T23:59:00`. On 3.12 and 3.13 (Linux, glibc) the first
        part is `999-12-31`: `strftime` delegates to the C library, and before 3.14 Python did
        not pad `%Y` to four digits there. `isoformat()` is Python's own code and always pads.
        This is the bug Hypothesis found in the CI matrix (Step 6).
        """,
        "",
    ),
    (
        "4.5",
        """
        import json

        status_counts = {200: 15690, 404: 580}
        round_trip = json.loads(json.dumps(status_counts))
        print(round_trip, round_trip == status_counts)
        """,
        """
        `{'200': 15690, '404': 580} False`. JSON object keys are always strings, so
        `json.dumps` converts the `int` keys and `json.loads` cannot know they were numbers. A
        JSON round trip is not an identity. `summary_document` therefore converts the status
        codes to strings itself, and its `TypedDict` says `dict[str, int]`.
        """,
        "",
    ),
    (
        "4.5",
        """
        import csv
        import io

        buffer = io.StringIO()
        csv.writer(buffer).writerow(["GET", "/search?q=a,b", 200])
        print(repr(buffer.getvalue()))
        """,
        """
        `'GET,"/search?q=a,b",200\\r\\n'`. The field containing a comma is quoted, and the row
        ends with `\\r\\n` (RFC 4180), not `\\n`. That is why CSV files must be opened with
        `newline=""`: otherwise text mode on Windows would turn `\\n` into `\\r\\n` and the file
        would end every row with `\\r\\r\\n`.
        """,
        "",
    ),
    (
        "4.5",
        """
        import sqlite3

        connection = sqlite3.connect(":memory:")
        with connection:
            connection.execute("CREATE TABLE hits (n INTEGER)")
            connection.execute("INSERT INTO hits VALUES (7)")
        print(connection.execute("SELECT n * 2, n / 2 FROM hits").fetchone())
        connection.close()
        """,
        """
        `(14, 3)`. Two surprises: `with connection:` **commits** (or rolls back) but does *not*
        close the connection, so the query after the block works; and SQLite divides two
        integers as integers (`7 / 2` is `3`). `write_sqlite` uses `closing(...)` for the close
        and `with connection:` for the transaction.
        """,
        "",
    ),
    (
        "4.5",
        """
        import gzip

        first = gzip.compress(b"GET /health", mtime=0)
        second = gzip.compress(b"GET /health", mtime=0)
        print(first[:2], first == second)
        """,
        """
        `b'\\x1f\\x8b' True`. Every gzip stream starts with the magic bytes `1f 8b`, which is how
        `is_gzip_file` recognizes compressed logs whatever their name. The header also stores a
        modification time; with the default (`mtime=None`, the current time) two compressions of
        the same data can differ. Fixing it at 0 makes the output reproducible, the trick
        `generate.py` uses.
        """,
        "",
    ),
    (
        "4.6",
        """
        from pydantic import BaseModel


        class Hit(BaseModel):
            status: int
            latency_ms: int


        hit = Hit(status="200", latency_ms=23.0)
        print(repr(hit.status), repr(hit.latency_ms))
        """,
        """
        `200 23`. Unlike `NamedTuple` (question 5), Pydantic **validates and converts** at
        runtime. In its default *lax* mode, the string `"200"` and the float `23.0` (no
        fractional part) are accepted and converted to `int`; `23.5` or `"abc"` would raise
        `ValidationError`.
        """,
        "",
    ),
    (
        "4.6",
        """
        from pydantic import BaseModel, ConfigDict, ValidationError


        class StrictHit(BaseModel):
            model_config = ConfigDict(strict=True)
            status: int
            latency_ms: int


        try:
            StrictHit(status="200", latency_ms=23.0)
        except ValidationError as error:
            print(error.error_count(), [detail["type"] for detail in error.errors()])
        """,
        """
        `2 ['int_type', 'int_type']`. Strict mode turns the conversions off: only real `int`
        values pass. Pydantic reports **every** failing field in one `ValidationError`, not
        just the first: the same "collect everything" idea as the log analyzer's strict mode
        and its `ExceptionGroup`.
        """,
        "",
    ),
    (
        "4.6",
        """
        import json

        import orjson

        document = {"status_counts": {"200": 3}, "p95_latency_ms": None}
        compact = orjson.dumps(document)
        print(type(compact).__name__, compact == json.dumps(document).encode())
        """,
        """
        `bytes False`. `orjson.dumps` returns **bytes** (UTF-8), not `str`. Even after encoding,
        the outputs differ: `json.dumps` puts a space after `:` and `,` by default, while orjson
        writes the compact form `{"status_counts":{"200":3},"p95_latency_ms":null}`. Same data,
        different bytes, so never compare JSON documents as text.
        """,
        "",
    ),
]


def _question_cells() -> list[NotebookNode]:
    """The 20 predict-the-output questions covering Phase 4."""
    unit_counts: dict[str, int] = {}
    for unit, *_ in QUESTIONS:
        unit_counts[unit] = unit_counts.get(unit, 0) + 1
    coverage_rows = "\n".join(
        f"            | {unit} | {count} |" for unit, count in unit_counts.items()
    )
    cells = [
        md(
            f"""
            ### Phase 4 review — 20 predict-the-output questions

            Twenty short snippets, at least three from every unit of the phase, several of them
            using the package you just built. For each one, decide what it prints **before**
            opening the answer, then run the proof cell. If a question surprises you, go back to
            the unit it names.

            | Unit | Questions |
            | --- | --- |
{coverage_rows}
            """
        )
    ]
    for question_number, (unit, snippet, answer, proof) in enumerate(QUESTIONS, start=1):
        cells.append(md(f"#### Question {question_number} — Unit {unit}"))
        cells.extend(predict_cells(snippet=snippet, answer=answer, proof=proof or snippet))
    return cells


def _closing_cells() -> list[NotebookNode]:
    """Phase 4 closing."""
    return [
        md(
            """
            ### Phase 4 complete

            You took notebook code and shipped it: a `src/`-layout package with its own lockfile,
            a typed public API that `mypy --strict` and its users' type checkers can rely on, a
            pytest + Hypothesis suite that fails the build under 90% coverage, logging that
            stays silent in a library and configurable in a CLI, an `argparse` tool with
            subcommands, gzip input and three export formats, and a CI pipeline that tests on
            four Python versions and publishes with short-lived OIDC credentials instead of
            stored secrets.

            **Next: Phase 5 — Concurrency, Async and Performance.** Threads, processes,
            `asyncio`, the free-threaded build and profiling. `log-analyzer generate` can produce
            logs of any size, which makes the analyzer a ready-made benchmark: is parsing CPU-bound
            or I/O-bound, and what does a process pool do to it?
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for the Phase 4 Project and the closing review."""
    return [
        *_overview_cells(),
        *_decision_cells(),
        *_pyproject_cells(),
        *_environment_cells(),
        *_code_tour_cells(),
        *_cli_cells(),
        *_test_cells(),
        *_typing_cells(),
        *_build_cells(),
        *_workflow_cells(),
        *_self_check_cells(),
        *_publish_cells(),
        *_question_cells(),
        *_closing_cells(),
    ]
