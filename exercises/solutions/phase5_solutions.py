"""Reference solutions for Phase 5 labs.

Run from the repository root:

    uv run python exercises/solutions/phase5_solutions.py            # every lab
    uv run python exercises/solutions/phase5_solutions.py "Lab 5.2"  # one lab

Each check_lab_5_N() runs the notebook's own check cells, so the notebook and this file test
exactly the same things. Lab 5.2's worker functions must be importable by child processes, so,
like the notebook's %%writefile cells, this file writes them to notebooks/_scratch/phase5/
(git-ignored) and imports them from there. Timings vary by machine; no check asserts a speedup
except the loose "the default build cannot reach 1.5x with threads" sanity check.
"""

import concurrent.futures
import functools
import hashlib
import importlib
import importlib.util
import inspect
import itertools
import json
import math
import multiprocessing
import os
import queue
import random
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from multiprocessing import shared_memory
from pathlib import Path
from types import ModuleType

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
                [n * n for n in range(12)],
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
        download_all(client, [f"http://lab.test/files/{n}" for n in range(url_count)], max_workers)
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
                    [10.0 * n for n in range(10)],
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


if __name__ == "__main__":
    selected = set(sys.argv[1:])
    for lab_title, check_lab in [("Lab 5.1", check_lab_5_1), ("Lab 5.2", check_lab_5_2)]:
        if selected and lab_title not in selected:
            continue
        print(f"===== {lab_title} =====")
        check_lab()
