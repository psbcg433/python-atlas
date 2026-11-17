"""Unit 5.1 — Concurrency Fundamentals, Threads and the GIL (with Lab 5.1)."""

import importlib.util
from pathlib import Path

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells


def _load_shop_api_source() -> str:
    """Return SHOP_API_SOURCE from the Phase 4 unit module (one copy of the server code).

    The module is loaded by file path, not through sys.path, so Phase 4's ``project.py`` can
    never shadow Phase 5's.
    """
    module_path = Path(__file__).resolve().parents[1] / "phase4" / "unit_4_6.py"
    spec = importlib.util.spec_from_file_location("phase4_unit_4_6", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SHOP_API_SOURCE


SHOP_API_SOURCE = _load_shop_api_source()

UNIT_SETUP_SOURCE = r'''
import asyncio
import concurrent.futures
import dis
import functools
import hashlib
import inspect
import itertools
import json
import os
import platform
import queue
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import sysconfig
import textwrap
import threading
import time
import timeit
import traceback
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

DEMO_SCALE = int(os.environ.get("PHASE5_DEMO_SCALE", "1"))  # the one knob for workload sizes
REPO_ROOT = find_repo_root()
scratch_dir = REPO_ROOT / "notebooks" / "_scratch"  # git-ignored
PHASE5_DIR = scratch_dir / "phase5"
PHASE5_DIR.mkdir(parents=True, exist_ok=True)
CHILD_ENV = {**os.environ, "PYTHON_COLORS": "0", "PYTHONUNBUFFERED": "1"}
SHOP_API = start_shop_api()


def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"


def raised_message(thunk: Callable[[], object]) -> str:
    """Call thunk and return "ErrorName: message" for the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return f"{type(error).__name__}: {error}"
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


def run_child(
    source: str, python: str = sys.executable, extra_env: dict[str, str] | None = None
) -> str:
    """Run dedented source as a script in a child interpreter; return its stdout + stderr.

    Paths of the scratch folder and interpreters are hidden so outputs stay machine-neutral.
    """
    script = PHASE5_DIR / "child_script.py"
    script.write_text(textwrap.dedent(source).lstrip("\n"), encoding="utf-8")
    completed = subprocess.run(
        [python, str(script)], capture_output=True, text=True, timeout=120,
        env={**CHILD_ENV, **(extra_env or {})}, cwd=PHASE5_DIR,
    )  # fmt: skip
    output = (completed.stdout + completed.stderr).rstrip()
    for path, label in ((str(PHASE5_DIR), "<scratch>"), (str(Path(python).parent), "<python>")):
        output = output.replace(path, label)
    return re.sub(r"/[^\s\"']*/lib/python3\.\d+t?/", "<stdlib>/", output)


FREE_THREADED_PYTHON = find_free_threaded_python()
print(interpreter_label())
print(f"{DEMO_SCALE=}  {os.process_cpu_count()=}  {SHOP_API=}")
print(f"free-threaded interpreter: {'found' if FREE_THREADED_PYTHON else 'not installed'}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 5.1 — Concurrency Fundamentals, Threads and the GIL

            **Objectives**

            - Tell concurrency from parallelism and CPU-bound from I/O-bound work, and pick
              processes, threads or coroutines from a comparison table and real latency
              numbers.
            - Create, name, join and stop threads; know what a daemon thread is.
            - Explain what the GIL protects, why it exists and when it is released, and
              prove it with CPU-bound and I/O-bound benchmarks.
            - Find race conditions (in `dis` output and in check-then-act code) and fix them
              with the right primitive: `Lock`, `RLock`, `Semaphore`, `Event`, `Condition`,
              `Barrier`, `Timer` or a queue.
            - Use `ThreadPoolExecutor` and `Future` well: submit, map, as_completed, wait,
              sizing, shutdown and error handling.
            - Run the free-threaded build (`python3.15t`) and measure what it changes.

            **JS bridge**

            | JavaScript / Node | Python | The difference that bites |
            | --- | --- | --- |
            | One thread runs all your JavaScript; the event loop interleaves callbacks | Many OS threads can run Python code; in the default build the GIL lets one of them execute bytecode at a time | Python threads are **preemptive**: a switch can happen between two bytecodes of the same line, so shared state needs locks |
            | No data races on ordinary objects (only one thread touches them) | Every thread sees the same heap | `counter += 1` from two threads can lose updates |
            | libuv thread pool (4 threads by default) runs `fs`, `dns.lookup`, `crypto.pbkdf2`, `zlib` for you | `ThreadPoolExecutor`: you create it, size it and submit work, including your own Python functions | Nothing is offloaded implicitly |
            | `worker_threads`: separate V8 isolate, separate heap, messages via structured clone | `threading.Thread` shares one heap; subinterpreters (5.2.6) are the isolate analogue | A Python thread is *not* a Worker |
            | `Atomics`, `Atomics.wait` / `notify` on a `SharedArrayBuffer` | `Lock`, `Condition`, `Event`, `Semaphore` | Python's primitives work on any object, not just a shared buffer |
            | `Promise` | `concurrent.futures.Future` | `future.result()` **blocks** the calling thread; there is no `await` on it outside asyncio |

            **How this unit runs.** Benchmarks print what they measured and the ratio; they
            never assert a speedup. I/O demos call the local shop API from Unit 4.6 (its
            `/slow?seconds=` route sleeps on the server, like a slow upstream service).
            Demos that need a fresh process (daemon threads at exit, the default
            `threading.excepthook` output, the free-threaded build) run as scripts in a
            child interpreter via `run_child(source, python=...)`.

            **The local shop API (copied unchanged from Unit 4.6).** A
            `BaseHTTPRequestHandler` with a few routes, served by `ThreadingHTTPServer` in a
            daemon thread on `127.0.0.1:18046` (any free port if that one is busy).
            """
        ),
        code(SHOP_API_SOURCE),
        md(
            """
            Unit setup, part 1: imports, `DEMO_SCALE`, the scratch folder, the API's base
            URL (`SHOP_API`) and the error and interpreter helpers shared since Phase 3.
            """
        ),
        code(UNIT_SETUP_SOURCE),
        md(
            """
            Unit setup, part 2: `Timer` (the timing context manager from Unit 1.14),
            `find_free_threaded_python()` (from Unit 3.1) and `run_child()`, which runs a
            script in a child interpreter and hides machine-specific paths.
            """
        ),
        code(UNIT_SETUP_SOURCE_2),
    ]


def _core_concept_cells() -> list[NotebookNode]:
    """5.1.1 Core concepts."""
    return [
        md(
            """
            ### 5.1.1 Core concepts

            - **Concurrency** is about *structure*: several tasks are in progress at the same
              time and their steps interleave. One core is enough.
            - **Parallelism** is about *execution*: several tasks run at the same instant on
              different cores.

            Node gives you concurrency (one thread, many callbacks in flight) and gets
            parallelism only inside libuv's thread pool or from `worker_threads`. CPython's
            default build gives threads concurrency but, for Python bytecode, not
            parallelism.

            ```mermaid
            gantt
                dateFormat x
                axisFormat %L ms
                section Concurrency (1 core)
                task A :a1, 0, 5
                task B :b1, 5, 10
                task A :a2, 10, 15
                task B :b2, 15, 20
                section Parallelism (2 cores)
                task A (core 1) :0, 20
                task B (core 2) :0, 20
            ```

            <details><summary>ASCII fallback</summary>

            ```text
            concurrency, 1 core:   AAAAABBBBBAAAAABBBBB   (interleaved: both in progress)
            parallelism, 2 cores:  AAAAAAAAAAAAAAAAAAAA   core 1
                                   BBBBBBBBBBBBBBBBBBBB   core 2 (both running at once)
            ```

            </details>

            The next cell makes this visible. Two CPU-bound threads each record a timestamp
            on every loop iteration for 60 ms. Afterwards the timeline is cut into 1 ms
            slots: `A` or `B` means only that thread ran in the slot, `*` means both ran
            (parallelism). Under the GIL you should see runs of `A` and `B` (about 5 ms
            each, the switch interval) and almost no `*`.
            """
        ),
        code(
            '''
            def record_activity(stop_at: float, samples: list[float]) -> None:
                """Spin until stop_at, appending a timestamp on every iteration."""
                while (now := time.perf_counter()) < stop_at:
                    samples.append(now)


            def activity_timeline(duration: float = 0.06, slot: float = 0.001) -> str:
                """Run two spinning threads and draw which one ran in each time slot."""
                start = time.perf_counter()
                samples: dict[str, list[float]] = {"A": [], "B": []}
                threads = [
                    threading.Thread(target=record_activity, args=(start + duration, samples[name]))
                    for name in samples
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
                slot_count = int(duration / slot)
                busy = {
                    name: {int((sample_time - start) / slot) for sample_time in times}
                    for name, times in samples.items()
                }
                cells = []
                for index in range(slot_count):
                    ran = [name for name in samples if index in busy[name]]
                    cells.append("*" if len(ran) == 2 else (ran[0] if ran else "."))
                return "".join(cells)


            print(f"[{interpreter_label()}]")
            print(activity_timeline())
            '''
        ),
        md(
            """
            **What to notice:** long runs of one letter, then the other. Both threads were
            *in progress* the whole time (concurrency), but at any moment only one executed
            Python code. A few `*` slots can appear where one thread hands over in the
            middle of a millisecond. The free-threaded build (5.1.10) prints mostly `*`.

            #### CPU-bound vs I/O-bound

            | | CPU-bound | I/O-bound |
            | --- | --- | --- |
            | Time is spent | executing instructions | waiting for a disk, network or another process |
            | Examples | parsing, hashing, image resizing, pure-Python loops | HTTP calls, database queries, reading files, `sleep` |
            | More threads help? | only if the work runs outside the GIL (C code that releases it) or on a free-threaded build | yes: waiting threads release the GIL |
            | Usual tool | processes, subinterpreters, NumPy, free-threaded threads | threads or asyncio |

            You can **measure** which kind a function is: compare the CPU time its thread
            used (`time.thread_time()`) with the wall-clock time (`time.perf_counter()`).
            A ratio near 1 means CPU-bound; near 0 means the thread mostly waited.
            """
        ),
        code(
            '''
            def busy_sum(count: int) -> int:
                """Pure-Python CPU work. `% 1000` keeps every value a small int, so each step costs the same."""
                return sum(number % 1000 for number in range(count))


            def fetch_slow_page(seconds: float = 0.2) -> bytes:
                """I/O work: the local API sleeps `seconds` before answering."""
                with urllib.request.urlopen(f"{SHOP_API}/slow?seconds={seconds}", timeout=10) as response:
                    return response.read()


            def cpu_share(work: Callable[[], object]) -> float:
                """CPU time used by this thread divided by wall-clock time, for one call of work."""
                wall_start, cpu_start = time.perf_counter(), time.thread_time()
                work()
                return (time.thread_time() - cpu_start) / (time.perf_counter() - wall_start)


            print(f"busy_sum:        CPU/wall = {cpu_share(lambda: busy_sum(2_000_000 * DEMO_SCALE)):.2f}")
            print(f"fetch_slow_page: CPU/wall = {cpu_share(fetch_slow_page):.2f}")
            '''
        ),
        md(
            """
            #### Latency numbers

            Choosing a concurrency model starts with knowing what you wait for. The classic
            table ("latency numbers every programmer should know", rounded; real hardware
            varies by a factor of a few):

            | Operation | Approximate time | Scaled: if 1 ns were 1 second |
            | --- | --- | --- |
            | L1 cache reference | 1 ns | 1 s |
            | Branch mispredict | 3 ns | 3 s |
            | L2 cache reference | 4 ns | 4 s |
            | Uncontended mutex lock/unlock (C) | 20 ns | 20 s |
            | Main memory reference | 100 ns | under 2 minutes |
            | Read 1 MB sequentially from memory | 10 µs | 3 hours |
            | Random read from an NVMe SSD | 20–100 µs | 6–28 hours |
            | Round trip inside one data centre | 500 µs | 6 days |
            | Read 1 MB sequentially from an SSD | 50–200 µs | 14–56 hours |
            | Disk seek (spinning disk) | 5 ms | 2 months |
            | Packet round trip, Europe ↔ US west coast | 150 ms | 5 years |

            Python adds its own costs on top. The next cell measures a few of them **on this
            machine** with `timeit` and one-off timings: a function call, an uncontended
            `threading.Lock`, starting a thread, creating and running a coroutine, a local
            HTTP round trip, reading 1 MB from the page cache and starting a child
            interpreter. Notice the six orders of magnitude between the first and last rows.
            """
        ),
        code(
            '''
            def per_call_seconds(statement: Callable[[], object], number: int) -> float:
                """Best-of-3 average seconds per call of statement."""
                return min(timeit.repeat(statement, number=number, repeat=3)) / number


            def human_time(seconds: float) -> str:
                """Format seconds as ns, µs or ms."""
                for unit, factor in (("ns", 1e9), ("µs", 1e6), ("ms", 1e3)):
                    if seconds * factor < 1000:
                        return f"{seconds * factor:,.1f} {unit}"
                return f"{seconds:.2f} s"


            def start_and_join_thread() -> None:
                """Create, start and join a thread that does nothing."""
                worker = threading.Thread(target=lambda: None)
                worker.start()
                worker.join()


            lock_for_timing = threading.Lock()
            megabyte_file = PHASE5_DIR / "one_megabyte.bin"
            megabyte_file.write_bytes(os.urandom(1024 * 1024))


            def lock_round_trip() -> None:
                """Acquire and release an uncontended lock."""
                with lock_for_timing:
                    pass


            def coroutine_round_trip() -> None:
                """Create a coroutine and run it to completion without an event loop."""
                coroutine = asyncio.sleep(0)
                try:
                    coroutine.send(None)
                except StopIteration:
                    pass
            '''
        ),
        md(
            """
            The table itself. The child-interpreter row runs `python -c pass` five times, so
            this cell takes a fraction of a second.
            """
        ),
        code(
            '''
            def start_child_interpreter() -> None:
                """Start a fresh interpreter that does nothing."""
                subprocess.run([sys.executable, "-c", "pass"], check=True)


            def local_http_round_trip() -> None:
                """GET a tiny JSON document from the local API (new TCP connection each time)."""
                with urllib.request.urlopen(f"{SHOP_API}/rates", timeout=5) as response:
                    response.read()


            measurements = [
                ("Python function call", per_call_seconds(lambda: None, 200_000)),
                ("threading.Lock acquire + release", per_call_seconds(lock_round_trip, 200_000)),
                ("coroutine create + run (no loop)", per_call_seconds(coroutine_round_trip, 50_000)),
                ("read 1 MB file (page cache)", per_call_seconds(megabyte_file.read_bytes, 200)),
                ("thread start + join", per_call_seconds(start_and_join_thread, 500)),
                ("local HTTP round trip", per_call_seconds(local_http_round_trip, 50)),
                ("child interpreter start", per_call_seconds(start_child_interpreter, 5)),
            ]
            print(f"[{interpreter_label()}] (varies by machine)")
            for label, seconds in measurements:
                print(f"{label:<36}{human_time(seconds):>14}")
            '''
        ),
        md(
            """
            #### Processes vs threads vs coroutines

            | | Process | Thread | Coroutine (asyncio) |
            | --- | --- | --- | --- |
            | Memory | separate address space (copy or fresh interpreter) | shared heap, own stack | shared heap; a suspended coroutine is a small heap object |
            | Start cost | milliseconds | tens of microseconds | about a microsecond |
            | How many | a few per core | hundreds to a few thousand | hundreds of thousands |
            | Runs Python bytecode in parallel | yes (one GIL each) | no in the default build; yes on a free-threaded build | no (one thread) |
            | Who decides when to switch | the OS scheduler | the OS, plus the GIL handoff every switch interval (preemptive) | your code, at each `await` (cooperative) |
            | Shared state | none by default; pass messages or use shared memory | everything; needs locks | everything, but switches only at `await`, so fewer races |
            | A crash affects | only that process | the whole process | the whole event loop |
            | Best for | CPU-bound pure Python | blocking I/O, C code that releases the GIL, legacy blocking libraries | many concurrent network connections |
            | Node equivalent | `child_process.fork`, `cluster` | libuv pool (C++ only), `worker_threads` (but isolated) | `async`/`await` on the event loop |

            The cell below checks the "start cost" and "how many" rows: it starts 200 threads
            that each sleep 10 ms, then runs 200 coroutines that each `await asyncio.sleep`
            for 10 ms (top-level `await` works in Jupyter because the kernel already runs an
            event loop). It also prints the size of one suspended coroutine object.
            """
        ),
        code(
            '''
            def sleep_briefly() -> None:
                """A thread body that waits 10 ms."""
                time.sleep(0.01)


            with Timer("200 threads (start, sleep 10 ms, join)"):
                many_threads = [threading.Thread(target=sleep_briefly) for _ in range(200)]
                for thread in many_threads:
                    thread.start()
                for thread in many_threads:
                    thread.join()

            with Timer("200 coroutines (sleep 10 ms, gather)"):
                await asyncio.gather(*(asyncio.sleep(0.01) for _ in range(200)))

            suspended = asyncio.sleep(1)
            print(f"one coroutine object: {sys.getsizeof(suspended)} bytes [{interpreter_label()}]")
            suspended.close()  # never awaited: close it so Python does not warn
            print(
                f"thread stack size setting: {threading.stack_size()} "
                "(0 = the OS default, 8 MiB virtual on Linux)"
            )
            '''
        ),
        md(
            """
            Both finish in roughly 10–30 ms, but the threads pay for 200 OS threads (each
            with its own stack reserved in virtual memory) while the coroutines are a few
            hundred bytes each on the heap. That is why a server holding 10 000 open
            connections uses asyncio (Units 5.3–5.4), not 10 000 threads.
            """
        ),
    ]


def _thread_cells() -> list[NotebookNode]:
    """5.1.2 threading.Thread."""
    return [
        md(
            """
            ### 5.1.2 `threading.Thread`

            | API | What it does |
            | --- | --- |
            | `Thread(target=f, args=(...), kwargs={...}, name="...", daemon=...)` | describe a thread; nothing runs yet |
            | `thread.start()` | ask the OS to start it; `run()` then calls `target(*args, **kwargs)` |
            | `thread.join(timeout=None)` | wait until it finishes (or the timeout passes; check `is_alive()` afterwards) |
            | `thread.is_alive()` | `True` between `start()` and the end of `run()` |
            | `thread.name`, `thread.ident`, `thread.native_id` | label you choose; Python's id; the OS thread id (what `top -H` shows) |
            | `thread.daemon` | daemon threads are killed when the interpreter exits |
            | `threading.current_thread()`, `main_thread()`, `get_ident()`, `get_native_id()` | who am I? |
            | `threading.enumerate()`, `active_count()` | all live `Thread` objects |

            **Creation, `start` and `join`.** A thread function cannot return a value to
            the caller: `join()` returns `None`. The usual workaround is to pass a container
            the thread writes into (or use a `ThreadPoolExecutor`, 5.1.8).
            """
        ),
        code(
            '''
            def greet_customer(customer_name: str, greetings: list[str]) -> None:
                """Thread body: append a greeting that names the thread running it."""
                current_thread = threading.current_thread()
                greetings.append(f"{current_thread.name} greeted {customer_name}")


            greetings: list[str] = []
            greeter = threading.Thread(
                target=greet_customer, args=("Asha",), kwargs={"greetings": greetings}, name="greeter-1"
            )
            print(f"before start: {greeter.is_alive()=}, {greeter.ident=}")
            greeter.start()
            join_result = greeter.join()
            print(f"after join:   {greeter.is_alive()=}, {join_result=}")
            print(f"{greetings=}")
            '''
        ),
        md(
            """
            **Names and IDs.** `ident` is Python's identifier (reused after a thread ends);
            `native_id` is the kernel's thread id. The main thread's `native_id` equals the
            process id on Linux. Exact numbers change on every run, so the cell prints
            comparisons and leaves the raw values for you to look at.
            """
        ),
        code(
            '''
            ids_seen: dict[str, tuple[int | None, int | None]] = {}


            def remember_ids() -> None:
                """Record this thread's Python ident and OS native id."""
                current_thread = threading.current_thread()
                ids_seen[current_thread.name] = (threading.get_ident(), threading.get_native_id())


            workers = [
                threading.Thread(target=remember_ids, name=f"id-probe-{probe_number}")
                for probe_number in range(2)
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()
            main = threading.main_thread()
            print(f"{main.name=}, main native_id == os.getpid(): {main.native_id == os.getpid()}")
            print(f"probe threads have distinct native ids: {len({ids[1] for ids in ids_seen.values()}) == 2}")
            print(f"raw ids (vary per run): {ids_seen}")
            print(f"default name of an unnamed thread: {threading.Thread(target=print).name!r}")
            '''
        ),
        md(
            """
            `threading.enumerate()` lists every live thread in this process. In a notebook
            that includes the kernel's own threads (heartbeat, I/O publishing, control) and
            the shop API's server thread; your list depends on the ipykernel version.
            """
        ),
        code(
            """
            print(f"{threading.active_count()=}")
            for live_thread in threading.enumerate():
                print(f"  {live_thread.name:<28} daemon={live_thread.daemon}")
            """
        ),
        md(
            """
            **Lifecycle errors.** A `Thread` object runs at most once: a second `start()`
            raises `RuntimeError`. `join(timeout)` returns when the timeout passes even if
            the thread is still running, so always check `is_alive()` afterwards.
            """
        ),
        code(
            """
            sleeper = threading.Thread(target=time.sleep, args=(0.3,), name="sleeper")
            sleeper.start()
            sleeper.join(timeout=0.05)
            print(f"after join(timeout=0.05): {sleeper.is_alive()=}")
            print(raised_message(sleeper.start))
            sleeper.join()
            print(f"after a full join:        {sleeper.is_alive()=}")
            """
        ),
        md(
            """
            **Daemon threads.** The interpreter waits for every non-daemon thread before it
            exits; daemon threads are simply stopped (no `finally`, no `with` cleanup). A
            new thread inherits `daemon` from the thread that creates it (the main thread is
            not a daemon). This only shows at interpreter exit, so the demo runs as a script
            in a child process: the main thread returns immediately in both cases.
            """
        ),
        code(
            '''
            DAEMON_DEMO = """
            import threading, time

            def background_job():
                try:
                    time.sleep(0.3)
                    print("background job finished")
                finally:
                    print("background job cleanup ran")

            daemon = {daemon}
            threading.Thread(target=background_job, daemon=daemon).start()
            print(f"main thread done (daemon={{daemon}})")
            """
            print(f"{threading.Thread(target=print).daemon=} (inherited from the main thread)")
            for daemon_flag in (False, True):
                print(f"--- child run with daemon={daemon_flag}")
                print(run_child(DAEMON_DEMO.format(daemon=daemon_flag)))
            '''
        ),
        md(
            """
            With `daemon=False` the process waits 0.3 s and the job finishes; with
            `daemon=True` the process exits at once and **neither print runs**, not even the
            `finally`. Use daemon threads only for work that is safe to lose (a heartbeat, a
            cache warmer), and give important workers a stop flag instead (5.1.9).

            **Subclassing vs `target`.** You can subclass `Thread` and override `run()`;
            this is handy when the thread carries state (here, its result). Passing a
            `target` keeps the work a plain function you can also call and test without
            threads.
            """
        ),
        code(
            '''
            class PriceFetcher(threading.Thread):
                """A thread subclass that fetches exchange rates and keeps the result."""

                def __init__(self, base_currency: str) -> None:
                    """Name the thread after the base currency it fetches rates for."""
                    super().__init__(name=f"rates-{base_currency}")
                    self.base_currency = base_currency
                    self.rates: dict[str, float] = {}

                def run(self) -> None:
                    """Called in the new thread by start()."""
                    url = f"{SHOP_API}/rates?base={self.base_currency}"
                    with urllib.request.urlopen(url, timeout=5) as reply:
                        self.rates = json.load(reply)["rates"]


            fetcher = PriceFetcher("INR")
            fetcher.start()
            fetcher.join()
            print(f"subclass: {fetcher.name} -> {fetcher.rates}")


            def fetch_rates(base_currency: str, results: dict[str, dict[str, float]]) -> None:
                """The same work as a plain function, usable with or without threads."""
                with urllib.request.urlopen(f"{SHOP_API}/rates?base={base_currency}", timeout=5) as reply:
                    results[base_currency] = json.load(reply)["rates"]


            rate_results: dict[str, dict[str, float]] = {}
            plain = threading.Thread(target=fetch_rates, args=("INR", rate_results))
            plain.start()
            plain.join()
            print(f"target:   {plain.name} -> {rate_results}")
            '''
        ),
        md(
            """
            | Style | Use it when |
            | --- | --- |
            | `Thread(target=func, args=...)` | almost always: the work stays a testable function |
            | `class Worker(Thread): def run(self)` | the thread is a long-lived object with its own state and methods (a poller, a server loop) |
            | `ThreadPoolExecutor().submit(func, ...)` | you want return values and exceptions back (5.1.8): the default for new code |

            > **Note:** override `run()`, never `start()`. And call `super().__init__()` in a
            > subclass's `__init__`, or `start()` fails with
            > `RuntimeError: thread.__init__() not called`.
            """
        ),
    ]


def _gil_cells() -> list[NotebookNode]:
    """5.1.3 The Global Interpreter Lock."""
    return [
        md(
            """
            ### 5.1.3 The Global Interpreter Lock

            **What it protects.** The GIL is a lock inside the interpreter. In the default
            build a thread must hold it to execute bytecode or touch Python objects. It
            protects CPython's *own* state: reference counts (incremented and decremented
            with plain, non-atomic instructions), the internals of `dict`, `list` and other
            built-ins, the memory allocator, the import system. It does **not** protect
            your program's invariants across several bytecodes (5.1.4).

            **Why it exists.** Reference counting (Unit 3.1) touches a counter on almost
            every operation; making every one of those atomic or locked would slow
            single-threaded code. One big lock made CPython simple and fast for one thread,
            and made C extensions easy to write (they could assume no other Python code runs
            concurrently). PEP 703's free-threaded build removes it at a cost (5.1.10).

            **When it is released.**

            | Situation | What happens |
            | --- | --- |
            | Blocking I/O: `socket.recv`, `file.read`, `select`, `subprocess` waits | the C code releases the GIL around the system call |
            | `time.sleep(seconds)` | released for the whole sleep |
            | C extensions doing long work: `hashlib` (data over 2 KiB), `zlib`, `bz2`, `lzma`, NumPy, `sqlite3` queries | released if the extension says so (`Py_BEGIN_ALLOW_THREADS`) |
            | A pure-Python loop | **not released voluntarily**; after the switch interval another thread asks for it and the eval loop hands it over at the next check |

            ```mermaid
            sequenceDiagram
                participant A as Thread A (CPU loop)
                participant G as GIL
                participant B as Thread B (waiting)
                A->>G: holds the GIL, runs bytecode
                B->>G: waits up to the switch interval (5 ms), then sets "drop request"
                G-->>A: eval breaker: A drops the GIL at the next check
                G->>B: B takes the GIL and runs
                A->>G: A waits for its turn
            ```

            <details><summary>ASCII fallback</summary>

            ```text
            Thread A: [run bytecode .......5 ms.......] drop -> wait ............ [run ...
            Thread B: wait ......... set drop request -> [run bytecode ...5 ms...] drop
                        a waiting thread asks after `sys.getswitchinterval()` seconds
            ```

            </details>

            **The switch interval.** `sys.getswitchinterval()` is 0.005 s by default. The
            next cell reuses `count_thread_switches` from Unit 3.2.10: two CPU-bound threads
            count how often the running thread changes in 0.2 s, at two intervals.
            """
        ),
        code(
            '''
            def count_thread_switches(switch_interval: float, duration: float = 0.2) -> int:
                """Two CPU-bound threads; count how often the running thread changes."""
                state = {"owner": "", "switches": 0}
                deadline = time.perf_counter() + duration

                def spin(name: str) -> None:
                    """Spin until the deadline, counting each change of the running thread."""
                    while time.perf_counter() < deadline:
                        if state["owner"] != name:
                            state["owner"] = name
                            state["switches"] += 1

                original_interval = sys.getswitchinterval()
                sys.setswitchinterval(switch_interval)
                try:
                    threads = [threading.Thread(target=spin, args=(name,)) for name in ("A", "B")]
                    for thread in threads:
                        thread.start()
                    for thread in threads:
                        thread.join()
                finally:
                    sys.setswitchinterval(original_interval)
                return state["switches"]


            print(f"{sys.getswitchinterval()=}  [{interpreter_label()}]")
            for interval in (0.005, 0.0005):
                print(
                    f"switch interval {interval * 1000:>4} ms -> "
                    f"{count_thread_switches(interval):>5} switches in 0.2 s"
                )
            '''
        ),
        md(
            """
            About 40 switches in 0.2 s at 5 ms (one every 5 ms), about ten times more at
            0.5 ms. A shorter interval makes threads more responsive but adds handoff
            overhead; leave it alone in real code.

            #### Benchmark: CPU-bound work in threads

            The same total work (`busy_sum` over 8 million numbers × `DEMO_SCALE`) split
            across 1, 2 and 4 threads. With the GIL only one thread executes bytecode at a
            time, so expect the wall time to stay about the same (or get slightly worse
            from handoffs).
            """
        ),
        code(
            '''
            def run_in_threads(work: Callable[[int], object], items: list[int]) -> float:
                """Run work(item) for every item, one thread per item; return wall seconds."""
                threads = [threading.Thread(target=work, args=(item,)) for item in items]
                start = time.perf_counter()
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
                return time.perf_counter() - start


            total_numbers = 8_000_000 * DEMO_SCALE
            print(f"[{interpreter_label()}] busy_sum over {total_numbers:,} numbers in total")
            cpu_baseline = 0.0
            for thread_count in (1, 2, 4):
                seconds = run_in_threads(busy_sum, [total_numbers // thread_count] * thread_count)
                cpu_baseline = cpu_baseline or seconds
                print(
                    f"{thread_count} thread(s): {seconds:.3f} s   "
                    f"speedup vs 1 thread: {cpu_baseline / seconds:.2f}x"
                )
            '''
        ),
        md(
            """
            #### Benchmark: I/O-bound work in threads

            Now 8 requests to the local API, each of which waits 0.1 s on the server. While
            a thread waits on its socket it has released the GIL, so the waits overlap.
            """
        ),
        code(
            """
            request_count = 8
            print(f"{request_count} requests, each waiting 0.1 s on the server")
            io_baseline = 0.0
            for thread_count in (1, 2, 4, 8):
                per_thread = request_count // thread_count
                seconds = run_in_threads(
                    lambda repeat: [fetch_slow_page(0.1) for _ in range(repeat)], [per_thread] * thread_count
                )
                io_baseline = io_baseline or seconds
                print(
                    f"{thread_count} thread(s): {seconds:.3f} s   "
                    f"speedup vs 1 thread: {io_baseline / seconds:.2f}x"
                )
            """
        ),
        md(
            """
            Close to linear: 8 threads take about as long as one request. Same threads, same
            GIL, opposite result; the difference is *where the time goes*.

            **`sleep` releases the GIL.** While the main thread sleeps for 50 ms, a
            background thread keeps counting. If `sleep` held the GIL the count would stay
            at zero.
            """
        ),
        code(
            '''
            progress = {"count": 0}
            stop_counting = threading.Event()


            def count_until_stopped() -> None:
                """CPU loop that counts until the event is set."""
                while not stop_counting.is_set():
                    progress["count"] += 1


            counter_thread = threading.Thread(target=count_until_stopped)
            counter_thread.start()
            before_sleep = progress["count"]
            time.sleep(0.05)  # the main thread releases the GIL here
            during_sleep = progress["count"] - before_sleep
            stop_counting.set()
            counter_thread.join()
            print(f"the other thread counted {during_sleep:,} times while the main thread slept 50 ms")
            '''
        ),
        md(
            """
            **C extensions release it too.** `hashlib` releases the GIL while it hashes
            buffers larger than 2 KiB, so hashing four 32 MiB buffers in four threads runs
            on four cores. Hashing 100 000 tiny 64-byte strings spends its time in Python
            (calls, loop) with the GIL held, so threads do not help there.
            """
        ),
        code(
            '''
            big_buffers = [os.urandom(32 * 1024 * 1024) for _ in range(4)]
            tiny_messages = [os.urandom(64) for _ in range(100_000)]


            def hash_big(index: int) -> None:
                """Hash one large buffer DEMO_SCALE times (the GIL is released inside)."""
                for _ in range(DEMO_SCALE):
                    hashlib.sha256(big_buffers[index]).digest()


            def hash_tiny(index: int) -> None:
                """Hash a quarter of the tiny messages (mostly Python overhead)."""
                for _ in range(DEMO_SCALE):
                    for message in tiny_messages[index::4]:
                        hashlib.sha256(message).digest()


            def all_four(work: Callable[[int], None]) -> None:
                """Do the four pieces of work one after another (the 1-thread baseline)."""
                for index in range(4):
                    work(index)


            for label, work in (("4 x 32 MiB buffers", hash_big), ("100 000 x 64 B messages", hash_tiny)):
                sequential = run_in_threads(all_four, [work])
                threaded = run_in_threads(work, [0, 1, 2, 3])
                print(
                    f"{label:<24} 1 thread {sequential:.3f} s | 4 threads "
                    f"{threaded:.3f} s | {sequential / threaded:.2f}x"
                )
            big_buffers.clear()  # free 128 MiB
            '''
        ),
        md(
            """
            > **Note:** "Is my workload CPU-bound in Python, or CPU-bound in C code that
            > releases the GIL?" decides whether threads help. NumPy, `hashlib`, `zlib`,
            > image codecs and database drivers often release it; your own `for` loops never
            > do (on the default build).

            **Under the hood.** Whether this interpreter has a GIL is a build-time property
            (`Py_GIL_DISABLED`) plus a runtime switch on free-threaded builds
            (`sys._is_gil_enabled()`, *new in 3.13*).
            """
        ),
        code(
            """
            print(f"{sysconfig.get_config_var('Py_GIL_DISABLED')=}")
            print(f"{sys._is_gil_enabled()=}")
            print(f"{sys.getswitchinterval()=}")
            """
        ),
    ]


def _race_cells() -> list[NotebookNode]:
    """5.1.4 Race conditions."""
    return [
        md(
            """
            ### 5.1.4 Race conditions

            A **race condition** is a bug whose outcome depends on how threads happen to
            interleave. It needs shared mutable state and at least one writer, and it
            usually hides in a *read–modify–write* or *check-then-act* sequence.

            **`counter += 1` is not atomic.** One line of Python, several bytecodes: load
            the value, add one, store the result. A thread switch between the load and the
            store means another thread's increment is overwritten.
            """
        ),
        code(
            '''
            stock_counter = 0


            def add_one() -> None:
                """Increment a module-level counter."""
                global stock_counter
                stock_counter += 1


            print(f"# dis on {interpreter_label()} (instruction names change between versions)")
            dis.dis(add_one)
            '''
        ),
        md(
            """
            Read the listing as three steps: `LOAD_GLOBAL stock_counter` (read), `BINARY_OP
            ... (+=)` (modify), `STORE_GLOBAL stock_counter` (write). Two threads can both
            read 41, both compute 42, and both store 42: one increment is lost.

            **Demo 1: plain `+=` on the default build.** Four threads add 100 000 each.
            """
        ),
        code(
            '''
            class PlainCounter:
                """A counter with no locking at all."""

                def __init__(self) -> None:
                    """Start at zero."""
                    self.value = 0


            def add_many(counter: PlainCounter, times: int) -> None:
                """Increment counter.value `times` times with +=."""
                for _ in range(times):
                    counter.value += 1


            plain_counter = PlainCounter()
            run_in_threads(lambda _: add_many(plain_counter, 100_000), [0, 1, 2, 3])
            print(f"[{interpreter_label()}] expected 400,000, got {plain_counter.value:,}")
            '''
        ),
        md(
            """
            On CPython 3.15's default build this usually prints the right total, and that
            is the trap. The eval loop only hands the GIL over at certain instructions (loop
            back-edges and calls), which here fall *between* increments, never inside one.
            That is an implementation detail, not a guarantee: other Python versions,
            a function call inside the loop, or the free-threaded build (5.1.10 runs this
            exact code there) lose updates.

            **Demo 2: make the window visible.** `time.sleep(0)` between the read and the
            write gives up the GIL, the way any I/O or call into slow code would. Now
            updates are lost on every build.
            """
        ),
        code(
            '''
            class YieldingCounter:
                """Read, give up the GIL, then write: the classic lost-update race."""

                def __init__(self) -> None:
                    """Start at zero."""
                    self.value = 0

                def increment(self) -> None:
                    """Read, yield the GIL, then write: two threads can lose an update."""
                    current = self.value  # read
                    time.sleep(0)  # another thread can run here
                    self.value = current + 1  # write (may overwrite someone else's update)


            yielding_counter = YieldingCounter()
            run_in_threads(lambda _: [yielding_counter.increment() for _ in range(500)], [0, 1, 2, 3])
            print(f"expected 2,000, got {yielding_counter.value:,}")
            '''
        ),
        md(
            """
            **Check-then-act.** The check is correct when it runs, but the world changes
            before the action. Five customers try to buy the last three phone cases; each
            checks stock, then (after a pause that stands for a database round trip)
            decrements it.
            """
        ),
        code(
            '''
            stock = {"phone-case": 3}
            sales: list[str] = []


            def buy(customer: str) -> None:
                """Check stock, pause, then sell: racy."""
                if stock["phone-case"] > 0:  # check
                    time.sleep(0.01)  # e.g. charge the card
                    stock["phone-case"] -= 1  # act
                    sales.append(customer)


            run_in_threads(buy, ["Asha", "Ravi", "Meena", "John", "Fatima"])
            print(f"sold {len(sales)} of 3 cases; stock is now {stock['phone-case']}")
            '''
        ),
        md(
            """
            All five checks saw `3 > 0` before anyone decremented, so the shop oversold and
            stock went negative. The same pattern hides in lazy initialization: `if key not
            in cache: cache[key] = load(key)` can call `load` once per thread.
            """
        ),
        code(
            '''
            cache: dict[str, str] = {}
            load_calls: list[str] = []


            def load_profile(user_id: str) -> str:
                """Expensive load (counts how often it runs)."""
                load_calls.append(threading.current_thread().name)
                time.sleep(0.01)
                return f"profile of {user_id}"


            def get_profile(user_id: str) -> str:
                """Racy lazy cache."""
                if user_id not in cache:
                    cache[user_id] = load_profile(user_id)
                return cache[user_id]


            run_in_threads(get_profile, ["u-42"] * 4)
            print(f"load_profile ran {len(load_calls)} times for one key")
            '''
        ),
        md(
            """
            #### What is atomic?

            "Atomic" here means: no other thread can observe a half-done state. In CPython,
            single operations on built-in containers are atomic. The default build gets that
            from the GIL; the free-threaded build keeps the same guarantees with per-object
            locks. This is documented in the
            [FAQ](https://docs.python.org/3/faq/library.html#what-kinds-of-global-value-mutation-are-thread-safe),
            but it is a CPython property, not a language promise.

            | Atomic (one operation on a built-in) | Not atomic (several steps) |
            | --- | --- |
            | `items.append(x)`, `items.pop()`, `items[i] = x` | `counter += 1`, `items[i] += 1` |
            | `mapping[key] = value`, `mapping.get(key)`, `mapping.pop(key, None)` | `if key not in mapping: mapping[key] = value` |
            | `mapping.setdefault(key, value)` | `mapping[key] = mapping.get(key, 0) + 1` |
            | `deque.append(x)`, `deque.popleft()` | iterating a list or dict while another thread changes it |
            | `name = other_object` (rebinding) | keeping two objects consistent with each other |
            | `next(it)` on built-in iterators such as `itertools.count` | `next(generator)` from two threads (raises `ValueError`) |

            Rule of thumb: if correctness depends on two steps happening together, use a
            lock. The next cell shows the atomic side: 4 threads × 50 000 `append`s always
            give exactly 200 000 items, and `setdefault` picks exactly one winner.
            """
        ),
        code(
            """
            shared_items: list[int] = []
            run_in_threads(lambda _: [shared_items.append(1) for _ in range(50_000)], [0, 1, 2, 3])
            print(f"{len(shared_items)=:,} (expected 200,000)")

            winners: dict[str, str] = {}
            claims: list[str] = []
            run_in_threads(
                lambda name: claims.append(winners.setdefault("seat-1A", name)), ["Asha", "Ravi", "Meena"]
            )
            print(f"setdefault winner seen by every thread: {set(claims) == {winners['seat-1A']}}")
            """
        ),
        md(
            """
            **Generators are not thread-safe.** Two threads calling `next()` on the same
            generator at the same moment get `ValueError: generator already executing`.
            *New in 3.15:* `threading.serialize_iterator(iterator)` wraps any iterator (or
            generator) with a lock around `__next__`, and `threading.synchronized_iterator`
            does the same as a decorator for generator functions. The cell is guarded so it
            prints a skip message on older kernels.
            """
        ),
        code(
            '''
            def order_numbers(count: int) -> Iterator[int]:
                """A generator with a pause inside, so two threads overlap in next()."""
                for number in range(count):
                    time.sleep(0.0005)
                    yield number


            def drain(source: Iterator[int], taken: list[int], errors: list[str]) -> None:
                """Consume the shared iterator, recording values and errors."""
                try:
                    for number in source:
                        taken.append(number)
                except ValueError as error:
                    errors.append(str(error))


            def share_between_two_threads(shared_source: Iterator[int]) -> str:
                """Let two threads drain one iterator; summarize what they got."""
                taken: list[int] = []
                errors: list[str] = []
                run_in_threads(lambda _: drain(shared_source, taken, errors), [0, 1])
                return (
                    f"items taken={len(taken)}, no duplicates={len(set(taken)) == len(taken)}, errors={errors}"
                )


            print(f"bare generator:     {share_between_two_threads(order_numbers(200))}")
            if hasattr(threading, "serialize_iterator"):
                print(
                    "serialize_iterator: "
                    f"{share_between_two_threads(threading.serialize_iterator(order_numbers(200)))}"
                )
            else:
                print("serialize_iterator: SKIP (new in 3.15)")
            '''
        ),
    ]


def _primitive_cells() -> list[NotebookNode]:
    """5.1.5 Synchronization primitives."""
    return [
        md(
            """
            ### 5.1.5 Synchronization primitives

            | Primitive | What it does | Typical use | JS analogue |
            | --- | --- | --- | --- |
            | `Lock` | one holder at a time; not reentrant | protect a read–modify–write | `Atomics` on a `SharedArrayBuffer`, or a promise-based mutex library |
            | `RLock` | like `Lock`, but the holding thread may re-acquire it | recursive or layered code that locks the same object | — |
            | `Semaphore(n)` | at most `n` holders | cap concurrent calls to a service | `p-limit` |
            | `BoundedSemaphore(n)` | a semaphore that raises if released more than acquired | the same, with a bug check: prefer it | — |
            | `Event` | a flag threads can wait for | "start now", "stop now" | a promise that resolves once |
            | `Condition` | a lock plus wait/notify on a predicate | "wait until stock > 0" | `Atomics.wait` / `notify` |
            | `Barrier(n)` | blocks until `n` threads arrive | phases that must start together | `Promise.all` used as a rendezvous |
            | `Timer(delay, f)` | a thread that calls `f` after `delay` unless cancelled | timeouts, debouncing | `setTimeout` / `clearTimeout` |

            All of them are context managers where it makes sense (`with lock:`), which
            guarantees the release even when the body raises.

            #### `Lock`

            The lost-update counter from 5.1.4, fixed: the read and the write happen while
            the lock is held, so no other thread can interleave.
            """
        ),
        code(
            '''
            class LockedYieldingCounter:
                """The yielding counter from 5.1.4 with its read-modify-write under a lock."""

                def __init__(self) -> None:
                    """Start at zero with a lock that guards the read-modify-write."""
                    self.value = 0
                    self._lock = threading.Lock()

                def increment(self) -> None:
                    """Read and write under the lock, so no update is lost."""
                    with self._lock:
                        current = self.value
                        time.sleep(0)  # other threads may run, but cannot enter this block
                        self.value = current + 1


            locked_counter = LockedYieldingCounter()
            run_in_threads(lambda _: [locked_counter.increment() for _ in range(500)], [0, 1, 2, 3])
            print(f"expected 2,000, got {locked_counter.value:,}")
            '''
        ),
        md(
            """
            `acquire()` can also be non-blocking or time-limited, and `locked()` reports the
            state. A plain `Lock` is **not reentrant**: the thread holding it blocks forever
            if it tries again. Here the second attempt uses `blocking=False` so the cell
            does not hang.
            """
        ),
        code(
            """
            inventory_lock = threading.Lock()
            print(f"{inventory_lock.acquire()=}  {inventory_lock.locked()=}")
            print(f"second acquire, same thread, non-blocking: {inventory_lock.acquire(blocking=False)}")
            from_other_thread: list[bool] = []
            run_in_threads(lambda _: from_other_thread.append(inventory_lock.acquire(timeout=0.05)), [0])
            print(f"acquire(timeout=0.05) from another thread: {from_other_thread[0]}")
            inventory_lock.release()
            print(f"after release: {inventory_lock.locked()=}")
            """
        ),
        md(
            """
            #### `RLock`

            A reentrant lock counts how many times its owner acquired it and frees it only
            after the same number of releases. It fits recursive code: totalling a category
            tree locks the tree at every level. With a plain `Lock` the recursive call would
            deadlock; the `timeout` in the plain-lock version turns that into a `False`.
            """
        ),
        code(
            '''
            category_tree = {"Tea": {"Green": {}, "Black": {"Assam": {}, "Darjeeling": {}}}}


            def count_categories(tree: dict[str, dict], lock: threading.Lock | threading.RLock) -> int:
                """Count nodes, taking the lock at every level of recursion."""
                if not lock.acquire(timeout=0.1):
                    raise TimeoutError("could not re-acquire the lock (it is not reentrant)")
                try:
                    return sum(1 + count_categories(children, lock) for children in tree.values())
                finally:
                    lock.release()


            print(f"RLock: {count_categories(category_tree, threading.RLock())} categories")
            print(f"Lock:  {raised_message(lambda: count_categories(category_tree, threading.Lock()))}")
            '''
        ),
        md(
            """
            #### `Semaphore`

            A semaphore holds a counter: `acquire()` decrements it (blocking at zero),
            `release()` increments it. Ten threads call a payment gateway that allows three
            concurrent requests; the semaphore keeps the peak at three.
            """
        ),
        code(
            '''
            gateway_slots = threading.Semaphore(3)
            in_flight = {"now": 0, "peak": 0}
            in_flight_lock = threading.Lock()


            def charge_card(order_id: int) -> None:
                """Call the 'gateway' while holding one of the three slots."""
                with gateway_slots:
                    with in_flight_lock:
                        in_flight["now"] += 1
                        in_flight["peak"] = max(in_flight["peak"], in_flight["now"])
                    time.sleep(0.02)  # the network call
                    with in_flight_lock:
                        in_flight["now"] -= 1


            seconds = run_in_threads(charge_card, list(range(10)))
            print(f"peak concurrent charges: {in_flight['peak']} (limit 3); 10 charges took {seconds:.2f} s")
            '''
        ),
        md(
            """
            #### `BoundedSemaphore`

            A plain `Semaphore` accepts extra `release()` calls silently, so a bug that
            releases twice raises the limit for good. `BoundedSemaphore` raises
            `ValueError` instead. Prefer it whenever releases should match acquires.
            """
        ),
        code(
            '''
            def acquirable(semaphore: threading.Semaphore) -> int:
                """How many non-blocking acquires succeed (then release them all again)."""
                count = 0
                while semaphore.acquire(blocking=False):
                    count += 1
                for _ in range(count):
                    semaphore.release()
                return count


            loose = threading.Semaphore(2)
            loose.release()  # a bug: one release too many
            print(f"Semaphore(2) after an extra release allows {acquirable(loose)} holders")

            strict = threading.BoundedSemaphore(2)
            print(f"BoundedSemaphore(2) extra release: {raised_message(strict.release)}")
            '''
        ),
        md(
            """
            #### `Event`

            An event is a boolean flag with `set()`, `clear()`, `is_set()` and
            `wait(timeout)`. Workers block on `wait()` until the main thread sets it: all
            three start at (almost) the same moment. `wait(timeout)` returns `False` if the
            timeout passes first.
            """
        ),
        code(
            '''
            shop_open = threading.Event()
            start_times: dict[str, float] = {}


            def cashier(name: str) -> None:
                """Wait for the shop to open, then record the start time."""
                shop_open.wait()
                start_times[name] = time.perf_counter()


            cashiers = [
                threading.Thread(target=cashier, args=(name,)) for name in ("till-1", "till-2", "till-3")
            ]
            for till in cashiers:
                till.start()
            time.sleep(0.05)
            print(f"before set: {shop_open.is_set()=}, started={len(start_times)}")
            shop_open.set()
            for till in cashiers:
                till.join()
            spread_ms = (max(start_times.values()) - min(start_times.values())) * 1000
            print(f"after set: started={len(start_times)}, spread {spread_ms:.2f} ms")
            shop_open.clear()
            print(f"after clear, wait(timeout=0.02) returns {shop_open.wait(timeout=0.02)}")
            '''
        ),
        md(
            """
            #### `Condition`

            A condition variable combines a lock with "wait until something is true".
            `wait_for(predicate)` releases the lock while waiting and re-checks the
            predicate after every `notify`. Here two packers wait for stock; a delivery
            thread adds items and calls `notify_all()`.
            """
        ),
        code(
            '''
            stock_arrived = threading.Condition()
            warehouse: list[str] = []
            packed: list[str] = []


            def packer(name: str, wanted: int) -> None:
                """Wait until enough items exist, then take them."""
                with stock_arrived:
                    stock_arrived.wait_for(lambda: len(warehouse) >= wanted, timeout=2)
                    taken = [warehouse.pop() for _ in range(min(wanted, len(warehouse)))]
                    packed.append(f"{name} packed {len(taken)}")


            def deliver(items: list[str]) -> None:
                """Add items one by one, waking the waiters each time."""
                for item in items:
                    time.sleep(0.01)
                    with stock_arrived:
                        warehouse.append(item)
                        stock_arrived.notify_all()


            run_in_threads(
                lambda job: job(),
                [lambda: packer("packer-A", 2), lambda: packer("packer-B", 3), lambda: deliver(list("abcde"))],
            )
            print(f"{sorted(packed)}, left in warehouse: {warehouse}")
            '''
        ),
        md(
            """
            > **Note:** always wait in a loop (or with `wait_for`): a thread can wake up
            > without its condition being true (another thread took the stock first, or a
            > spurious wake-up). `notify()` wakes one waiter, `notify_all()` wakes all.

            #### `Barrier`

            A barrier for `n` parties blocks every caller of `wait()` until `n` have
            arrived, then releases them together; `wait()` returns a distinct index
            `0 … n-1` and an optional `action` runs once per round. If a party never
            arrives, `wait(timeout)` breaks the barrier and every waiter gets
            `BrokenBarrierError`.
            """
        ),
        code(
            '''
            report_ready = threading.Barrier(3, action=lambda: print("action: all 3 parts loaded, merging"))
            arrival_indexes: list[int] = []


            def load_part(seconds: float) -> None:
                """Load a part of a report, then wait for the others."""
                time.sleep(seconds)
                arrival_indexes.append(report_ready.wait())


            run_in_threads(load_part, [0.01, 0.03, 0.02])
            print(f"indexes returned by wait(): {sorted(arrival_indexes)}")

            lonely = threading.Barrier(2)
            print(f"only 1 of 2 parties arrives: {raised_error_name(lambda: lonely.wait(timeout=0.05))}")
            print(f"{lonely.broken=}")
            '''
        ),
        md(
            """
            #### `Timer`

            `threading.Timer(delay, function, args)` is a `Thread` subclass that waits
            `delay` seconds, then calls the function, unless `cancel()` was called first.
            """
        ),
        code(
            """
            reminders: list[str] = []
            fires = threading.Timer(0.05, reminders.append, args=("payment reminder sent",))
            cancelled = threading.Timer(0.05, reminders.append, args=("this never happens",))
            fires.start()
            cancelled.start()
            cancelled.cancel()  # before the delay is over
            fires.join()
            cancelled.join()
            print(f"{reminders=}  {isinstance(fires, threading.Thread)=}")
            """
        ),
        md(
            """
            #### Deadlocks and prevention

            A **deadlock** is a set of threads each waiting for a lock another one holds.
            It needs all four (Coffman) conditions: mutual exclusion, hold-and-wait, no
            preemption, and a **circular wait**. Remove any one and deadlock is impossible.

            | Prevention | How | Breaks |
            | --- | --- | --- |
            | Lock ordering | every thread takes locks in one global order (for example by id) | circular wait |
            | Try-lock with back-off | `acquire(timeout=...)`; on failure release everything, wait a random moment, retry | hold-and-wait |
            | One coarser lock | protect both resources with a single lock | hold-and-wait (at the cost of concurrency) |
            | Don't hold a lock while calling unknown code | callbacks, I/O and other objects' methods may take locks of their own | hidden cycles |
            | Share by message passing | hand work to one owner thread through a `Queue` (5.1.6) | mutual exclusion on shared data |

            The demo: one thread updates the *inventory* then the *ledger*, another the
            ledger then the inventory. A `Barrier` makes both take their first lock before
            either asks for its second, so the circular wait happens every time; the
            `acquire(timeout=0.2)` turns the hang into a reported failure.
            """
        ),
        code(
            '''
            def lock_pair_naive(
                first: threading.Lock, second: threading.Lock, both_hold_one: threading.Barrier
            ) -> str:
                """Take first, wait until the other thread holds its first lock, then try second."""
                with first:
                    both_hold_one.wait()
                    if not second.acquire(timeout=0.2):
                        return "gave up: deadlock"
                    second.release()
                    return "done"


            inventory_lock, ledger_lock = threading.Lock(), threading.Lock()
            rendezvous = threading.Barrier(2)
            outcomes: list[str] = []
            run_in_threads(
                lambda locks: outcomes.append(lock_pair_naive(*locks, rendezvous)),
                [(inventory_lock, ledger_lock), (ledger_lock, inventory_lock)],
            )
            print(f"{outcomes=}")
            '''
        ),
        md(
            """
            Both threads held one lock and waited for the other: a circular wait. The first
            thread to time out gave up and released its lock, and only then could the other
            finish. Without the timeout both would wait forever (and the kernel would hang).

            **Fix with try-lock and back-off.** If the second lock is not free soon, release
            the first, sleep a short *random* time so the two threads stop colliding, and
            try again. (Lab 5.1 fixes a deadlock the other way, with lock ordering.)
            """
        ),
        code(
            '''
            def lock_pair_backoff(
                first: threading.Lock, second: threading.Lock, both_hold_one: threading.Barrier, seed: int
            ) -> str:
                """Acquire both locks or neither; retry with random back-off."""
                backoff = random.Random(seed)
                for attempt in range(1, 20):
                    with first:
                        if attempt == 1:
                            both_hold_one.wait()  # force the collision on the first try
                        if second.acquire(timeout=0.05):
                            second.release()
                            return f"done on attempt {attempt}"
                    time.sleep(backoff.uniform(0.0, 0.05))  # first is released here
                return "gave up"


            rendezvous = threading.Barrier(2)
            outcomes = []
            run_in_threads(
                lambda job: outcomes.append(lock_pair_backoff(job[0], job[1], rendezvous, seed=job[2])),
                [(inventory_lock, ledger_lock, 1), (ledger_lock, inventory_lock, 2)],
            )
            print(f"{sorted(outcomes)=}")
            '''
        ),
    ]


def _queue_cells() -> list[NotebookNode]:
    """5.1.6 Thread-safe queues."""
    return [
        md(
            """
            ### 5.1.6 Thread-safe queues

            The `queue` module gives thread-safe queues with the locking built in, which is
            usually the simplest correct design: threads share a queue instead of sharing
            data structures.

            | Class / method | Behaviour |
            | --- | --- |
            | `queue.Queue(maxsize=0)` | FIFO; `maxsize > 0` makes `put` block when full (back-pressure) |
            | `queue.LifoQueue` | LIFO (a stack) |
            | `queue.PriorityQueue` | smallest item first (a heap); put `(priority, tie_breaker, item)` tuples |
            | `put(item, block=True, timeout=None)`, `put_nowait` | `queue.Full` when it cannot add |
            | `get(block=True, timeout=None)`, `get_nowait` | `queue.Empty` when nothing arrives |
            | `task_done()`, `join()` | consumers mark items finished; `join()` waits until every `put` has a `task_done` |
            | `qsize()`, `empty()`, `full()` | snapshots only: another thread may change the answer immediately |
            | `shutdown(immediate=False)` | *new in 3.13*: later `put`s raise `queue.ShutDown`; `get` raises it once the queue is drained |

            **FIFO, LIFO and priority order** for the same three items:
            """
        ),
        code(
            """
            for queue_class in (queue.Queue, queue.LifoQueue):
                tickets = queue_class()
                for ticket in ("T-1 login bug", "T-2 typo", "T-3 outage"):
                    tickets.put(ticket)
                print(f"{queue_class.__name__:<10} -> {[tickets.get() for _ in range(3)]}")

            by_priority: queue.PriorityQueue[tuple[int, int, str]] = queue.PriorityQueue()
            arrival = itertools.count()  # tie-breaker: equal priorities keep arrival order
            for priority, ticket in (
                (3, "T-1 login bug"),
                (5, "T-2 typo"),
                (1, "T-3 outage"),
                (3, "T-4 slow page"),
            ):
                by_priority.put((priority, next(arrival), ticket))
            print(f"PriorityQueue -> {[by_priority.get()[2] for _ in range(4)]}")
            """
        ),
        md(
            """
            The tie-breaker matters: without it, two equal priorities would compare the
            next tuple element, and two items that cannot be compared (dicts, custom objects)
            raise `TypeError` inside the queue.

            **Bounded queues and timeouts.** `maxsize` makes a fast producer wait for a slow
            consumer instead of filling memory. The non-blocking and timeout forms raise
            `queue.Full` and `queue.Empty`.
            """
        ),
        code(
            """
            small_buffer: queue.Queue[str] = queue.Queue(maxsize=2)
            small_buffer.put("line 1")
            small_buffer.put("line 2")
            print(
                f"{small_buffer.full()=}  put_nowait: "
                f"{raised_error_name(lambda: small_buffer.put_nowait('line 3'))}"
            )
            print(f"put with timeout: {raised_error_name(lambda: small_buffer.put('line 3', timeout=0.02))}")
            print(f"{small_buffer.get()=}  {small_buffer.get()=}")
            print(
                f"get with timeout on empty queue: {raised_error_name(lambda: small_buffer.get(timeout=0.02))}"
            )
            """
        ),
        md(
            """
            **`task_done` and `join`.** Every `put` increments an "unfinished tasks"
            counter; every `task_done()` decrements it; `queue.join()` blocks until it is
            zero. That lets the producer wait until the work is *processed*, not just taken
            off the queue.
            """
        ),
        code(
            '''
            resize_jobs: queue.Queue[str] = queue.Queue()
            resized: list[str] = []


            def resize_worker() -> None:
                """Process jobs forever (a daemon thread); mark each one done."""
                while True:
                    image_name = resize_jobs.get()
                    time.sleep(0.01)
                    resized.append(image_name)
                    resize_jobs.task_done()


            threading.Thread(target=resize_worker, daemon=True, name="resizer").start()
            for image_name in ("a.png", "b.png", "c.png"):
                resize_jobs.put(image_name)
            print(f"right after put: {resize_jobs.unfinished_tasks=}")
            resize_jobs.join()
            print(f"after join:      {resize_jobs.unfinished_tasks=}, {resized=}")
            '''
        ),
        md(
            """
            That worker never ends: it is a daemon, so it would simply be killed at exit.

            **Sentinel shutdown.** To stop consumers cleanly, put one *sentinel* value per
            consumer after the real work. A unique `object()` is safer than `None`, which
            could be real data. Each consumer exits when it takes a sentinel, so `join()` on
            the threads returns.
            """
        ),
        code(
            '''
            STOP = object()  # sentinel: compared by identity
            log_lines: queue.Queue[object] = queue.Queue()
            error_counts: dict[str, int] = {}
            counts_lock = threading.Lock()


            def count_errors() -> None:
                """Consume log lines until the sentinel arrives."""
                while (line := log_lines.get()) is not STOP:
                    if " ERROR " in line:
                        reader = threading.current_thread().name
                        with counts_lock:
                            error_counts[reader] = error_counts.get(reader, 0) + 1
                    log_lines.task_done()
                log_lines.task_done()  # the sentinel counts as a task too


            consumers = [
                threading.Thread(target=count_errors, name=f"log-reader-{reader_number}")
                for reader_number in (1, 2)
            ]
            for consumer in consumers:
                consumer.start()
            for number in range(1, 101):
                log_lines.put(
                    f"2026-11-16 10:00:{number % 60:02d} "
                    f"{'ERROR' if number % 10 == 0 else 'INFO'} request {number}"
                )
            for _ in consumers:
                log_lines.put(STOP)
            for consumer in consumers:
                consumer.join()
            print(
                f"total errors: {sum(error_counts.values())}; "
                f"threads alive: {[consumer.is_alive() for consumer in consumers]}"
            )
            '''
        ),
        md(
            """
            **`Queue.shutdown()`** (*new in 3.13*) replaces the sentinel dance: after
            `shutdown()`, `put` raises `queue.ShutDown`, and `get` keeps returning the
            remaining items, then raises `queue.ShutDown` once the queue is empty.
            `shutdown(immediate=True)` drops the remaining items instead.
            """
        ),
        code(
            """
            if sys.version_info >= (3, 13):
                closing_queue: queue.Queue[str] = queue.Queue()
                for order_id in ("A-1", "A-2"):
                    closing_queue.put(order_id)
                closing_queue.shutdown()
                print(f"put after shutdown: {raised_error_name(lambda: closing_queue.put('A-3'))}")
                print(
                    f"drain: {closing_queue.get()}, {closing_queue.get()}, "
                    f"then {raised_error_name(closing_queue.get)}"
                )
            else:
                print("SKIP: Queue.shutdown is new in 3.13")
            """
        ),
    ]


def _thread_local_cells() -> list[NotebookNode]:
    """5.1.7 Thread-local state."""
    return [
        md(
            """
            ### 5.1.7 Thread-local state

            `threading.local()` creates an object whose attributes are **separate for every
            thread**: each thread sees only what it set itself. Web frameworks used this for
            "the current request" (Flask's `request`); in asyncio code the equivalent is
            `contextvars` (Unit 5.3), and in Node it is `AsyncLocalStorage`.

            Three request-handling threads store their user on a shared `local` object; a
            deeply nested function reads it without the value being passed around.
            """
        ),
        code(
            '''
            request_context = threading.local()
            audit_log: list[str] = []


            def write_audit(action: str) -> None:
                """Deep in the call stack: read the user of *this* thread's request."""
                audit_log.append(f"{request_context.user} {action}")


            def handle_request(user: str) -> None:
                """Set the per-thread context, then do work that needs it."""
                request_context.user = user
                time.sleep(0.01)  # other threads set their own user meanwhile
                write_audit("viewed orders")


            run_in_threads(handle_request, ["asha", "ravi", "meena"])
            print(sorted(audit_log))
            print(f"main thread: {raised_message(lambda: request_context.user)}")
            '''
        ),
        md(
            """
            The main thread never set `user`, so it gets `AttributeError`. Subclass `local`
            to give every thread defaults: `__init__` runs once **per thread**, the first
            time that thread touches the object.

            A real use: a `sqlite3` connection may only be used by the thread that created
            it (`check_same_thread=True`), so each worker thread keeps its own connection.
            """
        ),
        code(
            '''
            class PerThreadDatabase(threading.local):
                """One in-memory SQLite connection per thread, created on first use."""

                def __init__(self) -> None:
                    """Open a private in-memory database and record the owning thread."""
                    self.connection = sqlite3.connect(":memory:")
                    self.owner = threading.current_thread().name


            shared_connection = sqlite3.connect(":memory:")
            print("shared connection used from another thread:")
            run_in_threads(
                lambda _: print(" ", raised_error_name(lambda: shared_connection.execute("select 1"))), [0]
            )

            per_thread_db = PerThreadDatabase()
            connections_seen: list[sqlite3.Connection] = []


            def query_in_thread(_: object) -> None:
                """Use this thread's own connection (created on first access)."""
                connections_seen.append(per_thread_db.connection)
                per_thread_db.connection.execute("select 1")


            run_in_threads(query_in_thread, [0, 1])
            print(f"each worker got its own connection: {connections_seen[0] is not connections_seen[1]}")
            print(f"the main thread's is a third one: {per_thread_db.connection not in connections_seen}")
            print(f"main thread owner: {per_thread_db.owner}")
            '''
        ),
        md(
            """
            > **Warning:** thread pools reuse threads, so thread-local values **leak from
            > one task to the next** on the same worker. Reset them at the start of each
            > task (or use `contextvars`, which executors and asyncio copy per task).
            """
        ),
        code(
            '''
            task_local = threading.local()


            def tag_task(task_name: str) -> str:
                """Report what the previous task on this thread left behind, then tag it."""
                leftover = getattr(task_local, "task", None)
                task_local.task = task_name
                return f"{task_name} saw leftover {leftover!r}"


            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as single_worker:
                print(list(single_worker.map(tag_task, ["task-1", "task-2", "task-3"])))
            '''
        ),
    ]


def _executor_cells() -> list[NotebookNode]:
    """5.1.8 concurrent.futures.ThreadPoolExecutor."""
    return [
        md(
            """
            ### 5.1.8 `concurrent.futures.ThreadPoolExecutor`

            An executor owns a pool of worker threads and a work queue. You hand it
            callables; it hands back `Future` objects, which hold the eventual result **or
            exception**. This is the high-level API to reach for first.

            | API | What it does |
            | --- | --- |
            | `ThreadPoolExecutor(max_workers=None, thread_name_prefix="")` | pool; threads start lazily as work arrives |
            | `executor.submit(fn, *args, **kwargs)` | schedule one call; returns a `Future` immediately |
            | `executor.map(fn, *iterables, timeout=None, buffersize=None)` | results **in input order**; raises a task's exception when you reach it |
            | `as_completed(futures, timeout=None)` | yields futures **in completion order** |
            | `wait(futures, timeout=None, return_when=ALL_COMPLETED)` | returns `(done, not_done)` sets; also `FIRST_COMPLETED`, `FIRST_EXCEPTION` |
            | `future.result(timeout)`, `exception(timeout)` | block for the outcome; `result()` re-raises the task's exception |
            | `future.done()`, `running()`, `cancelled()`, `cancel()` | state; only a *pending* future can be cancelled |
            | `future.add_done_callback(fn)` | call `fn(future)` when it finishes |
            | `executor.shutdown(wait=True, cancel_futures=False)` | stop accepting work; `with` calls it for you |

            **`submit` and `Future`.** `slow_echo` waits on the local API for the given
            time, then returns its first argument. (In JS terms: `submit` is like calling an
            async function; the `Future` is the promise. But `result()` *blocks* the
            calling thread instead of being awaited.)
            """
        ),
        code(
            '''
            def slow_echo(value: str, seconds: float) -> str:
                """Wait `seconds` on the local API, then return value."""
                fetch_slow_page(seconds)
                return value


            with concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="shop") as executor:
                invoice_future = executor.submit(slow_echo, "invoice-17", 0.2)
                time.sleep(0.02)
                print(f"just after submit: done={invoice_future.done()}, running={invoice_future.running()}")
                print(f"result(timeout=5) -> {invoice_future.result(timeout=5)!r}")
                print(
                    f"afterwards:        done={invoice_future.done()}, exception={invoice_future.exception()}"
                )
                print(
                    f"worker thread name: {executor.submit(lambda: threading.current_thread().name).result()}"
                )
            '''
        ),
        md(
            """
            **Cancelling and callbacks.** With one worker, the first task runs and the
            others wait in the queue. `cancel()` succeeds only for a task that has not
            started. A done-callback runs in the worker thread that finished the task (or
            immediately in the caller if the future is already done).
            """
        ),
        code(
            """
            finished: list[str] = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                running_job = executor.submit(slow_echo, "job-1", 0.1)
                queued_job = executor.submit(slow_echo, "job-2", 0.1)
                doomed_job = executor.submit(slow_echo, "job-3", 0.1)
                for job in (running_job, queued_job, doomed_job):
                    job.add_done_callback(
                        lambda done: finished.append("cancelled" if done.cancelled() else done.result())
                    )
                time.sleep(0.02)
                print(f"cancel running job-1: {running_job.cancel()}")
                print(f"cancel queued job-3:  {doomed_job.cancel()}")
            print(f"callbacks saw: {finished}")
            """
        ),
        md(
            """
            **`map`: input order, not finish order.** The three tasks finish in the order
            0.1 s, 0.2 s, 0.3 s, but `map` yields results in the order you passed them. The
            total time is the slowest task, not the sum. `timeout` applies to the whole
            iteration and raises `TimeoutError` (the built-in, since 3.11) when exceeded.
            """
        ),
        code(
            """
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                with Timer("map over 0.3 s, 0.1 s, 0.2 s tasks"):
                    print(list(executor.map(slow_echo, ["slow", "fast", "medium"], [0.3, 0.1, 0.2])))
                too_slow = executor.map(slow_echo, ["late"], [0.3], timeout=0.05)
                print(f"with timeout=0.05: {raised_error_name(lambda: list(too_slow))}")
            """
        ),
        md(
            """
            **`map` with `buffersize`** (*new in 3.14*). Plain `map` submits a task for
            every input item straight away, so it reads the whole input iterable up front
            (an infinite generator would hang). `buffersize=n` keeps at most `n` tasks in
            flight and reads more input only as you consume results.
            """
        ),
        code(
            '''
            def numbered_rows(limit: int, consumed: list[int]) -> Iterator[int]:
                """Yield 0..limit-1, recording how many rows were read."""
                for row_number in range(limit):
                    consumed.append(row_number)
                    yield row_number


            if sys.version_info >= (3, 14):
                for buffer_size in (None, 4):
                    consumed_rows: list[int] = []
                    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                        squares = executor.map(
                            lambda row_number: row_number * row_number,
                            numbered_rows(10_000, consumed_rows),
                            buffersize=buffer_size,
                        )
                        first_square = next(squares)
                        print(
                            f"buffersize={buffer_size}: first result {first_square}, "
                            f"rows read so far: {len(consumed_rows):,}"
                        )
            else:
                print("SKIP: Executor.map(buffersize=) is new in 3.14")
            '''
        ),
        md(
            """
            **`as_completed`: finish order.** Use it when you want to handle each result as
            soon as it is ready (show progress, start follow-up work). Keep a dict from
            future to input so you know which task finished.
            """
        ),
        code(
            """
            delays = {"report-A": 0.3, "report-B": 0.1, "report-C": 0.2}
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                future_to_name = {
                    executor.submit(slow_echo, name, seconds): name for name, seconds in delays.items()
                }
                print(
                    "completion order:",
                    [future.result() for future in concurrent.futures.as_completed(future_to_name)],
                )
                stragglers = [executor.submit(slow_echo, "late", 0.3)]
                waiting = concurrent.futures.as_completed(stragglers, timeout=0.05)
                print(f"as_completed(timeout=0.05): {raised_error_name(lambda: list(waiting))}")
            """
        ),
        md(
            """
            **`wait`.** Returns two sets, `done` and `not_done`, when the condition is met.
            `FIRST_COMPLETED` is handy for "take the fastest mirror"; `FIRST_EXCEPTION`
            stops waiting as soon as one task fails.
            """
        ),
        code(
            '''
            def fail_after(seconds: float) -> str:
                """Raise after a short wait."""
                time.sleep(seconds)
                raise ConnectionError("mirror unreachable")


            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                mirrors = [
                    executor.submit(slow_echo, f"mirror-{mirror_number}", seconds)
                    for mirror_number, seconds in enumerate((0.3, 0.1, 0.2))
                ]
                done, not_done = concurrent.futures.wait(
                    mirrors, return_when=concurrent.futures.FIRST_COMPLETED
                )
                print(
                    f"FIRST_COMPLETED: done={[future.result() for future in done]}, "
                    f"still running={len(not_done)}"
                )

                mixed = [executor.submit(fail_after, 0.05), executor.submit(slow_echo, "slow", 0.3)]
                done, not_done = concurrent.futures.wait(mixed, return_when=concurrent.futures.FIRST_EXCEPTION)
                print(
                    f"FIRST_EXCEPTION: done={len(done)} "
                    f"({next(iter(done)).exception()!r}), not done={len(not_done)}"
                )

                done, not_done = concurrent.futures.wait(mirrors + mixed)  # ALL_COMPLETED
                print(f"ALL_COMPLETED: done={len(done)}, not done={len(not_done)}")
            '''
        ),
        md(
            """
            **Sizing.** The default `max_workers` is `min(32, (os.process_cpu_count() or 1)
            + 4)` (*changed in 3.13*: it used `os.cpu_count()` before). The right number
            depends on the work:

            | Work | Size the pool | Why |
            | --- | --- | --- |
            | I/O-bound (HTTP, database) | about the concurrency you want: throughput × latency (Little's law), capped by what the server allows | waiting threads cost little |
            | C code that releases the GIL (hashing, compression, NumPy) | about the number of cores | more threads than cores just queue up |
            | Pure-Python CPU work (default build) | threads do not help | use processes (5.2) or a free-threaded build |

            The cell prints the default (via the private `_max_workers` attribute, for
            demonstration only) and times 16 requests of 0.05 s each with 1, 4 and 16
            workers.
            """
        ),
        code(
            """
            print(
                f"{os.process_cpu_count()=}, default "
                f"max_workers={concurrent.futures.ThreadPoolExecutor()._max_workers}"
            )
            for worker_count in (1, 4, 16):
                with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
                    with Timer(f"16 requests x 0.05 s, {worker_count:>2} workers", report=None) as timing:
                        list(executor.map(fetch_slow_page, [0.05] * 16))
                print(
                    f"{timing.label}: {timing.elapsed_seconds:.2f} s "
                    f"(ideal {0.05 * -(-16 // worker_count):.2f} s)"
                )
            """
        ),
        md(
            """
            **Shutdown.** Leaving the `with` block calls `shutdown(wait=True)`: it waits for
            every submitted task. `shutdown(wait=False, cancel_futures=True)` cancels
            everything still queued and returns at once (running tasks still finish).
            After shutdown, `submit` raises `RuntimeError`.
            """
        ),
        code(
            """
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            backlog = [executor.submit(slow_echo, f"email-{email_number}", 0.05) for email_number in range(10)]
            time.sleep(0.02)
            executor.shutdown(wait=False, cancel_futures=True)
            print(
                f"cancelled: {sum(future.cancelled() for future in backlog)}, ran "
                f"or running: {sum(not future.cancelled() for future in backlog)}"
            )
            print(f"submit after shutdown: {raised_message(lambda: executor.submit(print))}")
            started = [future.result() for future in backlog if not future.cancelled()]  # let them finish
            """
        ),
        md(
            """
            **Exceptions.** A task's exception is stored in its future. `exception()`
            returns it; `result()` re-raises the *same* object, with the worker's traceback
            attached. The danger is the opposite case: a fire-and-forget `submit` whose
            future nobody looks at swallows the error silently.
            """
        ),
        code(
            '''
            def parse_quantity(text: str) -> int:
                """Parse a quantity; fails on bad input."""
                return int(text)


            with concurrent.futures.ThreadPoolExecutor() as executor:
                bad = executor.submit(parse_quantity, "three")
                stored = bad.exception()
                print(f"exception(): {stored!r}")
                try:
                    bad.result()
                except ValueError as error:
                    last_frame = traceback.extract_tb(error.__traceback__)[-1].name
                    print(
                        "result() re-raised the same object: "
                        f"{error is stored}; traceback ends in {last_frame!r}"
                    )
                executor.submit(parse_quantity, "seven")  # fire and forget: the ValueError vanishes
            print("no error was printed for 'seven': always check futures (or use map / as_completed)")
            '''
        ),
    ]


def _shutdown_cells() -> list[NotebookNode]:
    """5.1.9 Errors and shutdown."""
    return [
        md(
            """
            ### 5.1.9 Errors and shutdown

            An exception that escapes a thread's `run()` does **not** reach the thread that
            called `join()`. The thread dies, `threading.excepthook` is called, and the rest
            of the program carries on. The default hook prints `Exception in thread NAME:`
            and the traceback to stderr. Seen from a script in a child process:
            """
        ),
        code(
            '''
            print(
                run_child("""
                import threading

                def import_prices():
                    raise KeyError("sku-404")

                worker = threading.Thread(target=import_prices, name="price-importer")
                worker.start()
                worker.join()
                print("main thread: join() returned normally, worker.is_alive() =", worker.is_alive())
            """)
            )
            '''
        ),
        md(
            """
            **A custom `threading.excepthook`** receives one `ExceptHookArgs` argument with
            `exc_type`, `exc_value`, `exc_traceback` and `thread`. Install one to log thread
            failures properly (or to collect them, as here). Restore the previous hook
            afterwards; `threading.__excepthook__` always holds the original.
            """
        ),
        code(
            '''
            thread_failures: list[str] = []


            def collect_failure(hook_args: threading.ExceptHookArgs) -> None:
                """Record which thread failed and why, instead of printing a traceback."""
                thread_name = hook_args.thread.name if hook_args.thread else "?"
                thread_failures.append(f"{thread_name}: {hook_args.exc_type.__name__}: {hook_args.exc_value}")


            def import_prices() -> None:
                """A thread body that fails."""
                raise KeyError("sku-404")


            previous_hook = threading.excepthook
            threading.excepthook = collect_failure
            try:
                failing = threading.Thread(target=import_prices, name="price-importer")
                failing.start()
                failing.join()
            finally:
                threading.excepthook = previous_hook
            print(f"{thread_failures=}")
            print(f"{threading.__excepthook__ is not collect_failure=}")
            '''
        ),
        md(
            """
            **Daemon threads at shutdown, again.** A daemon thread is frozen mid-step when
            the interpreter exits: buffered data is lost and `finally` blocks never run. The
            child script below starts two writers that append a line every 10 ms and write
            a footer in `finally`. One is a daemon; the other is stopped by a flag the main
            thread sets before exiting. Then the parent reads both files.
            """
        ),
        code(
            r'''
            WRITERS_DEMO = """
                import threading, time

                stop = threading.Event()

                def write_lines(path, stop_flag):
                    with open(path, "w") as output:
                        try:
                            for number in range(1000):
                                if stop_flag is not None and stop_flag.is_set():
                                    break
                                output.write(f"line {number}\\n")
                                time.sleep(0.01)
                        finally:
                            output.write("FOOTER\\n")

                threading.Thread(target=write_lines, args=("daemon.txt", None), daemon=True).start()
                flagged = threading.Thread(target=write_lines, args=("flagged.txt", stop))
                flagged.start()
                time.sleep(0.05)
                stop.set()  # ask the non-daemon writer to finish
                print("main thread exiting")
            """
            print(run_child(WRITERS_DEMO))
            for name in ("daemon.txt", "flagged.txt"):
                lines = (PHASE5_DIR / name).read_text().splitlines()
                print(f"{name:<12} {len(lines)} lines, last line: {lines[-1] if lines else '(empty file)'!r}")
            '''
        ),
        md(
            """
            The daemon's file has no footer (and may even be empty: its buffered lines were
            never flushed). The flagged writer stopped at a clean point and closed its file.

            **Stop flags.** Python has no `thread.kill()`: killing a thread could leave
            locks held and data half-written. Stopping is cooperative: the thread checks a
            flag. Use an `Event` and wait on it with a timeout instead of `time.sleep`, so
            the thread wakes up the moment the flag is set.
            """
        ),
        code(
            '''
            def poll_with_sleep(stop: threading.Event) -> None:
                """Responds to stop only after the current sleep ends."""
                while not stop.is_set():
                    time.sleep(0.3)


            def poll_with_wait(stop: threading.Event) -> None:
                """Event.wait returns as soon as stop is set."""
                while not stop.wait(timeout=0.3):
                    pass


            for poller in (poll_with_sleep, poll_with_wait):
                stop_flag = threading.Event()
                poller_thread = threading.Thread(target=poller, args=(stop_flag,))
                poller_thread.start()
                time.sleep(0.05)
                with Timer(f"{poller.__name__}: time from set() to exit", report=None) as stop_timing:
                    stop_flag.set()
                    poller_thread.join()
                print(f"{stop_timing.label}: {stop_timing.elapsed_seconds * 1000:.0f} ms")
            '''
        ),
        md(
            """
            > **Note:** `KeyboardInterrupt` (Ctrl+C) and every signal handler run only in
            > the **main** thread. A worker blocked in `queue.get()` or `lock.acquire()`
            > never sees Ctrl+C, so the main thread must set the stop flag (or put
            > sentinels) when it catches `KeyboardInterrupt`, then join the workers.
            """
        ),
    ]


def _free_threading_cells() -> list[NotebookNode]:
    """5.1.10 Free-threaded Python."""
    return [
        md(
            """
            ### 5.1.10 Free-threaded Python

            | | |
            | --- | --- |
            | [PEP 703](https://peps.python.org/pep-0703/) | Making the GIL optional: a separate *free-threaded* build of CPython. Experimental in 3.13. |
            | [PEP 779](https://peps.python.org/pep-0779/) | Criteria for "supported" status. Since 3.14 the free-threaded build is officially supported (phase II), still a separate build, not the default. |
            | Executable | `python3.15t` (the `t` suffix); install with `uv python install 3.15t` |
            | Detect the build | `sysconfig.get_config_var("Py_GIL_DISABLED") == 1`, `sys.abiflags` contains `t` |
            | Detect the GIL at run time | `sys._is_gil_enabled()` (*new in 3.13*); can be `True` on a free-threaded build |
            | Force it | `PYTHON_GIL=0` / `PYTHON_GIL=1`, or `-X gil=0` / `-X gil=1` |

            **How it works without the GIL** (Unit 3.1 showed the memory side): biased
            reference counting (the owning thread updates its count cheaply; other threads
            use atomic operations), immortal objects, per-object locks inside `dict`, `list`
            and friends (so the "atomic" table in 5.1.4 still holds), and the `mimalloc`
            allocator. The price is some single-threaded speed and memory.

            **Detect and probe.** The next cell runs the same probe in this kernel's
            interpreter and in `python3.15t` (and once more with `PYTHON_GIL=1`), or prints
            a skip message when no free-threaded interpreter is installed.
            """
        ),
        code(
            '''
            BUILD_PROBE = """
                import sys, sysconfig
                print("Py_GIL_DISABLED:", sysconfig.get_config_var("Py_GIL_DISABLED"))
                print("sys.abiflags:", repr(sys.abiflags))
                print("extension suffix:", sysconfig.get_config_var("EXT_SUFFIX"))
                print("sys._is_gil_enabled():", sys._is_gil_enabled())
                print("threads inherit contextvars:", bool(sys.flags.thread_inherit_context))
            """
            print(f"--- this kernel [{interpreter_label()}]")
            print(run_child(BUILD_PROBE))
            if FREE_THREADED_PYTHON is None:
                print("SKIP: no free-threaded interpreter found (install one with: uv python install 3.15t)")
            else:
                print("--- python3.15t")
                print(run_child(BUILD_PROBE, python=FREE_THREADED_PYTHON))
                print("--- python3.15t with PYTHON_GIL=1")
                print(run_child(BUILD_PROBE, python=FREE_THREADED_PYTHON, extra_env={"PYTHON_GIL": "1"}))
            '''
        ),
        md(
            """
            **Compatibility.**

            - **Pure-Python packages** run unchanged.
            - **C extensions** need a separate wheel (ABI tag `cp315t`; note the different
              extension suffix above) **and** must declare that they are safe without the
              GIL (the `Py_mod_gil` slot). Importing an extension that does not declare it
              **re-enables the GIL** for the whole process and emits a `RuntimeWarning`.
              Check `sys._is_gil_enabled()` after your imports in production.
            - **Your own code**: races that the GIL happened to hide become real. The plain
              `counter.value += 1` from 5.1.4, unchanged, in both builds:
            """
        ),
        code(
            '''
            PLAIN_INCREMENT_RACE = """
                import sys, threading

                class PlainCounter:
                    value = 0

                counter = PlainCounter()

                def add_many(times):
                    for _ in range(times):
                        counter.value += 1

                threads = [threading.Thread(target=add_many, args=(100_000,)) for _ in range(4)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
                print(f"GIL enabled: {sys._is_gil_enabled()!s:<5}  expected 400,000, got {counter.value:,}")
            """
            print(run_child(PLAIN_INCREMENT_RACE))
            if FREE_THREADED_PYTHON is None:
                print("SKIP: no free-threaded interpreter found")
            else:
                print(run_child(PLAIN_INCREMENT_RACE, python=FREE_THREADED_PYTHON))
            '''
        ),
        md(
            """
            **Benchmark.** Each thread runs the same pure-Python loop (1 000 000 iterations
            × `DEMO_SCALE`); 1, 2, 4 and 8 threads run at once. *Throughput speedup* =
            threads × (time for one thread) ÷ (time for all threads): 1.0 means no gain,
            `n` means perfect scaling. The last line compares single-thread speed between
            the builds. Expect about 1.0× everywhere on the default build, and scaling up
            to your core count on 3.15t.
            """
        ),
        code(
            '''
            SCALING_BENCHMARK = """
                import json, os, threading, time

                LOOPS = 1_000_000 * int(os.environ.get("PHASE5_DEMO_SCALE", "1"))

                def spin():
                    total = 0
                    for number in range(LOOPS):
                        total += number * number

                def wall_seconds(thread_count):
                    threads = [threading.Thread(target=spin) for _ in range(thread_count)]
                    start = time.perf_counter()
                    for thread in threads:
                        thread.start()
                    for thread in threads:
                        thread.join()
                    return time.perf_counter() - start

                print(json.dumps({count: wall_seconds(count) for count in (1, 2, 4, 8)}))
            """
            '''
        ),
        md(
            """
            `scaling_table` runs that script in a child interpreter (this kernel's, then
            `python3.15t` if installed) and parses its JSON line; the loop prints one row per
            build with the time and throughput speedup for each thread count:
            """
        ),
        code(
            '''
            def scaling_table(python: str) -> dict[str, float]:
                """Run the benchmark in a child interpreter; return {thread count: seconds}."""
                return json.loads(run_child(SCALING_BENCHMARK, python=python).splitlines()[-1])


            builds = {"default build": scaling_table(sys.executable)}
            if FREE_THREADED_PYTHON is None:
                print("SKIP: no free-threaded interpreter found; showing the default build only")
            else:
                builds["free-threaded"] = scaling_table(FREE_THREADED_PYTHON)
            print(f"CPU cores available: {os.process_cpu_count()}")
            for build_name, seconds in builds.items():
                cells = [
                    f"{count}T {seconds[count]:.2f}s ({int(count) * seconds['1'] / seconds[count]:.1f}x)"
                    for count in seconds
                ]
                print(f"{build_name:<14} " + " | ".join(cells))
            if "free-threaded" in builds:
                print(
                    "single-thread time, free-threaded / default: "
                    f"{builds['free-threaded']['1'] / builds['default build']['1']:.2f}"
                )
            '''
        ),
        md(
            """
            On a machine with 4 or more cores the free-threaded row should approach 4× at
            four threads, while the default row stays near 1×. The single-thread ratio shows
            the cost of running without the GIL: usually a little above 1.0.

            | Choose the free-threaded build when | Stay on the default build when |
            | --- | --- |
            | CPU-bound pure-Python work must run in parallel **and** share large in-memory data | the work is I/O-bound (threads or asyncio already work) |
            | every C extension you need ships `cp315t` wheels | a key dependency has no free-threaded wheel (the GIL would come back anyway) |
            | you can test for races you never saw before | single-thread speed matters most |
            """
        ),
    ]


def _js_bridge_cells() -> list[NotebookNode]:
    """5.1.11 JS bridge."""
    return [
        md(
            """
            ### 5.1.11 JS bridge

            **libuv's thread pool.** Node runs your JavaScript on one thread. Network sockets
            never use a thread: libuv watches them with `epoll` / `kqueue` / IOCP. Work the
            OS cannot do asynchronously goes to libuv's **thread pool**: 4 threads by
            default, set with the `UV_THREADPOOL_SIZE` environment variable before startup
            (maximum 1024). It runs `fs.*` calls, `dns.lookup`, `crypto.pbkdf2`,
            `crypto.scrypt`, `crypto.randomBytes` (async form), async `zlib`, and C++ addon
            work. Your JavaScript itself never runs in that pool.

            **`worker_threads`.** Each `Worker` is a new V8 isolate with its **own heap,
            own event loop and own globals**. Workers communicate by `postMessage`
            (structured clone copies), transfer `ArrayBuffer`s, or share memory explicitly
            through a `SharedArrayBuffer` with `Atomics`.

            | Node | Python | Precise difference |
            | --- | --- | --- |
            | libuv pool runs C++ work for built-in modules | `ThreadPoolExecutor` runs **any** callable, including Python code | Python code in the pool still takes turns on the GIL (default build); C code that releases it runs in parallel, like libuv's pool |
            | `UV_THREADPOOL_SIZE=4` (process-wide, set before start) | `max_workers=` per executor; asyncio's default executor is `min(32, cpus + 4)` | you can have several pools of different sizes |
            | `fs.readFile(cb)` goes to the pool automatically | `open().read()` blocks the calling thread; in asyncio use `await asyncio.to_thread(...)` | nothing is offloaded unless you ask |
            | `worker_threads`: separate heap, message passing | `threading.Thread`: **one shared heap**, no copying | threads can race on any object; Workers cannot |
            | `worker_threads` (isolation + parallelism) | subinterpreters (5.2.6): own GIL, own modules, message passing | the closest match to a Worker |
            | `child_process.fork`, `cluster` | `multiprocessing`, `ProcessPoolExecutor` (5.2) | Python pickles messages; Node uses JSON/structured clone over IPC |
            | `SharedArrayBuffer` + `Atomics` | `multiprocessing.shared_memory` + locks (5.2.5) | |

            **The pool, side by side.** In Node, four `crypto.pbkdf2()` calls run in
            parallel on the libuv pool. In Python, `hashlib.pbkdf2_hmac` releases the GIL
            while OpenSSL works, so a `ThreadPoolExecutor` of 4 gets the same parallelism.
            """
        ),
        code(
            '''
            def derive_key(password: bytes) -> str:
                """PBKDF2-HMAC-SHA256 with many iterations (the GIL is released inside)."""
                iterations = 300_000 * DEMO_SCALE
                return hashlib.pbkdf2_hmac("sha256", password, b"per-user-salt", iterations).hex()[:12]


            passwords = [b"asha-pass", b"ravi-pass", b"meena-pass", b"john-pass"]
            with Timer("4 keys, one after another") as one_by_one:
                sequential_keys = [derive_key(password) for password in passwords]
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as key_pool:
                with Timer("4 keys, pool of 4 threads") as pooled:
                    pooled_keys = list(key_pool.map(derive_key, passwords))
            print(
                f"same keys: {pooled_keys == sequential_keys}; speedup "
                f"{one_by_one.elapsed_seconds / pooled.elapsed_seconds:.2f}x"
            )
            '''
        ),
        md(
            """
            **From asyncio** (Unit 5.3 explains the event loop), `asyncio.to_thread(f, *args)`
            runs `f` in the loop's default thread pool and gives back an awaitable. That is
            the closest thing to `util.promisify(crypto.pbkdf2)`: blocking or GIL-releasing
            work leaves the event loop thread free. The kernel already runs a loop, so the
            cell uses top-level `await`.
            """
        ),
        code(
            """
            with Timer("asyncio.gather of 4 to_thread calls"):
                async_keys = await asyncio.gather(
                    *(asyncio.to_thread(derive_key, password) for password in passwords)
                )
            print(f"same keys again: {async_keys == sequential_keys}")
            """
        ),
    ]


def _predict_cells() -> list[NotebookNode]:
    """Predict-the-output questions for Unit 5.1."""
    return [
        md("#### Predict the output"),
        *predict_cells(
            """
            import threading

            def work():
                print("working in", threading.current_thread().name)

            worker = threading.Thread(target=work(), name="worker")
            worker.start()
            worker.join()
            """,
            """
            `working in MainThread`. `target=work()` **calls** `work` immediately, in the
            main thread, and passes its return value (`None`) as the target. The `worker`
            thread then starts with no target and does nothing. Pass the function itself:
            `target=work`. (In JS the same slip is `setTimeout(work(), 0)`.)
            """,
            '''
            def work() -> None:
                """Print the name of the thread running this function."""
                print("working in", threading.current_thread().name)


            worker = threading.Thread(target=work(), name="worker")
            worker.start()
            worker.join()
            ''',
        ),
        *predict_cells(
            """
            from concurrent.futures import ThreadPoolExecutor
            import time

            def nap(seconds):
                time.sleep(seconds)
                return seconds

            with ThreadPoolExecutor(max_workers=3) as executor:
                print(list(executor.map(nap, [0.3, 0.1, 0.2])))
            """,
            """
            `[0.3, 0.1, 0.2]`. The tasks *finish* in the order 0.1, 0.2, 0.3, but `map`
            always yields results in **input order**. Use `as_completed` for finish order.
            The whole call takes about 0.3 s (the longest task), not 0.6 s.
            """,
            '''
            def nap(seconds: float) -> float:
                """Sleep for seconds, then return them."""
                time.sleep(seconds)
                return seconds


            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                print(list(executor.map(nap, [0.3, 0.1, 0.2])))
            ''',
        ),
        *predict_cells(
            """
            import threading

            def explode():
                raise ValueError("boom")

            worker = threading.Thread(target=explode)
            worker.start()
            worker.join()
            print("joined")
            """,
            """
            The thread's `ValueError` does **not** propagate to `join()`. The default
            `threading.excepthook` prints `Exception in thread Thread-N (explode):` and the
            traceback to stderr, then the main thread prints `joined`. The proof cell
            installs a temporary hook that prints one line instead of the full traceback.
            """,
            '''
            def explode() -> None:
                """Raise a ValueError inside the thread."""
                raise ValueError("boom")


            def one_line_hook(hook_args: threading.ExceptHookArgs) -> None:
                """Print one line for an uncaught thread exception instead of a traceback."""
                print(f"excepthook: {hook_args.exc_type.__name__}: {hook_args.exc_value}")


            saved_hook, threading.excepthook = threading.excepthook, one_line_hook
            try:
                worker = threading.Thread(target=explode)
                worker.start()
                worker.join()
                print("joined")
            finally:
                threading.excepthook = saved_hook
            ''',
        ),
    ]


LAB_SETUP_SOURCE = r'''
import concurrent.futures
import functools
import inspect
import itertools
import json
import math
import os
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

import httpx


def run_threads(work: Callable[[object], object], items: list[object]) -> None:
    """Run work(item) in one thread per item and join them all (a helper for the checks)."""
    threads = [threading.Thread(target=work, args=(item,)) for item in items]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


print("Lab 5.1 imports ready; helper: run_threads")
'''

LAB_COUNTER_SETUP_SOURCE = r'''
class UnsafeCounter:
    """Exercise 1: reads, gives up the GIL, then writes, so concurrent updates get lost."""

    def __init__(self) -> None:
        """Start at zero."""
        self.value = 0

    def increment(self) -> None:
        """Read, yield the GIL, then write, so concurrent updates get lost."""
        current = self.value
        time.sleep(0)  # let another thread run between the read and the write
        self.value = current + 1


print("Lab 5.1 helper ready: UnsafeCounter")
'''

LAB_DEADLOCK_SETUP_SOURCE = r'''
class DeadlockError(RuntimeError):
    """Exercise 5: raised when a lock cannot be acquired in time."""


def acquire_or_fail(lock: threading.Lock, timeout: float = 0.5) -> None:
    """Acquire lock or raise DeadlockError after timeout seconds (so a deadlock cannot hang)."""
    if not lock.acquire(timeout=timeout):
        raise DeadlockError(f"could not acquire a lock within {timeout} s")


@dataclass(eq=False)
class Account:
    """Exercise 5: a bank account with its own lock."""

    account_id: int
    balance: int
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


def transfer_naive(
    source: Account,
    target: Account,
    amount: int,
    pause: Callable[[], None] = lambda: time.sleep(0.05),
) -> None:
    """Exercise 5: lock source, pause, lock target, move money. Deadlocks on opposite transfers."""
    acquire_or_fail(source.lock)
    try:
        pause()  # widen the window so the deadlock shows every time
        acquire_or_fail(target.lock)
        try:
            source.balance -= amount
            target.balance += amount
        finally:
            target.lock.release()
    finally:
        source.lock.release()


print("Lab 5.1 helpers ready: Account, transfer_naive, acquire_or_fail, DeadlockError")
'''


def _lab_cells_part_1() -> list[NotebookNode]:
    """Lab 5.1 exercises 1–3."""
    return [
        md(
            """
            ### Lab 5.1

            Six exercises; replace each `raise NotImplementedError`, then run the check cell.
            Until you finish, the checks print FAIL; that is expected. The first setup cell
            below imports what the exercises need and defines `run_threads` (used by the
            checks):
            """
        ),
        code(LAB_SETUP_SOURCE),
        md(
            """
            `UnsafeCounter` for exercise 1: it reads the value, gives up the GIL with
            `time.sleep(0)`, then writes, so concurrent increments get lost:
            """
        ),
        code(LAB_COUNTER_SETUP_SOURCE),
        md(
            """
            The third setup cell defines the bank-transfer pieces of exercise 5: `Account`
            (an account with its own lock), `transfer_naive` (locks source, then target),
            `acquire_or_fail` and `DeadlockError` (a timed acquire, so a deadlock fails fast
            instead of hanging the notebook):
            """
        ),
        code(LAB_DEADLOCK_SETUP_SOURCE),
        md(
            """
            #### Exercise 1 — prove a race condition and fix it

            1. `hammer(counter, thread_count, increments_per_thread)` starts `thread_count`
               threads, each calling `counter.increment()` `increments_per_thread` times,
               joins them all and returns `counter.value`. Run on an `UnsafeCounter`, it
               should return **less** than `thread_count × increments_per_thread`: that
               proves the race.
            2. `LockedCounter` has a `value` attribute starting at 0 and an `increment()`
               that does the same read / `time.sleep(0)` / write as `UnsafeCounter`, but
               inside `with self._lock:` (a `threading.Lock` created in `__init__`).
            """
        ),
        code(
            '''
            def hammer(counter: object, thread_count: int, increments_per_thread: int) -> int:
                """Increment counter from several threads at once; return the final value."""
                raise NotImplementedError


            class LockedCounter:
                """UnsafeCounter's read / sleep(0) / write, made safe with a Lock."""

                def __init__(self) -> None:
                    """Set up the value and whatever protects it."""
                    raise NotImplementedError

                def increment(self) -> None:
                    """Add one to the value without losing concurrent updates."""
                    raise NotImplementedError
            '''
        ),
        md("Check exercise 1:"),
        code(
            '''
            def threads_left_behind() -> int:
                """How many more threads are alive after hammer() than before."""
                before = threading.active_count()
                hammer(LockedCounter(), 3, 10)
                return threading.active_count() - before


            run_checks(
                [
                    (
                        "race proven: UnsafeCounter loses updates",
                        lambda: hammer(UnsafeCounter(), 4, 200) < 800,
                        True,
                    ),
                    ("LockedCounter: 4 threads x 200", lambda: hammer(LockedCounter(), 4, 200), 800),
                    ("LockedCounter: 1 thread x 50", lambda: hammer(LockedCounter(), 1, 50), 50),
                    (
                        "LockedCounter keeps a threading.Lock",
                        lambda: any(
                            isinstance(value, type(threading.Lock()))
                            for value in vars(LockedCounter()).values()
                        ),
                        True,
                    ),
                    ("hammer joins every thread it starts", threads_left_behind, 0),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 2 — producer–consumer with `Queue`

            `process_with_workers(items, handle, worker_count)` returns
            `[handle(item) for item in items]`, computed by `worker_count` consumer threads:

            - put `(index, item)` pairs on a `queue.Queue`;
            - start `worker_count` threads named `consumer-1`, `consumer-2`, …; each takes
              pairs, stores `handle(item)` at its index and calls `task_done()`;
            - shut down with **one sentinel per consumer**, then join every consumer;
            - return the results in input order.
            """
        ),
        code(
            '''
            def process_with_workers[T, R](
                items: list[T], handle: Callable[[T], R], worker_count: int
            ) -> list[R]:
                """Run handle over items with worker_count consumer threads fed by a Queue."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 2:"),
        code(
            '''
            def square_slowly(number: int) -> int:
                """A handler that takes a few milliseconds."""
                time.sleep(0.005)
                return number * number


            def consumer_names_used(worker_count: int) -> tuple[int, bool]:
                """How many distinct threads ran the handler, and whether all were named consumer-N."""
                seen: set[str] = set()

                def record(number: int) -> int:
                    """Remember which thread handled the item, then return it unchanged."""
                    seen.add(threading.current_thread().name)
                    time.sleep(0.01)
                    return number

                process_with_workers(list(range(20)), record, worker_count)
                return len(seen), all(name.startswith("consumer-") for name in seen)


            def consumers_still_alive() -> list[str]:
                """Names of consumer threads alive after process_with_workers returns."""
                process_with_workers(list(range(10)), square_slowly, 3)
                return [thread.name for thread in threading.enumerate() if thread.name.startswith("consumer-")]
            '''
        ),
        md(
            """
            The checks: results in input order, any handler, empty input, all four named
            consumers busy, none left alive afterwards, and a real `queue.Queue` underneath:
            """
        ),
        code(
            """
            run_checks(
                [
                    (
                        "results in input order",
                        lambda: process_with_workers(list(range(12)), square_slowly, 4),
                        [number * number for number in range(12)],
                    ),
                    (
                        "works with any handler",
                        lambda: process_with_workers(["tea", "mug"], str.upper, 2),
                        ["TEA", "MUG"],
                    ),
                    ("empty input", lambda: process_with_workers([], square_slowly, 3), []),
                    ("all 4 consumers took work, named consumer-N", lambda: consumer_names_used(4), (4, True)),
                    ("no consumer thread left alive", consumers_still_alive, []),
                    ("uses queue.Queue", lambda: "Queue(" in inspect.getsource(process_with_workers), True),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 3 — a thread-pool downloader

            `download_all(client, urls, max_workers)` downloads every URL with
            `client.get(url)` on a `ThreadPoolExecutor(max_workers)`, collects results with
            `as_completed`, and returns a dict from each URL to:

            - the number of bytes in the body, for a successful (2xx) response;
            - the exception class name otherwise: call `response.raise_for_status()` and
              catch `httpx.HTTPError`, so a 404 gives `"HTTPStatusError"` and a refused
              connection gives `"ConnectError"`.

            The checks use an `httpx.Client` with a `MockTransport` that waits 50 ms per
            request and records how many requests were in flight at once.
            """
        ),
        code(
            '''
            def download_all(
                client: httpx.Client, urls: list[str], max_workers: int = 8
            ) -> dict[str, int | str]:
                """Download urls concurrently; map each to its byte count or error class name."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 3:"),
        code(
            '''
            def lab_client(latency: float = 0.05) -> tuple[httpx.Client, dict[str, int]]:
                """A client whose transport sleeps per request and tracks the peak in-flight count."""
                stats = {"now": 0, "peak": 0}
                stats_lock = threading.Lock()

                def handler(request: httpx.Request) -> httpx.Response:
                    """Answer a mock request after the latency, tracking the in-flight peak."""
                    with stats_lock:
                        stats["now"] += 1
                        stats["peak"] = max(stats["peak"], stats["now"])
                    try:
                        time.sleep(latency)
                        path = request.url.path
                        if path == "/broken":
                            raise httpx.ConnectError("connection refused", request=request)
                        if path.startswith("/files/"):
                            return httpx.Response(200, content=b"x" * int(path.rsplit("/", 1)[1]))
                        return httpx.Response(404)
                    finally:
                        with stats_lock:
                            stats["now"] -= 1

                return httpx.Client(transport=httpx.MockTransport(handler)), stats


            def peak_in_flight(url_count: int, max_workers: int) -> int:
                """Download url_count files and return the peak number of concurrent requests."""
                client, stats = lab_client()
                download_all(
                    client,
                    [f"http://lab.test/files/{file_number}" for file_number in range(url_count)],
                    max_workers,
                )
                return stats["peak"]
            '''
        ),
        md(
            """
            The checks: byte counts per URL, errors turned into class names, the concurrency
            cap (more than one request in flight, never more than `max_workers`), and the
            required `ThreadPoolExecutor` + `as_completed`:
            """
        ),
        code(
            """
            FILE_URLS = ["http://lab.test/files/10", "http://lab.test/files/2048"]
            BAD_URLS = ["http://lab.test/missing", "http://lab.test/broken"]
            run_checks(
                [
                    (
                        "byte counts",
                        lambda: download_all(lab_client()[0], FILE_URLS, 4),
                        {FILE_URLS[0]: 10, FILE_URLS[1]: 2048},
                    ),
                    (
                        "errors become class names",
                        lambda: download_all(lab_client()[0], BAD_URLS, 4),
                        {BAD_URLS[0]: "HTTPStatusError", BAD_URLS[1]: "ConnectError"},
                    ),
                    ("12 URLs, 4 workers: concurrent but capped", lambda: 1 < peak_in_flight(12, 4) <= 4, True),
                    ("1 worker: one request at a time", lambda: peak_in_flight(4, 1), 1),
                    ("no URLs", lambda: download_all(lab_client()[0], [], 4), {}),
                    (
                        "uses ThreadPoolExecutor and as_completed",
                        lambda: all(
                            word in inspect.getsource(download_all)
                            for word in ("ThreadPoolExecutor", "as_completed")
                        ),
                        True,
                    ),
                ]
            )
            """
        ),
    ]


def _lab_cells_part_2() -> list[NotebookNode]:
    """Lab 5.1 exercises 4–6."""
    return [
        md(
            """
            #### Exercise 4 — a semaphore-capped connection pool

            `ConnectionPool(size, connect)` hands out at most `size` connections at a time:

            - `connection()` is a context manager (use `@contextmanager`) that blocks while
              `size` connections are in use (a `threading.BoundedSemaphore(size)`), then
              yields an idle connection, or a new one from `connect()` if none is idle;
              on exit (even after an exception) the connection goes back to the idle list
              and the semaphore is released;
            - attributes `created` (how many times `connect()` ran), `in_use` (connections
              currently handed out) and `peak_in_use` (the highest `in_use` seen). Protect
              the counters and the idle list with a `Lock`.
            """
        ),
        code(
            '''
            class ConnectionPool:
                """At most `size` connections in use; idle connections are reused."""

                def __init__(self, size: int, connect: Callable[[], object]) -> None:
                    """Prepare the semaphore, the idle list and the counters."""
                    raise NotImplementedError

                @contextmanager
                def connection(self) -> Iterator[object]:
                    """Lend a connection for the duration of a with block."""
                    raise NotImplementedError
                    yield  # (makes this a generator; remove when you implement it)
            '''
        ),
        md("Check exercise 4:"),
        code(
            '''
            def make_pool(size: int) -> ConnectionPool:
                """A pool whose connections are numbered strings."""
                numbers = itertools.count(1)
                return ConnectionPool(size, lambda: f"conn-{next(numbers)}")


            def busy_pool(size: int, users: int) -> tuple[int, int, int]:
                """`users` threads each hold a connection for 20 ms; return (peak, created, in_use)."""
                pool = make_pool(size)

                def use(_: object) -> None:
                    """Hold one pooled connection for 20 ms."""
                    with pool.connection():
                        time.sleep(0.02)

                run_threads(use, list(range(users)))
                return pool.peak_in_use, pool.created, pool.in_use


            def sequential_reuse() -> list[object]:
                """Five uses one after another should reuse a single connection."""
                pool = make_pool(3)
                handed_out = []
                for _ in range(5):
                    with pool.connection() as connection:
                        handed_out.append(connection)
                return handed_out


            def released_after_error() -> tuple[int, object]:
                """An exception inside the with block must still return the connection."""
                pool = make_pool(1)
                try:
                    with pool.connection():
                        raise ValueError("query failed")
                except ValueError:
                    pass
                with pool.connection() as connection:  # would block forever if the slot leaked
                    return pool.in_use, connection
            '''
        ),
        md(
            """
            The checks: 12 users through a pool of 3 never see more than 3 connections,
            sequential users reuse one connection, an exception still returns it, and the cap
            is a `BoundedSemaphore`:
            """
        ),
        code(
            """
            run_checks(
                [
                    (
                        "12 users, size 3: peak 3, at most 3 created, all returned",
                        lambda: busy_pool(3, 12),
                        (3, 3, 0),
                    ),
                    ("sequential uses reuse one connection", sequential_reuse, ["conn-1"] * 5),
                    ("exception releases the connection", released_after_error, (1, "conn-1")),
                    (
                        "uses a BoundedSemaphore",
                        lambda: any(
                            isinstance(value, threading.BoundedSemaphore)
                            for value in vars(make_pool(2)).values()
                        ),
                        True,
                    ),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 5 — reproduce and fix a deadlock

            `transfer_naive` (setup cell) locks the source account, pauses 50 ms, then locks
            the target. `acquire_or_fail` raises `DeadlockError` after 0.5 s instead of
            hanging.

            1. `run_opposite_transfers(transfer)` creates `Account(1, 100)` and
               `Account(2, 100)`, runs `transfer(account_1, account_2, 10)` and
               `transfer(account_2, account_1, 20)` in two threads at the same time, and
               returns `{"outcomes": sorted list of "ok" or the exception class name per
               thread, "balances": (account_1.balance, account_2.balance)}`. With
               `transfer_naive` the outcomes include `"DeadlockError"`: that reproduces it.
            2. `transfer_ordered(source, target, amount, pause=...)` fixes it with **lock
               ordering**: acquire the two locks (with `acquire_or_fail`) in order of
               `account_id`, call `pause()` between the two acquisitions, move the money,
               release both.
            """
        ),
        code(
            '''
            def run_opposite_transfers(transfer: Callable[[Account, Account, int], None]) -> dict[str, object]:
                """Run two opposite transfers at once; report outcomes and final balances."""
                raise NotImplementedError


            def transfer_ordered(
                source: Account,
                target: Account,
                amount: int,
                pause: Callable[[], None] = lambda: time.sleep(0.05),
            ) -> None:
                """Move amount from source to target, locking accounts in account_id order."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 5:"),
        code(
            '''
            class RecordingLock:
                """A lock that records the account id each time it is acquired."""

                def __init__(self, account_id: int, log: list[int]) -> None:
                    """Wrap a real lock that logs account_id on every acquire."""
                    self._lock, self._account_id, self._log = threading.Lock(), account_id, log

                def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
                    """Acquire the wrapped lock and log the account id on success."""
                    acquired = self._lock.acquire(blocking, timeout)
                    if acquired:
                        self._log.append(self._account_id)
                    return acquired

                def release(self) -> None:
                    """Release the wrapped lock."""
                    self._lock.release()


            def lock_order_used() -> list[int]:
                """Account ids in the order transfer_ordered locked them, transferring 2 -> 1."""
                log: list[int] = []
                first = Account(1, 50, lock=RecordingLock(1, log))
                second = Account(2, 50, lock=RecordingLock(2, log))
                transfer_ordered(second, first, 5, pause=lambda: None)
                return log
            '''
        ),
        md(
            """
            The checks: the naive version deadlocks, the ordered version completes both
            transfers with the right balances, and it locks the lower `account_id` first:
            """
        ),
        code(
            """
            run_checks(
                [
                    (
                        "naive transfers deadlock",
                        lambda: "DeadlockError" in run_opposite_transfers(transfer_naive)["outcomes"],
                        True,
                    ),
                    (
                        "ordered transfers both succeed",
                        lambda: run_opposite_transfers(transfer_ordered)["outcomes"],
                        ["ok", "ok"],
                    ),
                    (
                        "ordered transfers move the money",
                        lambda: run_opposite_transfers(transfer_ordered)["balances"],
                        (110, 90),
                    ),
                    ("lower account_id is locked first", lock_order_used, [1, 2]),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 6 — GIL vs free-threaded CPU benchmark

            `measure_scaling(python_path, thread_count=4, loops=1_000_000)` runs a benchmark
            **in a child interpreter** (`subprocess.run([python_path, "-c", source], ...)`).
            The child script you write times a pure-Python loop of `loops` iterations in one
            thread, then `thread_count` threads each running the same loop at once, and
            prints one JSON line. Return a dict with exactly these keys:

            - `"gil_enabled"`: the child's `sys._is_gil_enabled()`;
            - `"one_thread_seconds"`, `"all_threads_seconds"`: the two wall times;
            - `"speedup"`: `thread_count * one_thread_seconds / all_threads_seconds`.

            The checks run it on this kernel's interpreter and, if installed, on
            `python3.15t` (`FREE_THREADED_PYTHON` from the unit setup). Speedups are only
            printed, except one loose sanity check: the default build cannot reach 1.5×.
            """
        ),
        code(
            '''
            def measure_scaling(
                python_path: str, thread_count: int = 4, loops: int = 1_000_000
            ) -> dict[str, object]:
                """Benchmark 1 vs thread_count CPU-bound threads in a child interpreter."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 6 (the free-threaded check prints a skip line when 3.15t is missing):"),
        code(
            '''
            @functools.cache
            def default_build_scaling() -> dict[str, object]:
                """Benchmark this kernel's interpreter once (exceptions are not cached)."""
                return measure_scaling(sys.executable)


            def free_threaded_reports_no_gil() -> bool:
                """True if 3.15t reports the GIL disabled, or if no 3.15t is installed."""
                if FREE_THREADED_PYTHON is None:
                    print("SKIP  free-threaded interpreter not installed")
                    return True
                return measure_scaling(FREE_THREADED_PYTHON)["gil_enabled"] is False


            def speedup_formula_holds() -> bool:
                """speedup == 4 * one / all for the default-build result."""
                result = default_build_scaling()
                expected = 4 * result["one_thread_seconds"] / result["all_threads_seconds"]
                return math.isclose(result["speedup"], expected, rel_tol=1e-6)
            '''
        ),
        md(
            """
            The checks: the four keys, the GIL flag of this kernel, the speedup formula, the
            one loose sanity bound for the default build, and the GIL flag of 3.15t:
            """
        ),
        code(
            """
            run_checks(
                [
                    (
                        "returns the four keys",
                        lambda: sorted(default_build_scaling()),
                        ["all_threads_seconds", "gil_enabled", "one_thread_seconds", "speedup"],
                    ),
                    (
                        "default build reports the GIL enabled",
                        lambda: default_build_scaling()["gil_enabled"],
                        True,
                    ),
                    ("speedup = threads x one / all", speedup_formula_holds, True),
                    (
                        "default build: no real speedup (< 1.5x)",
                        lambda: default_build_scaling()["speedup"] < 1.5,
                        True,
                    ),
                    ("3.15t reports the GIL disabled", free_threaded_reports_no_gil, True),
                ]
            )
            """
        ),
        md(
            """
            Once the checks pass, this cell prints your measurements side by side. Explain
            them in one sentence each: why the default build stays near 1×, and what limits
            the free-threaded build (core count, the single-thread overhead, other load on
            the machine).
            """
        ),
        code(
            """
            try:
                results = {"default build": default_build_scaling()}
                if FREE_THREADED_PYTHON is not None:
                    results["free-threaded"] = measure_scaling(FREE_THREADED_PYTHON)
                print(f"CPU cores available: {os.process_cpu_count()}")
                for build_name, result in results.items():
                    print(
                        f"{build_name:<14} GIL={result['gil_enabled']!s:<5} "
                        f"1 thread {result['one_thread_seconds']:.3f} s, "
                        f"4 threads {result['all_threads_seconds']:.3f} s, speedup {result['speedup']:.2f}x"
                    )
            except NotImplementedError:
                print("Finish exercise 6 first.")
            """
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 5.1."""
    return [
        md(
            """
            ### Recap — Unit 5.1

            | Concept | One-line takeaway | JS / Node equivalent |
            | --- | --- | --- |
            | Concurrency vs parallelism | Interleaving needs one core; running at the same instant needs several (and no GIL in the way) | one event loop vs `worker_threads` |
            | CPU- vs I/O-bound | Measure `thread_time` / wall time; threads help I/O and GIL-releasing C code | libuv pool helps `fs`/`crypto` |
            | `threading.Thread` | `target=` a function, `start`, `join`; no return value; daemon threads die at exit | `new Worker()` (but isolated) |
            | The GIL | Protects CPython's internals, not your invariants; released for I/O, `sleep` and cooperative C code; handed over every 5 ms | — |
            | Race conditions | `+=` and check-then-act are several bytecodes; built-in single operations are atomic | `Atomics` |
            | Primitives | `Lock`, `RLock`, `(Bounded)Semaphore`, `Event`, `Condition`, `Barrier`, `Timer`; always `with` | `p-limit`, `Atomics.wait` |
            | Deadlocks | Break circular wait with lock ordering, or hold-and-wait with try-lock + back-off | — |
            | Queues | `Queue`/`LifoQueue`/`PriorityQueue`; `task_done` + `join`; sentinels or `shutdown()` (3.13) | message channels |
            | `threading.local` | Per-thread attributes; leaks between tasks in a pool | `AsyncLocalStorage` |
            | `ThreadPoolExecutor` | `submit` → `Future`; `map` keeps order; `as_completed` finish order; check every future | `Promise.all`, `Promise.race` |
            | Errors and shutdown | `threading.excepthook`; no `kill()`; stop with an `Event` and `wait(timeout)` | `worker.terminate()` exists in Node |
            | Free-threaded build | `python3.15t`, `sys._is_gil_enabled()`; real thread parallelism, hidden races exposed | `worker_threads` parallelism |

            **Further reading**

            - [`threading`](https://docs.python.org/3/library/threading.html),
              [`queue`](https://docs.python.org/3/library/queue.html),
              [`concurrent.futures`](https://docs.python.org/3/library/concurrent.futures.html)
            - [`sys.setswitchinterval`](https://docs.python.org/3/library/sys.html#sys.setswitchinterval),
              [FAQ: what kinds of global value mutation are thread-safe?](https://docs.python.org/3/faq/library.html#what-kinds-of-global-value-mutation-are-thread-safe)
            - [Python support for free threading](https://docs.python.org/3/howto/free-threading-python.html),
              [C API extension support for free threading](https://docs.python.org/3/howto/free-threading-extensions.html)
            - [PEP 703](https://peps.python.org/pep-0703/) (making the GIL optional),
              [PEP 779](https://peps.python.org/pep-0779/) (supported status for free-threaded Python)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 5.1 and Lab 5.1."""
    return [
        *_overview_cells(),
        *_core_concept_cells(),
        *_thread_cells(),
        *_gil_cells(),
        *_race_cells(),
        *_primitive_cells(),
        *_queue_cells(),
        *_thread_local_cells(),
        *_executor_cells(),
        *_shutdown_cells(),
        *_free_threading_cells(),
        *_js_bridge_cells(),
        *_predict_cells(),
        *_lab_cells_part_1(),
        *_lab_cells_part_2(),
        *_recap_cells(),
    ]
