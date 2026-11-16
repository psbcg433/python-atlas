"""Phase 5 Project — 10× Faster Sales Report (notebook section).

The code lives in ``projects/sales-report/`` (real files: the scripts must run from a terminal
at full size). This section walks through it step by step, runs the benchmark at a reduced row
count, shows the full-size results and ends with 20 predict-the-output questions on Phase 5.
"""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

PROJECT_SETUP_SOURCE = r'''
import contextlib
import inspect
import os
import re
import subprocess
import sys
import textwrap
import time
import tracemalloc
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
from IPython.display import Markdown, display

DEMO_SCALE = int(os.environ.get("PHASE5_DEMO_SCALE", "1"))
REPO_ROOT = find_repo_root()
PROJECT_DIR = REPO_ROOT / "projects" / "sales-report"
PHASE5_DIR = REPO_ROOT / "notebooks" / "_scratch" / "phase5"
PHASE5_DIR.mkdir(parents=True, exist_ok=True)
PROJECT_ROWS = 50_000 * DEMO_SCALE  # reduced size for Run All; RESULTS.md holds the 1M-row run
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
CHILD_ENV = {
    **os.environ,
    "PYTHON_COLORS": "0",
    "PYTHONUNBUFFERED": "1",
    "NO_COLOR": "1",
    "PY_COLORS": "0",
}
CHILD_ENV.pop("FORCE_COLOR", None)


@contextlib.contextmanager
def network_delay(seconds: float) -> Iterator[None]:
    """Temporarily set the simulated store-API round trip (SALES_NETWORK_DELAY) in this process."""
    previous = os.environ.get("SALES_NETWORK_DELAY")
    os.environ["SALES_NETWORK_DELAY"] = str(seconds)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("SALES_NETWORK_DELAY")
        else:
            os.environ["SALES_NETWORK_DELAY"] = previous
'''

PROJECT_SETUP_SOURCE_2 = r'''
def run_in_project(*arguments: str, delay: float = 0.05, timeout: int = 300) -> str:
    """Run `python <arguments>` in projects/sales-report/ and return stdout + stderr."""
    completed = subprocess.run(
        [sys.executable, *arguments],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=PROJECT_DIR,
        env={**CHILD_ENV, "SALES_NETWORK_DELAY": str(delay)},
    )
    return (completed.stdout + completed.stderr).rstrip().replace(str(REPO_ROOT), "<repo>")


def run_child(source: str) -> str:
    """Run dedented source as a script in a child interpreter (Units 5.1-5.5)."""
    script = PHASE5_DIR / "child_script.py"
    script.write_text(textwrap.dedent(source).lstrip("\n"), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=PHASE5_DIR,
        env=CHILD_ENV,
    )
    return (completed.stdout + completed.stderr).rstrip()


def show_source(*objects: object) -> None:
    """Print the source code of functions or classes from the project files."""
    for item in objects:
        print(inspect.getsource(item).rstrip(), end="\n\n")


def traced_peak_mib(work: Callable[[], object]) -> float:
    """Peak tracemalloc MiB while running work (NumPy reports its buffers to tracemalloc too)."""
    tracemalloc.start()
    work()
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    return peak / 2**20


import common  # noqa: E402  (projects/sales-report/ is on sys.path now)
import fast_report  # noqa: E402
import slow_report  # noqa: E402

print(f"project folder: <repo>/{PROJECT_DIR.relative_to(REPO_ROOT)}")
print(f"{PROJECT_ROWS=:,}  (DEMO_SCALE={DEMO_SCALE})")
print(
    "files:",
    ", ".join(
        sorted(
            path.name for path in PROJECT_DIR.iterdir() if path.suffix in {".py", ".md", ".toml"}
        )
    ),
)
'''


def _overview_cells() -> list[NotebookNode]:
    """Project opener and setup."""
    return [
        md(
            """
            ## Phase 5 Project — 10× Faster Sales Report

            **Brief.** A nightly script turns one million sales rows into a text report:
            totals, revenue by region, top stores, top products, monthly revenue and the best
            store/product pairs. It was written quickly and it shows: nested loops, repeated
            scans over all rows, string concatenation, money as floats, and 40 store-directory
            API calls made one after another. Make it **at least 10× faster with at least 3×
            less peak memory**, without changing a single character of its output, and
            document every step (change → time → memory → reason), including one concurrency
            step.

            | File (`projects/sales-report/`) | Role |
            | --- | --- |
            | `common.py` | product catalog, seeded data generator (`generate_chunks`), simulated store API (`fetch_store_profile`) |
            | `slow_report.py` | the deliberately slow baseline (step 0) |
            | `fast_report.py` | steps 1–5, each a complete `build_report(rows, seed)`; `STEPS` describes them |
            | `benchmark.py` | runs every step in a fresh process, measures wall time and peak RSS, writes `RESULTS.md` |
            | `tests/test_reports.py` | every step must produce the slow report byte for byte |
            | `RESULTS.md` | the full-size (1 000 000 rows) benchmark, run from a terminal |

            **Method (Unit 5.5.1).** Measure the baseline, profile it, fix the largest cost,
            re-measure, repeat. Correctness is checked at every step by comparing report
            text, so no optimization can quietly change an answer.

            **How this section runs.** The scripts are real files, imported from the project
            folder. Correctness checks run in the kernel with the simulated network switched
            off; timings run in child processes. The benchmark runs here at
            `PROJECT_ROWS = 50 000 × DEMO_SCALE` rows so Run All stays fast; the 1M-row numbers
            come from `RESULTS.md`, produced in a terminal with:

            ```bash
            cd projects/sales-report
            uv run python benchmark.py --rows 1000000      # writes RESULTS.md
            uv run pytest tests -q                          # same report at every step
            ```
            """
        ),
        md(
            """
            Project setup, part 1: imports, paths, the reduced row count, and `network_delay()`,
            which switches the simulated store API's round trip for in-kernel runs.
            """
        ),
        code(PROJECT_SETUP_SOURCE),
        md(
            """
            Project setup, part 2: helpers to run the project scripts in a child process, show
            source code and measure traced peak memory; then the three project modules are
            imported.
            """
        ),
        code(PROJECT_SETUP_SOURCE_2),
    ]


def _input_cells() -> list[NotebookNode]:
    """The input data and the simulated API."""
    return [
        md(
            """
            ### The input: seeded rows and a slow API

            Both versions read the same rows from `generate_chunks(row_count, seed)`: NumPy
            columns (store index, product index, quantity, day of year) in chunks of 100 000
            rows from a seeded generator, so a given `(row_count, seed)` always means the same
            sales. Prices come from a fixed catalog in **integer paise**. The store directory
            "API" sleeps for one round trip (`SALES_NETWORK_DELAY`, default 50 ms) per call:
            """
        ),
        code(
            """
            show_source(common.generate_chunks, common.fetch_store_profile)
            """
        ),
        md("What one chunk and one API call look like:"),
        code(
            """
            first_chunk = next(common.generate_chunks(5, seed=42))
            print(f"{len(first_chunk)} rows, first order number {first_chunk.first_order_number}")
            for column in ("store_index", "product_index", "quantity", "day"):
                print(f"  {column:<14} {getattr(first_chunk, column).tolist()}")
            print(f"catalog: {len(common.PRODUCTS)} products, e.g. {common.PRODUCTS[0]}")
            with network_delay(0.05):
                start = time.perf_counter()
                profile = common.fetch_store_profile("ST-07")
                print(f"{profile}  ({(time.perf_counter() - start) * 1000:.0f} ms)")
            """
        ),
    ]


def _baseline_cells() -> list[NotebookNode]:
    """Step 0: the slow script, its report, its profile."""
    return [
        md(
            """
            ### Step 0 — The baseline and its report

            The slow script materializes every row as a dict, with a float price and per-row
            strings for the order id and the ISO date:
            """
        ),
        code(
            """
            show_source(slow_report.generate_rows)
            """
        ),
        md(
            """
            Then every metric is a separate scan over all rows, and the per-group totals are
            nested loops: 40 stores × all rows, 60 products × all rows, 12 months × all rows.
            The store section is typical (the `# SLOW:` comments mark each mistake):
            """
        ),
        code(
            """
            show_source(slow_report.fetch_profiles, slow_report.store_section)
            """
        ),
        md("The report itself, for 20 000 rows (the same text at every step, at any size):"),
        code(
            """
            with network_delay(0):
                reference_report = slow_report.build_report(20_000, 42)
            print(reference_report)
            """
        ),
        md(
            """
            #### Profile before optimizing

            A `cProfile` run of the baseline in a child process (with the 50 ms network delay
            on), sorted by own time:
            """
        ),
        code(
            '''
            baseline_profile = run_child(
                f"""
                import cProfile, os, pstats, sys
                os.environ["SALES_NETWORK_DELAY"] = "0.05"
                sys.path.insert(0, {str(PROJECT_DIR)!r})
                import slow_report
                with cProfile.Profile() as profiler:
                    slow_report.build_report({PROJECT_ROWS}, 42)
                pstats.Stats(profiler).strip_dirs().sort_stats("tottime").print_stats(8)
                """
            )
            print(re.sub(r"\\n\\s*\\n", "\\n", baseline_profile.split("Ordered by")[1]))
            '''
        ),
        md(
            """
            Reading it with Amdahl in mind (5.5.1):

            - `time.sleep` (inside `fetch_store_profile`) holds a fixed **2 s** (40 × 50 ms), at
              any row count. At small sizes it dominates; it can only be removed by *overlapping*
              the waits (concurrency), not by faster code.
            - `product_section`, `store_section`, `month_section` and `region_section` are the
              nested scans: their cost grows with groups × rows, and at 1M rows they are most
              of the runtime.
            - `generate_rows` (dicts, strings, NumPy scalars) costs time *and* is the reason
              the peak memory is about half a gigabyte at 1M rows.

            So the plan: remove the nested scans (step 1), shrink the rows (step 2), stop
            holding them all (step 3), overlap the network waits (step 4), and finally move the
            remaining per-row loop into C (step 5).
            """
        ),
    ]


def _step_cells() -> list[NotebookNode]:
    """Steps 1-5 with code and checks."""
    return [
        md(
            """
            ### Step 1 — One pass with dict accumulators

            Every total is updated in a **single loop**: per-store, per-product, per-month and
            per-pair dicts are indexed by the row's key instead of scanning all rows once per
            group (5.5.5: removing quadratic loops). Money is still a float here, converted to
            integer paise once at the end so the shared renderer can be used:
            """
        ),
        code(
            """
            show_source(fast_report.summarize_rows_single_pass)
            """
        ),
        md(
            """
            Every step's report must equal the baseline's. The check runs each step at a few
            sizes with the network off (the full check is the project's pytest suite, below):
            """
        ),
        code(
            '''
            def same_report_as_baseline(
                step: fast_report.Step, sizes: tuple[int, ...] = (0, 997, 20_000)
            ) -> bool:
                """True if the step reproduces the baseline report text at every size."""
                with network_delay(0):
                    return all(step.build(rows, 42) == slow_report.build_report(rows, 42) for rows in sizes)


            print(f"step 1 matches the baseline: {same_report_as_baseline(fast_report.STEPS[1])}")
            '''
        ),
        md(
            """
            ### Step 2 — Lean rows, exact money, no per-row strings

            A row becomes a tuple of four small ints (store index, product index, quantity, day
            of year). Money is integer paise looked up in a plain-`int` price list; the month
            comes from a day → month table instead of slicing an ISO date string; no order id
            or pair key string is built per row; the report is assembled with one `"\\n".join`
            (5.5.6). `add_rows` also binds the totals to local names before the loop:
            """
        ),
        code(
            """
            show_source(fast_report.generate_lean_rows, fast_report.add_rows)
            """
        ),
        md(
            "What a row costs in each representation (`sys.getsizeof` of the container only; the dict row also owns two unique strings and a float):"
        ),
        code(
            """
            with network_delay(0):
                dict_row = slow_report.generate_rows(1, 42)[0]
                lean_row = fast_report.generate_lean_rows(1, 42)[0]
            print(f"dict row : {sys.getsizeof(dict_row)} bytes  {dict_row}")
            print(f"tuple row: {sys.getsizeof(lean_row)} bytes  {lean_row}")
            print(f"step 2 matches the baseline: {same_report_as_baseline(fast_report.STEPS[2])}")
            """
        ),
        md(
            """
            #### Why integer paise, if the float report is already identical?

            The baseline's floats happen to produce the right report: every line amount is
            price × whole quantity, and totals are rounded once at the end. Add one realistic
            rule, 18 % GST per line rounded half-up to the paisa (Unit 1.3), and floats start
            to disagree with exact arithmetic on some lines:
            """
        ),
        code(
            '''
            def gst_float(price_paise: int, quantity: int) -> float:
                """GST in rupees with float arithmetic and round() (what the slow style would do)."""
                return round(price_paise / 100 * quantity * 0.18, 2)


            def gst_paise(price_paise: int, quantity: int) -> int:
                """GST in paise, exact: integer arithmetic, half-up rounding."""
                return (price_paise * quantity * 18 + 50) // 100


            lines = [(product.price_paise, quantity) for product in common.PRODUCTS for quantity in range(1, 6)]
            wrong = [(p, q) for p, q in lines if round(gst_float(p, q) * 100) != gst_paise(p, q)]
            print(
                f"{len(wrong)} of {len(lines)} catalog lines get a different GST with floats, e.g. {wrong[:3]}"
            )
            '''
        ),
        md(
            """
            Exact integers make the report correct by construction, not by luck.

            ### Step 3 — Stream chunks instead of materializing the rows

            Step 2 still builds a list of a million tuples before adding anything up. Since
            every total is a running sum, each chunk can be aggregated and dropped (5.5.7:
            generators); only one 100 000-row chunk exists at a time:
            """
        ),
        code(
            """
            show_source(fast_report.summarize_stream)
            """
        ),
        md(
            "Peak traced memory of the two approaches at `PROJECT_ROWS` (the gap grows with the row count; at 1M rows see `RESULTS.md`):"
        ),
        code(
            """
            def materialize_then_add() -> None:
                fast_report.add_rows(
                    fast_report.SalesSummary(), fast_report.generate_lean_rows(PROJECT_ROWS * 4, 42)
                )


            list_peak = traced_peak_mib(materialize_then_add)
            stream_peak = traced_peak_mib(lambda: fast_report.summarize_stream(PROJECT_ROWS * 4, 42))
            print(
                f"{PROJECT_ROWS * 4:,} rows: list of tuples peak {list_peak:.1f} MiB, "
                f"streaming peak {stream_peak:.1f} MiB"
            )
            print(f"step 3 matches the baseline: {same_report_as_baseline(fast_report.STEPS[3])}")
            """
        ),
        md(
            """
            ### Step 4 — Concurrent store lookups (the concurrency step)

            The 40 API calls are pure waiting, so they are an I/O-bound job (Unit 5.1): a
            thread pool submits all 40 at once, and the main thread aggregates the rows
            **while** the requests are in flight. `time.sleep`, like a socket read, releases
            the GIL, so the waits overlap with each other *and* with the CPU work. Results are
            collected in submission order, so the report does not depend on which call
            finished first:
            """
        ),
        code(
            """
            show_source(fast_report.build_with_concurrent_profiles)
            """
        ),
        md("The effect on the network part alone, at the real 50 ms delay:"),
        code(
            """
            from concurrent.futures import ThreadPoolExecutor

            with network_delay(0.05):
                start = time.perf_counter()
                sequential = slow_report.fetch_profiles(common.STORE_CODES)
                sequential_seconds = time.perf_counter() - start
                start = time.perf_counter()
                with ThreadPoolExecutor(max_workers=40) as pool:
                    concurrent_profiles = list(pool.map(common.fetch_store_profile, common.STORE_CODES))
                concurrent_seconds = time.perf_counter() - start
            print(
                f"sequential {sequential_seconds:.2f} s, concurrent {concurrent_seconds:.3f} s, "
                f"same profiles: {sequential == concurrent_profiles}"
            )
            print(f"step 4 matches the baseline: {same_report_as_baseline(fast_report.STEPS[4])}")
            """
        ),
        md(
            """
            **Why threads, not asyncio or processes?** The API client here is blocking (like
            `requests`), so threads are the direct fit; with an async HTTP client the same step
            is `asyncio.gather` under a `Semaphore` (Units 5.3–5.4) and, since the aggregation
            is CPU work, it would go to `asyncio.to_thread`. Processes buy nothing for waiting
            and would have to pickle the rows. And once the aggregation is vectorized (step 5)
            it takes tens of milliseconds at 1M rows, so splitting it across processes would
            cost more in start-up and pickling than it saves (Amdahl again, Unit 5.2).

            ### Step 5 — Vectorize the per-chunk grouping

            The remaining cost is the Python loop over each row (about 1 s per million rows).
            NumPy does the same grouping in C: one `int64` amount column per chunk, then
            `np.add.at` adds amounts, units and counts into `stores × products` and `months`
            tables. `np.add.at` handles repeated indices correctly (a plain fancy-index `+=`
            would count each index once per chunk), and everything stays integer, so money is
            exact (5.5.9):
            """
        ),
        code(
            """
            show_source(fast_report.summarize_vectorized)
            """
        ),
        md(
            "Check, and compare the two aggregation loops alone (no network) at `PROJECT_ROWS × 4`:"
        ),
        code(
            """
            print(f"step 5 matches the baseline: {same_report_as_baseline(fast_report.STEPS[5])}")
            timings = {}
            for label, summarize in (
                ("Python loop (step 3)", fast_report.summarize_stream),
                ("NumPy (step 5)", fast_report.summarize_vectorized),
            ):
                start = time.perf_counter()
                summary = summarize(PROJECT_ROWS * 4, 42)
                timings[label] = time.perf_counter() - start
                print(
                    f"{label:<22} {timings[label] * 1000:7.1f} ms   "
                    f"revenue {fast_report.format_paise(summary.revenue_paise)}"
                )
            print(f"ratio: {timings['Python loop (step 3)'] / timings['NumPy (step 5)']:.0f}x")
            """
        ),
    ]


def _verification_cells() -> list[NotebookNode]:
    """Tests, benchmark, results."""
    return [
        md(
            """
            ### The safety net: identical reports, tested

            `tests/test_reports.py` compares every step with the slow report at several sizes
            and seeds (including 0 rows, 1 row and a size that spans two chunks), checks the
            generator's determinism, the exact money formatting, the grand total against an
            independent sum, and that the store lookups really overlap:
            """
        ),
        code(
            """
            test_file = PROJECT_DIR / "tests" / "test_reports.py"
            print("\\n".join(test_file.read_text(encoding="utf-8").splitlines()[10:42]))
            """
        ),
        md("Run the suite with pytest in a child process:"),
        code(
            """
            print(run_in_project("-m", "pytest", "tests", "-q", "-p", "no:cacheprovider", timeout=600))
            """
        ),
        md(
            """
            ### The benchmark at a reduced size

            `benchmark.py` runs each step in a **fresh process** (5.5.1), measures wall time
            around `build_report` and the peak resident set size, and checks that every step's
            report has the same SHA-256. At `PROJECT_ROWS` rows the fixed costs dominate: the
            2 s of sequential network waits in steps 0–3 and the ~35 MiB interpreter + NumPy
            floor in the memory column. So expect a large speedup from step 4 and a modest
            memory ratio here:
            """
        ),
        code(
            """
            reduced = run_in_project("benchmark.py", "--rows", str(PROJECT_ROWS), "--output", "-")
            print("\\n".join(line for line in reduced.splitlines() if line.startswith("step ")))
            display(Markdown(reduced[reduced.index("| Step") :]))
            """
        ),
        md(
            """
            ### The full-size result (1 000 000 rows)

            `RESULTS.md` was written by `benchmark.py --rows 1000000` run from a terminal (it
            takes about half a minute, most of it the baseline). Your machine will give other
            numbers; the shape (which step helps time, which helps memory) should hold:
            """
        ),
        code(
            """
            results_text = (PROJECT_DIR / "RESULTS.md").read_text(encoding="utf-8")
            display(Markdown(results_text))
            verdict = re.search(
                r"\\*\\*Result: ([\\d.,]+)x faster and ([\\d.,]+)x less peak memory\\*\\*", results_text
            )
            if verdict:
                speedup, memory_ratio = (float(value.replace(",", "")) for value in verdict.groups())
                print(f"targets (>= 10x faster, >= 3x less memory) met: {speedup >= 10 and memory_ratio >= 3}")
            """
        ),
        md(
            """
            ### What the steps teach

            | Step | What it fixed | Lesson | Unit |
            | --- | --- | --- | --- |
            | 1 | nested group × row scans | the algorithm first: an O(groups × rows) job became O(rows) | 5.5.5 |
            | 2 | dict rows, per-row strings, float money | fewer, smaller objects are faster *and* leaner; exact money by construction | 5.5.6–5.5.7, 1.3 |
            | 3 | the list of all rows | streaming makes peak memory independent of the input size | 5.5.7 |
            | 4 | 40 sequential waits | overlap I/O with threads; a fixed cost no CPU optimization can touch | 5.1, 5.4 |
            | 5 | the per-row Python loop | vectorize the hot loop; keep integers in int64 | 5.5.9 |

            Two more lessons hide in the table: the order matters less than measuring after
            every change (at 50 000 rows step 4 looks like the only one that counts; at 1M rows
            step 1 and step 5 carry the CPU work), and every step kept the output **identical**,
            which is what makes it safe to ship.
            """
        ),
    ]


QUESTIONS: list[tuple[str, str, str, str]] = [
    (
        "5.1",
        """
        import threading

        order = []
        worker = threading.Thread(target=lambda: order.append("worker"))
        worker.run()  # run(), not start()
        order.append("main")
        print(order, worker.is_alive())
        """,
        """
        `['worker', 'main'] False`. `run()` is the method that `start()` calls **in the new
        thread**; calling it directly runs the target in the *current* thread, like any
        function call. No thread was started, so it is not alive.
        """,
        "",
    ),
    (
        "5.1",
        """
        import threading

        lock, rlock = threading.Lock(), threading.RLock()
        print(lock.acquire(), lock.acquire(timeout=0.1))
        print(rlock.acquire(), rlock.acquire(timeout=0.1))
        """,
        """
        `True False`, then `True True`. A `Lock` is not re-entrant: the second acquire by the
        same thread waits for itself and times out. An `RLock` counts acquisitions by its
        owning thread, so the owner may acquire it again (and must release it as many times).
        """,
        """
        import threading

        lock, rlock = threading.Lock(), threading.RLock()
        print(lock.acquire(), lock.acquire(timeout=0.1))
        print(rlock.acquire(), rlock.acquire(timeout=0.1))
        lock.release()
        rlock.release()
        rlock.release()
        """,
    ),
    (
        "5.1",
        '''
        import time
        from concurrent.futures import ThreadPoolExecutor


        def nap(seconds: float) -> float:
            """Sleep, then return the duration."""
            time.sleep(seconds)
            return seconds


        with ThreadPoolExecutor(max_workers=3) as pool:
            print(list(pool.map(nap, [0.3, 0.1, 0.2])))
        ''',
        """
        `[0.3, 0.1, 0.2]`. `Executor.map` returns results in **input order**, whatever order
        the calls finish in (the 0.1 s call finishes first, but its result waits for the
        0.3 s one). Use `as_completed` for finish order.
        """,
        "",
    ),
    (
        "5.1",
        """
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor() as pool:
            future = pool.submit(int, "12x")
        print(future.done(), type(future.exception()).__name__)
        """,
        """
        `True ValueError`. An exception raised in a worker does not crash the program or
        print anything: it is stored in the future. `future.exception()` returns it, and
        `future.result()` would re-raise it. Futures nobody checks hide errors.
        """,
        "",
    ),
    (
        "5.2",
        """
        import multiprocessing as mp

        counter = 0

        def bump():
            global counter
            counter += 1
            print("child sees", counter)

        if __name__ == "__main__":
            process = mp.Process(target=bump)
            process.start()
            process.join()
            print("parent sees", counter)
        """,
        """
        `child sees 1`, then `parent sees 0`. A process has its own memory: the child changed
        **its copy** of `counter`. Sharing needs explicit IPC (queues, pipes, shared memory,
        a manager). The proof runs the script in a child interpreter (a notebook function
        cannot be a process target under spawn/forkserver).
        """,
        '''
        print(
            run_child(
                """
                import multiprocessing as mp

                counter = 0


                def bump() -> None:
                    global counter
                    counter += 1
                    print("child sees", counter, flush=True)


                if __name__ == "__main__":
                    process = mp.Process(target=bump)
                    process.start()
                    process.join()
                    print("parent sees", counter)
                """
            )
        )
        ''',
    ),
    (
        "5.2",
        """
        import pickle

        try:
            pickle.dumps(lambda price: price * 1.18)
        except Exception as error:
            print(type(error).__name__)
        """,
        """
        `PicklingError`. Functions are pickled **by reference** (module + qualified name), and
        a lambda has no importable name. That is why process-pool workers must be module-level
        functions in an importable module (Unit 5.2), and why `functools.partial` of such a
        function works where a lambda fails.
        """,
        "",
    ),
    (
        "5.2",
        """
        parallel_fraction, workers = 0.9, 8
        print(round(1 / ((1 - parallel_fraction) + parallel_fraction / workers), 2))
        """,
        """
        `4.71`. Amdahl's law: 10 % of the work stays serial, so 8 workers give 1 / (0.1 +
        0.1125) ≈ 4.71×, not 8×, and no number of workers can beat 10×.
        """,
        "",
    ),
    (
        "5.2",
        """
        import multiprocessing as mp
        import sys

        process = mp.Process(target=sys.exit, args=(3,))
        process.start()
        process.join()
        print(process.exitcode)
        """,
        """
        `3`. `sys.exit(3)` in the child raises `SystemExit(3)`, and the process exits with
        that status. `exitcode` is `0` for success, the exit status otherwise, and a negative
        signal number (such as `-15` for SIGTERM) when the child was killed. `sys.exit` works
        as a target because it is importable by name.
        """,
        "",
    ),
    (
        "5.3",
        """
        import asyncio

        async def worker(name):
            print(f"{name} start")
            await asyncio.sleep(0)
            print(f"{name} end")

        async def main():
            task = asyncio.create_task(worker("task"))
            print("main before")
            await asyncio.sleep(0)
            print("main after")
            await task

        asyncio.run(main())
        """,
        """
        `main before`, `task start`, `main after`, `task end`. `create_task` only schedules the
        task. Each `await asyncio.sleep(0)` puts the current task at the **back** of the ready
        queue: main yields, the task runs to its first `await`, main resumes, then the task
        finishes. (The proof uses top-level `await main()`, because the kernel's loop is
        already running.)
        """,
        '''
        import asyncio


        async def worker(name: str) -> None:
            """Print around one yield to the loop."""
            print(f"{name} start")
            await asyncio.sleep(0)
            print(f"{name} end")


        async def main() -> None:
            """Schedule the worker and interleave with it."""
            task = asyncio.create_task(worker("task"))
            print("main before")
            await asyncio.sleep(0)
            print("main after")
            await task


        await main()
        ''',
    ),
    (
        "5.3",
        """
        async def total():
            return 42


        result = total()
        print(type(result).__name__)
        result.close()
        """,
        """
        `coroutine`. Calling an `async def` function runs **none** of its body: it returns a
        coroutine object, which runs only when awaited or wrapped in a task. (Unlike a JS
        `async` function, which runs synchronously up to its first `await` and returns a
        Promise.) `close()` avoids the "never awaited" warning.
        """,
        "",
    ),
    (
        "5.3",
        """
        import asyncio

        async def after(seconds, value):
            await asyncio.sleep(seconds)
            return value

        print(await asyncio.gather(after(0.2, "slow"), after(0.1, "fast")))
        """,
        """
        `['slow', 'fast']`. Like `Promise.all`, `gather` returns results in the order the
        awaitables were **passed**, not the order they finished. The whole call takes about
        0.2 s, because both sleeps run concurrently.
        """,
        '''
        import asyncio


        async def after(seconds: float, value: str) -> str:
            """Return value after a delay."""
            await asyncio.sleep(seconds)
            return value


        print(await asyncio.gather(after(0.2, "slow"), after(0.1, "fast")))
        ''',
    ),
    (
        "5.3",
        """
        import asyncio

        # in Jupyter, where an event loop is already running:
        pending = asyncio.sleep(0)
        try:
            asyncio.run(pending)
        except RuntimeError as error:
            print(error)
        """,
        """
        `asyncio.run() cannot be called from a running event loop`. `asyncio.run` creates and
        owns a new loop, and one thread can run only one loop at a time. In a notebook use
        top-level `await`; in a script, call `asyncio.run(main())` once at the entry point.
        """,
        """
        import asyncio

        pending = asyncio.sleep(0)
        try:
            asyncio.run(pending)
        except RuntimeError as error:
            print(error)
        finally:
            pending.close()
        """,
    ),
    (
        "5.4",
        """
        import asyncio

        try:
            async with asyncio.timeout(0.05):
                await asyncio.sleep(1)
        except TimeoutError:
            print("timed out")
        print("after")
        """,
        """
        `timed out`, then `after`. When the deadline passes, the sleeping code receives a
        `CancelledError`, and `asyncio.timeout` converts it into the built-in `TimeoutError`
        at the block's edge (3.11+). The rest of the program carries on.
        """,
        "",
    ),
    (
        "5.4",
        """
        import asyncio

        gate = asyncio.Semaphore(2)
        state = {"running": 0, "peak": 0}

        async def job():
            async with gate:
                state["running"] += 1
                state["peak"] = max(state["peak"], state["running"])
                await asyncio.sleep(0.01)
                state["running"] -= 1

        await asyncio.gather(*(job() for _ in range(6)))
        print(state["peak"])
        """,
        """
        `2`. Six jobs start together, but the semaphore lets only two inside the `async with`
        block at a time: the asyncio version of `p-limit(2)`.
        """,
        '''
        import asyncio

        gate = asyncio.Semaphore(2)
        state = {"running": 0, "peak": 0}


        async def job() -> None:
            """Count how many jobs are inside the semaphore at once."""
            async with gate:
                state["running"] += 1
                state["peak"] = max(state["peak"], state["running"])
                await asyncio.sleep(0.01)
                state["running"] -= 1


        await asyncio.gather(*(job() for _ in range(6)))
        print(state["peak"])
        ''',
    ),
    (
        "5.4",
        """
        import asyncio

        queue = asyncio.Queue()
        queue.put_nowait("order-1")
        queue.shutdown()
        print(queue.get_nowait())
        try:
            queue.put_nowait("order-2")
        except asyncio.QueueShutDown:
            print("QueueShutDown")
        """,
        """
        `order-1`, then `QueueShutDown`. `Queue.shutdown()` (*New in 3.13*) stops new `put`s at
        once, but items already queued can still be taken; `shutdown(immediate=True)` would
        drop them. Workers stop when `get()` raises `QueueShutDown` on an empty, shut-down
        queue.
        """,
        "",
    ),
    (
        "5.4",
        """
        import asyncio
        import contextvars

        request_id = contextvars.ContextVar("request_id", default="-")

        async def handler():
            request_id.set("req-7")

        await asyncio.create_task(handler())
        print(request_id.get())
        """,
        """
        `-`. Each task runs in a **copy** of the context that was current when it was created.
        The handler's `set` changes only its copy, so the caller still sees the default. This
        is what keeps concurrent requests' IDs apart.
        """,
        '''
        import asyncio
        import contextvars

        request_id = contextvars.ContextVar("request_id", default="-")


        async def handler() -> None:
            """Set the request id inside the task's own context copy."""
            request_id.set("req-7")


        await asyncio.create_task(handler())
        print(request_id.get())
        ''',
    ),
    (
        "5.5",
        """
        import time

        start = time.process_time()
        time.sleep(0.2)
        print(round(time.process_time() - start, 1))
        """,
        """
        `0.0`. `process_time` counts CPU time, and a sleeping process uses almost none.
        `perf_counter` would show 0.2. Comparing the two tells you whether code is waiting or
        computing (5.5.2).
        """,
        "",
    ),
    (
        "5.5",
        """
        import heapq

        heap = [5, 1, 4]
        heapq.heapify(heap)
        heapq.heappush(heap, 0)
        print(heap[0], heapq.heappop(heap), heapq.heappop(heap))
        """,
        """
        `0 0 1`. A heap keeps its **smallest** item at index 0; `heappop` removes and returns
        it, and the next smallest moves to the front. The rest of the list is only partially
        ordered.
        """,
        "",
    ),
    (
        "5.5",
        """
        squares = (n * n for n in range(4))
        print(sum(squares), sum(squares))
        """,
        """
        `14 0`. A generator expression produces its items once. The first `sum` consumes all
        of them (0 + 1 + 4 + 9); the second finds the generator exhausted. Generators save
        memory (5.5.7) but are one-shot, unlike a list.
        """,
        "",
    ),
    (
        "5.5",
        """
        import numpy as np

        totals = np.zeros(3, dtype=np.int64)
        stores = np.array([0, 2, 0, 0])
        totals[stores] += 1
        print(totals)
        np.add.at(totals, stores, 1)
        print(totals)
        """,
        """
        `[1 0 1]`, then `[4 0 2]`. Fancy-index `+=` is buffered: it reads `totals[[0, 2, 0, 0]]`,
        adds 1, and writes back, so store 0 is incremented **once** however often it appears.
        `np.add.at` is unbuffered and applies every occurrence, which is why the project's
        step 5 groups with it.
        """,
        "",
    ),
]


def _question_cells() -> list[NotebookNode]:
    """20 predict-the-output questions covering Units 5.1-5.5."""
    unit_counts: dict[str, int] = {}
    for unit, *_ in QUESTIONS:
        unit_counts[unit] = unit_counts.get(unit, 0) + 1
    coverage = ", ".join(f"{count} on Unit {unit}" for unit, count in unit_counts.items())
    cells = [
        md(
            f"""
            ### Phase 5 review — predict the output

            Twenty questions across the whole phase ({coverage}). Decide on the answer
            before opening it, then run the proof cell. Timing-sensitive answers use delays
            large enough to be deterministic.
            """
        )
    ]
    for question_number, (unit, snippet, answer, proof) in enumerate(QUESTIONS, start=1):
        cells.append(md(f"#### Question {question_number} (Unit {unit})"))
        cells.extend(predict_cells(snippet=snippet, answer=answer, proof=proof or snippet))
    return cells


def _closing_cells() -> list[NotebookNode]:
    """Phase wrap-up."""
    return [
        md(
            """
            ## Phase 5 — Wrap-up

            | You can now… | Where |
            | --- | --- |
            | choose threads, processes, subinterpreters or asyncio for a workload, and back the choice with a benchmark | 5.1, 5.2, 5.4 |
            | explain the event loop's ready queue, tasks and futures as precisely as Node's phases and microtasks | 5.3 |
            | run asyncio safely in production: task groups, timeouts, backpressure, retries, tests | 5.4 |
            | profile CPU and memory, read a flame graph, and optimize in the right order | 5.5 |
            | take a real script from slow to fast without changing its output, and prove both | Project |

            **Next:** Phase 6 builds web services with FastAPI on top of the asyncio, HTTP
            client and testing skills from this phase.
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for the Phase 5 Project."""
    return [
        *_overview_cells(),
        *_input_cells(),
        *_baseline_cells(),
        *_step_cells(),
        *_verification_cells(),
        *_question_cells(),
        *_closing_cells(),
    ]
