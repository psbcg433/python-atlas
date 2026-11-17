"""Reference solutions for Phase 5 labs.

Run from the repository root:

    uv run python exercises/solutions/phase5_solutions.py            # every lab
    uv run python exercises/solutions/phase5_solutions.py "Lab 5.3"  # one lab

Each check_lab_5_N() runs the notebook's own check cells, so the notebook and this file test
exactly the same things. Lab 5.2's worker functions must be importable by child processes, so,
like the notebook's %%writefile cells, this file writes them to notebooks/_scratch/phase5/
(git-ignored) and imports them from there. Timings vary by machine; no check asserts a speedup
except the loose "the default build cannot reach 1.5x with threads" sanity check.
Labs 5.3 and 5.4 are asyncio labs: their checks run in asyncio.run(), and their HTTP checks
use httpx.MockTransport, so no server or network is needed.
Lab 5.5 is a performance lab: speed checks use wide margins against much larger real gaps
and print the measured ratios; memory checks compare tracemalloc peaks.
"""

import asyncio
import concurrent.futures
import contextlib
import contextvars
import cProfile
import functools
import gc
import hashlib
import heapq
import importlib
import importlib.util
import inspect
import itertools
import json
import logging
import math
import multiprocessing
import os
import pstats
import queue
import random
import selectors
import shutil
import socket
import subprocess
import sys
import threading
import time
import timeit
import tracemalloc
import uuid
import warnings
from collections import Counter, deque
from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
    Coroutine,
    Generator,
    Iterable,
    Iterator,
)
from contextlib import contextmanager
from dataclasses import dataclass, field
from multiprocessing import shared_memory
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx

type TestCase = tuple[str, Callable[[], object], object]

REPO_ROOT = Path(__file__).resolve().parents[2]
PHASE5_DIR = REPO_ROOT / "notebooks" / "_scratch" / "phase5"
DEMO_SCALE = int(os.environ.get("PHASE5_DEMO_SCALE", "1"))
HAS_NUMPY = importlib.util.find_spec("numpy") is not None
if HAS_NUMPY:
    import numpy as np


def run_checks(test_cases: list[TestCase]) -> None:
    """Run (label, thunk, expected) cases and print PASS/FAIL for each. Never raises."""
    passed_count = 0
    for label, thunk, expected in test_cases:
        try:
            actual = thunk()
        except Exception as error:  # a check must never stop the run
            print(f"FAIL  {label}: raised {type(error).__name__}: {error}")
            continue
        if actual == expected:
            passed_count += 1
            print(f"PASS  {label}")
        else:
            print(f"FAIL  {label}: expected {expected!r}, got {actual!r}")
    print(f"{passed_count}/{len(test_cases)} checks passed")


def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"


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


def fresh_import(module_name: str) -> ModuleType:
    """Import a module saved under PHASE5_DIR, always re-reading the file from disk."""
    for cached in (PHASE5_DIR / "__pycache__").glob(f"{module_name}.*.pyc"):
        cached.unlink()
    importlib.invalidate_caches()
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


# ----- Lab 5.1: helpers from the lab setup cell -----


def run_threads(work: Callable[[object], object], items: list[object]) -> None:
    """Run work(item) in one thread per item and join them all (a helper for the checks)."""
    threads = [threading.Thread(target=work, args=(item,)) for item in items]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


class UnsafeCounter:
    """Exercise 1: reads, gives up the GIL, then writes, so concurrent updates get lost."""

    def __init__(self) -> None:
        self.value = 0

    def increment(self) -> None:
        current = self.value
        time.sleep(0)  # let another thread run between the read and the write
        self.value = current + 1


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


# ----- Lab 5.1: reference solutions -----


def hammer(counter: object, thread_count: int, increments_per_thread: int) -> int:
    """Increment counter from several threads at once; return the final value."""

    def work() -> None:
        for _ in range(increments_per_thread):
            counter.increment()

    threads = [threading.Thread(target=work) for _ in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return counter.value


class LockedCounter:
    """UnsafeCounter's read / sleep(0) / write, made safe with a Lock."""

    def __init__(self) -> None:
        self.value = 0
        self._lock = threading.Lock()

    def increment(self) -> None:
        with self._lock:
            current = self.value
            time.sleep(0)
            self.value = current + 1


def process_with_workers[T, R](
    items: list[T], handle: Callable[[T], R], worker_count: int
) -> list[R]:
    """Run handle over items with worker_count consumer threads fed by a Queue."""
    work: queue.Queue[tuple[int, T] | None] = queue.Queue()
    results: list[R | None] = [None] * len(items)

    def consume() -> None:
        while (pair := work.get()) is not None:
            index, item = pair
            results[index] = handle(item)
            work.task_done()
        work.task_done()  # the sentinel

    consumers = [
        threading.Thread(target=consume, name=f"consumer-{number}")
        for number in range(1, worker_count + 1)
    ]
    for consumer in consumers:
        consumer.start()
    for pair in enumerate(items):
        work.put(pair)
    for _ in consumers:
        work.put(None)  # one sentinel per consumer
    for consumer in consumers:
        consumer.join()
    return results  # type: ignore[return-value]


def download_all(
    client: httpx.Client, urls: list[str], max_workers: int = 8
) -> dict[str, int | str]:
    """Download urls concurrently; map each to its byte count or error class name."""

    def fetch(url: str) -> int:
        response = client.get(url)
        response.raise_for_status()
        return len(response.content)

    results: dict[str, int | str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {executor.submit(fetch, url): url for url in urls}
        for future in concurrent.futures.as_completed(future_to_url):
            url = future_to_url[future]
            try:
                results[url] = future.result()
            except httpx.HTTPError as error:
                results[url] = type(error).__name__
    return results


class ConnectionPool:
    """At most `size` connections in use; idle connections are reused."""

    def __init__(self, size: int, connect: Callable[[], object]) -> None:
        self._connect = connect
        self._slots = threading.BoundedSemaphore(size)
        self._lock = threading.Lock()
        self._idle: list[object] = []
        self.created = 0
        self.in_use = 0
        self.peak_in_use = 0

    @contextmanager
    def connection(self) -> Iterator[object]:
        with self._slots:
            with self._lock:
                if self._idle:
                    handed_out = self._idle.pop()
                else:
                    handed_out = self._connect()
                    self.created += 1
                self.in_use += 1
                self.peak_in_use = max(self.peak_in_use, self.in_use)
            try:
                yield handed_out
            finally:
                with self._lock:
                    self.in_use -= 1
                    self._idle.append(handed_out)


def run_opposite_transfers(transfer: Callable[[Account, Account, int], None]) -> dict[str, object]:
    """Run two opposite transfers at once; report outcomes and final balances."""
    first, second = Account(1, 100), Account(2, 100)
    outcomes: list[str] = []

    def attempt(source: Account, target: Account, amount: int) -> None:
        try:
            transfer(source, target, amount)
            outcomes.append("ok")
        except Exception as error:
            outcomes.append(type(error).__name__)

    threads = [
        threading.Thread(target=attempt, args=(first, second, 10)),
        threading.Thread(target=attempt, args=(second, first, 20)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return {"outcomes": sorted(outcomes), "balances": (first.balance, second.balance)}


def transfer_ordered(
    source: Account,
    target: Account,
    amount: int,
    pause: Callable[[], None] = lambda: time.sleep(0.05),
) -> None:
    """Move amount from source to target, locking accounts in account_id order."""
    lower, higher = sorted((source, target), key=lambda account: account.account_id)
    acquire_or_fail(lower.lock)
    try:
        pause()
        acquire_or_fail(higher.lock)
        try:
            source.balance -= amount
            target.balance += amount
        finally:
            higher.lock.release()
    finally:
        lower.lock.release()


SCALING_CHILD = """
import json, sys, threading, time

thread_count, loops = int(sys.argv[1]), int(sys.argv[2])

def spin():
    total = 0
    for number in range(loops):
        total += number % 7

def wall_seconds(count):
    threads = [threading.Thread(target=spin) for _ in range(count)]
    start = time.perf_counter()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return time.perf_counter() - start

print(json.dumps({
    "gil_enabled": sys._is_gil_enabled(),
    "one_thread_seconds": wall_seconds(1),
    "all_threads_seconds": wall_seconds(thread_count),
}))
"""


def measure_scaling(
    python_path: str, thread_count: int = 4, loops: int = 1_000_000
) -> dict[str, object]:
    """Benchmark 1 vs thread_count CPU-bound threads in a child interpreter."""
    completed = subprocess.run(
        [python_path, "-c", SCALING_CHILD, str(thread_count), str(loops)],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    result = json.loads(completed.stdout.splitlines()[-1])
    result["speedup"] = thread_count * result["one_thread_seconds"] / result["all_threads_seconds"]
    return result


# ----- Lab 5.2: worker modules (the notebook's %%writefile cells) -----

WORKER_SOURCES = {
    "lab52_hashing.py": '''\
"""Lab 5.2 exercise 1 worker."""

import hashlib
from pathlib import Path


def sha256_file(path: Path) -> tuple[str, str]:
    """Return (file name, SHA-256 hex digest), reading 1 MiB blocks."""
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return path.name, digest.hexdigest()
''',
    "lab52_chunks.py": '''\
"""Lab 5.2 exercise 2 worker (given)."""


def tiny_task(number: int) -> int:
    """A deliberately tiny task."""
    return (number * 7) % 11
''',
    "lab52_shared.py": '''\
"""Lab 5.2 exercise 3 worker."""

from multiprocessing import shared_memory


def scale_slice(block_name: str, length: int, start: int, stop: int, factor: float) -> None:
    """Multiply values[start:stop] of the shared float64 array by factor, in place."""
    import numpy as np

    block = shared_memory.SharedMemory(name=block_name, track=False)
    try:
        values = np.ndarray((length,), dtype=np.float64, buffer=block.buf)
        values[start:stop] *= factor
        del values
    finally:
        block.close()
''',
    "lab52_wordcount.py": '''\
"""Lab 5.2 exercise 4 worker."""

import re
from collections import Counter


def count_words(lines: list[str]) -> Counter[str]:
    """Map step: count the lowercase words in a chunk of lines."""
    counts: Counter[str] = Counter()
    for line in lines:
        counts.update(re.findall(r"[a-z']+", line.lower()))
    return counts
''',
}


def shm_segments() -> set[str]:
    """Names of POSIX shared-memory blocks made by multiprocessing (Linux; empty elsewhere)."""
    folder = Path("/dev/shm")
    return {entry.name for entry in folder.glob("psm_*")} if folder.exists() else set()


if HAS_NUMPY:
    import numpy as np


def prepare_lab_5_2() -> None:
    """Write the worker modules and the lab data, then import the workers (once)."""
    global LAB52_DIR, lab_random, HASH_FILES, WORDS, CORPUS
    global hashing_workers, chunk_workers, shared_workers, wordcount_workers
    PHASE5_DIR.mkdir(parents=True, exist_ok=True)
    if str(PHASE5_DIR) not in sys.path:
        sys.path.insert(0, str(PHASE5_DIR))
    for file_name, source in WORKER_SOURCES.items():
        (PHASE5_DIR / file_name).write_text(source, encoding="utf-8")
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
    hashing_workers = fresh_import("lab52_hashing")
    chunk_workers = fresh_import("lab52_chunks")
    shared_workers = fresh_import("lab52_shared")
    wordcount_workers = fresh_import("lab52_wordcount")


# ----- Lab 5.2: reference solutions (the notebook-side functions) -----


def hash_files(
    paths: list[Path], executor_class: type[concurrent.futures.Executor], max_workers: int = 4
) -> dict[str, str]:
    """Hash files with executor_class(max_workers); return {file name: digest}."""
    with executor_class(max_workers=max_workers) as executor:
        return dict(executor.map(hashing_workers.sha256_file, paths))


def benchmark_hashing(paths: list[Path], max_workers: int = 4) -> dict[str, float]:
    """Seconds for "sequential", "threads" and "processes"."""
    timings: dict[str, float] = {}
    start = time.perf_counter()
    for path in paths:
        hashing_workers.sha256_file(path)
    timings["sequential"] = time.perf_counter() - start
    for name, executor_class in (
        ("threads", concurrent.futures.ThreadPoolExecutor),
        ("processes", concurrent.futures.ProcessPoolExecutor),
    ):
        start = time.perf_counter()
        hash_files(paths, executor_class, max_workers)
        timings[name] = time.perf_counter() - start
    return timings


def time_chunksizes(
    items: list[int], chunksizes: list[int], processes: int = 4
) -> dict[int, float]:
    """Seconds for Pool.map(tiny_task, items, chunksize=c) for each c, using one pool."""
    timings: dict[int, float] = {}
    with multiprocessing.Pool(processes) as pool:
        pool.map(chunk_workers.tiny_task, range(processes))  # warm up
        for chunksize in chunksizes:
            start = time.perf_counter()
            pool.map(chunk_workers.tiny_task, items, chunksize=chunksize)
            timings[chunksize] = time.perf_counter() - start
    return timings


def render_chart(timings: dict[int, float], width: int = 40) -> list[str]:
    """A text bar chart, one line per chunksize in ascending order."""
    slowest = max(timings.values())
    return [
        f"{chunksize:>6} | {'#' * max(1, round(width * seconds / slowest))} {seconds:.3f} s"
        for chunksize, seconds in sorted(timings.items())
    ]


def parallel_scale(values: np.ndarray, factor: float, workers: int = 4) -> np.ndarray:
    """Scale a copy of values in shared memory with one process per slice."""
    source = np.asarray(values, dtype=np.float64)
    block = shared_memory.SharedMemory(create=True, size=max(source.nbytes, 1))
    try:
        shared = np.ndarray(source.shape, dtype=np.float64, buffer=block.buf)
        shared[:] = source
        size, extra = divmod(len(source), workers)
        children, start = [], 0
        for index in range(workers):
            stop = start + size + (1 if index < extra else 0)
            children.append(
                multiprocessing.Process(
                    target=shared_workers.scale_slice,
                    args=(block.name, len(source), start, stop, factor),
                )
            )
            start = stop
        for child in children:
            child.start()
        for child in children:
            child.join()
        result = shared.copy()
        del shared
        return result
    finally:
        block.close()
        block.unlink()


def merge_counts(partials: Iterable[Counter[str]]) -> Counter[str]:
    """Reduce step: add the partial counts."""
    total: Counter[str] = Counter()
    for partial in partials:
        total.update(partial)
    return total


def split_lines(lines: list[str], chunk_count: int) -> list[list[str]]:
    """Nearly equal chunks (sizes differ by at most one)."""
    size, extra = divmod(len(lines), chunk_count)
    chunks, start = [], 0
    for index in range(chunk_count):
        stop = start + size + (1 if index < extra else 0)
        chunks.append(lines[start:stop])
        start = stop
    return chunks


def parallel_word_count(
    lines: list[str], workers: int = 4, chunks_per_worker: int = 4
) -> Counter[str]:
    """Map-reduce word count with a process pool."""
    chunks = split_lines(lines, workers * chunks_per_worker)
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        return merge_counts(pool.map(wordcount_workers.count_words, chunks))


def amdahl_speedup(parallel_fraction: float, workers: int) -> float:
    """Amdahl's law."""
    if not 0 <= parallel_fraction <= 1:
        raise ValueError(f"parallel_fraction must be between 0 and 1, got {parallel_fraction}")
    return 1 / ((1 - parallel_fraction) + parallel_fraction / workers)


def speedup_report(lines: list[str], workers: int = 4) -> dict[str, float]:
    """Measured speedup next to Amdahl's prediction."""
    chunks = split_lines(lines, workers * 4)
    start = time.perf_counter()
    partials = [wordcount_workers.count_words(chunk) for chunk in chunks]
    map_seconds = time.perf_counter() - start
    start = time.perf_counter()
    merge_counts(partials)
    reduce_seconds = time.perf_counter() - start
    sequential_seconds = map_seconds + reduce_seconds
    start = time.perf_counter()
    parallel_word_count(lines, workers)
    parallel_seconds = time.perf_counter() - start
    parallel_fraction = map_seconds / sequential_seconds
    return {
        "sequential_seconds": sequential_seconds,
        "parallel_seconds": parallel_seconds,
        "measured_speedup": sequential_seconds / parallel_seconds,
        "parallel_fraction": parallel_fraction,
        "predicted_speedup": amdahl_speedup(parallel_fraction, workers),
    }


def check_lab_5_1() -> None:
    """The notebook's Lab 5.1 check cells, verbatim."""
    FREE_THREADED_PYTHON = find_free_threaded_python()
    print("--- exercise 1")

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
    print("--- exercise 2")

    def square_slowly(number: int) -> int:
        """A handler that takes a few milliseconds."""
        time.sleep(0.005)
        return number * number

    def consumer_names_used(worker_count: int) -> tuple[int, bool]:
        """How many distinct threads ran the handler, and whether all were named consumer-N."""
        seen: set[str] = set()

        def record(number: int) -> int:
            seen.add(threading.current_thread().name)
            time.sleep(0.01)
            return number

        process_with_workers(list(range(20)), record, worker_count)
        return len(seen), all(name.startswith("consumer-") for name in seen)

    def consumers_still_alive() -> list[str]:
        """Names of consumer threads alive after process_with_workers returns."""
        process_with_workers(list(range(10)), square_slowly, 3)
        return [
            thread.name for thread in threading.enumerate() if thread.name.startswith("consumer-")
        ]

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
            (
                "all 4 consumers took work, named consumer-N",
                lambda: consumer_names_used(4),
                (4, True),
            ),
            ("no consumer thread left alive", consumers_still_alive, []),
            ("uses queue.Queue", lambda: "Queue(" in inspect.getsource(process_with_workers), True),
        ]
    )
    print("--- exercise 3")

    def lab_client(latency: float = 0.05) -> tuple[httpx.Client, dict[str, int]]:
        """A client whose transport sleeps per request and tracks the peak in-flight count."""
        stats = {"now": 0, "peak": 0}
        stats_lock = threading.Lock()

        def handler(request: httpx.Request) -> httpx.Response:
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
            (
                "12 URLs, 4 workers: concurrent but capped",
                lambda: 1 < peak_in_flight(12, 4) <= 4,
                True,
            ),
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
    print("--- exercise 4")

    def make_pool(size: int) -> ConnectionPool:
        """A pool whose connections are numbered strings."""
        numbers = itertools.count(1)
        return ConnectionPool(size, lambda: f"conn-{next(numbers)}")

    def busy_pool(size: int, users: int) -> tuple[int, int, int]:
        """`users` threads each hold a connection for 20 ms; return (peak, created, in_use)."""
        pool = make_pool(size)

        def use(_: object) -> None:
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
    print("--- exercise 5")

    class RecordingLock:
        """A lock that records the account id each time it is acquired."""

        def __init__(self, account_id: int, log: list[int]) -> None:
            self._lock, self._account_id, self._log = threading.Lock(), account_id, log

        def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
            acquired = self._lock.acquire(blocking, timeout)
            if acquired:
                self._log.append(self._account_id)
            return acquired

        def release(self) -> None:
            self._lock.release()

    def lock_order_used() -> list[int]:
        """Account ids in the order transfer_ordered locked them, transferring 2 -> 1."""
        log: list[int] = []
        first = Account(1, 50, lock=RecordingLock(1, log))
        second = Account(2, 50, lock=RecordingLock(2, log))
        transfer_ordered(second, first, 5, pause=lambda: None)
        return log

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
    print("--- exercise 6")

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


def check_lab_5_2() -> None:
    """The notebook's Lab 5.2 check cells, verbatim."""
    prepare_lab_5_2()
    print("--- exercise 1")
    EXPECTED_DIGESTS = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in HASH_FILES
    }
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
    print("--- exercise 2")
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
    print("--- exercise 3")

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
                    [10.0 * index for index in range(10)],
                ),
                (
                    "one worker",
                    lambda: parallel_scale(np.arange(3.0), -1.0, 1).tolist(),
                    [0.0, -1.0, -2.0],
                ),
                (
                    "returns float64",
                    lambda: str(parallel_scale(np.arange(4), 2.0).dtype),
                    "float64",
                ),
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
    print("--- exercise 4")
    SAMPLE_LINES = ["The shop's tea", "the TEA was late", ""]

    def report_consistent() -> bool:
        """The report's numbers agree with each other."""
        report = speedup_report(CORPUS[:20_000], 4)
        return (
            math.isclose(
                report["measured_speedup"],
                report["sequential_seconds"] / report["parallel_seconds"],
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


# ----- Lab 5.3: unit code the lab relies on -----


type ToyCoroutine = Generator[object, object, object]


class RoundRobinLoop:
    """Step 1: a ready queue of generators, resumed in turn until each finishes."""

    def __init__(self) -> None:
        self.ready: deque[tuple[ToyCoroutine, object]] = deque()
        self.steps = 0

    def spawn(self, coroutine: ToyCoroutine) -> object:
        """Schedule a new task; it starts on the next pass."""
        self.ready.append((coroutine, None))
        return None

    def run(self) -> None:
        """Run until no task is left."""
        while self.ready:
            self.run_ready()

    def run_ready(self) -> None:
        """Resume every task that was ready when this pass started."""
        for _ in range(len(self.ready)):
            coroutine, value = self.ready.popleft()
            self.steps += 1
            try:
                request = coroutine.send(value)
            except StopIteration as stop:
                self.finish(coroutine, stop.value)
            else:
                self.handle(coroutine, request)

    def handle(self, coroutine: ToyCoroutine, request: object) -> None:
        """Step 1 understands one request: run me again on the next pass."""
        self.ready.append((coroutine, None))

    def finish(self, coroutine: ToyCoroutine, result: object) -> None:
        """A task returned. Step 5 stores the result."""


class TimerLoop(RoundRobinLoop):
    """Step 2: a task may yield ("sleep", seconds); sleepers wait in a heap."""

    def __init__(self) -> None:
        super().__init__()
        self.timers: list[tuple[float, int, ToyCoroutine]] = []
        self.tie_breaker = itertools.count()

    def handle(self, coroutine: ToyCoroutine, request: object) -> None:
        match request:
            case ("sleep", float() | int() as seconds):
                wake_at = time.monotonic() + seconds
                heapq.heappush(self.timers, (wake_at, next(self.tie_breaker), coroutine))
            case _:
                super().handle(coroutine, request)

    def run(self) -> None:
        """Each iteration: wait, release due timers, run what is ready."""
        while self.ready or self.timers or self.waiting_for_io():
            self.wait_for_events(self.timeout())
            while self.timers and self.timers[0][0] <= time.monotonic():
                _, _, coroutine = heapq.heappop(self.timers)
                self.ready.append((coroutine, None))
            self.run_ready()

    def timeout(self) -> float | None:
        """0 if work is ready, else until the next timer, else forever (None)."""
        if self.ready:
            return 0
        if self.timers:
            return max(0.0, self.timers[0][0] - time.monotonic())
        return None

    def wait_for_events(self, timeout: float | None) -> None:
        if timeout:
            time.sleep(timeout)  # nothing else to do until the next timer

    def waiting_for_io(self) -> bool:
        return False


class IOLoop(TimerLoop):
    """Step 3: a task may yield ("read", sock) or ("write", sock)."""

    def __init__(self) -> None:
        super().__init__()
        self.selector = selectors.DefaultSelector()

    def handle(self, coroutine: ToyCoroutine, request: object) -> None:
        match request:
            case ("read", socket.socket() as sock):
                self.selector.register(sock, selectors.EVENT_READ, coroutine)
            case ("write", socket.socket() as sock):
                self.selector.register(sock, selectors.EVENT_WRITE, coroutine)
            case _:
                super().handle(coroutine, request)

    def waiting_for_io(self) -> bool:
        return bool(self.selector.get_map())

    def wait_for_events(self, timeout: float | None) -> None:
        """select() instead of sleep(): wake up early when a socket is ready."""
        if not self.waiting_for_io():
            return super().wait_for_events(timeout)
        for key, _ in self.selector.select(timeout):
            self.selector.unregister(key.fileobj)  # one-shot registration
            self.ready.append((key.data, None))


class ToyTask:
    """What asyncio calls a Task: a running coroutine plus its result and waiters."""

    def __init__(self, coroutine: ToyCoroutine) -> None:
        self.coroutine = coroutine
        self.done = False
        self.result: object = None
        self.waiters: list[ToyCoroutine] = []


class ToyLoop(IOLoop):
    """Step 5: spawn() returns a ToyTask; a task may yield ("join", other_task)."""

    def __init__(self) -> None:
        super().__init__()
        self.tasks: dict[ToyCoroutine, ToyTask] = {}

    def spawn(self, coroutine: ToyCoroutine) -> ToyTask:
        task = self.tasks[coroutine] = ToyTask(coroutine)
        super().spawn(coroutine)
        return task

    def handle(self, coroutine: ToyCoroutine, request: object) -> None:
        match request:
            case ("join", ToyTask() as other) if other.done:
                self.ready.append((coroutine, other.result))
            case ("join", ToyTask() as other):
                other.waiters.append(coroutine)  # resumed by finish()
            case _:
                super().handle(coroutine, request)

    def finish(self, coroutine: ToyCoroutine, result: object) -> None:
        task = self.tasks.pop(coroutine)
        task.done, task.result = True, result
        for waiter in task.waiters:  # like a Future's done-callbacks
            self.ready.append((waiter, result))


class Ask:
    """An awaitable that hands a question to the driver and returns its reply."""

    def __init__(self, question: str) -> None:
        self.question = question

    def __await__(self) -> Generator[str, object, object]:
        reply = yield self.question
        return reply


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


# ----- Lab 5.3: helpers and given code from the lab cells -----


async def outcome(awaitable: Awaitable[object]) -> object:
    """Await and return the result, or "raised ErrorName". Never raises an Exception."""
    try:
        return await awaitable
    except Exception as error:
        return f"raised {type(error).__name__}"


@contextlib.contextmanager
def quiet_unawaited() -> Generator[None]:
    """Hide "coroutine ... was never awaited" warnings caused by unfinished stubs."""
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", "coroutine .* was never awaited", RuntimeWarning)
        yield
        gc.collect()


def run_toy(main: Callable[[ToyLoop], ToyCoroutine]) -> tuple[object, float]:
    """Run main(loop) on a fresh ToyLoop; return (its result, seconds taken)."""
    loop = ToyLoop()
    started = time.perf_counter()
    main_task = loop.spawn(main(loop))
    loop.run()
    return main_task.result, time.perf_counter() - started


async def run_puzzle(puzzle: Callable[[list[str]], Coroutine[Any, Any, None]]) -> list[str]:
    """Run one ordering puzzle and return its log (stragglers get 50 ms to finish)."""
    log: list[str] = []
    await puzzle(log)
    await asyncio.sleep(0.05)
    return log


PRICE_BOOK = {"price:chai": 20, "price:vada": 15, "gst": 5}


def book_responder(request: object) -> object:
    """Answer a request from PRICE_BOOK (KeyError if unknown)."""
    return PRICE_BOOK[str(request)]


async def order_total(sku: str, quantity: int) -> int:
    price = await Ask(f"price:{sku}")
    gst_percent = await Ask("gst")
    return price * quantity * (100 + gst_percent) // 100


async def safe_price(sku: str) -> object:
    try:
        return await Ask(f"price:{sku}")
    except KeyError:
        return "unavailable"


async def strict_price(sku: str) -> object:
    return await Ask(f"price:{sku}")  # lets a KeyError escape


async def no_questions() -> str:
    return "instant"


def toy_sleep_then(value: object, seconds: float) -> ToyCoroutine:
    """Sleep on the toy loop, then return value."""
    yield ("sleep", seconds)
    return value


def toy_instant(value: object) -> ToyCoroutine:
    """Return value on the first step, without ever yielding."""
    if False:
        yield
    return value


WIDGETS = ["sales", "stock", "orders", "returns", "reviews"]


async def fetch_widget(name: str, seconds: float = 1.0) -> str:
    await asyncio.sleep(seconds)
    return f"{name}: ok"


async def load_dashboard_sequential() -> dict[str, str]:
    return {name: await fetch_widget(name) for name in WIDGETS}


RACE_LOG: list[str] = []


async def contender(name: str, seconds: float, fail: bool = False) -> str:
    try:
        await asyncio.sleep(seconds)
    except asyncio.CancelledError:
        RACE_LOG.append(f"{name} cancelled")
        raise
    if fail:
        raise ConnectionError(f"{name} failed")
    return name


async def puzzle_1(log: list[str]) -> None:
    async def child() -> None:
        log.append("child")

    asyncio.create_task(child())
    log.append("parent")
    await asyncio.sleep(0)


async def puzzle_2(log: list[str]) -> None:
    async def child(name: str) -> None:
        log.append(name)

    background = asyncio.create_task(child("task"))
    await child("direct")
    log.append("after direct")
    await background


async def puzzle_3(log: list[str]) -> None:
    loop = asyncio.get_running_loop()
    loop.call_later(0, log.append, "later")
    loop.call_soon(log.append, "soon")
    log.append("now")
    await asyncio.sleep(0.01)


async def puzzle_4(log: list[str]) -> None:  # needs Python 3.14+ (eager_start)
    async def child(name: str) -> None:
        log.append(f"{name} start")
        await asyncio.sleep(0)
        log.append(f"{name} end")

    asyncio.create_task(child("lazy"))
    asyncio.create_task(child("eager"), eager_start=True)
    log.append("parent")
    await asyncio.sleep(0.01)


async def puzzle_5(log: list[str]) -> None:
    async def child() -> int:
        log.append("child")
        return 1

    task = asyncio.create_task(child())
    task.add_done_callback(lambda _: log.append("callback"))
    await task
    log.append("awaiter")


async def puzzle_6(log: list[str]) -> None:
    async def step(name: str, delay: float) -> str:
        await asyncio.sleep(delay)
        log.append(name)
        return name

    results = await asyncio.gather(step("a", 0.02), step("b", 0), step("c", 0.01))
    log.append("+".join(results))


async def puzzle_7(log: list[str]) -> None:
    async def child() -> None:
        try:
            log.append("child start")
            await asyncio.sleep(1)
        finally:
            log.append("child finally")

    task = asyncio.create_task(child())
    await asyncio.sleep(0)
    task.cancel()
    log.append("cancel requested")
    try:
        await task
    except asyncio.CancelledError:
        log.append("parent saw CancelledError")


async def puzzle_8(log: list[str]) -> None:
    loop = asyncio.get_running_loop()
    signal = loop.create_future()

    async def waiter(name: str) -> None:
        await signal
        log.append(name)

    waiters = [asyncio.create_task(waiter(name)) for name in ("w1", "w2")]
    await asyncio.sleep(0)
    signal.add_done_callback(lambda _: log.append("callback"))
    loop.call_soon(log.append, "call_soon")
    signal.set_result(None)
    log.append("set")
    await asyncio.gather(*waiters)


PUZZLES = {
    1: puzzle_1,
    2: puzzle_2,
    3: puzzle_3,
    4: puzzle_4,
    5: puzzle_5,
    6: puzzle_6,
    7: puzzle_7,
    8: puzzle_8,
}


async def chat_scenario(room_factory: Callable[[], Any]) -> dict[str, object]:
    """Run a three-client conversation against room_factory().handle."""
    room, errors, clients = room_factory(), [], {}

    async def guarded(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await room.handle(reader, writer)
        except Exception as error:  # keep failures out of the kernel log
            errors.append(type(error).__name__)
            writer.close()

    async def send(nick: str, line: str) -> None:
        clients[nick][1].write(f"{line}\n".encode())
        with contextlib.suppress(ConnectionError):  # the server may have dropped us
            await clients[nick][1].drain()
        await asyncio.sleep(0.05)  # let the server deliver before the next step

    async def received(nick: str) -> list[str]:
        lines = []
        while True:
            try:
                line = await asyncio.wait_for(clients[nick][0].readline(), 0.1)
            except TimeoutError:
                return lines
            if not line:
                return lines
            lines.append(line.decode().rstrip("\n"))

    server = await asyncio.start_server(guarded, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        for nick in ("asha", "ben", "chen"):
            clients[nick] = await asyncio.open_connection("127.0.0.1", port)
            await send(nick, nick)
        await send("asha", "hello")
        await send("ben", "hi asha")
        transcripts = {"chen": await received("chen")}
        clients["chen"][1].close()
        await asyncio.sleep(0.05)
        transcripts |= {nick: await received(nick) for nick in ("asha", "ben")}
        errors_seen = list(errors)
    finally:
        for _, writer in clients.values():
            writer.close()
        server.close()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(server.wait_closed(), 1)
    return {"transcripts": transcripts, "errors": errors_seen}


# ----- Lab 5.3: reference solutions -----


def drive(
    coroutine: Coroutine[Any, Any, Any], responder: Callable[[object], object]
) -> tuple[list[object], object]:
    """Run coroutine to completion, answering each yielded request with responder."""
    requests: list[object] = []
    try:
        request = coroutine.send(None)
        while True:
            requests.append(request)
            try:
                reply = responder(request)
            except Exception as error:
                request = coroutine.throw(error)
            else:
                request = coroutine.send(reply)
    except StopIteration as stop:
        return requests, stop.value


def toy_gather(
    loop: ToyLoop, coroutines: list[ToyCoroutine]
) -> Generator[object, object, list[object]]:
    """Spawn every coroutine on loop, join them all, return results in input order."""
    tasks = [loop.spawn(coroutine) for coroutine in coroutines]  # all start before we wait
    results: list[object] = []
    for task in tasks:
        results.append((yield ("join", task)))
    return results


async def load_dashboard_concurrent() -> dict[str, str]:
    """The same dict as load_dashboard_sequential(), in about 1 s."""
    contents = await asyncio.gather(*(fetch_widget(name) for name in WIDGETS))
    return dict(zip(WIDGETS, contents, strict=True))


async def race(coroutines: Iterable[Coroutine[Any, Any, Any]]) -> Any:
    """Return the first result (or raise the first error); cancel and await the rest."""
    tasks = [asyncio.ensure_future(coroutine) for coroutine in coroutines]
    if not tasks:
        raise ValueError("race() needs at least one coroutine")
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()  # no effect on tasks that already finished
        await asyncio.gather(*tasks, return_exceptions=True)  # wait for the cancellations
    winner = next(task for task in tasks if task in done)
    return winner.result()


def predictions() -> dict[int, list[str]]:
    """Your predicted final log for each puzzle: {1: [...], 2: [...], ..., 8: [...]}."""
    return {
        1: ["parent", "child"],
        2: ["direct", "after direct", "task"],
        3: ["now", "soon", "later"],
        4: ["eager start", "parent", "lazy start", "eager end", "lazy end"],
        5: ["child", "callback", "awaiter"],
        6: ["b", "c", "a", "a+b+c"],
        7: ["child start", "cancel requested", "child finally", "parent saw CancelledError"],
        8: ["set", "call_soon", "w1", "w2", "callback"],
    }


class ChatRoom:
    """A chat room served with asyncio streams (protocol in the exercise text)."""

    def __init__(self) -> None:
        self.members: dict[asyncio.StreamWriter, str] = {}

    async def broadcast(self, sender: asyncio.StreamWriter, line: str) -> None:
        """Send line to every member except sender; drop members that have gone away."""
        for writer in list(self.members):
            if writer is sender:
                continue
            try:
                writer.write(f"{line}\n".encode())
                await writer.drain()
            except ConnectionError:
                self.members.pop(writer, None)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Serve one client: nickname line first, then chat lines until EOF."""
        nick = (await reader.readline()).decode().strip()
        if not nick:
            writer.close()
            return
        self.members[writer] = nick
        await self.broadcast(writer, f"* {nick} joined")
        try:
            while line := await reader.readline():
                await self.broadcast(writer, f"{nick}: {line.decode().rstrip()}")
        except ConnectionError:
            pass
        finally:
            self.members.pop(writer, None)
            await self.broadcast(writer, f"* {nick} left")
            writer.close()


# ----- Lab 5.4: helpers and given code from the lab cells -----


class InFlightTracker:
    """Counts concurrent requests inside a mock transport handler."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.now, self.peak, self.calls = 0, 0, Counter()

    @contextlib.contextmanager
    def track(self, key: object) -> Generator[None]:
        self.now += 1
        self.peak = max(self.peak, self.now)
        self.calls[key] += 1
        try:
            yield
        finally:
            self.now -= 1


def mock_client(handler: Callable[[httpx.Request], Awaitable[httpx.Response]]) -> httpx.AsyncClient:
    """An AsyncClient whose requests go to handler instead of the network."""
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.shop.test"
    )


async def loop_lag_during(work: Callable[[], Awaitable[object]], interval: float = 0.01) -> float:
    """Run work() while a 10 ms heartbeat runs; return the heartbeat's worst lateness in seconds."""
    stop, worst = asyncio.Event(), [0.0]

    async def beat() -> None:
        while not stop.is_set():
            before = asyncio.get_running_loop().time()
            await asyncio.sleep(interval)
            worst[0] = max(worst[0], asyncio.get_running_loop().time() - before - interval)

    monitor = asyncio.create_task(beat())
    await asyncio.sleep(0.02)
    try:
        await work()
    finally:
        stop.set()
        await monitor
    return worst[0]


def scenario_field(result: object, key: str) -> object:
    """result[key] if result is a dict (a finished scenario), else result itself (an error)."""
    return result[key] if isinstance(result, dict) else result


catalog_tracker = InFlightTracker()


async def catalog_api(request: httpx.Request) -> httpx.Response:
    """GET /items/<n>: 10 ms each; item 13 answers 500, item 21 refuses to connect."""
    item_id = int(request.url.path.rsplit("/", 1)[1])
    with catalog_tracker.track(item_id):
        await asyncio.sleep(0.01)
        if item_id == 13:
            return httpx.Response(500)
        if item_id == 21:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json={"id": item_id, "price": item_id * 10})


RETRY_CALLS: list[str] = []


async def flaky_inventory_call(
    fail_times: int, error_type: type[Exception] = ConnectionError
) -> str:
    """Fails fail_times times with error_type, then succeeds."""
    RETRY_CALLS.append(error_type.__name__)
    if len(RETRY_CALLS) <= fail_times:
        raise error_type(f"attempt {len(RETRY_CALLS)} failed")
    return f"ok after {len(RETRY_CALLS)} calls"


PAGED_ITEMS = [{"id": item_id, "sku": f"sku-{item_id:03d}"} for item_id in range(45)]


page_requests: list[dict[str, str]] = []


async def paged_api(request: httpx.Request) -> httpx.Response:
    """Cursor pagination over PAGED_ITEMS (/products) or nothing (/empty)."""
    query = dict(request.url.params)
    page_requests.append(query)
    items = PAGED_ITEMS if request.url.path == "/products" else []
    start, limit = int(query.get("cursor", 0)), int(query.get("limit", 10))
    next_start = start + limit
    next_cursor = str(next_start) if next_start < len(items) else None
    return httpx.Response(200, json={"items": items[start:next_start], "next_cursor": next_cursor})


def _legacy_pdf(order_id: int) -> str:
    time.sleep(0.1)  # a synchronous PDF library
    return f"invoice-{order_id}.pdf"


def _tax_table(region: str) -> dict[str, object]:
    end = time.perf_counter() + 0.1
    while time.perf_counter() < end:  # a CPU-heavy pure-Python loop
        pass
    return {"region": region, "gst": 18}


async def load_profile() -> dict[str, object]:
    await asyncio.sleep(0.15)  # slow, but it awaits: harmless
    return {"user": "asha"}


async def render_invoice() -> dict[str, object]:
    await asyncio.sleep(0.01)
    return {"file": _legacy_pdf(42)}


async def send_sms() -> dict[str, object]:
    await asyncio.sleep(0.02)
    return {"sms": "sent"}


async def lookup_tax() -> dict[str, object]:
    await asyncio.sleep(0.01)
    return _tax_table("KA")


HANDLERS_A = {"load_profile": load_profile, "render_invoice": render_invoice, "send_sms": send_sms}


HANDLERS_B = {"load_profile": load_profile, "send_sms": send_sms, "lookup_tax": lookup_tax}


REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar("lab_request_id", default="-")


request_records: list[tuple[str, str]] = []


class CaptureRequestIds(logging.Handler):
    """Record (current request id, message) for every log call."""

    def emit(self, record: logging.LogRecord) -> None:
        request_records.append((REQUEST_ID.get(), record.getMessage()))


request_log = logging.getLogger("lab54.requests")


request_log.handlers[:] = [CaptureRequestIds()]


request_log.setLevel(logging.INFO)


request_log.propagate = False


def audit_trail(path: str) -> str:
    """Runs in a worker thread; returns the request id it can see."""
    return REQUEST_ID.get()


async def echo_request_id_api(request: httpx.Request) -> httpx.Response:
    await asyncio.sleep(0.005)  # let concurrent requests interleave
    return httpx.Response(
        200, json={"x-request-id": request.headers.get("x-request-id", "missing")}
    )


STORE_COUNT = 500


store_tracker = InFlightTracker()


async def sales_api(request: httpx.Request) -> httpx.Response:
    """Store sales; some stores hang, some always fail, some fail once with 503."""
    store_id = int(request.url.path.split("/")[2])
    with store_tracker.track(store_id):
        if store_id % 97 == 3:
            await asyncio.sleep(1.0)  # hangs: must be cut off by the timeout
        await asyncio.sleep(0.01)
        if store_id % 50 == 7:
            return httpx.Response(500)
        if store_id % 40 == 11 and store_tracker.calls[store_id] == 1:
            return httpx.Response(503)  # busy once, fine on retry
        return httpx.Response(200, json={"store": store_id, "amount": store_id * 37 % 1000})


# ----- Lab 5.4: reference solutions -----


async def fetch_all(
    client: httpx.AsyncClient, urls: list[str], max_concurrency: int
) -> list[object]:
    """GET every URL, at most max_concurrency at a time; JSON or error name, in input order."""
    slots = asyncio.Semaphore(max_concurrency)

    async def fetch_one(url: str) -> object:
        async with slots:
            try:
                response = await client.get(url)
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as error:
                return type(error).__name__

    return list(await asyncio.gather(*(fetch_one(url) for url in urls)))


class WorkerPool:
    """Fixed-size pool of worker tasks fed by a bounded queue."""

    def __init__(
        self, job: Callable[[Any], Awaitable[object]], worker_count: int = 3, queue_size: int = 10
    ) -> None:
        self.job = job
        self.worker_count = worker_count
        self.queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=queue_size)
        self.workers: list[asyncio.Task[None]] = []
        self.results: dict[Any, object] = {}
        self.closed = False

    async def start(self) -> None:
        self.workers = [
            asyncio.create_task(self._work(), name=f"pool-worker-{worker_number}")
            for worker_number in range(self.worker_count)
        ]

    async def _work(self) -> None:
        while True:
            try:
                item = await self.queue.get()
            except asyncio.QueueShutDown:
                return
            try:
                self.results[item] = await self.job(item)
            except Exception as error:
                self.results[item] = type(error).__name__
            finally:
                self.queue.task_done()

    async def submit(self, item: Any) -> None:
        if self.closed:
            raise RuntimeError("the pool is shutting down")
        await self.queue.put(item)

    async def shutdown(self, immediate: bool = False) -> dict[Any, object]:
        self.closed = True
        self.queue.shutdown(immediate=immediate)
        if immediate:
            for worker in self.workers:
                worker.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
        return dict(self.results)


def retry_async[**P, R](
    *,
    attempts: int = 3,
    base_delay: float = 0.1,
    max_delay: float = 2.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
    rng: random.Random | None = None,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Retry an async function with full-jitter exponential backoff."""
    jitter = rng if rng is not None else random.Random()

    def decorate(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            for attempt in range(1, attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except retry_on:
                    if attempt == attempts:
                        raise
                await sleep(jitter.uniform(0, min(max_delay, base_delay * 2 ** (attempt - 1))))
            raise AssertionError("unreachable")

        return wrapper

    return decorate


async def paginate(
    client: httpx.AsyncClient, path: str, page_size: int = 10
) -> AsyncIterator[dict[str, Any]]:
    """Yield every item of a cursor-paginated endpoint, fetching pages lazily."""
    cursor: str | None = None
    while True:
        params: dict[str, str | int] = {"limit": page_size}
        if cursor is not None:
            params["cursor"] = cursor
        response = await client.get(path, params=params)
        response.raise_for_status()
        page = response.json()
        for item in page["items"]:
            yield item
        cursor = page["next_cursor"]
        if cursor is None:
            return


async def find_blocking_handler(
    handlers: dict[str, Callable[[], Awaitable[object]]], threshold: float = 0.05
) -> str:
    """Name of the handler that blocks the event loop for longer than threshold seconds."""
    lags = {name: await loop_lag_during(handler) for name, handler in handlers.items()}
    culprit = max(lags, key=lags.__getitem__)
    if lags[culprit] <= threshold:
        raise LookupError(f"no handler blocked the loop for more than {threshold} s")
    return culprit


async def render_invoice_fixed() -> dict[str, object]:
    """Same result as render_invoice(), without blocking the loop."""
    await asyncio.sleep(0.01)
    return {"file": await asyncio.to_thread(_legacy_pdf, 42)}


def make_traced_client(transport: httpx.AsyncBaseTransport) -> httpx.AsyncClient:
    """AsyncClient whose request hook adds X-Request-ID from REQUEST_ID."""

    async def add_request_id(request: httpx.Request) -> None:
        request.headers["X-Request-ID"] = REQUEST_ID.get()

    return httpx.AsyncClient(
        transport=transport,
        base_url="https://api.shop.test",
        event_hooks={"request": [add_request_id]},
    )


async def handle_request(
    client: httpx.AsyncClient, path: str, request_id: str | None = None
) -> dict[str, str]:
    """Serve one request with REQUEST_ID set; return request_id, echoed header and audit value."""
    token = REQUEST_ID.set(request_id or uuid.uuid4().hex[:8])
    try:
        request_log.info("start %s", path)
        response = await client.get(path)
        audit = await asyncio.to_thread(audit_trail, path)
        request_log.info("done %s", path)
        return {
            "request_id": REQUEST_ID.get(),
            "echoed": response.json()["x-request-id"],
            "audit": audit,
        }
    finally:
        REQUEST_ID.reset(token)


async def aggregate_sales(
    client: httpx.AsyncClient, store_ids: list[int], max_concurrency: int = 50, timeout: float = 0.2
) -> dict[str, object]:
    """Fetch every store's sales concurrently; return total, ok count and failed ids."""
    slots = asyncio.Semaphore(max_concurrency)

    async def store_amount(store_id: int) -> int | None:
        async with slots:
            for attempt in range(2):
                try:
                    async with asyncio.timeout(timeout):
                        response = await client.get(f"/stores/{store_id}/sales")
                except TimeoutError, httpx.TransportError:
                    return None
                if response.status_code == 503 and attempt == 0:
                    continue
                return response.json()["amount"] if response.is_success else None
            return None

    amounts = await asyncio.gather(*(store_amount(store_id) for store_id in store_ids))
    failed = sorted(
        store_id for store_id, amount in zip(store_ids, amounts, strict=True) if amount is None
    )
    return {
        "total": sum(amount for amount in amounts if amount is not None),
        "ok": len(store_ids) - len(failed),
        "failed": failed,
    }


# ----- Lab 5.3 and Lab 5.4: the notebook's check cells -----


async def _lab_5_3_checks() -> None:
    """The notebook's Lab 5.3 check cells, in order."""
    with quiet_unawaited():
        run_checks(
            [
                (
                    "two requests answered",
                    lambda: drive(order_total("chai", 2), book_responder),
                    (["price:chai", "gst"], 42),
                ),
                (
                    "responder error thrown in and handled",
                    lambda: drive(safe_price("dosa"), book_responder),
                    (["price:dosa"], "unavailable"),
                ),
                (
                    "unhandled error propagates",
                    lambda: raised_error_name(lambda: drive(strict_price("dosa"), book_responder)),
                    "KeyError",
                ),
                (
                    "no requests at all",
                    lambda: drive(no_questions(), book_responder),
                    ([], "instant"),
                ),
            ]
        )

    def gather_three(loop: ToyLoop) -> ToyCoroutine:
        specs = [("a", 0.2), ("b", 0.1), ("c", 0.15)]
        return (
            yield from toy_gather(
                loop, [toy_sleep_then(value, seconds) for value, seconds in specs]
            )
        )

    def gather_mixed(loop: ToyLoop) -> ToyCoroutine:
        return (yield from toy_gather(loop, [toy_sleep_then("later", 0.05), toy_instant("now")]))

    def gather_nothing(loop: ToyLoop) -> ToyCoroutine:
        return (yield from toy_gather(loop, []))

    three_run = functools.cache(lambda: run_toy(gather_three))
    run_checks(
        [
            ("results in input order", lambda: three_run()[0], ["a", "b", "c"]),
            ("sleeps overlap (< 0.35 s, not 0.45 s)", lambda: three_run()[1] < 0.35, True),
            (
                "joining a task that already finished",
                lambda: run_toy(gather_mixed)[0],
                ["later", "now"],
            ),
            ("empty list", lambda: run_toy(gather_nothing)[0], []),
        ]
    )

    with Timer("load_dashboard_concurrent", report=None) as dashboard_timer:
        dashboard = await outcome(load_dashboard_concurrent())
    finished = isinstance(dashboard, dict)
    run_checks(
        [
            (
                "same widgets as the sequential version",
                lambda: dashboard,
                {name: f"{name}: ok" for name in WIDGETS},
            ),
            ("keys in WIDGETS order", lambda: list(dashboard) if finished else dashboard, WIDGETS),
            (
                "about 1 s (< 1.5 s)",
                lambda: finished and dashboard_timer.elapsed_seconds < 1.5,
                True,
            ),
        ]
    )

    with quiet_unawaited():
        RACE_LOG.clear()
        race_winner = await outcome(
            race([contender("slow", 0.2), contender("fast", 0.01), contender("mid", 0.1)])
        )
        losers_cancelled = sorted(RACE_LOG)
        RACE_LOG.clear()
        race_failure = await outcome(
            race([contender("broken", 0.01, fail=True), contender("steady", 0.2)])
        )
        failure_cancelled = sorted(RACE_LOG)
        race_single = await outcome(race([contender("solo", 0)]))
        race_empty = await outcome(race([]))
    run_checks(
        [
            ("fastest result wins", lambda: race_winner, "fast"),
            (
                "losers cancelled before race returns",
                lambda: losers_cancelled,
                ["mid cancelled", "slow cancelled"],
            ),
            ("the winner's exception propagates", lambda: race_failure, "raised ConnectionError"),
            (
                "losers cancelled after a failure too",
                lambda: failure_cancelled,
                ["steady cancelled"],
            ),
            ("one contender", lambda: race_single, "solo"),
            ("no contenders -> ValueError", lambda: race_empty, "raised ValueError"),
        ]
    )

    puzzle_logs = {}
    for number, puzzle in PUZZLES.items():
        puzzle_logs[number] = await run_puzzle(puzzle)
    run_checks(
        [
            (f"puzzle {number}", lambda number=number: predictions()[number], log)
            for number, log in puzzle_logs.items()
        ]
    )

    chat_result = await outcome(chat_scenario(ChatRoom))
    chat_transcripts = chat_result["transcripts"] if isinstance(chat_result, dict) else {}
    run_checks(
        [
            (
                "asha's screen",
                lambda: chat_transcripts.get("asha"),
                ["* ben joined", "* chen joined", "ben: hi asha", "* chen left"],
            ),
            (
                "ben's screen",
                lambda: chat_transcripts.get("ben"),
                ["* chen joined", "asha: hello", "* chen left"],
            ),
            (
                "chen's screen",
                lambda: chat_transcripts.get("chen"),
                ["asha: hello", "ben: hi asha"],
            ),
            (
                "no handler errors",
                lambda: chat_result["errors"] if isinstance(chat_result, dict) else chat_result,
                [],
            ),
        ]
    )


def check_lab_5_3() -> None:
    """Run every Lab 5.3 check (each check prints PASS/FAIL)."""
    asyncio.run(_lab_5_3_checks())


async def _lab_5_4_checks() -> None:
    """The notebook's Lab 5.4 check cells, in order."""
    catalog_urls = [f"/items/{item_id}" for item_id in range(30)]
    expected_catalog = [
        "HTTPStatusError"
        if item_id == 13
        else "ConnectError"
        if item_id == 21
        else {"id": item_id, "price": item_id * 10}
        for item_id in range(30)
    ]
    catalog_tracker.reset()
    async with mock_client(catalog_api) as catalog_client:
        with Timer("fetch_all", report=None) as fetch_timer:
            fetched = await outcome(fetch_all(catalog_client, catalog_urls, max_concurrency=5))
        fetched_nothing = await outcome(fetch_all(catalog_client, [], max_concurrency=5))
    run_checks(
        [
            ("results in input order, errors as names", lambda: fetched, expected_catalog),
            ("never more than 5 requests in flight", lambda: 0 < catalog_tracker.peak <= 5, True),
            ("actually concurrent (peak == 5)", lambda: catalog_tracker.peak, 5),
            (
                "faster than sequential 30 x 10 ms",
                lambda: isinstance(fetched, list) and fetch_timer.elapsed_seconds < 0.2,
                True,
            ),
            ("empty URL list", lambda: fetched_nothing, []),
        ]
    )

    async def double_later(item: int) -> int:
        await asyncio.sleep(0.01)
        if item == 7:
            raise ValueError("unlucky item")
        return item * 2

    async def slow_job(item: int) -> int:
        await asyncio.sleep(0.05)
        return item

    async def graceful_scenario() -> dict[str, object]:
        pool = WorkerPool(double_later, worker_count=3, queue_size=4)
        await pool.start()
        with Timer("12 jobs", report=None) as pool_timer:
            for item in range(12):
                await pool.submit(item)
            results = await pool.shutdown()
        return {
            "results": results,
            "seconds": pool_timer.elapsed_seconds,
            "workers": len(pool.workers),
            "all_exited": all(worker.done() for worker in pool.workers),
            "late_submit": await outcome(pool.submit(99)),
        }

    async def immediate_scenario() -> dict[str, object]:
        pool = WorkerPool(slow_job, worker_count=2, queue_size=50)
        await pool.start()
        for item in range(20):
            await pool.submit(item)
        await asyncio.sleep(0.01)
        results = await pool.shutdown(immediate=True)
        return {
            "finished": len(results),
            "all_exited": all(worker.done() for worker in pool.workers),
        }

    graceful, immediate = await outcome(graceful_scenario()), await outcome(immediate_scenario())
    run_checks(
        [
            (
                "every queued item processed, errors as names",
                lambda: scenario_field(graceful, "results"),
                {item: "ValueError" if item == 7 else item * 2 for item in range(12)},
            ),
            (
                "3 workers, all exited after shutdown",
                lambda: (
                    scenario_field(graceful, "workers"),
                    scenario_field(graceful, "all_exited"),
                ),
                (3, True),
            ),
            (
                "workers ran concurrently (< 0.1 s, not 0.12 s)",
                lambda: scenario_field(graceful, "seconds") < 0.1,
                True,
            ),
            (
                "submit after shutdown -> RuntimeError",
                lambda: scenario_field(graceful, "late_submit"),
                "raised RuntimeError",
            ),
            (
                "immediate shutdown drops queued items",
                lambda: scenario_field(immediate, "finished") < 20,
                True,
            ),
            (
                "immediate shutdown: workers exited",
                lambda: scenario_field(immediate, "all_exited"),
                True,
            ),
        ]
    )

    recorded_sleeps: list[float] = []

    async def record_sleep(seconds: float) -> None:
        recorded_sleeps.append(round(seconds, 6))

    async def retry_case(
        fail_times: int, error_type: type[Exception] = ConnectionError
    ) -> dict[str, object]:
        RETRY_CALLS.clear()
        recorded_sleeps.clear()
        decorator = retry_async(
            attempts=4,
            base_delay=0.1,
            max_delay=0.25,
            retry_on=(ConnectionError,),
            sleep=record_sleep,
            rng=random.Random(7),
        )
        result = await outcome(decorator(flaky_inventory_call)(fail_times, error_type))
        return {"result": result, "calls": len(RETRY_CALLS), "sleeps": list(recorded_sleeps)}

    expected_rng = random.Random(7)
    expected_delays = [
        round(expected_rng.uniform(0, min(0.25, 0.1 * 2**retry)), 6) for retry in range(3)
    ]
    recovers, gives_up, not_retried = (
        await outcome(retry_case(2)),
        await outcome(retry_case(10)),
        await outcome(retry_case(5, KeyError)),
    )
    run_checks(
        [
            (
                "recovers after 2 failures",
                lambda: (scenario_field(recovers, "result"), scenario_field(recovers, "calls")),
                ("ok after 3 calls", 3),
            ),
            (
                "full-jitter delays from rng",
                lambda: scenario_field(recovers, "sleeps"),
                expected_delays[:2],
            ),
            (
                "gives up after 4 calls, re-raises",
                lambda: (scenario_field(gives_up, "result"), scenario_field(gives_up, "calls")),
                ("raised ConnectionError", 4),
            ),
            (
                "capped delays (3 sleeps)",
                lambda: scenario_field(gives_up, "sleeps"),
                expected_delays,
            ),
            (
                "other errors are not retried",
                lambda: (
                    scenario_field(not_retried, "result"),
                    scenario_field(not_retried, "calls"),
                ),
                ("raised KeyError", 1),
            ),
            (
                "keeps the name",
                lambda: retry_async()(flaky_inventory_call).__name__,
                "flaky_inventory_call",
            ),
        ]
    )

    async def paging_case(
        path: str, page_size: int = 10, stop_after: int | None = None
    ) -> dict[str, object]:
        page_requests.clear()
        collected: list[int] = []
        async with mock_client(paged_api) as paging_client:
            async with contextlib.aclosing(paginate(paging_client, path, page_size)) as items:
                async for item in items:
                    collected.append(item["id"])
                    if stop_after is not None and len(collected) == stop_after:
                        break
        return {
            "ids": collected,
            "requests": len(page_requests),
            "first": page_requests[0] if page_requests else None,
        }

    every_page = await outcome(paging_case("/products"))
    stopped_early = await outcome(paging_case("/products", stop_after=12))
    bigger_pages = await outcome(paging_case("/products", page_size=20))
    empty_listing = await outcome(paging_case("/empty"))
    run_checks(
        [
            ("all 45 items in order", lambda: scenario_field(every_page, "ids"), list(range(45))),
            ("5 requests for 45 items", lambda: scenario_field(every_page, "requests"), 5),
            (
                "first request: limit only, no cursor",
                lambda: scenario_field(every_page, "first"),
                {"limit": "10"},
            ),
            (
                "lazy: stopping after 12 items costs 2 requests",
                lambda: (
                    scenario_field(stopped_early, "ids"),
                    scenario_field(stopped_early, "requests"),
                ),
                (list(range(12)), 2),
            ),
            ("page_size=20 -> 3 requests", lambda: scenario_field(bigger_pages, "requests"), 3),
            (
                "empty endpoint",
                lambda: (
                    scenario_field(empty_listing, "ids"),
                    scenario_field(empty_listing, "requests"),
                ),
                ([], 1),
            ),
        ]
    )

    culprit_a = await outcome(find_blocking_handler(HANDLERS_A))
    culprit_b = await outcome(find_blocking_handler(HANDLERS_B))
    fixed_result = await outcome(render_invoice_fixed())
    fixed_lag = await outcome(loop_lag_during(render_invoice_fixed))
    run_checks(
        [
            ("set A: the blocking handler", lambda: culprit_a, "render_invoice"),
            ("set B: the blocking handler", lambda: culprit_b, "lookup_tax"),
            ("fixed version: same result", lambda: fixed_result, {"file": "invoice-42.pdf"}),
            (
                "fixed version: loop lag under 50 ms",
                lambda: isinstance(fixed_lag, float) and fixed_lag < 0.05,
                True,
            ),
        ]
    )

    async def request_id_scenario() -> dict[str, object]:
        request_records.clear()
        async with make_traced_client(httpx.MockTransport(echo_request_id_api)) as traced_client:
            many = await asyncio.gather(
                *(
                    handle_request(
                        traced_client, f"/orders/{order_number}", f"req-{order_number:02d}"
                    )
                    for order_number in range(20)
                )
            )
            generated = await handle_request(traced_client, "/orders/new")
        return {
            "many": many,
            "generated": generated,
            "caller_sees": REQUEST_ID.get(),
            "records": list(request_records),
        }

    def records_match(scenario: object) -> bool:
        records = scenario_field(scenario, "records")
        tagged = [
            (logged_id, message) for logged_id, message in records if "/orders/new" not in message
        ]
        return len(records) == 42 and all(
            logged_id == f"req-{message.rsplit('/', 1)[1]:0>2}" for logged_id, message in tagged
        )

    traced = await outcome(request_id_scenario())
    run_checks(
        [
            (
                "header carries each request's id",
                lambda: [reply["echoed"] for reply in scenario_field(traced, "many")],
                [f"req-{order_number:02d}" for order_number in range(20)],
            ),
            (
                "worker thread sees the id",
                lambda: all(
                    reply["audit"] == reply["request_id"]
                    for reply in scenario_field(traced, "many")
                ),
                True,
            ),
            ("40 + 2 log lines, each tagged with its own id", lambda: records_match(traced), True),
            (
                "generated id: 8 hex chars, echoed",
                lambda: (
                    len(scenario_field(traced, "generated")["request_id"]),
                    scenario_field(traced, "generated")["echoed"]
                    == scenario_field(traced, "generated")["request_id"],
                ),
                (8, True),
            ),
            ("caller's context restored", lambda: scenario_field(traced, "caller_sees"), "-"),
        ]
    )

    store_ids = list(range(STORE_COUNT))
    failing_stores = sorted(store for store in store_ids if store % 50 == 7 or store % 97 == 3)
    expected_sales = {
        "total": sum(store * 37 % 1000 for store in store_ids if store not in failing_stores),
        "ok": STORE_COUNT - len(failing_stores),
        "failed": failing_stores,
    }
    store_tracker.reset()
    async with mock_client(sales_api) as sales_client:
        with Timer("aggregate_sales", report=None) as aggregate_timer:
            aggregated = await outcome(aggregate_sales(sales_client, store_ids))
    run_checks(
        [
            ("totals, ok count and failed ids", lambda: aggregated, expected_sales),
            ("at most 50 in flight, and concurrent", lambda: 1 < store_tracker.peak <= 50, True),
            (
                "each 503 store retried exactly once",
                lambda: {store_tracker.calls[store] for store in store_ids if store % 40 == 11},
                {2},
            ),
            (
                "hung stores cut off (< 1 s overall)",
                lambda: isinstance(aggregated, dict) and aggregate_timer.elapsed_seconds < 1.0,
                True,
            ),
        ]
    )
    if isinstance(aggregated, dict):
        seconds_taken = aggregate_timer.elapsed_seconds
        print(f"aggregate_sales took {seconds_taken:.2f} s for {STORE_COUNT} endpoints")


def check_lab_5_4() -> None:
    """Run every Lab 5.4 check (each check prints PASS/FAIL)."""
    asyncio.run(_lab_5_4_checks())


# ----- Lab 5.5: setup and given code from the lab cells -----

LAB55_DIR = PHASE5_DIR / "lab55"
LAB55_CITIES = ("Pune", "Delhi", "Kochi", "Patna", "Surat", "Indore")
LAB55_EVENT_TYPES = ("view", "click", "add_to_cart", "purchase")


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
    LAB55_DIR.mkdir(parents=True, exist_ok=True)
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


# ----- Lab 5.5: reference solutions -----


def hottest_function(function: Callable[..., object], *args: object) -> str:
    """Profile function(*args) once; return the name of the entry with the largest tottime."""
    profiler = cProfile.Profile()
    profiler.runcall(function, *args)
    entries = pstats.Stats(
        profiler
    ).stats  # (file, line, name) -> (cc, nc, tottime, cumtime, callers)
    (_file, _line, name), _timings = max(entries.items(), key=lambda entry: entry[1][2])
    return name


def city_totals_fast(
    orders: list[tuple[int, int, int]], customers: list[tuple[int, str, str]]
) -> dict[str, int]:
    """Same result as city_totals_slow, without a scan per order."""
    city_of = {
        customer_id: city for customer_id, _name, city in customers
    }  # built once: O(customers)
    totals: dict[str, int] = {}
    for _order_id, customer_id, amount in orders:
        city = city_of[customer_id]  # O(1) instead of a linear scan
        totals[city] = totals.get(city, 0) + amount
    return dict(sorted(totals.items()))


def count_pairs_linear(amounts: list[int], target: int) -> int:
    """Same result as count_pairs_quadratic, in O(n)."""
    seen: Counter[int] = Counter()
    pair_count = 0
    for amount in amounts:
        pair_count += seen[target - amount]  # every earlier complement makes one pair
        seen[amount] += 1
    return pair_count


def timing_table(
    candidates: dict[str, Callable[[], object]], number: int = 1000, repeat: int = 5
) -> list[tuple[str, float]]:
    """(label, best seconds per call) for every candidate, fastest first."""
    rows = [
        (label, min(timeit.repeat(work, number=number, repeat=repeat)) / number)
        for label, work in candidates.items()
    ]
    return sorted(rows, key=lambda row: row[1])


def render_timing_table(rows: list[tuple[str, float]]) -> str:
    """Markdown table: variant, time per call in µs, ratio to the fastest row."""
    lines = ["| Variant | Time per call | Relative |", "| --- | ---: | ---: |"]
    fastest = rows[0][1] if rows else 1.0
    for label, seconds in rows:
        lines.append(f"| {label} | {seconds * 1e6:,.2f} µs | {seconds / fastest:.2f}x |")
    return "\n".join(lines)


def revenue_by_store_numpy(
    store_ids: np.ndarray, amounts: np.ndarray, store_count: int
) -> np.ndarray:
    """Vectorized revenue_by_store_loop: an int64 array of length store_count."""
    totals = np.zeros(store_count, dtype=np.int64)
    np.add.at(totals, store_ids, amounts)  # integer arithmetic: exact, repeated ids all added
    return totals


def zscores_numpy(values: np.ndarray) -> np.ndarray:
    """Vectorized zscores_loop."""
    return (values - values.mean()) / values.std()  # np.std is the population standard deviation


def peak_memory(function: Callable[..., object], *args: object) -> tuple[object, int]:
    """Call function(*args); return (result, peak traced bytes above the starting level)."""
    started_here = not tracemalloc.is_tracing()
    if started_here:
        tracemalloc.start()
    tracemalloc.reset_peak()
    baseline = tracemalloc.get_traced_memory()[0]
    try:
        result = function(*args)
        peak = tracemalloc.get_traced_memory()[1] - baseline
    finally:
        if started_here:
            tracemalloc.stop()
    return result, peak


def event_summary_lean(path: Path) -> dict[str, object]:
    """Same result as event_summary_eager, streaming the file."""
    events: Counter[str] = Counter()
    total_bytes = 0
    users: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        next(handle)  # header
        for line in handle:
            _timestamp, user_id, event, size = line.rstrip("\n").split(",")
            events[event] += 1
            total_bytes += int(size)
            users.add(user_id)
    return {
        "events": dict(sorted(events.items())),
        "total_bytes": total_bytes,
        "unique_users": len(users),
    }


# ----- Lab 5.5: the notebook's check cells -----


def check_lab_5_5() -> None:
    """Run every Lab 5.5 check (the notebook's check cells; each prints PASS/FAIL)."""
    LAB55_CUSTOMERS, LAB55_ORDERS, LAB55_EVENTS = prepare_lab_5_5()
    print("--- Check exercise 1")
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
    print("--- Check exercise 2")
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
    print("--- Check exercise 3")
    expected_table = (
        "| Variant | Time per call | Relative |\n| --- | ---: | ---: |\n"
        "| join | 12.34 µs | 1.00x |\n| plus | 24.68 µs | 2.00x |"
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
                "| Variant | Time per call | Relative |\n| --- | ---: | ---: |",
            ),
            (
                "render a slow row",
                lambda: render_timing_table([("a", 0.5e-6), ("b", 1.5e-3)]).splitlines()[-1],
                "| b | 1,500.00 µs | 3000.00x |",
            ),
            (
                "sorted fastest first",
                lambda: [
                    label
                    for label, _ in timing_table(
                        {"sleep": lambda: time.sleep(0.002), "noop": lambda: None},
                        number=3,
                        repeat=2,
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
    print("--- Check exercise 4")
    vector_rng = random.Random(60)
    sale_count = 200_000 * DEMO_SCALE
    store_id_list = [
        vector_rng.randrange(45) for _ in range(sale_count)
    ]  # store ids 45..49 never sell
    amount_list = [vector_rng.randrange(100, 900_000) for _ in range(sale_count)]
    value_list = [vector_rng.gauss(500, 120) for _ in range(50_000)]
    store_id_array, amount_array, value_array = (
        np.array(store_id_list),
        np.array(amount_list),
        np.array(value_list),
    )
    expected_revenue = revenue_by_store_loop(store_id_list, amount_list, 50)
    loop_seconds = best_time_or_none(lambda: revenue_by_store_loop(store_id_list, amount_list, 50))
    numpy_seconds = best_time_or_none(
        lambda: revenue_by_store_numpy(store_id_array, amount_array, 50)
    )
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
    print("--- Check exercise 5")

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


if __name__ == "__main__":
    selected = set(sys.argv[1:])
    labs = [
        ("Lab 5.1", check_lab_5_1),
        ("Lab 5.2", check_lab_5_2),
        ("Lab 5.3", check_lab_5_3),
        ("Lab 5.4", check_lab_5_4),
        ("Lab 5.5", check_lab_5_5),
    ]
    for lab_title, check_lab in labs:
        if selected and lab_title not in selected:
            continue
        print(f"===== {lab_title} =====")
        check_lab()
