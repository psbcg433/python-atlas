"""Unit 5.5 — Performance and Memory Optimization (with Lab 5.5)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = r'''
import array
import bisect
import functools
import gc
import heapq
import importlib
import importlib.util
import io
import json
import linecache
import math
import os
import platform
import pstats
import random
import re
import shutil
import statistics
import subprocess
import sys
import sysconfig
import textwrap
import time
import timeit
import tracemalloc
from collections import Counter, deque
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

DEMO_SCALE = int(os.environ.get("PHASE5_DEMO_SCALE", "1"))  # the one knob for workload sizes
REPO_ROOT = find_repo_root()
scratch_dir = REPO_ROOT / "notebooks" / "_scratch"  # git-ignored
PHASE5_DIR = scratch_dir / "phase5"
PHASE5_DIR.mkdir(parents=True, exist_ok=True)
os.chdir(REPO_ROOT / "notebooks")  # %%writefile cells use paths relative to notebooks/
if str(PHASE5_DIR) not in sys.path:
    sys.path.insert(0, str(PHASE5_DIR))
CHILD_ENV = {**os.environ, "PYTHON_COLORS": "0", "PYTHONUNBUFFERED": "1", "NO_COLOR": "1"}
CHILD_ENV.pop("FORCE_COLOR", None)  # ipykernel sets it; profilers would print colour codes
VENV_BIN = Path(sys.executable).parent


def has_module(name: str) -> bool:
    """True if the module can be imported (checked without importing it)."""
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:  # a parent package is missing
        return False


def tool_path(name: str) -> str | None:
    """A command-line tool from this virtual environment first, then from PATH."""
    candidate = VENV_BIN / name
    return str(candidate) if candidate.exists() else shutil.which(name)


HAS_NUMPY, HAS_PANDAS, HAS_POLARS = has_module("numpy"), has_module("pandas"), has_module("polars")
HAS_TACHYON = sys.version_info >= (3, 15) and has_module("profiling.sampling")
HAS_LINE_PROFILER, HAS_MEMRAY = has_module("line_profiler"), has_module("memray")
HAS_SCALENE, HAS_SNAKEVIZ = has_module("scalene"), has_module("snakeviz")
HAS_PYPERF, HAS_PYTEST_BENCHMARK = has_module("pyperf"), has_module("pytest_benchmark")
PY_SPY = tool_path("py-spy")
(PHASE5_DIR / "perf_tests").mkdir(exist_ok=True)  # for the %%writefile test module in 5.5.12
'''

UNIT_SETUP_SOURCE_2 = r'''
class Timer:
    """Timing context manager (shared since Unit 1.14): reports on exit, keeps elapsed_seconds."""

    def __init__(self, label: str, report: Callable[[str], None] | None = print) -> None:
        """Remember the label and where to report the elapsed time."""
        self.label = label
        self.report = report
        self.elapsed_seconds = 0.0

    def __enter__(self) -> Timer:
        """Start the clock."""
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Stop the clock and report the elapsed milliseconds."""
        self.elapsed_seconds = time.perf_counter() - self._start
        if self.report is not None:
            self.report(f"{self.label} took {self.elapsed_seconds * 1000:.2f} ms")


def tidy_output(text: str, python: str = sys.executable) -> str:
    """Replace machine-specific paths and addresses in child output with short labels."""
    replacements = (
        (str(PHASE5_DIR), "<scratch>"),
        (str(REPO_ROOT), "<repo>"),
        (str(Path(python).parent), "<python>"),
    )
    for path, label in replacements:
        text = text.replace(path, label)
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)  # colour codes some tools print anyway
    text = re.sub(r"0x[0-9a-f]{6,}", "0x<address>", text)
    return re.sub(r"/[^\s\"'():]*/lib/python3\.\d+t?/", "<stdlib>/", text)


def run_tool(*command: str, extra_env: dict[str, str] | None = None, timeout: int = 120) -> str:
    """Run a command in the scratch folder; return its tidied stdout + stderr."""
    completed = subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**CHILD_ENV, **(extra_env or {})},
        cwd=PHASE5_DIR,
    )
    return tidy_output((completed.stdout + completed.stderr).rstrip())


def run_child(
    source: str, python: str = sys.executable, extra_env: dict[str, str] | None = None
) -> str:
    """Run dedented source as a script in a child interpreter; return its stdout + stderr."""
    script = PHASE5_DIR / "child_script.py"
    script.write_text(textwrap.dedent(source).lstrip("\n"), encoding="utf-8")
    output = run_tool(python, str(script), extra_env=extra_env)
    return tidy_output(output, python)
'''

UNIT_SETUP_SOURCE_3 = r'''
def find_free_threaded_python() -> str | None:
    """Path of an installed free-threaded 3.15 interpreter, or None (shared since Unit 3.1)."""
    candidates: list[str] = []
    if uv_path := shutil.which("uv"):
        found = subprocess.run(
            [uv_path, "python", "find", "3.15t"], capture_output=True, text=True, timeout=60
        )
        if found.returncode == 0:
            candidates.append(found.stdout.strip())
    if on_path := shutil.which("python3.15t"):
        candidates.append(on_path)
    probe = "import sysconfig; print(sysconfig.get_config_var('Py_GIL_DISABLED'))"
    for candidate in candidates:
        answer = subprocess.run([candidate, "-c", probe], capture_output=True, text=True)
        if answer.stdout.strip() == "1":
            return candidate
    return None


def interpreter_label() -> str:
    """Implementation, version and build flavour: print it next to every benchmark."""
    free_threaded = bool(sysconfig.get_config_var("Py_GIL_DISABLED"))
    build = "free-threaded build" if free_threaded else "default (GIL) build"
    implementation = platform.python_implementation()
    return f"{implementation} {platform.python_version()}, {build}, {platform.machine()}"


def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"


FREE_THREADED_PYTHON = find_free_threaded_python()
print(interpreter_label())
print(f"{DEMO_SCALE=}  free-threaded interpreter: {'found' if FREE_THREADED_PYTHON else 'none'}")
tools = {
    "Tachyon (profiling.sampling)": HAS_TACHYON,
    "py-spy": PY_SPY is not None,
    "line_profiler": HAS_LINE_PROFILER,
    "memray": HAS_MEMRAY,
    "scalene": HAS_SCALENE,
    "snakeviz": HAS_SNAKEVIZ,
    "pyperf": HAS_PYPERF,
    "pytest-benchmark": HAS_PYTEST_BENCHMARK,
}
for tool_name, found in tools.items():
    print(
        f"  {tool_name:<30} "
        f"{'available' if found else 'not installed: its cells print a skip message'}"
    )
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 5.5 — Performance and Memory Optimization

            **Objectives**

            - Follow a measure-first method: find the bottleneck with a profiler, predict the
              gain with Amdahl's law, change one thing, re-measure with clean benchmarks.
            - Time code with `perf_counter`, `timeit` and `%timeit`, and read the spread, not
              just one number.
            - Profile CPU with deterministic (`cProfile`) and sampling profilers (the 3.15
              **Tachyon** profiler, py-spy, scalene), per line with `line_profiler`, and read
              a flame graph.
            - Profile memory with `tracemalloc` and memray; tell *peak* from *current*.
            - Optimize in the right order: algorithms and data structures first, then
              interpreter-level habits, then memory layout, caching, vectorization and native
              code.
            - Measure what the free-threaded build and the JIT change, and keep performance
              under watch in production and CI.

            **JS bridge**

            | Node.js | Python | The difference that bites |
            | --- | --- | --- |
            | `performance.now()`, `console.time` | `time.perf_counter()` / `perf_counter_ns()` | `time.time()` is wall-clock and can jump; never benchmark with it |
            | `tinybench`, `mitata`, benchmark.js | `timeit`, `%timeit`, `pyperf` | `timeit` switches the garbage collector **off** while it measures |
            | `node --cpu-prof` + DevTools | `cProfile` + `pstats` + snakeviz | `cProfile` hooks **every call**: exact counts, but it slows small functions down a lot |
            | `0x`, `clinic flame`, `perf` | Tachyon (`python -m profiling.sampling`), py-spy | sampling profilers read the stack from outside: low overhead, can attach to a live process |
            | heap snapshots, `--heap-prof` | `tracemalloc`, memray | `tracemalloc` sees Python allocations only; memray also sees C allocations |
            | V8's JIT (always on, hidden classes) | specializing interpreter (3.11+) and an optional JIT (3.13+, off by default) | type-stable code helps both; Python's JIT gains are still modest |
            | typed arrays, `Buffer` | `array`, `memoryview`, NumPy | one block of raw numbers instead of one object per number |
            | N-API, WASM | C extensions, Cython, Rust/PyO3, `ctypes`/`cffi` | crossing the boundary has a per-call cost: move whole loops, not single operations |
            | `worker_threads` for CPU work | free-threaded build (`python3.15t`) | on the default build, threads do not speed up pure-Python CPU work |

            **How this unit runs.** Every profiler runs on a small script in `notebooks/_scratch/phase5/`
            through a subprocess, and its real output is printed. Tools that are not installed,
            the free-threaded build and the JIT are detected first; when one is missing its cell
            prints a skip message. Workload sizes are multiplied by `DEMO_SCALE`. **Timings vary
            by machine:** cells print what they measured and the ratio, never a promise.
            """
        ),
        md(
            """
            Unit setup, part 1: imports, `DEMO_SCALE`, the scratch folder, and feature flags for
            the optional tools (checked with `importlib.util.find_spec`, never imported here).
            """
        ),
        code(UNIT_SETUP_SOURCE),
        md(
            """
            Unit setup, part 2: `Timer` (Unit 1.14), `run_tool()` (runs a command in the
            scratch folder and replaces machine-specific paths with labels such as `<scratch>`)
            and `run_child()` (Units 5.1–5.4: runs source code as a script in a child
            interpreter).
            """
        ),
        code(UNIT_SETUP_SOURCE_2),
        md(
            """
            Unit setup, part 3: `find_free_threaded_python()` (Unit 3.1), the interpreter label
            printed next to benchmarks, and a summary of which tools this machine has.
            """
        ),
        code(UNIT_SETUP_SOURCE_3),
    ]


def _method_cells() -> list[NotebookNode]:
    """5.5.1 Method."""
    return [
        md(
            """
            ### 5.5.1 Method

            Performance work fails in one of two ways: optimizing code that does not matter,
            or "optimizing" without measuring and making things slower. The cure is a loop:

            ```mermaid
            flowchart LR
                A[Measure end to end] --> B[Profile: where does the time go?]
                B --> C[Hypothesis + Amdahl estimate]
                C --> D[Change ONE thing]
                D --> E[Re-measure, same input]
                E -->|faster and still correct| F[Keep, commit]
                E -->|not faster| G[Revert]
                F --> A
                G --> B
            ```

            <details><summary>ASCII fallback</summary>

            ```text
            measure -> profile -> hypothesis (+ Amdahl) -> change one thing -> re-measure
               ^                                                               |
               +------------------- keep (faster, correct) or revert ----------+
            ```

            </details>

            **Measure first.** Your intuition about *where* the time goes is usually wrong: a
            "slow" regex may cost 1 % while a forgotten linear scan inside a loop costs 90 %.
            """
        ),
        md(
            """
            #### Amdahl's law for optimization

            If a part that takes a fraction `p` of the runtime becomes `s` times faster, the
            whole program becomes `1 / ((1 - p) + p / s)` times faster. Unit 5.2 used the same
            formula for parallel workers; here it decides what is worth optimizing at all.
            """
        ),
        code(
            '''
            def overall_speedup(fraction: float, part_speedup: float) -> float:
                """Amdahl: whole-program speedup when `fraction` of it gets `part_speedup` faster."""
                return 1 / ((1 - fraction) + fraction / part_speedup)


            print(
                f"{'share of runtime':>17} | {'part 2x faster':>14} | "
                f"{'part 10x':>8} | {'part infinitely fast':>20}"
            )
            for fraction in (0.05, 0.25, 0.50, 0.90, 0.99):
                speedups = [overall_speedup(fraction, part_speedup) for part_speedup in (2, 10, math.inf)]
                print(
                    f"{fraction:>17.0%} | {speedups[0]:>13.2f}x | {speedups[1]:>7.2f}x | {speedups[2]:>19.2f}x"
                )
            '''
        ),
        md(
            """
            Read the first row: making a function that takes 5 % of the runtime *infinitely*
            fast gains 1.05×. Read the last column: the untouched part caps the total. This is
            why the profiler comes first: it tells you `p`.

            #### Benchmark hygiene

            | Rule | Why |
            | --- | --- |
            | Same input, same machine, same Python build | otherwise you compare different things |
            | Warm up, then repeat many times | the first calls pay for imports, caches and the specializing interpreter's warm-up |
            | Report the **minimum** (or median) and the spread | noise only ever adds time; one number hides variance |
            | Run benchmarks in a **fresh process** | earlier cells leave garbage, warm caches and fragmented memory |
            | Keep the machine quiet | browsers, indexing and CPU frequency scaling add noise |
            | Check correctness in the same run | a fast wrong answer is not an optimization |
            | Measure at realistic sizes | O(n²) code looks fine at n = 100 |

            Warm-up is real. First calls pay one-time costs: lazy imports, filling caches
            (here: `re` compiling a pattern and caching it), and the specializing
            interpreter's warm-up (Unit 3.2). `sum_of_squares` is used by later cells; the
            regex function shows the warm-up (run the cell a second time and the slow first
            call is gone, because the pattern is already cached):
            """
        ),
        code(
            '''
            def sum_of_squares(count: int) -> int:
                """A small pure-Python loop to time."""
                total = 0
                for number in range(count):
                    total += number * number
                return total


            def parse_order_code(code_text: str) -> tuple[str, ...] | None:
                """Split an order code such as MH-2026-004217-7; re compiles the pattern on first use."""
                match = re.fullmatch(
                    r"(?P<state>[A-Z]{2})-(?P<year>\\d{4})-(?P<serial>\\d{6})-(?P<check>[0-9X])", code_text
                )
                return match.groups() if match else None


            call_times = []
            for _ in range(5):
                start = time.perf_counter_ns()
                parse_order_code("MH-2026-004217-7")
                call_times.append(time.perf_counter_ns() - start)
            print("per-call ns:", call_times)
            print(f"first call / fastest call = {call_times[0] / min(call_times):.0f}x")
            '''
        ),
        md(
            """
            Repeat and look at the spread. `timeit.repeat` returns one total per repetition;
            the minimum is the best estimate of the code's cost, the rest is noise from the
            machine:
            """
        ),
        code(
            """
            totals = timeit.repeat(lambda: sum_of_squares(2_000), number=200, repeat=7)
            per_call_us = sorted(total / 200 * 1e6 for total in totals)
            print("per call, sorted (µs):", [round(value, 2) for value in per_call_us])
            print(f"min {per_call_us[0]:.2f} µs, median {statistics.median(per_call_us):.2f} µs")
            print(f"spread (max/min): {per_call_us[-1] / per_call_us[0]:.2f}x")
            """
        ),
        md(
            """
            `timeit` switches the garbage collector **off** while it measures, so code that
            allocates many container objects looks faster under `timeit` than in a real
            program. Pass `gc.enable()` as the setup to measure with the collector on:
            """
        ),
        code(
            """
            build_nested = "[[index] for index in range(20_000)]"  # 20 000 GC-tracked lists
            gc_off = min(timeit.repeat(build_nested, number=20, repeat=5)) / 20
            gc_on = (
                min(timeit.repeat(build_nested, setup="gc.enable()", number=20, repeat=5, globals=globals()))
                / 20
            )
            print(f"GC off (timeit default): {gc_off * 1000:.2f} ms per call")
            print(f"GC on:                   {gc_on * 1000:.2f} ms per call  ({gc_on / gc_off:.2f}x)")
            """
        ),
        md(
            """
            #### pyperf

            [`pyperf`](https://pyperf.readthedocs.io/) is the benchmark runner CPython's own
            developers use (it powers the `pyperformance` suite). It applies the hygiene rules
            for you: it spawns **several worker processes**, discards warm-up runs, calibrates
            the loop count, reports mean ± standard deviation, warns when the results are
            unstable, and can compare two saved result files (`python -m pyperf compare_to`).
            It is not part of this course's dependencies, so the cell checks for it first:
            """
        ),
        code(
            """
            pyperf_command = [
                sys.executable,
                "-m",
                "pyperf",
                "timeit",
                "--fast",
                "-s",
                "values = list(range(1000))",
                "sum(values)",
            ]
            print("$ python -m pyperf timeit --fast -s 'values = list(range(1000))' 'sum(values)'")
            if HAS_PYPERF:
                print(run_tool(*pyperf_command))
            else:
                print("pyperf is not installed: skipping (install with `uv add --dev pyperf`).")
            """
        ),
        md(
            """
            The core idea needs nothing but the standard library: run the measurement in
            several **fresh processes** and look at how much the processes disagree. Here
            `python -m timeit` (the command-line face of `timeit`) runs in four separate
            interpreters:
            """
        ),
        code(
            """
            per_process = []
            for _ in range(4):
                line = run_tool(
                    sys.executable, "-m", "timeit", "-r", "5", "-s", "values = list(range(1000))", "sum(values)"
                )
                print(line)
                per_process.append(
                    float(line.split(":")[1].split()[0])
                )  # "N loops, best of 5: X usec per loop"
            mean, spread = statistics.mean(per_process), statistics.stdev(per_process)
            print(f"across processes: {mean:.3f} ± {spread:.3f} (same unit as above)")
            """
        ),
    ]


def _timing_cells() -> list[NotebookNode]:
    """5.5.2 Timing."""
    return [
        md(
            """
            ### 5.5.2 Timing

            #### `perf_counter` and the other clocks

            | Clock | Measures | Use it for |
            | --- | --- | --- |
            | `time.perf_counter()` / `perf_counter_ns()` | wall time, monotonic, highest resolution | benchmarks, `Timer` |
            | `time.monotonic()` | wall time, monotonic | timeouts, deadlines, rate limiters |
            | `time.process_time()` | CPU time of this process (all threads), excludes sleep | "is it CPU or waiting?" |
            | `time.time()` | calendar time since 1970; **can jump** (NTP, manual changes) | timestamps, never durations |

            `time.get_clock_info` shows what each clock is built on and its resolution:
            """
        ),
        code(
            """
            for clock_name in ("perf_counter", "monotonic", "process_time", "time"):
                info = time.get_clock_info(clock_name)
                print(
                    f"{clock_name:<13} monotonic={info.monotonic!s:<5} adjustable={info.adjustable!s:<5}"
                    f" resolution={info.resolution:.0e} s  ({info.implementation})"
                )
            """
        ),
        md(
            """
            Wall time and CPU time answer different questions. A sleep (or a network wait)
            takes wall time but almost no CPU time; a busy loop takes both. Comparing the two
            tells you whether code is waiting or computing:
            """
        ),
        code(
            '''
            def wall_and_cpu(work: Callable[[], object]) -> tuple[float, float]:
                """Return (wall seconds, CPU seconds) for one call of work."""
                wall_start, cpu_start = time.perf_counter(), time.process_time()
                work()
                return time.perf_counter() - wall_start, time.process_time() - cpu_start


            for label, work in (
                ("sleep 0.2 s", lambda: time.sleep(0.2)),
                ("busy loop", lambda: sum_of_squares(1_000_000)),
            ):
                wall_seconds, cpu_seconds = wall_and_cpu(work)
                print(f"{label:<12} wall {wall_seconds:.3f} s  CPU {cpu_seconds:.3f} s")
            '''
        ),
        md(
            """
            Use `perf_counter_ns()` (integer nanoseconds) when you subtract many small
            intervals: floats lose precision on a large counter value. `Timer` from
            Unit 1.14 wraps `perf_counter` in a context manager:
            """
        ),
        code(
            """
            float_rng = random.Random(42)
            unsorted_floats = [float_rng.random() for _ in range(200_000 * DEMO_SCALE)]
            with Timer("sorting 200 000 floats"):
                sorted(unsorted_floats)
            gaps = []
            for _ in range(1_000):
                first_ns = time.perf_counter_ns()
                gaps.append(time.perf_counter_ns() - first_ns)
            print(f"smallest gap between two perf_counter_ns() calls: {min(gaps)} ns")
            """
        ),
        md(
            """
            #### `timeit`

            `timeit.timeit(stmt, setup, number)` runs `stmt` `number` times and returns the
            **total** seconds. Statements can be strings (compiled once, run in a fresh
            namespace, so pass `globals=` to see your names) or zero-argument callables (the
            call itself adds a little overhead):
            """
        ),
        code(
            """
            string_total = timeit.timeit(
                "sorted(values)", setup="values = list(range(1000, 0, -1))", number=2_000
            )
            callable_total = timeit.timeit(lambda: sorted(range(1000, 0, -1)), number=2_000)
            with_globals = timeit.timeit("sum_of_squares(100)", number=2_000, globals=globals())
            print(f"string stmt:   {string_total / 2_000 * 1e6:.2f} µs per call")
            print(f"callable stmt: {callable_total / 2_000 * 1e6:.2f} µs per call (also builds the range)")
            print(f"globals=:      {with_globals / 2_000 * 1e6:.2f} µs per sum_of_squares(100)")
            """
        ),
        md(
            """
            `Timer.autorange()` picks the loop count for you (powers of 1, 2, 5 × 10ⁿ until the
            total reaches 0.2 s), which is what the `python -m timeit` command does before it
            repeats:
            """
        ),
        code(
            """
            loop_count, total_seconds = timeit.Timer("'-'.join(map(str, range(100)))").autorange()
            print(f"autorange chose {loop_count:,} loops, {total_seconds:.3f} s in total")
            print(f"-> {total_seconds / loop_count * 1e6:.2f} µs per call")
            """
        ),
        md(
            """
            #### `%timeit` and `%%timeit`

            In IPython and Jupyter, `%timeit` (one line) and `%%timeit` (whole cell) do the
            autorange and repeat for you and print mean ± standard deviation. `-n` fixes the
            loops per run and `-r` the number of runs (fixed here to keep Run All fast); `-o`
            returns a `TimeitResult` object whose `.best`, `.average` and `.stdev` you can use:
            """
        ),
        code(
            """
            %timeit -n 2000 -r 5 sum(range(1_000))
            """
        ),
        md(
            "The cell magic times the whole cell body; the first line after `%%timeit` is setup that is not timed:"
        ),
        code(
            """
            %%timeit -n 200 -r 5
            joined = ""
            for word in ["chai"] * 1_000:
                joined += word
            """
        ),
        md("With `-o -q` the result is returned quietly, so you can compute with it:"),
        code(
            """
            timeit_result = %timeit -o -q -n 2000 -r 5 sorted(range(1_000, 0, -1))
            print(f"best {timeit_result.best * 1e6:.2f} µs, average {timeit_result.average * 1e6:.2f} µs")
            print(
                f"stdev {timeit_result.stdev * 1e6:.2f} µs over {timeit_result.repeat} runs"
                f" of {timeit_result.loops} loops"
            )
            """
        ),
    ]


def _cpu_profiling_cells() -> list[NotebookNode]:
    """5.5.3 CPU profiling."""
    return [
        md(
            """
            ### 5.5.3 CPU profiling

            A **profiler** tells you where the time goes. There are two families:

            | | Deterministic (tracing) | Sampling (statistical) |
            | --- | --- | --- |
            | How | a hook runs on **every** call and return | the stack is read every *N* µs, often from another process |
            | Tools | `cProfile` (= `profiling.tracing` in 3.15), `line_profiler` | Tachyon (3.15), py-spy, scalene |
            | Gives | exact call counts, per-function times | the share of samples per function or line |
            | Overhead | large, and uneven: tiny functions look slower than they are | small and even; safe in production |
            | Attach to a running process | no | yes (Tachyon, py-spy) |

            Every profiler below runs on the same small script, in a subprocess, and its real
            output is printed. The script has three deliberate hot spots: a linear-scan lookup
            inside a loop, a string-building loop, and a simulated network call that waits
            without using the CPU.
            """
        ),
        code(
            '''
            %%writefile _scratch/phase5/profile_target.py
            """Profiling target for Unit 5.5: an order report with three deliberate hot spots."""

            import os
            import time

            DEMO_SCALE = int(os.environ.get("PHASE5_DEMO_SCALE", "1"))
            CITIES = ("Pune", "Delhi", "Kochi", "Patna", "Surat")


            def make_customers(count: int) -> list[tuple[int, str]]:
                """(customer_id, city) pairs; ids are spread out, so no list index works."""
                return [(number * 7 + 3, CITIES[number % 5]) for number in range(count)]


            def make_orders(count: int, customers: list[tuple[int, str]]) -> list[tuple[int, int]]:
                """(customer_id, amount_paise) pairs from a deterministic formula (no randomness)."""
                return [
                    (customers[(number * 7919) % len(customers)][0], (number * 104729) % 50_000 + 100)
                    for number in range(count)
                ]
            '''
        ),
        md(
            """
            Hot spot 1 and the function that calls it. `%%writefile -a` appends to the same
            file, so the script is still one module with the same line numbers:
            """
        ),
        code(
            '''
            %%writefile -a _scratch/phase5/profile_target.py


            def find_city(customers: list[tuple[int, str]], customer_id: int) -> str:
                """Hot spot 1: a linear scan for every lookup."""
                for candidate_id, city in customers:
                    if candidate_id == customer_id:
                        return city
                raise KeyError(customer_id)


            def city_totals(orders: list[tuple[int, int]], customers: list[tuple[int, str]]) -> dict[str, int]:
                """Revenue per city, calling find_city once per order."""
                totals: dict[str, int] = {}
                for customer_id, amount in orders:
                    city = find_city(customers, customer_id)
                    totals[city] = totals.get(city, 0) + amount
                return totals
            '''
        ),
        md(
            """
            Hot spots 2 and 3 and the entry point, appended in the same way:
            """
        ),
        code(
            '''
            %%writefile -a _scratch/phase5/profile_target.py


            def render_lines(orders: list[tuple[int, int]]) -> str:
                """Hot spot 2: one str.format call and one string concatenation per order."""
                text = ""
                for number, (customer_id, amount) in enumerate(orders * 20):
                    text += "{:>7} {:>8} {:>10.2f}\\n".format(number, customer_id, amount / 100)
                return text


            def fetch_exchange_rate() -> float:
                """Hot spot 3, wall clock only: a simulated 0.3 s network call (no CPU used)."""
                time.sleep(0.3)
                return 83.25


            def main() -> None:
                """Build the data, fetch the rate, compute and render."""
                customers = make_customers(2_500)
                orders = make_orders(8_000 * DEMO_SCALE, customers)
                rate = fetch_exchange_rate()
                totals = city_totals(orders, customers)
                text = render_lines(orders)
                print(f"{len(orders)} orders, {len(totals)} cities, {len(text):,} chars, rate {rate}")


            if __name__ == "__main__":
                main()
            '''
        ),
        md("First, the plain run: how long does the whole script take without any profiler?"),
        code(
            """
            with Timer("profile_target.py, no profiler"):
                print(run_tool(sys.executable, "profile_target.py"))
            """
        ),
        md(
            """
            #### `cProfile` from the command line

            `python -m cProfile -s tottime script.py` runs the script under the profiler and
            prints one row per function, sorted by **own time**. Only the top of the table
            matters:
            """
        ),
        code(
            '''
            def first_lines(text: str, line_count: int) -> str:
                """The first line_count lines of a block of text."""
                return "\\n".join(text.splitlines()[:line_count])


            cprofile_output = run_tool(sys.executable, "-m", "cProfile", "-s", "tottime", "profile_target.py")
            print(first_lines(cprofile_output, 14))
            '''
        ),
        md(
            """
            | Column | Meaning |
            | --- | --- |
            | `ncalls` | number of calls (`a/b`: total/primitive, for recursion) |
            | `tottime` | time spent **inside** the function itself, excluding the functions it called |
            | `percall` (first) | `tottime / ncalls` |
            | `cumtime` | time from entry to exit, **including** everything it called |
            | `percall` (second) | `cumtime / primitive calls` |

            Read it: `find_city` has the biggest `tottime`, and it is called once per order. The
            fix is not to make `find_city` faster but to stop calling it 8 000 times (a dict,
            in 5.5.5). Notice too that the run took longer than without the profiler: that is
            the tracing overhead.

            #### Saving a profile and reading it with `pstats`

            `-o file.prof` saves the raw data instead of printing it. `pstats.Stats` loads it
            and can sort, filter and restrict the output; `strip_dirs()` shortens file paths:
            """
        ),
        code(
            """
            print(run_tool(sys.executable, "-m", "cProfile", "-o", "target.prof", "profile_target.py"))
            stats_buffer = io.StringIO()
            target_stats = pstats.Stats(str(PHASE5_DIR / "target.prof"), stream=stats_buffer)
            target_stats.strip_dirs().sort_stats(pstats.SortKey.CUMULATIVE).print_stats(r"profile_target", 6)
            print(tidy_output(stats_buffer.getvalue().strip()))
            """
        ),
        md(
            """
            The argument `r"profile_target"` is a regex that keeps only rows from our file,
            and `6` keeps the first six. `print_callers` answers "who calls this?" and
            `print_callees` answers "what does this call?":
            """
        ),
        code(
            """
            stats_buffer.seek(0)
            stats_buffer.truncate()
            target_stats.print_callers("find_city")
            target_stats.print_callees("city_totals")
            print(tidy_output(stats_buffer.getvalue().strip()))
            """
        ),
        md(
            """
            #### The `cProfile` API, and `profiling.tracing`

            In code, `cProfile.Profile()` is a context manager (3.8+), and `pstats.Stats`
            accepts the profiler directly. *New in 3.15* (PEP 799): the profilers moved into a
            `profiling` package; `profiling.tracing` is the new name of `cProfile`, which stays
            as an alias. The demo runs in a child interpreter:
            """
        ),
        code(
            '''
            print(
                run_child(
                    """
                    import cProfile
                    import pstats
                    import sys

                    import profile_target

                    customers = profile_target.make_customers(2_500)
                    orders = profile_target.make_orders(2_000, customers)
                    with cProfile.Profile() as profiler:
                        profile_target.city_totals(orders, customers)
                    pstats.Stats(profiler).strip_dirs().sort_stats(pstats.SortKey.TIME).print_stats(3)
                    if sys.version_info >= (3, 15):
                        import profiling.tracing

                        same_class = profiling.tracing.Profile is cProfile.Profile
                        print("profiling.tracing.Profile is cProfile.Profile:", same_class)
                    """
                ).strip()
            )
            '''
        ),
        md(
            """
            #### snakeviz

            snakeviz is a **browser** viewer for `.prof` files: an icicle or sunburst chart in
            which each function's width is its share of the time and clicking zooms in. It
            starts a local web server, so this notebook does not launch it. Here is the command
            and the file it reads:
            """
        ),
        code(
            """
            profile_file = PHASE5_DIR / "target.prof"
            print(f"profile file: <scratch>/{profile_file.name}, {profile_file.stat().st_size:,} bytes")
            print(f"functions recorded: {len(target_stats.stats)}, total calls: {target_stats.total_calls:,}")
            print("open it in a terminal with:")
            print("    uv run snakeviz notebooks/_scratch/phase5/target.prof")
            if not HAS_SNAKEVIZ:
                print("snakeviz is not installed: `uv add --dev snakeviz` first.")
            """
        ),
        md(
            """
            #### The Tachyon sampling profiler (*New in 3.15*)

            Python 3.15 ships a sampling profiler in the standard library, `profiling.sampling`,
            nicknamed **Tachyon** (PEP 799). It reads the target's stack from **outside** the
            process many thousands of times per second, so the target runs at nearly full
            speed. `run` starts a script under it; `attach PID` samples a process that is
            already running (5.5.12). Outputs include a pstats-like table (the default),
            `--collapsed` stacks, an HTML `--flamegraph`, `--gecko` for the Firefox Profiler and
            a source `--heatmap`.
            """
        ),
        code(
            """
            if HAS_TACHYON:
                tachyon_output = run_tool(
                    sys.executable,
                    "-m",
                    "profiling.sampling",
                    "run",
                    "-r",
                    "5khz",
                    "--sort",
                    "tottime",
                    "-l",
                    "6",
                    "--no-summary",
                    "profile_target.py",
                )
                print(tachyon_output)
            else:
                print("Tachyon needs Python 3.15+ (profiling.sampling): skipping.")
            """
        ),
        md(
            """
            The rows are **lines**, not functions (`file:line(function)`), so a hot loop body
            stands out directly. The columns are estimates: `nsamples` direct/cumulative,
            `sample%` the share of samples executing that line.

            **Wall time vs CPU time.** By default Tachyon samples in `wall` mode: a thread
            blocked in `time.sleep` (or on a socket) still collects samples. `--mode cpu` keeps
            only samples taken while the thread was running on a CPU. The simulated network
            call shows the difference:
            """
        ),
        code(
            """
            if HAS_TACHYON:
                for mode in ("wall", "cpu"):
                    mode_output = run_tool(
                        sys.executable,
                        "-m",
                        "profiling.sampling",
                        "run",
                        "--mode",
                        mode,
                        "--sort",
                        "cumtime",
                        "-l",
                        "40",
                        "--no-summary",
                        "profile_target.py",
                    )
                    interesting = [
                        line
                        for line in mode_output.splitlines()
                        if "fetch_exchange_rate" in line or "(city_totals)" in line
                    ]
                    print(f"--mode {mode}:")
                    print(
                        "\\n".join(f"    {line.strip()}" for line in interesting)
                        or "    (no samples in these functions)"
                    )
            else:
                print("Tachyon needs Python 3.15+: skipping.")
            """
        ),
        md(
            """
            In `wall` mode `fetch_exchange_rate` holds a large share (it waited 0.3 s); in `cpu`
            mode it all but disappears. Use wall mode to find out why a request is slow, CPU
            mode to find out what burns the processor. (`--mode gil` keeps samples where the
            thread held the GIL, which is useful for threaded programs.)

            #### Reading flame graphs

            A **flame graph** draws every sampled stack as a column of boxes: the bottom box is
            the entry point, each box above it is a function that box called.

            - **Width** = share of samples containing that function (not time order: the x axis
              is sorted alphabetically or by size, not by when things happened).
            - **Height** = stack depth. Tall is not slow; **wide** is.
            - A wide box with nothing on top is spending its *own* time: that is the hot spot.
              A wide box covered by children is just passing time down.
            - Colours are usually random (or by module); they carry no meaning.
            - An "icicle" chart (snakeviz, some viewers) is the same picture upside down.

            Tachyon writes **collapsed stacks** (one line per distinct stack: frames joined by
            `;`, then a sample count), the input format of every flame-graph tool, and an
            interactive HTML flame graph:
            """
        ),
        code(
            """
            if HAS_TACHYON:
                for output_flag, file_name in (
                    ("--collapsed", "tachyon_stacks.txt"),
                    ("--flamegraph", "target_flame.html"),
                ):
                    print(
                        run_tool(
                            sys.executable,
                            "-m",
                            "profiling.sampling",
                            "run",
                            output_flag,
                            "-o",
                            file_name,
                            "profile_target.py",
                        )
                    )
                tachyon_stacks = (PHASE5_DIR / "tachyon_stacks.txt").read_text()
                print(
                    "\\nHTML flame graph: <scratch>/target_flame.html "
                    f"({(PHASE5_DIR / 'target_flame.html').stat().st_size:,} bytes)"
                )
                print("first collapsed stack:", tidy_output(tachyon_stacks.splitlines()[0])[:150], "...")
            else:
                tachyon_stacks = ""
                print("Tachyon needs Python 3.15+: skipping.")
            """
        ),
        md(
            """
            A flame graph is a tree of stacks, so a few lines of Python can draw it as text:
            parse the collapsed stacks, add the counts up along each path, and print each
            function indented under its caller with a bar as wide as its share. Frames are
            reduced to function names, and everything below `main` (the interpreter's start-up
            frames) is cut off:
            """
        ),
        code(
            '''
            def parse_collapsed(text: str) -> Counter[tuple[str, ...]]:
                """Collapsed stacks (Tachyon or py-spy format) -> {(main, ..., leaf): samples}."""
                stacks: Counter[tuple[str, ...]] = Counter()
                for line in text.splitlines():
                    frames_text, _, count = line.rpartition(" ")
                    if not frames_text:
                        continue
                    names = []
                    for frame in frames_text.split(";"):
                        if frame.startswith("tid:"):
                            continue
                        if " (" in frame:  # py-spy: "function (file:line)"
                            names.append(frame.split(" (")[0])
                        elif frame.count(":") >= 2:  # Tachyon: "file:function:line"
                            names.append(frame.split(":")[-2])
                        else:  # pseudo-frames such as <GC>
                            names.append(frame)
                    if "main" in names:
                        stacks[tuple(names[names.index("main") :])] += int(count)
                return stacks
            '''
        ),
        md(
            """
            `flame_tree` adds the samples up along every path, then draws each function under
            its caller, widest first, skipping branches under 1 %:
            """
        ),
        code(
            '''
            def flame_tree(stacks: Counter[tuple[str, ...]], min_share: float = 0.01, width: int = 30) -> str:
                """Draw collapsed stacks as an indented text flame graph (widest children first)."""
                totals: Counter[tuple[str, ...]] = Counter()
                for stack, count in stacks.items():
                    for depth in range(1, len(stack) + 1):
                        totals[stack[:depth]] += count
                grand_total = sum(stacks.values()) or 1
                lines: list[str] = []

                def draw(path: tuple[str, ...]) -> None:
                    """Append one bar for path, then recurse into its children."""
                    share = totals[path] / grand_total
                    label = "  " * (len(path) - 1) + path[-1]
                    lines.append(f"{label:<34} {'█' * round(share * width):<{width}} {share:6.1%}")
                    children = [
                        child_path
                        for child_path in totals
                        if len(child_path) == len(path) + 1 and child_path[:-1] == path
                    ]
                    for child in sorted(children, key=totals.__getitem__, reverse=True):
                        if totals[child] / grand_total >= min_share:
                            draw(child)

                for root in sorted({stack[:1] for stack in stacks}, key=totals.__getitem__, reverse=True):
                    draw(root)
                return "\\n".join(lines)
            '''
        ),
        md("The Tachyon samples of `profile_target.py`, drawn as a text flame graph (wall mode):"),
        code(
            """
            print(
                flame_tree(parse_collapsed(tachyon_stacks))
                if tachyon_stacks
                else "no Tachyon samples (skipped above)"
            )
            """
        ),
        md(
            """
            Read it top-down: `main` is 100 %. `city_totals` is wide, but almost all of it is
            `find_city` beneath it, so `find_city` is the plateau to attack. `fetch_exchange_rate`
            is wide only because wall mode counts waiting (its child is `time.sleep`, which has
            no Python frame). `render_lines` is the second CPU hot spot.

            #### py-spy

            [py-spy](https://github.com/benfred/py-spy) is a sampling profiler written in Rust
            that, like Tachyon, reads the target's memory from outside. It works on many Python
            versions (useful before 3.15) and offers `record` (flame graphs: SVG by default,
            `-f raw` for collapsed stacks, `-f speedscope`), `top` (a live, `top`-like view)
            and `dump` (print every thread's stack once, see 5.5.12). On Linux it needs
            permission to read another process's memory (`ptrace`): fine for a child it
            starts itself, `sudo` or `kernel.yama.ptrace_scope=0` for attaching.
            """
        ),
        code(
            """
            if PY_SPY:
                spy_output = run_tool(
                    PY_SPY,
                    "record",
                    "-r",
                    "250",
                    "-f",
                    "raw",
                    "-o",
                    "pyspy_stacks.txt",
                    "--",
                    sys.executable,
                    "profile_target.py",
                )
                print(
                    "\\n".join(
                        line
                        for line in spy_output.splitlines()
                        if (line.startswith("py-spy>") or "orders" in line) and "flamegraph.pl" not in line
                    )
                )
                if (PHASE5_DIR / "pyspy_stacks.txt").exists():
                    print(flame_tree(parse_collapsed((PHASE5_DIR / "pyspy_stacks.txt").read_text())))
            else:
                print("py-spy is not installed (or not on PATH): skipping. Install with `uv add --dev py-spy`.")
            """
        ),
        md(
            """
            The CPU work has the same shape as in Tachyon's graph: two independent sampling
            profilers agree. By default py-spy **drops idle samples** (a thread sleeping or
            blocked on I/O), so `fetch_exchange_rate` almost vanishes, as in Tachyon's
            `--mode cpu`; `py-spy record --idle` keeps them.

            #### `line_profiler`

            Function-level profiles say *which* function; `line_profiler` says *which line*.
            It is deterministic: it times every line of the functions you select, so select
            only the suspects. The usual workflow is to decorate them with `@profile` and run
            `kernprof -l -v script.py`; here the `LineProfiler` API wraps two functions of the
            unchanged script, in a child interpreter. Timing every line is slow, so the child
            uses a quarter of the orders:
            """
        ),
        code(
            '''
            if HAS_LINE_PROFILER:
                line_profile_output = run_child(
                    """
                    from line_profiler import LineProfiler

                    import profile_target

                    customers = profile_target.make_customers(2_500)
                    orders = profile_target.make_orders(2_000, customers)
                    line_profiler = LineProfiler(profile_target.find_city, profile_target.render_lines)
                    line_profiler.runcall(profile_target.city_totals, orders, customers)
                    line_profiler.runcall(profile_target.render_lines, orders)
                    line_profiler.print_stats(output_unit=1e-3)
                    """
                )
                print(re.sub(r"\\n{2,}", "\\n", line_profile_output))
            else:
                print("line_profiler is not installed: skipping. Install with `uv add --dev line-profiler`.")
            '''
        ),
        md(
            """
            `Hits` is how many times the line ran, `% Time` its share of the function. In
            `find_city` the loop header and the comparison take nearly everything: millions of
            hits for 2 000 lookups, the signature of a linear scan. In `render_lines`
            the `format` + `+=` line dominates.

            #### scalene

            [scalene](https://github.com/plasma-umass/scalene) is a sampling profiler that
            reports, **per line**, time split into *Python* (interpreted bytecode), *native*
            (C code such as NumPy or built-ins) and *system* (the kernel: I/O, sleeping), plus
            memory allocation and copy volume. The split answers "would vectorizing help?":
            time that is already native will not get much faster. `scalene run` saves a JSON
            profile; `scalene view` opens it in a browser or the terminal. Memory tracking
            slows scalene down a lot on this script (every `+=` reallocates a large string),
            so this run is `--cpu-only`; 5.5.4 runs it with memory on the memory target. The
            helper prints the lines with activity from the JSON file:
            """
        ),
        code(
            '''
            def show_scalene(script: str, *options: str) -> None:
                """Profile script with scalene, then print the totals and the lines with activity."""
                print(
                    run_tool(
                        tool_path("scalene") or "scalene", "run", *options, "-o", "scalene_profile.json", script
                    ).splitlines()[0]
                )
                profile = json.loads((PHASE5_DIR / "scalene_profile.json").read_text())
                print(
                    f"elapsed {profile['elapsed_time_sec']:.2f} s, "
                    f"max footprint {profile['max_footprint_mb']:.1f} MB"
                )
                for file_name, file_profile in profile["files"].items():
                    print(
                        f"{'line':>4} {'Python':>7} {'native':>7} {'system':>7} {'alloc MB':>9}  "
                        f"{Path(file_name).name}"
                    )
                    for line in file_profile["lines"]:
                        line["line"] = (
                            line["line"].replace("\\\\u003e", ">").replace("\\\\u003c", "<")
                        )  # scalene escapes < and >
                        shares = (line["n_cpu_percent_python"], line["n_cpu_percent_c"], line["n_sys_percent"])
                        if sum(shares) + line["n_malloc_mb"] >= 0.5:
                            print(
                                f"{line['lineno']:>4} "
                                + " ".join(f"{share:6.1f}%" for share in shares)
                                + f" {line['n_malloc_mb']:>9.1f}  {line['line'].strip()[:58]}"
                            )


            if HAS_SCALENE:
                show_scalene("profile_target.py", "--cpu-only")
            else:
                print("scalene is not installed: skipping. Install with `uv add --dev scalene`.")
            '''
        ),
        md(
            """
            > **Note:** scalene's numbers are statistical and its line attribution is coarser
            > than `line_profiler`'s (it can split a loop's time between the loop header and its
            > body). Use it for the Python/native/system split and the memory columns, and
            > confirm surprises with a second tool.

            #### Which profiler when

            | Question | Tool |
            | --- | --- |
            | Which functions are slow, and how often are they called? | `cProfile` + `pstats` (+ snakeviz to browse) |
            | Where does time go, without slowing the program down? | Tachyon (3.15), py-spy |
            | Which **line** inside this function? | `line_profiler`; Tachyon's line rows |
            | Python time, or already in C? Plus memory per line | scalene |
            | What is a live production process doing right now? | `py-spy dump`, Tachyon `attach` (5.5.12) |
            | Waiting or computing? | Tachyon `--mode wall` vs `--mode cpu`; `perf_counter` vs `process_time` |
            """
        ),
    ]


def _memory_profiling_cells() -> list[NotebookNode]:
    """5.5.4 Memory profiling."""
    return [
        md(
            """
            ### 5.5.4 Memory profiling

            Two numbers describe memory over a run:

            - **current**: what is allocated *now*;
            - **peak**: the highest value *current* ever reached.

            Peak is what decides whether a job fits on a machine (or is killed by the OOM
            killer). A function can end with a small current value after a huge temporary
            peak. Two tool families measure memory:

            | Tool | Sees | Cost |
            | --- | --- | --- |
            | `tracemalloc` (stdlib) | allocations made through Python's allocators, with the source line that made them | slows allocation-heavy code a few times |
            | memray | every allocation, including C/C++ (`malloc`, NumPy, extensions), as a recorded timeline | runs the program under a tracker; reports afterwards |
            | RSS (`/proc`, `resource`, psutil) | what the OS has given the process | free to read, but includes the interpreter, libraries and freed-but-kept memory |

            The target script builds a list of row dicts, then an index over them (freed before
            the end), then a small summary:
            """
        ),
        code(
            '''
            %%writefile _scratch/phase5/memory_target.py
            """Memory profiling target for Unit 5.5: big temporaries, small result."""

            import os

            DEMO_SCALE = int(os.environ.get("PHASE5_DEMO_SCALE", "1"))
            ROW_COUNT = 100_000 * DEMO_SCALE
            CITIES = ("Pune", "Delhi", "Kochi")


            def load_rows(count: int) -> list[dict[str, object]]:
                """One dict per order, with a unique order-id string each."""
                return [{"order_id": f"ORD-{number:07d}", "city": CITIES[number % 3], "amount": number % 50_000} for number in range(count)]


            def build_index(rows: list[dict[str, object]]) -> dict[object, dict[str, object]]:
                """A second big structure: order id -> row."""
                return {row["order_id"]: row for row in rows}


            def summarize(rows: list[dict[str, object]]) -> dict[str, int]:
                """Revenue per city: a tiny result."""
                totals: dict[str, int] = {}
                for row in rows:
                    totals[row["city"]] = totals.get(row["city"], 0) + row["amount"]
                return totals


            def main() -> dict[str, int]:
                """Load, index (temporarily), summarize; only the summary survives."""
                rows = load_rows(ROW_COUNT)
                index = build_index(rows)
                print(f"indexed {len(index):,} orders")
                del index
                return summarize(rows)


            if __name__ == "__main__":
                print(main())
            '''
        ),
        md(
            """
            #### `tracemalloc`

            `tracemalloc.start(frames)` records every allocation with a traceback of up to
            `frames` frames. `get_traced_memory()` returns `(current, peak)`, and a
            `take_snapshot()` groups the live allocations by line. The child script traces the
            target's `main()`:
            """
        ),
        code(
            '''
            print(
                run_child(
                    """
                    import tracemalloc

                    import memory_target

                    tracemalloc.start(5)
                    rows = memory_target.load_rows(memory_target.ROW_COUNT)
                    current, peak = tracemalloc.get_traced_memory()
                    print(f"after load_rows: current {current / 2**20:.1f} MiB, peak {peak / 2**20:.1f} MiB")
                    for stat in tracemalloc.take_snapshot().statistics("lineno")[:3]:
                        print(f"  {stat.size / 2**20:6.1f} MiB in {stat.count:>7,} blocks  {stat.traceback[0]}")
                    index = memory_target.build_index(rows)
                    del index
                    totals = memory_target.summarize(rows)
                    del rows
                    current, peak = tracemalloc.get_traced_memory()
                    print(f"at the end:      current {current / 2**20:.1f} MiB, peak {peak / 2**20:.1f} MiB")
                    bookkeeping_mib = tracemalloc.get_tracemalloc_memory() / 2**20
                    print(f"tracemalloc's own bookkeeping: {bookkeeping_mib:.1f} MiB")
                    """
                )
            )
            '''
        ),
        md(
            """
            Peak vs current is the whole story here: at the end almost nothing is left, but the
            peak (rows + index alive together) is what the machine had to provide. Notice the
            bookkeeping line: tracing costs memory too, so never leave it on in production.

            #### Peak vs current, step by step

            The same functions in the kernel. `tracemalloc.reset_peak()` (3.9+) starts a new
            peak measurement without clearing the traces, so you can measure one phase at a
            time:
            """
        ),
        code(
            """
            import memory_target  # written by the %%writefile cell above

            tracemalloc.start()
            phase_rows = memory_target.load_rows(50_000 * DEMO_SCALE)
            print(
                "after load_rows:   current {:5.1f} MiB  peak {:5.1f} MiB".format(
                    *(byte_count / 2**20 for byte_count in tracemalloc.get_traced_memory())
                )
            )
            tracemalloc.reset_peak()
            phase_totals = memory_target.summarize(phase_rows)
            print(
                "summarize only:    current {:5.1f} MiB  peak {:5.1f} MiB".format(
                    *(byte_count / 2**20 for byte_count in tracemalloc.get_traced_memory())
                )
            )
            del phase_rows
            print(
                "after del rows:    current {:5.1f} MiB  peak {:5.1f} MiB".format(
                    *(byte_count / 2**20 for byte_count in tracemalloc.get_traced_memory())
                )
            )
            tracemalloc.stop()
            print(f"{phase_totals=}")
            """
        ),
        md(
            """
            `summarize` alone adds almost nothing to the peak: it streams over the rows. Deleting
            the rows brings *current* back down, while the peak of that phase stays.

            **Finding growth (leaks).** Take a snapshot, run the suspect code, take another, and
            `compare_to` lists the lines whose memory grew. Here a module-level cache that is
            never trimmed is the "leak":
            """
        ),
        code(
            '''
            response_cache: dict[int, bytes] = {}


            def handle_request(request_id: int) -> int:
                """Pretend request handler that caches every response forever."""
                response_cache[request_id] = bytes(2_000)  # a new 2 kB object per request
                return len(response_cache[request_id])


            tracemalloc.start()
            before = tracemalloc.take_snapshot()
            for request_id in range(2_000):
                handle_request(request_id)
            after = tracemalloc.take_snapshot()
            tracemalloc.stop()
            for stat in after.compare_to(before, "lineno")[:2]:
                frame = stat.traceback[0]
                source = linecache.getline(frame.filename, frame.lineno).strip()
                print(
                    f"+{stat.size_diff / 1024:7.1f} KiB  +{stat.count_diff:>5} blocks  "
                    f"line {frame.lineno}: {source}"
                )
            '''
        ),
        md(
            """
            The top entry is the line that stores a new `bytes(2_000)` per request: about
            4 MB in 2 000 new blocks (the dict's own growth comes next). In a real service you
            would take the two snapshots minutes apart.

            **RSS is a different number.** The operating system sees pages, not objects. RSS
            includes the interpreter and loaded libraries, and memory that Python freed but
            kept for reuse (small objects live in *arenas* that are only returned when
            completely empty). Large blocks go straight to `mmap` and are returned at once:
            """
        ),
        code(
            '''
            def rss_mib() -> float | None:
                """Resident set size of this process in MiB (Linux /proc, psutil fallback)."""
                status_file = Path("/proc/self/status")
                if status_file.exists():
                    for line in status_file.read_text().splitlines():
                        if line.startswith("VmRSS:"):
                            return int(line.split()[1]) / 1024
                if has_module("psutil"):
                    import psutil

                    return psutil.Process().memory_info().rss / 2**20
                return None


            print(f"RSS now:                     {rss_mib():7.1f} MiB")
            big_block = bytearray(200 * 2**20)  # one 200 MiB allocation (mmap)
            print(f"with a 200 MiB bytearray:    {rss_mib():7.1f} MiB")
            del big_block
            print(f"after del (block returned):  {rss_mib():7.1f} MiB")
            '''
        ),
        md(
            """
            The bytearray's pages are touched (zero-filled) as it is created, so RSS rises by
            about 200 MiB and falls back when it is freed. A list of a million small objects
            behaves differently: after `del` some of the memory may stay in the process. The
            numbers vary by OS and allocator.

            #### memray

            [memray](https://bloomberg.github.io/memray/) (Bloomberg) records **every**
            allocation, including those made by C code, into a capture file while the program
            runs, then turns the file into reports: `stats` (totals and histograms), `summary`
            (a table by function), `flamegraph` and `table` (HTML), and `tree`/`live`
            (interactive terminal views, not used here). memray supports Linux and macOS.
            """
        ),
        code(
            """
            if HAS_MEMRAY:
                memray = tool_path("memray") or "memray"
                print(
                    run_tool(
                        memray, "run", "--force", "-o", "memory_target.bin", "memory_target.py"
                    ).splitlines()[0]
                )
                memray_stats = run_tool(memray, "stats", "memory_target.bin")
                print(first_lines(memray_stats[memray_stats.find("📏") :], 9))
            else:
                print(
                    "memray is not installed (Linux/macOS only): skipping. Install with `uv add --dev memray`."
                )
            """
        ),
        md(
            """
            "Total memory allocated" adds up every allocation over the run (memory reused many
            times counts many times); **peak memory usage** is the high-water mark. The `stats`
            report also lists the locations that allocated the most:
            """
        ),
        code(
            """
            if HAS_MEMRAY:
                top_start = memray_stats.find("🥇 Top 5 largest allocating locations (by size)")
                print(first_lines(memray_stats[top_start:], 6))
                print(run_tool(memray, "flamegraph", "--force", "-o", "memory_flame.html", "memory_target.bin"))
                print(
                    f"HTML peak-memory flame graph: {(PHASE5_DIR / 'memory_flame.html').stat().st_size:,} bytes"
                )
            else:
                print("memray is not installed: skipping.")
            """
        ),
        md(
            """
            `load_rows` (the dict and the f-string per row) and `build_index` lead, as
            expected. The memray flame graph is a flame graph of the allocations alive **at
            the peak**: the same reading rules as 5.5.3, with width meaning bytes instead of
            samples.

            scalene (5.5.3) also measures memory per line when it runs without `--cpu-only`:
            """
        ),
        code(
            """
            if HAS_SCALENE:
                show_scalene("memory_target.py")
            else:
                print("scalene is not installed: skipping.")
            """
        ),
        md(
            """
            The `alloc MB` column puts the row dicts (`load_rows`) first and the index second,
            matching tracemalloc and memray.

            > **Note:** for C extensions, `memray run --native` adds C stack frames, and
            > `memray run --live` shows allocations as they happen. `pytest-memray` turns
            > memory limits into test failures.
            """
        ),
    ]


def _algorithmic_cells() -> list[NotebookNode]:
    """5.5.5 Algorithmic optimization."""
    return [
        md(
            """
            ### 5.5.5 Algorithmic optimization

            The largest wins come from doing **less work**, not from doing the same work
            faster. A better algorithm turns 10 s into 10 ms; a micro-optimization turns 10 s
            into 8 s. This section measures with a small helper that returns the best time
            per call:
            """
        ),
        code(
            '''
            def best_seconds(work: Callable[[], object], number: int = 5, repeat: int = 3) -> float:
                """Best (minimum) seconds per call of work over `repeat` rounds of `number` calls."""
                return min(timeit.repeat(work, number=number, repeat=repeat)) / number
            '''
        ),
        md(
            """
            #### Right data structures

            | Operation | `list` | `dict` / `set` | `collections.deque` |
            | --- | --- | --- | --- |
            | `x in container` | O(n) scan | **O(1)** hash lookup | O(n) |
            | lookup by key | O(n) scan (as `find_city` did) | **O(1)** | — |
            | append / pop at the end | O(1) amortized | — | O(1) |
            | insert / pop at the **front** | **O(n)**: shifts every element | — | **O(1)** |
            | index `container[i]` | O(1) | — | O(n) in the middle |

            The `find_city` fix from 5.5.3: build a dict once (O(n)), then each lookup is O(1):
            """
        ),
        code(
            '''
            import profile_target  # the 5.5.3 script, importable from the scratch folder

            customers = profile_target.make_customers(2_500)
            orders = profile_target.make_orders(8_000 * DEMO_SCALE, customers)


            def city_totals_dict(
                orders: list[tuple[int, int]], customers: list[tuple[int, str]]
            ) -> dict[str, int]:
                """Same result as profile_target.city_totals, with one dict instead of a scan per order."""
                city_of = dict(customers)  # customer_id -> city, built once
                totals: dict[str, int] = {}
                for customer_id, amount in orders:
                    city = city_of[customer_id]
                    totals[city] = totals.get(city, 0) + amount
                return totals


            scan_seconds = best_seconds(lambda: profile_target.city_totals(orders, customers), number=1)
            dict_seconds = best_seconds(lambda: city_totals_dict(orders, customers))
            print(
                "same result:",
                city_totals_dict(orders, customers) == profile_target.city_totals(orders, customers),
            )
            print(
                f"linear scan {scan_seconds * 1000:.1f} ms, dict {dict_seconds * 1000:.2f} ms "
                f"-> {scan_seconds / dict_seconds:.0f}x"
            )
            '''
        ),
        md(
            "Membership tests show the same gap, and `list.pop(0)` vs `deque.popleft()` shows the cost of shifting:"
        ),
        code(
            '''
            blocked_ids = list(range(0, 200_000, 3))
            blocked_set = set(blocked_ids)
            queries = range(1_000)
            list_seconds = best_seconds(lambda: sum(query in blocked_ids for query in queries), number=1)
            set_seconds = best_seconds(lambda: sum(query in blocked_set for query in queries))
            print(f"1 000 membership tests: list {list_seconds * 1000:.1f} ms, set {set_seconds * 1000:.3f} ms")


            def drain_list(count: int) -> None:
                """Empty a list from the front (each pop(0) shifts the rest)."""
                items = list(range(count))
                while items:
                    items.pop(0)  # shifts every remaining element


            def drain_deque(count: int) -> None:
                """Empty a deque from the front (each popleft is O(1))."""
                items = deque(range(count))
                while items:
                    items.popleft()


            print(
                "drain 50 000 from the front: "
                f"list {best_seconds(lambda: drain_list(50_000), number=1) * 1000:.1f} ms, "
                f"deque {best_seconds(lambda: drain_deque(50_000), number=1) * 1000:.1f} ms"
            )
            '''
        ),
        md(
            """
            #### Removing quadratic loops

            A loop inside a loop over the same data is O(n²): double the input, quadruple the
            time. The classic example is "which order ids appear twice?":
            """
        ),
        code(
            '''
            def duplicates_quadratic(order_ids: list[int]) -> set[int]:
                """Compare every pair: O(n^2)."""
                found = set()
                for position, order_id in enumerate(order_ids):
                    if order_id in order_ids[position + 1 :]:  # a scan inside the loop
                        found.add(order_id)
                return found


            def duplicates_linear(order_ids: list[int]) -> set[int]:
                """Remember what was seen: O(n)."""
                seen: set[int] = set()
                found = set()
                for order_id in order_ids:
                    if order_id in seen:
                        found.add(order_id)
                    seen.add(order_id)
                return found
            '''
        ),
        md(
            "Time both at n and 2n. The growth factor tells the complexity class, whatever the machine:"
        ),
        code(
            """
            id_rng = random.Random(42)
            for label, finder in (("quadratic", duplicates_quadratic), ("linear", duplicates_linear)):
                timings = []
                for size in (2_000, 4_000):
                    order_ids = [id_rng.randrange(size * 10) for _ in range(size)]
                    timings.append(best_seconds(lambda find=finder, ids=order_ids: find(ids), number=1))
                print(
                    f"{label:<9} n=2000: {timings[0] * 1000:7.2f} ms  n=4000: {timings[1] * 1000:7.2f} ms  "
                    f"growth x{timings[1] / timings[0]:.1f}"
                )
            sample_ids = [5, 3, 5, 9, 3, 5]
            print(f"same answer: {duplicates_quadratic(sample_ids) == duplicates_linear(sample_ids) == {3, 5}}")
            """
        ),
        md(
            """
            Doubling n roughly quadruples the quadratic version and doubles the linear one.
            Hidden quadratic loops are common: `x in some_list` inside a loop, `list.remove`
            or `list.insert(0, …)` in a loop, `str +=` in some cases, or repeated `sorted()`
            inside a loop.

            #### `heapq`

            `heapq` keeps a list arranged as a binary min-heap: `heappush`/`heappop` cost
            O(log n), and the smallest item is always at index 0. Use it for "the k largest",
            priority queues, and merging sorted streams.
            """
        ),
        code(
            """
            sale_rng = random.Random(7)
            sale_amounts = [sale_rng.randrange(100, 1_000_000) for _ in range(500_000 * DEMO_SCALE)]
            top_by_sort = sorted(sale_amounts, reverse=True)[:5]
            top_by_heap = heapq.nlargest(5, sale_amounts)
            print(f"{top_by_heap=}  same as sorting: {top_by_heap == top_by_sort}")
            sort_seconds = best_seconds(lambda: sorted(sale_amounts, reverse=True)[:5], number=1)
            heap_seconds = best_seconds(lambda: heapq.nlargest(5, sale_amounts), number=1)
            print(
                f"top 5 of {len(sale_amounts):,}: full sort {sort_seconds * 1000:.0f} ms, "
                f"nlargest {heap_seconds * 1000:.0f} ms"
            )
            """
        ),
        md(
            """
            `nlargest(k, …)` keeps only a k-sized heap: O(n log k) time and O(k) memory,
            against O(n log n) and O(n) for a full sort. (For k close to n, sorting wins, and
            `heapq` says so in its docs.) As a priority queue, push `(priority, sequence,
            item)` tuples; the sequence number breaks ties so items themselves are never
            compared:
            """
        ),
        code(
            """
            delivery_queue: list[tuple[int, int, str]] = []
            for sequence, (priority, order_id) in enumerate(
                [(3, "ORD-7"), (1, "ORD-2"), (2, "ORD-9"), (1, "ORD-4")]
            ):
                heapq.heappush(delivery_queue, (priority, sequence, order_id))
            print("dispatch order:", [heapq.heappop(delivery_queue)[2] for _ in range(len(delivery_queue))])
            morning, evening = [3, 8, 15], [1, 9, 12, 20]  # already sorted
            print("merged lazily:", list(heapq.merge(morning, evening)))
            """
        ),
        md(
            """
            #### `bisect`

            `bisect` searches a **sorted** list by halving: O(log n) per lookup.
            `bisect_left(a, x)` returns the first position where `x` could be inserted (before
            equal items), `bisect_right` the last; `insort` inserts while keeping the order.
            A typical use is bucket lookup, such as finding the tax slab for an income:
            """
        ),
        code(
            '''
            slab_starts = [0, 400_000, 800_000, 1_200_000, 1_600_000, 2_000_000, 2_400_000]  # rupees
            slab_rates = [0, 5, 10, 15, 20, 25, 30]  # percent


            def marginal_rate(income: int) -> int:
                """Tax rate of the slab containing income (bisect_right: a slab start belongs to that slab)."""
                return slab_rates[bisect.bisect_right(slab_starts, income) - 1]


            print([(income, marginal_rate(income)) for income in (0, 399_999, 400_000, 1_250_000, 9_000_000)])
            prices = [10, 20, 20, 30]
            print(
                f"bisect_left={bisect.bisect_left(prices, 20)}  bisect_right={bisect.bisect_right(prices, 20)}"
            )
            bisect.insort(prices, 25)
            print(f"after insort(25): {prices}")
            '''
        ),
        md(
            """
            `key=` (3.10+) searches by a derived value without building a separate list of
            keys; the list must be sorted by that same key. Against a linear scan the
            difference grows with the list:
            """
        ),
        code(
            """
            price_list = sorted(
                (sale_rng.randrange(1_000_000), f"SKU-{sku_number}") for sku_number in range(200_000)
            )
            target_price = price_list[150_000][0]
            by_bisect = price_list[bisect.bisect_left(price_list, target_price, key=lambda item: item[0])]
            by_scan = next(item for item in price_list if item[0] >= target_price)
            print(f"same item: {by_bisect == by_scan}")
            scan_seconds = best_seconds(lambda: next(item for item in price_list if item[0] >= target_price))
            bisect_seconds = best_seconds(
                lambda: bisect.bisect_left(price_list, target_price, key=lambda item: item[0]), number=1000
            )
            print(
                f"scan {scan_seconds * 1e6:,.0f} µs, bisect {bisect_seconds * 1e6:.2f} µs "
                f"-> {scan_seconds / bisect_seconds:,.0f}x"
            )
            """
        ),
        md(
            """
            #### Memoization

            When a function is called again and again with the same arguments, remember the
            answers. Recursive problems with overlapping subproblems go from exponential to
            linear. Counting the calls makes the difference visible without any timing:
            """
        ),
        code(
            '''
            call_counter = Counter()


            def ways_to_pay(amount: int, coins: tuple[int, ...]) -> int:
                """Number of ways to pay `amount` with the coins (order matters): exponential."""
                call_counter["plain"] += 1
                if amount == 0:
                    return 1
                return sum(ways_to_pay(amount - coin, coins) for coin in coins if coin <= amount)


            @functools.cache
            def ways_to_pay_cached(amount: int, coins: tuple[int, ...]) -> int:
                """The same recursion; each (amount, coins) pair is computed once."""
                call_counter["cached"] += 1
                if amount == 0:
                    return 1
                return sum(ways_to_pay_cached(amount - coin, coins) for coin in coins if coin <= amount)


            coins = (1, 2, 5)
            print(ways_to_pay(22, coins), ways_to_pay_cached(22, coins), dict(call_counter))
            print(ways_to_pay_cached.cache_info())
            '''
        ),
        md(
            """
            Same answer, hundreds of thousands of calls against 23. `functools.cache` is an
            unbounded `lru_cache`; 5.5.8 covers bounded caches, hit rates and invalidation.
            Memoization trades memory for time and needs hashable arguments (hence the
            `tuple` of coins, not a list).
            """
        ),
    ]


def _interpreter_cells() -> list[NotebookNode]:
    """5.5.6 Interpreter-level optimization."""
    return [
        md(
            """
            ### 5.5.6 Interpreter-level optimization

            After the algorithm is right, the remaining cost is the interpreter's work per
            operation: each bytecode instruction, attribute lookup, function call and
            temporary object costs tens of nanoseconds. These habits reduce that work. Measure
            each one; since 3.11 the specializing interpreter has made several old tricks
            (local aliases especially) worth much less than they used to be.

            The helper prints nanoseconds per call for a few variants of the same operation:
            """
        ),
        code(
            '''
            def compare_variants(
                title: str, variants: dict[str, Callable[[], object]], number: int = 200
            ) -> None:
                """Print best time per call of each variant (in input order) and its ratio to the first."""
                print(title)
                baseline = None
                for label, work in variants.items():
                    seconds = best_seconds(work, number=number, repeat=5)
                    baseline = baseline or seconds
                    print(f"  {label:<34} {seconds * 1e6:9.2f} µs   x{seconds / baseline:.2f}")
            '''
        ),
        md(
            """
            #### Local aliases

            A global name costs a dictionary lookup (cached by `LOAD_GLOBAL` specialization
            since 3.11), and `module.attribute` costs one more lookup per use. Binding the
            function to a local name once makes each use a `LOAD_FAST`, an array index:
            """
        ),
        code(
            '''
            def roots_global(values: list[float]) -> list[float]:
                """math.sqrt looked up on every iteration."""
                result = []
                for value in values:
                    result.append(math.sqrt(value))
                return result


            def roots_local(values: list[float]) -> list[float]:
                """sqrt and append bound to locals once."""
                result = []
                append, sqrt = result.append, math.sqrt
                for value in values:
                    append(sqrt(value))
                return result


            float_values = [float(number) for number in range(10_000)]
            compare_variants(
                "10 000 square roots",
                {
                    "math.sqrt + result.append": lambda: roots_global(float_values),
                    "local aliases": lambda: roots_local(float_values),
                },
            )
            '''
        ),
        md(
            "Under the hood, `dis` of the loop body shows the difference: the first loop does a global load and two attribute loads per iteration, the second only fast local loads. Measured above, the gain is small on 3.15, because those loads are specialized and cached:"
        ),
        code(
            """
            import dis

            for function in (roots_global, roots_local):
                source_lines, first_line = inspect.getsourcelines(function)
                body_line = first_line + next(
                    line_number
                    for line_number, line in enumerate(source_lines)
                    if "append(" in line and "=" not in line
                )
                body_ops = [
                    instruction.opname
                    for instruction in dis.get_instructions(function)
                    if instruction.positions and instruction.positions.lineno == body_line
                ]
                print(f"{function.__name__:<13} loop body: {' '.join(body_ops)}")
            """
        ),
        md(
            """
            #### Built-ins written in C

            `sum`, `min`, `max`, `sorted`, `any`, `map`, `str.join` and friends run their loop
            in C, without dispatching one bytecode per element. Moving a loop *into* a built-in
            usually beats any amount of tuning of the Python loop:
            """
        ),
        code(
            '''
            def manual_sum(values: list[int]) -> int:
                """Sum with a Python loop."""
                total = 0
                for value in values:
                    total += value
                return total


            int_values = list(range(100_000))
            compare_variants(
                "sum of 100 000 ints",
                {"Python for loop": lambda: manual_sum(int_values), "built-in sum()": lambda: sum(int_values)},
                number=20,
            )
            compare_variants(
                "max of 100 000 ints",
                {
                    "max with a key lambda": lambda: max(int_values, key=lambda value: value),
                    "plain max()": lambda: max(int_values),
                },
                number=20,
            )
            '''
        ),
        md(
            """
            The `key=lambda` version is slower because it calls a Python function per element:
            the loop is in C, the work per element is not. Prefer `operator.itemgetter` /
            `attrgetter` over a lambda when a key is needed.

            #### `str.join` instead of `+=`

            Strings are immutable, so `text += piece` creates a new string. CPython has an
            in-place shortcut when the string has no other reference, which often hides the
            cost, but the shortcut breaks as soon as another reference exists. `"".join(parts)`
            computes the final size once and copies each piece once:
            """
        ),
        code(
            '''
            pieces = [f"line {line_number}\\n" for line_number in range(20_000)]


            def concat_plus(parts: list[str]) -> str:
                """Join with += on a string that has no other reference."""
                text = ""
                for part in parts:
                    text += part  # in-place resize when `text` has no other reference
                return text


            def concat_plus_shared(parts: list[str]) -> str:
                """Join with += while keeping old strings alive (full copies)."""
                text, history = "", []
                for part in parts[:5_000]:
                    history.append(text)  # a second reference defeats the shortcut: full copy each time
                    text += part
                return text


            compare_variants(
                "joining text",
                {
                    "+= (shortcut applies)": lambda: concat_plus(pieces),
                    "+= with a second reference (1/4 of the pieces)": lambda: concat_plus_shared(pieces),
                    '"".join(parts)': lambda: "".join(pieces),
                },
                number=10,
            )
            '''
        ),
        md(
            """
            The shortcut is a CPython implementation detail (PyPy and other implementations do
            not have it), and it does not apply to `bytes`. `join` is the portable, always
            linear choice; for bytes use `b"".join` or `io.BytesIO`.

            #### Comprehensions

            A list comprehension avoids the `result.append` lookup and call per element. Since
            3.12 (PEP 709) comprehensions are also **inlined**: no hidden function object is
            created and called each time the comprehension runs:
            """
        ),
        code(
            '''
            def squares_loop(count: int) -> list[int]:
                """Build the squares with append in a loop."""
                result = []
                for number in range(count):
                    result.append(number * number)
                return result


            def squares_comprehension(count: int) -> list[int]:
                """Build the squares with a list comprehension."""
                return [number * number for number in range(count)]


            compare_variants(
                "10 000 squares",
                {
                    "for + append": lambda: squares_loop(10_000),
                    "list comprehension": lambda: squares_comprehension(10_000),
                },
            )
            makes_function = any(
                instruction.opname == "MAKE_FUNCTION"
                for instruction in dis.get_instructions(squares_comprehension)
            )
            print("comprehension compiled inline (no hidden function object):", not makes_function)
            '''
        ),
        md(
            """
            #### Avoiding exceptions in hot paths

            Since 3.11 a `try` block costs **nothing** when no exception is raised ("zero-cost"
            exception handling). *Raising* and catching is still expensive: an exception
            object, a traceback, unwinding. So `try/except` is the fastest choice when misses
            are rare and the slowest when they are common:
            """
        ),
        code(
            '''
            stock = {f"SKU-{sku_number}": sku_number for sku_number in range(1_000)}


            def count_with_try(skus: list[str]) -> int:
                """Sum stock with try/except for missing SKUs."""
                total = 0
                for sku in skus:
                    try:
                        total += stock[sku]
                    except KeyError:
                        pass
                return total


            def count_with_get(skus: list[str]) -> int:
                """Sum stock with dict.get for missing SKUs."""
                total = 0
                for sku in skus:
                    total += stock.get(sku, 0)
                return total
            '''
        ),
        md("Two workloads: every key present, and half the keys missing:"),
        code(
            """
            all_hits = [f"SKU-{lookup_number % 1_000}" for lookup_number in range(10_000)]
            half_misses = [f"SKU-{lookup_number % 2_000}" for lookup_number in range(10_000)]
            compare_variants(
                "all keys present",
                {
                    "try/except KeyError": lambda: count_with_try(all_hits),
                    "dict.get": lambda: count_with_get(all_hits),
                },
            )
            compare_variants(
                "half the keys missing",
                {
                    "try/except KeyError": lambda: count_with_try(half_misses),
                    "dict.get": lambda: count_with_get(half_misses),
                },
            )
            """
        ),
        md(
            """
            #### Type-stable code

            The specializing adaptive interpreter (PEP 659, 3.11+) watches the types each
            instruction sees and rewrites it into a specialized form: `BINARY_OP` becomes
            `BINARY_OP_ADD_INT` when both operands keep being ints. When the types keep
            changing, the specialization fails and the instruction falls back to the generic,
            slower path. V8 does the same with hidden classes and inline caches; mixing types
            in a hot loop hurts both. `dis(..., adaptive=True)` shows the rewritten bytecode:
            """
        ),
        code(
            '''
            def running_total(values: list) -> float:
                """Add up values; the + instruction specializes on the types it sees."""
                total = 0
                for value in values:
                    total = total + value
                return total


            def specialized_adds(values: list) -> list[str]:
                """Warm the function up on `values`, then list the specialized forms of its `+`."""
                code_copy = running_total.__code__.replace()  # a fresh code object: no earlier specialization
                fresh = type(running_total)(code_copy, globals())
                for _ in range(50):
                    fresh(values)
                return sorted(
                    {
                        instruction.opname
                        for instruction in dis.get_instructions(fresh, adaptive=True)
                        if instruction.opname.startswith("BINARY_OP")
                    }
                )


            print("ints only:   ", specialized_adds(list(range(1_000))))
            print("floats only: ", specialized_adds([number / 2 for number in range(1_000)]))
            '''
        ),
        md(
            """
            The same `+` became `BINARY_OP_ADD_INT` or `BINARY_OP_ADD_FLOAT` depending on the
            data it ran on (the exact opnames are a CPython detail and change between
            versions). Each specialized instruction carries a cheap guard; when the guard keeps
            failing because the types keep changing, the instruction is de-specialized and
            re-specialized, and each pass does more work.

            Attribute access shows the cost most clearly. `item.price` on objects of **one**
            class hits the same inline cache entry every time; objects of four different
            classes (four "shapes", in V8 terms) keep missing it, exactly like a polymorphic
            call site in JavaScript:
            """
        ),
        code(
            '''
            def make_item_classes(count: int) -> list[type]:
                """`count` distinct classes whose instances all have a `price` attribute."""

                def __init__(self: object, price: int) -> None:
                    """Store the price."""
                    self.price = price

                return [type(f"Item{number}", (), {"__init__": __init__}) for number in range(count)]


            def total_price(items: list) -> int:
                """Sum item.price over the items."""
                total = 0
                for item in items:
                    total += item.price
                return total


            one_class, four_classes = make_item_classes(1), make_item_classes(4)
            same_shape = [one_class[0](index) for index in range(100_000)]
            mixed_shapes = [four_classes[index % 4](index) for index in range(100_000)]
            compare_variants(
                "total_price over 100 000 objects",
                {
                    "one class (monomorphic)": lambda: total_price(same_shape),
                    "four classes (polymorphic)": lambda: total_price(mixed_shapes),
                },
                number=20,
            )
            '''
        ),
        md(
            """
            Same values, same code, more time per item for the mixed list. Consistent types
            are what *every* optimizing layer relies on: the specializer, the JIT (5.5.11),
            Cython, NumPy dtypes, V8.
            """
        ),
    ]


def _memory_lean_cells() -> list[NotebookNode]:
    """5.5.7 Memory-lean data."""
    return [
        md(
            """
            ### 5.5.7 Memory-lean data

            Every Python value is an object with a header (reference count and type pointer,
            16 bytes on 64-bit builds) and every container holds 8-byte pointers to objects.
            A million small records therefore cost far more than their raw data. The helper
            measures how much memory a structure **keeps** after it is built (traced bytes
            still allocated while the result is alive):
            """
        ),
        code(
            '''
            def retained_bytes(build: Callable[[], object]) -> tuple[object, int]:
                """Build an object under tracemalloc; return it and the bytes it still holds."""
                gc.collect()
                tracemalloc.start()
                before = tracemalloc.get_traced_memory()[0]
                result = build()
                kept = tracemalloc.get_traced_memory()[0] - before
                tracemalloc.stop()
                return result, kept
            '''
        ),
        md(
            """
            #### `__slots__`

            A regular instance stores attributes in a per-instance dict (shared keys and inline
            values since 3.11–3.13 make that cheaper than it was). `__slots__` replaces it with
            fixed fields in the object itself: smaller, and no new attributes can be added.
            `@dataclass(slots=True)` (3.10+) generates the slots for you; a `tuple` subclass
            such as `NamedTuple` is smaller still:
            """
        ),
        code(
            '''
            class PlainReading:
                """A reading with a per-instance __dict__."""

                def __init__(self, sensor_id: int, value: float) -> None:
                    """Store the sensor id and value."""
                    self.sensor_id, self.value = sensor_id, value


            class SlottedReading:
                """A reading with __slots__ (no per-instance __dict__)."""

                __slots__ = ("sensor_id", "value")

                def __init__(self, sensor_id: int, value: float) -> None:
                    """Store the sensor id and value."""
                    self.sensor_id, self.value = sensor_id, value


            @dataclass(slots=True)
            class DataclassReading:
                """A reading as a slotted dataclass."""

                sensor_id: int
                value: float
            '''
        ),
        md("100 000 instances of each, plus the bare tuple:"),
        code(
            """
            reading_count = 100_000 * DEMO_SCALE
            for label, record_type in (
                ("plain class", PlainReading),
                ("__slots__ class", SlottedReading),
                ("dataclass(slots=True)", DataclassReading),
                ("tuple", lambda *fields: fields),
            ):
                _, kept = retained_bytes(
                    lambda make=record_type: [
                        make(reading_number, reading_number * 0.5) for reading_number in range(reading_count)
                    ]
                )
                print(
                    f"{label:<22} {kept / reading_count:6.1f} bytes per record "
                    "(list pointer and float included)"
                )
            print(
                "slots forbid new attributes:",
                raised_error_name(lambda: setattr(SlottedReading(1, 2.0), "unit", "C")),
            )
            """
        ),
        md(
            """
            #### `array`

            `array.array(typecode)` stores raw machine numbers in one contiguous buffer, like a
            JavaScript typed array: 8 bytes per `'q'` (signed 64-bit) item instead of an
            8-byte pointer plus a 28-byte (or larger) `int` object. Small ints (−5…1024 in
            3.15) are shared singletons, so the list side is measured with larger values:
            """
        ),
        code(
            """
            int_count = 200_000 * DEMO_SCALE
            int_list, list_bytes = retained_bytes(lambda: [number * 1_000 for number in range(int_count)])
            int_array, array_bytes = retained_bytes(
                lambda: array.array("q", (number * 1_000 for number in range(int_count)))
            )
            print(f"list of ints : {list_bytes / int_count:5.1f} bytes per item")
            print(
                f"array('q')   : {array_bytes / int_count:5.1f} bytes per item, itemsize={int_array.itemsize}"
            )
            print(
                f"same values: {list(int_array[:3]) == int_list[:3]}, "
                f"raw buffer {len(int_array.tobytes()):,} bytes"
            )
            """
        ),
        md(
            """
            #### `memoryview`

            Slicing `bytes`, `bytearray` or an `array` **copies** the data. A `memoryview`
            slice is a window onto the same buffer (the buffer protocol, PEP 3118): no copy,
            and writes through a view of a mutable buffer change the original. `.cast()`
            reinterprets the bytes with another format:
            """
        ),
        code(
            """
            payload = bytes(50 * 2**20)  # a 50 MiB "file" already in memory
            _, slice_bytes = retained_bytes(lambda: payload[10 : 40 * 2**20])
            _, view_bytes = retained_bytes(lambda: memoryview(payload)[10 : 40 * 2**20])
            print(
                f"bytes slice copies {slice_bytes / 2**20:.1f} MiB; memoryview slice keeps {view_bytes} bytes"
            )

            frame = bytearray(b"HDR:temperature=21")
            body = memoryview(frame)[4:]  # skip the header, no copy
            body[:4] = b"TEMP"
            print(frame, "| as unsigned 32-bit ints:", memoryview(bytearray(range(8))).cast("I").tolist())
            payload = b""  # release the 50 MiB buffer
            """
        ),
        md(
            """
            #### Generators

            A list comprehension materializes every element; a generator expression produces
            one element at a time. When the result is consumed once (summed, written, filtered
            into something small), the generator's peak memory stays constant:
            """
        ),
        code(
            '''
            def peak_during(work: Callable[[], object]) -> int:
                """Peak traced bytes while running work (current baseline excluded)."""
                tracemalloc.start()
                work()
                peak = tracemalloc.get_traced_memory()[1]
                tracemalloc.stop()
                return peak


            line_count = 300_000 * DEMO_SCALE
            list_peak = peak_during(
                lambda: sum(
                    [
                        len(f"order {order_number},Pune,{order_number % 997}")
                        for order_number in range(line_count)
                    ]
                )
            )
            generator_peak = peak_during(
                lambda: sum(
                    len(f"order {order_number},Pune,{order_number % 997}") for order_number in range(line_count)
                )
            )
            print(f"sum over a list comprehension: peak {list_peak / 2**20:7.2f} MiB")
            print(f"sum over a generator:          peak {generator_peak / 2**20:7.2f} MiB")
            generator_bytes = sys.getsizeof(order_number for order_number in range(line_count))
            print(f"generator object itself: {generator_bytes} bytes")
            '''
        ),
        md(
            """
            #### Interning

            Strings parsed from input are new objects even when their text repeats: a million
            rows with five city names hold a million city strings. `sys.intern` returns one
            canonical object per distinct text, so repeats share it (and `is` comparisons
            become possible). Identifiers and many literals are interned automatically;
            runtime strings are not:
            """
        ),
        code(
            """
            csv_lines = [
                f"{row_number},{('Pune', 'Delhi', 'Kochi', 'Patna', 'Surat')[row_number % 5]},"
                f"{row_number % 997}"
                for row_number in range(200_000 * DEMO_SCALE)
            ]
            plain_cities, plain_bytes = retained_bytes(lambda: [line.split(",")[1] for line in csv_lines])
            interned_cities, interned_bytes = retained_bytes(
                lambda: [sys.intern(line.split(",")[1]) for line in csv_lines]
            )
            print(
                f"plain split  : {plain_bytes / 2**20:5.1f} MiB, "
                f"distinct objects {len({id(city) for city in plain_cities}):,}"
            )
            print(
                f"sys.intern   : {interned_bytes / 2**20:5.1f} MiB, "
                f"distinct objects {len({id(city) for city in interned_cities}):,}"
            )
            del plain_cities, interned_cities
            """
        ),
        md(
            """
            The interned list holds five string objects and 200 000 pointers to them. pandas'
            `category` dtype and Polars' `Categorical` apply the same idea to columns.
            """
        ),
    ]


def _caching_cells() -> list[NotebookNode]:
    """5.5.8 Caching."""
    return [
        md(
            """
            ### 5.5.8 Caching

            A cache is worth having when the **hit rate** is high, the computation is expensive
            compared with a lookup, and stale answers are either impossible or acceptable for a
            known time. Every cache needs an answer to "when is an entry wrong?" (invalidation)
            and "how big may it grow?" (eviction).

            #### `lru_cache` hit rates

            `functools.lru_cache(maxsize=N)` keeps the N most recently used results;
            `cache_info()` reports hits, misses and the current size. The hit rate depends on
            how the access pattern compares with `maxsize`. Here a few products are requested
            far more often than the rest (a typical skewed pattern):
            """
        ),
        code(
            '''
            def product_requests(count: int, product_count: int = 500, seed: int = 42) -> list[int]:
                """Skewed product ids: low ids are requested much more often (roughly Zipf-like)."""
                request_rng = random.Random(seed)
                weights = [1 / (rank + 1) for rank in range(product_count)]
                return request_rng.choices(range(product_count), weights=weights, k=count)


            def hit_rate(maxsize: int | None, requests: list[int]) -> tuple[float, object]:
                """Replay requests through a fresh lru_cache of the given size."""

                @functools.lru_cache(maxsize=maxsize)
                def load_product(product_id: int) -> str:
                    """Pretend to load a product from the database."""
                    return f"product {product_id}"

                for product_id in requests:
                    load_product(product_id)
                info = load_product.cache_info()
                return info.hits / (info.hits + info.misses), info
            '''
        ),
        md("The same 20 000 requests through caches of growing size:"),
        code(
            """
            requests = product_requests(20_000)
            for maxsize in (8, 32, 128, 512, None):
                rate, info = hit_rate(maxsize, requests)
                print(f"maxsize={maxsize!s:<5} hit rate {rate:6.1%}   {info}")
            """
        ),
        md(
            """
            A small cache already catches the hot items; beyond the number of distinct keys
            (500 here) a bigger cache cannot help. Measure the hit rate on real traffic before
            choosing `maxsize`, and remember that `maxsize=None` never evicts: it is a memory
            leak if the key space is unbounded.

            #### TTL caches

            When the underlying data changes (exchange rates, a remote config), entries must
            **expire**. `cachetools.TTLCache(maxsize, ttl, timer=...)` (installed in Phase 4)
            evicts entries older than `ttl` seconds. A fake clock makes the demo
            deterministic:
            """
        ),
        code(
            '''
            if has_module("cachetools"):
                import cachetools

                fake_now = [0.0]
                rate_cache = cachetools.TTLCache(maxsize=100, ttl=60, timer=lambda: fake_now[0])
                upstream_calls = []

                @cachetools.cached(rate_cache)
                def exchange_rate(currency: str) -> float:
                    """Record the upstream call and return the rate."""
                    upstream_calls.append((fake_now[0], currency))
                    return {"USD": 83.25, "EUR": 90.10}[currency]

                for moment in (0, 10, 59, 61, 70):
                    fake_now[0] = moment
                    exchange_rate("USD")
                print(
                    f"5 lookups, {len(upstream_calls)} upstream calls "
                    f"at t={[when for when, _ in upstream_calls]}"
                )
            else:
                print("cachetools is not installed: skipping.")
            '''
        ),
        md(
            """
            The entry fetched at t=0 serves t=10 and t=59, expires at t=60, and is fetched again
            at t=61. A TTL bounds staleness; it does not prevent it.

            #### Invalidation

            "There are only two hard things in computer science: cache invalidation and naming
            things." The main strategies:

            | Strategy | How | Example |
            | --- | --- | --- |
            | Clear everything | `cached_function.cache_clear()` | after a bulk import |
            | Delete on write | the code that changes the data removes the key | `del cache[key]` in `update_price` |
            | Versioned keys | put a version number in the key; bump it on change | `(product_id, catalog_version)` |
            | Expire | TTL | rates, remote config |

            Delete-on-write with an explicit dictionary cache:
            """
        ),
        code(
            '''
            price_store = {"SKU-1": 49_900, "SKU-2": 12_500}  # the "database"
            price_cache: dict[str, str] = {}


            def formatted_price(sku: str) -> str:
                """Read-through cache: compute on a miss, then remember."""
                if sku not in price_cache:
                    price_cache[sku] = f"₹{price_store[sku] / 100:,.2f}"
                return price_cache[sku]


            def update_price(sku: str, paise: int) -> None:
                """Write path: change the data AND invalidate the cached entry."""
                price_store[sku] = paise
                price_cache.pop(sku, None)


            print(formatted_price("SKU-1"))
            update_price("SKU-1", 44_900)
            print(formatted_price("SKU-1"), "(fresh after invalidation)")
            '''
        ),
        md(
            """
            Versioned keys avoid finding every key to delete: bump one counter and old entries
            simply stop being asked for (eviction cleans them up later). `lru_cache` can only be
            cleared as a whole, and `functools.cached_property` is invalidated per object with
            `del`:
            """
        ),
        code(
            '''
            catalog_version = 1


            @functools.lru_cache(maxsize=256)
            def catalog_page(page: int, version: int) -> str:
                """The version argument is part of the cache key."""
                return f"page {page} rendered for catalog v{version}"


            print(catalog_page(1, catalog_version), catalog_page.cache_info().misses, "miss")
            catalog_version += 1  # the catalog changed: new keys, old entries are never hit again
            print(catalog_page(1, catalog_version), catalog_page.cache_info().misses, "misses")
            catalog_page.cache_clear()
            print("after cache_clear:", catalog_page.cache_info())


            class Basket:
                """A basket whose total is computed once and cached."""

                def __init__(self, prices: list[int]) -> None:
                    """Store the prices."""
                    self.prices = prices

                @functools.cached_property
                def total(self) -> int:
                    """Sum the prices (computed on first access, then cached)."""
                    return sum(self.prices)


            basket = Basket([100, 250])
            print(basket.total, end=" -> ")
            basket.prices.append(50)
            print(basket.total, "(stale)", end=" -> ")
            del basket.total  # invalidate this object's cached value
            print(basket.total, "(recomputed)")
            '''
        ),
        md(
            """
            > **Warning:** `@lru_cache` on a **method** caches on `self` too, so every instance
            > that ever called it stays alive as long as the cache does (a memory leak for
            > short-lived objects). Cache on a module-level function keyed by plain values, or
            > use `cached_property` for per-object results.
            """
        ),
    ]


def _vectorization_cells() -> list[NotebookNode]:
    """5.5.9 Vectorization."""
    return [
        md(
            """
            ### 5.5.9 Vectorization

            **Vectorization** means expressing a computation as operations on whole arrays, so
            the per-element loop runs in compiled code over raw numbers instead of in the
            interpreter over objects. NumPy is the foundation; pandas and Polars build
            dataframes on the same idea.

            #### NumPy arrays

            An `ndarray` is one typed block of memory (`dtype`, `shape`, strides). Each
            operation dispatches once and then loops in C, often with SIMD instructions:
            """
        ),
        code(
            """
            if HAS_NUMPY:
                import numpy as np

                element_count = 1_000_000 * DEMO_SCALE
                amounts_list = [number % 50_000 for number in range(element_count)]
                amounts_array = np.array(amounts_list, dtype=np.int64)
                print(
                    f"dtype={amounts_array.dtype}, shape={amounts_array.shape}, nbytes={amounts_array.nbytes:,}"
                )
                list_seconds = best_seconds(lambda: sum(amount * 2 for amount in amounts_list), number=1)
                array_seconds = best_seconds(lambda: (amounts_array * 2).sum(), number=5)
                print(
                    f"sum of doubled amounts: list {list_seconds * 1000:.1f} ms, "
                    f"NumPy {array_seconds * 1000:.2f} ms -> {list_seconds / array_seconds:.0f}x"
                )
            else:
                print("NumPy is not installed: skipping.")
            """
        ),
        md(
            """
            > **Note:** the speedup only exists while data stays in arrays. Converting a list
            > to an array (`np.array(amounts_list)`) and back (`.tolist()`) costs a Python-level
            > pass each way; a NumPy scalar in a Python loop (`for x in array:`) is *slower*
            > than a plain int.

            #### Broadcasting

            Operations between arrays of different shapes follow the **broadcasting** rules:
            compare shapes from the right; two dimensions are compatible when they are equal
            or one of them is 1; size-1 dimensions are stretched (virtually, without copying).
            A column of tax rates against a row of prices gives the whole table in one
            expression:
            """
        ),
        code(
            """
            if HAS_NUMPY:
                prices_paise = np.array([9_900, 24_900, 1_29_900, 4_99_900])  # shape (4,)
                gst_percent = np.array([[5], [12], [18]])  # shape (3, 1)
                with_gst = prices_paise + prices_paise * gst_percent // 100  # shape (3, 4)
                print(f"{prices_paise.shape} with {gst_percent.shape} -> {with_gst.shape}")
                print(with_gst)
                print("incompatible shapes:", raised_error_name(lambda: np.ones(3) + np.ones(4)))
            else:
                print("NumPy is not installed: skipping.")
            """
        ),
        md(
            """
            A common use is normalizing columns: subtract each column's mean (shape `(3,)`)
            from a `(rows, 3)` matrix. No loop, and no copy of the means per row:
            """
        ),
        code(
            """
            if HAS_NUMPY:
                sales_matrix = np.random.default_rng(42).normal(
                    loc=[100, 50, 10], scale=[20, 5, 2], size=(100_000, 3)
                )
                centered = sales_matrix - sales_matrix.mean(axis=0)  # (100000, 3) - (3,)
                print("column means after centering:", np.round(centered.mean(axis=0), 10))
                print("column standard deviations:", np.round(centered.std(axis=0), 2))
            else:
                print("NumPy is not installed: skipping.")
            """
        ),
        md(
            """
            #### ufuncs

            A **ufunc** (universal function) is an element-wise operation implemented in C:
            `np.add`, `np.multiply`, `np.sqrt`, `np.maximum`, comparisons, and many more. Every
            ufunc also has methods: `reduce` (fold an axis), `accumulate` (running result),
            `outer`, and `at` (unbuffered in-place updates at indices, which handles repeated
            indices correctly: the grouping tool of the Phase 5 Project). `out=` writes into an
            existing array to avoid a temporary:
            """
        ),
        code(
            """
            if HAS_NUMPY:
                daily_sales = np.array([120, 90, 150, 80, 200, 170, 60])
                print("np.add.reduce       :", np.add.reduce(daily_sales))
                print("np.maximum.accumulate:", np.maximum.accumulate(daily_sales))
                buffer = np.empty_like(daily_sales)
                np.multiply(daily_sales, 2, out=buffer)  # no temporary array
                print("multiply with out=  :", buffer)
                store_of_sale, revenue_by_store = np.array([0, 2, 0, 1, 2, 2]), np.zeros(3, dtype=np.int64)
                np.add.at(revenue_by_store, store_of_sale, [10, 20, 30, 40, 50, 60])
                print("np.add.at grouping  :", revenue_by_store, "(repeated indices are all added)")
            else:
                print("NumPy is not installed: skipping.")
            """
        ),
        md(
            """
            Not everything that looks like a ufunc is fast: `np.vectorize` and `np.frompyfunc`
            call a Python function per element. They are conveniences, not optimizations:
            """
        ),
        code(
            """
            if HAS_NUMPY:
                small = np.arange(200_000, dtype=np.float64)
                ufunc_seconds = best_seconds(lambda: np.sqrt(small) + 1, number=20)
                vectorize_seconds = best_seconds(
                    lambda: np.vectorize(lambda value: math.sqrt(value) + 1)(small), number=1
                )
                print(
                    f"np.sqrt ufunc {ufunc_seconds * 1000:.2f} ms, "
                    f"np.vectorize(Python function) {vectorize_seconds * 1000:.1f} ms"
                )
            else:
                print("NumPy is not installed: skipping.")
            """
        ),
        md(
            """
            #### pandas vs Polars

            Both are dataframe libraries. pandas (3.x) is the long-standing standard, eager
            and NumPy/Arrow-backed. Polars is written in Rust on Apache Arrow memory, runs
            operations on several cores, and has a **lazy** API whose query optimizer can
            push filters down and drop unused columns before any work happens. The same
            group-by in each (and in plain Python for reference):
            """
        ),
        code(
            '''
            frame_rng = random.Random(42)
            frame_size = 500_000 * DEMO_SCALE
            frame_cities = [
                ("Pune", "Delhi", "Kochi", "Patna", "Surat")[frame_rng.randrange(5)] for _ in range(frame_size)
            ]
            frame_amounts = [frame_rng.randrange(100, 50_000) for _ in range(frame_size)]


            def python_group_sum() -> dict[str, int]:
                """Group-by sum in plain Python, for reference."""
                totals: dict[str, int] = {}
                for city, amount in zip(frame_cities, frame_amounts, strict=True):
                    totals[city] = totals.get(city, 0) + amount
                return dict(sorted(totals.items()))


            print(
                f"{frame_size:,} rows; plain Python: {best_seconds(python_group_sum, number=1) * 1000:.0f} ms"
            )
            '''
        ),
        md(
            "pandas and Polars, eager and lazy; each result is checked against the plain-Python one:"
        ),
        code(
            '''
            expected_totals = python_group_sum()
            if HAS_PANDAS:
                import pandas as pd

                sales_pd = pd.DataFrame({"city": frame_cities, "amount": frame_amounts})
                pandas_totals = sales_pd.groupby("city")["amount"].sum().to_dict()
                pandas_seconds = best_seconds(lambda: sales_pd.groupby("city")["amount"].sum(), number=3)
                print(
                    f"pandas {pd.__version__:<7} groupby: {pandas_seconds * 1000:6.1f} ms  "
                    f"correct: {pandas_totals == expected_totals}"
                )
            if HAS_POLARS:
                import polars as pl

                sales_pl = pl.DataFrame({"city": frame_cities, "amount": frame_amounts})

                def eager_query() -> pl.DataFrame:
                    """Polars eager group-by."""
                    return sales_pl.group_by("city").agg(pl.col("amount").sum())

                def lazy_query() -> pl.DataFrame:
                    """Polars lazy group-by, collected."""
                    return sales_pl.lazy().group_by("city").agg(pl.col("amount").sum()).collect()

                polars_totals = dict(eager_query().sort("city").iter_rows())
                polars_correct = polars_totals == expected_totals
                for label, query in (("eager", eager_query), ("lazy", lazy_query)):
                    query_ms = best_seconds(query, number=3) * 1000
                    print(
                        f"polars {pl.__version__:<7} {label:<6}: {query_ms:6.1f} ms  correct: {polars_correct}"
                    )
            if not (HAS_PANDAS or HAS_POLARS):
                print("neither pandas nor Polars is installed: skipping.")
            '''
        ),
        md(
            """
            Both dataframes beat the Python loop by a wide margin; which of the two wins
            depends on the operation, the data size and the core count (Polars uses several
            threads). The lazy plan pays off on multi-step queries, where the optimizer can
            remove work:
            """
        ),
        code(
            """
            if HAS_POLARS:
                plan = (
                    sales_pl.lazy()
                    .filter(pl.col("amount") > 40_000)
                    .group_by("city")
                    .agg(pl.len().alias("big_orders"))
                )
                print(plan.explain())
            else:
                print("Polars is not installed: skipping.")
            """
        ),
    ]


def _native_cells() -> list[NotebookNode]:
    """5.5.10 Native code."""
    return [
        md(
            """
            ### 5.5.10 Native code

            When the hot loop is still Python after the algorithm, data structures and
            vectorization are right, move that loop into compiled code. The options differ in
            how much you rewrite and what you must build:

            | Option | You write | Build step | Good for |
            | --- | --- | --- | --- |
            | `ctypes` (stdlib) | C (or use an existing `.so`/`.dll`) | a C compiler, or nothing for existing libraries | calling existing C libraries |
            | CFFI | C declarations + C | optional (ABI mode needs none) | wrapping C libraries more comfortably than ctypes |
            | Cython | Python with C type annotations (`.pyx` or pure-Python mode) | Cython + C compiler | speeding up existing Python loops, wrapping C |
            | Rust via PyO3 + maturin | Rust | Rust toolchain + maturin | new extensions with memory safety (Polars, pydantic-core, orjson are built this way) |
            | Numba | plain Python + `@njit` | none (LLVM JIT at runtime) | numeric loops over NumPy arrays |
            | mypyc | ordinary type-annotated Python | mypyc + C compiler | compiling whole typed modules (mypy and black ship compiled with it) |
            | PyPy | nothing: a different interpreter | none | pure-Python programs; C extensions run slower through its compatibility layer |

            > **Warning:** each crossing between Python and native code has a fixed cost
            > (argument conversion, a call). Move whole loops across the boundary, not one
            > operation per call.

            The running example is one function, written in Python first:
            """
        ),
        code(
            '''
            def sum_of_squares_mod(count: int) -> int:
                """Sum of (i % 1000)**2 for i in range(count): a tight integer loop."""
                total = 0
                for index in range(count):
                    remainder = index % 1000
                    total += remainder * remainder
                return total


            loop_count = 5_000_000 * DEMO_SCALE
            with Timer("pure Python", report=None) as python_timer:
                python_result = sum_of_squares_mod(loop_count)
            print(f"{python_result=}  {python_timer.elapsed_seconds * 1000:.0f} ms")
            '''
        ),
        md(
            """
            #### `ctypes`

            `ctypes` loads a shared library and calls its functions. You declare each
            function's argument and return types; nothing checks that they match the C code, so
            a wrong declaration means wrong results or a crash. The cell compiles a tiny C file
            with the system compiler first (and skips without one):
            """
        ),
        code(
            '''
            C_SOURCE = """
            #include <stdint.h>
            int64_t sum_of_squares_mod(int64_t count) {
                int64_t total = 0;
                for (int64_t index = 0; index < count; index++) {
                    int64_t remainder = index % 1000;
                    total += remainder * remainder;
                }
                return total;
            }
            double dot(const double *left, const double *right, int64_t length) {
                double total = 0.0;
                for (int64_t index = 0; index < length; index++) total += left[index] * right[index];
                return total;
            }
            """
            C_COMPILER = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
            library_suffix = {"win32": ".dll", "darwin": ".dylib"}.get(sys.platform, ".so")
            LIBRARY_PATH = PHASE5_DIR / f"libsquares{library_suffix}"
            if C_COMPILER and sys.platform != "win32":
                (PHASE5_DIR / "squares.c").write_text(C_SOURCE)
                print(
                    run_tool(C_COMPILER, "-O2", "-shared", "-fPIC", "-o", str(LIBRARY_PATH), "squares.c")
                    or f"compiled {LIBRARY_PATH.name}"
                )
            else:
                print("no C compiler found (or Windows): the ctypes and CFFI cells will skip.")
            '''
        ),
        md("Load the library, declare the signature, call it:"),
        code(
            """
            import ctypes

            if LIBRARY_PATH.exists():
                squares_library = ctypes.CDLL(str(LIBRARY_PATH))
                squares_library.sum_of_squares_mod.argtypes = [ctypes.c_int64]
                squares_library.sum_of_squares_mod.restype = ctypes.c_int64
                with Timer("ctypes", report=None) as c_timer:
                    c_result = squares_library.sum_of_squares_mod(loop_count)
                print(f"same result: {c_result == python_result}")
                print(
                    f"C via ctypes {c_timer.elapsed_seconds * 1000:.1f} ms "
                    f"vs Python {python_timer.elapsed_seconds * 1000:.0f} ms"
                    f" -> {python_timer.elapsed_seconds / c_timer.elapsed_seconds:.0f}x"
                )
            else:
                print("library not built: skipping.")
            """
        ),
        md(
            """
            Passing arrays: NumPy exposes its buffer as a C pointer, so C can read a million
            doubles without any copying. A plain call with no work shows the fixed per-call
            cost:
            """
        ),
        code(
            """
            if LIBRARY_PATH.exists() and HAS_NUMPY:
                double_pointer = ctypes.POINTER(ctypes.c_double)
                squares_library.dot.argtypes = [double_pointer, double_pointer, ctypes.c_int64]
                squares_library.dot.restype = ctypes.c_double
                left, right = np.arange(1_000_000, dtype=np.float64), np.full(1_000_000, 0.5)
                c_dot = squares_library.dot(
                    left.ctypes.data_as(double_pointer), right.ctypes.data_as(double_pointer), len(left)
                )
                print(f"dot via C: {c_dot:,.1f}   NumPy agrees: {math.isclose(c_dot, float(left @ right))}")
                per_call = best_seconds(lambda: squares_library.sum_of_squares_mod(0), number=10_000)
                print(f"one ctypes call doing no work: {per_call * 1e9:.0f} ns")
            else:
                print("library or NumPy missing: skipping.")
            """
        ),
        md(
            """
            #### CFFI

            [CFFI](https://cffi.readthedocs.io/) takes C declarations as text, so signatures
            are written once in C syntax. *ABI mode* (`ffi.dlopen`) loads an existing library
            like `ctypes`; *API mode* compiles a real extension module and is faster and safer.
            CFFI is not a course dependency (it is often present because other packages depend
            on it), so the cell checks first:
            """
        ),
        code(
            """
            if has_module("cffi") and LIBRARY_PATH.exists():
                import cffi

                ffi = cffi.FFI()
                ffi.cdef("int64_t sum_of_squares_mod(int64_t count);")
                cffi_library = ffi.dlopen(str(LIBRARY_PATH))
                print(
                    f"cffi {cffi.__version__}: result matches: "
                    f"{cffi_library.sum_of_squares_mod(loop_count) == python_result}"
                )
            else:
                print(
                    "cffi is not installed (or the library was not built): skipping. `uv add cffi` to try it."
                )
            """
        ),
        md(
            """
            #### Cython

            Cython compiles a superset of Python to C. Adding C types to the hot variables
            removes the object boxing in the loop; in *pure-Python mode* the annotations are
            ordinary Python, so the same file still runs uncompiled:

            ```python
            # squares_cy.py, compiled with `cythonize -i squares_cy.py`
            import cython

            def sum_of_squares_mod(count: cython.longlong) -> cython.longlong:
                total: cython.longlong = 0
                index: cython.longlong
                for index in range(count):
                    remainder: cython.longlong = index % 1000
                    total += remainder * remainder
                return total
            ```
            """
        ),
        code(
            """
            if has_module("Cython"):
                import Cython

                print(
                    f"Cython {Cython.__version__} is installed: "
                    "build with `cythonize -i squares_cy.py` (needs a C compiler)."
                )
            else:
                print("Cython is not installed: skipping the build (`uv add --dev cython` to try it).")
            """
        ),
        md(
            """
            #### Rust via PyO3 and maturin

            PyO3 provides Rust bindings for the CPython API; maturin builds and packages the
            result as a wheel. `maturin new --bindings pyo3 squares` creates the project, and
            `maturin develop` builds it into the active environment:

            ```rust
            use pyo3::prelude::*;

            #[pyfunction]
            fn sum_of_squares_mod(count: i64) -> i64 {
                (0..count).map(|index| { let r = index % 1000; r * r }).sum()
            }

            #[pymodule]
            fn squares(module: &Bound<'_, PyModule>) -> PyResult<()> {
                module.add_function(wrap_pyfunction!(sum_of_squares_mod, module)?)
            }
            ```
            """
        ),
        code(
            """
            rust_tools = {name: shutil.which(name) for name in ("cargo", "rustc", "maturin")}
            if all(rust_tools.values()):
                print("Rust toolchain and maturin found:", ", ".join(rust_tools))
                print(
                    "build with: maturin new --bindings pyo3 squares && cd squares && maturin develop --release"
                )
            else:
                missing = [name for name, path in rust_tools.items() if path is None]
                print(
                    f"not available here ({', '.join(missing)} missing): skipping. "
                    "Install Rust from rustup.rs and `uv tool install maturin`."
                )
            """
        ),
        md(
            """
            #### Numba

            Numba compiles a Python function to machine code with LLVM the first time it is
            called with given argument types. It understands a numeric subset of Python and
            NumPy; other code falls back or fails to compile:

            ```python
            from numba import njit

            @njit(cache=True)
            def sum_of_squares_mod(count):
                total = 0
                for index in range(count):
                    remainder = index % 1000
                    total += remainder * remainder
                return total
            ```

            Numba releases usually trail new CPython versions by some months.
            """
        ),
        code(
            """
            if has_module("numba"):
                import numba

                print(
                    f"Numba {numba.__version__} is installed: decorate the function with @numba.njit "
                    "and call it twice (compile, then run)."
                )
            else:
                print(
                    f"Numba is not installed (no build for Python {platform.python_version()} "
                    "in this environment): skipping."
                )
            """
        ),
        md(
            """
            #### mypyc

            mypyc ships with mypy (installed in Phase 4). It compiles ordinary, fully
            type-annotated modules to C extensions: the annotations you already wrote for
            `mypy --strict` become the C types. The command is `mypyc module.py`, which needs a
            C compiler and `setuptools` to build the extension:
            """
        ),
        code(
            """
            mypyc_requirements = {
                "mypyc": has_module("mypyc"),
                "setuptools": has_module("setuptools"),
                "C compiler": C_COMPILER is not None,
            }
            print(
                ", ".join(f"{name}: {'yes' if found else 'no'}" for name, found in mypyc_requirements.items())
            )
            if all(mypyc_requirements.values()):
                print(
                    "ready: `uv run mypyc notebooks/_scratch/phase5/profile_target.py` "
                    "would compile the 5.5.3 script."
                )
            else:
                print(
                    "cannot build with mypyc here: skipping "
                    "(mypyc builds through setuptools; `uv add --dev setuptools`)."
                )
            """
        ),
        md(
            """
            #### PyPy

            PyPy is an alternative Python implementation with a **tracing JIT**: it records the
            hot loops of a running program and compiles them, so unchanged pure-Python code
            often runs several times faster, like a JavaScript engine. The costs: it trails
            CPython's language version, C extensions go through a slower compatibility layer,
            and its garbage collector does not free objects immediately (always close files
            with `with`).
            """
        ),
        code(
            """
            pypy = shutil.which("pypy3") or shutil.which("pypy")
            if pypy:
                print(
                    run_tool(
                        pypy,
                        "-c",
                        "import sys, platform; print(platform.python_implementation(), sys.version.split()[0])",
                    )
                )
            else:
                print("PyPy is not installed: skipping (`uv python install pypy` provides one).")
            """
        ),
    ]


def _free_threading_jit_cells() -> list[NotebookNode]:
    """5.5.11 Free-threading and JIT effects."""
    return [
        md(
            """
            ### 5.5.11 Free-threading and JIT effects

            Two CPython features change performance without changing your code:

            - the **free-threaded build** (`python3.15t`, PEP 703/779; Units 3.1 and 5.1)
              removes the GIL, so CPU-bound threads run in parallel, at the price of somewhat
              slower single-threaded code (per-object locking, biased reference counting);
            - the **experimental JIT** (PEP 744, 3.13+) is built into the default 3.15 build
              here but off unless `PYTHON_JIT=1` is set; it compiles hot traces of
              specialized bytecode into machine code with a "copy-and-patch" technique.

            The only honest way to know what they do for *your* code is to run the same
            benchmark on each. The benchmark script runs a pure-Python CPU loop once on one
            thread, then four copies of it on four threads:
            """
        ),
        code(
            '''
            %%writefile _scratch/phase5/p5_build_benchmark.py
            """CPU loop on 1 thread, then 4 threads x the same work; prints one JSON line."""

            import json
            import os
            import sys
            import sysconfig
            import threading
            import time
            from collections.abc import Callable

            LOOPS = 2_000_000 * int(os.environ.get("PHASE5_DEMO_SCALE", "1"))


            def busy(loops: int) -> int:
                """The CPU-bound work: a pure-Python arithmetic loop."""
                total = 0
                for index in range(loops):
                    total += (index % 7) * (index % 11)
                return total


            def best_of(runs: int, work: Callable[[], object]) -> float:
                """Fastest wall time of work() over runs attempts."""
                timings = []
                for _ in range(runs):
                    start = time.perf_counter()
                    work()
                    timings.append(time.perf_counter() - start)
                return min(timings)
            '''
        ),
        md(
            """
            The second half (appended to the same file) starts four threads on the same
            loop and prints one JSON line with the build's flags and both timings:
            """
        ),
        code(
            '''
            %%writefile -a _scratch/phase5/p5_build_benchmark.py


            def four_threads() -> None:
                """Run busy(LOOPS) on four threads at once and wait for all of them."""
                threads = [threading.Thread(target=busy, args=(LOOPS,)) for _ in range(4)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()


            jit = getattr(sys, "_jit", None)
            print(json.dumps({
                "gil_disabled": bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
                "jit_enabled": bool(jit and jit.is_enabled()),
                "one_thread": best_of(3, lambda: busy(LOOPS)),
                "four_threads": best_of(2, four_threads),
            }))
            '''
        ),
        md(
            """
            Run it on the default build with the JIT off and on, and on the free-threaded build
            (when installed). `PYTHON_JIT=1` only has an effect on builds that include the JIT:
            """
        ),
        code(
            """
            build_runs = [
                ("default build, JIT off", sys.executable, {"PYTHON_JIT": "0"}),
                ("default build, PYTHON_JIT=1", sys.executable, {"PYTHON_JIT": "1"}),
            ]
            if FREE_THREADED_PYTHON:
                build_runs += [
                    ("free-threaded 3.15t", FREE_THREADED_PYTHON, {"PYTHON_JIT": "0"}),
                    ("free-threaded, PYTHON_JIT=1", FREE_THREADED_PYTHON, {"PYTHON_JIT": "1"}),
                ]
            else:
                print("no free-threaded interpreter found: only the default build is measured.")
            build_results = {}
            for label, python, extra_env in build_runs:
                output = run_tool(python, "p5_build_benchmark.py", extra_env=extra_env, timeout=300)
                build_results[label] = json.loads(output.splitlines()[-1])
            baseline_one = build_results["default build, JIT off"]["one_thread"]
            print(
                f"{'build':<28} {'JIT on?':>7} {'1 thread':>9} "
                f"{'4 threads':>10} {'4T/1T':>6} {'1T vs baseline':>15}"
            )
            for label, result in build_results.items():
                ratio = result["four_threads"] / result["one_thread"]
                print(
                    f"{label:<28} {result['jit_enabled']!s:>7} {result['one_thread']:8.3f}s "
                    f"{result['four_threads']:9.3f}s {ratio:6.2f} {result['one_thread'] / baseline_one:14.2f}x"
                )
            """
        ),
        md(
            """
            How to read the table (your numbers will differ):

            - **4T/1T** is the wall time of four threads' worth of work divided by one
              thread's. On the GIL build it is about 4 (or worse): the threads take turns. On
              the free-threaded build it is close to 1: the four threads really run at once.
            - **1T vs baseline** compares single-thread speed with the default build, JIT off.
              The free-threaded build is usually a little slower on one thread. The JIT is
              usually a few percent faster on loops like this, sometimes no faster, and it
              cannot help code that spends its time in C functions or waiting on I/O.
            - "JIT on?" is what `sys._jit.is_enabled()` reported inside the child: a build
              without the JIT ignores `PYTHON_JIT=1` (here the free-threaded build).

            The decision rule from Unit 5.2 still holds: measure *your* workload on each build
            before switching, and check that your C extensions support the free-threaded build
            (Unit 5.1.10).
            """
        ),
    ]


def _production_cells() -> list[NotebookNode]:
    """5.5.12 Production performance."""
    return [
        md(
            """
            ### 5.5.12 Production performance

            Benchmarks on a laptop find most problems; some only appear under real traffic,
            real data and real concurrency. Three practices cover production:

            1. **Sampling a live process** when something is slow right now;
            2. **Continuous profiling**: sample all the time at a low rate, store the results,
               compare deploys;
            3. **Benchmarks in CI**, so a regression fails a build instead of reaching users.

            #### Sampling in production

            Sampling profilers attach from outside, need no code changes and add little
            overhead, so they are safe on a production process. The "server" below is a child
            process that keeps doing work; the cells attach to it with py-spy and Tachyon.
            (Attaching needs `ptrace` permission on Linux: `kernel.yama.ptrace_scope` 0, the
            same user and capabilities, or `sudo`; in containers, `SYS_PTRACE`.)
            """
        ),
        code(
            '''
            %%writefile _scratch/phase5/fake_server.py
            """A stand-in for a production process: handles 'requests' until killed."""

            import time

            import profile_target

            CUSTOMERS = profile_target.make_customers(2_500)


            def handle_request(request_number: int) -> dict[str, int]:
                """Handle one fake request: build orders and total them."""
                orders = profile_target.make_orders(500, CUSTOMERS)
                return profile_target.city_totals(orders, CUSTOMERS)


            def serve_forever() -> None:
                """Handle requests forever, pausing 1 ms between them."""
                request_number = 0
                while True:
                    handle_request(request_number)
                    request_number += 1
                    time.sleep(0.001)  # waiting for the next request


            if __name__ == "__main__":
                serve_forever()
            '''
        ),
        md("Start it in the background and take one snapshot of its stacks with `py-spy dump`:"),
        code(
            """
            server = subprocess.Popen(
                [sys.executable, "fake_server.py"],
                cwd=PHASE5_DIR,
                env=CHILD_ENV,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(1.0)  # let it start
            print(f"server running: {server.poll() is None}")
            if PY_SPY:
                dump = run_tool(PY_SPY, "dump", "--pid", str(server.pid))
                print(re.sub(r"\\d{3,}", "<n>", "\\n".join(dump.splitlines()[2:])) if "Thread" in dump else dump)
            else:
                print("py-spy is not installed: skipping the dump.")
            """
        ),
        md(
            """
            One dump is a single sample, but it is often enough: a process that is "stuck"
            shows the line it is stuck on. `py-spy record --pid PID --duration 10` and
            `py-spy top --pid PID` sample over time. Tachyon does the same with `attach`
            (*New in 3.15*), here for one second. In its header, *Error rate* is the share of
            samples it failed to take (for example, a stack read while the process was
            changing it), not a failure of the program being profiled:
            """
        ),
        code(
            """
            if HAS_TACHYON and server.poll() is None:
                attach_output = run_tool(
                    sys.executable,
                    "-m",
                    "profiling.sampling",
                    "attach",
                    "-d",
                    "1",
                    "--sort",
                    "tottime",
                    "-l",
                    "5",
                    "--no-summary",
                    str(server.pid),
                )
                print(re.sub(r"\\b\\d{4,}\\b", "<pid>", attach_output))
            else:
                print("Tachyon needs Python 3.15+ (or the server is not running): skipping.")
            server.terminate()
            server.wait(timeout=10)
            print(f"server stopped, exit code {server.returncode}")
            """
        ),
        md(
            """
            Both point at `find_city`, from a process that was not started under a profiler and
            was never restarted. That is the production workflow: notice latency in metrics,
            attach, find the line, fix it, deploy, and confirm in the metrics.

            #### Continuous profiling

            A **continuous profiler** samples every instance of a service all the time at a
            low rate (for example 100 Hz, well under 1 % overhead), ships aggregated stacks to
            a backend, and lets you view flame graphs per service, version and time range or
            diff two deploys. Examples: Grafana Pyroscope, Datadog, Elastic, Google Cloud
            Profiler, Parca (eBPF-based, needs no agent in the process). The principle fits in
            a few lines: a background thread reads the main thread's current frame with
            `sys._current_frames()` and counts function names. The demo runs in a child:
            """
        ),
        code(
            '''
            print(
                run_child(
                    """
                    import collections
                    import sys
                    import threading
                    import time

                    import profile_target

                    samples = collections.Counter()
                    main_thread_id = threading.main_thread().ident

                    def sampler(stop: threading.Event, interval: float = 0.005) -> None:
                        while not stop.wait(interval):
                            frame = sys._current_frames().get(main_thread_id)
                            if frame is not None:
                                samples[frame.f_code.co_qualname] += 1

                    stop = threading.Event()
                    threading.Thread(target=sampler, args=(stop,), daemon=True).start()
                    profile_target.main()
                    stop.set()
                    total = sum(samples.values())
                    for name, count in samples.most_common(4):
                        print(f"{name:<22} {count / total:6.1%} of {total} samples")
                    """
                )
            )
            '''
        ),
        md(
            """
            This sampler counts wall time (it records the main thread's frame whatever it is
            doing), so the sleeping `fetch_exchange_rate` leads, and it gets fewer samples than
            requested because the sampling thread itself needs the GIL to run. Real continuous
            profilers sample from outside the interpreter (like py-spy) or with
            eBPF, record whole stacks rather than the top frame, and aggregate per minute; the
            idea is the same. *New in 3.14*: `sys.remote_exec()` (PEP 768) lets a debugger or
            profiler run code inside a live process safely, which is what Tachyon and pdb's
            `-p PID` build on.

            #### `pytest-benchmark` in CI

            [`pytest-benchmark`](https://pytest-benchmark.readthedocs.io/) adds a `benchmark`
            fixture that calibrates, repeats and records timings, saves them as JSON, and can
            **fail the test run** when a function got slower than a saved baseline:

            ```python
            # tests/test_performance.py
            def test_city_totals_speed(benchmark):
                result = benchmark(city_totals_dict, ORDERS, CUSTOMERS)
                assert result == EXPECTED
            ```

            ```yaml
            # .github/workflows/bench.yml (one job)
            - run: uv run pytest tests/test_performance.py --benchmark-autosave
            - run: uv run pytest tests/test_performance.py --benchmark-compare --benchmark-compare-fail=mean:15%
            ```

            Shared CI runners are noisy, so use generous thresholds (or a dedicated runner),
            compare against a baseline measured on the same runner type, and prefer comparing
            the *ratio* of two implementations over absolute times. pytest-benchmark is not a
            course dependency; the cell checks first:
            """
        ),
        code(
            """
            if HAS_PYTEST_BENCHMARK:
                print(
                    "pytest-benchmark is installed: run `uv run pytest --benchmark-only` "
                    "on a test using the `benchmark` fixture."
                )
            else:
                print("pytest-benchmark is not installed: skipping its run (`uv add --dev pytest-benchmark`).")
            """
        ),
        md(
            """
            Without the plugin, plain pytest can still guard performance in a robust way:
            compare the optimized function against the slow one **in the same run** and require
            a large margin. Machine speed cancels out of the ratio. The test module is written
            to the scratch folder and pytest runs it in a child process:
            """
        ),
        code(
            '''
            %%writefile _scratch/phase5/perf_tests/test_city_totals_perf.py
            """A CI-friendly performance guard: a ratio in the same run, not an absolute time."""

            import timeit

            import profile_target

            CUSTOMERS = profile_target.make_customers(2_500)
            ORDERS = profile_target.make_orders(4_000, CUSTOMERS)


            def city_totals_dict(orders: list[tuple[int, int]], customers: list[tuple[int, str]]) -> dict[str, int]:
                """The dict-based fix from 5.5.5."""
                city_of = dict(customers)
                totals: dict[str, int] = {}
                for customer_id, amount in orders:
                    totals[city_of[customer_id]] = totals.get(city_of[customer_id], 0) + amount
                return totals


            def test_same_result() -> None:
                """The dict version gives the same totals."""
                assert city_totals_dict(ORDERS, CUSTOMERS) == profile_target.city_totals(ORDERS, CUSTOMERS)


            def test_dict_version_is_much_faster() -> None:
                """The dict version is far faster, measured in the same run."""
                slow = min(timeit.repeat(lambda: profile_target.city_totals(ORDERS, CUSTOMERS), number=1, repeat=3))
                fast = min(timeit.repeat(lambda: city_totals_dict(ORDERS, CUSTOMERS), number=1, repeat=3))
                print(f"ratio {slow / fast:.0f}x")
                assert slow / fast > 10  # the real gap is far larger; the margin absorbs CI noise
            '''
        ),
        md("Run it with pytest (`-s` shows the printed ratio):"),
        code(
            """
            pytest_output = run_tool(
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-s",
                "-p",
                "no:cacheprovider",
                "perf_tests",
                extra_env={"PY_COLORS": "0"},
            )
            print("\\n".join(line for line in pytest_output.splitlines() if line.strip()))
            """
        ),
    ]


def _predict_cells() -> list[NotebookNode]:
    """Predict-the-output questions for Unit 5.5."""
    return [
        md("#### Predict the output"),
        *predict_cells(
            """
            from functools import lru_cache

            @lru_cache(maxsize=2)
            def square(n):
                return n * n

            for n in [1, 2, 1, 3, 2, 1]:
                square(n)
            print(square.cache_info())
            """,
            """
            `CacheInfo(hits=1, misses=5, maxsize=2, currsize=2)`. Trace the cache (most recent
            last): 1 miss `[1]`; 2 miss `[1, 2]`; 1 **hit** `[2, 1]`; 3 miss, evicts 2 → `[1, 3]`;
            2 miss, evicts 1 → `[3, 2]`; 1 miss, evicts 3 → `[2, 1]`. A cache smaller than the
            working set mostly misses.
            """,
            '''
            @functools.lru_cache(maxsize=2)
            def square(number: int) -> int:
                """Square a number (cached)."""
                return number * number


            for number in [1, 2, 1, 3, 2, 1]:
                square(number)
            print(square.cache_info())
            ''',
        ),
        *predict_cells(
            """
            import tracemalloc

            tracemalloc.start()
            data = [0] * 1_000_000
            del data
            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            print(current < 100_000, peak > 7_000_000)
            """,
            """
            `True True`. The list held a million 8-byte pointers (about 8 MB, all pointing at
            the same cached `0`). After `del`, *current* is back near zero, but *peak* remembers
            the high-water mark. Peak is what the machine had to provide.
            """,
            """
            tracemalloc.start()
            data = [0] * 1_000_000
            del data
            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            print(current < 100_000, peak > 7_000_000)
            """,
        ),
        *predict_cells(
            """
            import numpy as np

            rates = np.array([[5], [12], [18]])
            prices = np.arange(4)
            print((rates * prices).shape)
            print(np.ones(3) + np.ones(4))
            """,
            """
            `(3, 4)`, then a `ValueError` ("operands could not be broadcast together with
            shapes (3,) (4,)"). Shapes are compared from the right: `(3, 1)` with `(4,)` works
            because the 1 stretches to 4 and the missing dimension counts as 1. `(3,)` with
            `(4,)` has two different sizes, neither of them 1.
            """,
            """
            if HAS_NUMPY:
                rates = np.array([[5], [12], [18]])
                prices = np.arange(4)
                print((rates * prices).shape)
                try:
                    print(np.ones(3) + np.ones(4))
                except ValueError as error:
                    print(f"{type(error).__name__}: {error}")
            else:
                print("NumPy is not installed: skipping.")
            """,
        ),
    ]


LAB_SETUP_SOURCE = r'''
LAB55_DIR = PHASE5_DIR / "lab55"
LAB55_DIR.mkdir(exist_ok=True)
LAB55_CITIES = ("Pune", "Delhi", "Kochi", "Patna", "Surat", "Indore")
LAB55_EVENT_TYPES = ("view", "click", "add_to_cart", "purchase")
if HAS_NUMPY:
    import numpy as np


def make_lab_customers(count: int = 1_200, seed: int = 55) -> list[tuple[int, str, str]]:
    """(customer_id, name, city) with shuffled, spread-out ids."""
    rng = random.Random(seed)
    customer_ids = rng.sample(range(10_000, 99_999), count)
    return [
        (customer_id, f"Customer {position}", LAB55_CITIES[position % 6])
        for position, customer_id in enumerate(customer_ids)
    ]


def make_lab_orders(
    customers: list[tuple[int, str, str]], count: int, seed: int = 56
) -> list[tuple[int, int, int]]:
    """(order_id, customer_id, amount_paise) rows."""
    rng = random.Random(seed)
    return [
        (order_id, rng.choice(customers)[0], rng.randrange(1_000, 500_000))
        for order_id in range(count)
    ]


print("Lab 5.5 generators ready: make_lab_customers, make_lab_orders")
'''

LAB_DATA_SOURCE = r'''
def write_events(path: Path, count: int, seed: int = 57) -> Path:
    """Write a seeded CSV event log: timestamp,user_id,event,bytes."""
    rng = random.Random(seed)
    with path.open("w", encoding="utf-8") as handle:
        handle.write("timestamp,user_id,event,bytes\n")
        for second in range(count):
            event = rng.choice(LAB55_EVENT_TYPES)
            user_id, size = rng.randrange(3_000), rng.randrange(200, 90_000)
            handle.write(f"{1_767_225_600 + second},{user_id},{event},{size}\n")
    return path


def prepare_lab_5_5() -> tuple[list[tuple[int, str, str]], list[tuple[int, int, int]], Path]:
    """Create the lab data: customers, orders and the event-log file."""
    customers = make_lab_customers()
    orders = make_lab_orders(customers, 4_000 * DEMO_SCALE)
    events = write_events(LAB55_DIR / "events.csv", 60_000 * DEMO_SCALE)
    return customers, orders, events


def best_time_or_none(work: Callable[[], object], repeat: int = 3) -> float | None:
    """Best of `repeat` single runs in seconds, or None if work raises (an unfinished stub)."""
    try:
        return min(timeit.repeat(work, number=1, repeat=repeat))
    except Exception:
        return None


LAB55_CUSTOMERS, LAB55_ORDERS, LAB55_EVENTS = prepare_lab_5_5()
print(f"{len(LAB55_CUSTOMERS):,} customers, {len(LAB55_ORDERS):,} orders")
print(f"events file: {LAB55_EVENTS.stat().st_size:,} bytes")
'''

LAB_GIVEN_SLOW_SOURCE = r'''
def lookup_customer(
    customers: list[tuple[int, str, str]], customer_id: int
) -> tuple[int, str, str]:
    """Find a customer by id with a linear scan."""
    for customer in customers:
        if customer[0] == customer_id:
            return customer
    raise KeyError(customer_id)


def city_totals_slow(
    orders: list[tuple[int, int, int]], customers: list[tuple[int, str, str]]
) -> dict[str, int]:
    """Revenue (paise) per customer city, sorted by city name. Correct, but slow."""
    totals: dict[str, int] = {}
    for _order_id, customer_id, amount in orders:
        city = lookup_customer(customers, customer_id)[2]
        totals[city] = totals.get(city, 0) + amount
    return dict(sorted(totals.items()))
'''


def _lab_cells_part_1() -> list[NotebookNode]:
    """Lab 5.5 setup and exercises 1-2."""
    return [
        md(
            """
            ### Lab 5.5

            Five exercises. Replace each `raise NotImplementedError`, then run the check cell;
            until then the checks print FAIL, which is expected. Checks that involve speed use
            a large margin against a much larger real gap and print the measured ratio; memory
            checks are exact properties of the code, not of the machine.

            The first setup cell defines the seeded customer and order generators:
            """
        ),
        code(LAB_SETUP_SOURCE),
        md(
            """
            The second writes the event log for exercise 5, creates the lab data under
            `notebooks/_scratch/phase5/lab55/`, and defines `best_time_or_none` (a timing that
            returns `None` instead of raising while a stub is unfinished):
            """
        ),
        code(LAB_DATA_SOURCE),
        md(
            """
            #### Exercise 1 — Profile and fix a slow function

            `city_totals_slow` (given below) is correct but slow. First find out *why* with a
            profiler, then fix it.

            1. Write `hottest_function(function, *args)`: profile one call
               `function(*args)` with `cProfile` and return the **name** of the function with
               the largest **own time** (`tottime`). For a Python function that is its plain
               name (`"lookup_customer"`); for a built-in it is the label pstats uses, such as
               `"<built-in method builtins.sorted>"`. (`pstats.Stats(profiler).stats` maps
               `(file, line, name)` to `(primitive calls, calls, tottime, cumtime, callers)`.)
            2. Write `city_totals_fast(orders, customers)`, returning exactly what
               `city_totals_slow` returns, much faster.
            """
        ),
        code(LAB_GIVEN_SLOW_SOURCE),
        md("Your solution, part 1:"),
        code(
            '''
            def hottest_function(function: Callable[..., object], *args: object) -> str:
                """Profile function(*args) once; return the name of the entry with the largest tottime."""
                raise NotImplementedError
            '''
        ),
        md("Your solution, part 2:"),
        code(
            '''
            def city_totals_fast(
                orders: list[tuple[int, int, int]], customers: list[tuple[int, str, str]]
            ) -> dict[str, int]:
                """Same result as city_totals_slow, without a scan per order."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 1:"),
        code(
            """
            slow_totals = city_totals_slow(LAB55_ORDERS, LAB55_CUSTOMERS)
            slow_seconds = best_time_or_none(lambda: city_totals_slow(LAB55_ORDERS, LAB55_CUSTOMERS))
            fast_seconds = best_time_or_none(lambda: city_totals_fast(LAB55_ORDERS, LAB55_CUSTOMERS))
            run_checks(
                [
                    (
                        "profile finds the hot spot",
                        lambda: hottest_function(city_totals_slow, LAB55_ORDERS, LAB55_CUSTOMERS),
                        "lookup_customer",
                    ),
                    (
                        "built-ins are reported too",
                        lambda: "sorted" in hottest_function(sorted, list(range(200_000, 0, -1))),
                        True,
                    ),
                    (
                        "fast version: same totals",
                        lambda: city_totals_fast(LAB55_ORDERS, LAB55_CUSTOMERS),
                        slow_totals,
                    ),
                    (
                        "fast version: no longer dominated by lookup_customer",
                        lambda: (
                            hottest_function(city_totals_fast, LAB55_ORDERS, LAB55_CUSTOMERS)
                            != "lookup_customer"
                        ),
                        True,
                    ),
                    (
                        "fast version: at least 5x faster",
                        lambda: fast_seconds is not None and slow_seconds / fast_seconds >= 5,
                        True,
                    ),
                ]
            )
            if fast_seconds:
                print(
                    f"measured: slow {slow_seconds * 1000:.1f} ms, fast {fast_seconds * 1000:.2f} ms "
                    f"-> {slow_seconds / fast_seconds:.0f}x"
                )
            """
        ),
        md(
            """
            #### Exercise 2 — Rewrite an O(n²) algorithm as O(n)

            `count_pairs_quadratic(amounts, target)` counts the index pairs `i < j` with
            `amounts[i] + amounts[j] == target` by trying every pair. Write
            `count_pairs_linear(amounts, target)` with the same results in **one pass**.
            (Hint: when you reach an amount, how many earlier amounts complete it?)
            """
        ),
        code(
            '''
            def count_pairs_quadratic(amounts: list[int], target: int) -> int:
                """Pairs i < j with amounts[i] + amounts[j] == target, by brute force: O(n^2)."""
                pair_count = 0
                for first in range(len(amounts)):
                    for second in range(first + 1, len(amounts)):
                        if amounts[first] + amounts[second] == target:
                            pair_count += 1
                return pair_count


            def growth_factor(count_pairs: Callable[[list[int], int], int], size: int) -> float | None:
                """Best time at 4 x size divided by best time at size (about 4 for O(n), 16 for O(n^2))."""
                rng = random.Random(58)
                small, large = (
                    [rng.randrange(1_000) for _ in range(list_size)] for list_size in (size, 4 * size)
                )
                small_time = best_time_or_none(lambda: count_pairs(small, 1_000))
                large_time = best_time_or_none(lambda: count_pairs(large, 1_000))
                return None if small_time is None or large_time is None else large_time / small_time
            '''
        ),
        md("Your solution:"),
        code(
            '''
            def count_pairs_linear(amounts: list[int], target: int) -> int:
                """Same result as count_pairs_quadratic, in O(n)."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 2:"),
        code(
            """
            pair_cases = [
                ([], 10),
                ([5], 10),
                ([5, 5, 5], 10),
                ([1, 9, 2, 8, 5, 5], 10),
                ([-3, 13, 0, 10, 10], 10),
                ([4, 4, 4, 4], 8),
            ]
            pair_rng = random.Random(59)
            random_amounts = [pair_rng.randrange(-50, 150) for _ in range(1_500)]
            linear_growth = growth_factor(count_pairs_linear, 50_000 * DEMO_SCALE)
            run_checks(
                [
                    *(
                        (
                            f"pairs in {amounts} summing to {target}",
                            lambda amounts=amounts, target=target: count_pairs_linear(amounts, target),
                            count_pairs_quadratic(amounts, target),
                        )
                        for amounts, target in pair_cases
                    ),
                    (
                        "1 500 random amounts",
                        lambda: count_pairs_linear(random_amounts, 100),
                        count_pairs_quadratic(random_amounts, 100),
                    ),
                    (
                        "4x the input takes less than 8x the time",
                        lambda: linear_growth is not None and linear_growth < 8,
                        True,
                    ),
                ]
            )
            if linear_growth:
                print(f"measured growth for 4x the input: x{linear_growth:.1f} (O(n) ~ 4, O(n^2) ~ 16)")
            """
        ),
    ]


def _lab_cells_part_2() -> list[NotebookNode]:
    """Lab 5.5 exercises 3-5."""
    return [
        md(
            """
            #### Exercise 3 — A micro-optimization timing table

            1. Write `timing_table(candidates, number=1000, repeat=5)`: `candidates` maps a
               label to a zero-argument callable. Time each with `timeit.repeat` and return a
               list of `(label, best seconds per call)` sorted **fastest first**.
            2. Write `render_timing_table(rows)`, which turns such a list into a Markdown
               table, times in microseconds with two decimals and a thousands separator,
               relative to the fastest row (the first one) with two decimals:

            ```text
            | Variant | Time per call | Relative |
            | --- | ---: | ---: |
            | join | 12.34 µs | 1.00x |
            | plus | 24.68 µs | 2.00x |
            ```

            No trailing newline; an empty list gives just the two header lines.
            """
        ),
        md("Your solution, part 1:"),
        code(
            '''
            def timing_table(
                candidates: dict[str, Callable[[], object]], number: int = 1000, repeat: int = 5
            ) -> list[tuple[str, float]]:
                """(label, best seconds per call) for every candidate, fastest first."""
                raise NotImplementedError
            '''
        ),
        md("Your solution, part 2:"),
        code(
            '''
            def render_timing_table(rows: list[tuple[str, float]]) -> str:
                """Markdown table: variant, time per call in µs, ratio to the fastest row."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 3:"),
        code(
            """
            expected_table = (
                "| Variant | Time per call | Relative |\\n| --- | ---: | ---: |\\n"
                "| join | 12.34 µs | 1.00x |\\n| plus | 24.68 µs | 2.00x |"
            )
            run_checks(
                [
                    (
                        "render two rows",
                        lambda: render_timing_table([("join", 12.34e-6), ("plus", 24.68e-6)]),
                        expected_table,
                    ),
                    (
                        "render no rows",
                        lambda: render_timing_table([]),
                        "| Variant | Time per call | Relative |\\n| --- | ---: | ---: |",
                    ),
                    (
                        "render a slow row",
                        lambda: render_timing_table([("a", 0.5e-6), ("b", 1.5e-3)]).splitlines()[-1],
                        "| b | 1,500.00 µs | 3000.00x |",
                    ),
                ]
            )
            """
        ),
        md(
            """
            The `timing_table` checks: rows sorted fastest first, and times reported per call
            (a 2 ms sleep must come out between 2 ms and 200 ms, not ×3 for `number=3`; the
            upper bound is generous so a busy machine cannot fail it):
            """
        ),
        code(
            """
            run_checks(
                [
                    (
                        "sorted fastest first",
                        lambda: [
                            label
                            for label, _ in timing_table(
                                {"sleep": lambda: time.sleep(0.002), "noop": lambda: None}, number=3, repeat=2
                            )
                        ],
                        ["noop", "sleep"],
                    ),
                    (
                        "seconds per call, not per batch",
                        lambda: (
                            0.002
                            <= timing_table({"sleep": lambda: time.sleep(0.002)}, number=3, repeat=2)[0][1]
                            < 0.2
                        ),
                        True,
                    ),
                ]
            )
            """
        ),
        md(
            "Once it passes, your functions produce a real table for four ways to build a CSV line:"
        ),
        code(
            '''
            csv_fields = [str(column_number) for column_number in range(30)]


            def csv_line_plus() -> str:
                """Build the CSV line with += (the slow variant)."""
                line = ""
                for csv_field in csv_fields:
                    line += csv_field + ","
                return line[:-1]


            csv_candidates = {
                "str += in a loop": csv_line_plus,
                '",".join(fields)': lambda: ",".join(csv_fields),
                "join of a generator": lambda: ",".join(field for field in csv_fields),
                "str.format with unpacking": lambda: ("{}," * len(csv_fields))[:-1].format(*csv_fields),
            }
            try:
                print(render_timing_table(timing_table(csv_candidates, number=2_000)))
            except NotImplementedError:
                print("finish exercise 3 to see the table")
            '''
        ),
        md(
            """
            #### Exercise 4 — NumPy vectorization

            Vectorize the two loops below. `revenue_by_store_numpy(store_ids, amounts,
            store_count)` takes NumPy integer arrays and returns an `int64` array of length
            `store_count` (stores without sales get 0; money stays exact). `zscores_numpy(values)`
            returns `(value - mean) / standard deviation` (population standard deviation) for a
            float array. No Python loops.
            """
        ),
        code(
            '''
            def revenue_by_store_loop(store_ids: list[int], amounts: list[int], store_count: int) -> list[int]:
                """Total amount per store id (0..store_count-1), with a Python loop."""
                totals = [0] * store_count
                for store_id, amount in zip(store_ids, amounts, strict=True):
                    totals[store_id] += amount
                return totals


            def zscores_loop(values: list[float]) -> list[float]:
                """Standard scores with the population standard deviation, with Python loops."""
                mean = sum(values) / len(values)
                spread = (sum((value - mean) ** 2 for value in values) / len(values)) ** 0.5
                return [(value - mean) / spread for value in values]
            '''
        ),
        md("Your solution, part 1:"),
        code(
            '''
            def revenue_by_store_numpy(
                store_ids: np.ndarray, amounts: np.ndarray, store_count: int
            ) -> np.ndarray:
                """Vectorized revenue_by_store_loop: an int64 array of length store_count."""
                raise NotImplementedError
            '''
        ),
        md("Your solution, part 2:"),
        code(
            '''
            def zscores_numpy(values: np.ndarray) -> np.ndarray:
                """Vectorized zscores_loop."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 4:"),
        code(
            """
            vector_rng = random.Random(60)
            sale_count = 200_000 * DEMO_SCALE
            store_id_list = [vector_rng.randrange(45) for _ in range(sale_count)]  # store ids 45..49 never sell
            amount_list = [vector_rng.randrange(100, 900_000) for _ in range(sale_count)]
            value_list = [vector_rng.gauss(500, 120) for _ in range(50_000)]
            store_id_array, amount_array, value_array = (
                np.array(store_id_list),
                np.array(amount_list),
                np.array(value_list),
            )
            """
        ),
        md(
            """
            The expected result comes from the given loop; both versions are timed once here,
            then the revenue checks (exact values, `int64`, zeros for stores without sales):
            """
        ),
        code(
            """
            expected_revenue = revenue_by_store_loop(store_id_list, amount_list, 50)
            loop_seconds = best_time_or_none(lambda: revenue_by_store_loop(store_id_list, amount_list, 50))
            numpy_seconds = best_time_or_none(lambda: revenue_by_store_numpy(store_id_array, amount_array, 50))
            run_checks(
                [
                    (
                        "revenue matches the loop (exact)",
                        lambda: revenue_by_store_numpy(store_id_array, amount_array, 50).tolist(),
                        expected_revenue,
                    ),
                    (
                        "revenue dtype is int64",
                        lambda: revenue_by_store_numpy(store_id_array, amount_array, 50).dtype == np.int64,
                        True,
                    ),
                    (
                        "stores without sales are 0",
                        lambda: revenue_by_store_numpy(store_id_array, amount_array, 50)[45:].tolist(),
                        [0] * 5,
                    ),
                ]
            )
            """
        ),
        md(
            """
            The z-score checks, then the one speed check (with a wide margin) and the measured
            ratio:
            """
        ),
        code(
            """
            run_checks(
                [
                    (
                        "z-scores match the loop",
                        lambda: bool(np.allclose(zscores_numpy(value_array), zscores_loop(value_list))),
                        True,
                    ),
                    (
                        "z-scores have mean 0 and std 1",
                        lambda: [
                            round(float(statistic(zscores_numpy(value_array))), 6)
                            for statistic in (np.mean, np.std)
                        ],
                        [0.0, 1.0],
                    ),
                    (
                        "vectorized revenue at least 5x faster",
                        lambda: numpy_seconds is not None and loop_seconds / numpy_seconds >= 5,
                        True,
                    ),
                ]
            )
            if numpy_seconds:
                print(
                    f"measured: loop {loop_seconds * 1000:.1f} ms, NumPy {numpy_seconds * 1000:.2f} ms "
                    f"-> {loop_seconds / numpy_seconds:.0f}x"
                )
            """
        ),
        md(
            """
            #### Exercise 5 — A 5× peak-memory reduction

            `event_summary_eager(path)` reads the whole event log into memory before
            summarizing it.

            1. Write `peak_memory(function, *args)`, which calls `function(*args)` and returns
               `(result, peak_bytes)`: the peak traced memory **during the call**, above what
               was allocated before it. It must also work when `tracemalloc` is already
               tracing (then leave it running), and stop tracing only if it started it.
            2. Write `event_summary_lean(path)` with the same result and **at least 5× less**
               peak memory.
            """
        ),
        code(
            '''
            def event_summary_eager(path: Path) -> dict[str, object]:
                """Event counts, total bytes and distinct users, computed from all rows in memory."""
                lines = path.read_text(encoding="utf-8").splitlines()
                header = lines[0].split(",")
                rows = [dict(zip(header, line.split(","), strict=True)) for line in lines[1:]]
                return {
                    "events": dict(sorted(Counter(row["event"] for row in rows).items())),
                    "total_bytes": sum(int(row["bytes"]) for row in rows),
                    "unique_users": len({row["user_id"] for row in rows}),
                }
            '''
        ),
        md("Your solution, part 1:"),
        code(
            '''
            def peak_memory(function: Callable[..., object], *args: object) -> tuple[object, int]:
                """Call function(*args); return (result, peak traced bytes above the starting level)."""
                raise NotImplementedError
            '''
        ),
        md("Your solution, part 2:"),
        code(
            '''
            def event_summary_lean(path: Path) -> dict[str, object]:
                """Same result as event_summary_eager, streaming the file."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 5:"),
        code(
            '''
            def peak_memory_keeps_outer_trace() -> bool:
                """peak_memory inside an outer trace must leave that trace running."""
                tracemalloc.start()
                try:
                    _, inner_peak = peak_memory(lambda: len(bytearray(2_000_000)))
                    return tracemalloc.is_tracing() and inner_peak >= 2_000_000
                finally:
                    tracemalloc.stop()


            def peak_ratio() -> float:
                """Peak of the eager version divided by peak of the lean version."""
                return (
                    peak_memory(event_summary_eager, LAB55_EVENTS)[1]
                    / peak_memory(event_summary_lean, LAB55_EVENTS)[1]
                )
            '''
        ),
        md(
            """
            The checks: `peak_memory` returns the result, sees a 5 MB temporary, stops only its
            own trace, and the lean summary gives the same result with at least 5× lower peak:
            """
        ),
        code(
            """
            run_checks(
                [
                    ("peak_memory returns the result", lambda: peak_memory(len, "chai")[0], 4),
                    (
                        "peak_memory sees a 5 MB temporary",
                        lambda: peak_memory(lambda: len(bytearray(5_000_000)))[1] >= 5_000_000,
                        True,
                    ),
                    (
                        "peak_memory stops the trace it started",
                        lambda: (peak_memory(len, "x"), tracemalloc.is_tracing())[1],
                        False,
                    ),
                    ("peak_memory works inside an outer trace", peak_memory_keeps_outer_trace, True),
                    (
                        "lean summary: same result",
                        lambda: event_summary_lean(LAB55_EVENTS),
                        event_summary_eager(LAB55_EVENTS),
                    ),
                    ("lean summary: at least 5x lower peak", lambda: peak_ratio() >= 5, True),
                ]
            )
            try:
                print(f"measured peak ratio eager/lean: {peak_ratio():.0f}x")
            except NotImplementedError:
                pass
            """
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 5.5."""
    return [
        md(
            """
            ### Recap — Unit 5.5

            | Concept | One-line takeaway | JS / Node equivalent |
            | --- | --- | --- |
            | Method | measure, profile, estimate with Amdahl, change one thing, re-measure | same discipline |
            | Benchmark hygiene | warm up, repeat, report min/median and spread, fresh processes; `timeit` turns GC off; `pyperf` automates it | `tinybench`, `mitata` |
            | Timing | `perf_counter` for durations, `process_time` for CPU, never `time.time()`; `%timeit -o` | `performance.now()` |
            | Deterministic profiling | `cProfile`/`profiling.tracing` + `pstats` (+ snakeviz): exact calls, real overhead | `--cpu-prof` |
            | Sampling profiling | Tachyon (3.15), py-spy, scalene: low overhead, attachable, wall vs CPU modes | `0x`, `perf` |
            | Line profiling | `line_profiler` for the suspects only | — |
            | Flame graphs | width = share of samples, height = depth; attack wide plateaus | Chrome flame chart |
            | Memory | `tracemalloc` (Python, by line, peak vs current), memray (everything, timeline), RSS is a third number | heap snapshots |
            | Algorithms first | dict/set lookups, no hidden O(n²), `heapq`, `bisect`, memoization | same |
            | Interpreter habits | built-ins in C, `join`, comprehensions, no exceptions in hot paths, stable types; aliases matter less since 3.11 | V8 inline caches |
            | Memory-lean data | `__slots__`, `array`, `memoryview`, generators, `sys.intern` | typed arrays, `Buffer` |
            | Caching | measure the hit rate; bound size; TTL for changing data; invalidate on write or version keys | `lru-cache` |
            | Vectorization | NumPy arrays, broadcasting, ufuncs (`at` for grouping); pandas or Polars for frames | typed-array loops, Arquero/Danfo |
            | Native code | ctypes/CFFI, Cython, PyO3, Numba, mypyc, PyPy; cross the boundary per loop, not per item | N-API, WASM |
            | Builds | 3.15t scales CPU threads, costs some single-thread speed; the JIT gives modest gains; measure both | V8 tiers |
            | Production | attach samplers to live processes, continuous profiling, ratio-based benchmarks in CI | Clinic.js, APMs |

            **Further reading**

            - [`timeit`](https://docs.python.org/3/library/timeit.html),
              [`time` clocks](https://docs.python.org/3/library/time.html#time.perf_counter),
              [The Python profilers (`cProfile`, `pstats`, `profiling`)](https://docs.python.org/3.15/library/profiling.html),
              [`tracemalloc`](https://docs.python.org/3/library/tracemalloc.html)
            - [`heapq`](https://docs.python.org/3/library/heapq.html), [`bisect`](https://docs.python.org/3/library/bisect.html),
              [`functools.lru_cache`](https://docs.python.org/3/library/functools.html#functools.lru_cache),
              [`array`](https://docs.python.org/3/library/array.html), [`memoryview`](https://docs.python.org/3/library/stdtypes.html#memoryview),
              [`ctypes`](https://docs.python.org/3/library/ctypes.html)
            - [PEP 799](https://peps.python.org/pep-0799/) (the `profiling` package and the sampling profiler),
              [PEP 659](https://peps.python.org/pep-0659/) (specializing adaptive interpreter),
              [PEP 709](https://peps.python.org/pep-0709/) (inlined comprehensions),
              [PEP 744](https://peps.python.org/pep-0744/) (JIT compilation),
              [PEP 703](https://peps.python.org/pep-0703/) / [PEP 779](https://peps.python.org/pep-0779/) (free-threading),
              [PEP 768](https://peps.python.org/pep-0768/) (safe external debugger interface),
              [PEP 3118](https://peps.python.org/pep-3118/) (buffer protocol)
            - Tools: [pyperf](https://pyperf.readthedocs.io/), [snakeviz](https://jiffyclub.github.io/snakeviz/),
              [py-spy](https://github.com/benfred/py-spy), [line_profiler](https://github.com/pyutils/line_profiler),
              [scalene](https://github.com/plasma-umass/scalene), [memray](https://bloomberg.github.io/memray/),
              [NumPy broadcasting](https://numpy.org/doc/stable/user/basics.broadcasting.html), [Polars](https://docs.pola.rs/),
              [PyO3](https://pyo3.rs/), [Cython](https://cython.org/), [Numba](https://numba.pydata.org/),
              [mypyc](https://mypyc.readthedocs.io/), [pytest-benchmark](https://pytest-benchmark.readthedocs.io/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 5.5 and Lab 5.5."""
    return [
        *_overview_cells(),
        *_method_cells(),
        *_timing_cells(),
        *_cpu_profiling_cells(),
        *_memory_profiling_cells(),
        *_algorithmic_cells(),
        *_interpreter_cells(),
        *_memory_lean_cells(),
        *_caching_cells(),
        *_vectorization_cells(),
        *_native_cells(),
        *_free_threading_jit_cells(),
        *_production_cells(),
        *_predict_cells(),
        *_lab_cells_part_1(),
        *_lab_cells_part_2(),
        *_recap_cells(),
    ]
