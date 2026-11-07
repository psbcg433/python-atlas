"""Phase 3 Project — Internals Toolkit, closing with 15 predict-the-output questions."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

PROJECT_SETUP_SOURCE = '''
import ast
import importlib
import inspect
import json
import os
import platform
import subprocess
import sys
import sysconfig
import tempfile
import textwrap
import tracemalloc
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

CHILD_ENV = {**os.environ, "PYTHON_COLORS": "0"}
PROJECTS_DIR = find_repo_root() / "projects"
if str(PROJECTS_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECTS_DIR))  # so the notebook can import pyinspect

import pyinspect  # noqa: E402
from pyinspect import examples, scanner  # noqa: E402


def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"


def interpreter_label() -> str:
    """Implementation, version and build flavour of the running interpreter."""
    free_threaded = bool(sysconfig.get_config_var("Py_GIL_DISABLED"))
    build = "free-threaded build" if free_threaded else "default (GIL) build"
    implementation = platform.python_implementation()
    return f"{implementation} {platform.python_version()}, {build}, {platform.machine()}"


def run_pyinspect(*arguments: str, cwd: Path = PROJECTS_DIR) -> tuple[int, str]:
    """Run `python -m pyinspect ...` in a child process; return (exit status, output)."""
    completed = subprocess.run(
        [sys.executable, "-m", "pyinspect", *arguments],
        capture_output=True, text=True, cwd=cwd, timeout=120,
        env={**CHILD_ENV, "PYTHONPATH": str(PROJECTS_DIR)},
    )  # fmt: skip
    return completed.returncode, (completed.stdout + completed.stderr).strip()


def run_python(*arguments: str, cwd: Path | None = None) -> str:
    """Run the kernel's interpreter in a child process; return stdout and stderr, stripped."""
    completed = subprocess.run(
        [sys.executable, *arguments],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=CHILD_ENV,
        timeout=120,
    )
    return (completed.stdout + completed.stderr).strip()


@contextmanager
def temporary_modules(files: dict[str, str]) -> Iterator[Path]:
    """Write modules to a temporary folder first on sys.path; forget them afterwards (Unit 3.3)."""
    with tempfile.TemporaryDirectory(prefix="project3_") as folder:
        root = Path(folder)
        for relative_path, text in files.items():
            (root / relative_path).parent.mkdir(parents=True, exist_ok=True)
            (root / relative_path).write_text(textwrap.dedent(text))
        sys.path.insert(0, folder)
        importlib.invalidate_caches()
        try:
            yield root
        finally:
            sys.path.remove(folder)
            for name, module in list(sys.modules.items()):
                if str(getattr(getattr(module, "__spec__", None), "origin", "") or "").startswith(
                    folder
                ):
                    del sys.modules[name]


def write_tree(root: Path, files: dict[str, str]) -> None:
    """Write {relative path: source} under root (dedented, leading blank line removed)."""
    for relative_path, text in files.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(text).lstrip("\\n"))


print(interpreter_label())
print(f"pyinspect {pyinspect.__version__} from {Path(pyinspect.__file__).parent.parent.name}/")
'''


def _overview_cells() -> list[NotebookNode]:
    """Project introduction, setup and Step 1."""
    return [
        md(
            """
            ## Phase 3 Project — Internals Toolkit

            Build `pyinspect`, a small command-line toolkit that turns this phase's
            instruments into reusable tools, run with `python -m pyinspect`:

            | Requirement | Command | Built on |
            | --- | --- | --- |
            | A memory-profiler wrapper around `tracemalloc` reporting the top allocating lines of any callable | `memory module:function` | 3.1.11–3.1.12, Lab 3.1 exercise 6 |
            | An AST-based code scanner | `scan PATH...` | 3.2.2, 3.2.12, Lab 3.2 exercises 3 and 7 |
            | An import-time report | `imports MODULE` | 3.3.12, Lab 3.3 exercise 6 |
            | A package run with `python -m` | `__main__.py` | 3.3.6, 3.3.8 |

            The code outgrows a notebook, so it lives in a real package in the repository's
            `projects/` folder:

            ```text
            projects/pyinspect/
            ├── __init__.py     version + lazy re-exports of the public API (3.3.12)
            ├── __main__.py     `python -m pyinspect` entry point (3.3.8)
            ├── cli.py          argparse subcommands and exit codes
            ├── memory.py       profile_allocations, format_memory_report
            ├── scanner.py      rule registry, scan_source, scan_paths, format_findings
            ├── importtime.py   parse_importtime, import_subtree, measure_import, format_import_report
            └── examples.py     sample workloads for the memory command
            ```

            Each step reads the relevant code with `inspect.getsource` (so the notebook always
            shows the real file), uses it from the notebook, then runs the same feature from
            the command line in a child process.

            > **Note:** memory sizes and import times vary by machine and Python version; the
            > self-check in Step 6 compares relationships, never exact numbers. `pyinspect`
            > needs Python 3.15 because it uses `lazy` imports.

            ### Step 1 — the package and `python -m pyinspect`

            The setup cell puts `projects/` on `sys.path` so the notebook can import the
            package, and defines `run_pyinspect(*arguments, cwd=PROJECTS_DIR)` to run the CLI in a
            child process (as you would in a terminal), plus the Unit 3.3 helpers the review
            questions need.
            """
        ),
        code(PROJECT_SETUP_SOURCE),
        md("The files on disk:"),
        code(
            """
            package_dir = PROJECTS_DIR / "pyinspect"
            for path in sorted(package_dir.glob("*.py")):
                print(f"{path.name:<14} {len(path.read_text().splitlines()):>4} lines")
            """
        ),
        md(
            """
            `__main__.py` is a two-line shim that calls `cli.main()` and turns its return value
            into the exit status, so the logic stays importable and testable (3.3.8). The CLI
            uses `argparse` subcommands and three exit codes: 0 success, 1 findings (for
            `scan`, so CI can fail a build), 2 usage errors.
            """
        ),
        code(
            """
            print((package_dir / "__main__.py").read_text())
            status, output = run_pyinspect("--version")
            print(f"python -m pyinspect --version -> {output!r} (exit {status})")
            status, output = run_pyinspect("--help")
            print("\\n".join(output.splitlines()[:9]))
            """
        ),
        md(
            """
            **Lazy re-exports.** `pyinspect/__init__.py` re-exports the public API with
            `lazy from ... import ...` (3.3.12), so `import pyinspect` loads only the package
            itself; each submodule loads on first use. The kernel imported `examples` and
            `scanner` explicitly; the other two are still pending:
            """
        ),
        code(
            """
            lazy_lines = [line for line in inspect.getsource(pyinspect).splitlines() if line.startswith("lazy")]
            print("\\n".join(lazy_lines))
            loaded = sorted(name for name in sys.modules if name.startswith("pyinspect."))
            print(f"submodules loaded so far: {loaded}")
            print(f"{type(vars(pyinspect)['measure_import']).__name__=}  (still a lazy proxy)")
            """
        ),
    ]


def _memory_cells() -> list[NotebookNode]:
    """Step 2 — the memory profiler."""
    return [
        md(
            """
            ### Step 2 — a memory profiler around `tracemalloc`

            `profile_allocations(function, *args, top=10, min_bytes=1024, **kwargs)` returns a
            `MemoryReport` with:

            - `peak_bytes`: the highest extra memory **during** the call (temporaries included),
              from `tracemalloc.reset_peak()` and `get_traced_memory()`,
            - `retained_bytes` and `sites`: memory **still held** when the call returned
              (its return value, caches, leaks), from a snapshot diff grouped by line,
            - the callable's `result`.

            Design points from Unit 3.1: tracing is started only if it was off and stopped
            again in `finally`; frames from `tracemalloc` itself are filtered out; a warm-up
            `filter_traces` call compiles the filter patterns **before** the first snapshot
            (otherwise the regex cache's own allocations would show up as "allocating
            lines"), and lines below `min_bytes` are dropped as noise.
            """
        ),
        code(
            """
            print(inspect.getsource(pyinspect.profile_allocations))
            """
        ),
        md(
            """
            **From the notebook.** Any callable works, including one defined in a cell (its
            source lines come from `linecache`, 3.1.11; the "file" of a notebook cell is a
            generated number). The returned index is what stays in memory.
            """
        ),
        code(
            '''
            def build_order_index(order_count: int) -> dict[int, dict[str, object]]:
                """Index of fake orders by id."""
                return {order_id: {"id": order_id, "items": ["TEA-01"] * 3} for order_id in range(order_count)}


            order_report = pyinspect.profile_allocations(build_order_index, 30_000, top=3)
            print(pyinspect.format_memory_report(order_report))
            print(f"result: {len(order_report.result):,} orders; tracing left on: {tracemalloc.is_tracing()}")
            '''
        ),
        md(
            """
            **Spotting a leak.** `examples.fill_price_cache` adds entries to a module-level dict
            that is never emptied (3.1.12). Profiling it twice in the same process shows memory
            retained **every** time at the same line: the signature of a leak. The cache is
            emptied afterwards.
            """
        ),
        code(
            """
            for attempt in (1, 2):
                leak_report = pyinspect.profile_allocations(examples.fill_price_cache, top=1)
                retained = pyinspect.memory.format_bytes(leak_report.retained_bytes)
                top_site = leak_report.sites[0]
                print(f"call {attempt}: retained {retained} at {top_site.location}: {top_site.source}")
            examples._PRICE_CACHE.clear()
            """
        ),
        md(
            """
            **From the command line.** `memory module:function` imports the target in a fresh
            interpreter and calls it with no arguments. A function that only churns temporaries
            has a high peak and retains nothing. A bad target exits with status 2.
            """
        ),
        code(
            """
            for target in ("pyinspect.examples:build_price_table", "pyinspect.examples:churn_temporaries"):
                status, output = run_pyinspect("memory", target, "--top", "2")
                print(f"$ python -m pyinspect memory {target}   (exit {status})\\n{output}\\n")
            print(run_pyinspect("memory", "pyinspect.examples:no_such_function"))
            """
        ),
    ]


def _scanner_cells() -> list[NotebookNode]:
    """Step 3 — the AST scanner."""
    return [
        md(
            """
            ### Step 3 — an AST-based code scanner

            Rules are plain functions registered with a decorator (the registry pattern from
            Units 1.12 and 2.6). Each takes the parsed module and yields `(node, message)` pairs;
            `scan_source` turns them into sortable `Finding` dataclasses (`path`, `line`,
            `column`, `code`, `message`). A file that does not parse yields one `E999`
            finding instead of crashing the scan. The registered rules, and one rule's code:
            """
        ),
        code(
            """
            for registered in pyinspect.RULES.values():
                print(f"{registered.code}  {registered.description:<38} ({registered.check.__name__})")
            print()
            print(inspect.getsource(scanner.missing_docstrings))
            """
        ),
        md(
            """
            **Scanning a sample project.** `scan_paths` accepts files and folders, skips
            `__pycache__` and dot-folders, sorts findings by path, line and column, and can
            report paths relative to a folder. The same scan runs through the CLI from inside
            the project folder; it exits with status 1 because there are findings, and
            `--json` gives machine-readable output.
            """
        ),
        code(
            '''
            SAMPLE_PROJECT = {
                "app/handlers.py": """
                    def handle(event, seen=[]):
                        try:
                            return eval(event["expression"])
                        except:
                            return None
                    """,
                "app/models.py": """
                    class Order:
                        def total(self):
                            return 0

                        def _private(self):
                            return 1
                    """,
                "app/clean.py": (
                    '"""Clean module."""\\n\\n\\ndef ok(value=None):\\n    """Return value."""\\n    return value\\n'
                ),
                "app/broken.py": "def broken(:\\n    pass\\n",
                "app/.cache/ignored.py": "def ignored(x=[]):\\n    pass\\n",
            }
            with tempfile.TemporaryDirectory() as folder:
                write_tree(Path(folder), SAMPLE_PROJECT)
                sample_findings = pyinspect.scan_paths([Path(folder) / "app"], relative_to=folder)
                cli_status, cli_text = run_pyinspect("scan", "app", cwd=Path(folder))
                json_status, json_text = run_pyinspect("scan", "app", "--json", cwd=Path(folder))
            print(pyinspect.format_findings(sample_findings))
            same_text = cli_text == pyinspect.format_findings(sample_findings)
            print(f"\\nCLI exit status: {cli_status}; same text as in-process: {same_text}")
            print(f"--json: {len(json.loads(json_text))} findings, first = {json.loads(json_text)[0]}")
            '''
        ),
        md(
            """
            **Extending the scanner.** A new rule is one decorated function. The cell
            registers a rule against `global` statements, scans a snippet, and removes the rule
            again so later cells see the original rule set.
            """
        ),
        code(
            '''
            @scanner.rule("W001", "global statement")
            def global_statements(tree: ast.Module) -> Iterator[tuple[ast.AST, str]]:
                """`global` makes functions depend on hidden module state (1.11)."""
                for node in ast.walk(tree):
                    if isinstance(node, ast.Global):
                        yield node, f"global statement for {', '.join(node.names)}"


            try:
                snippet = 'COUNT = 0\\n\\n\\ndef bump():\\n    """Add one."""\\n    global COUNT\\n    COUNT += 1\\n'
                for finding in pyinspect.scan_source(snippet, "counter.py"):
                    print(finding)
            finally:
                del pyinspect.RULES["W001"]
            print(f"rules now: {list(pyinspect.RULES)}")
            '''
        ),
    ]


def _importtime_cells() -> list[NotebookNode]:
    """Step 4 — the import-time report."""
    return [
        md(
            """
            ### Step 4 — an import-time report

            `measure_import(module)` runs `python -X importtime -c "import module"` in a fresh
            interpreter (the child gets the caller's `sys.path`), and `parse_importtime` turns
            each line into an `ImportTiming(module, self_us, cumulative_us, depth)`; the module
            name is validated first, because it is pasted into `-c` code.

            The report must not count the interpreter's own start-up imports (`site`,
            `codecs`, ...), which `-X importtime` also prints. CPython prints a module **after**
            its dependencies, indented deeper, so `import_subtree` takes the target's line and
            the run of deeper lines just above it. On a fixed sample:
            """
        ),
        code(
            '''
            SAMPLE_REPORT = """
            import time: self [us] | cumulative | imported package
            import time:       300 |        300 |   encodings.utf_8
            import time:       500 |        800 | site
            import time:       120 |        120 |     _json
            import time:       400 |        520 |   json.decoder
            import time:       210 |        210 |   json.encoder
            import time:       650 |       1380 | json
            """
            sample_timings = pyinspect.parse_importtime(SAMPLE_REPORT)
            print(f"parsed {len(sample_timings)} lines; first: {sample_timings[0]}")
            json_subtree = pyinspect.import_subtree(sample_timings, "json")
            print(f"subtree of json: {[timing.module for timing in json_subtree]}")
            print(pyinspect.format_import_report("json", sample_timings, top=2))
            print(inspect.getsource(pyinspect.importtime.import_subtree).split('"""')[-1].rstrip())
            '''
        ),
        md(
            """
            **Real measurements** through the CLI (times vary by machine and run). `os` is
            already loaded at start-up, so there is nothing to report; an unknown module exits
            with status 2.
            """
        ),
        code(
            """
            for module_name in ("json", "asyncio", "os", "no_such_module"):
                status, output = run_pyinspect("imports", module_name, "--top", "3")
                print(f"$ python -m pyinspect imports {module_name}   (exit {status})\\n{output}\\n")
            """
        ),
    ]


def _self_inspection_cells() -> list[NotebookNode]:
    """Step 5 — pyinspect inspects itself."""
    return [
        md(
            """
            ### Step 5 — the toolkit inspects itself

            Three checks on `pyinspect` with its own tools:

            1. **scan**: the package passes its own rules (exit status 0).
            2. **imports**: thanks to the lazy re-exports, importing `pyinspect` loads one
               module.
            3. **memory**: what does scanning a real package (the standard library's `json`)
               cost? `profile_allocations` forwards extra keyword arguments to the callable.
            """
        ),
        code(
            """
            status, output = run_pyinspect("scan", "pyinspect")
            print(f"scan pyinspect -> {output!r} (exit {status})")
            status, output = run_pyinspect("imports", "pyinspect")
            print(output)
            json_package = Path(json.__file__).parent
            scan_report = pyinspect.profile_allocations(
                pyinspect.scan_paths, [json_package], relative_to=json_package.parent, top=2
            )
            print(f"\\nscanning the json package: {len(scan_report.result)} findings")
            print(pyinspect.format_memory_report(scan_report))
            """
        ),
    ]


def _self_check_cells() -> list[NotebookNode]:
    """Step 6 — self-check."""
    return [
        md(
            """
            ### Step 6 — self-check

            Twelve checks against the requirements. They compare relationships (bigger than,
            same line, exit status), never exact byte counts or timings.
            """
        ),
        code(
            """
            def price_table_report() -> pyinspect.MemoryReport:
                return pyinspect.profile_allocations(examples.build_price_table)


            def churn_is_peak_only() -> bool:
                report = pyinspect.profile_allocations(examples.churn_temporaries)
                return report.retained_bytes * 10 < report.peak_bytes


            def sample_scan() -> list[tuple[str, int, str]]:
                with tempfile.TemporaryDirectory() as folder:
                    write_tree(Path(folder), SAMPLE_PROJECT)
                    findings = pyinspect.scan_paths([Path(folder) / "app"], relative_to=folder)
                return [(finding.path, finding.line, finding.code) for finding in findings]


            EXPECTED_SAMPLE = [
                ("app/broken.py", 1, "E999"),
                ("app/handlers.py", 1, "D103"),
                ("app/handlers.py", 1, "B006"),
                ("app/handlers.py", 3, "S307"),
                ("app/handlers.py", 4, "E722"),
                ("app/models.py", 2, "D103"),
            ]
            run_checks(
                [
                    (
                        "CLI --version",
                        lambda: run_pyinspect("--version"),
                        (0, f"pyinspect {pyinspect.__version__}"),
                    ),
                    (
                        "memory: top line is the list",
                        lambda: "return [" in price_table_report().sites[0].source,
                        True,
                    ),
                    (
                        "memory: retains over 1 MB",
                        lambda: price_table_report().retained_bytes > 1_000_000,
                        True,
                    ),
                    ("memory: temporaries are peak only", churn_is_peak_only, True),
                    (
                        "memory: tracing left off",
                        lambda: (pyinspect.profile_allocations(len, "abc"), tracemalloc.is_tracing())[1],
                        False,
                    ),
                    (
                        "memory: top must be >= 1",
                        lambda: raised_error_name(lambda: pyinspect.profile_allocations(len, "a", top=0)),
                        "ValueError",
                    ),
                    ("scan: sample findings", sample_scan, EXPECTED_SAMPLE),
                    ("scan: CLI exit status on pyinspect", lambda: run_pyinspect("scan", "pyinspect")[0], 0),
                    (
                        "imports: subtree excludes start-up",
                        lambda: [t.module for t in pyinspect.import_subtree(sample_timings, "json")],
                        ["_json", "json.decoder", "json.encoder", "json"],
                    ),
                    (
                        "imports: lazy pyinspect loads one module",
                        lambda: len(
                            pyinspect.import_subtree(pyinspect.measure_import("pyinspect"), "pyinspect")
                        ),
                        1,
                    ),
                    (
                        "imports: code injection refused",
                        lambda: raised_error_name(lambda: pyinspect.measure_import("os; print(1)")),
                        "ValueError",
                    ),
                    ("CLI: bad target exits 2", lambda: run_pyinspect("memory", "nope")[0], 2),
                ]
            )
            """
        ),
    ]


QUESTIONS: list[tuple[str, str, str, str]] = [
    # (unit, snippet, answer, proof); proof is the snippet unless given separately
    (
        "3.1",
        """
        import weakref

        try:
            weakref.ref([1, 2])
        except TypeError as error:
            print(type(error).__name__)
        """,
        """
        `TypeError`. Built-in `list`, `dict`, `tuple`, `int` and `str` objects have no slot
        for weak references (3.1.8). Instances of your own classes (even a `list` subclass)
        can be weakly referenced.
        """,
        "",
    ),
    (
        "3.1",
        """
        import weakref


        class Box:
            pass


        log = []
        box = Box()
        weakref.finalize(box, log.append, "freed")
        alias = box
        del box
        log.append("after del")
        del alias
        print(log)
        """,
        """
        `['after del', 'freed']`. `del box` removes one of two references, so the object
        survives; the finalizer runs at `del alias`, when the count reaches zero (3.1.3).
        """,
        "",
    ),
    (
        "3.1",
        """
        import functools, gc, weakref

        class Engine:
            @functools.cache
            def quote(self, sku):
                return len(sku)

        engine = Engine()
        engine.quote("TEA-01")
        probe = weakref.ref(engine)
        del engine
        gc.collect()
        print(probe() is not None)
        """,
        """
        `True`. The cache lives on the class and its keys include `self`, so it keeps the
        instance alive; not even `gc.collect()` can free it (3.1.12).
        """,
        """
        import functools
        import gc
        import weakref


        class Engine:
            @functools.cache  # noqa: B019 (the leak being asked about)
            def quote(self, sku: str) -> int:
                return len(sku)


        engine = Engine()
        engine.quote("TEA-01")
        probe = weakref.ref(engine)
        del engine
        gc.collect()
        print(probe() is not None)
        Engine.quote.cache_clear()  # release it again
        """,
    ),
    (
        "3.1",
        """
        print(int("1000") is int("1000"))
        """,
        """
        `True` on 3.15, `False` on 3.14 and earlier. The small-int cache covers -5 to 1024
        since 3.15 (it ended at 256 before), so both calls return the same immortal object
        (3.1.10). Never rely on `is` for numbers.
        """,
        "",
    ),
    (
        "3.1",
        """
        import gc

        saved = []

        class Phoenix:
            calls = 0

            def __del__(self):
                Phoenix.calls += 1
                saved.append(self)

        bird = Phoenix()
        del bird
        saved.clear()
        gc.collect()
        print(Phoenix.calls)
        """,
        """
        `1`. The first `__del__` resurrects the object by storing it in `saved`. When it dies
        again, PEP 442 guarantees the finalizer is not called a second time (3.1.7).
        """,
        """
        import gc

        saved = []


        class Phoenix:
            calls = 0

            def __del__(self) -> None:
                Phoenix.calls += 1
                saved.append(self)


        bird = Phoenix()
        del bird
        saved.clear()
        gc.collect()
        print(Phoenix.calls)
        """,
    ),
    (
        "3.2",
        """
        def kib():
            return 2 ** 10

        print(1024 in kib.__code__.co_consts)
        """,
        """
        `True`. The compiler folds `2 ** 10` into the constant `1024` (3.2.6); the function
        just loads it.
        """,
        """
        def kib() -> int:
            return 2**10


        print(1024 in kib.__code__.co_consts)
        """,
    ),
    (
        "3.2",
        """
        import ast

        for text in ("1 + 2j", "1 + 2"):
            try:
                print(ast.literal_eval(text))
            except ValueError:
                print("ValueError")
        """,
        """
        `(1+2j)` then `ValueError`. `literal_eval` accepts `+` and `-` only to write complex
        numbers; `1 + 2` is arithmetic, which it refuses (3.2.11). Use an AST evaluator like
        Lab 3.2's `safe_eval` for arithmetic.
        """,
        "",
    ),
    (
        "3.2",
        """
        def make():
            def inner():
                pass
            return inner

        first, second = make(), make()
        print(first is second, first.__code__ is second.__code__)
        """,
        """
        `False True`. Each call runs `def inner` again and builds a **new function object**,
        but around the **same code object**, compiled once with `make` (3.2.4). That is also
        why specialization state is shared between them (Lab 3.2, exercise 6).
        """,
        """
        def make() -> object:
            def inner() -> None:
                pass

            return inner


        first, second = make(), make()
        print(first is second, first.__code__ is second.__code__)
        """,
    ),
    (
        "3.2",
        """
        try:
            eval("len('abc')", {"__builtins__": {}})
        except NameError as error:
            print(error)
        """,
        """
        `name 'len' is not defined`. With an empty `__builtins__`, names like `len` are not
        found. This is **not** a sandbox: `().__class__.__base__.__subclasses__()` still
        reaches dangerous classes (3.2.11).
        """,
        "",
    ),
    (
        "3.2",
        """
        def is_small(size):
            return size in [1, 2, 3]

        print((1, 2, 3) in is_small.__code__.co_consts)
        """,
        """
        `True`. A list literal used only for `in` becomes a constant **tuple** built once at
        compile time (3.2.6); a set literal would become a `frozenset`.
        """,
        """
        def is_small(size: int) -> bool:
            return size in [1, 2, 3]


        print((1, 2, 3) in is_small.__code__.co_consts)
        """,
    ),
    (
        "3.3",
        """
        # counter_mod.py contains:
        #     print("loading")
        #     hits = 0
        import counter_mod
        import counter_mod
        counter_mod.hits += 1
        import counter_mod as again
        print(again.hits)
        """,
        """
        ```text
        loading
        1
        ```

        The module's code runs once; later imports find it in `sys.modules` (3.3.4). `again`
        is the same module object, so it sees the incremented `hits`.
        """,
        """
        with temporary_modules({"counter_mod.py": "print('loading')\\nhits = 0\\n"}):
            import counter_mod  # noqa: I001 (the repeated import is the point)
            import counter_mod

            counter_mod.hits += 1
            import counter_mod as again

            print(again.hits)
        """,
    ),
    (
        "3.3",
        """
        # shapes.py contains:
        #     __all__ = ["circle"]
        #     def circle(): ...
        #     def square(): ...
        #     _scale = 2
        from shapes import *
        print("circle" in dir(), "square" in dir(), "_scale" in dir())
        """,
        """
        `True False False`. With `__all__` defined, `import *` takes exactly those names;
        `square` is public but not listed, and `_scale` would be skipped even without
        `__all__` (3.3.3).
        """,
        """
        shapes_source = (
            "__all__ = ['circle']\\n\\ndef circle():\\n    pass\\n\\ndef square():\\n    pass\\n\\n_scale = 2\\n"
        )
        with temporary_modules({"shapes.py": shapes_source}):
            star_namespace: dict[str, object] = {}
            exec("from shapes import *", star_namespace)
            print("circle" in star_namespace, "square" in star_namespace, "_scale" in star_namespace)
        """,
    ),
    (
        "3.3",
        """
        # cycle_a.py:  import cycle_b
        #              VALUE = 42
        # cycle_b.py:  import cycle_a
        #              print(hasattr(cycle_a, "VALUE"))
        import cycle_a
        print(cycle_a.VALUE)
        """,
        """
        ```text
        False
        42
        ```

        `cycle_a` is in `sys.modules` before its code runs. Its first line imports `cycle_b`,
        whose `import cycle_a` returns the **partially initialized** module, which has no
        `VALUE` yet (3.3.9). Plain `import` survives the cycle; `from cycle_a import VALUE`
        would have raised `ImportError`.
        """,
        """
        cycle_files = {
            "cycle_a.py": "import cycle_b\\n\\nVALUE = 42\\n",
            "cycle_b.py": "import cycle_a\\n\\nprint(hasattr(cycle_a, 'VALUE'))\\n",
        }
        with temporary_modules(cycle_files):
            import cycle_a

            print(cycle_a.VALUE)
        """,
    ),
    (
        "3.3",
        """
        import sys

        sys.modules["config"] = 42
        import config
        print(config + 1)
        """,
        """
        `43`. `import` checks `sys.modules` first and returns whatever is cached there, even an
        int (3.3.2). Test doubles and some plugin systems use this on purpose.
        """,
        """
        sys.modules["config"] = 42
        try:
            import config

            print(config + 1)
        finally:
            del sys.modules["config"]
        """,
    ),
    (
        "3.3",
        """
        # tools/report.py contains:  print(__name__)
        # In a terminal:   python -m tools.report
        # In Python:       import tools.report
        """,
        """
        ```text
        __main__
        tools.report
        ```

        Run as the program (with `-m` or as a file), a module's `__name__` is `"__main__"`;
        imported, it is its qualified name (3.3.8). That is what the
        `if __name__ == "__main__":` guard tests.
        """,
        """
        with temporary_modules({"tools/__init__.py": "", "tools/report.py": "print(__name__)\\n"}) as root:
            print(run_python("-m", "tools.report", cwd=root))
            import tools.report  # noqa: F401 (imported for its print)
        """,
    ),
]


def _question_cells() -> list[NotebookNode]:
    """The 15 predict-the-output questions covering Phase 3."""
    unit_counts: dict[str, int] = {}
    for unit, *_ in QUESTIONS:
        unit_counts[unit] = unit_counts.get(unit, 0) + 1
    coverage_rows = "\n".join(
        f"            | {unit} | {count} |" for unit, count in unit_counts.items()
    )
    cells = [
        md(
            f"""
            ### Phase 3 review — 15 predict-the-output questions

            Fifteen short snippets, five from each unit. For each one, decide what it prints
            **before** opening the answer, then run the proof cell. If a question surprises
            you, go back to the section it names. Snippets leave out type hints to stay short;
            the proof cells add them (and use `temporary_modules` where a snippet needs a
            module file).

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
    """Phase 3 closing."""
    return [
        md(
            """
            ### Phase 3 complete

            You can now explain where an object's memory comes from (frames referencing heap
            objects, pymalloc and free lists) and when it is freed (reference counting, the
            cyclic GC, immortality), find leaks with `tracemalloc`, read `dis` output down to
            specialized instructions and the JIT's micro-ops, transform code with `ast`, and
            trace exactly what happens between `import x` and the first line of your code. The
            `pyinspect` toolkit packages those skills.

            **Next: Phase 4 — Professional Python: Packaging, Typing, Testing and the Standard
            Library.** `pyinspect` is a natural first candidate for what Phase 4 teaches: a
            `pyproject.toml` with a `[project.scripts]` entry point, type checking with mypy,
            and a pytest suite to replace the notebook self-check.
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for the Phase 3 Project and the closing review."""
    return [
        *_overview_cells(),
        *_memory_cells(),
        *_scanner_cells(),
        *_importtime_cells(),
        *_self_inspection_cells(),
        *_self_check_cells(),
        *_question_cells(),
        *_closing_cells(),
    ]
