"""Unit 5.4 — asyncio in Production (with Lab 5.4)."""

from nbformat import NotebookNode
from unit_5_1 import SHOP_API_SOURCE  # one copy of the Unit 4.6 server code

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = r'''
import asyncio
import concurrent.futures
import contextlib
import contextvars
import functools
import gc
import importlib
import importlib.util
import inspect
import io
import itertools
import logging
import os
import platform
import random
import re
import subprocess
import sys
import sysconfig
import textwrap
import threading
import time
import warnings
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Generator, Iterable
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock

import httpx

DEMO_SCALE = int(os.environ.get("PHASE5_DEMO_SCALE", "1"))  # the one knob for workload sizes
REPO_ROOT = find_repo_root()
scratch_dir = REPO_ROOT / "notebooks" / "_scratch"  # git-ignored
PHASE5_DIR = scratch_dir / "phase5"
PHASE5_DIR.mkdir(parents=True, exist_ok=True)
os.chdir(REPO_ROOT / "notebooks")  # %%writefile cells use paths relative to notebooks/
if str(PHASE5_DIR) not in sys.path:
    sys.path.insert(0, str(PHASE5_DIR))  # child processes receive a copy of sys.path
CHILD_ENV = {**os.environ, "PYTHON_COLORS": "0", "PYTHONUNBUFFERED": "1", "PY_COLORS": "0"}
KERNEL_LOOP = asyncio.get_running_loop()


def has_module(name: str) -> bool:
    """True if the module can be imported (checked without importing it)."""
    return importlib.util.find_spec(name) is not None


HAS_UVLOOP = has_module("uvloop") and sys.platform != "win32"  # uvloop does not support Windows
HAS_AIOFILES, HAS_AIOHTTP, HAS_TENACITY = (
    has_module("aiofiles"),
    has_module("aiohttp"),
    has_module("tenacity"),
)
HAS_ANYIO, HAS_TRIO, HAS_PYTEST_ASYNCIO = (
    has_module("anyio"),
    has_module("trio"),
    has_module("pytest_asyncio"),
)


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
    output = re.sub(r"0x[0-9a-f]{6,}", "0x<address>", output)
    return re.sub(r"/[^\s\"']*/lib/python3\.\d+t?/", "<stdlib>/", output)


def fresh_import(module_name: str) -> ModuleType:
    """Import a module saved by a %%writefile cell, always re-reading the file from disk."""
    for cached in (PHASE5_DIR / "__pycache__").glob(f"{module_name}.*.pyc"):
        cached.unlink()
    importlib.invalidate_caches()
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


print(interpreter_label())
print(f"{DEMO_SCALE=}  kernel loop: {type(KERNEL_LOOP).__name__}")
optional = {
    "uvloop": HAS_UVLOOP,
    "aiofiles": HAS_AIOFILES,
    "aiohttp": HAS_AIOHTTP,
    "tenacity": HAS_TENACITY,
    "anyio": HAS_ANYIO,
    "trio": HAS_TRIO,
    "pytest-asyncio": HAS_PYTEST_ASYNCIO,
}
print(
    "optional packages: "
    + ", ".join(f"{name} {'yes' if found else 'no'}" for name, found in optional.items())
)
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 5.4 — asyncio in Production

            **Objectives**

            - Run groups of tasks safely with `TaskGroup`, and handle several failures
              at once with `ExceptionGroup` and `except*`.
            - Put deadlines on work with `asyncio.timeout`, cancel tasks correctly, clean
              up on cancellation, and protect critical steps with `shield`.
            - Coordinate tasks with `Event`, `Lock`, `Condition`, `Semaphore` and
              `Barrier`; build worker pools and pipelines on `asyncio.Queue` with
              backpressure and `Queue.shutdown()`.
            - Write async context managers, iterators and generators, and close them
              deterministically with `aclosing`.
            - Detect a blocked event loop (debug mode, slow-callback warnings, a lag
              monitor) and fix it with threads, processes or async libraries.
            - Carry request-scoped state with `contextvars`; use a shared
              `httpx.AsyncClient` with limits and timeouts; rate-limit and retry with
              backoff and jitter.
            - Test async code with pytest, `AsyncMock` and `httpx.MockTransport`; speed up
              the loop with `uvloop`; bridge threads, anyio and trio.

            **JS bridge**

            | Node.js | asyncio | The difference that bites |
            | --- | --- | --- |
            | `Promise.all` + an `AbortController` you wire up yourself | `asyncio.TaskGroup` | a failure cancels the siblings **automatically** and all errors arrive together in an `ExceptionGroup` |
            | `AbortSignal.timeout(ms)` | `async with asyncio.timeout(seconds):` | cancellation is delivered *into* the coroutine as `CancelledError` |
            | `controller.abort()` | `task.cancel()` | `CancelledError` is a `BaseException`: `except Exception` does not catch it |
            | `p-limit(5)` | `asyncio.Semaphore(5)` | built in |
            | `for await (const x of stream)` | `async for x in stream:` | close early-exited generators with `aclosing` |
            | `await using` / `Symbol.asyncDispose` | `async with` / `__aexit__` | |
            | `AsyncLocalStorage` | `contextvars.ContextVar` | each Task gets a *copy* of the context |
            | `undici.Agent({connections})` | `httpx.AsyncClient(limits=httpx.Limits(...))` | create one client and share it |
            | blocked-loop detectors (`blocked-at`, `--cpu-prof`) | `asyncio` debug mode, `slow_callback_duration` | built in |
            | Jest / Vitest async tests | pytest + anyio plugin (or pytest-asyncio), `AsyncMock` | tests need an event loop: the plugin provides it |

            **How this unit runs.** Cells use top-level `await` on the kernel's loop.
            Demos that need a fresh loop (`asyncio.run(..., debug=True)`, uvloop, anyio's
            `run`) and the pytest run happen in child processes. HTTP demos talk to the
            Unit 4.6 shop API on `127.0.0.1` or to `httpx.MockTransport`, never to the
            internet. Optional packages are detected first; a missing one prints a skip
            message.
            """
        ),
        md(
            """
            Unit setup, part 1: imports, `DEMO_SCALE`, the scratch folder (on `sys.path`
            for the worker module in 5.4.6), feature flags for the optional packages, and
            the error and interpreter helpers.
            """
        ),
        code(UNIT_SETUP_SOURCE),
        md(
            """
            Unit setup, part 2: `Timer`, `run_child()` (as in Unit 5.3) and
            `fresh_import()` (Unit 5.2).
            """
        ),
        code(UNIT_SETUP_SOURCE_2),
        md(
            """
            The local shop API from Unit 4.6 (the same code, started once per kernel) for
            the HTTP demos in 5.4.8–5.4.9. Its `/slow?seconds=` route sleeps on the server,
            `/flaky/<key>?fail=N` fails N times with 503 before succeeding, and
            `/connections` counts the TCP connections it has accepted.
            """
        ),
        code(SHOP_API_SOURCE),
        md("Start it (the first call starts the server; later calls return the same URL):"),
        code(
            """
            SHOP_API = start_shop_api()
            print(f"{SHOP_API=}")
            """
        ),
    ]


def _structured_concurrency_cells() -> list[NotebookNode]:
    """5.4.1 Structured concurrency."""
    return [
        md(
            """
            ### 5.4.1 Structured concurrency

            **Structured concurrency** means a task's children cannot outlive the block
            that started them: when the block exits, every child has finished, and if one
            child fails, its siblings are cancelled and the error is reported. Trio
            introduced the idea ("nurseries"); asyncio adopted it as `TaskGroup` in 3.11.

            `gather` is *not* structured. When one awaitable fails, `gather` raises at
            once, but the others keep running in the background as orphans:
            """
        ),
        code(
            '''
            progress: list[str] = []


            async def job(name: str, seconds: float, fail: bool = False) -> str:
                """Sleep, then succeed or fail; records completion and cancellation."""
                try:
                    await asyncio.sleep(seconds)
                except asyncio.CancelledError:
                    progress.append(f"{name} cancelled")
                    raise
                if fail:
                    raise ValueError(f"{name} failed")
                progress.append(f"{name} finished")
                return name


            try:
                await asyncio.gather(job("report", 0.05), job("invoice", 0.01, fail=True))
            except ValueError as error:
                print(f"gather raised: {error}")
            print(f"right after: {progress}  <- report is still running")
            await asyncio.sleep(0.06)
            print(f"a bit later: {progress}  <- the orphan finished on its own")
            '''
        ),
        md(
            """
            `async with asyncio.TaskGroup() as group:` starts tasks with
            `group.create_task(...)`; the block does not exit until all of them are done.
            Results are read from the task objects afterwards:
            """
        ),
        code(
            """
            progress.clear()
            async with asyncio.TaskGroup() as group:
                report_task = group.create_task(job("report", 0.02))
                invoice_task = group.create_task(job("invoice", 0.01))
            print(f"{report_task.result()=} {invoice_task.result()=}")
            print(progress)
            """
        ),
        md(
            """
            When a child fails, the group cancels the other children, waits for them,
            and raises an **`ExceptionGroup`** holding every error that happened (two
            jobs failed here at the same moment, so both are reported):
            """
        ),
        code(
            """
            progress.clear()
            try:
                async with asyncio.TaskGroup() as group:
                    group.create_task(job("report", 0.05))
                    group.create_task(job("invoice", 0.01, fail=True))
                    group.create_task(job("email", 0.01, fail=True))
            except ExceptionGroup as error:
                print(f"{type(error).__name__}: {error}")
                for sub_error in error.exceptions:
                    print(f"  {sub_error!r}")
            print(progress)
            """
        ),
        md(
            """
            **`ExceptionGroup`** (*new in 3.11*) is an exception that carries several
            exceptions, possibly nested. `split(type)` divides it into matching and
            non-matching groups; `subgroup(predicate)` keeps only what matches:
            """
        ),
        code(
            """
            batch_error = ExceptionGroup(
                "order batch failed",
                [
                    ValueError("bad quantity"),
                    KeyError("sku-9"),
                    ExceptionGroup("payments", [ConnectionError("gateway down")]),
                ],
            )
            print(f"{batch_error}  ->  {len(batch_error.exceptions)} top-level entries")
            value_errors, others = batch_error.split(ValueError)
            print(f"split: {value_errors.exceptions} | rest: {others.exceptions}")
            network = batch_error.subgroup(lambda error: isinstance(error, ConnectionError))
            print(f"subgroup keeps the nesting: {network!r}")
            """
        ),
        md(
            """
            **`except*`** handles each kind of error in a group separately; every clause
            whose type matches runs (unlike plain `except`, where only the first matching
            clause runs). Anything left unhandled is re-raised as a smaller group.
            """
        ),
        code(
            '''
            def handle_batch(error_group: ExceptionGroup) -> None:
                """Route each kind of failure to its own handler."""
                try:
                    raise error_group
                except* ValueError as input_errors:
                    print(f"  fix the input: {[str(error) for error in input_errors.exceptions]}")
                except* LookupError as missing:
                    print(f"  unknown items: {[str(error) for error in missing.exceptions]}")
                except* ConnectionError as network_errors:
                    print(f"  retry later: {[str(error) for error in network_errors.exceptions]}")


            handle_batch(batch_error)
            '''
        ),
        md(
            """
            **`as_completed`** hands back results in *completion* order. Iterated with
            plain `for`, it yields awaitables to await. *New in 3.13:* iterated with
            `async for`, it yields the **original tasks** you passed in, so you can tell
            which one finished:
            """
        ),
        code(
            """
            async def quote(supplier: str, seconds: float) -> str:
                await asyncio.sleep(seconds)
                return f"{supplier}: Rs {round(seconds * 1000)}"


            for next_quote in asyncio.as_completed([quote("A", 0.03), quote("B", 0.01), quote("C", 0.02)]):
                print(f"for:       {await next_quote}")

            if sys.version_info >= (3, 13):
                supplier_tasks = {
                    asyncio.create_task(quote(name, seconds)): name
                    for name, seconds in (("A", 0.03), ("B", 0.01))
                }
                async for finished_task in asyncio.as_completed(supplier_tasks):
                    print(f"async for: task for {supplier_tasks[finished_task]} -> {finished_task.result()}")
            else:
                print("async iteration over as_completed needs Python 3.13+: skipped")
            """
        ),
        md(
            """
            *New in 3.15:* `TaskGroup.cancel()` stops a group early **without** an error,
            for example once the first supplier has answered. The block exits normally
            and the remaining children are cancelled:
            """
        ),
        code(
            """
            found_suppliers: list[str] = []


            async def search_supplier(group: asyncio.TaskGroup, supplier: str, seconds: float) -> None:
                await asyncio.sleep(seconds)
                found_suppliers.append(supplier)
                group.cancel()  # enough: stop the whole search


            if hasattr(asyncio.TaskGroup, "cancel"):
                progress.clear()
                async with asyncio.TaskGroup() as search_group:
                    for supplier, seconds in (("A", 0.03), ("B", 0.01), ("C", 0.5)):
                        search_group.create_task(search_supplier(search_group, supplier, seconds))
                print(f"block exited normally; found {found_suppliers}")
            else:
                print("TaskGroup.cancel() needs Python 3.15+: skipped")
            """
        ),
        md(
            """
            **Under the hood.** The cancellation logic is short enough to read.
            `_on_task_done` notices a failed child and calls `_abort`, which cancels
            every child that is still running:
            """
        ),
        code(
            """
            abort_source = inspect.getsource(asyncio.TaskGroup._abort)
            print(textwrap.dedent(abort_source).strip())
            print(f"\\n{sys.getsizeof(asyncio.TaskGroup())} bytes for an empty TaskGroup (shallow)")
            """
        ),
    ]


def _timeout_cells() -> list[NotebookNode]:
    """5.4.2 Timeouts and cancellation."""
    return [
        md(
            """
            ### 5.4.2 Timeouts and cancellation

            `async with asyncio.timeout(seconds):` (*new in 3.11*) puts a deadline on a
            whole block. When it expires, the task is cancelled; the context manager turns
            that cancellation into `TimeoutError` at the `async with`. `expired()` tells
            whether it fired; `reschedule()` moves the deadline; `timeout(None)` starts
            without one.
            """
        ),
        code(
            """
            try:
                async with asyncio.timeout(0.05) as deadline:
                    await asyncio.sleep(1)
            except TimeoutError:
                print(f"timed out; {deadline.expired()=}")

            async with asyncio.timeout(None) as deadline:  # no deadline yet
                deadline.reschedule(KERNEL_LOOP.time() + 0.5)  # decided later
                await asyncio.sleep(0.01)
            print(f"finished in time; {deadline.expired()=}")
            """
        ),
        md(
            """
            `asyncio.timeout_at(when)` takes an absolute loop time: one **overall
            deadline** for several steps, which per-call timeouts cannot express:
            """
        ),
        code(
            """
            steps_done: list[int] = []
            overall_deadline = KERNEL_LOOP.time() + 0.1
            try:
                async with asyncio.timeout_at(overall_deadline):
                    for step in range(5):
                        await asyncio.sleep(0.03)  # each step alone would be fine
                        steps_done.append(step)
            except TimeoutError:
                print(f"overall deadline hit after steps {steps_done}")
            """
        ),
        md(
            """
            **`CancelledError` semantics.** `task.cancel(msg)` schedules a
            `CancelledError` to be thrown into the coroutine at its current `await`.
            Since 3.8 it is a `BaseException`, so `except Exception` does **not** catch
            it; cleanup in `finally` still runs. Cancelling a finished task does nothing
            and returns `False`.
            """
        ),
        code(
            """
            print(f"{asyncio.CancelledError.__mro__[1].__name__=}")


            async def careful_worker() -> None:
                try:
                    await asyncio.sleep(1)
                except Exception:
                    print("  never printed: CancelledError is not an Exception")
                finally:
                    print("  finally runs on cancellation")


            worker_task = asyncio.create_task(careful_worker())
            await asyncio.sleep(0)
            print(f"{worker_task.cancel('shutting down')=}")
            try:
                await worker_task
            except asyncio.CancelledError as error:
                print(f"CancelledError: {error}; {worker_task.cancelled()=}")
            print(f"cancel a finished task: {worker_task.cancel()=}")
            """
        ),
        md(
            """
            > **Warning:** never swallow `CancelledError`. If a coroutine catches it and
            > carries on, `cancel()` silently fails: the task finishes normally, and
            > `asyncio.timeout` and `TaskGroup` (which count pending cancellations with
            > `cancelling()` / `uncancel()`) stop working. Clean up, then re-raise.
            """
        ),
        code(
            """
            async def stubborn_worker() -> str:
                try:
                    await asyncio.sleep(1)
                except asyncio.CancelledError:
                    return "ignored the cancel"  # BUG
                return "finished"


            stubborn_task = asyncio.create_task(stubborn_worker())
            await asyncio.sleep(0)
            stubborn_task.cancel()
            print(f"{await stubborn_task=}  {stubborn_task.cancelled()=}  {stubborn_task.cancelling()=}")
            """
        ),
        md(
            """
            **Cleanup.** A cancelled coroutine may still `await` during its cleanup (roll
            back, close a connection), as long as it re-raises afterwards:
            """
        ),
        code(
            """
            cleanup_log: list[str] = []


            async def upload_report() -> None:
                try:
                    cleanup_log.append("upload: started")
                    await asyncio.sleep(1)
                except asyncio.CancelledError:
                    cleanup_log.append("upload: cancelled, rolling back")
                    await asyncio.sleep(0.01)  # async cleanup is allowed
                    raise
                finally:
                    cleanup_log.append("upload: connection closed")


            upload_task = asyncio.create_task(upload_report())
            await asyncio.sleep(0.02)
            upload_task.cancel()
            await asyncio.gather(upload_task, return_exceptions=True)
            print(cleanup_log)
            """
        ),
        md(
            """
            **`shield`.** `asyncio.shield(task)` protects an operation from the
            *caller's* cancellation: the caller stops waiting, but the shielded task keeps
            running. Use it for steps that must not be interrupted halfway (committing a
            payment). Keep a reference to the inner task, or it may be collected.
            """
        ),
        code(
            """
            payment_log: list[str] = []


            async def charge_card() -> str:
                await asyncio.sleep(0.05)
                payment_log.append("charge: committed")
                return "TXN-81"


            async def checkout() -> str:
                charge_task = asyncio.create_task(charge_card())
                try:
                    async with asyncio.timeout(0.01):
                        return await asyncio.shield(charge_task)
                except TimeoutError:
                    payment_log.append("checkout: stopped waiting; the charge continues")
                    return await charge_task  # here we choose to wait for it after all


            print(f"{await checkout()=}")
            print(payment_log)
            """
        ),
    ]


def _coordination_cells() -> list[NotebookNode]:
    """5.4.3 Coordination."""
    return [
        md(
            """
            ### 5.4.3 Coordination

            asyncio has the same primitives as `threading` (Unit 5.1.5), but for tasks on
            one loop. They are **not thread-safe**, and waiting on them is an `await`.

            | Primitive | Use it to |
            | --- | --- |
            | `Event` | let many tasks wait until something happens (`set()` wakes all) |
            | `Lock` | make a read-`await`-write sequence atomic |
            | `Condition` | wait until a predicate on shared state becomes true |
            | `Semaphore` / `BoundedSemaphore` | allow at most N tasks into a section |
            | `Barrier` (*new in 3.11*) | make N tasks wait for each other before continuing |

            **`Event`:** customers wait until the store opens.
            """
        ),
        code(
            """
            store_open = asyncio.Event()
            arrivals: list[str] = []


            async def customer(name: str) -> None:
                await store_open.wait()
                arrivals.append(name)


            customers = [asyncio.create_task(customer(name)) for name in ("asha", "ben", "chen")]
            await asyncio.sleep(0.01)
            print(f"before set(): {arrivals} {store_open.is_set()=}")
            store_open.set()
            await asyncio.gather(*customers)
            print(f"after set():  {arrivals}")
            """
        ),
        md(
            """
            **`Lock`.** Between awaits a task cannot be interrupted, so `balance += 10`
            needs no lock. But a read, then an `await`, then a write is a race: every task
            reads the old balance before anyone writes. A `Lock` makes the sequence
            atomic:
            """
        ),
        code(
            """
            class Wallet:
                def __init__(self) -> None:
                    self.balance = 0


            async def deposit(wallet: Wallet, amount: int, lock: asyncio.Lock | None = None) -> None:
                async def read_then_write() -> None:
                    current = wallet.balance
                    await asyncio.sleep(0)  # e.g. a database round trip
                    wallet.balance = current + amount

                if lock is None:
                    await read_then_write()
                else:
                    async with lock:
                        await read_then_write()


            for label, lock in (("no lock", None), ("with Lock", asyncio.Lock())):
                wallet = Wallet()
                await asyncio.gather(*(deposit(wallet, 10, lock) for _ in range(100)))
                print(f"{label:<9}: balance {wallet.balance} (expected 1000)")
            """
        ),
        md(
            """
            **`Condition`:** buyers wait until there is enough stock;
            `wait_for(predicate)` re-checks after every `notify_all()`.
            """
        ),
        code(
            """
            stock = {"chai": 0}
            stock_changed = asyncio.Condition()
            served: list[str] = []


            async def buyer(name: str, quantity: int) -> None:
                async with stock_changed:
                    await stock_changed.wait_for(lambda: stock["chai"] >= quantity)
                    stock["chai"] -= quantity
                    served.append(f"{name} got {quantity}")


            async def restock(amount: int) -> None:
                async with stock_changed:
                    stock["chai"] += amount
                    stock_changed.notify_all()


            buyers = [asyncio.create_task(buyer("asha", 2)), asyncio.create_task(buyer("ben", 3))]
            for amount in (2, 3):
                await asyncio.sleep(0.01)
                await restock(amount)
                await asyncio.sleep(0.01)
                print(f"after restocking {amount}: served={served} left={stock['chai']}")
            await asyncio.wait(buyers)
            print(f"all buyers done: {all(buyer_task.done() for buyer_task in buyers)}")
            """
        ),
        md(
            """
            **`Semaphore`:** at most three calls to a payment gateway at once.
            `BoundedSemaphore` also catches a `release()` without a matching `acquire()`:
            """
        ),
        code(
            """
            gateway_slots = asyncio.Semaphore(3)
            gateway_load = {"now": 0, "peak": 0}


            async def call_gateway(payment_id: int) -> int:
                async with gateway_slots:
                    gateway_load["now"] += 1
                    gateway_load["peak"] = max(gateway_load["peak"], gateway_load["now"])
                    await asyncio.sleep(0.01)
                    gateway_load["now"] -= 1
                return payment_id


            with Timer("10 payments, 3 at a time"):
                await asyncio.gather(*(call_gateway(payment_id) for payment_id in range(10)))
            print(f"peak concurrent calls: {gateway_load['peak']}")
            print(f"extra release on BoundedSemaphore -> {raised_message(asyncio.BoundedSemaphore(1).release)}")
            """
        ),
        md(
            """
            **`Barrier`:** three delivery riders get ready at different speeds; nobody
            leaves until all three are ready. `wait()` returns each task's arrival index.
            """
        ),
        code(
            """
            all_ready = asyncio.Barrier(3)
            rider_log: list[str] = []


            async def rider(name: str, preparation_seconds: float) -> None:
                await asyncio.sleep(preparation_seconds)
                rider_log.append(f"{name} ready")
                arrival_index = await all_ready.wait()
                rider_log.append(f"{name} leaves (arrived #{arrival_index})")


            await asyncio.gather(rider("asha", 0.03), rider("ben", 0.01), rider("chen", 0.02))
            print("\\n".join(rider_log))
            print(f"{all_ready.parties=} {all_ready.n_waiting=} {all_ready.broken=}")
            """
        ),
    ]


def _queue_cells() -> list[NotebookNode]:
    """5.4.4 Queues and worker pools."""
    return [
        md(
            """
            ### 5.4.4 Queues and worker pools

            `asyncio.Queue` hands items from producer tasks to consumer tasks. `await
            queue.put(item)` waits while the queue is full (if it has a `maxsize`);
            `await queue.get()` waits while it is empty. Three orderings, plus the
            non-waiting forms and their errors:
            """
        ),
        code(
            """
            for queue_class in (asyncio.Queue, asyncio.LifoQueue, asyncio.PriorityQueue):
                demo_queue = queue_class()
                for item in (3, 1, 2):
                    demo_queue.put_nowait(item)
                drained_order = [demo_queue.get_nowait() for _ in range(demo_queue.qsize())]
                print(f"{queue_class.__name__:<14} -> {drained_order}")
            print(f"get_nowait() on an empty queue -> {raised_error_name(asyncio.Queue().get_nowait)}")
            full_queue = asyncio.Queue(maxsize=1)
            full_queue.put_nowait("only")
            print(
                f"put_nowait() on a full queue  -> {raised_error_name(lambda: full_queue.put_nowait('more'))}"
            )
            """
        ),
        md(
            """
            **A worker pool**, the classic pattern: N worker tasks loop on `get()`; each
            calls `task_done()` when an item is finished; `await queue.join()` waits until
            every item put so far is done. Before 3.13 the workers were then stopped by
            cancelling them:
            """
        ),
        code(
            '''
            async def packer(name: str, orders: asyncio.Queue[str], packed: list[str]) -> None:
                """Take orders forever; the pool cancels the packers when the queue is drained."""
                while True:
                    order = await orders.get()
                    try:
                        await asyncio.sleep(0.01)  # pack it
                        packed.append(f"{order} by {name}")
                    finally:
                        orders.task_done()


            orders: asyncio.Queue[str] = asyncio.Queue()
            for order_number in range(9):
                orders.put_nowait(f"order-{order_number}")
            packed_orders: list[str] = []
            packers = [
                asyncio.create_task(packer(f"packer-{number}", orders, packed_orders)) for number in range(3)
            ]
            with Timer("9 orders x 10 ms with 3 packers"):
                await orders.join()
            for packer_task in packers:
                packer_task.cancel()
            await asyncio.gather(*packers, return_exceptions=True)
            print(f"{len(packed_orders)} packed, e.g. {packed_orders[:3]}")
            '''
        ),
        md(
            """
            **Backpressure.** An unbounded queue lets a fast producer pile up items in
            memory. With `maxsize=2` the producer's `put()` waits until the slow consumer
            makes room, so it can never get more than two items ahead:
            """
        ),
        code(
            """
            bounded_queue: asyncio.Queue[int] = asyncio.Queue(maxsize=2)
            flow_log: list[str] = []


            async def fast_producer() -> None:
                for item in range(5):
                    await bounded_queue.put(item)
                    flow_log.append(f"put {item} (queue size {bounded_queue.qsize()})")


            async def slow_consumer() -> None:
                for _ in range(5):
                    await asyncio.sleep(0.02)
                    flow_log.append(f"        got {await bounded_queue.get()}")


            await asyncio.gather(fast_producer(), slow_consumer())
            print("\\n".join(flow_log))
            """
        ),
        md(
            """
            **`Queue.shutdown()`** (*new in 3.13*) replaces the cancel-the-workers dance.
            After `shutdown()`, `put()` raises `QueueShutDown`; consumers still receive
            the items already queued, and once the queue is empty their `get()` raises
            `QueueShutDown`, which is their signal to exit. `shutdown(immediate=True)`
            also drops the items still waiting.
            """
        ),
        code(
            """
            async def shutdown_aware_worker(name: str, jobs: asyncio.Queue[str], report: list[str]) -> None:
                while True:
                    try:
                        job = await jobs.get()
                    except asyncio.QueueShutDown:
                        report.append(f"{name} exits")
                        return
                    await asyncio.sleep(0.01)
                    report.append(f"{name} did {job}")
                    jobs.task_done()


            if hasattr(asyncio.Queue, "shutdown"):
                jobs: asyncio.Queue[str] = asyncio.Queue()
                for job in ("a", "b", "c"):
                    jobs.put_nowait(job)
                jobs.shutdown()  # graceful: no new items, drain the rest
                print(f"put after shutdown -> {raised_error_name(lambda: jobs.put_nowait('d'))}")
                shutdown_report: list[str] = []
                await asyncio.gather(
                    *(shutdown_aware_worker(name, jobs, shutdown_report) for name in ("w1", "w2"))
                )
                print(shutdown_report)
                dropped: asyncio.Queue[str] = asyncio.Queue()
                for job in ("x", "y"):
                    dropped.put_nowait(job)
                dropped.shutdown(immediate=True)
                print(f"immediate: {dropped.qsize()=}, get -> {raised_error_name(dropped.get_nowait)}")
            else:
                print("Queue.shutdown() needs Python 3.13+: skipped")
            """
        ),
        md(
            """
            **Pipelines.** Stages connected by bounded queues: each stage reads from its
            inbox and writes to its outbox, and shutdown flows downstream. When `read`
            finishes it shuts down `raw`; `parse` drains `raw`, gets `QueueShutDown`, and
            shuts down `parsed`; `total` drains `parsed` and returns. (With several
            workers per stage, shut the outbox down only after *all* of them finished.)
            """
        ),
        code(
            """
            SALES_LINES = ["chai,2", "vada,1", "chai,3", "idli,4", "vada,2", "chai,1"]


            async def read_stage(lines: list[str], outbox: asyncio.Queue[str]) -> None:
                for line in lines:
                    await outbox.put(line)
                outbox.shutdown()


            async def parse_stage(inbox: asyncio.Queue[str], outbox: asyncio.Queue[tuple[str, int]]) -> None:
                try:
                    while True:
                        sku, quantity = (await inbox.get()).split(",")
                        await outbox.put((sku, int(quantity)))
                except asyncio.QueueShutDown:
                    outbox.shutdown()


            async def total_stage(inbox: asyncio.Queue[tuple[str, int]]) -> Counter[str]:
                totals: Counter[str] = Counter()
                try:
                    while True:
                        sku, quantity = await inbox.get()
                        totals[sku] += quantity
                except asyncio.QueueShutDown:
                    return totals


            raw_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=2)
            parsed_queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue(maxsize=2)
            _, _, sales_totals = await asyncio.gather(
                read_stage(SALES_LINES, raw_queue),
                parse_stage(raw_queue, parsed_queue),
                total_stage(parsed_queue),
            )
            print(dict(sales_totals))
            """
        ),
    ]


def _async_protocol_cells() -> list[NotebookNode]:
    """5.4.5 Async protocols."""
    return [
        md(
            """
            ### 5.4.5 Async protocols

            Every synchronous protocol from Units 1.13–1.14 has an async twin whose
            methods are coroutines:

            | Sync | Async | Methods |
            | --- | --- | --- |
            | `with` | `async with` | `__aenter__`, `__aexit__` |
            | `@contextmanager` | `@asynccontextmanager` | an async generator with one `yield` |
            | `for` | `async for` | `__aiter__` (plain method), `__anext__` (raises `StopAsyncIteration`) |
            | generator | async generator | `async def` + `yield` |
            | `closing()` | `aclosing()` | calls `aclose()` |
            | `ExitStack` | `AsyncExitStack` | |

            **`async with`:** connecting and disconnecting can both await. `__aexit__`
            sees the exception (if any) and returns `False` to let it propagate.
            """
        ),
        code(
            '''
            class FakeDatabase:
                """An async context manager: connect on entry, disconnect on exit."""

                def __init__(self, log: list[str]) -> None:
                    self.log = log

                async def __aenter__(self) -> FakeDatabase:
                    await asyncio.sleep(0)  # the network handshake
                    self.log.append("connect")
                    return self

                async def __aexit__(
                    self, error_type: type[BaseException] | None, error: object, traceback: object
                ) -> bool:
                    await asyncio.sleep(0)
                    self.log.append(f"disconnect (error: {error_type.__name__ if error_type else None})")
                    return False  # do not swallow exceptions

                async def count_orders(self) -> int:
                    self.log.append("query")
                    return 3


            database_log: list[str] = []
            async with FakeDatabase(database_log) as database:
                print(f"{await database.count_orders()=}")
            print(database_log)
            '''
        ),
        md(
            """
            **`@asynccontextmanager`** writes the same thing as an async generator: code
            before `yield` is the entry, code after it the exit. A transaction that
            commits on success and rolls back on error:
            """
        ),
        code(
            """
            @contextlib.asynccontextmanager
            async def transaction(log: list[str]) -> AsyncIterator[str]:
                await asyncio.sleep(0)
                log.append("BEGIN")
                try:
                    yield "txn-1"
                except Exception:
                    log.append("ROLLBACK")
                    raise
                else:
                    log.append("COMMIT")


            transaction_log: list[str] = []
            async with transaction(transaction_log) as transaction_id:
                transaction_log.append(f"insert in {transaction_id}")
            try:
                async with transaction(transaction_log):
                    raise ValueError("duplicate order id")
            except ValueError as error:
                transaction_log.append(f"caught {error!r}")
            print(transaction_log)
            """
        ),
        md(
            """
            **`async for`** with a hand-written async iterator: `__aiter__` returns the
            iterator (it is *not* a coroutine), `__anext__` is a coroutine that raises
            `StopAsyncIteration` at the end:
            """
        ),
        code(
            '''
            class OrderFeed:
                """Async iterator over order ids, fetching each one with an await."""

                def __init__(self, order_ids: Iterable[str]) -> None:
                    self._order_ids = iter(order_ids)

                def __aiter__(self) -> OrderFeed:
                    return self

                async def __anext__(self) -> str:
                    try:
                        order_id = next(self._order_ids)
                    except StopIteration:
                        raise StopAsyncIteration from None
                    await asyncio.sleep(0.001)  # fetch the order
                    return order_id


            async for order_id in OrderFeed(["A-1", "A-2", "A-3"]):
                print(f"processing {order_id}")
            '''
        ),
        md(
            """
            **Async generators** are far shorter: `async def` with `yield`. They work with
            `async for` and in async comprehensions (`[x async for x in gen]`):
            """
        ),
        code(
            '''
            async def price_ticks(sku: str, count: int) -> AsyncIterator[tuple[str, float]]:
                """Stream simulated price updates."""
                price = 20.0
                for _ in range(count):
                    await asyncio.sleep(0.001)
                    price = round(price * 1.05, 2)
                    yield sku, price


            ticks = [price async for _, price in price_ticks("chai", 4)]
            print(f"{ticks=}")
            print(f"{type(price_ticks('chai', 1)).__name__}, {inspect.isasyncgenfunction(price_ticks)=}")
            '''
        ),
        md(
            """
            **`aclosing`.** If you `break` out of an `async for`, the generator is left
            suspended. Its `finally` cannot run synchronously (it might need to await), so
            asyncio's finalizer hook schedules `aclose()` for later, *after* your code has
            moved on (at the latest, `asyncio.run` closes leftover generators at
            shutdown). `contextlib.aclosing(gen)` closes it right at the end of the block:
            """
        ),
        code(
            """
            closing_log: list[str] = []


            async def stream_rows() -> AsyncIterator[int]:
                try:
                    for row in range(1000):
                        await asyncio.sleep(0)
                        yield row
                finally:
                    closing_log.append("  stream_rows: cursor closed")


            async for row in stream_rows():
                if row == 2:
                    break
            closing_log.append("plain async for: loop exited")
            await asyncio.sleep(0.01)
            async with contextlib.aclosing(stream_rows()) as rows:
                async for row in rows:
                    if row == 2:
                        break
            closing_log.append("aclosing: block exited")
            print("\\n".join(closing_log))
            """
        ),
    ]


ASYNC_WORKERS = '''
%%writefile _scratch/phase5/p5_async_workers.py
"""CPU-bound worker for Unit 5.4.6 (process pools need importable functions)."""


def count_primes(limit: int) -> int:
    """Count primes below limit with trial division: pure Python, holds the GIL."""
    count = 0
    for candidate in range(2, limit):
        if all(candidate % divisor for divisor in range(2, int(candidate**0.5) + 1)):
            count += 1
    return count
'''


def _blocking_cells() -> list[NotebookNode]:
    """5.4.6 Blocking the loop."""
    return [
        md(
            """
            ### 5.4.6 Blocking the loop

            Any call that does not `await` and takes a while (`time.sleep`, `requests.get`,
            a big JSON parse, a CPU-heavy loop, a synchronous database driver) freezes
            the **whole** loop: no other request makes progress, timers fire late, and
            timeouts stop working. Three ways to spot it:

            1. **A lag monitor:** a task that sleeps 10 ms in a loop and measures how late
               it wakes up.
            2. **Debug mode** (`asyncio.run(main(), debug=True)`, `PYTHONASYNCIODEBUG=1`,
               `python -X dev`, or `loop.set_debug(True)`): the loop logs every callback
               or task step that runs longer than `loop.slow_callback_duration` (0.1 s by
               default), and reports where never-awaited coroutines were created.
            3. **A profiler** such as py-spy (Unit 5.5).

            The lag monitor first. A handler that calls `time.sleep(0.2)` directly delays
            the heartbeat by about 200 ms; the same call through `asyncio.to_thread`
            barely delays it:
            """
        ),
        code(
            '''
            async def heartbeat(stop: asyncio.Event, interval: float = 0.01) -> float:
                """Sleep in a loop; return the worst lateness (seconds) seen while running."""
                worst = 0.0
                while not stop.is_set():
                    before = KERNEL_LOOP.time()
                    await asyncio.sleep(interval)
                    worst = max(worst, KERNEL_LOOP.time() - before - interval)
                return worst


            async def worst_lag_during(work: Callable[[], Awaitable[object]]) -> float:
                """Run work() while a heartbeat runs; return the heartbeat's worst lag."""
                stop = asyncio.Event()
                monitor = asyncio.create_task(heartbeat(stop))
                await asyncio.sleep(0.02)  # let the heartbeat settle
                await work()
                stop.set()
                return await monitor


            def render_invoice_pdf() -> str:
                time.sleep(0.2)  # a blocking library call
                return "invoice.pdf"


            async def invoice_handler_blocking() -> str:
                return render_invoice_pdf()


            async def invoice_handler_threaded() -> str:
                return await asyncio.to_thread(render_invoice_pdf)


            for handler in (invoice_handler_blocking, invoice_handler_threaded):
                print(f"{handler.__name__:<25} worst loop lag {await worst_lag_during(handler) * 1000:5.0f} ms")
            '''
        ),
        md(
            """
            **Debug mode in a script.** `asyncio.run(main(), debug=True)` with a
            threshold of 50 ms. The loop names the slow task step and its duration; it
            also shows where a never-awaited coroutine was created:
            """
        ),
        code(
            '''
            print(
                run_child(
                    """
                    import asyncio
                    import time


                    async def render_invoice():
                        time.sleep(0.15)  # blocks the loop
                        await asyncio.sleep(0)


                    async def send_email():
                        await asyncio.sleep(0)


                    async def main():
                        asyncio.get_running_loop().slow_callback_duration = 0.05
                        send_email()  # BUG: never awaited
                        await asyncio.gather(render_invoice(), asyncio.sleep(0.01))


                    asyncio.run(main(), debug=True)
                    """
                )
            )
            '''
        ),
        md(
            """
            **Debug mode on a running loop.** The kernel's loop can be switched to debug
            mode for a moment. The helper below does that, lowers the threshold, and
            collects the `asyncio` logger's warnings in a list instead of printing them.
            The kernel's own tasks may show up too, so the cell keeps only messages
            about our task, parsed into name, coroutine and duration:
            """
        ),
        code(
            '''
            class ListHandler(logging.Handler):
                """A logging handler that keeps formatted messages in a list."""

                def __init__(self, messages: list[str]) -> None:
                    super().__init__()
                    self.messages = messages

                def emit(self, record: logging.LogRecord) -> None:
                    self.messages.append(record.getMessage())


            @contextlib.contextmanager
            def slow_callback_report(threshold: float = 0.05) -> Generator[list[str]]:
                """Temporarily enable debug mode on the kernel loop; yield the slow-step messages."""
                messages: list[str] = []
                asyncio_logger = logging.getLogger("asyncio")
                handler = ListHandler(messages)
                saved = (KERNEL_LOOP.get_debug(), KERNEL_LOOP.slow_callback_duration, asyncio_logger.propagate)
                KERNEL_LOOP.set_debug(True)
                KERNEL_LOOP.slow_callback_duration = threshold
                asyncio_logger.addHandler(handler)
                asyncio_logger.propagate = False
                try:
                    yield messages
                finally:
                    asyncio_logger.removeHandler(handler)
                    KERNEL_LOOP.set_debug(saved[0])
                    KERNEL_LOOP.slow_callback_duration, asyncio_logger.propagate = saved[1], saved[2]
            '''
        ),
        md("Run the blocking handler and the threaded one under it, as named tasks:"),
        code(
            """
            SLOW_STEP = re.compile(
                r"name='(?P<task>[^']+)' coro=<(?P<coro>\\w+)\\(\\).*took (?P<seconds>[\\d.]+) seconds"
            )
            with slow_callback_report(threshold=0.05) as slow_steps:
                await asyncio.create_task(invoice_handler_blocking(), name="render-invoice")
                await asyncio.create_task(invoice_handler_threaded(), name="render-invoice-threaded")
            for message in slow_steps:
                if (match := SLOW_STEP.search(message)) and match["task"].startswith("render-invoice"):
                    print(f"slow step: task {match['task']} ({match['coro']}) took {match['seconds']} s")
            threshold = KERNEL_LOOP.slow_callback_duration
            print(f"debug mode restored to {KERNEL_LOOP.get_debug()}, threshold {threshold} s")
            """
        ),
        md(
            """
            **Fixes.** Which tool depends on *why* the call blocks:

            | Blocking because | Fix | Why |
            | --- | --- | --- |
            | it waits on I/O in a sync library | `await asyncio.to_thread(func, *args)` | the thread waits; the loop stays free (the GIL is released while waiting) |
            | it waits on I/O and an async library exists | use the async library (`httpx.AsyncClient`, `asyncpg`, `aiofiles`, `asyncio.create_subprocess_exec`) | no thread per call |
            | it computes in pure Python | `await loop.run_in_executor(process_pool, func, *args)` | a thread would still hold the GIL and slow the loop (Unit 5.1); a process runs truly in parallel |
            | it computes in C that releases the GIL (`hashlib`, NumPy, zlib) | `to_thread` | threads run in parallel |

            `to_thread(func, *args)` is `loop.run_in_executor(None, functools.partial(...))`
            on the default thread pool, plus copying `contextvars` (5.4.7). For CPU-bound
            Python, the worker function must be importable by child processes (Unit 5.2),
            so it lives in a `%%writefile` module:
            """
        ),
        code(ASYNC_WORKERS),
        md(
            """
            Counting primes below 120 000 three ways: directly in the coroutine (the
            loop is frozen for the whole computation), in the default thread pool (the
            thread competes with the loop for the GIL), and in a process pool (the loop is
            untouched). Timings and lags vary by machine; compare the columns:
            """
        ),
        code(
            """
            async_workers = fresh_import("p5_async_workers")
            prime_limit = 120_000 * DEMO_SCALE


            async def primes_directly() -> int:
                return async_workers.count_primes(prime_limit)


            async def primes_in_thread() -> int:
                return await asyncio.to_thread(async_workers.count_primes, prime_limit)


            with concurrent.futures.ProcessPoolExecutor(max_workers=1) as process_pool:
                await KERNEL_LOOP.run_in_executor(
                    process_pool, async_workers.count_primes, 10
                )  # warm up the worker

                async def primes_in_process() -> int:
                    return await KERNEL_LOOP.run_in_executor(
                        process_pool, async_workers.count_primes, prime_limit
                    )

                for strategy in (primes_directly, primes_in_thread, primes_in_process):
                    with Timer(strategy.__name__, report=None) as strategy_timer:
                        lag = await worst_lag_during(strategy)
                    seconds_taken = strategy_timer.elapsed_seconds
                    print(f"{strategy.__name__:<18} took {seconds_taken:.2f} s, worst lag {lag * 1000:6.0f} ms")
            """
        ),
        md(
            """
            **Async libraries.** Asyncio itself has no asynchronous file API (neither does
            the OS, portably). `aiofiles` gives `async with aiofiles.open(...)` and
            `await file.read()`, implemented by running each call in the loop's default
            thread pool, which is what libuv does for `fs` in Node:
            """
        ),
        code(
            """
            if HAS_AIOFILES:
                import aiofiles

                report_path = PHASE5_DIR / "async_report.txt"
                async with aiofiles.open(report_path, "w", encoding="utf-8") as report_file:
                    await report_file.write("chai,5\\nvada,3\\n")
                async with aiofiles.open(report_path, encoding="utf-8") as report_file:
                    print(f"read back with aiofiles: {(await report_file.read()).splitlines()}")
            else:
                print("aiofiles is not installed: skipping (uv add aiofiles)")
            """
        ),
        md(
            """
            Subprocesses have a native async API, `asyncio.create_subprocess_exec`, built
            on the selector (pipes are file descriptors too); several can run at once
            without threads:
            """
        ),
        code(
            """
            async def run_python(snippet: str) -> str:
                process = await asyncio.create_subprocess_exec(
                    sys.executable, "-c", snippet, stdout=asyncio.subprocess.PIPE, env=CHILD_ENV
                )
                stdout, _ = await process.communicate()
                return f"exit {process.returncode}: {stdout.decode().strip()}"


            with Timer("three child interpreters started concurrently"):
                outputs = await asyncio.gather(
                    *(run_python(f"import time; time.sleep(0.2); print({n} * {n})") for n in (2, 3, 4))
                )
            print(outputs)
            """
        ),
    ]


def _contextvar_cells() -> list[NotebookNode]:
    """5.4.7 contextvars."""
    return [
        md(
            """
            ### 5.4.7 `contextvars`

            A global variable is shared by every concurrent request, and a thread-local
            does not help when one thread runs a thousand tasks. A
            **`contextvars.ContextVar`** holds a value per *context*, and asyncio gives
            every Task its own copy of the context, taken when the task is created.
            Node's equivalent is `AsyncLocalStorage`.

            | API | Meaning |
            | --- | --- |
            | `var = ContextVar("name", default=...)` | create once, at module level |
            | `var.get()` | the value in the current context (or the default) |
            | `token = var.set(value)` / `var.reset(token)` | set, then restore the previous value |
            | `with var.set(value):` | the same as set + reset (*new in 3.14*: `Token` is a context manager) |
            | `contextvars.copy_context()`, `ctx.run(func)` | snapshot the context; run a function inside a snapshot |
            """
        ),
        code(
            """
            tenant = contextvars.ContextVar("tenant", default="public")
            print(f"default: {tenant.get()}")
            token = tenant.set("acme")
            print(f"after set: {tenant.get()}")
            tenant.reset(token)
            print(f"after reset: {tenant.get()}")
            if sys.version_info >= (3, 14):
                with tenant.set("globex"):
                    print(f"inside with: {tenant.get()}")
                print(f"after with: {tenant.get()}")
            token = tenant.set("initech")
            snapshot = contextvars.copy_context()  # remembers tenant = "initech"
            tenant.reset(token)
            print(f"now: {tenant.get()}; inside the snapshot: {snapshot.run(tenant.get)}")
            """
        ),
        md(
            """
            **Each task works on a copy.** A child task sees what its parent had set when
            the child was created; a value the child sets never leaks back to the parent,
            and two concurrent requests never see each other's values. (`gather` wraps
            each coroutine in its own task, so each `handle` call gets its own copy.)
            """
        ),
        code(
            """
            request_id = contextvars.ContextVar("request_id", default="-")
            context_log: list[str] = []


            async def child_step() -> None:
                context_log.append(f"  child task sees {request_id.get()}")
                request_id.set("changed-by-child")


            async def handle(new_request_id: str) -> None:
                request_id.set(new_request_id)
                await asyncio.create_task(child_step())
                await asyncio.sleep(0.01)  # let the other request run in between
                context_log.append(f"{new_request_id}: parent still sees {request_id.get()}")


            await asyncio.gather(handle("req-1"), handle("req-2"))
            print("\\n".join(context_log))
            print(f"the cell's own context: {request_id.get()}")
            """
        ),
        md(
            """
            **Log correlation.** A `logging.Filter` copies the current request id onto
            every record, and the formatter prints it. Two requests interleave, yet every
            line is tagged with the right id, without passing ids through function
            arguments. (The handler writes to a `StringIO` so the output is shown here.)
            """
        ),
        code(
            '''
            class RequestIdFilter(logging.Filter):
                """Attach the current request id to every log record."""

                def filter(self, record: logging.LogRecord) -> bool:
                    record.request_id = request_id.get()
                    return True


            log_stream = io.StringIO()
            stream_handler = logging.StreamHandler(log_stream)
            stream_handler.setFormatter(logging.Formatter("%(request_id)-7s %(levelname)s %(message)s"))
            stream_handler.addFilter(RequestIdFilter())
            shop_logger = logging.getLogger("shop.orders.demo")
            shop_logger.handlers[:] = [stream_handler]
            shop_logger.setLevel(logging.INFO)
            shop_logger.propagate = False


            async def handle_order(new_request_id: str, sku: str) -> None:
                token = request_id.set(new_request_id)
                try:
                    shop_logger.info("checking stock for %s", sku)
                    await asyncio.sleep(0.01)
                    shop_logger.info("reserved %s", sku)
                finally:
                    request_id.reset(token)


            await asyncio.gather(handle_order("req-a1", "chai"), handle_order("req-b2", "vada"))
            print(log_stream.getvalue().rstrip())
            '''
        ),
        md(
            """
            **Contexts and threads.** `asyncio.to_thread` runs the function inside a copy
            of the caller's context; `loop.run_in_executor` does not, so the worker sees
            the default value. Fix it by passing `contextvars.copy_context().run` as the
            function:
            """
        ),
        code(
            '''
            def audit_entry() -> str:
                """Runs in a worker thread and reads the request id."""
                return f"audit for {request_id.get()} on {threading.current_thread().name.split('_')[0]}"


            token = request_id.set("req-77")
            try:
                print(f"to_thread:                 {await asyncio.to_thread(audit_entry)}")
                print(f"run_in_executor:           {await KERNEL_LOOP.run_in_executor(None, audit_entry)}")
                snapshot = contextvars.copy_context()
                in_snapshot = await KERNEL_LOOP.run_in_executor(None, snapshot.run, audit_entry)
                print(f"run_in_executor + ctx.run: {in_snapshot}")
            finally:
                request_id.reset(token)
            '''
        ),
    ]


def _http_client_cells() -> list[NotebookNode]:
    """5.4.8 HTTP clients."""
    return [
        md(
            """
            ### 5.4.8 HTTP clients

            `httpx.AsyncClient` is the async twin of the `httpx.Client` from Unit 4.6.
            Create **one** client per application (or per upstream service) and share
            it: it keeps a connection pool, so repeated requests reuse TCP connections
            instead of paying a new handshake each time. Always close it, with `async
            with` or `await client.aclose()`.

            Twenty concurrent requests to `/slow?seconds=0.2` through one shared client
            take about 0.2 s. The server's `/connections` counter shows the pool at work:
            the first batch opens connections, the second batch reuses them.
            """
        ),
        code(
            '''
            async def connections_opened(client: httpx.AsyncClient) -> int:
                """Total TCP connections the shop API has accepted so far."""
                return (await client.get("/connections")).json()["connections"]


            async with httpx.AsyncClient(base_url=SHOP_API, timeout=5) as shared_client:
                for batch in ("first batch", "second batch"):
                    before = await connections_opened(shared_client)
                    with Timer(f"{batch}: 20 concurrent requests", report=None) as batch_timer:
                        responses = await asyncio.gather(
                            *(shared_client.get("/slow", params={"seconds": 0.2}) for _ in range(20))
                        )
                    opened = await connections_opened(shared_client) - before
                    statuses = Counter(response.status_code for response in responses)
                    seconds_taken = batch_timer.elapsed_seconds
                    print(
                        f"{batch}: {seconds_taken:.2f} s, statuses {dict(statuses)}, new connections {opened}"
                    )
            '''
        ),
        md(
            """
            **Limits.** `httpx.Limits(max_connections=5)` caps the pool. The other
            requests wait for a free connection, so twenty 0.2 s requests take about
            4 × 0.2 s. That protects the upstream service, the way a semaphore would:
            """
        ),
        code(
            """
            limits = httpx.Limits(max_connections=5, max_keepalive_connections=5)
            async with httpx.AsyncClient(base_url=SHOP_API, timeout=5, limits=limits) as limited_client:
                before = await connections_opened(limited_client)
                with Timer("20 requests through a pool of 5 connections"):
                    await asyncio.gather(
                        *(limited_client.get("/slow", params={"seconds": 0.2}) for _ in range(20))
                    )
                print(f"new connections: {await connections_opened(limited_client) - before}")
            """
        ),
        md(
            """
            **One client per request** is the most common mistake: every request opens
            (and closes) its own connection. Thirty quick `/rates` calls each way:
            """
        ),
        code(
            """
            async def rates_with_new_client() -> int:
                async with httpx.AsyncClient(base_url=SHOP_API) as throwaway_client:
                    return (await throwaway_client.get("/rates")).status_code


            async with httpx.AsyncClient(base_url=SHOP_API) as counter_client:
                before = await connections_opened(counter_client)
                with Timer("30 requests, a new client each", report=None) as per_request_timer:
                    await asyncio.gather(*(rates_with_new_client() for _ in range(30)))
                per_request_connections = await connections_opened(counter_client) - before
                before = await connections_opened(counter_client)
                with Timer("30 requests, one shared client", report=None) as shared_timer:
                    await asyncio.gather(*(counter_client.get("/rates") for _ in range(30)))
                shared_connections = await connections_opened(counter_client) - before
            per_request_ms, shared_ms = (
                per_request_timer.elapsed_seconds * 1000,
                shared_timer.elapsed_seconds * 1000,
            )
            print(f"new client per request: {per_request_ms:6.1f} ms, {per_request_connections} connections")
            print(f"one shared client:      {shared_ms:6.1f} ms, {shared_connections} connections")
            """
        ),
        md(
            """
            **Timeouts.** httpx has four timeouts: `connect`, `read`, `write` and `pool`
            (waiting for a free connection). There is no default *total* timeout, so wrap
            a whole operation in `asyncio.timeout` when you need a deadline:
            """
        ),
        code(
            """
            async with httpx.AsyncClient(
                base_url=SHOP_API, timeout=httpx.Timeout(5.0, read=0.1)
            ) as impatient_client:
                try:
                    await impatient_client.get("/slow", params={"seconds": 0.5})
                except httpx.ReadTimeout as error:
                    print(f"read timeout: {type(error).__name__}")

            one_connection = httpx.Limits(max_connections=1)
            async with httpx.AsyncClient(
                base_url=SHOP_API, timeout=httpx.Timeout(5.0, pool=0.05), limits=one_connection
            ) as tiny_pool:
                hog = asyncio.create_task(tiny_pool.get("/slow", params={"seconds": 0.3}))
                await asyncio.sleep(0.05)  # the hog now holds the only connection
                try:
                    await tiny_pool.get("/rates")
                except httpx.PoolTimeout as error:
                    print(f"pool timeout: {type(error).__name__}")
                await hog

            async with httpx.AsyncClient(base_url=SHOP_API, timeout=5) as client_with_deadline:
                try:
                    async with asyncio.timeout(0.15):  # total deadline for two calls
                        await client_with_deadline.get("/slow", params={"seconds": 0.1})
                        await client_with_deadline.get("/slow", params={"seconds": 0.1})
                except TimeoutError:
                    print("total deadline: TimeoutError from asyncio.timeout")
            """
        ),
        md(
            """
            Status errors are not raised automatically; `raise_for_status()` turns 4xx/5xx
            into `httpx.HTTPStatusError`:
            """
        ),
        code(
            """
            async with httpx.AsyncClient(base_url=SHOP_API) as status_client:
                busy = await status_client.get("/status/503")
                print(f"{busy.status_code=} {busy.is_success=}")
                print(raised_message(busy.raise_for_status).splitlines()[0])
            """
        ),
        md(
            """
            **aiohttp** is the other major async HTTP library (client *and* server; it
            predates httpx). It is not part of this course's dependencies, so the next cell
            runs only if it is installed. The client looks like this:

            ```python
            import aiohttp

            async with aiohttp.ClientSession(base_url=SHOP_API, timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.get("/rates") as response:
                    rates = await response.json()
            ```

            | | httpx | aiohttp |
            | --- | --- | --- |
            | Sync API too | yes (`httpx.Client`) | no |
            | HTTP/2 | yes (`http2=True`) | no |
            | Server | no | yes |
            | Test transport | `MockTransport` | `aioresponses` (third party) |
            """
        ),
        code(
            """
            if HAS_AIOHTTP:
                import aiohttp

                async with aiohttp.ClientSession(
                    base_url=SHOP_API, timeout=aiohttp.ClientTimeout(total=5)
                ) as session:
                    async with session.get("/rates") as aiohttp_response:
                        print(f"aiohttp: {aiohttp_response.status} {await aiohttp_response.json()}")
            else:
                print("aiohttp is not installed (not a course dependency): skipping the live demo")
            """
        ),
    ]


def _rate_limit_cells() -> list[NotebookNode]:
    """5.4.9 Rate limiting and retries."""
    return [
        md(
            """
            ### 5.4.9 Rate limiting and retries

            **Token bucket.** A bucket holds up to `capacity` tokens and refills at
            `rate` tokens per second; each request takes one token and waits when the
            bucket is empty. Bursts up to `capacity` go through at once, then requests are
            spaced `1 / rate` apart. (Unit 1.6.14's `allow_request` is a sliding-window
            *check* that rejects; a token bucket *waits*.) The lock makes waiters queue
            up fairly instead of all waking at once:
            """
        ),
        code(
            '''
            class AsyncTokenBucket:
                """Allow `rate` acquisitions per second on average, bursts up to `capacity`."""

                def __init__(self, rate: float, capacity: int) -> None:
                    self.rate, self.capacity = rate, capacity
                    self.tokens = float(capacity)
                    self.updated = KERNEL_LOOP.time()
                    self.lock = asyncio.Lock()

                async def acquire(self) -> None:
                    async with self.lock:
                        while True:
                            now = KERNEL_LOOP.time()
                            self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                            self.updated = now
                            if self.tokens >= 1:
                                self.tokens -= 1
                                return
                            await asyncio.sleep((1 - self.tokens) / self.rate)
            '''
        ),
        md(
            """
            Fifteen requests to the shop API at 50 per second with a burst of 5: the
            first five start immediately, the rest about 20 ms apart:
            """
        ),
        code(
            """
            bucket = AsyncTokenBucket(rate=50, capacity=5)
            bucket_start = KERNEL_LOOP.time()
            start_times_ms: list[int] = []


            async def rate_limited_get(client: httpx.AsyncClient) -> int:
                await bucket.acquire()
                start_times_ms.append(round((KERNEL_LOOP.time() - bucket_start) * 1000))
                return (await client.get("/rates")).status_code


            async with httpx.AsyncClient(base_url=SHOP_API) as limited:
                statuses = await asyncio.gather(*(rate_limited_get(limited) for _ in range(15)))
            gaps_after_burst = [later - earlier for earlier, later in itertools.pairwise(start_times_ms[4:])]
            print(f"start times (ms): {start_times_ms}")
            average_gap = sum(gaps_after_burst) / len(gaps_after_burst)
            print(f"{len(statuses)} requests; after the burst, one every {average_gap:.1f} ms (limit 20 ms)")
            """
        ),
        md(
            """
            **Backoff with jitter.** Retrying immediately hammers a struggling service.
            *Exponential backoff* doubles the wait each attempt (capped); *jitter*
            randomizes it so that a thousand clients that failed together do not all retry
            at the same instant (AWS Architecture Blog, "Exponential Backoff and Jitter"):

            | Strategy | Delay before retry *n* (base *b*, cap *c*) |
            | --- | --- |
            | exponential | `min(c, b * 2**n)` |
            | full jitter | `uniform(0, min(c, b * 2**n))` |
            | equal jitter | half of the exponential delay + `uniform(0, half)` |
            """
        ),
        code(
            '''
            def backoff_delay(
                attempt: int, strategy: str, rng: random.Random, base: float = 0.1, cap: float = 2.0
            ) -> float:
                """Delay in seconds before retry number `attempt` (0-based)."""
                exponential = min(cap, base * 2**attempt)
                match strategy:
                    case "exponential":
                        return exponential
                    case "full jitter":
                        return rng.uniform(0, exponential)
                    case "equal jitter":
                        return exponential / 2 + rng.uniform(0, exponential / 2)
                raise ValueError(f"unknown strategy {strategy!r}")


            backoff_rng = random.Random(42)  # seeded: the table is the same on every run
            print(
                f"{'attempt':<8}"
                + "".join(f"{strategy:>14}" for strategy in ("exponential", "full jitter", "equal jitter"))
            )
            for attempt in range(6):
                delays = [
                    backoff_delay(attempt, strategy, backoff_rng)
                    for strategy in ("exponential", "full jitter", "equal jitter")
                ]
                print(f"{attempt:<8}" + "".join(f"{delay:>13.3f}s" for delay in delays))
            '''
        ),
        md(
            """
            A retry loop with full jitter against the flaky endpoint, which answers 503
            twice and then 200. Only 503 (and connection errors) are retried; a 404
            would be returned at once. Lab 5.4 exercise 3 turns this into a reusable
            decorator.
            """
        ),
        code(
            '''
            async def fetch_flaky_with_retries(
                client: httpx.AsyncClient, key: str, attempts: int = 4
            ) -> dict[str, object]:
                """GET /flaky/<key>?fail=2, retrying 503s with full-jitter backoff."""
                retry_rng = random.Random(7)
                for attempt in range(attempts):
                    try:
                        response = await client.get(f"/flaky/{key}", params={"fail": 2})
                        if response.status_code != 503:
                            response.raise_for_status()
                            return response.json()
                        reason = "503"
                    except httpx.TransportError as error:
                        reason = type(error).__name__
                    delay = backoff_delay(attempt, "full jitter", retry_rng, base=0.02)
                    print(f"  attempt {attempt + 1}: {reason}, retrying in {delay * 1000:.0f} ms")
                    await asyncio.sleep(delay)
                raise RuntimeError(f"gave up after {attempts} attempts")


            async with httpx.AsyncClient(base_url=SHOP_API) as retry_client:
                await retry_client.get("/reset")  # clear the server's attempt counters
                print(await fetch_flaky_with_retries(retry_client, "unit54-retry"))
            '''
        ),
        md(
            """
            `tenacity` (Unit 4.6) supports async code too: `AsyncRetrying` in an
            `async for` loop, or the `@retry` decorator on an `async def`:
            """
        ),
        code(
            """
            if HAS_TENACITY:
                from tenacity import (
                    AsyncRetrying,
                    retry_if_exception_type,
                    stop_after_attempt,
                    wait_random_exponential,
                )

                async with httpx.AsyncClient(base_url=SHOP_API) as tenacity_client:
                    await tenacity_client.get("/reset")
                    retrying = AsyncRetrying(
                        stop=stop_after_attempt(5),
                        wait=wait_random_exponential(multiplier=0.01, max=0.1),
                        retry=retry_if_exception_type(httpx.HTTPStatusError),
                        reraise=True,
                    )
                    async for attempt in retrying:
                        with attempt:
                            flaky_response = await tenacity_client.get(
                                "/flaky/unit54-tenacity", params={"fail": 2}
                            )
                            flaky_response.raise_for_status()
                attempt_number = attempt.retry_state.attempt_number
                print(f"tenacity: succeeded on attempt {attempt_number}: {flaky_response.json()}")
            else:
                print("tenacity is not installed: skipping")
            """
        ),
    ]


UVLOOP_BENCHMARK = """
import asyncio
import os
import time

DEMO_SCALE = int(os.environ.get("PHASE5_DEMO_SCALE", "1"))
ROUND_TRIPS = 5_000 * DEMO_SCALE
TASKS = 50_000 * DEMO_SCALE


async def echo(reader, writer):
    while line := await reader.readline():
        writer.write(line)
        await writer.drain()
    writer.close()


async def round_trips():
    server = await asyncio.start_server(echo, "127.0.0.1", 0)
    reader, writer = await asyncio.open_connection("127.0.0.1", server.sockets[0].getsockname()[1])
    started = time.perf_counter()
    for _ in range(ROUND_TRIPS):
        writer.write(b"ping\\n")
        await reader.readline()
    elapsed = time.perf_counter() - started
    writer.close()
    await writer.wait_closed()
    server.close()
    await server.wait_closed()
    return elapsed


async def many_tasks():
    started = time.perf_counter()
    await asyncio.gather(*(asyncio.sleep(0) for _ in range(TASKS)))
    return time.perf_counter() - started


def bench(loop_factory):
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        return runner.run(round_trips()), runner.run(many_tasks())


try:
    import uvloop
except ImportError:
    uvloop = None
results = {"asyncio (default loop)": bench(None)}
if uvloop is not None:
    results[f"uvloop {uvloop.__version__}"] = bench(uvloop.new_event_loop)
print(f"{ROUND_TRIPS} TCP round trips and {TASKS} tasks on each loop:")
for label, (echo_seconds, task_seconds) in results.items():
    print(f"  {label:<23} round trips {echo_seconds:.3f} s | tasks {task_seconds:.3f} s")
if len(results) == 2:
    (echo_a, task_a), (echo_b, task_b) = results.values()
    print(f"uvloop speedup: round trips {echo_a / echo_b:.1f}x, tasks {task_a / task_b:.1f}x")
"""

ASYNC_TEST_FILE = '''
"""Async tests run by pytest with anyio's plugin (bundled with anyio)."""

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

pytestmark = pytest.mark.anyio  # run every test in this module on an event loop


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"  # "trio" also works if trio is installed


async def fetch_rate(client: httpx.AsyncClient, currency: str) -> float:
    response = await client.get("/rates")
    response.raise_for_status()
    return response.json()["rates"][currency]


def rates_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"rates": {"USD": 0.01}})


async def test_fetch_rate_with_mock_transport() -> None:
    transport = httpx.MockTransport(rates_ok)
    async with httpx.AsyncClient(transport=transport, base_url="https://shop.test") as client:
        assert await fetch_rate(client, "USD") == 0.01


async def test_server_error_raises() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    async with httpx.AsyncClient(transport=transport, base_url="https://shop.test") as client:
        with pytest.raises(httpx.HTTPStatusError):
            await fetch_rate(client, "USD")


async def test_gateway_is_awaited_once() -> None:
    gateway = AsyncMock()
    gateway.charge.return_value = "ok"
    assert await gateway.charge(250, currency="INR") == "ok"
    gateway.charge.assert_awaited_once_with(250, currency="INR")


async def test_slow_call_times_out() -> None:
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.01):
            await asyncio.sleep(1)
'''

PYTEST_ASYNCIO_TEST_FILE = '''
"""The same idea with pytest-asyncio's marker."""

import asyncio

import pytest


@pytest.mark.asyncio
async def test_sleep_returns_result() -> None:
    assert await asyncio.sleep(0, result="done") == "done"
'''


def _testing_cells() -> list[NotebookNode]:
    """5.4.10 Performance and testing."""
    return [
        md(
            """
            ### 5.4.10 Performance and testing

            **uvloop** replaces asyncio's pure-Python loop with one built on libuv, the
            same C library Node uses, written in Cython. It is a drop-in loop
            implementation: `uvloop.run(main())`, or `asyncio.run(main(),
            loop_factory=uvloop.new_event_loop)` (`loop_factory` is *new in 3.12*; the
            older `uvloop.install()` / event-loop policies are deprecated). It speeds up
            the loop's own overhead (I/O callbacks, transports), not your Python code. It
            does not support Windows.

            The benchmark runs in a child process: TCP echo round trips over loopback and
            many short tasks, on each loop. Timings vary; read the ratio. First the
            script:
            """
        ),
        code(f'UVLOOP_BENCHMARK_SOURCE = r"""\n{UVLOOP_BENCHMARK.strip()}\n"""'),
        md("Run it (or skip it where uvloop is unavailable):"),
        code(
            """
            if HAS_UVLOOP:
                print(run_child(UVLOOP_BENCHMARK_SOURCE))
            else:
                reason = (
                    "not supported on Windows" if sys.platform == "win32" else "not installed (uv add uvloop)"
                )
                print(f"uvloop {reason}: skipping the benchmark")
            """
        ),
        md(
            """
            **`AsyncMock`** (*new in 3.8*) is a mock whose calls return awaitables. It
            records awaits as well as calls (`assert_awaited_once_with`, `await_count`),
            and `side_effect` can raise:
            """
        ),
        code(
            """
            async def checkout_with(gateway: Any, amount: int) -> str:
                result = await gateway.charge(amount=amount, currency="INR")
                return result["status"]


            payment_gateway = AsyncMock()
            payment_gateway.charge.return_value = {"status": "ok", "txn": "T-1"}
            print(f"{await checkout_with(payment_gateway, 250)=}")
            payment_gateway.charge.assert_awaited_once_with(amount=250, currency="INR")
            print(
                f"{payment_gateway.charge.await_count=} {inspect.iscoroutinefunction(payment_gateway.charge)=}"
            )
            payment_gateway.charge.side_effect = ConnectionError("gateway down")
            try:
                await checkout_with(payment_gateway, 99)
            except ConnectionError as error:
                print(f"side_effect raised {type(error).__name__}: {error}")
            """
        ),
        md(
            """
            **`httpx.MockTransport`** swaps the network for a function (sync or async)
            that receives the `Request` and returns a `Response`. The client code under
            test is unchanged; nothing leaves the process (the `shop.test` host is never
            resolved):
            """
        ),
        code(
            """
            seen_paths: list[str] = []


            async def fake_shop(request: httpx.Request) -> httpx.Response:
                seen_paths.append(request.url.path)
                if request.url.path == "/rates":
                    return httpx.Response(200, json={"rates": {"USD": 0.012}})
                return httpx.Response(404, json={"error": "no route"})


            async with httpx.AsyncClient(
                transport=httpx.MockTransport(fake_shop), base_url="https://shop.test"
            ) as mocked_client:
                rates_reply, missing_reply = await asyncio.gather(
                    mocked_client.get("/rates"), mocked_client.get("/nope")
                )
            print(f"{rates_reply.json()=} {missing_reply.status_code=} {seen_paths=}")
            """
        ),
        md(
            """
            **pytest and async tests.** A test function that is `async def` needs a
            plugin to run it on an event loop:

            | Plugin | Marker | Notes |
            | --- | --- | --- |
            | anyio (bundled with the `anyio` package, which httpx depends on) | `@pytest.mark.anyio` + an `anyio_backend` fixture | runs on asyncio or trio |
            | pytest-asyncio | `@pytest.mark.asyncio` (or `asyncio_mode = "auto"`) | asyncio only; not a course dependency |

            The test module below uses anyio's plugin, `AsyncMock`, `MockTransport` and a
            timeout:
            """
        ),
        code(f"ASYNC_TEST_SOURCE = r'''\n{ASYNC_TEST_FILE.strip()}\n'''"),
        md(
            """
            The next cell writes it to a scratch folder with its own `pytest.ini` (so the
            repository's settings do not apply) and runs pytest in a child process:
            """
        ),
        code(
            """
            async_test_dir = PHASE5_DIR / "async_tests"
            async_test_dir.mkdir(exist_ok=True)
            pytest_ini = "[pytest]\\naddopts = -p no:cacheprovider\\n"
            (async_test_dir / "pytest.ini").write_text(pytest_ini, encoding="utf-8")
            test_module = textwrap.dedent(ASYNC_TEST_SOURCE).lstrip()
            (async_test_dir / "test_async_shop.py").write_text(test_module, encoding="utf-8")
            pytest_run = subprocess.run(
                [sys.executable, "-m", "pytest", "-v", "--no-header", "test_async_shop.py"],
                capture_output=True, text=True, cwd=async_test_dir, env=CHILD_ENV, timeout=120,
            )  # fmt: skip
            print(re.sub(r"in [\\d.]+s", "in <time>", pytest_run.stdout.strip()))
            """
        ),
        md(
            """
            With pytest-asyncio installed, the `@pytest.mark.asyncio` form runs the same
            way (otherwise the cell prints a skip message):
            """
        ),
        code(f"PYTEST_ASYNCIO_SOURCE = r'''\n{PYTEST_ASYNCIO_TEST_FILE.strip()}\n'''"),
        md("Run it if the plugin is installed:"),
        code(
            """
            if HAS_PYTEST_ASYNCIO:
                marker_module = textwrap.dedent(PYTEST_ASYNCIO_SOURCE).lstrip()
                (async_test_dir / "test_pytest_asyncio.py").write_text(marker_module, encoding="utf-8")
                pytest_asyncio_run = subprocess.run(
                    [sys.executable, "-m", "pytest", "-q", "test_pytest_asyncio.py"],
                    capture_output=True, text=True, cwd=async_test_dir, env=CHILD_ENV, timeout=120,
                )  # fmt: skip
                print(re.sub(r"in [\\d.]+s", "in <time>", pytest_asyncio_run.stdout.strip()))
            else:
                print("pytest-asyncio is not installed (not a course dependency): skipping")
            """
        ),
    ]


def _interop_cells() -> list[NotebookNode]:
    """5.4.11 Interop."""
    return [
        md(
            """
            ### 5.4.11 Interop

            **Threads → loop.** asyncio objects are not thread-safe; from another
            thread, talk to a loop only through:

            | Call (from another thread) | Effect |
            | --- | --- |
            | `asyncio.run_coroutine_threadsafe(coro, loop)` | runs `coro` on the loop; returns a `concurrent.futures.Future` to block on |
            | `loop.call_soon_threadsafe(callback, *args)` | queues a callback and wakes the loop (through its self-pipe) |
            | `asyncio.wrap_future(concurrent_future)` | the other direction: await a thread-pool Future from async code |

            Three "legacy" worker threads each ask the loop to reserve stock and block on
            the answer, while the loop awaits the threads' futures:
            """
        ),
        code(
            '''
            async def reserve_stock(sku: str) -> str:
                await asyncio.sleep(0.01)
                return f"{sku} reserved on {threading.current_thread().name}"


            def legacy_worker(sku: str, loop: asyncio.AbstractEventLoop) -> str:
                """Sync code in a worker thread: submit to the loop, block for the result."""
                return asyncio.run_coroutine_threadsafe(reserve_stock(sku), loop).result(timeout=2)


            with concurrent.futures.ThreadPoolExecutor(
                max_workers=3, thread_name_prefix="legacy"
            ) as legacy_pool:
                thread_futures = [
                    legacy_pool.submit(legacy_worker, sku, KERNEL_LOOP) for sku in ("chai", "vada", "idli")
                ]
                print(await asyncio.gather(*(asyncio.wrap_future(future) for future in thread_futures)))
            '''
        ),
        md(
            """
            `call_soon_threadsafe` feeding an `asyncio.Queue` from a sensor thread. Calling
            `put_nowait` directly from the thread would be a race (and would not wake a
            loop sleeping in `select`):
            """
        ),
        code(
            """
            readings: asyncio.Queue[float] = asyncio.Queue()


            def sensor_thread(loop: asyncio.AbstractEventLoop) -> None:
                for temperature in (21.5, 22.0, 22.4):
                    time.sleep(0.01)
                    loop.call_soon_threadsafe(readings.put_nowait, temperature)
                loop.call_soon_threadsafe(readings.shutdown)


            threading.Thread(target=sensor_thread, args=(KERNEL_LOOP,), daemon=True).start()
            received_readings: list[float] = []
            try:
                while True:
                    received_readings.append(await readings.get())
            except asyncio.QueueShutDown:
                print(f"readings from the thread: {received_readings}")
            """
        ),
        md(
            """
            **anyio and trio.** *Trio* is an alternative async library built around
            structured concurrency from the start (nurseries, cancel scopes); its ideas
            gave asyncio `TaskGroup` and `timeout`. Trio and asyncio do not interoperate
            directly. *anyio* is a compatibility layer with trio-style APIs that runs on
            either: libraries written against anyio (httpx, Starlette, FastAPI in
            Phase 6) work on both. Inside the kernel, anyio code runs on the asyncio loop:
            """
        ),
        code(
            """
            if HAS_ANYIO:
                import anyio

                anyio_log: list[str] = []

                async def anyio_job(name: str, seconds: float) -> None:
                    await anyio.sleep(seconds)
                    anyio_log.append(name)

                async with anyio.create_task_group() as task_group:  # like asyncio.TaskGroup
                    task_group.start_soon(anyio_job, "slow", 0.02)
                    task_group.start_soon(anyio_job, "fast", 0.01)
                with anyio.move_on_after(0.01) as cancel_scope:  # a timeout that does not raise
                    await anyio.sleep(1)
                print(f"{anyio_log=} {cancel_scope.cancelled_caught=}")
                print(f"anyio.to_thread.run_sync: {await anyio.to_thread.run_sync(sum, [1, 2, 3])}")
            else:
                print("anyio is not installed: skipping")
            """
        ),
        md(
            """
            `anyio.run(main, backend=...)` is the entry point, like `asyncio.run`. The same
            `main` runs on asyncio, and on trio when trio is installed (it is not a course
            dependency, so the trio line prints a skip message here):
            """
        ),
        code(
            '''
            print(
                run_child(
                    """
                    import importlib.util

                    import anyio


                    async def main():
                        async with anyio.create_task_group() as group:
                            for delay in (0.02, 0.01):
                                group.start_soon(anyio.sleep, delay)
                        return anyio.get_current_task().name


                    for backend in ("asyncio", "trio"):
                        if backend == "trio" and importlib.util.find_spec("trio") is None:
                            print("trio:    not installed, skipping")
                            continue
                        main_task_name = anyio.run(main, backend=backend)
                        print(f"{backend + ':':<8} anyio.run finished, main task {main_task_name!r}")
                    """
                )
                if HAS_ANYIO
                else "anyio is not installed: skipping"
            )
            '''
        ),
    ]


def _predict_cells() -> list[NotebookNode]:
    """Predict-the-output questions for Unit 5.4."""
    return [
        md("#### Predict the output"),
        *predict_cells(
            """
            async def worker():
                try:
                    await asyncio.sleep(1)
                except Exception:
                    print("caught")
                finally:
                    print("finally")

            task = asyncio.create_task(worker())
            await asyncio.sleep(0)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                print("cancelled")
            """,
            """
            `finally`, then `cancelled`. `CancelledError` derives from `BaseException`
            (since Python 3.8), so `except Exception` does not catch it; `finally` runs,
            the error propagates out of the task, and awaiting the task re-raises it.
            """,
            """
            async def worker() -> None:
                try:
                    await asyncio.sleep(1)
                except Exception:
                    print("caught")
                finally:
                    print("finally")


            predict_task = asyncio.create_task(worker())
            await asyncio.sleep(0)
            predict_task.cancel()
            try:
                await predict_task
            except asyncio.CancelledError:
                print("cancelled")
            """,
        ),
        *predict_cells(
            """
            async def steady():
                try:
                    await asyncio.sleep(1)
                except asyncio.CancelledError:
                    print("steady cancelled")
                    raise

            async def broken():
                await asyncio.sleep(0.01)
                raise KeyError("sku-404")

            try:
                async with asyncio.TaskGroup() as group:
                    group.create_task(steady())
                    group.create_task(broken())
            except* KeyError as errors:
                print(type(errors).__name__, len(errors.exceptions))
            """,
            """
            `steady cancelled`, then `ExceptionGroup 1`. When `broken` fails, the group
            cancels `steady`, waits for it, and raises an `ExceptionGroup` containing the
            one `KeyError`. `except*` binds the matching *group*, not the bare `KeyError`.
            """,
            """
            async def steady() -> None:
                try:
                    await asyncio.sleep(1)
                except asyncio.CancelledError:
                    print("steady cancelled")
                    raise


            async def broken() -> None:
                await asyncio.sleep(0.01)
                raise KeyError("sku-404")


            try:
                async with asyncio.TaskGroup() as group:
                    group.create_task(steady())
                    group.create_task(broken())
            except* KeyError as errors:
                print(type(errors).__name__, len(errors.exceptions))
            """,
        ),
        *predict_cells(
            """
            colour = contextvars.ContextVar("colour", default="outer")

            async def paint():
                colour.set("painted")

            async def main():
                await asyncio.create_task(paint())
                print(colour.get())
                await paint()
                print(colour.get())

            await asyncio.create_task(main())
            """,
            """
            `outer`, then `painted`. A Task runs in a *copy* of the context, so the first
            `paint()` (a separate task) changes only its copy. Awaiting `paint()`
            directly runs it inside `main`'s own task and context, so the second
            `set()` is visible to `main`. (`main` itself runs as a task so that the
            kernel's context stays untouched.)
            """,
            """
            colour = contextvars.ContextVar("colour", default="outer")


            async def paint() -> None:
                colour.set("painted")


            async def main() -> None:
                await asyncio.create_task(paint())
                print(colour.get())
                await paint()
                print(colour.get())


            await asyncio.create_task(main())
            """,
        ),
    ]


LAB_SETUP_SOURCE = r'''
from collections.abc import Awaitable


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
            before = KERNEL_LOOP.time()
            await asyncio.sleep(interval)
            worst[0] = max(worst[0], KERNEL_LOOP.time() - before - interval)

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


print("Lab 5.4 helpers ready: outcome, quiet_unawaited, InFlightTracker, mock_client,")
print("loop_lag_during, scenario_field")
'''


def _lab_cells_part_1() -> list[NotebookNode]:
    """Lab 5.4 exercises 1-3."""
    return [
        md(
            """
            ### Lab 5.4

            Seven exercises. All HTTP goes through `httpx.MockTransport` handlers (no
            network). Replace each `raise NotImplementedError`, then run the check cell;
            until then the checks print FAIL, which is expected.
            """
        ),
        code(LAB_SETUP_SOURCE),
        md(
            """
            #### Exercise 1 — `fetch_all(urls, max_concurrency)`

            Write `fetch_all(client, urls, max_concurrency)`. It GETs every URL with the
            shared `client`, with **at most `max_concurrency` requests in flight**, and
            returns a list **in input order**. Each element is the parsed JSON body of a
            successful response, or the class name of the error otherwise: call
            `response.raise_for_status()`, so a 500 becomes `"HTTPStatusError"` and a
            refused connection `"ConnectError"`. It never raises for a single failed URL.
            """
        ),
        code(
            '''
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
            '''
        ),
        md("Your solution:"),
        code(
            '''
            async def fetch_all(
                client: httpx.AsyncClient, urls: list[str], max_concurrency: int
            ) -> list[object]:
                """GET every URL, at most max_concurrency at a time; JSON or error name, in input order."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 1:"),
        code(
            """
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
            """
        ),
        md(
            """
            #### Exercise 2 — an async worker pool with graceful shutdown

            Complete `WorkerPool`, which runs the async function `job` over submitted
            items with `worker_count` worker tasks fed by a bounded `asyncio.Queue`:

            - `await pool.start()` starts the workers and stores them in `pool.workers`;
            - `await pool.submit(item)` queues an item (it waits while the queue is
              full: backpressure) and raises `RuntimeError` after shutdown has begun;
            - `await pool.shutdown()` stops accepting items, lets the workers finish
              **everything already queued**, waits for every worker to exit, and returns
              `{item: result}`, where a job that raised maps to the exception's class
              name;
            - `await pool.shutdown(immediate=True)` drops the queued items, cancels the
              jobs in progress, waits for the workers, and returns what had finished.

            `Queue.shutdown()` (5.4.4) does most of the work.
            """
        ),
        md("Your solution:"),
        code(
            '''
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

                async def start(self) -> None:
                    raise NotImplementedError

                async def submit(self, item: Any) -> None:
                    raise NotImplementedError

                async def shutdown(self, immediate: bool = False) -> dict[Any, object]:
                    raise NotImplementedError
            '''
        ),
        md("Check exercise 2:"),
        code(
            """
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
                return {"finished": len(results), "all_exited": all(worker.done() for worker in pool.workers)}


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
                        lambda: (scenario_field(graceful, "workers"), scenario_field(graceful, "all_exited")),
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
            """
        ),
        md(
            """
            #### Exercise 3 — `retry_async`

            Write the decorator factory `retry_async(...)` for async functions. The
            decorated function is called at most `attempts` times in total. An exception
            that is an instance of `retry_on` triggers a retry; before retry *n* (n = 1,
            2, …) it awaits `sleep(delay)` with the **full-jitter** delay
            `rng.uniform(0, min(max_delay, base_delay * 2 ** (n - 1)))` (use
            `random.Random()` when `rng` is `None`). When the attempts run out, the last
            exception is re-raised. Other exceptions are raised at once, never retried.
            Keep the function's name and docstring (`functools.wraps`). `sleep` is a
            parameter so tests can record delays instead of waiting.
            """
        ),
        code(
            '''
            RETRY_CALLS: list[str] = []


            async def flaky_inventory_call(
                fail_times: int, error_type: type[Exception] = ConnectionError
            ) -> str:
                """Fails fail_times times with error_type, then succeeds."""
                RETRY_CALLS.append(error_type.__name__)
                if len(RETRY_CALLS) <= fail_times:
                    raise error_type(f"attempt {len(RETRY_CALLS)} failed")
                return f"ok after {len(RETRY_CALLS)} calls"
            '''
        ),
        md("Your solution:"),
        code(
            '''
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
                raise NotImplementedError
            '''
        ),
        md("Check exercise 3:"),
        code(
            """
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
                    ("capped delays (3 sleeps)", lambda: scenario_field(gives_up, "sleeps"), expected_delays),
                    (
                        "other errors are not retried",
                        lambda: (scenario_field(not_retried, "result"), scenario_field(not_retried, "calls")),
                        ("raised KeyError", 1),
                    ),
                    (
                        "keeps the name",
                        lambda: retry_async()(flaky_inventory_call).__name__,
                        "flaky_inventory_call",
                    ),
                ]
            )
            """
        ),
    ]


def _lab_cells_part_2() -> list[NotebookNode]:
    """Lab 5.4 exercises 4-7."""
    return [
        md(
            """
            #### Exercise 4 — an async paginator

            Write the async generator `paginate(client, path, page_size=10)`. The endpoint
            is cursor-paginated: `GET path?limit=<page_size>` returns
            `{"items": [...], "next_cursor": "<cursor>" or null}`; the next page is
            `GET path?limit=<page_size>&cursor=<cursor>`. Yield the items one by one,
            and fetch a page only when the caller asks for an item beyond the current one
            (a caller that stops after 12 items must cause only 2 requests).
            """
        ),
        code(
            '''
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
            '''
        ),
        md("Your solution:"),
        code(
            '''
            async def paginate(
                client: httpx.AsyncClient, path: str, page_size: int = 10
            ) -> AsyncIterator[dict[str, Any]]:
                """Yield every item of a cursor-paginated endpoint, fetching pages lazily."""
                raise NotImplementedError
                yield  # the yield makes this an async generator
            '''
        ),
        md("Check exercise 4:"),
        code(
            """
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
            """
        ),
        md(
            """
            #### Exercise 5 — find a hidden blocking call

            Each handler set below contains exactly one handler that blocks the event
            loop somewhere deep inside (and one that is slow but harmless: slow is not
            the same as blocking). Write `find_blocking_handler(handlers, threshold)`,
            which runs each handler and returns the name of the one that blocks the loop
            for longer than `threshold` seconds. Use the tools from 5.4.6:
            `loop_lag_during` (a lag monitor, in the lab setup) or `slow_callback_report`
            (debug mode). Then write `render_invoice_fixed()`, which returns the same
            value as `render_invoice()` without blocking the loop. Do not read the
            source to find the culprit; measure it.
            """
        ),
        code(
            """
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
            """
        ),
        md("Your solution:"),
        code(
            '''
            async def find_blocking_handler(
                handlers: dict[str, Callable[[], Awaitable[object]]], threshold: float = 0.05
            ) -> str:
                """Name of the handler that blocks the event loop for longer than threshold seconds."""
                raise NotImplementedError


            async def render_invoice_fixed() -> dict[str, object]:
                """Same result as render_invoice(), without blocking the loop."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 5:"),
        code(
            """
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
            """
        ),
        md(
            """
            #### Exercise 6 — request-ID propagation with `contextvars`

            Two pieces:

            1. `make_traced_client(transport)` returns an `httpx.AsyncClient` (base URL
               `https://api.shop.test`) with a **request event hook** (an `async`
               function in `event_hooks={"request": [...]}`) that sets the header
               `X-Request-ID` to `REQUEST_ID.get()` on every outgoing request.
            2. `handle_request(client, path, request_id=None)` sets `REQUEST_ID` to
               `request_id` (or to a new `uuid.uuid4().hex[:8]` when it is `None`) **for
               this request only** (reset it before returning); logs `"start {path}"` and
               `"done {path}"` with `request_log.info`; GETs `path`; runs
               `audit_trail(path)` in a worker thread with `asyncio.to_thread`; and returns
               `{"request_id": ..., "echoed": <the "x-request-id" field of the JSON
               reply>, "audit": <what audit_trail returned>}`.

            The log handler records the request id current at each log call, so correct
            propagation is visible in `request_records`.
            """
        ),
        code(
            '''
            import uuid  # noqa: F401 (for your solution)

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
            '''
        ),
        md("Your solution:"),
        code(
            '''
            def make_traced_client(transport: httpx.AsyncBaseTransport) -> httpx.AsyncClient:
                """AsyncClient whose request hook adds X-Request-ID from REQUEST_ID."""
                raise NotImplementedError


            async def handle_request(
                client: httpx.AsyncClient, path: str, request_id: str | None = None
            ) -> dict[str, str]:
                """Serve one request with REQUEST_ID set; return request_id, echoed header and audit value."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 6:"),
        code(
            """
            async def request_id_scenario() -> dict[str, object]:
                request_records.clear()
                async with make_traced_client(httpx.MockTransport(echo_request_id_api)) as traced_client:
                    many = await asyncio.gather(
                        *(handle_request(traced_client, f"/orders/{n}", f"req-{n:02d}") for n in range(20))
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
                tagged = [(rid, message) for rid, message in records if "/orders/new" not in message]
                return len(records) == 42 and all(
                    rid == f"req-{message.rsplit('/', 1)[1]:0>2}" for rid, message in tagged
                )


            traced = await outcome(request_id_scenario())
            run_checks(
                [
                    (
                        "header carries each request's id",
                        lambda: [reply["echoed"] for reply in scenario_field(traced, "many")],
                        [f"req-{n:02d}" for n in range(20)],
                    ),
                    (
                        "worker thread sees the id",
                        lambda: all(
                            reply["audit"] == reply["request_id"] for reply in scenario_field(traced, "many")
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
            """
        ),
        md(
            """
            #### Exercise 7 — an API aggregator over 500 mocked endpoints

            Write `aggregate_sales(client, store_ids, max_concurrency=50, timeout=0.2)`.
            For every store it GETs `/stores/<id>/sales` (JSON `{"store": id, "amount":
            n}`), with at most `max_concurrency` requests in flight and each attempt
            limited to `timeout` seconds. Use `asyncio.timeout`: `MockTransport`
            ignores httpx's own timeouts. A `503` is retried **once**; any other error
            status, a timeout or a transport error marks the store as failed. Return
            `{"total": <sum of amounts of the successful stores>, "ok": <their count>,
            "failed": <sorted list of failed store ids>}`.
            """
        ),
        code(
            '''
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
            '''
        ),
        md("Your solution:"),
        code(
            '''
            async def aggregate_sales(
                client: httpx.AsyncClient, store_ids: list[int], max_concurrency: int = 50, timeout: float = 0.2
            ) -> dict[str, object]:
                """Fetch every store's sales concurrently; return total, ok count and failed ids."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 7:"),
        code(
            """
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
            """
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 5.4."""
    return [
        md(
            """
            ### Recap — Unit 5.4

            | Concept | One-line takeaway | JS / Node equivalent |
            | --- | --- | --- |
            | Structured concurrency | `TaskGroup`: children never outlive the block; one failure cancels the rest; `ExceptionGroup` + `except*` | `Promise.all` + manual `AbortController` |
            | Timeouts and cancellation | `asyncio.timeout` / `timeout_at`; `CancelledError` is a `BaseException`: clean up, re-raise; `shield` for must-finish steps | `AbortSignal.timeout` |
            | Coordination | `Event`, `Lock` (only around read-await-write), `Condition`, `Semaphore`, `Barrier`; not thread-safe | `p-limit`, hand-rolled |
            | Queues and pools | bounded `Queue` = backpressure; `Queue.shutdown()` (3.13) for clean exits; pipelines pass shutdown downstream | streams with `highWaterMark` |
            | Async protocols | `async with`, `@asynccontextmanager`, `async for`, async generators; `aclosing` for early exits | `for await`, `await using` |
            | Blocking the loop | lag monitor, debug mode (`slow_callback_duration`); `to_thread` for I/O, process pool for Python CPU work | `blocked-at`, worker threads |
            | `contextvars` | per-task copies of request state; `to_thread` copies the context, `run_in_executor` does not | `AsyncLocalStorage` |
            | HTTP clients | one shared `httpx.AsyncClient`; `Limits`; connect/read/write/pool timeouts plus `asyncio.timeout` for totals | `undici.Agent` |
            | Rate limiting and retries | token bucket waits; exponential backoff with full jitter; retry only what is retryable | `bottleneck`, `p-retry` |
            | Performance and testing | `uvloop` for loop overhead; pytest + anyio plugin; `AsyncMock`; `httpx.MockTransport` | Jest/Vitest, `nock` |
            | Interop | `run_coroutine_threadsafe`, `call_soon_threadsafe`, `wrap_future`; anyio runs on asyncio and trio | — |

            **Further reading**

            - [`asyncio` task groups, timeouts, shielding](https://docs.python.org/3/library/asyncio-task.html),
              [synchronization primitives](https://docs.python.org/3/library/asyncio-sync.html),
              [queues](https://docs.python.org/3/library/asyncio-queue.html),
              [developing with asyncio (debug mode)](https://docs.python.org/3/library/asyncio-dev.html)
            - [`contextvars`](https://docs.python.org/3/library/contextvars.html),
              [`contextlib` (`asynccontextmanager`, `aclosing`, `AsyncExitStack`)](https://docs.python.org/3/library/contextlib.html),
              [`unittest.mock.AsyncMock`](https://docs.python.org/3/library/unittest.mock.html#unittest.mock.AsyncMock)
            - [PEP 492](https://peps.python.org/pep-0492/) (`async with`, `async for`),
              [PEP 525](https://peps.python.org/pep-0525/) (async generators),
              [PEP 567](https://peps.python.org/pep-0567/) (context variables),
              [PEP 654](https://peps.python.org/pep-0654/) (exception groups and `except*`)
            - [HTTPX async client](https://www.python-httpx.org/async/), [uvloop](https://github.com/MagicStack/uvloop),
              [AnyIO](https://anyio.readthedocs.io/), [Trio](https://trio.readthedocs.io/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 5.4 and Lab 5.4."""
    return [
        *_overview_cells(),
        *_structured_concurrency_cells(),
        *_timeout_cells(),
        *_coordination_cells(),
        *_queue_cells(),
        *_async_protocol_cells(),
        *_blocking_cells(),
        *_contextvar_cells(),
        *_http_client_cells(),
        *_rate_limit_cells(),
        *_testing_cells(),
        *_interop_cells(),
        *_predict_cells(),
        *_lab_cells_part_1(),
        *_lab_cells_part_2(),
        *_recap_cells(),
    ]
