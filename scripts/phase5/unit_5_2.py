"""Unit 5.2 — Multiprocessing and Subinterpreters (with Lab 5.2)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = r'''
import concurrent.futures
import functools
import importlib
import importlib.util
import itertools
import math
import multiprocessing
import operator
import os
import pickle
import pickletools
import platform
import random
import re
import signal
import subprocess
import sys
import sysconfig
import textwrap
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable
from multiprocessing import shared_memory
from pathlib import Path
from types import ModuleType

DEMO_SCALE = int(os.environ.get("PHASE5_DEMO_SCALE", "1"))  # the one knob for workload sizes
REPO_ROOT = find_repo_root()
scratch_dir = REPO_ROOT / "notebooks" / "_scratch"  # git-ignored
PHASE5_DIR = scratch_dir / "phase5"
PHASE5_DIR.mkdir(parents=True, exist_ok=True)
os.chdir(REPO_ROOT / "notebooks")  # %%writefile cells use paths relative to notebooks/
if str(PHASE5_DIR) not in sys.path:
    sys.path.insert(0, str(PHASE5_DIR))  # child processes receive a copy of sys.path
CHILD_ENV = {**os.environ, "PYTHON_COLORS": "0", "PYTHONUNBUFFERED": "1"}
HAS_NUMPY = importlib.util.find_spec("numpy") is not None
HAS_INTERPRETERS = importlib.util.find_spec("concurrent.interpreters") is not None


def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"


def raised_message(thunk: Callable[[], object]) -> str:
    """Call thunk and return "ErrorName: message" (memory addresses hidden), or "no error"."""
    try:
        thunk()
    except Exception as error:
        return re.sub(r" at 0x[0-9a-f]+", "", f"{type(error).__name__}: {error}")
    return "no error"


def interpreter_label() -> str:
    """Implementation, version and build flavour: print it next to every benchmark."""
    free_threaded = bool(sysconfig.get_config_var("Py_GIL_DISABLED"))
    build = "free-threaded build" if free_threaded else "default (GIL) build"
    implementation = platform.python_implementation()
    return f"{implementation} {platform.python_version()}, {build}, {platform.machine()}"
'''

UNIT_SETUP_SOURCE_2 = r'''
class Timer:
    """Timing context manager (shared since Unit 1.14): reports on exit, keeps elapsed_seconds."""

    def __init__(self, label: str, report: Callable[[str], None] | None = print) -> None:
        self.label = label
        self.report = report
        self.elapsed_seconds = 0.0

    def __enter__(self) -> Timer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.elapsed_seconds = time.perf_counter() - self._start
        if self.report is not None:
            self.report(f"{self.label} took {self.elapsed_seconds * 1000:.2f} ms")


def run_child(
    source: str, python: str = sys.executable, extra_env: dict[str, str] | None = None
) -> str:
    """Run dedented source as a script in a child interpreter; return its stdout + stderr."""
    script = PHASE5_DIR / "child_script.py"
    script.write_text(textwrap.dedent(source).lstrip("\n"), encoding="utf-8")
    completed = subprocess.run(
        [python, str(script)], capture_output=True, text=True, timeout=120,
        env={**CHILD_ENV, **(extra_env or {})}, cwd=PHASE5_DIR,
    )  # fmt: skip
    output = (completed.stdout + completed.stderr).rstrip()
    for path, label in ((str(PHASE5_DIR), "<scratch>"), (str(Path(python).parent), "<python>")):
        output = output.replace(path, label)
    output = re.sub(r"pid=\d+", "pid=<pid>", output)
    return re.sub(r"/[^\s\"']*/lib/python3\.\d+t?/", "<stdlib>/", output)


def fresh_import(module_name: str) -> ModuleType:
    """Import a module saved by a %%writefile cell, always re-reading the file from disk."""
    for cached in (PHASE5_DIR / "__pycache__").glob(f"{module_name}.*.pyc"):
        cached.unlink()  # a stale .pyc could survive a quick edit
    importlib.invalidate_caches()
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


print(interpreter_label())
print(f"{DEMO_SCALE=}  {os.process_cpu_count()=}  {multiprocessing.get_start_method()=}")
print(
    f"numpy: {'available' if HAS_NUMPY else 'missing'}, "
    f"subinterpreters: {'available' if HAS_INTERPRETERS else 'missing'}"
)
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 5.2 — Multiprocessing and Subinterpreters

            **Objectives**

            - Run CPU-bound Python in parallel with processes, and know what each one costs
              to start.
            - Pick a start method (`fork`, `spawn`, `forkserver`) and write code that works
              with all three, including from a notebook.
            - Use `Process`, `Pool` and `ProcessPoolExecutor`, and tune `chunksize`,
              `initializer` and `max_tasks_per_child`.
            - Know what can be pickled, what pickling costs, and when parallel code is slower
              than serial code.
            - Move data between processes with queues, pipes, shared values, managers and
              shared memory (with NumPy).
            - Use subinterpreters (`concurrent.interpreters`, `InterpreterPoolExecutor`):
              parallelism inside one process.
            - Choose a concurrency model with a decision matrix, Amdahl's law and a
              benchmark.

            **JS bridge**

            | Node | Python | The difference that bites |
            | --- | --- | --- |
            | `child_process.fork(file)` | `multiprocessing.Process(target=func)` | Python starts the child at a *function*, but that function must be importable by the child |
            | `cluster` (fork workers that share a port) | `ProcessPoolExecutor`, `multiprocessing.Pool` | pools hand out tasks; they do not share sockets |
            | `process.send` / `'message'` (JSON or structured clone over IPC) | `Queue`, `Pipe` (pickle over a pipe) | pickle can rebuild arbitrary classes, and cannot send lambdas, locks or open files |
            | `worker_threads` (isolate per thread, own heap) | subinterpreters: own GIL, own modules, one process | the closest match to a Worker |
            | `SharedArrayBuffer` + typed arrays | `multiprocessing.shared_memory` + NumPy arrays | you must `close()` and `unlink()` the block yourself |
            | `os.availableParallelism()` | `os.process_cpu_count()` (*new in 3.13*) | both respect CPU affinity |

            **How this unit runs.** A process started with `spawn` or `forkserver` is a
            fresh interpreter: it can only run a function it can **import**. Functions
            typed into a notebook cell live in the kernel's `__main__`, which a child cannot
            import (5.2.2 shows the failure). So each section first saves its worker
            functions to a small module under `notebooks/_scratch/phase5/` with
            `%%writefile`, then imports it with `fresh_import()`. Demos that need a clean
            parent process (start-method costs, the main guard, Ctrl+C handling) run as
            scripts in a child interpreter with `run_child()`.
            """
        ),
        md(
            """
            Unit setup, part 1: imports, `DEMO_SCALE`, the scratch folder (also put on
            `sys.path` so worker modules saved there are importable here and in every child
            process), feature flags for NumPy and subinterpreters, and the error and
            interpreter helpers.
            """
        ),
        code(UNIT_SETUP_SOURCE),
        md(
            """
            Unit setup, part 2: `Timer` (Unit 1.14), `run_child()` (Unit 5.1, now also
            hiding process ids) and `fresh_import(module_name)`, which re-imports a module
            from disk after a `%%writefile` cell has changed it.
            """
        ),
        code(UNIT_SETUP_SOURCE_2),
    ]


BASICS_WORKERS = '''
%%writefile _scratch/phase5/p5_basics.py
"""Worker functions for Units 5.2.1-5.2.4. Child processes import this module by name."""

import os
import sys
import time

ORDERS: list[str] = []  # module-level state: every process has its own copy
PRICE_TABLE: dict[str, float] = {}


def busy_sum(count: int) -> int:
    """Pure-Python CPU work (the same loop as Unit 5.1)."""
    return sum(number % 1000 for number in range(count))


def add_order(order_id: str) -> tuple[int, int]:
    """Append to this process's ORDERS; return (pid, number of orders it holds)."""
    ORDERS.append(order_id)
    return os.getpid(), len(ORDERS)


def square(number: int) -> int:
    """A tiny task."""
    return number * number


def power(base: int, exponent: int) -> int:
    """Two arguments, for starmap."""
    return base**exponent


def slow_square(number: int) -> int:
    """Square after a delay that makes later numbers finish first."""
    time.sleep(0.05 * (3 - number % 3))
    return number * number


def nap_then_exit(seconds: float, exit_code: int) -> None:
    """Sleep, then end the process with exit_code."""
    time.sleep(seconds)
    sys.exit(exit_code)


def load_price_table(gst_percent: float) -> None:
    """Pool initializer: runs once in each worker process."""
    PRICE_TABLE.update({"TEA-500": 240.0, "MUG-02": 199.0, "gst": gst_percent})
    PRICE_TABLE["loaded_by"] = os.getpid()


def price_with_gst(sku: str) -> tuple[str, float, bool]:
    """Use the table the initializer loaded in this worker."""
    total = round(PRICE_TABLE[sku] * (1 + PRICE_TABLE["gst"] / 100), 2)
    return sku, total, PRICE_TABLE["loaded_by"] == os.getpid()


def pid_after_nap(_: object) -> int:
    """Return the worker's pid after a short nap."""
    time.sleep(0.01)
    return os.getpid()


def silence_stderr() -> None:
    """Initializer that sends this worker's stderr to /dev/null (keeps one demo short)."""
    os.dup2(os.open(os.devnull, os.O_WRONLY), 2)
'''


def _process_cells() -> list[NotebookNode]:
    """5.2.1 Processes."""
    return [
        md(
            """
            ### 5.2.1 Processes

            A process has its **own address space** and runs its **own interpreter with its
            own GIL**. Nothing is shared by accident: no races on ordinary objects, and
            CPU-bound Python code really runs in parallel. The price: starting a process
            takes milliseconds, and every argument and result must be serialized (pickled)
            to cross the boundary.

            The worker module for 5.2.1–5.2.4. `%%writefile` saves the cell's text to a
            file instead of running it; the module-level `ORDERS` list will show that each
            process has its own copy of module state.
            """
        ),
        code(BASICS_WORKERS),
        md(
            """
            Import it. `fresh_import` re-reads the file, so editing and re-running the cell
            above always takes effect.
            """
        ),
        code(
            """
            p5_basics = fresh_import("p5_basics")
            print(f"{p5_basics.__name__} loaded; {p5_basics.square(12)=}")
            """
        ),
        md(
            """
            **Separate memory.** One worker process receives three orders; each call
            appends to *its* `ORDERS`. The parent's `p5_basics.ORDERS` never changes, and
            the worker's process id differs from the kernel's.
            """
        ),
        code(
            """
            with concurrent.futures.ProcessPoolExecutor(max_workers=1) as one_worker:
                replies = list(one_worker.map(p5_basics.add_order, ["A-1", "A-2", "A-3"]))
            worker_pids = {pid for pid, _ in replies}
            print(f"worker saw order counts {[count for _, count in replies]}")
            print(f"worker pid differs from the kernel's: {worker_pids != {os.getpid()}}")
            print(f"the kernel's p5_basics.ORDERS: {p5_basics.ORDERS}")
            """
        ),
        md(
            """
            **Separate GILs.** The 5.1.3 benchmark again: the same total `busy_sum` work,
            now split across 1 and 4 *processes*. Each process has its own GIL, so on a
            machine with at least 4 cores this should approach 4× (minus start-up and
            pickling).
            """
        ),
        code(
            """
            total_numbers = 16_000_000 * DEMO_SCALE
            with Timer("1 process (this kernel)") as serial_run:
                p5_basics.busy_sum(total_numbers)
            with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
                with Timer("4 worker processes, including pool start-up") as parallel_run:
                    list(pool.map(p5_basics.busy_sum, [total_numbers // 4] * 4))
            print(
                f"[{interpreter_label()}] speedup "
                f"{serial_run.elapsed_seconds / parallel_run.elapsed_seconds:.2f}x"
            )
            """
        ),
        md(
            """
            **Creation cost.** How long does it take to start a process and wait for it to
            finish, for each start method (explained in 5.2.2), compared with a thread? The
            measurement runs as a script in a fresh child interpreter, because `fork` from
            this multi-threaded kernel would be unsafe (5.2.2 shows why).
            """
        ),
        code(
            '''
            CREATION_COST = """
                import multiprocessing, threading, time

                def do_nothing():
                    pass

                def average_ms(start_one, repeats=5):
                    start = time.perf_counter()
                    for _ in range(repeats):
                        start_one()
                    return (time.perf_counter() - start) / repeats * 1000

                def thread_once():
                    worker = threading.Thread(target=do_nothing)
                    worker.start()
                    worker.join()

                if __name__ == "__main__":
                    print(f"{'thread':<11} {average_ms(thread_once):8.3f} ms")
                    for method in multiprocessing.get_all_start_methods():
                        context = multiprocessing.get_context(method)

                        def process_once():
                            child = context.Process(target=do_nothing)
                            child.start()
                            child.join()

                        process_once()  # warm-up (starts the fork server once)
                        print(f"{method:<11} {average_ms(process_once):8.3f} ms")
            """
            print(f"[{interpreter_label()}] start + join, average of 5 (varies by machine):")
            print(run_child(CREATION_COST))
            '''
        ),
        md(
            """
            A thread costs tens of microseconds. `fork` copies the parent (cheap thanks to
            copy-on-write pages) and costs about a millisecond; `forkserver` forks from a
            small, already-running server process; `spawn` starts a whole new interpreter
            and re-imports modules, the slowest. That is why you **reuse** processes in a
            pool instead of starting one per task.
            """
        ),
    ]


def _start_method_cells() -> list[NotebookNode]:
    """5.2.2 Start methods."""
    return [
        md(
            """
            ### 5.2.2 Start methods

            | Method | How the child starts | Speed | Safe with threads in the parent? | Default on |
            | --- | --- | --- | --- | --- |
            | `fork` | `os.fork()`: a copy of the parent, mid-program, with all its memory | fastest | **no**: locks held by other threads are copied in their locked state | nothing since 3.14 (was Linux/POSIX until 3.13) |
            | `spawn` | a fresh interpreter that imports the parent's `__main__` module, then unpickles the target | slowest | yes | Windows, macOS (since 3.8) |
            | `forkserver` | a single-threaded server process, started once, forks a child for each request | fast after the first | yes | **POSIX except macOS, since 3.14** |

            Query and choose with `get_start_method()`, `get_all_start_methods()` and
            `get_context(method)`, which returns an object with the whole `multiprocessing`
            API bound to that method. Prefer a context over `set_start_method()`, which may
            be called only once per program.
            """
        ),
        code(
            """
            print(f"{multiprocessing.get_start_method()=}")
            print(f"{multiprocessing.get_all_start_methods()=}")
            spawn_context = multiprocessing.get_context("spawn")
            with concurrent.futures.ProcessPoolExecutor(max_workers=1, mp_context=spawn_context) as spawn_pool:
                print(f"spawn pool: {spawn_pool.submit(p5_basics.square, 9).result()=}")
            print(f"{spawn_context.Process.__name__=}")
            """
        ),
        md(
            """
            **Why `fork` and threads do not mix.** `fork()` copies only the calling thread.
            If another thread held a lock at that moment, the child gets the lock in its
            locked state and nobody left to release it. Python warns
            (`DeprecationWarning: This process ... is multi-threaded, use of fork() may lead
            to deadlocks`). The script below makes it happen: a thread holds a lock, the
            main thread forks, and the child tries the lock with a timeout.
            """
        ),
        code(
            '''
            FORK_WITH_THREADS = """
                import multiprocessing, threading, time, warnings

                warnings.simplefilter("always")  # show the DeprecationWarning
                inventory_lock = threading.Lock()

                def hold_lock():
                    with inventory_lock:
                        time.sleep(1)

                def child_wants_lock():
                    got_it = inventory_lock.acquire(timeout=0.5)
                    print(f"child: acquired the lock copied from the parent: {got_it}")

                if __name__ == "__main__":
                    threading.Thread(target=hold_lock).start()
                    time.sleep(0.05)  # the other thread now holds the lock
                    child = multiprocessing.get_context("fork").Process(target=child_wants_lock)
                    child.start()
                    child.join()
            """
            if "fork" in multiprocessing.get_all_start_methods():
                print(run_child(FORK_WITH_THREADS))
            else:
                print("SKIP: fork is not available on this platform")
            '''
        ),
        md(
            """
            The child waits half a second and gives up: the lock will never be released in
            its copy of the world. Real programs deadlock this way inside `logging`,
            `malloc` or a database driver. A notebook kernel always runs extra threads,
            which is one reason `forkserver` became the default.

            **The main guard.** With `spawn` and `forkserver`, the child imports the
            parent's main module (as `__mp_main__`) to find the target function. Without an
            `if __name__ == "__main__":` guard, that import runs the process-starting code
            again inside the child, and `multiprocessing` stops it with a `RuntimeError`.
            The output is trimmed to the last lines.
            """
        ),
        code(
            '''
            NO_GUARD = """
                import multiprocessing

                def greet():
                    print("hello from the child")

                context = multiprocessing.get_context("spawn")
                child = context.Process(target=greet)
                child.start()
                child.join()
                print(f"parent: child exit code {child.exitcode}")
            """
            WITH_GUARD = """
                import multiprocessing

                def greet():
                    print("hello from the child")

                if __name__ == "__main__":
                    context = multiprocessing.get_context("spawn")
                    child = context.Process(target=greet)
                    child.start()
                    child.join()
                    print(f"parent: child exit code {child.exitcode}")
            """
            print("--- without the guard (key lines of the output)")
            key_phrases = ("RuntimeError", "bootstrapping phase", "if __name__", "parent:")
            for line in run_child(NO_GUARD).splitlines():
                if any(phrase in line for phrase in key_phrases):
                    print(line.strip())
            print("--- with the guard")
            print(run_child(WITH_GUARD))
            '''
        ),
        md(
            """
            #### Notebook caveat: worker functions must live in importable modules

            Functions are pickled **by reference**: the pickle stores the module name and
            the function name, never the code. A function typed into a notebook cell
            belongs to the kernel's `__main__` module. A child interpreter's `__main__` is a
            different module, so the lookup fails. First the mechanism, by hand: pickle a
            notebook function and try to load it in a fresh interpreter.
            """
        ),
        code(
            '''
            def tax_for(amount: float) -> float:
                """Defined in a notebook cell, so it belongs to the kernel's __main__ module."""
                return round(amount * 0.18, 2)


            payload = pickle.dumps(tax_for)
            print(
                "the pickle names the function: "
                f"{b'__main__' in payload and b'tax_for' in payload}, {len(payload)} bytes"
            )
            loader = subprocess.run(
                [sys.executable, "-c", "import pickle, sys; pickle.loads(sys.stdin.buffer.read())"],
                input=payload, capture_output=True, env=CHILD_ENV,
            )  # fmt: skip
            print(f"loading it in a fresh interpreter: {loader.stderr.decode().strip().splitlines()[-1]}")
            '''
        ),
        md(
            """
            A process pool hits exactly that error inside the worker, which then dies, and
            the pool reports `BrokenProcessPool`. (The `silence_stderr` initializer hides
            the worker's own traceback to keep the output short.) The same call with the
            function from the importable `p5_basics` module works.
            """
        ),
        code(
            """
            with concurrent.futures.ProcessPoolExecutor(
                max_workers=1, initializer=p5_basics.silence_stderr
            ) as pool:
                print(
                    "notebook function: "
                    f"{raised_message(lambda: pool.submit(tax_for, 100.0).result(timeout=60))}"
                )
            with concurrent.futures.ProcessPoolExecutor(max_workers=1) as pool:
                print(f"module function:   {pool.submit(p5_basics.square, 100).result()=}")
            """
        ),
        md(
            """
            | Option | Works because | Trade-off |
            | --- | --- | --- |
            | Save workers to a module (`%%writefile`, or a real `.py` file in your project) and import it | the child imports the module by name | the approach used in this phase |
            | Run the code as a script (`python script.py`) | the child imports the script as `__mp_main__`; it needs the main guard | not interactive |
            | `get_context("fork")` | the child is a copy of the kernel, function included | unsafe with the kernel's threads (above); not on Windows |
            | Third-party pickling (`cloudpickle`, used by Dask, Ray, joblib) | pickles functions by value | an extra dependency |
            """
        ),
    ]


def _process_api_cells() -> list[NotebookNode]:
    """5.2.3 Process APIs."""
    return [
        md(
            """
            ### 5.2.3 Process APIs

            #### `Process`

            `multiprocessing.Process` mirrors `threading.Thread` (`target`, `args`, `name`,
            `daemon`, `start`, `join`, `is_alive`) and adds process controls:

            | Attribute / method | Meaning |
            | --- | --- |
            | `pid` | the OS process id (after `start()`) |
            | `exitcode` | `None` while running, `0` on success, `n` after `sys.exit(n)`, `-signal` if killed by a signal |
            | `terminate()` / `kill()` | send `SIGTERM` / `SIGKILL` (no `finally` blocks run in the child) |
            | `interrupt()` | send `SIGINT`, so the child gets `KeyboardInterrupt` (*new in 3.14*) |
            | `close()` | release the `Process` object's resources once it has finished |

            Three children: one exits normally, one calls `sys.exit(3)`, one is terminated
            while it sleeps.
            """
        ),
        code(
            """
            children = {
                "finishes": multiprocessing.Process(
                    target=p5_basics.nap_then_exit, args=(0.05, 0), name="finishes"
                ),
                "exits with 3": multiprocessing.Process(target=p5_basics.nap_then_exit, args=(0.05, 3)),
                "terminated": multiprocessing.Process(target=p5_basics.nap_then_exit, args=(10, 0)),
            }
            for child in children.values():
                child.start()
            print(
                f"right after start: exitcode={children['finishes'].exitcode}, "
                f"has pid={children['finishes'].pid is not None}"
            )
            children["terminated"].terminate()
            for label, child in children.items():
                child.join()
                print(f"{label:<13} exitcode={child.exitcode:>4}  alive={child.is_alive()}")
                child.close()
            print(f"-signal.SIGTERM = {-signal.SIGTERM}")
            """
        ),
        md(
            """
            #### `Pool`

            `multiprocessing.Pool(processes)` is the original pool API:

            | Method | Returns | Order |
            | --- | --- | --- |
            | `map(func, iterable, chunksize)` | a list | input order |
            | `imap(func, iterable, chunksize)` | a lazy iterator | input order |
            | `imap_unordered(func, iterable, chunksize)` | a lazy iterator | **completion** order |
            | `starmap(func, iterable_of_tuples)` | a list of `func(*args)` | input order |
            | `apply_async`, `map_async` | `AsyncResult` objects | — |

            > **Warning:** `Pool.__exit__` calls `terminate()`, not `close()` + `join()`.
            > Collect every result *inside* the `with` block.
            """
        ),
        code(
            """
            with multiprocessing.Pool(processes=3) as pool:
                print(f"map:            {pool.map(p5_basics.slow_square, range(6))}")
                print(f"imap_unordered: {list(pool.imap_unordered(p5_basics.slow_square, range(6)))}")
                print(f"starmap:        {pool.starmap(p5_basics.power, [(2, 10), (3, 4), (10, 3)])}")
            """
        ),
        md(
            """
            `slow_square` sleeps longer for numbers divisible by 3, so `imap_unordered`
            yields them last (the exact order can vary slightly between runs).

            **`chunksize`.** Each task is pickled and sent through a pipe; `chunksize=n`
            sends `n` items per message, so the per-message overhead is paid once per chunk.
            For many tiny tasks that is the difference between slow and fast. (Lab 5.2
            draws the full curve.)
            """
        ),
        code(
            """
            tiny_items = range(20_000 * DEMO_SCALE)
            with multiprocessing.Pool(processes=4) as pool:
                pool.map(p5_basics.square, range(8))  # start the workers before timing
                for chunk_size in (1, 2_000):
                    with Timer(f"Pool.map of {len(tiny_items):,} tiny tasks, chunksize={chunk_size:>5}"):
                        pool.map(p5_basics.square, tiny_items, chunksize=chunk_size)
            """
        ),
        md(
            """
            #### `ProcessPoolExecutor`

            The `concurrent.futures` version: the same `submit` / `map` / `Future` API as
            `ThreadPoolExecutor` (5.1.8), plus process-specific options:

            | Option | Effect |
            | --- | --- |
            | `max_workers` | defaults to `os.process_cpu_count()` |
            | `mp_context` | a start-method context (`get_context("spawn")`) |
            | `initializer`, `initargs` | a function run once in each new worker (load a model, open a connection, set up logging) |
            | `max_tasks_per_child` | replace a worker after it has run `n` tasks (contains memory leaks in long-running pools; *new in 3.11*) |
            | `map(..., chunksize=n)` | the same batching as `Pool.map` |
            | `terminate_workers()`, `kill_workers()` | stop all workers now (*new in 3.14*) |

            **`initializer`.** Each worker loads the price table once; every task then uses
            the worker's own copy. The third field shows the table was loaded in the same
            process that ran the task.
            """
        ),
        code(
            """
            with concurrent.futures.ProcessPoolExecutor(
                max_workers=2, initializer=p5_basics.load_price_table, initargs=(18.0,)
            ) as pool:
                for sku, price_with_tax, loaded_here in pool.map(
                    p5_basics.price_with_gst, ["TEA-500", "MUG-02", "TEA-500"]
                ):
                    print(f"{sku:<8} ₹{price_with_tax:>7.2f}  table loaded in this worker: {loaded_here}")
            print(f"the kernel's PRICE_TABLE stays empty: {p5_basics.PRICE_TABLE}")
            """
        ),
        md(
            """
            **`max_tasks_per_child`.** With one worker and a limit of 2 tasks, six tasks run
            in three different processes.
            """
        ),
        code(
            """
            with concurrent.futures.ProcessPoolExecutor(max_workers=1, max_tasks_per_child=2) as pool:
                task_pids = list(pool.map(p5_basics.pid_after_nap, range(6)))
            print(f"distinct worker processes for 6 tasks: {len(set(task_pids))}")
            print(
                "pattern (same letter = same process): "
                f"{''.join(chr(65 + sorted(set(task_pids)).index(pid)) for pid in task_pids)}"
            )
            """
        ),
    ]


def _data_transfer_cells() -> list[NotebookNode]:
    """5.2.4 Data transfer."""
    return [
        md(
            """
            ### 5.2.4 Data transfer

            Every argument, return value and exception that crosses a process boundary is
            **pickled** in the sender and unpickled in the receiver (Unit 4.5 covered
            `pickle`). Two consequences: some objects cannot cross at all, and big objects
            are expensive to send.

            **Pickling constraints.**

            | Can be pickled | Cannot be pickled |
            | --- | --- |
            | `None`, numbers, strings, bytes, tuples, lists, dicts, sets of picklable items | lambdas and functions defined inside functions |
            | module-level functions and classes (by reference: module + name) | open files, sockets, database connections |
            | instances of module-level classes (dataclasses included) | locks, threads, generators, coroutines |
            | `functools.partial` of a module-level function | functions in the notebook's `__main__` (they pickle, but a child cannot load them: 5.2.2) |
            """
        ),
        code(
            '''
            def make_discount(percent: int) -> Callable[[float], float]:
                """Return a nested function (not picklable)."""

                def apply(amount: float) -> float:
                    return amount * (100 - percent) / 100

                return apply


            candidates = {
                "tuple of numbers and text": ("TEA-500", 2, 240.0),
                "module-level function": p5_basics.square,
                "functools.partial(p5_basics.power, 2)": functools.partial(p5_basics.power, 2),
                "lambda": lambda amount: amount * 2,
                "nested function": make_discount(10),
                "threading.Lock()": threading.Lock(),
                "generator": (number for number in range(3)),
                "open file": open(os.devnull),
            }


            def pickle_outcome(candidate: object) -> str:
                """ "OK" if candidate pickles, else the error."""
                return raised_message(lambda: pickle.dumps(candidate)).replace("no error", "OK")


            for label, candidate in candidates.items():
                print(f"{label:<40} {pickle_outcome(candidate)}")
            candidates["open file"].close()
            '''
        ),
        md(
            """
            #### Under the hood: what a pickled function contains

            `pickletools.dis` disassembles a pickle. A function is just two strings, its
            module and its name, plus `STACK_GLOBAL` ("import this and look it up"). The
            code itself is never sent: the receiver must be able to import it.
            """
        ),
        code(
            """
            os.environ["PYTHON_COLORS"] = "0"  # the kernel sets FORCE_COLOR=1; this wins over it
            try:
                pickletools.dis(pickle.dumps(p5_basics.square))
            finally:
                del os.environ["PYTHON_COLORS"]
            """
        ),
        md(
            """
            **Pickling cost.** A list of a million integers: `sys.getsizeof` counts only
            the list's pointer array, the pickle holds every value, and sending it to a
            worker means pickle → pipe → unpickle (and the same back for the result).
            """
        ),
        code(
            """
            order_ids = list(range(1_000_000 * DEMO_SCALE))
            with Timer("pickle.dumps(1M ints)"):
                order_payload = pickle.dumps(order_ids)
            with Timer("pickle.loads(1M ints)"):
                pickle.loads(order_payload)
            print(
                f"sys.getsizeof(list): {sys.getsizeof(order_ids) / 1e6:.1f} "
                f"MB, pickle: {len(order_payload) / 1e6:.1f} MB"
            )

            with concurrent.futures.ProcessPoolExecutor(max_workers=1) as pool:
                pool.submit(len, []).result()  # start the worker before timing
                with Timer("len() of the list in a worker (send 1M ints)"):
                    pool.submit(len, order_ids).result()
            with Timer("len() of the list in the kernel"):
                len(order_ids)
            """
        ),
        md(
            """
            **When parallel is slower.** Squaring a number takes about 30 ns; sending it to
            a worker and getting the answer back takes tens of microseconds. With tiny
            tasks the pool spends its time on overhead, and even large chunks only pay off
            when the work per item outweighs pickling it.
            """
        ),
        code(
            """
            numbers = list(range(200_000 * DEMO_SCALE))
            with Timer("sequential, in the kernel"):
                [p5_basics.square(number) for number in numbers]
            with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
                list(pool.map(p5_basics.square, range(8)))  # start the workers
                with Timer("4 processes, chunksize=1 (only the first 10% of the items!)"):
                    list(pool.map(p5_basics.square, numbers[: len(numbers) // 10]))
                with Timer("4 processes, chunksize=10_000"):
                    list(pool.map(p5_basics.square, numbers, chunksize=10_000))
            """
        ),
        md(
            """
            Both parallel versions lose. Rules of thumb:

            - Make each task **coarse**: seconds of work, not microseconds (batch items, or
              use `chunksize`).
            - **Send little, compute a lot**: pass a file name or a row range, not the data;
              return a summary, not every intermediate value.
            - For big arrays, share memory instead of pickling (5.2.5).
            - Measure. A parallel version that is not faster is pure complexity.
            """
        ),
    ]


IPC_WORKERS = '''
%%writefile _scratch/phase5/p5_ipc.py
"""Worker functions for Unit 5.2.5 (inter-process communication)."""

import os
from multiprocessing import shared_memory


def produce_orders(order_queue, count: int) -> None:
    """Put count orders on a multiprocessing.Queue, then a None sentinel."""
    for number in range(1, count + 1):
        order_queue.put({"order_id": number, "producer_pid": os.getpid()})
    order_queue.put(None)


def price_service(connection) -> None:
    """Answer price requests over one end of a Pipe until told to stop."""
    prices = {"TEA-500": 240.0, "MUG-02": 199.0}
    while (request := connection.recv()) != "stop":
        connection.send({"sku": request, "price": prices.get(request)})
    connection.close()


def add_visits(counter, times: int, use_lock: bool) -> None:
    """Increment a shared multiprocessing.Value, with or without its lock."""
    for _ in range(times):
        if use_lock:
            with counter.get_lock():
                counter.value += 1
        else:
            counter.value += 1  # read and write are separate steps: updates get lost


def fill_squares(shared_array, start: int, stop: int) -> None:
    """Write index squared into a slice of a shared multiprocessing.Array."""
    for index in range(start, stop):
        shared_array[index] = index * index


def record_stock(stock, log, sku: str, quantity: int) -> None:
    """Write through Manager proxies (a dict and a list)."""
    stock[sku] = quantity
    log.append(f"set {sku}")


def square_in_place(block_name: str, length: int) -> None:
    """Attach to a shared float64 block by name and square every value in place."""
    import numpy as np

    block = shared_memory.SharedMemory(name=block_name, track=False)
    try:
        values = np.ndarray((length,), dtype=np.float64, buffer=block.buf)
        values **= 2
        del values  # drop the view before closing the block
    finally:
        block.close()
'''


def _ipc_cells() -> list[NotebookNode]:
    """5.2.5 IPC."""
    return [
        md(
            """
            ### 5.2.5 IPC

            | Tool | What it is | Use it for |
            | --- | --- | --- |
            | `multiprocessing.Queue` | many-to-many FIFO; items are pickled and sent by a background feeder thread | work and result streams |
            | `Pipe(duplex=True)` | two `Connection` ends; `send` / `recv` pickled objects | a conversation between exactly two processes |
            | `Value(typecode, initial)`, `Array(typecode, size)` | a C value / array in shared memory, with an optional lock | counters, small numeric buffers |
            | `Manager()` | a server process holding real Python objects; others get **proxies** | shared dicts and lists (slow: every access is a round trip) |
            | `shared_memory.SharedMemory` | a named block of raw shared memory | large arrays without copying (with NumPy) |

            The worker module for this section:
            """
        ),
        code(IPC_WORKERS),
        md("Import it:"),
        code(
            """
            p5_ipc = fresh_import("p5_ipc")
            print(f"{p5_ipc.__name__} loaded")
            """
        ),
        md(
            """
            **`Queue`.** A producer process puts five orders and a `None` sentinel; the
            parent reads until the sentinel (the same pattern as 5.1.6, across processes).
            """
        ),
        code(
            """
            order_queue = multiprocessing.Queue()
            producer = multiprocessing.Process(target=p5_ipc.produce_orders, args=(order_queue, 5))
            producer.start()
            received = []
            while (order := order_queue.get(timeout=30)) is not None:
                received.append(order)
            producer.join()
            print(f"received order ids {[order['order_id'] for order in received]}")
            print(f"all from the producer process: {len({order['producer_pid'] for order in received}) == 1}")
            """
        ),
        md(
            """
            **`Pipe`.** A two-way channel: the parent asks a price service in another
            process and gets answers back. `poll(timeout)` checks whether a message is
            waiting.
            """
        ),
        code(
            """
            parent_end, child_end = multiprocessing.Pipe()
            service = multiprocessing.Process(target=p5_ipc.price_service, args=(child_end,))
            service.start()
            for sku in ("TEA-500", "SPOON-1"):
                parent_end.send(sku)
                print(f"asked {sku}: {parent_end.recv()}")
            print(f"anything else waiting? {parent_end.poll(timeout=0.05)}")
            parent_end.send("stop")
            service.join()
            print(f"service exit code: {service.exitcode}")
            """
        ),
        md(
            """
            **`Value` and `Array`.** Shared C storage. `Value` comes with a lock, but
            `counter.value += 1` is still a read followed by a write: the 5.1.4 race, now
            between processes. Wrap it in `with counter.get_lock():`. `Array` slices can be
            filled by different processes without a lock when they do not overlap.
            """
        ),
        code(
            """
            for use_lock in (False, True):
                visits = multiprocessing.Value("i", 0)
                workers = [
                    multiprocessing.Process(target=p5_ipc.add_visits, args=(visits, 5_000, use_lock))
                    for _ in range(4)
                ]
                for worker in workers:
                    worker.start()
                for worker in workers:
                    worker.join()
                print(f"use_lock={use_lock!s:<5}: expected 20,000 visits, got {visits.value:,}")

            squares = multiprocessing.Array("q", 8)  # 8 signed 64-bit integers, zeroed
            halves = [
                multiprocessing.Process(target=p5_ipc.fill_squares, args=(squares, start, start + 4))
                for start in (0, 4)
            ]
            for half in halves:
                half.start()
            for half in halves:
                half.join()
            print(f"Array filled by two processes: {list(squares)}")
            """
        ),
        md(
            """
            **`Manager`.** A manager runs a server process that owns ordinary Python
            objects; other processes get proxies that forward every operation to it. That
            makes it flexible (any picklable values, nested structures) and slow. The timing
            compares 1 000 writes to a managed dict with 1 000 writes to a plain dict.
            """
        ),
        code(
            """
            with multiprocessing.Manager() as manager:
                stock, change_log = manager.dict(), manager.list()
                writers = [
                    multiprocessing.Process(target=p5_ipc.record_stock, args=(stock, change_log, sku, quantity))
                    for sku, quantity in (("TEA-500", 40), ("MUG-02", 12))
                ]
                for writer in writers:
                    writer.start()
                for writer in writers:
                    writer.join()
                print(f"stock={dict(sorted(stock.items()))}, log={sorted(change_log)}")
                with Timer("1,000 writes to a Manager dict (a round trip each)"):
                    for number in range(1_000):
                        stock[f"sku-{number}"] = number
            plain_dict: dict[str, int] = {}
            with Timer("1,000 writes to a plain dict"):
                for number in range(1_000):
                    plain_dict[f"sku-{number}"] = number
            """
        ),
        md(
            """
            #### `shared_memory` with NumPy

            `SharedMemory(create=True, size=n)` allocates a named block that any process
            can attach to by name. Wrapping its buffer in a NumPy array gives both processes
            a view of the **same bytes**: nothing is pickled except the block's name. The
            owner must `close()` its view and `unlink()` the block when done (otherwise the
            memory stays allocated until reboot on some systems). The worker attaches with
            `track=False` (*new in 3.13*) so only the owner's resource tracker manages the
            block.
            """
        ),
        code(
            """
            if not HAS_NUMPY:
                print("SKIP: numpy is not installed")
            else:
                import numpy as np

                readings = np.arange(1.0, 9.0)  # 8 float64 values
                block = shared_memory.SharedMemory(create=True, size=readings.nbytes)
                try:
                    shared_readings = np.ndarray(readings.shape, dtype=np.float64, buffer=block.buf)
                    shared_readings[:] = readings
                    squarer = multiprocessing.Process(
                        target=p5_ipc.square_in_place, args=(block.name, len(readings))
                    )
                    squarer.start()
                    squarer.join()
                    print(f"after the child squared them: {shared_readings.tolist()}")
                    print(
                        f"sent to the child: the name {block.name!r:.12}... "
                        f"({len(pickle.dumps(block.name))} bytes pickled)"
                    )
                    print(f"pickling the array instead would send {len(pickle.dumps(readings))} bytes")
                    del shared_readings  # release the view before closing
                finally:
                    block.close()
                    block.unlink()
            """
        ),
        md(
            """
            Eight floats is a toy; the same code with 100 million floats still sends only
            the name. Lab 5.2 splits one shared array across several workers.
            """
        ),
    ]


def _subinterpreter_cells() -> list[NotebookNode]:
    """5.2.6 Subinterpreters."""
    return [
        md(
            """
            ### 5.2.6 Subinterpreters

            A **subinterpreter** is a second, isolated Python interpreter inside the *same
            process*: its own modules, its own `sys`, its own `__main__`, and (since
            [PEP 684](https://peps.python.org/pep-0684/), 3.12) **its own GIL**. So several
            interpreters can run Python bytecode in parallel on different threads, with
            process-like isolation and thread-like start-up cost.

            | | |
            | --- | --- |
            | [PEP 734](https://peps.python.org/pep-0734/) | `concurrent.interpreters` in the standard library (*new in 3.14*) |
            | `interpreters.create()` | a new interpreter; `close()` it when done |
            | `interp.exec(source)` | run code in its `__main__`; errors come back as `ExecutionFailed` |
            | `interp.call(func, *args)` | call a function there and return its result |
            | `interp.call_in_thread(func, *args)` | the same in a new thread (returns the `Thread`) |
            | `interp.prepare_main(name=value)` | bind shareable objects in its `__main__` |
            | `interpreters.create_queue()` | a queue that works across interpreters |
            | `interpreters.is_shareable(obj)` | `None`, `bool`, numbers, `str`, `bytes`, tuples of those, queues |
            | `InterpreterPoolExecutor` | `concurrent.futures` pool of interpreters (*new in 3.14*) |

            > **Note:** output printed *inside* a subinterpreter goes to the process's real
            > stdout, which the notebook does not show. The demos send results back through
            > return values and queues instead.

            **Basics.** Create an interpreter, pass it a queue, let it report its id, call
            a function in it, and show that changing `sys` there does not affect the main
            interpreter.
            """
        ),
        code(
            """
            if not HAS_INTERPRETERS:
                print("SKIP: concurrent.interpreters is not available (new in 3.14)")
            else:
                from concurrent import interpreters

                worker_interpreter = interpreters.create()
                try:
                    reports = interpreters.create_queue()
                    worker_interpreter.prepare_main(reports=reports, greeting="namaste")
                    worker_interpreter.exec(
                        "from concurrent import interpreters as i; import sys; "
                        "sys.course_marker = True; reports.put((greeting, i.get_current().id))"
                    )
                    print(f"from the subinterpreter: {reports.get(timeout=10)}")
                    print(f"main interpreter id: {interpreters.get_main().id}")
                    print(f"call(len, 'namaste') = {worker_interpreter.call(len, 'namaste')}")
                    print(f"main interpreter sees sys.course_marker: {hasattr(sys, 'course_marker')}")
                    print(f"interpreters alive: {len(interpreters.list_all())}")
                    samples = (42, "text", (1, 2), [1, 2], {"a": 1})
                    shareable = {repr(value): interpreters.is_shareable(value) for value in samples}
                    print(f"is_shareable: {shareable}")
                finally:
                    worker_interpreter.close()
            """
        ),
        md(
            """
            **A subinterpreter has its own `sys.path`.** It starts with the default search
            path (the working directory and the standard library), not the kernel's
            modified `sys.path`, so our scratch folder is missing. Callables and arguments
            are passed as shareable objects or pickled, and a function pickled by reference
            must be importable *inside the subinterpreter*. The fix is a tiny function that
            uses only built-ins, run once in each new interpreter: here with `call`, in a
            pool as the `initializer`.
            """
        ),
        code(
            """
            def add_to_sys_path(folder: str) -> None:
                \"\"\"Initializer for a fresh subinterpreter: make `folder` importable there.\"\"\"
                import sys

                if folder not in sys.path:
                    sys.path.insert(0, folder)


            if not HAS_INTERPRETERS:
                print("SKIP: concurrent.interpreters is not available (new in 3.14)")
            else:
                path_test = interpreters.create()
                try:
                    try:
                        path_test.call(p5_basics.pid_after_nap, None)
                    except interpreters.NotShareableError as error:
                        cause = str(error.__cause__).splitlines()[0]
                        print(f"before: {type(error).__name__}: {error} ({cause})")
                    path_test.call(add_to_sys_path, str(PHASE5_DIR))
                    same_process = path_test.call(p5_basics.pid_after_nap, None) == os.getpid()
                    print(f"after add_to_sys_path: it runs, in the kernel's own process: {same_process}")
                finally:
                    path_test.close()
            """
        ),
        md(
            """
            **One GIL per interpreter.** The same four `busy_sum` jobs on a pool of four
            threads (one shared GIL) and on a pool of four interpreters (four GILs, each
            interpreter initialized with `add_to_sys_path`). Unlike processes, the
            interpreter pool starts in milliseconds and stays in one process.
            """
        ),
        code(
            """
            if not HAS_INTERPRETERS:
                print("SKIP: concurrent.interpreters is not available (new in 3.14)")
            else:
                jobs = [4_000_000 * DEMO_SCALE] * 4
                print(f"[{interpreter_label()}] 4 x busy_sum({jobs[0]:,})")
                pools = {
                    "ThreadPoolExecutor": lambda: concurrent.futures.ThreadPoolExecutor(max_workers=4),
                    "InterpreterPoolExecutor": lambda: concurrent.futures.InterpreterPoolExecutor(
                        max_workers=4, initializer=add_to_sys_path, initargs=(str(PHASE5_DIR),)
                    ),
                }
                for pool_name, make_pool in pools.items():
                    with make_pool() as pool:
                        list(pool.map(p5_basics.busy_sum, [10] * 4))  # start the workers
                        with Timer(f"{pool_name:<24}"):
                            list(pool.map(p5_basics.busy_sum, jobs))
                with Timer("create + close one interpreter", report=None) as interpreter_cost:
                    interpreters.create().close()
                print(f"create + close one interpreter: {interpreter_cost.elapsed_seconds * 1000:.1f} ms")
            """
        ),
        md(
            """
            **Compatibility.** Every C extension imported in a subinterpreter must support
            multi-phase initialization and a per-interpreter GIL. Most of the standard
            library does; many third-party extensions do not yet. NumPy, for example,
            refuses to load:
            """
        ),
        code(
            """
            if not HAS_INTERPRETERS or not HAS_NUMPY:
                print("SKIP: needs both concurrent.interpreters and numpy")
            else:
                numpy_test = interpreters.create()
                try:
                    numpy_test.exec("import numpy")
                    print("numpy imported in a subinterpreter")
                except interpreters.ExecutionFailed as failure:
                    first_sentence = next(line for line in failure.excinfo.msg.splitlines() if line.strip())
                    print(f"ExecutionFailed wrapping {failure.excinfo.type.__name__}: {first_sentence}")
                finally:
                    numpy_test.close()
            """
        ),
        md(
            """
            | | Threads | Subinterpreters | Processes |
            | --- | --- | --- | --- |
            | Parallel Python bytecode | no (default build) | yes | yes |
            | Isolation | none | modules, globals, `sys` | everything (address space) |
            | Start-up | ~10 µs | ~ms | ~ms to tens of ms |
            | Passing data | shared objects | shareable values, queues, pickling | pickling, shared memory |
            | C extensions | all | only those that support it | all |
            | A crash (segfault) takes down | the process | the process | only that worker |
            """
        ),
    ]


PATTERN_WORKERS = '''
%%writefile _scratch/phase5/p5_patterns.py
"""Worker functions for Units 5.2.7-5.2.8."""

import time
from collections import Counter

from p5_basics import busy_sum  # noqa: F401  (re-exported for the benchmark)


def wait_for_io(seconds: float) -> float:
    """Stand-in for a network call: the worker just waits."""
    time.sleep(seconds)
    return seconds


def revenue_by_city(records: list[tuple[str, int]]) -> Counter[str]:
    """Map step: total revenue per city in one chunk of sales records."""
    totals: Counter[str] = Counter()
    for city, amount in records:
        totals[city] += amount
    return totals
'''


def _choosing_cells() -> list[NotebookNode]:
    """5.2.7 Choosing a model."""
    return [
        md(
            """
            ### 5.2.7 Choosing a model

            **Decision matrix.**

            | Workload | Threads | Processes | Subinterpreters | asyncio (5.3–5.4) | Free-threaded threads |
            | --- | --- | --- | --- | --- | --- |
            | Many network calls (HTTP, DB) | good up to hundreds | wasteful | wasteful | **best** for thousands | good |
            | Blocking library with no async API | **best** | works | depends on C extensions | via `to_thread` | good |
            | CPU-bound pure Python | useless (GIL) | **best default** | good if extensions allow | useless | **good** |
            | CPU-bound in NumPy / hashlib / zlib | **good** (they release the GIL) | works, pays pickling | NumPy not supported yet | via `to_thread` | good |
            | Large shared in-memory data, CPU-bound | GIL-bound | shared memory only | shareable values only | — | **best** |
            | Isolation from crashes and leaks | none | **best** (`max_tasks_per_child`) | partial | none | none |

            The worker module for the last two sections:
            """
        ),
        code(PATTERN_WORKERS),
        md("Import it:"),
        code(
            """
            p5_patterns = fresh_import("p5_patterns")
            print(f"{p5_patterns.__name__} loaded")
            """
        ),
        md(
            """
            **Justify it with a benchmark.** The same two jobs on every model: CPU-bound
            (8 × `busy_sum`) and I/O-bound (8 × a 0.1 s wait), with 4 workers each. One
            table, measured on this machine.
            """
        ),
        code(
            """
            cpu_jobs, io_jobs = [3_000_000 * DEMO_SCALE] * 8, [0.1] * 8
            executors: dict[str, Callable[[], concurrent.futures.Executor]] = {
                "threads": lambda: concurrent.futures.ThreadPoolExecutor(4),
                "processes": lambda: concurrent.futures.ProcessPoolExecutor(4),
            }
            if HAS_INTERPRETERS:
                executors["subinterpreters"] = lambda: concurrent.futures.InterpreterPoolExecutor(
                    4, initializer=add_to_sys_path, initargs=(str(PHASE5_DIR),)
                )

            measured: dict[str, dict[str, float]] = {"sequential": {}}
            for job_name, worker, jobs in (
                ("cpu", p5_patterns.busy_sum, cpu_jobs),
                ("io", p5_patterns.wait_for_io, io_jobs),
            ):
                with Timer("", report=None) as serial_timer:
                    [worker(job) for job in jobs]
                measured["sequential"][job_name] = serial_timer.elapsed_seconds
                for model, make_executor in executors.items():
                    with make_executor() as pool:
                        list(pool.map(worker, jobs[:4]))  # warm up the workers
                        with Timer("", report=None) as model_timer:
                            list(pool.map(worker, jobs))
                    measured.setdefault(model, {})[job_name] = model_timer.elapsed_seconds
            print(f"[{interpreter_label()}], 4 workers per pool")
            print(f"{'model':<16}{'CPU-bound':>12}{'I/O-bound':>12}")
            for model, times in measured.items():
                print(f"{model:<16}{times['cpu']:>11.3f}s{times['io']:>11.3f}s")
            """
        ),
        md(
            """
            Threads win nothing on the CPU column and everything on the I/O column;
            processes and subinterpreters win on CPU. For I/O, all pools get about 4×
            (4 workers waiting at once), which is why the cheapest option, threads (or
            asyncio), is the right one there.

            #### Amdahl's law

            If a fraction `p` of a program's run time can be parallelized and the rest
            `1 - p` cannot, the best possible speedup on `N` workers is

            ```text
            S(N) = 1 / ((1 - p) + p / N)        and as N grows without limit, S → 1 / (1 - p)
            ```

            A program that is 90% parallel can never run more than 10× faster, however many
            cores you add. The table and chart show how quickly the serial part dominates.
            """
        ),
        code(
            '''
            def amdahl(parallel_fraction: float, workers: float) -> float:
                """Amdahl's law: the speedup limit for a parallel fraction on `workers` workers."""
                return 1 / ((1 - parallel_fraction) + parallel_fraction / workers)


            worker_counts = [1, 2, 4, 8, 16, 64, math.inf]
            print("p \\\\ N  " + "".join(f"{('inf' if n == math.inf else n):>7}" for n in worker_counts))
            for fraction in (0.5, 0.75, 0.9, 0.95, 0.99):
                print(f"{fraction:<7}" + "".join(f"{amdahl(fraction, n):>7.1f}" for n in worker_counts))
            print()
            for n in (1, 2, 4, 8, 16, 32):
                print(f"p=0.9, N={n:>2} {'#' * round(amdahl(0.9, n) * 4):<40} {amdahl(0.9, n):.1f}x")
            '''
        ),
        md(
            """
            Run it backwards to estimate the parallel fraction of a real run: from a
            measured speedup `S` on `N` workers, `p = (1 - 1/S) / (1 - 1/N)`. Process
            start-up and pickling count as serial time, so measured `p` is lower than the
            "obvious" one.
            """
        ),
        code(
            """
            for model in ("processes", "subinterpreters"):
                if model in measured:
                    speedup = measured["sequential"]["cpu"] / measured[model]["cpu"]
                    implied_fraction = (1 - 1 / speedup) / (1 - 1 / 4)
                    print(
                        f"{model:<16} CPU speedup on 4 workers {speedup:.2f}x -> "
                        f"implied parallel fraction p = {implied_fraction:.2f}"
                    )
            """
        ),
    ]


def _pattern_cells() -> list[NotebookNode]:
    """5.2.8 Patterns."""
    return [
        md(
            """
            ### 5.2.8 Patterns

            #### Map-reduce

            1. **Split** the input into chunks.
            2. **Map**: each worker turns its chunk into a small partial result.
            3. **Reduce**: combine the partial results in the parent.

            Only the partial results travel back, so the reduce step stays cheap. Here:
            revenue per city over 400 000 sales records, with `Counter` partials that add up
            with `+`. (Lab 5.2 does word counts the same way.)
            """
        ),
        code(
            """
            sales_random = random.Random(52)
            cities = ["Pune", "Mumbai", "Bengaluru", "Chennai", "Kolkata"]
            sales = [
                (sales_random.choice(cities), sales_random.randint(100, 5_000))
                for _ in range(400_000 * DEMO_SCALE)
            ]

            with Timer("sequential map + reduce"):
                serial_totals = p5_patterns.revenue_by_city(sales)
            with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
                with Timer("parallel: 16 chunks on 4 workers"):
                    chunks = [
                        sales[start : start + len(sales) // 16]
                        for start in range(0, len(sales), len(sales) // 16)
                    ]
                    partials = pool.map(p5_patterns.revenue_by_city, chunks)
                    parallel_totals = functools.reduce(operator.add, partials, Counter())
            print(
                f"same totals: {parallel_totals == serial_totals}; top city: {parallel_totals.most_common(1)}"
            )
            """
        ),
        md(
            """
            On this workload the parallel version is often *not* faster: summing one number
            per record is cheap compared with pickling the record to a worker. The pattern
            pays off when the map step is expensive per item (parsing, hashing, matching),
            and costs least when workers read their own input (a file name or a byte range)
            instead of receiving it.

            #### Chunking

            How you split matters as much as how many workers you use:

            | Too few chunks (1 per worker) | Too many chunks (1 per item) | About 4 chunks per worker |
            | --- | --- | --- |
            | one slow chunk leaves the others idle at the end | per-chunk overhead dominates | balances load and overhead |

            `itertools.batched` (*new in 3.12*) cuts an iterable into chunks of a fixed
            size; to get a fixed *number* of nearly equal chunks, compute the size first.
            """
        ),
        code(
            '''
            def split_evenly[T](items: list[T], chunk_count: int) -> list[list[T]]:
                """Split items into chunk_count chunks whose sizes differ by at most one."""
                size, extra = divmod(len(items), chunk_count)
                chunks, start = [], 0
                for index in range(chunk_count):
                    stop = start + size + (1 if index < extra else 0)
                    chunks.append(items[start:stop])
                    start = stop
                return chunks


            ten_orders = [f"order-{n}" for n in range(10)]
            print(
                "batched(size 4):        "
                f"{[len(batch) for batch in itertools.batched(ten_orders, 4, strict=False)]}"
            )
            print(f"split_evenly(4 chunks): {[len(chunk) for chunk in split_evenly(ten_orders, 4)]}")
            print(f"workers x 4 chunks for {os.process_cpu_count()} CPUs: {os.process_cpu_count() * 4} chunks")
            '''
        ),
        md(
            """
            #### `KeyboardInterrupt` handling

            Pressing Ctrl+C in a terminal sends `SIGINT` to the whole process group: the
            parent *and* every worker. Without care, each worker prints its own
            `KeyboardInterrupt` traceback and the pool can hang. The usual recipe:

            1. Workers ignore `SIGINT` (an `initializer` that sets `SIG_IGN`): stopping is
               the parent's job.
            2. The parent catches `KeyboardInterrupt`, cancels pending work and stops the
               workers: `executor.terminate_workers()` (*new in 3.14*; it also cancels
               pending futures), or `pool.terminate()` for a `multiprocessing.Pool`.
            3. Exit with a clear message (and exit code 130, the shell convention for
               Ctrl+C).

            The script below follows that recipe. The notebook starts it, waits for two
            results, then sends `SIGINT` to the parent process only (POSIX).
            """
        ),
        code(
            '''
            CTRL_C_DEMO = """
                import signal, sys, time
                from concurrent.futures import ProcessPoolExecutor

                def ignore_sigint():
                    signal.signal(signal.SIGINT, signal.SIG_IGN)  # Ctrl+C is the parent's job

                def slow_task(number):
                    time.sleep(0.2)
                    return number

                if __name__ == "__main__":
                    executor = ProcessPoolExecutor(max_workers=2, initializer=ignore_sigint)
                    try:
                        print("started", flush=True)
                        for result in executor.map(slow_task, range(100)):
                            print(f"got {result}", flush=True)
                    except KeyboardInterrupt:
                        print("KeyboardInterrupt: cancelling pending tasks and stopping workers")
                        executor.terminate_workers()
                        print("workers stopped; exiting cleanly")
                        sys.exit(130)
            """
            if not hasattr(signal, "SIGINT") or os.name != "posix":
                print("SKIP: this demo sends POSIX signals")
            else:
                (PHASE5_DIR / "ctrl_c_demo.py").write_text(textwrap.dedent(CTRL_C_DEMO), encoding="utf-8")
                demo = subprocess.Popen(
                    [sys.executable, "ctrl_c_demo.py"], cwd=PHASE5_DIR, env=CHILD_ENV,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                )  # fmt: skip
                lines_before = [demo.stdout.readline().strip() for _ in range(3)]  # started, got 0, got 1
                demo.send_signal(signal.SIGINT)
                rest, _ = demo.communicate(timeout=30)
                print("\\n".join(lines_before + rest.strip().splitlines()))
                print(f"exit code: {demo.returncode}")
            '''
        ),
        md(
            """
            #### `os.process_cpu_count()`

            `os.cpu_count()` reports the CPUs in the machine. `os.process_cpu_count()`
            (*new in 3.13*) reports how many **this process may use**: it respects CPU
            affinity (`taskset`, container limits that pin CPUs). The `-X cpu_count=N` option
            and the `PYTHON_CPU_COUNT` variable (*new in 3.13*) override **both** functions,
            which is handy for testing pool sizing. Pools default to `process_cpu_count()`,
            and so should your own sizing. The child script pins itself to two CPUs (Linux
            only), then runs again with `PYTHON_CPU_COUNT=3`.
            """
        ),
        code(
            '''
            AFFINITY_DEMO = """
                import os
                print(f"os.cpu_count()={os.cpu_count()}  os.process_cpu_count()={os.process_cpu_count()}")
                if hasattr(os, "sched_setaffinity"):
                    os.sched_setaffinity(0, set(sorted(os.sched_getaffinity(0))[:2]))
                    print(f"pinned to 2 CPUs: os.process_cpu_count()={os.process_cpu_count()}")
                else:
                    print("SKIP: sched_setaffinity is not available on this platform")
            """
            print(run_child(AFFINITY_DEMO))
            print("--- with PYTHON_CPU_COUNT=3")
            print(run_child(AFFINITY_DEMO.split("if hasattr")[0], extra_env={"PYTHON_CPU_COUNT": "3"}))
            '''
        ),
    ]


def _predict_cells() -> list[NotebookNode]:
    """Predict-the-output questions for Unit 5.2."""
    return [
        md("#### Predict the output"),
        *predict_cells(
            """
            # p5_basics.add_order appends to the module-level list ORDERS
            # and returns (pid, len(ORDERS)).
            with ProcessPoolExecutor(max_workers=1) as pool:
                counts = [count for _, count in pool.map(p5_basics.add_order, ["B-1", "B-2"])]
            print(counts, p5_basics.ORDERS)
            """,
            """
            `[1, 2] []`. The single worker process keeps its own copy of `ORDERS` across
            both tasks (it is reused), so it counts 1 then 2. The kernel's module was never
            touched: processes do not share memory. (A fresh pool starts from an empty
            list again.)
            """,
            """
            with concurrent.futures.ProcessPoolExecutor(max_workers=1) as pool:
                counts = [count for _, count in pool.map(p5_basics.add_order, ["B-1", "B-2"])]
            print(counts, p5_basics.ORDERS)
            """,
        ),
        *predict_cells(
            """
            import pickle

            def outer():
                def helper():
                    return 1
                return helper

            for candidate in (len, outer, outer()):
                try:
                    pickle.dumps(candidate)
                    print("ok", end=" ")
                except Exception as error:
                    print(type(error).__name__, end=" ")
            """,
            """
            `ok ok PicklingError`. `len` and `outer` are found by name (`builtins.len`,
            `__main__.outer`), so they pickle. The nested `helper` has the qualified name
            `outer.<locals>.helper`, which cannot be looked up, so pickling fails, and it
            could never be sent to a process. (Whether `__main__.outer` could be *loaded*
            by a child is a separate question: 5.2.2.)
            """,
            """
            def outer() -> Callable[[], int]:
                def helper() -> int:
                    return 1

                return helper


            for candidate in (len, outer, outer()):
                try:
                    pickle.dumps(candidate)
                    print("ok", end=" ")
                except Exception as error:
                    print(type(error).__name__, end=" ")
            print()
            """,
        ),
        *predict_cells(
            """
            # 90% of a job parallelizes perfectly. What speedup on 16 cores, and the most on any number?
            print(round(1 / ((1 - 0.9) + 0.9 / 16), 1), round(1 / (1 - 0.9), 1))
            """,
            """
            `6.4 10.0`. Amdahl's law: the 10% serial part costs 0.1 of the original time on
            any number of cores, so the speedup can never exceed 1 / 0.1 = 10. Sixteen
            cores give 1 / (0.1 + 0.05625) = 6.4.
            """,
            """
            print(round(1 / ((1 - 0.9) + 0.9 / 16), 1), round(1 / (1 - 0.9), 1))
            """,
        ),
    ]


LAB_SETUP_SOURCE = r'''
import concurrent.futures
import hashlib
import importlib.util
import inspect
import math
import multiprocessing
import random
import re
import sys
import time
from collections import Counter
from collections.abc import Iterable
from multiprocessing import shared_memory
from pathlib import Path

LAB52_DIR = PHASE5_DIR / "lab52"
LAB52_DIR.mkdir(parents=True, exist_ok=True)
lab_random = random.Random(52)

HASH_FILES = [LAB52_DIR / f"export-{number}.bin" for number in range(8)]
for path in HASH_FILES:  # 8 files of 8 MiB x DEMO_SCALE, same bytes every run
    path.write_bytes(lab_random.randbytes(8 * 1024 * 1024 * DEMO_SCALE))

WORDS = "chai masala the shop's order delivered late early pune mumbai".split()
WORDS += "refund invoice gst customer happy isn't tea mug kettle rain".split()
CORPUS = [
    " ".join(lab_random.choices(WORDS, k=12)).capitalize() for _ in range(100_000 * DEMO_SCALE)
]


def shm_segments() -> set[str]:
    """Names of POSIX shared-memory blocks made by multiprocessing (Linux; empty elsewhere)."""
    folder = Path("/dev/shm")
    return {entry.name for entry in folder.glob("psm_*")} if folder.exists() else set()


if HAS_NUMPY:
    import numpy as np
print(
    f"{len(HASH_FILES)} files of {HASH_FILES[0].stat().st_size // 2**20} "
    f"MiB, {len(CORPUS):,} corpus lines"
)
print(f"first corpus line: {CORPUS[0]!r}")
'''


def _lab_cells_part_1() -> list[NotebookNode]:
    """Lab 5.2 exercises 1–2."""
    return [
        md(
            """
            ### Lab 5.2

            Four exercises. Worker functions go in `%%writefile` cells (child processes must
            import them); edit the cell, run it, then run the cell after it, which
            re-imports the module with `fresh_import`. Replace each
            `raise NotImplementedError`, then run the check cell. Until you finish, the
            checks print FAIL; that is expected.

            The setup cell writes eight 8 MiB files for exercise 1 and builds a seeded
            100 000-line corpus for exercise 4.

            > **Warning:** after editing a worker module, re-run *both* the `%%writefile`
            > cell and the cell after it. `fresh_import` puts a new module object in
            > `sys.modules`; a function still taken from the old module object can no
            > longer be pickled (`PicklingError: ... it's not the same object as ...`),
            > because pickle checks that the name leads back to that exact object.
            """
        ),
        code(LAB_SETUP_SOURCE),
        md(
            """
            #### Exercise 1 — parallel hashing with processes vs threads, with the result explained

            1. In `lab52_hashing.py`, `sha256_file(path)` returns `(path.name, hex digest)`,
               reading the file in 1 MiB blocks and feeding them to one `hashlib.sha256()`.
            2. `hash_files(paths, executor_class, max_workers=4)` hashes every file with
               `executor_class(max_workers=max_workers)` (it will be called with
               `ThreadPoolExecutor` and `ProcessPoolExecutor`) and returns
               `{file name: digest}`.
            3. `benchmark_hashing(paths, max_workers=4)` returns the seconds taken for
               `"sequential"` (a plain loop), `"threads"` and `"processes"`.
            """
        ),
        code(
            '''
            %%writefile _scratch/phase5/lab52_hashing.py
            """Lab 5.2 exercise 1 worker."""

            import hashlib  # noqa: F401 (for your solution)
            from pathlib import Path


            def sha256_file(path: Path) -> tuple[str, str]:
                """Return (file name, SHA-256 hex digest), reading 1 MiB blocks."""
                raise NotImplementedError
            '''
        ),
        md("Re-import the worker module, then write the two functions:"),
        code(
            '''
            hashing_workers = fresh_import("lab52_hashing")


            def hash_files(
                paths: list[Path], executor_class: type[concurrent.futures.Executor], max_workers: int = 4
            ) -> dict[str, str]:
                """Hash files with executor_class(max_workers); return {file name: digest}."""
                raise NotImplementedError


            def benchmark_hashing(paths: list[Path], max_workers: int = 4) -> dict[str, float]:
                """Seconds for "sequential", "threads" and "processes"."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 1:"),
        code(
            """
            EXPECTED_DIGESTS = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in HASH_FILES}
            run_checks(
                [
                    (
                        "sha256_file returns (name, digest)",
                        lambda: hashing_workers.sha256_file(HASH_FILES[0]),
                        (HASH_FILES[0].name, EXPECTED_DIGESTS[HASH_FILES[0].name]),
                    ),
                    (
                        "threads: right digests",
                        lambda: hash_files(HASH_FILES, concurrent.futures.ThreadPoolExecutor),
                        EXPECTED_DIGESTS,
                    ),
                    (
                        "processes: right digests",
                        lambda: hash_files(HASH_FILES, concurrent.futures.ProcessPoolExecutor),
                        EXPECTED_DIGESTS,
                    ),
                    (
                        "benchmark: three positive timings",
                        lambda: sorted(
                            name for name, seconds in benchmark_hashing(HASH_FILES).items() if seconds > 0
                        ),
                        ["processes", "sequential", "threads"],
                    ),
                ]
            )
            """
        ),
        md(
            """
            **Explain the result.** Run the benchmark, then write down which model won and
            why before opening the answer.

            <details><summary>Answer</summary>

            Threads usually match or beat processes here. `hashlib` releases the GIL while
            it hashes each 1 MiB block, and file reads release it too, so threads already
            hash on several cores at once, with no start-up cost and nothing to pickle
            (each task sends only a path and returns a short string). Processes get the
            same parallelism but pay for starting workers and importing the module. With
            much bigger files the two converge; with many tiny files, threads win clearly;
            if the hashing were pure Python (no GIL release), only processes would scale.

            </details>
            """
        ),
        code(
            """
            try:
                for model, seconds in benchmark_hashing(HASH_FILES).items():
                    print(f"{model:<11} {seconds:.3f} s")
            except NotImplementedError:
                print("Finish exercise 1 first.")
            """
        ),
        md(
            """
            #### Exercise 2 — a `chunksize` tuning chart

            The worker `tiny_task` is given (it is deliberately cheap).

            1. `time_chunksizes(items, chunksizes, processes=4)` creates **one**
               `multiprocessing.Pool(processes)`, warms it up, then times
               `pool.map(tiny_task, items, chunksize=c)` for each `c` and returns
               `{chunksize: seconds}`.
            2. `render_chart(timings, width=40)` returns one line per chunksize, in
               ascending chunksize order: `f"{chunksize:>6} | {bar} {seconds:.3f} s"` where
               `bar` is `"#"` repeated `max(1, round(width * seconds / slowest))` times.
            """
        ),
        code(
            '''
            %%writefile _scratch/phase5/lab52_chunks.py
            """Lab 5.2 exercise 2 worker (given)."""


            def tiny_task(number: int) -> int:
                """A deliberately tiny task."""
                return (number * 7) % 11
            '''
        ),
        md("Re-import the worker module, then write the two functions:"),
        code(
            '''
            chunk_workers = fresh_import("lab52_chunks")


            def time_chunksizes(
                items: list[int], chunksizes: list[int], processes: int = 4
            ) -> dict[int, float]:
                """Seconds for Pool.map(tiny_task, items, chunksize=c) for each c, using one pool."""
                raise NotImplementedError


            def render_chart(timings: dict[int, float], width: int = 40) -> list[str]:
                """A text bar chart, one line per chunksize in ascending order."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 2:"),
        code(
            """
            run_checks(
                [
                    (
                        "chart lines",
                        lambda: render_chart({10: 0.25, 1: 0.5, 100: 0.05}, width=20),
                        [
                            "     1 | #################### 0.500 s",
                            "    10 | ########## 0.250 s",
                            "   100 | ## 0.050 s",
                        ],
                    ),
                    (
                        "tiny bars still show one #",
                        lambda: render_chart({1: 1.0, 1000: 0.001}, width=10)[1],
                        "  1000 | # 0.001 s",
                    ),
                    (
                        "one key per chunksize",
                        lambda: sorted(time_chunksizes(list(range(2_000)), [1, 50, 500])),
                        [1, 50, 500],
                    ),
                    (
                        "positive timings",
                        lambda: all(
                            seconds > 0 for seconds in time_chunksizes(list(range(500)), [1, 100]).values()
                        ),
                        True,
                    ),
                ]
            )
            """
        ),
        md(
            """
            Once the checks pass, draw the real chart for 40 000 tasks (this takes a few
            seconds, most of it at `chunksize=1`). Where does the curve flatten on your
            machine?
            """
        ),
        code(
            """
            try:
                chart_timings = time_chunksizes(list(range(40_000 * DEMO_SCALE)), [1, 10, 100, 1_000, 10_000])
                print("\\n".join(render_chart(chart_timings)))
            except NotImplementedError:
                print("Finish exercise 2 first.")
            """
        ),
    ]


def _lab_cells_part_2() -> list[NotebookNode]:
    """Lab 5.2 exercises 3–4."""
    return [
        md(
            """
            #### Exercise 3 — shared-memory array workers

            1. In `lab52_shared.py`, `scale_slice(block_name, length, start, stop, factor)`
               attaches to the shared block with `SharedMemory(name=block_name,
               track=False)`, views it as a `float64` NumPy array of `length` values,
               multiplies `values[start:stop]` by `factor` in place, and closes the block
               (delete the array view first).
            2. `parallel_scale(values, factor, workers=4)` creates a `SharedMemory` block,
               copies `values` into it (as `float64`), starts one `multiprocessing.Process`
               per slice (split as evenly as possible), joins them, returns a **copy** of
               the result, and always closes and unlinks the block. The input array must
               not change.
            """
        ),
        code(
            '''
            %%writefile _scratch/phase5/lab52_shared.py
            """Lab 5.2 exercise 3 worker."""

            from multiprocessing import shared_memory  # noqa: F401 (for your solution)


            def scale_slice(block_name: str, length: int, start: int, stop: int, factor: float) -> None:
                """Multiply values[start:stop] of the shared float64 array by factor, in place."""
                raise NotImplementedError
            '''
        ),
        md("Re-import the worker module, then write `parallel_scale`:"),
        code(
            '''
            shared_workers = fresh_import("lab52_shared")


            def parallel_scale(values: np.ndarray, factor: float, workers: int = 4) -> np.ndarray:
                """Scale a copy of values in shared memory with one process per slice."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 3 (prints a skip message without NumPy):"),
        code(
            '''
            def segments_left_behind() -> list[str]:
                """Shared-memory blocks that exist after parallel_scale but did not before."""
                before = shm_segments()
                parallel_scale(np.arange(1_000.0), 2.0)
                return sorted(shm_segments() - before)


            def input_unchanged() -> list[float]:
                """parallel_scale must not modify its argument."""
                original = np.arange(5.0)
                parallel_scale(original, 3.0)
                return original.tolist()


            if not HAS_NUMPY:
                print("SKIP: numpy is not installed")
            else:
                run_checks(
                    [
                        (
                            "scales every value",
                            lambda: parallel_scale(np.arange(6.0), 2.5).tolist(),
                            [0.0, 2.5, 5.0, 7.5, 10.0, 12.5],
                        ),
                        (
                            "uneven split: 10 values, 4 workers",
                            lambda: parallel_scale(np.arange(10.0), 10.0, 4).tolist(),
                            [10.0 * n for n in range(10)],
                        ),
                        (
                            "one worker",
                            lambda: parallel_scale(np.arange(3.0), -1.0, 1).tolist(),
                            [0.0, -1.0, -2.0],
                        ),
                        ("returns float64", lambda: str(parallel_scale(np.arange(4), 2.0).dtype), "float64"),
                        ("input array unchanged", input_unchanged, [0.0, 1.0, 2.0, 3.0, 4.0]),
                        ("no shared memory left behind", segments_left_behind, []),
                        (
                            "uses Process and SharedMemory",
                            lambda: all(
                                word in inspect.getsource(parallel_scale)
                                for word in ("Process(", "SharedMemory(")
                            ),
                            True,
                        ),
                    ]
                )
            '''
        ),
        md(
            """
            #### Exercise 4 — map-reduce word counts, measured speedup vs Amdahl's prediction

            1. In `lab52_wordcount.py`, `count_words(lines)` (the map step) returns a
               `Counter` of the words in a list of lines: lowercase each line and take
               `re.findall(r"[a-z']+", line)`.
            2. `merge_counts(partials)` (the reduce step) adds an iterable of `Counter`s.
            3. `parallel_word_count(lines, workers=4, chunks_per_worker=4)` splits `lines`
               into `workers * chunks_per_worker` nearly equal chunks, maps them with a
               `ProcessPoolExecutor(workers)` and reduces with `merge_counts`.
            4. `amdahl_speedup(parallel_fraction, workers)` returns
               `1 / ((1 - p) + p / workers)`; raise `ValueError` unless `0 <= p <= 1`.
            5. `speedup_report(lines, workers=4)` returns a dict with
               - `"sequential_seconds"`: time to run `count_words` on every chunk in the
                 kernel (the map time) plus time to `merge_counts` them (the reduce time);
               - `"parallel_seconds"`: time for `parallel_word_count(lines, workers)`;
               - `"measured_speedup"`: sequential ÷ parallel;
               - `"parallel_fraction"`: map time ÷ sequential time (the part that can run
                 in parallel);
               - `"predicted_speedup"`: `amdahl_speedup(parallel_fraction, workers)`.
            """
        ),
        code(
            '''
            %%writefile _scratch/phase5/lab52_wordcount.py
            """Lab 5.2 exercise 4 worker."""

            import re  # noqa: F401 (for your solution)
            from collections import Counter


            def count_words(lines: list[str]) -> Counter[str]:
                """Map step: count the lowercase words in a chunk of lines."""
                raise NotImplementedError
            '''
        ),
        md("Re-import the worker module, then write the four functions:"),
        code(
            '''
            wordcount_workers = fresh_import("lab52_wordcount")


            def merge_counts(partials: Iterable[Counter[str]]) -> Counter[str]:
                """Reduce step: add the partial counts."""
                raise NotImplementedError


            def parallel_word_count(
                lines: list[str], workers: int = 4, chunks_per_worker: int = 4
            ) -> Counter[str]:
                """Map-reduce word count with a process pool."""
                raise NotImplementedError


            def amdahl_speedup(parallel_fraction: float, workers: int) -> float:
                """Amdahl's law."""
                raise NotImplementedError


            def speedup_report(lines: list[str], workers: int = 4) -> dict[str, float]:
                """Measured speedup next to Amdahl's prediction."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 4:"),
        code(
            '''
            SAMPLE_LINES = ["The shop's tea", "the TEA was late", ""]


            def report_consistent() -> bool:
                """The report's numbers agree with each other."""
                report = speedup_report(CORPUS[:20_000], 4)
                return (
                    math.isclose(
                        report["measured_speedup"], report["sequential_seconds"] / report["parallel_seconds"]
                    )
                    and math.isclose(
                        report["predicted_speedup"], amdahl_speedup(report["parallel_fraction"], 4)
                    )
                    and 0 < report["parallel_fraction"] <= 1
                )


            run_checks(
                [
                    (
                        "count_words (map step)",
                        lambda: dict(wordcount_workers.count_words(SAMPLE_LINES)),
                        {"the": 2, "shop's": 1, "tea": 2, "was": 1, "late": 1},
                    ),
                    (
                        "merge_counts (reduce step)",
                        lambda: dict(merge_counts([Counter(a=1, b=2), Counter(b=3), Counter()])),
                        {"a": 1, "b": 5},
                    ),
                    (
                        "parallel result equals sequential",
                        lambda: (
                            parallel_word_count(CORPUS[:20_000])
                            == wordcount_workers.count_words(CORPUS[:20_000])
                        ),
                        True,
                    ),
                    ("amdahl_speedup(0.9, 16)", lambda: round(amdahl_speedup(0.9, 16), 2), 6.4),
                    (
                        "amdahl_speedup at p=1 and p=0",
                        lambda: (amdahl_speedup(1.0, 8), amdahl_speedup(0.0, 8)),
                        (8.0, 1.0),
                    ),
                    (
                        "p outside 0..1 is rejected",
                        lambda: raised_error_name(lambda: amdahl_speedup(1.5, 4)),
                        "ValueError",
                    ),
                    (
                        "speedup_report keys",
                        lambda: sorted(speedup_report(CORPUS[:20_000], 4)),
                        [
                            "measured_speedup",
                            "parallel_fraction",
                            "parallel_seconds",
                            "predicted_speedup",
                            "sequential_seconds",
                        ],
                    ),
                    ("speedup_report is consistent", report_consistent, True),
                ]
            )
            '''
        ),
        md(
            """
            Once the checks pass, compare the measurement with the prediction on the full
            corpus. Expect the measured speedup to fall short of Amdahl's number: the law
            assumes the parallel part splits perfectly, but here every chunk of lines must
            be pickled to a worker and every `Counter` pickled back, and the pool must
            start. That overhead behaves like extra serial time. The last number turns the
            measurement back into a parallel fraction (`p = (1 - 1/S) / (1 - 1/N)`, from
            5.2.7): the gap between it and the profiled `p` is the cost of going parallel.
            """
        ),
        code(
            """
            try:
                for workers in (2, 4):
                    report = speedup_report(CORPUS, workers)
                    effective_p = (1 - 1 / report["measured_speedup"]) / (1 - 1 / workers)
                    print(
                        f"{workers} workers: sequential {report['sequential_seconds']:.3f} s, "
                        f"parallel {report['parallel_seconds']:.3f} s"
                    )
                    print(
                        f"  measured {report['measured_speedup']:.2f}x, "
                        f"Amdahl predicts {report['predicted_speedup']:.2f}x"
                    )
                    print(
                        f"  p from the profile {report['parallel_fraction']:.3f}, "
                        f"p implied by the measurement {effective_p:.2f}"
                    )
            except NotImplementedError:
                print("Finish exercise 4 first.")
            """
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 5.2."""
    return [
        md(
            """
            ### Recap — Unit 5.2

            | Concept | One-line takeaway | JS / Node equivalent |
            | --- | --- | --- |
            | Processes | Own memory and own GIL: real parallelism for Python code; milliseconds to start | `child_process.fork` |
            | Start methods | `forkserver` is the POSIX default since 3.14; `fork` is unsafe with threads; `spawn` needs the main guard | — |
            | Importable workers | Functions are pickled by name; notebook functions live in `__main__` and fail in children | — |
            | `Process`, `Pool`, `ProcessPoolExecutor` | Reuse workers; `chunksize` for small tasks; `initializer` per worker; `max_tasks_per_child` against leaks | `cluster`, worker pools |
            | Data transfer | Everything crosses as a pickle: coarse tasks, small messages, or parallel gets slower | structured clone |
            | IPC | `Queue`, `Pipe`, `Value`/`Array` (+ lock), `Manager` (slow proxies), `shared_memory` (zero-copy with NumPy) | `process.send`, `SharedArrayBuffer` |
            | Subinterpreters | `concurrent.interpreters` (3.14): own GIL inside one process; C extensions must opt in | `worker_threads` |
            | Choosing a model | Decision matrix + a benchmark on your workload | — |
            | Amdahl's law | `S = 1 / ((1 - p) + p / N)`; the serial part caps the speedup | — |
            | Patterns | Map-reduce with `Counter`s, ~4 chunks per worker, workers ignore SIGINT, size by `os.process_cpu_count()` | `os.availableParallelism()` |

            **Further reading**

            - [`multiprocessing`](https://docs.python.org/3/library/multiprocessing.html)
              (read *Programming guidelines*),
              [`multiprocessing.shared_memory`](https://docs.python.org/3/library/multiprocessing.shared_memory.html)
            - [`concurrent.futures`](https://docs.python.org/3/library/concurrent.futures.html)
              (`ProcessPoolExecutor`, `InterpreterPoolExecutor`),
              [`concurrent.interpreters`](https://docs.python.org/3/library/concurrent.interpreters.html)
            - [`pickle`: what can be pickled](https://docs.python.org/3/library/pickle.html#what-can-be-pickled-and-unpickled),
              [`os.process_cpu_count`](https://docs.python.org/3/library/os.html#os.process_cpu_count)
            - [PEP 371](https://peps.python.org/pep-0371/) (the `multiprocessing` package),
              [PEP 684](https://peps.python.org/pep-0684/) (a per-interpreter GIL),
              [PEP 734](https://peps.python.org/pep-0734/) (multiple interpreters in the standard library)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 5.2 and Lab 5.2."""
    return [
        *_overview_cells(),
        *_process_cells(),
        *_start_method_cells(),
        *_process_api_cells(),
        *_data_transfer_cells(),
        *_ipc_cells(),
        *_subinterpreter_cells(),
        *_choosing_cells(),
        *_pattern_cells(),
        *_predict_cells(),
        *_lab_cells_part_1(),
        *_lab_cells_part_2(),
        *_recap_cells(),
    ]
